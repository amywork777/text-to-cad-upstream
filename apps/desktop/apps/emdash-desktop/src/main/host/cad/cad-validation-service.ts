import { execFile } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { promisify } from 'node:util';
import type {
  CadParameterApplyResult,
  CadSourceHistoryResult,
  CadValidationResult,
} from '@core/features/browser/api';
import {
  applyCadParameterValues,
  parseCadSourceHistory,
} from '@core/features/cad/api/cad-source-history';
import { verifiedMigratedCadSourceForLegacy } from '@main/host/cad/cad-migration-marker';
import { provisionCadRuntime } from '@main/host/cad/cad-runtime-service';
import { findCadPluginRoot, findCadPythonExecutable } from '@main/host/cad/cad-viewer-service';
import {
  cadSourceRebuildToolPlan as compatibilityCadSourceRebuildToolPlan,
  normalizeCadArtifactRelationship,
  resolveCadBuildArtifactPath,
  resolveCadgenCapability,
  resolveCadSourceArtifactRelationship,
  type CadgenContract,
  type CadRuntimeCommand,
} from '@main/host/cad/cadgen-compatibility';

const execFileAsync = promisify(execFile);
const VALIDATION_TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 5 * 1024 * 1024;
const MAX_SOURCE_BYTES = 2 * 1024 * 1024;
interface CadValidationInFlight {
  revision: string;
  promise: Promise<CadValidationResult>;
}

const validationInFlight = new Map<string, CadValidationInFlight>();
const recentValidation = new Map<string, CadValidationResult>();
const cadArtifactOperationTails = new Map<string, Promise<void>>();
const cadArtifactRebuildCounts = new Map<string, number>();

type CadArtifactTarget =
  | {
      success: true;
      workspacePath: string;
      relativeModelPath: string;
      relativeSourcePath?: string;
    }
  | { success: false; error: string };

export type CadArtifactTargetInput = {
  workspacePath: string;
  filePath: string;
  /** Persisted model-catalog provenance; preferred over upstream cache metadata. */
  sourcePath?: string;
};

export function validateCadModel(input: CadArtifactTargetInput): Promise<CadValidationResult> {
  const key = cadArtifactOperationKey(input);
  const existing = validationInFlight.get(key);
  const requestedRevision = cadValidationInputRevision(input);
  const rebuildQueued = (cadArtifactRebuildCounts.get(key) ?? 0) > 0;
  if (!rebuildQueued && existing?.revision === requestedRevision) return existing.promise;
  const cached = recentValidation.get(key);
  if (!rebuildQueued && cached?.success && cadValidationResultIsCurrent(input, cached)) {
    return Promise.resolve(cached);
  }
  // A prior inspection may still be building derived render metadata. Queue
  // the newer artifact revision behind it rather than sharing stale facts.
  const pending = enqueueCadArtifactOperation(key, () => validateCadModelOnce(input));
  const cleanup = () => {
    if (validationInFlight.get(key)?.promise === pending) validationInFlight.delete(key);
  };
  validationInFlight.set(key, { revision: requestedRevision, promise: pending });
  void pending.then((result) => {
    if (result.success) recentValidation.set(key, result);
    cleanup();
  }, cleanup);
  return pending;
}

/**
 * Explicitly rebuilds an authored Python recipe before inspecting the STEP it
 * produced. Normal open/restart validation must use validateCadModel instead;
 * that path treats the accepted STEP as immutable input and never runs Python.
 */
export function rebuildCadModel(input: {
  workspacePath: string;
  filePath: string;
}): Promise<CadValidationResult> {
  const key = cadArtifactOperationKey(input);
  cadArtifactRebuildCounts.set(key, (cadArtifactRebuildCounts.get(key) ?? 0) + 1);
  return enqueueCadArtifactOperation(key, () => rebuildCadModelOnce(input)).finally(() => {
    const remaining = (cadArtifactRebuildCounts.get(key) ?? 1) - 1;
    if (remaining > 0) cadArtifactRebuildCounts.set(key, remaining);
    else cadArtifactRebuildCounts.delete(key);
  });
}

export function cadArtifactOperationKey(input: CadArtifactTargetInput): string {
  const workspacePath = resolve(input.workspacePath);
  const requestedPath = isAbsolute(input.filePath)
    ? resolve(input.filePath)
    : resolve(workspacePath, input.filePath);
  const modelPath = isPythonModelPath(requestedPath)
    ? cadSourceOutputPath(workspacePath, requestedPath)
    : requestedPath;
  return `${workspacePath}\0${modelPath}`;
}

/**
 * Resolve the artifact a library-first recipe declares without executing it.
 * cadgen requires `write=` to be a string literal, so this lightweight import /
 * decorator scan can give a custom output the same mutex as direct STEP
 * validation before Python runs.
 */
function cadSourceOutputPath(workspacePath: string, sourcePath: string): string {
  const relationship = resolveCadSourceArtifactRelationship({ workspacePath, sourcePath });
  return relationship
    ? join(relationship.workspacePath, relationship.relativeModelPath)
    : resolve(workspacePath, defaultModelPath(relative(workspacePath, sourcePath)));
}

export function enqueueCadArtifactOperation<T>(
  key: string,
  operation: () => Promise<T>
): Promise<T> {
  const previous = cadArtifactOperationTails.get(key) ?? Promise.resolve();
  const result = previous.catch(() => undefined).then(operation);
  const tail = result.then(
    () => undefined,
    () => undefined
  );
  cadArtifactOperationTails.set(key, tail);
  void tail.then(() => {
    if (cadArtifactOperationTails.get(key) === tail) cadArtifactOperationTails.delete(key);
  });
  return result;
}

export function cadValidationInputRevision(input: CadArtifactTargetInput): string {
  const target = resolveCadArtifactTarget(input);
  if (!target.success) return 'missing';
  try {
    const modelHash = sha256(join(target.workspacePath, target.relativeModelPath));
    const sourceState = target.relativeSourcePath
      ? optionalFileHash(join(target.workspacePath, target.relativeSourcePath))
      : 'unlinked';
    return `${modelHash}:${sourceState}`;
  } catch {
    return 'unreadable';
  }
}

function cadValidationResultIsCurrent(
  input: CadArtifactTargetInput,
  result: Extract<CadValidationResult, { success: true }>
): boolean {
  try {
    const target = resolveCadArtifactTarget(input);
    if (
      !target.success ||
      result.artifact.modelPath !== target.relativeModelPath ||
      result.artifact.sourcePath !== target.relativeSourcePath
    ) {
      return false;
    }
    const modelPath = join(target.workspacePath, result.artifact.modelPath);
    if (!existsSync(modelPath) || sha256(modelPath) !== result.artifact.modelHash) return false;
    const sourcePath = result.artifact.sourcePath;
    if (!sourcePath) return true;
    const absoluteSourcePath = join(target.workspacePath, sourcePath);
    if (!result.artifact.sourceHash) return !existsSync(absoluteSourcePath);
    return (
      existsSync(absoluteSourcePath) && sha256(absoluteSourcePath) === result.artifact.sourceHash
    );
  } catch {
    return false;
  }
}

async function validateCadModelOnce(input: CadArtifactTargetInput): Promise<CadValidationResult> {
  const target = resolveCadArtifactTarget(input);
  if (!target.success) return target;

  const runtime = await prepareCadRuntime();
  if (!runtime.success) return runtime;

  try {
    const beforeHash = sha256(join(target.workspacePath, target.relativeModelPath));
    const result = await inspectCadArtifact(
      runtime.python,
      target.workspacePath,
      target.relativeModelPath,
      target.relativeSourcePath
    );
    const afterHash = sha256(join(target.workspacePath, target.relativeModelPath));
    if (afterHash !== beforeHash) {
      throw new Error('The canonical STEP changed while it was being inspected.');
    }
    return result;
  } catch (error) {
    return { success: false, error: validationErrorMessage(error) };
  }
}

async function rebuildCadModelOnce(input: {
  workspacePath: string;
  filePath: string;
}): Promise<CadValidationResult> {
  const target = validateSourceTarget(input);
  if (!target.success) return target;
  if (isLegacyPythonModelPath(target.relativeFilePath)) {
    return {
      success: false,
      error:
        'This legacy .step.py model is view-only until it is migrated. Run python -m cadgen.migrate on the source before rebuilding it.',
    };
  }
  if (!isPythonModelPath(target.relativeFilePath)) {
    return { success: false, error: 'A source rebuild requires a Python @step model.' };
  }

  const runtime = await prepareCadRuntime();
  if (!runtime.success) return runtime;

  try {
    const buildCommand = cadSourceRebuildToolPlan(target.relativeFilePath, runtime.contract);
    const build = await runCadCommand(
      runtime.python,
      target.workspacePath,
      buildCommand.tool,
      buildCommand.args
    );
    const modelPath = cadValidationModelPath(
      target.workspacePath,
      target.relativeFilePath,
      build,
      runtime.contract
    );
    return inspectCadArtifact(
      runtime.python,
      target.workspacePath,
      modelPath,
      target.relativeFilePath
    );
  } catch (error) {
    return { success: false, error: validationErrorMessage(error) };
  }
}

async function prepareCadRuntime(): Promise<
  { success: true; python: string; contract: CadgenContract } | { success: false; error: string }
> {
  let pluginRoot = findCadPluginRoot();
  if (!pluginRoot) {
    try {
      await provisionCadRuntime();
      pluginRoot = findCadPluginRoot();
    } catch (error) {
      return {
        success: false,
        error: `Could not prepare the pinned CAD environment: ${errorMessage(error)}`,
      };
    }
  }
  if (!pluginRoot) {
    return {
      success: false,
      error: 'The pinned CAD plugin could not be located after automatic setup.',
    };
  }
  const capability = resolveCadgenCapability(pluginRoot);
  if (!capability) {
    return {
      success: false,
      error: 'The pinned CAD environment has an unsupported or missing cadgen package manifest.',
    };
  }
  const python = findCadPythonExecutable(pluginRoot);
  if (!existsSync(python)) {
    try {
      await provisionCadRuntime();
    } catch (error) {
      return {
        success: false,
        error: `Could not prepare the pinned CAD environment: ${errorMessage(error)}`,
      };
    }
    if (!existsSync(python)) {
      return { success: false, error: 'The pinned CAD environment is incomplete.' };
    }
  }

  return { success: true, python, contract: capability.contract };
}

async function inspectCadArtifact(
  python: string,
  workspacePath: string,
  modelPath: string,
  sourcePath?: string
): Promise<Extract<CadValidationResult, { success: true }>> {
  const inspectionResults: Record<string, unknown>[] = [];
  for (const command of cadInspectionToolPlan(modelPath)) {
    inspectionResults.push(await runCadCommand(python, workspacePath, command.tool, command.args));
  }
  const [refs = {}, validation = {}] = inspectionResults;
  const token = Array.isArray(refs.tokens) ? refs.tokens[0] : undefined;
  const summary = isRecord(token) && isRecord(token.summary) ? token.summary : {};
  const entryFacts = isRecord(token) && isRecord(token.entryFacts) ? token.entryFacts : {};
  return {
    success: true,
    artifact: cadArtifactIdentity(workspacePath, modelPath, sourcePath),
    facts: {
      occurrenceCount: numberValue(summary.occurrenceCount),
      faceCount: numberValue(summary.faceCount),
      size: numberTuple(entryFacts.size),
    },
    validation,
  };
}

export function readCadModelHistory(input: {
  workspacePath: string;
  filePath: string;
}): CadSourceHistoryResult {
  const target = validateSourceTarget(input);
  if (!target.success) return target;
  if (!isPythonModelPath(target.relativeFilePath)) {
    return { success: false, error: 'Feature history requires a Python @step model.' };
  }
  try {
    const sourcePath = join(target.workspacePath, target.relativeFilePath);
    const source = readCadSource(sourcePath);
    const history = parseCadSourceHistory(source);
    return {
      success: true,
      sourceHash: sha256Text(source),
      history: isLegacyPythonModelPath(target.relativeFilePath)
        ? {
            ...history,
            parameters: [],
            diagnostics: [
              ...history.diagnostics,
              'This legacy .step.py source is view-only. Run python -m cadgen.migrate on it before editing dimensions.',
            ],
          }
        : history,
    };
  } catch (error) {
    return { success: false, error: errorMessage(error) };
  }
}

export function applyCadModelParameters(input: {
  workspacePath: string;
  filePath: string;
  expectedSourceHash: string;
  values: Record<string, number>;
}): CadParameterApplyResult {
  const target = validateSourceTarget(input);
  if (!target.success) return target;
  if (isLegacyPythonModelPath(target.relativeFilePath)) {
    return {
      success: false,
      error:
        'This legacy .step.py model is view-only until it is migrated. Run python -m cadgen.migrate on the source before editing parameters.',
    };
  }
  if (!isPythonModelPath(target.relativeFilePath)) {
    return {
      success: false,
      error: 'Design parameters require a Python @step model.',
    };
  }
  if (Object.keys(input.values).length === 0) {
    return { success: false, error: 'No design parameter changes were provided.' };
  }
  try {
    const sourcePath = join(target.workspacePath, target.relativeFilePath);
    const source = readCadSource(sourcePath);
    if (sha256Text(source) !== input.expectedSourceHash) {
      return {
        success: false,
        conflict: true,
        error: 'The generator changed on disk. Refresh History before applying parameters.',
      };
    }
    const applied = applyCadParameterValues(source, input.values);
    atomicWriteSource(sourcePath, applied.source);
    return {
      success: true,
      sourceHash: sha256Text(applied.source),
      appliedValues: applied.appliedValues,
    };
  } catch (error) {
    return { success: false, error: errorMessage(error) };
  }
}

export type { CadRuntimeCommand } from '@main/host/cad/cadgen-compatibility';

export function cadSourceRebuildToolPlan(
  relativeFilePath: string,
  contract: CadgenContract
): CadRuntimeCommand {
  return compatibilityCadSourceRebuildToolPlan(relativeFilePath, contract);
}

export function cadInspectionToolPlan(modelPath: string): CadRuntimeCommand[] {
  return [
    {
      tool: 'cadgen',
      args: ['step', 'inspect', 'refs', modelPath, '--facts', '--planes', '--positioning'],
    },
    { tool: 'cadgen', args: ['step', 'inspect', 'validate', modelPath] },
  ];
}

export function cadArtifactIdentity(workspacePath: string, modelPath: string, sourcePath?: string) {
  const absoluteModelPath = join(workspacePath, modelPath);
  if (!existsSync(absoluteModelPath)) {
    throw new Error(`Canonical CAD artifact does not exist: ${absoluteModelPath}`);
  }
  const modelHash = sha256(absoluteModelPath);
  const sourceHash = sourcePath ? optionalFileHash(join(workspacePath, sourcePath)) : undefined;
  return {
    // The accepted on-disk artifact is canonical. Source identity remains
    // attached for staleness/conflict checks but does not redefine the model
    // revision independently of the STEP bytes.
    revisionId: `sha256:${modelHash}`,
    modelPath,
    modelHash,
    ...(sourcePath ? { sourcePath } : {}),
    ...(sourceHash ? { sourceHash } : {}),
  };
}

function sha256(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function sha256Text(source: string): string {
  return createHash('sha256').update(source).digest('hex');
}

function optionalFileHash(path: string): string | undefined {
  return existsSync(path) ? sha256(path) : undefined;
}

function readCadSource(path: string): string {
  const stats = statSync(path);
  if (stats.size > MAX_SOURCE_BYTES) {
    throw new Error('The CAD generator is larger than the 2 MB History limit.');
  }
  return readFileSync(path, 'utf8');
}

function atomicWriteSource(path: string, source: string): void {
  const temporaryPath = `${path}.hardcore-${randomUUID()}.tmp`;
  try {
    writeFileSync(temporaryPath, source, { encoding: 'utf8', mode: statSync(path).mode });
    renameSync(temporaryPath, path);
  } finally {
    if (existsSync(temporaryPath)) rmSync(temporaryPath);
  }
}

/**
 * Resolves the immutable artifact inspected by normal open/restart validation.
 * A Python path is accepted only as a link to its sibling STEP; the recipe is
 * never executed here.
 */
export function resolveCadArtifactTarget(input: CadArtifactTargetInput): CadArtifactTarget {
  const workspacePath = resolve(input.workspacePath);
  const requestedFilePath = resolveWorkspaceFilePath(workspacePath, input.filePath);
  const requestedRelativePath = relative(workspacePath, requestedFilePath);
  if (!isSafeWorkspaceRelativePath(requestedRelativePath)) {
    return { success: false, error: 'CAD files must be inside the active model workspace.' };
  }

  let modelPath: string;
  let sourcePath: string | undefined;
  if (/\.(?:step|stp)$/i.test(requestedFilePath)) {
    modelPath = requestedFilePath;
    sourcePath =
      linkedSourceForStep(workspacePath, requestedFilePath, input.sourcePath) ?? undefined;
  } else if (isPythonModelPath(requestedFilePath)) {
    modelPath = cadSourceOutputPath(workspacePath, requestedFilePath);
    sourcePath =
      verifiedSourceForLegacy(workspacePath, requestedFilePath, modelPath) ?? requestedFilePath;
  } else {
    return {
      success: false,
      error: 'Artifact validation requires a canonical STEP/STP file.',
    };
  }

  const relativeModelPath = relative(workspacePath, modelPath);
  if (!isSafeWorkspaceRelativePath(relativeModelPath)) {
    return { success: false, error: 'CAD files must be inside the active model workspace.' };
  }
  if (!existsSync(modelPath)) {
    return {
      success: false,
      error: `Canonical CAD artifact does not exist: ${modelPath}. Rebuild its source explicitly to create it.`,
    };
  }

  const relativeSourcePath = sourcePath ? relative(workspacePath, sourcePath) : undefined;
  return {
    success: true,
    workspacePath,
    relativeModelPath,
    ...(relativeSourcePath && isSafeWorkspaceRelativePath(relativeSourcePath)
      ? { relativeSourcePath }
      : {}),
  };
}

function validateSourceTarget(input: {
  workspacePath: string;
  filePath: string;
}):
  | { success: true; workspacePath: string; relativeFilePath: string }
  | { success: false; error: string } {
  const workspacePath = resolve(input.workspacePath);
  const requestedFilePath = resolveWorkspaceFilePath(workspacePath, input.filePath);
  const requestedModelPath = join(
    workspacePath,
    defaultModelPath(relative(workspacePath, requestedFilePath))
  );
  const filePath =
    verifiedSourceForLegacy(workspacePath, requestedFilePath, requestedModelPath) ??
    requestedFilePath;
  const relativeFilePath = relative(workspacePath, filePath);
  if (!isSafeWorkspaceRelativePath(relativeFilePath)) {
    return { success: false, error: 'CAD files must be inside the active model workspace.' };
  }
  if (!existsSync(filePath))
    return { success: false, error: `CAD file does not exist: ${filePath}` };
  return { success: true, workspacePath, relativeFilePath };
}

function linkedSourceForStep(
  workspacePath: string,
  filePath: string,
  explicitSourcePath?: string
): string | null {
  if (!/\.(?:step|stp)$/i.test(filePath)) return null;
  const stepRelativePath = relative(workspacePath, filePath);
  if (!isSafeWorkspaceRelativePath(stepRelativePath)) return null;

  if (explicitSourcePath) {
    const relationship = normalizeCadArtifactRelationship({
      workspacePath,
      modelPath: filePath,
      sourcePath: explicitSourcePath,
    });
    if (relationship) {
      const sourcePath = join(workspacePath, relationship.relativeSourcePath);
      if (existsSync(sourcePath)) return sourcePath;
    }
  }

  // Bounded pinned-0.4 fallback. Newer cadgen contracts must supply source
  // association through Hardcore's explicit persisted model metadata or an
  // upstream contract that has been verified before it is added here.
  const descriptorPath = join(
    workspacePath,
    dirname(stepRelativePath),
    '__cadgen__',
    'models',
    basename(stepRelativePath),
    'assembly.json'
  );
  try {
    const descriptor: unknown = JSON.parse(readFileSync(descriptorPath, 'utf8'));
    if (
      isRecord(descriptor) &&
      descriptor.sourceKind === 'python' &&
      typeof descriptor.sourcePath === 'string' &&
      descriptor.sourcePath.trim() &&
      descriptor.sourcePath.toLowerCase().endsWith('.py')
    ) {
      // Upstream defines sourcePath relative to the STEP's parent, not the
      // project root. Resolve it there, then re-apply the workspace boundary.
      const sourcePath = resolve(dirname(filePath), descriptor.sourcePath);
      const sourceRelativePath = relative(workspacePath, sourcePath);
      if (isSafeWorkspaceRelativePath(sourceRelativePath)) {
        const verifiedSource = verifiedSourceForLegacy(workspacePath, sourcePath, filePath);
        if (verifiedSource) return verifiedSource;
        if (existsSync(sourcePath)) return sourcePath;
      }
    }
  } catch {
    // A raw or not-yet-built STEP has no descriptor. Do not guess a plain
    // same-stem .py source: imported CAD and an unrelated helper can share a
    // stem. Newer recipes require explicit persisted Hardcore metadata until
    // upstream establishes another source-association contract.
  }

  // Preserve the old artifact.step.py naming convention as a bounded legacy
  // compatibility link. Legacy recipes remain read-only until migrated.
  const legacySibling = `${filePath}.py`;
  const verifiedSource = verifiedSourceForLegacy(workspacePath, legacySibling, filePath);
  if (verifiedSource) return verifiedSource;
  return existsSync(legacySibling) ? legacySibling : null;
}

function isSafeWorkspaceRelativePath(path: string): boolean {
  return Boolean(path) && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function resolveWorkspaceFilePath(workspacePath: string, filePath: string): string {
  return isAbsolute(filePath) ? resolve(filePath) : resolve(workspacePath, filePath);
}

function verifiedSourceForLegacy(
  workspacePath: string,
  legacySourcePath: string,
  modelPath: string
): string | null {
  if (!isLegacyPythonModelPath(legacySourcePath)) return null;
  return verifiedMigratedCadSourceForLegacy({
    workspacePath,
    legacySourcePath,
    migratedSourcePath: legacySourcePath.replace(/\.(?:step|stp)\.py$/i, '.py'),
    modelPath,
  });
}

export function assertLegacyCadArtifactIsCurrent(
  workspacePath: string,
  relativeSourcePath: string
): string {
  if (!isLegacyPythonModelPath(relativeSourcePath)) {
    throw new Error('Legacy CAD compatibility requires a .step.py or .stp.py source.');
  }
  const modelPath = defaultModelPath(relativeSourcePath);
  const absoluteModelPath = join(workspacePath, modelPath);
  if (!existsSync(absoluteModelPath)) {
    throw new Error(
      `The legacy model has no accepted sibling STEP. Run python -m cadgen.migrate ${relativeSourcePath}, then rebuild it.`
    );
  }

  const recordedSourceHash = readCadgenStepSourceHash(absoluteModelPath);
  const currentSourceHash = sha256(join(workspacePath, relativeSourcePath));
  if (!recordedSourceHash || recordedSourceHash !== currentSourceHash) {
    throw new Error(
      `The legacy source cannot be proven to match its accepted STEP. Run python -m cadgen.migrate ${relativeSourcePath}, then rebuild it before editing.`
    );
  }
  return modelPath;
}

function readCadgenStepSourceHash(path: string): string | null {
  const text = readFileSync(path, 'utf8');
  const match = text.match(
    /DESCRIPTIVE_REPRESENTATION_ITEM\s*\(\s*'cadgen:sourceHash'\s*,\s*'([0-9a-f]{64})'\s*\)/i
  );
  return match?.[1]?.toLowerCase() ?? null;
}

async function runCadCommand(
  python: string,
  cwd: string,
  tool: CadRuntimeCommand['tool'],
  args: string[]
): Promise<Record<string, unknown>> {
  const pythonArgs = tool === 'model' ? args : ['-m', 'cadgen.cli', ...args];
  const result = await execFileAsync(python, pythonArgs, {
    cwd,
    timeout: VALIDATION_TIMEOUT_MS,
    maxBuffer: MAX_OUTPUT_BYTES,
    env: cadToolEnvironment(),
  });
  const line = result.stdout
    .trim()
    .split('\n')
    .map((candidate) => candidate.trim())
    .filter(Boolean)
    .at(-1);
  if (!line) throw new Error('CAD tool returned no result.');
  const parsed: unknown = JSON.parse(line);
  if (!isRecord(parsed) || parsed.ok !== true) throw new Error('CAD tool did not pass.');
  return parsed;
}

export function cadValidationModelPath(
  workspacePath: string,
  relativeFilePath: string,
  build: Record<string, unknown>,
  contract: CadgenContract
): string {
  if (!isPythonModelPath(relativeFilePath)) return relativeFilePath;
  return resolveCadBuildArtifactPath({
    workspacePath,
    relativeSourcePath: relativeFilePath,
    build,
    contract,
  });
}

function defaultModelPath(sourcePath: string): string {
  if (/\.(?:step|stp)\.py$/i.test(sourcePath)) return sourcePath.slice(0, -3);
  return sourcePath.replace(/\.py$/i, '.step');
}

function isPythonModelPath(path: string): boolean {
  return path.toLowerCase().endsWith('.py');
}

function isLegacyPythonModelPath(path: string): boolean {
  return /\.(?:step|stp)\.py$/i.test(path);
}

export function cadToolEnvironment(
  environment: NodeJS.ProcessEnv = process.env
): NodeJS.ProcessEnv {
  return {
    ...environment,
    // Parameter edits often preserve both source length and the filesystem's
    // coarse timestamp. Pointing Python at an unwritten cache directory keeps a
    // same-second stale `.pyc` from regenerating the previous model revision.
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONPYCACHEPREFIX: join(tmpdir(), `hardcore-cad-no-bytecode-${process.pid}`),
  };
}

function validationErrorMessage(error: unknown): string {
  if (isRecord(error)) {
    const stdout = typeof error.stdout === 'string' ? error.stdout.trim() : '';
    if (stdout) {
      try {
        const parsed: unknown = JSON.parse(stdout);
        if (isRecord(parsed)) {
          const failureCount = numberValue(parsed.failureCount);
          if (failureCount)
            return `Geometry validation found ${failureCount} failing occurrence${failureCount === 1 ? '' : 's'}.`;
          if (Array.isArray(parsed.errors) && parsed.errors.length > 0) {
            const first = parsed.errors[0];
            if (isRecord(first) && typeof first.message === 'string') return first.message;
            return String(first);
          }
        }
      } catch {
        // Use the process error below when stdout is not JSON.
      }
    }
    if (typeof error.stderr === 'string' && error.stderr.trim())
      return error.stderr.trim().split('\n').at(-1) ?? 'CAD validation failed.';
    if (typeof error.message === 'string') return error.message;
  }
  return 'CAD validation failed.';
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function numberTuple(value: unknown): [number, number, number] | undefined {
  if (
    !Array.isArray(value) ||
    value.length !== 3 ||
    !value.every((item) => typeof item === 'number')
  )
    return undefined;
  return [value[0], value[1], value[2]];
}
