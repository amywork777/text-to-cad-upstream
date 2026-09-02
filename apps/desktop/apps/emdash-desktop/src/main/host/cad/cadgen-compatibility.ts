import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';

/**
 * The Text-to-CAD checkout has shipped the Viewer in several locations. Keep
 * that moving upstream layout behind one boundary so the desktop app does not
 * spread version-specific paths through its lifecycle code.
 */
export type CadgenContract = 'pinned-0.4' | 'step-first-0.5';

export type CadgenCapability = {
  contract: CadgenContract;
  version: string;
  manifestPath: string;
};

export type CadViewerCapability = {
  contract: CadgenContract;
  layout: 'bundled-skill' | 'repository-app' | 'repository-root';
  viewerRoot: string;
  launcher: string;
  urlContract: 'root-query';
  supportsCadgenPython: boolean;
};

const CAD_VIEWER_LAYOUTS: ReadonlyArray<
  Pick<CadViewerCapability, 'layout' | 'urlContract' | 'supportsCadgenPython'> & {
    relativeRoot: string;
  }
> = [
  {
    layout: 'repository-app',
    relativeRoot: join('apps', 'viewer'),
    urlContract: 'root-query',
    supportsCadgenPython: true,
  },
  {
    layout: 'bundled-skill',
    relativeRoot: join('skills', 'cad-viewer', 'scripts', 'viewer'),
    urlContract: 'root-query',
    supportsCadgenPython: true,
  },
  {
    layout: 'repository-root',
    relativeRoot: 'viewer',
    urlContract: 'root-query',
    supportsCadgenPython: true,
  },
];

export function resolveCadViewerCapability(pluginRoot: string): CadViewerCapability | null {
  for (const layout of CAD_VIEWER_LAYOUTS) {
    const viewerRoot = join(pluginRoot, layout.relativeRoot);
    const launcher = join(viewerRoot, 'server', 'main.mjs');
    if (!existsSync(launcher)) continue;
    const manifest = readJsonRecord(join(viewerRoot, 'package.json'));
    const contract = viewerManifestContract(manifest, pluginRoot);
    if (!contract) continue;
    return {
      contract,
      layout: layout.layout,
      viewerRoot,
      launcher,
      urlContract: layout.urlContract,
      supportsCadgenPython: layout.supportsCadgenPython,
    };
  }
  return null;
}

/** Resolve the installed Python runtime from its canonical package manifest. */
export function resolveCadgenCapability(pluginRoot: string): CadgenCapability | null {
  const manifestPath = join(pluginRoot, 'packages', 'cadgen', 'pyproject.toml');
  let source: string;
  try {
    source = readFileSync(manifestPath, 'utf8');
  } catch {
    return null;
  }
  const projectSection = source.match(/(?:^|\n)\[project\]\s*\n([\s\S]*?)(?=\n\[|$)/)?.[1];
  if (!projectSection) return null;
  const name = projectSection.match(/^\s*name\s*=\s*["']([^"']+)["']/m)?.[1];
  const version = projectSection.match(/^\s*version\s*=\s*["']([^"']+)["']/m)?.[1];
  const contract = version ? cadgenContractFromVersion(version) : null;
  return name === 'cadgen' && version && contract ? { contract, version, manifestPath } : null;
}

export function cadgenPythonEnvironment(
  environment: NodeJS.ProcessEnv,
  pythonExecutable: string | null | undefined
): NodeJS.ProcessEnv {
  const python = pythonExecutable?.trim();
  return python ? { ...environment, CADGEN_PYTHON: python } : { ...environment };
}

export type CadSourceArtifactRelationship = {
  workspacePath: string;
  relativeSourcePath: string;
  relativeModelPath: string;
  declaration: 'explicit' | 'out' | 'write' | 'sibling-default';
};

/** Normalize a persisted model/source pair from Hardcore's model catalog. */
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
 * Python. 0.5 renamed write= to out= and cad-project recipes commonly map
 * src/foo.py to STEP/foo.step with out="../STEP/foo.step". The retired write=
 * spelling remains readable while Hardcore is pinned to the 0.4-era contract.
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
    declaration: target?.keyword ?? 'sibling-default',
  };
}

export function cadStepOutputDeclaration(
  source: string
): { keyword: 'out' | 'write'; path: string } | null {
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
    // Prefer the current 0.5 spelling if malformed transitional source
    // happens to contain both declarations.
    for (const keyword of ['out', 'write'] as const) {
      const match = declaration.match(new RegExp(`\\b${keyword}\\s*=\\s*(['"])([^'"\\\\]+)\\1`));
      const path = match?.[2]?.trim();
      if (path) return { keyword, path };
    }
    return null;
  }
  return null;
}

export type CadRuntimeCommand = {
  tool: 'model' | 'cadgen';
  args: string[];
};

/** Direct model execution is established by both supported cadgen contracts. */
export function cadSourceRebuildToolPlan(
  relativeSourcePath: string,
  contract: CadgenContract
): CadRuntimeCommand {
  if (/\.(?:step|stp)\.py$/i.test(relativeSourcePath)) {
    throw new Error('Legacy .step.py recipes must be migrated before rebuilding.');
  }
  if (/\.py$/i.test(relativeSourcePath)) {
    // Both explicitly supported package contracts establish direct model
    // execution. Requiring the detected contract keeps future CLI changes from
    // being adopted solely because a directory happened to look like 0.5.
    if (contract !== 'pinned-0.4' && contract !== 'step-first-0.5') {
      throw new Error('The installed cadgen contract is not supported.');
    }
    return { tool: 'model', args: [relativeSourcePath, '--force', '--json'] };
  }
  throw new Error('A source rebuild requires a Python @step model.');
}

/**
 * Resolve the artifact reported after a build. cadPath is the established
 * machine result in pinned cadgen; the declared out=/write= relationship is
 * the bounded fallback when a compatible runner omits it.
 */
export function resolveCadBuildArtifactPath(input: {
  workspacePath: string;
  relativeSourcePath: string;
  build: Record<string, unknown>;
  contract: CadgenContract;
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

function viewerManifestContract(
  manifest: Record<string, unknown> | null,
  pluginRoot: string
): CadgenContract | null {
  if (!manifest || typeof manifest.name !== 'string') return null;
  if (manifest.name === 'cad-viewer') {
    return manifestVersionContract(manifest) ?? dependencyContract(manifest);
  }
  if (manifest.name !== 'cad-viewer-runtime') return null;

  // Released skills intentionally reduce the bundled runtime manifest to a
  // name and version. Its version is an established contract; the full root
  // Viewer manifest is an additional consistency check when present in a
  // development checkout.
  const runtimeContract = manifestVersionContract(manifest);
  const canonicalManifest = readJsonRecord(join(pluginRoot, 'viewer', 'package.json'));
  const canonicalContract = canonicalManifest
    ? (manifestVersionContract(canonicalManifest) ?? dependencyContract(canonicalManifest))
    : null;
  if (runtimeContract && canonicalContract && runtimeContract !== canonicalContract) return null;
  return runtimeContract ?? canonicalContract;
}

function dependencyContract(manifest: Record<string, unknown>): CadgenContract | null {
  const dependencies = isRecord(manifest.dependencies) ? manifest.dependencies : {};
  if (typeof dependencies['cadgen-js'] === 'string') return 'step-first-0.5';
  if (typeof dependencies.cadjs === 'string') return 'pinned-0.4';
  return null;
}

function manifestVersionContract(manifest: Record<string, unknown>): CadgenContract | null {
  return typeof manifest.version === 'string' ? cadgenContractFromVersion(manifest.version) : null;
}

function cadgenContractFromVersion(version: string): CadgenContract | null {
  const match = version.match(/^(\d+)\.(\d+)(?:\.|$)/);
  if (!match || Number(match[1]) !== 0) return null;
  if (Number(match[2]) === 4) return 'pinned-0.4';
  if (Number(match[2]) === 5) return 'step-first-0.5';
  return null;
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

function isLegacyPythonCadSource(path: string): boolean {
  return /\.(?:step|stp)\.py$/i.test(path);
}

function isSafeWorkspaceRelativePath(path: string): boolean {
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
