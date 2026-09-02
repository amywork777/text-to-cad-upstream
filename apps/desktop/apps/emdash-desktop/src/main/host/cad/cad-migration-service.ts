import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { promisify } from 'node:util';
import type { CadMigrationResult } from '@core/features/browser/api';
import {
  canonicalCadModelPathForLegacySource,
  isLegacyCadSourcePath,
  migratedCadSourcePath,
} from '@core/features/cad/api/cad-source-path';
import {
  type CadVerifiedMigrationMarker,
  cadMigrationSha256,
  readCadVerifiedMigrationMarker,
  writeCadVerifiedMigrationMarker,
} from '@main/host/cad/cad-migration-marker';
import {
  currentCadRuntimePythonExecutable,
  provisionCadRuntime,
} from '@main/host/cad/cad-runtime-service';
import {
  assertLegacyCadArtifactIsCurrent,
  cadArtifactOperationKey,
  enqueueCadArtifactOperation,
} from '@main/host/cad/cad-validation-service';

const execFileAsync = promisify(execFile);
const MIGRATION_TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 2 * 1024 * 1024;
const MAX_SOURCE_BYTES = 2 * 1024 * 1024;
const CONTENT_HASH_PATTERN = /^[0-9a-f]{64}$/i;

interface CadMigrationRunOptions {
  cwd: string;
  env: NodeJS.ProcessEnv;
  timeout: number;
  maxBuffer: number;
}

export interface CadMigrationDependencies {
  prepareRuntime(): Promise<void>;
  pythonExecutable(): string;
  run(
    executable: string,
    args: readonly string[],
    options: CadMigrationRunOptions
  ): Promise<{ stdout: string; stderr: string }>;
}

const defaultDependencies: CadMigrationDependencies = {
  prepareRuntime: provisionCadRuntime,
  pythonExecutable: currentCadRuntimePythonExecutable,
  run: async (executable, args, options) => {
    const result = await execFileAsync(executable, [...args], { ...options, encoding: 'utf8' });
    return { stdout: String(result.stdout), stderr: String(result.stderr) };
  },
};

const migrationInFlight = new Map<string, Promise<CadMigrationResult>>();

export async function migrateLegacyCadModel(
  input: { workspacePath: string; filePath: string },
  dependencies: CadMigrationDependencies = defaultDependencies
): Promise<CadMigrationResult> {
  const queued = normalizeMigrationQueueInput(input);
  if (!queued.success) return queued;
  const key = cadArtifactOperationKey(queued.input);
  const existing = migrationInFlight.get(key);
  if (existing) return existing;
  const operation = enqueueCadArtifactOperation(key, () =>
    migrateLegacyCadModelOnce(queued.input, dependencies)
  );
  migrationInFlight.set(key, operation);
  const cleanup = () => {
    if (migrationInFlight.get(key) === operation) migrationInFlight.delete(key);
  };
  void operation.then(cleanup, cleanup);
  return operation;
}

async function migrateLegacyCadModelOnce(
  input: { workspacePath: string; filePath: string },
  dependencies: CadMigrationDependencies
): Promise<CadMigrationResult> {
  const target = validateMigrationTarget(input);
  if (!target.success) return target;

  const markerRead = readCadVerifiedMigrationMarker({
    workspacePath: target.workspacePath,
    legacySourcePath: target.sourcePath,
    migratedSourcePath: target.migratedSourcePath,
    modelPath: target.modelPath,
  });
  if (!markerRead.success) return markerRead;
  if (markerRead.marker) {
    return commitVerifiedMigration(target, markerRead.marker, markerRead.markerPath);
  }
  if (!target.sourceExists) {
    return {
      success: false,
      error:
        'The legacy CAD source is missing and there is no verified migration marker. Recovery is required before the plain source can be trusted.',
    };
  }
  if (target.migratedSourceExists) {
    return {
      success: false,
      error: `${target.relativeMigratedSourcePath} already exists without a verified migration marker. Resolve that file before migrating.`,
    };
  }

  const originalSource = readFileSync(target.sourcePath);
  if (originalSource.byteLength > MAX_SOURCE_BYTES) {
    return { success: false, error: 'The legacy CAD source is too large to migrate safely.' };
  }
  const originalSourceMode = statSync(target.sourcePath).mode & 0o777;
  const originalModel = readFileSync(target.modelPath);
  const originalModelMode = statSync(target.modelPath).mode & 0o777;
  const originalSourceHash = cadMigrationSha256(originalSource);
  const originalModelHash = cadMigrationSha256(originalModel);
  let comparison: GeometryComparisonWorkspace | null = null;
  let markerWritten = false;

  try {
    const currentModelPath = assertLegacyCadArtifactIsCurrent(
      target.workspacePath,
      target.relativeSourcePath
    );
    if (resolve(target.workspacePath, currentModelPath) !== target.modelPath) {
      throw new Error('The legacy source is linked to a different canonical STEP.');
    }

    await dependencies.prepareRuntime();
    assertProjectInputsUnchanged(target, originalSourceHash, originalModelHash);
    const python = dependencies.pythonExecutable();
    if (!isExecutableFile(python)) {
      throw new Error('The pinned CAD Python interpreter is unavailable.');
    }

    comparison = createGeometryComparisonWorkspace(target, originalSource, originalSourceMode);
    await runAndGuard(
      dependencies,
      python,
      [comparison.legacyWrapperPath, '--force', '--json'],
      migrationRunOptions(target.workspacePath),
      target,
      originalSourceHash,
      originalModelHash
    );
    assertIsolatedBuild(comparison.legacyModelPath);

    await runAndGuard(
      dependencies,
      python,
      ['-m', 'cadgen.migrate', basename(comparison.legacySourcePath)],
      migrationRunOptions(dirname(comparison.legacySourcePath)),
      target,
      originalSourceHash,
      originalModelHash
    );
    if (existsSync(comparison.legacySourcePath) || !isRegularFile(comparison.migratedSourcePath)) {
      throw new Error('cadgen did not complete the isolated legacy-source rename.');
    }

    writeCandidateWrapper(comparison, target);
    await runAndGuard(
      dependencies,
      python,
      [comparison.candidateWrapperPath, '--force', '--json'],
      migrationRunOptions(target.workspacePath),
      target,
      originalSourceHash,
      originalModelHash
    );
    assertIsolatedBuild(comparison.candidateModelPath);

    for (const modelPath of [comparison.legacyModelPath, comparison.candidateModelPath]) {
      await runAndGuard(
        dependencies,
        python,
        ['-m', 'cadgen.cli', 'step', 'inspect', 'validate', modelPath],
        migrationRunOptions(target.workspacePath),
        target,
        originalSourceHash,
        originalModelHash
      );
    }

    const baselineSignature = readPackageGeometrySignature(
      renderPackagePath(comparison.legacyModelPath)
    );
    const migratedSignature = readPackageGeometrySignature(
      renderPackagePath(comparison.candidateModelPath)
    );
    if (stableJson(migratedSignature) !== stableJson(baselineSignature)) {
      throw new Error(
        'The migrated recipe rebuilt different geometry or placements, so it was not accepted.'
      );
    }
    assertProjectInputsUnchanged(target, originalSourceHash, originalModelHash);

    const migratedSource = readFileSync(comparison.migratedSourcePath);
    if (migratedSource.byteLength === 0 || migratedSource.byteLength > MAX_SOURCE_BYTES) {
      throw new Error('The migrated CAD source has an invalid size.');
    }
    const marker: CadVerifiedMigrationMarker = {
      version: 1,
      state: 'verified',
      legacySourcePath: target.relativeSourcePath,
      migratedSourcePath: target.relativeMigratedSourcePath,
      modelPath: target.relativeModelPath,
      originalSourceHash,
      modelHash: originalModelHash,
      migratedSourceHash: cadMigrationSha256(migratedSource),
      sourceMode: originalSourceMode,
      migratedSourceBase64: migratedSource.toString('base64'),
    };
    writeCadVerifiedMigrationMarker(markerRead.markerPath, marker);
    markerWritten = true;
    return commitVerifiedMigration(target, marker, markerRead.markerPath);
  } catch (error) {
    if (markerWritten) {
      return {
        success: false,
        error: `${migrationErrorMessage(error)} The verified migration is safe to retry.`,
      };
    }
    const recovery = restoreProjectInputs(
      target,
      originalSource,
      originalSourceMode,
      originalModel,
      originalModelMode
    );
    return migrationFailureWithRecovery(migrationErrorMessage(error), recovery);
  } finally {
    cleanupGeometryComparisonWorkspace(comparison);
  }
}

type MigrationTarget = Extract<ReturnType<typeof validateMigrationTarget>, { success: true }>;

function normalizeMigrationQueueInput(input: {
  workspacePath: string;
  filePath: string;
}):
  | { success: true; input: { workspacePath: string; filePath: string } }
  | { success: false; error: string } {
  try {
    const workspacePath = realpathSync(resolve(input.workspacePath));
    const requestedPath = isAbsolute(input.filePath)
      ? resolve(input.filePath)
      : resolve(workspacePath, input.filePath);
    const realParent = realpathSync(dirname(requestedPath));
    const filePath = resolve(realParent, basename(requestedPath));
    if (!isInsideWorkspace(relative(workspacePath, filePath))) {
      return { success: false, error: 'CAD files must stay inside the active project workspace.' };
    }
    return { success: true, input: { workspacePath, filePath } };
  } catch (error) {
    return { success: false, error: migrationErrorMessage(error) };
  }
}

function validateMigrationTarget(input: { workspacePath: string; filePath: string }):
  | {
      success: true;
      workspacePath: string;
      sourcePath: string;
      migratedSourcePath: string;
      modelPath: string;
      relativeSourcePath: string;
      relativeMigratedSourcePath: string;
      relativeModelPath: string;
      sourceExists: boolean;
      migratedSourceExists: boolean;
    }
  | { success: false; error: string } {
  try {
    const workspacePath = realpathSync(resolve(input.workspacePath));
    const sourceParent = realpathSync(dirname(resolve(input.filePath)));
    const sourcePath = resolve(sourceParent, basename(input.filePath));
    const relativeSourcePath = relative(workspacePath, sourcePath);
    if (!isLegacyCadSourcePath(sourcePath)) {
      return { success: false, error: 'Only legacy .step.py or .stp.py models can be migrated.' };
    }
    if (!isInsideWorkspace(relativeSourcePath)) {
      return { success: false, error: 'CAD files must stay inside the active project workspace.' };
    }
    const relativeMigratedSourcePath = migratedCadSourcePath(relativeSourcePath);
    const relativeModelPath = canonicalCadModelPathForLegacySource(relativeSourcePath);
    if (!relativeMigratedSourcePath || !relativeModelPath) {
      return { success: false, error: 'The legacy CAD source name could not be migrated safely.' };
    }
    const migratedSourcePath = resolve(workspacePath, relativeMigratedSourcePath);
    const modelPath = resolve(workspacePath, relativeModelPath);
    const sourceExists = existsSync(sourcePath);
    const migratedSourceExists = existsSync(migratedSourcePath);
    if (sourceExists && !isRegularFileInside(workspacePath, sourcePath)) {
      return { success: false, error: 'The legacy CAD source must be a regular project file.' };
    }
    if (migratedSourceExists && !isRegularFileInside(workspacePath, migratedSourcePath)) {
      return { success: false, error: 'The migrated CAD source must be a regular project file.' };
    }
    if (!isRegularFileInside(workspacePath, modelPath)) {
      return { success: false, error: 'The accepted STEP must be a regular project file.' };
    }
    return {
      success: true,
      workspacePath,
      sourcePath,
      migratedSourcePath,
      modelPath,
      relativeSourcePath,
      relativeMigratedSourcePath,
      relativeModelPath,
      sourceExists,
      migratedSourceExists,
    };
  } catch (error) {
    return { success: false, error: migrationErrorMessage(error) };
  }
}

function commitVerifiedMigration(
  target: MigrationTarget,
  marker: CadVerifiedMigrationMarker,
  markerPath: string
): CadMigrationResult {
  try {
    if (cadMigrationSha256(readFileSync(target.modelPath)) !== marker.modelHash) {
      throw new Error('The accepted STEP changed after migration verification.');
    }
    if (!existsSync(target.migratedSourcePath)) {
      if (marker.state !== 'verified' || !marker.migratedSourceBase64) {
        throw new Error('The verified migrated CAD source is missing.');
      }
      atomicCreateFile(
        target.migratedSourcePath,
        Buffer.from(marker.migratedSourceBase64, 'base64'),
        marker.sourceMode
      );
    }
    if (
      !isRegularFile(target.migratedSourcePath) ||
      cadMigrationSha256(readFileSync(target.migratedSourcePath)) !== marker.migratedSourceHash
    ) {
      throw new Error('The migrated CAD source does not match its verified content.');
    }
    chmodSync(target.migratedSourcePath, marker.sourceMode);

    if (existsSync(target.sourcePath)) {
      if (
        !isRegularFile(target.sourcePath) ||
        cadMigrationSha256(readFileSync(target.sourcePath)) !== marker.originalSourceHash
      ) {
        throw new Error('The legacy CAD source changed before verified cleanup completed.');
      }
      unlinkSync(target.sourcePath);
      fsyncDirectory(dirname(target.sourcePath));
    }

    const committedMarker: CadVerifiedMigrationMarker = {
      version: 1,
      state: 'committed',
      legacySourcePath: marker.legacySourcePath,
      migratedSourcePath: marker.migratedSourcePath,
      modelPath: marker.modelPath,
      originalSourceHash: marker.originalSourceHash,
      modelHash: marker.modelHash,
      migratedSourceHash: marker.migratedSourceHash,
      sourceMode: marker.sourceMode,
    };
    writeCadVerifiedMigrationMarker(markerPath, committedMarker);
    return migrationSuccess(target);
  } catch (error) {
    return {
      success: false,
      error: `${migrationErrorMessage(error)} The verified migration marker was kept so cleanup can be retried safely.`,
    };
  }
}

function migrationSuccess(target: MigrationTarget): Extract<CadMigrationResult, { success: true }> {
  return {
    success: true,
    sourcePath: target.relativeMigratedSourcePath,
    modelPath: target.relativeModelPath,
    openPath: target.relativeModelPath,
  };
}

type GeometryComparisonWorkspace = {
  root: string;
  legacySourcePath: string;
  migratedSourcePath: string;
  legacyWrapperPath: string;
  candidateWrapperPath: string;
  legacyModelPath: string;
  candidateModelPath: string;
};

function createGeometryComparisonWorkspace(
  target: MigrationTarget,
  originalSource: Buffer,
  sourceMode: number
): GeometryComparisonWorkspace {
  const root = mkdtempSync(join(tmpdir(), 'hardcore-cad-migration-geometry-'));
  const migrationRoot = join(root, 'migration');
  mkdirSync(migrationRoot);
  const legacySourcePath = join(migrationRoot, basename(target.sourcePath));
  const migratedSourcePath = join(migrationRoot, basename(target.migratedSourcePath));
  writeFileSync(legacySourcePath, originalSource, { mode: sourceMode });
  const comparison = {
    root,
    legacySourcePath,
    migratedSourcePath,
    legacyWrapperPath: join(root, 'legacy-wrapper.py'),
    candidateWrapperPath: join(root, 'candidate-wrapper.py'),
    legacyModelPath: join(root, 'legacy.step'),
    candidateModelPath: join(root, 'candidate.step'),
  };
  writeModelWrapper({
    wrapperPath: comparison.legacyWrapperPath,
    sourcePath: comparison.legacySourcePath,
    displaySourcePath: target.sourcePath,
    outputPath: comparison.legacyModelPath,
    mode: 'legacy',
    modelName: 'gen_step',
  });
  return comparison;
}

function writeCandidateWrapper(
  comparison: GeometryComparisonWorkspace,
  target: MigrationTarget
): void {
  writeModelWrapper({
    wrapperPath: comparison.candidateWrapperPath,
    sourcePath: comparison.migratedSourcePath,
    displaySourcePath: target.migratedSourcePath,
    outputPath: comparison.candidateModelPath,
    mode: 'candidate',
  });
}

function writeModelWrapper(input: {
  wrapperPath: string;
  sourcePath: string;
  displaySourcePath: string;
  outputPath: string;
  mode: 'legacy' | 'candidate';
  modelName?: string;
}): void {
  const namespaceName = `hardcore_migration_${input.mode}`;
  const lines = [
    'from pathlib import Path',
    'import sys',
    `sys.path.insert(0, ${JSON.stringify(dirname(input.displaySourcePath))})`,
    `_source_path = Path(${JSON.stringify(input.sourcePath)}).resolve()`,
    '_source = _source_path.read_text()',
    `_namespace = {"__name__": ${JSON.stringify(namespaceName)}, "__file__": ${JSON.stringify(input.displaySourcePath)}, "__package__": None}`,
    'exec(compile(_source, str(_source_path), "exec"), _namespace)',
    ...(input.mode === 'candidate'
      ? [
          'from cadgen.authoring import registered_model',
          '_model = registered_model(_source_path)',
          'if _model is None or _model.fmt != "step":',
          '    raise RuntimeError("The migrated source did not register exactly one STEP model.")',
          '_build = _model.func',
        ]
      : [
          `_build = _namespace.get(${JSON.stringify(input.modelName)})`,
          'if not callable(_build):',
          `    raise RuntimeError(${JSON.stringify(`Legacy model function ${input.modelName}() was not found.`)})`,
        ]),
    'from cadgen.authoring import step',
    `@step(write=${JSON.stringify(input.outputPath)})`,
    'def isolated_migration_geometry():',
    '    return _build()',
    '',
  ];
  writeFileSync(input.wrapperPath, lines.join('\n'), { encoding: 'utf8', mode: 0o600 });
}

async function runAndGuard(
  dependencies: CadMigrationDependencies,
  python: string,
  args: readonly string[],
  options: CadMigrationRunOptions,
  target: MigrationTarget,
  sourceHash: string,
  modelHash: string
): Promise<void> {
  try {
    await dependencies.run(python, args, options);
  } finally {
    assertProjectInputsUnchanged(target, sourceHash, modelHash);
  }
}

function assertProjectInputsUnchanged(
  target: MigrationTarget,
  sourceHash: string,
  modelHash: string
): void {
  if (
    !isRegularFile(target.modelPath) ||
    cadMigrationSha256(readFileSync(target.modelPath)) !== modelHash
  ) {
    throw new Error('An external CAD command unexpectedly changed the accepted STEP.');
  }
  if (
    !isRegularFile(target.sourcePath) ||
    cadMigrationSha256(readFileSync(target.sourcePath)) !== sourceHash
  ) {
    throw new Error('An external CAD command unexpectedly changed the legacy source.');
  }
  if (existsSync(target.migratedSourcePath)) {
    throw new Error('An external CAD command unexpectedly wrote into the project workspace.');
  }
}

function assertIsolatedBuild(modelPath: string): void {
  if (!isRegularFile(modelPath)) {
    throw new Error('The isolated migration check did not produce a regular STEP file.');
  }
  const packagePath = renderPackagePath(modelPath);
  if (!isRegularDirectory(packagePath) || !isRegularFile(join(packagePath, 'assembly.json'))) {
    throw new Error('The isolated migration check did not produce a readable render package.');
  }
}

function restoreProjectInputs(
  target: MigrationTarget,
  originalSource: Buffer,
  originalSourceMode: number,
  originalModel: Buffer,
  originalModelMode: number
): { success: true; restored: boolean } | { success: false; error: string } {
  const failures: string[] = [];
  let restored = false;
  if (!fileMatches(target.sourcePath, originalSource)) {
    try {
      atomicReplaceFile(target.sourcePath, originalSource, originalSourceMode);
      restored = true;
    } catch (error) {
      failures.push(`source rollback: ${migrationErrorMessage(error)}`);
    }
  }
  if (!fileMatches(target.modelPath, originalModel)) {
    try {
      atomicReplaceFile(target.modelPath, originalModel, originalModelMode);
      restored = true;
    } catch (error) {
      failures.push(`STEP rollback: ${migrationErrorMessage(error)}`);
    }
  }
  if (existsSync(target.migratedSourcePath)) {
    failures.push('an unexpected plain source remains in the project workspace');
  }
  return failures.length === 0
    ? { success: true, restored }
    : { success: false, error: failures.join('; ') };
}

function migrationFailureWithRecovery(
  error: string,
  recovery: ReturnType<typeof restoreProjectInputs>
): Extract<CadMigrationResult, { success: false }> {
  if (!recovery.success) {
    return {
      success: false,
      error: `${error} Rollback failed (${recovery.error}). Manual recovery is required.`,
    };
  }
  return {
    success: false,
    error: recovery.restored
      ? `${error} The original source and STEP were restored atomically.`
      : `${error} The original source and STEP remain unchanged.`,
  };
}

type GeometrySignature = {
  components: string[];
  occurrences: Array<{
    id: string;
    contentHash: string;
    transform: unknown;
    color?: unknown;
    material?: unknown;
  }>;
  hierarchy: unknown;
  assemblyMates: unknown;
  bbox: unknown;
};

function readPackageGeometrySignature(packagePath: string): GeometrySignature {
  if (!isRegularDirectory(packagePath)) {
    throw new Error('The isolated render package is missing or unsafe.');
  }
  const descriptorPath = join(packagePath, 'assembly.json');
  if (!isRegularFile(descriptorPath)) {
    throw new Error('The isolated render package has no regular assembly descriptor.');
  }
  const parsed: unknown = JSON.parse(readFileSync(descriptorPath, 'utf8'));
  if (!isRecord(parsed)) throw new Error('The isolated assembly descriptor is invalid.');
  return packageGeometrySignature(parsed);
}

function packageGeometrySignature(descriptor: Record<string, unknown>): GeometrySignature {
  const componentRows = isRecord(descriptor.components) ? descriptor.components : {};
  const contentHashes = new Map<string, string>();
  for (const [componentId, value] of Object.entries(componentRows)) {
    if (!isRecord(value) || typeof value.contentHash !== 'string') {
      throw new Error('The render package has incomplete component hashes.');
    }
    const hash = value.contentHash.toLowerCase();
    if (!CONTENT_HASH_PATTERN.test(hash)) {
      throw new Error('The render package has an invalid component hash.');
    }
    contentHashes.set(componentId, hash);
  }
  if (contentHashes.size === 0) throw new Error('The render package has no components.');
  if (!Array.isArray(descriptor.occurrences) || descriptor.occurrences.length === 0) {
    throw new Error('The render package has no component occurrences.');
  }
  const occurrences = descriptor.occurrences.map((value) => {
    if (!isRecord(value) || typeof value.id !== 'string' || typeof value.component !== 'string') {
      throw new Error('The render package has an invalid component occurrence.');
    }
    const contentHash = contentHashes.get(value.component);
    if (!contentHash) throw new Error('A component occurrence references a missing component.');
    return {
      id: value.id,
      contentHash,
      transform: value.transform ?? null,
      ...(value.color === undefined ? {} : { color: value.color }),
      ...(value.material === undefined ? {} : { material: value.material }),
    };
  });
  occurrences.sort((left, right) => left.id.localeCompare(right.id));
  return {
    components: [...contentHashes.values()].sort(),
    occurrences,
    hierarchy: geometryHierarchy(descriptor.assemblyRoot),
    assemblyMates: descriptor.assemblyMates ?? null,
    bbox: descriptor.bbox ?? null,
  };
}

function geometryHierarchy(value: unknown): unknown {
  if (!isRecord(value)) return null;
  return {
    id: typeof value.id === 'string' ? value.id : null,
    nodeType: typeof value.nodeType === 'string' ? value.nodeType : null,
    leafPartIds: Array.isArray(value.leafPartIds)
      ? [...value.leafPartIds].sort((left, right) => String(left).localeCompare(String(right)))
      : [],
    children: Array.isArray(value.children) ? value.children.map(geometryHierarchy) : [],
  };
}

function cleanupGeometryComparisonWorkspace(comparison: GeometryComparisonWorkspace | null): void {
  if (!comparison) return;
  try {
    rmSync(comparison.root, { recursive: true, force: true });
  } catch {
    // Temporary comparison files contain no accepted project data.
  }
}

function migrationRunOptions(cwd: string): CadMigrationRunOptions {
  return {
    cwd,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', CADGEN_WARM: '0' },
    timeout: MIGRATION_TIMEOUT_MS,
    maxBuffer: MAX_OUTPUT_BYTES,
  };
}

function renderPackagePath(modelPath: string): string {
  return join(dirname(modelPath), '__cadgen__', 'models', basename(modelPath));
}

function atomicCreateFile(path: string, contents: Buffer, mode: number): void {
  const temporaryPath = writeDurableTemporaryFile(path, contents, mode);
  try {
    linkSync(temporaryPath, path);
    chmodSync(path, mode);
    fsyncDirectory(dirname(path));
  } finally {
    if (existsSync(temporaryPath)) rmSync(temporaryPath, { force: true });
  }
}

function atomicReplaceFile(path: string, contents: Buffer, mode: number): void {
  const temporaryPath = writeDurableTemporaryFile(path, contents, mode);
  try {
    renameSync(temporaryPath, path);
    fsyncDirectory(dirname(path));
  } finally {
    if (existsSync(temporaryPath)) rmSync(temporaryPath, { force: true });
  }
}

function fsyncDirectory(path: string): void {
  if (process.platform === 'win32') return;
  const descriptor = openSync(path, 'r');
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function writeDurableTemporaryFile(path: string, contents: Buffer, mode: number): string {
  const temporaryPath = join(dirname(path), `.${basename(path)}.${randomUUID()}.tmp`);
  let descriptor: number | null = null;
  try {
    descriptor = openSync(temporaryPath, 'wx', mode);
    writeFileSync(descriptor, contents);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = null;
    chmodSync(temporaryPath, mode);
    return temporaryPath;
  } catch (error) {
    if (descriptor !== null) closeSync(descriptor);
    if (existsSync(temporaryPath)) rmSync(temporaryPath, { force: true });
    throw error;
  }
}

function fileMatches(path: string, expected: Buffer): boolean {
  try {
    return (
      isRegularFile(path) && cadMigrationSha256(readFileSync(path)) === cadMigrationSha256(expected)
    );
  } catch {
    return false;
  }
}

function isRegularFileInside(workspacePath: string, path: string): boolean {
  try {
    return isRegularFile(path) && isInsideWorkspace(relative(workspacePath, realpathSync(path)));
  } catch {
    return false;
  }
}

function isRegularFile(path: string): boolean {
  try {
    return existsSync(path) && !lstatSync(path).isSymbolicLink() && statSync(path).isFile();
  } catch {
    return false;
  }
}

function isExecutableFile(path: string): boolean {
  try {
    return existsSync(path) && statSync(path).isFile();
  } catch {
    return false;
  }
}

function isRegularDirectory(path: string): boolean {
  try {
    return existsSync(path) && !lstatSync(path).isSymbolicLink() && statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function isInsideWorkspace(path: string): boolean {
  return Boolean(path) && path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function stableJson(value: unknown): string {
  return JSON.stringify(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function migrationErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return 'Could not migrate the legacy CAD source.';
  const detail = error as Error & { stderr?: string | Buffer };
  const stderr = String(detail.stderr ?? '').trim();
  return stderr || error.message || 'Could not migrate the legacy CAD source.';
}
