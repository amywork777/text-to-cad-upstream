import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { delimiter, dirname, isAbsolute, join, posix, relative, resolve, win32 } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const CAD_SKILL_PACKAGE = Object.freeze({
  marketplace: 'text-to-cad',
  source: 'vendor/text-to-cad',
  plugin: 'cad@text-to-cad',
  delivery: 'provider-plugin',
  version: '0.4.25',
  revision: '2a96f69670971435074937429babc4cc30f5298b',
});

const MARKETPLACE = CAD_SKILL_PACKAGE.marketplace;
const PLUGIN = CAD_SKILL_PACKAGE.plugin;
const MIN_CODEX_VERSION = [0, 142, 0];
const MIN_PYTHON_VERSION = [3, 11, 0];
const PROJECT_ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const PINNED_CADGEN_VERSION = '0.4.25';
const PINNED_PIP_VERSION = '25.2';
export const CAD_RUNTIME_CONSTRAINTS_PATH = join(
  PROJECT_ROOT,
  'tooling',
  'cad-runtime-constraints.txt'
);
const REQUIRED_CAD_DISTRIBUTIONS = ['build123d', 'cadquery-ocp', 'ezdxf', 'shapely'];
const CAD_IMPORTS = ['OCP', 'build123d', 'cadgen', 'cadgen.authoring', 'cadgen.cli'];
const BUNDLE_MARKER = '.hardcore-cad-bundle.json';
const RUNTIME_MARKER = '.hardcore-cad-runtime.json';

export function parseVersion(output) {
  const match = output.match(/(\d+)\.(\d+)\.(\d+)/);
  return match ? match.slice(1, 4).map(Number) : null;
}

export function compareVersions(left, right) {
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const delta = (left[index] ?? 0) - (right[index] ?? 0);
    if (delta !== 0) return Math.sign(delta);
  }
  return 0;
}

export function hasMarketplace(output) {
  return output.includes(MARKETPLACE);
}

export function hasMarketplaceRoot(output, root) {
  return hasMarketplace(output) && output.includes(root);
}

export function hasPlugin(output) {
  const entry = providerPluginEntry(output);
  if (!entry || /\bnot installed\b/i.test(entry)) return false;
  return /\binstalled,\s*enabled\b/i.test(entry) || /Status:\s*[^\n]*\benabled\b/i.test(entry);
}

export function parseCodexPluginRoot(output) {
  const line = providerPluginEntry(output)?.split('\n')[0];
  const match = line?.match(/installed,\s+enabled\s+\S+\s+(.+?)\s*$/);
  return match?.[1] ?? null;
}

export function parseCodexPluginVersion(output) {
  const line = providerPluginEntry(output)?.split('\n')[0];
  return line?.match(/installed,\s+enabled\s+(\S+)/)?.[1] ?? null;
}

export function parseClaudePluginVersion(output) {
  const entry = providerPluginEntry(output);
  if (!entry || !hasPlugin(entry)) return null;
  return entry.match(/Version:\s*(\S+)/)?.[1] ?? null;
}

function providerPluginEntry(output) {
  const lines = output.split('\n');
  const index = lines.findIndex((line) =>
    new RegExp(`(?:^|\\s|❯)${PLUGIN.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:\\s|$)`).test(line)
  );
  if (index === -1) return null;

  const entry = [lines[index]];
  for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
    const line = lines[cursor];
    if (/^\s*❯\s+\S+@\S+/.test(line) || /^Marketplace\s+`/.test(line)) break;
    if (/^\S+@\S+\s{2,}/.test(line)) break;
    entry.push(line);
  }
  return entry.join('\n');
}

export function resolveCommand(
  name,
  pathValue = process.env.PATH ?? '',
  platform = process.platform
) {
  if (isAbsolute(name) || /^[a-z]:[\\/]/i.test(name) || name.startsWith('\\\\')) return name;
  const hasWindowsExtension = /\.(?:bat|cmd|com|exe)$/i.test(name);
  const executable = platform === 'win32' && !hasWindowsExtension ? `${name}.cmd` : name;
  for (const directory of pathValue.split(delimiter)) {
    if (!directory || directory.includes('node_modules/.bin')) continue;
    const candidate = join(directory, executable);
    if (existsSync(candidate)) return candidate;
  }
  return executable;
}

export function providerPluginInstallPlan(provider, source = CAD_SKILL_PACKAGE.source) {
  if (provider === 'codex') {
    return [
      ['plugin', 'marketplace', 'add', source],
      ['plugin', 'add', PLUGIN],
    ];
  }
  if (provider === 'claude') {
    return [
      ['plugin', 'marketplace', 'add', source],
      ['plugin', 'install', PLUGIN],
    ];
  }
  throw new Error(`Unsupported CAD skill provider: ${provider}`);
}

export function resolveBundledPluginRoot(projectRoot = PROJECT_ROOT) {
  const root = join(projectRoot, CAD_SKILL_PACKAGE.source);
  const codexManifest = join(root, '.codex-plugin', 'plugin.json');
  const claudeManifest = join(root, '.claude-plugin', 'plugin.json');
  return existsSync(codexManifest) && existsSync(claudeManifest) ? root : null;
}

export function resolveCadRuntimeRoot(projectRoot = PROJECT_ROOT, environment = process.env) {
  const configured = environment.HARDCORE_CAD_RUNTIME_ROOT?.trim();
  return configured ? resolve(configured) : join(projectRoot, '.cad-runtime');
}

export function resolveStagedPluginRoot(runtimeRoot = resolveCadRuntimeRoot()) {
  return join(runtimeRoot, 'plugins', MARKETPLACE);
}

export function stageBundledPlugin(
  projectRoot = PROJECT_ROOT,
  runtimeRoot = resolveCadRuntimeRoot(projectRoot),
  { mutate = true } = {}
) {
  const source = resolveBundledPluginRoot(projectRoot);
  if (!source) throw new Error('Hardcore could not locate its bundled CAD plugin.');

  const target = resolveStagedPluginRoot(runtimeRoot);
  if (!mutate || stagedPluginIsCurrent(target)) return target;

  const staging = `${target}.staging-${process.pid}`;
  mkdirSync(dirname(target), { recursive: true });
  rmSync(staging, { recursive: true, force: true });
  try {
    cpSync(source, staging, {
      recursive: true,
      filter: (sourcePath) => shouldCopyBundledPluginPath(source, sourcePath),
    });
    writeFileSync(
      join(staging, BUNDLE_MARKER),
      `${JSON.stringify({ revision: CAD_SKILL_PACKAGE.revision })}\n`,
      'utf8'
    );
    rmSync(target, { recursive: true, force: true });
    renameSync(staging, target);
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  return target;
}

function stagedPluginIsCurrent(root) {
  const codexManifest = join(root, '.codex-plugin', 'plugin.json');
  const claudeManifest = join(root, '.claude-plugin', 'plugin.json');
  if (!existsSync(codexManifest) || !existsSync(claudeManifest)) return false;
  try {
    const marker = JSON.parse(readFileSync(join(root, BUNDLE_MARKER), 'utf8'));
    return marker.revision === CAD_SKILL_PACKAGE.revision;
  } catch {
    return false;
  }
}

function shouldCopyBundledPluginPath(root, sourcePath) {
  const path = relative(root, sourcePath);
  if (!path) return true;
  const segments = path.split(/[\\/]/);
  return (
    !segments.some((segment) => ['.git', '.venv', '__pycache__'].includes(segment)) &&
    !path.endsWith('.pyc')
  );
}

function capture(command, args, { environment = process.env, platform = process.platform } = {}) {
  const result = spawnSync(resolveCommand(command, environment.PATH ?? '', platform), args, {
    encoding: 'utf8',
    env: environment,
  });
  return {
    available: result.error?.code !== 'ENOENT',
    ok: result.status === 0,
    output: `${result.stdout ?? ''}${result.stderr ?? ''}`,
  };
}

function run(command, args, { environment = process.env } = {}) {
  const result = spawnSync(resolveCommand(command, environment.PATH ?? ''), args, {
    env: environment,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} exited with status ${result.status}`);
  }
}

export function parseCadRuntimeConstraints(source) {
  const versions = {};
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^([A-Za-z0-9_.-]+)==([^\s;]+)$/);
    if (!match) throw new Error(`Invalid CAD runtime constraint: ${rawLine}`);
    versions[normalizeDistributionName(match[1])] = match[2];
  }
  return versions;
}

export function cadRuntimeInstallPlan(
  executable,
  cadgenSource,
  constraintsPath = CAD_RUNTIME_CONSTRAINTS_PATH
) {
  return [
    {
      command: executable,
      args: [
        '-m',
        'pip',
        'install',
        '--disable-pip-version-check',
        '--upgrade',
        `pip==${PINNED_PIP_VERSION}`,
        'setuptools==80.9.0',
        'wheel==0.45.1',
      ],
    },
    {
      command: executable,
      args: [
        '-m',
        'pip',
        'install',
        '--disable-pip-version-check',
        '--force-reinstall',
        '--constraint',
        constraintsPath,
        cadgenSource,
      ],
      environment: {
        ...process.env,
        // PEP 517 build isolation launches a second pip process. Carry the
        // same lock into that process so setuptools cannot drift either.
        PIP_CONSTRAINT: constraintsPath,
      },
    },
  ];
}

function normalizeDistributionName(name) {
  return name.toLowerCase().replace(/[-_.]+/g, '-');
}

function cadRuntimeHealthcheckSource(constraintsPath) {
  return `
import importlib.metadata
import importlib.util
import pathlib
import re

def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()

expected = {}
for raw_line in pathlib.Path(${JSON.stringify(constraintsPath)}).read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    name, version = line.split("==", 1)
    expected[normalize(name)] = version

installed = {
    normalize(distribution.metadata["Name"]): distribution.version
    for distribution in importlib.metadata.distributions()
    if distribution.metadata.get("Name")
}
required = ${JSON.stringify(REQUIRED_CAD_DISTRIBUTIONS)}
wrong = sorted(
    name for name, version in installed.items()
    if name != "cadgen" and (name not in expected or expected[name] != version)
)
missing = sorted(name for name in required if installed.get(name) != expected.get(name))
missing_imports = any(
    importlib.util.find_spec(name) is None
    for name in ${JSON.stringify(CAD_IMPORTS)}
)
wrong_cadgen = importlib.metadata.version("cadgen") != ${JSON.stringify(PINNED_CADGEN_VERSION)}
raise SystemExit(bool(wrong or missing or missing_imports or wrong_cadgen))
`;
}

export function bootstrapPythonCommand(platform = process.platform, environment = process.env) {
  return bootstrapPythonCandidates(platform, environment)[0].command;
}

export function bootstrapPythonCandidates(platform = process.platform, environment = process.env) {
  const configured = environment.CAD_DESKTOP_BOOTSTRAP_PYTHON?.trim();
  if (configured) return [{ command: configured, args: [] }];
  return platform === 'win32'
    ? [
        { command: 'py.exe', args: ['-3.11'] },
        { command: 'python.exe', args: [] },
      ]
    : [
        { command: 'python3.11', args: [] },
        { command: 'python3', args: [] },
      ];
}

export function resolveBootstrapPython(
  platform = process.platform,
  environment = process.env,
  probe = (command, args) => capture(command, args, { environment, platform })
) {
  const attempts = [];
  for (const candidate of bootstrapPythonCandidates(platform, environment)) {
    const result = probe(candidate.command, [
      ...candidate.args,
      '-c',
      'import sys; print(".".join(map(str, sys.version_info[:3])))',
    ]);
    const version = parseVersion(result.output);
    attempts.push({ ...candidate, available: result.available, version });
    if (
      result.available &&
      result.ok &&
      version &&
      compareVersions(version, MIN_PYTHON_VERSION) >= 0
    ) {
      return { ...candidate, version };
    }
  }

  const detected = attempts
    .filter(({ available }) => available)
    .map(({ command, version }) => `${command} ${version?.join('.') ?? '(unusable)'}`)
    .join(', ');
  const detail = detected ? ` Detected: ${detected}.` : '';
  throw new Error(
    `Hardcore CAD requires Python 3.11 or newer; no compatible interpreter was found.${detail} Install Python 3.11+ and retry, or set CAD_DESKTOP_BOOTSTRAP_PYTHON to its executable.`
  );
}

function pythonExecutable(runtime) {
  return process.platform === 'win32'
    ? join(runtime, 'Scripts', 'python.exe')
    : join(runtime, 'bin', 'python');
}

export function managedRuntimeTransactionPaths(runtimeRoot) {
  return {
    runtime: join(runtimeRoot, 'venv'),
    generations: join(runtimeRoot, 'venv-generations'),
    next: join(runtimeRoot, '.venv-next'),
    backup: join(runtimeRoot, '.venv-backup'),
    marker: join(runtimeRoot, RUNTIME_MARKER),
    markerNext: join(runtimeRoot, `${RUNTIME_MARKER}.next`),
    markerBackup: join(runtimeRoot, `${RUNTIME_MARKER}.backup`),
    transaction: join(runtimeRoot, `${RUNTIME_MARKER}.transaction`),
  };
}

export function provisionManagedPythonEnvironment(
  runtimeRoot,
  prepare,
  { revision = CAD_SKILL_PACKAGE.revision } = {}
) {
  const paths = managedRuntimeTransactionPaths(runtimeRoot);
  recoverManagedPythonEnvironment(runtimeRoot);
  mkdirSync(paths.generations, { recursive: true });

  // Keep the environment at its final, versioned path. Moving a Python venv
  // after installation breaks the absolute shebangs in its console scripts.
  // The stable `venv` path is only a symlink/junction that can be swapped.
  const candidate = join(
    paths.generations,
    `candidate-${process.pid}-${Date.now()}-${randomUUID()}`
  );
  const transaction = {
    version: 1,
    candidate,
    hadRuntime: existsSync(paths.runtime),
    hadMarker: existsSync(paths.marker),
  };

  try {
    prepare(candidate);
    if (!existsSync(pythonExecutable(candidate))) {
      throw new Error(`CAD Python candidate is missing its interpreter: ${candidate}`);
    }

    removeManagedEnvironment(paths.next);
    symlinkSync(candidate, paths.next, process.platform === 'win32' ? 'junction' : 'dir');
    writeFileSync(paths.markerNext, `${JSON.stringify({ revision })}\n`, {
      encoding: 'utf8',
      flag: 'wx',
    });
    writeJsonAtomically(paths.transaction, transaction);

    try {
      if (transaction.hadRuntime) renameSync(paths.runtime, paths.backup);
      renameSync(paths.next, paths.runtime);
      if (transaction.hadMarker) renameSync(paths.marker, paths.markerBackup);
      renameSync(paths.markerNext, paths.marker);

      // Removing the journal is the commit point. Before it disappears, the
      // recovery path always prefers the previously working environment.
      unlinkSync(paths.transaction);
    } catch (error) {
      try {
        rollbackManagedPythonEnvironment(paths, transaction);
      } catch (rollbackError) {
        throw new Error(
          `CAD runtime update failed and its previous environment could not be restored: ${errorMessage(error)}; rollback failed: ${errorMessage(rollbackError)}`
        );
      }
      throw error;
    }

    // The new runtime is already committed and usable. Cleanup is retryable on
    // the next launch, so a locked old directory must not turn success into a
    // provisioning failure (notably on Windows).
    try {
      finalizeManagedPythonEnvironment(paths);
    } catch (error) {
      console.warn(`CAD runtime cleanup will be retried: ${errorMessage(error)}`);
    }
    return pythonExecutable(paths.runtime);
  } catch (error) {
    // Preparation failures occur before the transaction and leave the current
    // runtime untouched. A committed swap has no transaction to roll back.
    if (!existsSync(paths.transaction)) {
      removeManagedEnvironment(paths.next);
      removeManagedEnvironment(paths.markerNext);
      let canonicalCandidate = candidate;
      try {
        canonicalCandidate = realpathSync(candidate);
      } catch {
        // A failed preparation may leave only part of the candidate directory.
      }
      if (managedLinkTarget(paths.runtime, paths.generations) !== canonicalCandidate) {
        removeManagedEnvironment(candidate);
      }
    }
    throw error;
  }
}

export function recoverManagedPythonEnvironment(runtimeRoot) {
  const paths = managedRuntimeTransactionPaths(runtimeRoot);
  if (existsSync(paths.transaction)) {
    const transaction = readManagedRuntimeTransaction(paths);
    rollbackManagedPythonEnvironment(paths, transaction);
    return;
  }

  // No journal means a completed commit. Finish any cleanup interrupted after
  // the commit point; if the stable link itself is absent, prefer the backup.
  let restoredBackup = false;
  if (existsSync(paths.backup)) {
    if (existsSync(paths.runtime)) {
      cleanupManagedRuntimeBackup(paths);
    } else {
      renameSync(paths.backup, paths.runtime);
      restoredBackup = true;
    }
  }
  if (existsSync(paths.markerBackup)) {
    if (restoredBackup) {
      removeManagedEnvironment(paths.marker);
      renameSync(paths.markerBackup, paths.marker);
    } else if (existsSync(paths.marker)) {
      unlinkSync(paths.markerBackup);
    } else {
      renameSync(paths.markerBackup, paths.marker);
    }
  }
  removeManagedEnvironment(paths.next);
  removeManagedEnvironment(paths.markerNext);
  cleanupOrphanedRuntimeGenerations(paths);
}

function rollbackManagedPythonEnvironment(paths, transaction) {
  if (transaction.hadRuntime && existsSync(paths.backup)) {
    // Move the candidate link out of the way without recursively deleting it;
    // restoring the previous runtime is the first priority.
    if (existsSync(paths.runtime)) renameSync(paths.runtime, paths.next);
    renameSync(paths.backup, paths.runtime);
  } else if (!transaction.hadRuntime && !existsSync(paths.next) && existsSync(paths.runtime)) {
    // First-install transaction reached the new link before being interrupted.
    renameSync(paths.runtime, paths.next);
  }

  if (transaction.hadMarker && existsSync(paths.markerBackup)) {
    if (existsSync(paths.marker)) renameSync(paths.marker, paths.markerNext);
    renameSync(paths.markerBackup, paths.marker);
  } else if (!transaction.hadMarker && !existsSync(paths.markerNext) && existsSync(paths.marker)) {
    renameSync(paths.marker, paths.markerNext);
  }

  removeManagedEnvironment(paths.next);
  removeManagedEnvironment(paths.markerNext);
  removeManagedEnvironment(transaction.candidate);
  removeManagedEnvironment(paths.transaction);
  cleanupOrphanedRuntimeGenerations(paths);
}

function finalizeManagedPythonEnvironment(paths) {
  cleanupManagedRuntimeBackup(paths);
  removeManagedEnvironment(paths.markerBackup);
  removeManagedEnvironment(paths.next);
  removeManagedEnvironment(paths.markerNext);
  cleanupOrphanedRuntimeGenerations(paths);
}

function cleanupManagedRuntimeBackup(paths) {
  if (!existsSync(paths.backup)) return;
  const generation = managedLinkTarget(paths.backup, paths.generations);
  removeManagedEnvironment(paths.backup);
  if (generation) removeManagedEnvironment(generation);
}

function cleanupOrphanedRuntimeGenerations(paths) {
  if (!existsSync(paths.generations)) return;
  const active = managedLinkTarget(paths.runtime, paths.generations);
  for (const entry of readdirSync(paths.generations, { withFileTypes: true })) {
    const candidate = join(paths.generations, entry.name);
    let canonicalCandidate = candidate;
    try {
      canonicalCandidate = realpathSync(candidate);
    } catch {
      // A half-created generation is still safe to remove by its bounded path.
    }
    if (canonicalCandidate === active) continue;
    removeManagedEnvironment(candidate);
  }
}

function managedLinkTarget(link, generations) {
  try {
    if (!lstatSync(link).isSymbolicLink()) return null;
    const target = realpathSync(link);
    const boundary = realpathSync(generations);
    const path = relative(boundary, target);
    return path && !path.startsWith('..') && !isAbsolute(path) ? target : null;
  } catch {
    return null;
  }
}

function readManagedRuntimeTransaction(paths) {
  let value;
  try {
    value = JSON.parse(readFileSync(paths.transaction, 'utf8'));
  } catch (error) {
    throw new Error(`Could not recover the interrupted CAD runtime update: ${errorMessage(error)}`);
  }
  const candidate = typeof value?.candidate === 'string' ? resolve(value.candidate) : '';
  const generations = resolve(paths.generations);
  const candidatePath = relative(generations, candidate);
  if (
    value?.version !== 1 ||
    typeof value?.hadRuntime !== 'boolean' ||
    typeof value?.hadMarker !== 'boolean' ||
    !candidatePath ||
    candidatePath.startsWith('..') ||
    isAbsolute(candidatePath)
  ) {
    throw new Error('Could not recover the interrupted CAD runtime update: invalid journal.');
  }
  return { ...value, candidate };
}

function writeJsonAtomically(path, value) {
  const temporary = `${path}.${process.pid}-${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(value)}\n`, { encoding: 'utf8', flag: 'wx' });
    renameSync(temporary, path);
  } finally {
    removeManagedEnvironment(temporary);
  }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function pythonCheck(executable, runtimeRoot) {
  if (!executable || !existsSync(executable)) return false;
  if (!existsSync(CAD_RUNTIME_CONSTRAINTS_PATH)) return false;
  const result = spawnSync(executable, [
    '-c',
    cadRuntimeHealthcheckSource(CAD_RUNTIME_CONSTRAINTS_PATH),
  ]);
  if (result.status !== 0 || !runtimeRoot) return result.status === 0;
  try {
    const marker = JSON.parse(readFileSync(join(runtimeRoot, RUNTIME_MARKER), 'utf8'));
    return marker.revision === CAD_SKILL_PACKAGE.revision;
  } catch {
    return false;
  }
}

export function viewerRuntimeLinkPlan(pluginRoot, executable, platform = process.platform) {
  const path = platform === 'win32' ? win32 : posix;
  const environmentRoot = path.join(
    pluginRoot,
    'skills',
    'cad-viewer',
    'scripts',
    'viewer',
    '.venv'
  );
  return {
    environmentRoot,
    runtimeRoot: path.dirname(path.dirname(executable)),
    python: path.join(
      environmentRoot,
      platform === 'win32' ? 'Scripts' : 'bin',
      platform === 'win32' ? 'python.exe' : 'python'
    ),
    linkType: platform === 'win32' ? 'junction' : 'dir',
  };
}

function ensurePythonRuntime(cadgenSource, { mutate, runtimeRoot }) {
  const override = process.env.CAD_DESKTOP_PYTHON;
  if (override) {
    if (!pythonCheck(override)) {
      throw new Error(`CAD_DESKTOP_PYTHON is not a usable CAD backend: ${override}`);
    }
    return override;
  }

  recoverManagedPythonEnvironment(runtimeRoot);
  const runtime = join(runtimeRoot, 'venv');
  const executable = pythonExecutable(runtime);
  if (pythonCheck(executable, runtimeRoot)) return executable;
  if (!mutate) return null;

  const bootstrap = resolveBootstrapPython();
  console.log(`Preparing CAD Python runtime at ${runtime}`);
  return provisionManagedPythonEnvironment(runtimeRoot, (candidate) => {
    const candidateExecutable = pythonExecutable(candidate);
    run(bootstrap.command, [...bootstrap.args, '-m', 'venv', candidate]);
    for (const command of cadRuntimeInstallPlan(candidateExecutable, cadgenSource)) {
      run(command.command, command.args, {
        environment: command.environment ?? process.env,
      });
    }
    if (!pythonCheck(candidateExecutable)) {
      throw new Error(
        `CAD Python installed but required imports failed: ${CAD_IMPORTS.join(', ')}`
      );
    }
  });
}

export function ensureViewerPython(pluginRoot, executable, { mutate }) {
  if (!executable) return false;
  const plan = viewerRuntimeLinkPlan(pluginRoot, executable);
  if (pythonCheck(plan.python)) return true;
  if (!mutate) return false;

  mkdirSync(dirname(plan.environmentRoot), { recursive: true });
  removeManagedEnvironment(plan.environmentRoot);
  try {
    symlinkSync(plan.runtimeRoot, plan.environmentRoot, plan.linkType);
  } catch (error) {
    throw new Error(
      `Could not link the CAD Viewer to its pinned Python runtime: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  if (!pythonCheck(plan.python)) throw new Error(`CAD Python launcher failed: ${plan.python}`);
  return true;
}

function removeManagedEnvironment(environmentRoot) {
  try {
    if (lstatSync(environmentRoot).isSymbolicLink()) {
      unlinkSync(environmentRoot);
      return;
    }
    rmSync(environmentRoot, { recursive: true, force: true });
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return;
    throw error;
  }
}

function checkCodex({ mutate, pluginSourceRoot, refreshPlugin }) {
  const [addMarketplace, installPlugin] = providerPluginInstallPlan('codex', pluginSourceRoot);
  const versionResult = capture('codex', ['--version']);
  if (!versionResult.available) return { provider: 'Codex', available: false, ready: false };
  if (!versionResult.ok) throw new Error('Could not read the Codex version');

  const version = parseVersion(versionResult.output);
  if (!version || compareVersions(version, MIN_CODEX_VERSION) < 0) {
    throw new Error('Codex 0.142.0 or newer is required for repository-root plugins');
  }

  let marketplaces = capture('codex', ['plugin', 'marketplace', 'list']);
  if (!marketplaces.ok) throw new Error('Could not list Codex plugin marketplaces');
  if (
    mutate &&
    hasMarketplace(marketplaces.output) &&
    !hasMarketplaceRoot(marketplaces.output, pluginSourceRoot)
  ) {
    const existingPlugins = capture('codex', ['plugin', 'list']);
    if (hasPlugin(existingPlugins.output)) run('codex', ['plugin', 'remove', PLUGIN]);
    run('codex', ['plugin', 'marketplace', 'remove', MARKETPLACE]);
    marketplaces = capture('codex', ['plugin', 'marketplace', 'list']);
  }
  if (mutate && !hasMarketplaceRoot(marketplaces.output, pluginSourceRoot)) {
    run('codex', addMarketplace);
    marketplaces = capture('codex', ['plugin', 'marketplace', 'list']);
  }

  let plugins = capture('codex', ['plugin', 'list']);
  if (!plugins.ok) throw new Error('Could not list Codex plugins');
  if (
    mutate &&
    hasPlugin(plugins.output) &&
    (refreshPlugin || parseCodexPluginVersion(plugins.output) !== CAD_SKILL_PACKAGE.version)
  ) {
    run('codex', ['plugin', 'remove', PLUGIN]);
    plugins = capture('codex', ['plugin', 'list']);
  }
  if (mutate && !hasPlugin(plugins.output)) {
    run('codex', installPlugin);
    plugins = capture('codex', ['plugin', 'list']);
    if (!hasPlugin(plugins.output)) {
      run('codex', installPlugin);
      plugins = capture('codex', ['plugin', 'list']);
    }
  }

  const pluginCurrent =
    hasPlugin(plugins.output) &&
    parseCodexPluginVersion(plugins.output) === CAD_SKILL_PACKAGE.version;
  return {
    provider: 'Codex',
    available: true,
    version: version.join('.'),
    marketplace: hasMarketplaceRoot(marketplaces.output, pluginSourceRoot),
    plugin: pluginCurrent,
    pluginRoot: pluginCurrent ? parseCodexPluginRoot(plugins.output) : null,
    ready: hasMarketplaceRoot(marketplaces.output, pluginSourceRoot) && pluginCurrent,
  };
}

function checkClaude({ mutate, pluginSourceRoot, refreshPlugin }) {
  const [addMarketplace, installPlugin] = providerPluginInstallPlan('claude', pluginSourceRoot);
  const versionResult = capture('claude', ['--version']);
  if (!versionResult.available) return { provider: 'Claude Code', available: false, ready: false };
  if (!versionResult.ok) throw new Error('Could not read the Claude Code version');

  let marketplaces = capture('claude', ['plugin', 'marketplace', 'list']);
  if (!marketplaces.ok) throw new Error('Could not list Claude Code plugin marketplaces');
  if (
    mutate &&
    hasMarketplace(marketplaces.output) &&
    !hasMarketplaceRoot(marketplaces.output, pluginSourceRoot)
  ) {
    const existingPlugins = capture('claude', ['plugin', 'list']);
    if (hasPlugin(existingPlugins.output))
      run('claude', ['plugin', 'uninstall', PLUGIN, '--keep-data']);
    run('claude', ['plugin', 'marketplace', 'remove', MARKETPLACE]);
    marketplaces = capture('claude', ['plugin', 'marketplace', 'list']);
  }
  if (mutate && !hasMarketplaceRoot(marketplaces.output, pluginSourceRoot)) {
    run('claude', addMarketplace);
    marketplaces = capture('claude', ['plugin', 'marketplace', 'list']);
  }

  let plugins = capture('claude', ['plugin', 'list']);
  if (!plugins.ok) throw new Error('Could not list Claude Code plugins');
  if (
    mutate &&
    hasPlugin(plugins.output) &&
    (refreshPlugin || parseClaudePluginVersion(plugins.output) !== CAD_SKILL_PACKAGE.version)
  ) {
    run('claude', ['plugin', 'uninstall', PLUGIN, '--keep-data']);
    plugins = capture('claude', ['plugin', 'list']);
  }
  if (mutate && !hasPlugin(plugins.output)) {
    run('claude', installPlugin);
    plugins = capture('claude', ['plugin', 'list']);
    if (!hasPlugin(plugins.output)) {
      run('claude', installPlugin);
      plugins = capture('claude', ['plugin', 'list']);
    }
  }

  const version = parseVersion(versionResult.output);
  const pluginVersion = parseClaudePluginVersion(plugins.output);
  const pluginCurrent = pluginVersion === CAD_SKILL_PACKAGE.version;
  return {
    provider: 'Claude Code',
    available: true,
    version: version?.join('.') ?? versionResult.output.trim(),
    marketplace: hasMarketplaceRoot(marketplaces.output, pluginSourceRoot),
    plugin: pluginCurrent,
    pluginRoot: pluginCurrent
      ? join(
          process.env.HOME ?? '',
          '.claude',
          'plugins',
          'cache',
          MARKETPLACE,
          'cad',
          pluginVersion
        )
      : null,
    ready: hasMarketplaceRoot(marketplaces.output, pluginSourceRoot) && pluginCurrent,
  };
}

export function parseOptions(args) {
  const check = args.includes('--check');
  const runtimeOnly = args.includes('--runtime-only');
  const providerArg = args.find((arg) => arg.startsWith('--provider='));
  const provider = providerArg?.slice('--provider='.length) ?? 'all';
  if (!['all', 'codex', 'claude'].includes(provider)) {
    throw new Error('--provider must be all, codex, or claude');
  }
  if (runtimeOnly && provider !== 'all') {
    throw new Error('--runtime-only cannot be combined with --provider');
  }
  return { check, provider, runtimeOnly };
}

function printStatus(status) {
  if (!status.available) {
    console.log(`${status.provider}: not installed (skipped)`);
    return;
  }
  const state = status.ready
    ? 'ready (plugin + Python backend)'
    : status.plugin
      ? 'CAD Python backend missing'
      : 'CAD plugin missing';
  console.log(`${status.provider} ${status.version}: ${state}`);
}

export function main(args = process.argv.slice(2)) {
  const options = parseOptions(args);
  const runtimeRoot = resolveCadRuntimeRoot();
  const stagedRoot = resolveStagedPluginRoot(runtimeRoot);
  const refreshPlugin = !stagedPluginIsCurrent(stagedRoot);
  const pluginSourceRoot = stageBundledPlugin(PROJECT_ROOT, runtimeRoot, {
    mutate: !options.check,
  });
  const cadgenSource = join(pluginSourceRoot, 'packages', 'cadgen');
  if (options.runtimeOnly) {
    const executable = ensurePythonRuntime(cadgenSource, {
      mutate: !options.check,
      runtimeRoot,
    });
    if (!executable) {
      throw new Error('The bundled CAD Python runtime has not been provisioned.');
    }
    if (!ensureViewerPython(pluginSourceRoot, executable, { mutate: !options.check })) {
      throw new Error('The bundled CAD Viewer could not access the pinned Python runtime.');
    }
    console.log(`CAD Python runtime: ready (${executable})`);
    return;
  }

  const checks = [];
  if (options.provider === 'all' || options.provider === 'codex') {
    checks.push(checkCodex({ mutate: !options.check, pluginSourceRoot, refreshPlugin }));
  }
  if (options.provider === 'all' || options.provider === 'claude') {
    checks.push(checkClaude({ mutate: !options.check, pluginSourceRoot, refreshPlugin }));
  }

  const installed = checks.filter((status) => status.available && status.ready);
  const runtimeAvailable =
    installed.some((status) => status.pluginRoot) &&
    existsSync(join(cadgenSource, 'pyproject.toml'));
  const executable = runtimeAvailable
    ? ensurePythonRuntime(cadgenSource, {
        mutate: !options.check,
        runtimeRoot,
      })
    : null;
  for (const status of installed) {
    status.ready = Boolean(
      status.pluginRoot &&
      ensureViewerPython(status.pluginRoot, executable, { mutate: !options.check })
    );
  }
  checks.forEach(printStatus);

  const available = checks.filter((status) => status.available);
  if (available.length === 0) throw new Error('Neither Codex nor Claude Code is installed');
  if (available.some((status) => !status.ready)) process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
