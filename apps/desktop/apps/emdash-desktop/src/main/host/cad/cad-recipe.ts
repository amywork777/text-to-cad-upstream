import { createHash } from 'node:crypto';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';

/**
 * How the desktop reads a cadgen 0.5 model recipe without running it.
 *
 * A recipe is a plain `.py` file that decorates one function with `@step`.
 * Its artifact is the sibling `<stem>.step` unless the decorator says
 * `out="..."`, which resolves relative to the script. Reading the declaration
 * is a lightweight import/decorator scan; Python only ever runs through the
 * explicit rebuild path. Legacy `.step.py` files are view-only.
 */
export type CadSourceArtifactRelationship = {
  workspacePath: string;
  relativeSourcePath: string;
  relativeModelPath: string;
  declaration: 'explicit' | 'out' | 'sibling-default' | 'record';
};

/** Normalize a persisted model/source pair from the desktop's model catalog. */
export function normalizeCadArtifactRelationship(input: {
  workspacePath: string;
  modelPath: string;
  sourcePath: string;
}): CadSourceArtifactRelationship | null {
  const workspacePath = resolve(input.workspacePath);
  const modelPath = isAbsolute(input.modelPath)
    ? resolve(input.modelPath)
    : resolve(workspacePath, input.modelPath);
  const sourcePath = isAbsolute(input.sourcePath)
    ? resolve(input.sourcePath)
    : resolve(workspacePath, input.sourcePath);
  const relativeModelPath = relative(workspacePath, modelPath);
  const relativeSourcePath = relative(workspacePath, sourcePath);
  if (
    !isSafeWorkspaceRelativePath(relativeModelPath) ||
    !isSafeWorkspaceRelativePath(relativeSourcePath) ||
    !/\.(?:step|stp)$/i.test(relativeModelPath) ||
    !/\.py$/i.test(relativeSourcePath)
  ) {
    return null;
  }
  return {
    workspacePath,
    relativeSourcePath,
    relativeModelPath,
    declaration: 'explicit',
  };
}

/**
 * Resolve one authored @step recipe to the STEP it writes without executing
 * Python. cad-project recipes commonly map src/foo.py to STEP/foo.step with
 * out="../STEP/foo.step"; the default is the sibling <stem>.step.
 */
export function resolveCadSourceArtifactRelationship(input: {
  workspacePath: string;
  sourcePath: string;
  source?: string;
}): CadSourceArtifactRelationship | null {
  const workspacePath = resolve(input.workspacePath);
  const sourcePath = isAbsolute(input.sourcePath)
    ? resolve(input.sourcePath)
    : resolve(workspacePath, input.sourcePath);
  const relativeSourcePath = relative(workspacePath, sourcePath);
  if (!isSafeWorkspaceRelativePath(relativeSourcePath) || !/\.py$/i.test(sourcePath)) return null;

  let source = input.source;
  if (source === undefined) {
    try {
      source = readFileSync(sourcePath, 'utf8');
    } catch {
      source = '';
    }
  }
  const target = cadStepOutputDeclaration(source);
  const defaultPath = isLegacyPythonCadSource(sourcePath)
    ? sourcePath.slice(0, -3)
    : sourcePath.slice(0, -3) + '.step';
  const modelPath = target
    ? isAbsolute(target.path)
      ? resolve(target.path)
      : resolve(dirname(sourcePath), target.path)
    : defaultPath;
  const relativeModelPath = relative(workspacePath, modelPath);
  if (
    !isSafeWorkspaceRelativePath(relativeModelPath) ||
    !/\.(?:step|stp)$/i.test(relativeModelPath)
  ) {
    return null;
  }
  return {
    workspacePath,
    relativeSourcePath,
    relativeModelPath,
    declaration: target ? 'out' : 'sibling-default',
  };
}

/** The `out=` string literal of the recipe's @step decorator, when declared. */
export function cadStepOutputDeclaration(source: string): { keyword: 'out'; path: string } | null {
  const stepNames = new Set<string>();
  const moduleNames = new Set<string>();
  for (const line of source.split(/\r?\n/)) {
    const fromImport = line.match(/^\s*from\s+cadgen(?:\.authoring)?\s+import\s+(.+?)(?:\s*#.*)?$/);
    if (fromImport) {
      for (const imported of fromImport[1].split(',')) {
        const match = imported.trim().match(/^step(?:\s+as\s+([A-Za-z_]\w*))?$/);
        if (match) stepNames.add(match[1] ?? 'step');
      }
    }
    const moduleImport = line.match(/^\s*import\s+cadgen(?:\s+as\s+([A-Za-z_]\w*))?\s*(?:#.*)?$/);
    if (moduleImport) moduleNames.add(moduleImport[1] ?? 'cadgen');
  }
  if (stepNames.size === 0 && moduleNames.size === 0) return null;

  const lines = source.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    const decorator = line.match(/^\s*@([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?\b/);
    if (!decorator) continue;
    const directStep = !decorator[2] && stepNames.has(decorator[1]);
    const moduleStep = decorator[2] === 'step' && moduleNames.has(decorator[1]);
    if (!directStep && !moduleStep) continue;

    let declaration = line;
    let callDepth = pythonDecoratorCallDepth(line);
    while (callDepth > 0 && index + 1 < lines.length) {
      const continuation = lines[++index] ?? '';
      declaration += `\n${continuation}`;
      callDepth += pythonDecoratorCallDepth(continuation);
    }
    const match = declaration.match(/\bout\s*=\s*(['"])([^'"\\]+)\1/);
    const path = match?.[2]?.trim();
    return path ? { keyword: 'out', path } : null;
  }
  return null;
}

export type CadRuntimeCommand = {
  tool: 'model' | 'cadgen';
  args: string[];
};

/**
 * The one source door in cadgen 0.5: running the script. The freshness gate
 * inside cadgen decides whether anything rebuilds, so the desktop never
 * passes --force; opening, previewing, and restarting never call this at all.
 */
export function cadSourceRebuildToolPlan(relativeSourcePath: string): CadRuntimeCommand {
  if (/\.(?:step|stp)\.py$/i.test(relativeSourcePath)) {
    throw new Error(
      'Legacy .step.py recipes are view-only. Rename the file to a plain .py model with one @step function before rebuilding it.'
    );
  }
  if (!/\.py$/i.test(relativeSourcePath)) {
    throw new Error('A source rebuild requires a Python @step model.');
  }
  return { tool: 'model', args: [relativeSourcePath, '--json'] };
}

/**
 * Resolve the artifact reported after a model run. cadgen reports the
 * document as `cadPath` (workspace-relative, without the extension); the
 * declared out=/sibling relationship is the fallback when a run omits it.
 */
export function resolveCadBuildArtifactPath(input: {
  workspacePath: string;
  relativeSourcePath: string;
  build: Record<string, unknown>;
}): string {
  const workspacePath = resolve(input.workspacePath);
  const relationship = resolveCadSourceArtifactRelationship({
    workspacePath,
    sourcePath: input.relativeSourcePath,
  });
  const cadReference =
    typeof input.build.cadPath === 'string' && input.build.cadPath.trim()
      ? input.build.cadPath.trim()
      : relationship?.relativeModelPath;
  if (!cadReference) throw new Error('The CAD build did not identify its generated artifact.');
  const reported = /\.(?:step|stp)$/i.test(cadReference) ? cadReference : `${cadReference}.step`;
  const absoluteModelPath = resolve(workspacePath, reported);
  const relativeModelPath = relative(workspacePath, absoluteModelPath);
  if (!isSafeWorkspaceRelativePath(relativeModelPath)) {
    throw new Error('The generated CAD artifact must remain inside the active model workspace.');
  }
  if (!/\.(?:step|stp)$/i.test(relativeModelPath)) {
    throw new Error(`The model generated an unsupported CAD artifact: ${reported}`);
  }
  return relativeModelPath;
}

/**
 * cadgen's user-level cache root, resolved by the same rule cadgen and
 * cadgen-js use: $CADGEN_CACHE_DIR, then the platform cache convention, then
 * ~/.cache/cadgen.
 */
export function resolveCadgenCacheRoot(
  environment: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  home: string = homedir()
): string {
  const override = environment.CADGEN_CACHE_DIR?.trim();
  if (override) return override;
  if (platform === 'win32') {
    const localAppData = environment.LOCALAPPDATA?.trim();
    if (localAppData) return join(localAppData, 'cadgen');
  } else {
    const xdgCacheHome = environment.XDG_CACHE_HOME?.trim();
    if (xdgCacheHome) return join(xdgCacheHome, 'cadgen');
  }
  return join(home, '.cache', 'cadgen');
}

/**
 * The records-tier provenance file cadgen writes for every generated document:
 * `<cache>/records/<sha256(resolved artifact path)[:24]>.source.json`. It is
 * evictable bookkeeping, never identity: a missing record reads as an import.
 */
export function cadgenProvenanceRecordPath(
  artifactPath: string,
  cacheRoot: string = resolveCadgenCacheRoot()
): string {
  const resolved = resolveLikeCadgen(artifactPath);
  const key = createHash('sha256').update(resolved, 'utf8').digest('hex').slice(0, 24);
  return join(cacheRoot, 'records', `${key}.source.json`);
}

export interface CadgenSourceProvenance {
  sourceKind: string;
  sourcePath?: string;
  sourceHash?: string;
}

export function readCadgenSourceProvenance(
  artifactPath: string,
  cacheRoot: string = resolveCadgenCacheRoot()
): CadgenSourceProvenance | null {
  const record = readJsonRecord(cadgenProvenanceRecordPath(artifactPath, cacheRoot));
  if (!record || typeof record.sourceKind !== 'string') return null;
  return {
    sourceKind: record.sourceKind,
    ...(typeof record.sourcePath === 'string' ? { sourcePath: record.sourcePath } : {}),
    ...(typeof record.sourceHash === 'string' ? { sourceHash: record.sourceHash } : {}),
  };
}

/**
 * Follow cadgen's own provenance record from a STEP back to the recipe that
 * wrote it. The record is only a hint: the recipe must exist inside the
 * workspace and its declared output must resolve back to this exact STEP.
 */
export function linkedSourceFromCadgenRecord(input: {
  workspacePath: string;
  modelPath: string;
  cacheRoot?: string;
}): CadSourceArtifactRelationship | null {
  const workspacePath = resolve(input.workspacePath);
  const modelPath = isAbsolute(input.modelPath)
    ? resolve(input.modelPath)
    : resolve(workspacePath, input.modelPath);
  const relativeModelPath = relative(workspacePath, modelPath);
  if (!isSafeWorkspaceRelativePath(relativeModelPath) || !existsSync(modelPath)) return null;
  const provenance = readCadgenSourceProvenance(modelPath, input.cacheRoot);
  if (provenance?.sourceKind !== 'python' || !provenance.sourcePath?.trim()) return null;
  // cadgen records the recipe relative to the document's directory.
  const sourcePath = resolve(dirname(modelPath), provenance.sourcePath);
  const relativeSourcePath = relative(workspacePath, sourcePath);
  if (
    !isSafeWorkspaceRelativePath(relativeSourcePath) ||
    !/\.py$/i.test(relativeSourcePath) ||
    isLegacyPythonCadSource(relativeSourcePath) ||
    !existsSync(sourcePath)
  ) {
    return null;
  }
  const declared = resolveCadSourceArtifactRelationship({ workspacePath, sourcePath });
  if (!declared || declared.relativeModelPath !== relativeModelPath) return null;
  return { workspacePath, relativeSourcePath, relativeModelPath, declaration: 'record' };
}

function resolveLikeCadgen(path: string): string {
  const absolute = resolve(path);
  try {
    return realpathSync.native(absolute);
  } catch {
    return absolute;
  }
}

function pythonDecoratorCallDepth(source: string): number {
  let depth = 0;
  let quote: "'" | '"' | null = null;
  let escaped = false;
  for (const character of source) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === '\\' && quote) {
      escaped = true;
      continue;
    }
    if (quote) {
      if (character === quote) quote = null;
      continue;
    }
    if (character === "'" || character === '"') {
      quote = character;
      continue;
    }
    if (character === '#') break;
    if (character === '(') depth += 1;
    if (character === ')') depth -= 1;
  }
  return depth;
}

export function isLegacyPythonCadSource(path: string): boolean {
  return /\.(?:step|stp)\.py$/i.test(path);
}

export function isSafeWorkspaceRelativePath(path: string): boolean {
  return Boolean(path) && path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readJsonRecord(path: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
