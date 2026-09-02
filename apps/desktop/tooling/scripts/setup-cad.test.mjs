import assert from 'node:assert/strict';
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import {
  CAD_RUNTIME_CONSTRAINTS_PATH,
  CAD_SKILL_PACKAGE,
  bootstrapPythonCandidates,
  bootstrapPythonCommand,
  cadRuntimeInstallPlan,
  compareVersions,
  ensureViewerPython,
  hasMarketplace,
  hasMarketplaceRoot,
  hasPlugin,
  managedRuntimeTransactionPaths,
  parseClaudePluginVersion,
  parseCodexPluginRoot,
  parseCodexPluginVersion,
  parseCadRuntimeConstraints,
  parseOptions,
  parseVersion,
  providerPluginInstallPlan,
  provisionManagedPythonEnvironment,
  recoverManagedPythonEnvironment,
  resolveBootstrapPython,
  resolveBundledPluginRoot,
  resolveCadRuntimeRoot,
  resolveCommand,
  resolveStagedPluginRoot,
  stageBundledPlugin,
  viewerRuntimeLinkPlan,
} from './setup-cad.mjs';

test("ships Jake's complete CAD plugin to both supported agents", () => {
  assert.deepEqual(CAD_SKILL_PACKAGE, {
    marketplace: 'text-to-cad',
    source: 'vendor/text-to-cad',
    plugin: 'cad@text-to-cad',
    delivery: 'provider-plugin',
    version: '0.4.25',
    revision: '2a96f69670971435074937429babc4cc30f5298b',
  });
  assert.deepEqual(providerPluginInstallPlan('codex', '/Applications/Hardcore/CAD'), [
    ['plugin', 'marketplace', 'add', '/Applications/Hardcore/CAD'],
    ['plugin', 'add', 'cad@text-to-cad'],
  ]);
  assert.deepEqual(providerPluginInstallPlan('claude', '/Applications/Hardcore/CAD'), [
    ['plugin', 'marketplace', 'add', '/Applications/Hardcore/CAD'],
    ['plugin', 'install', 'cad@text-to-cad'],
  ]);
  assert.throws(() => providerPluginInstallPlan('other'), /Unsupported CAD skill provider/);
});

test('parses provider CLI versions', () => {
  assert.deepEqual(parseVersion('codex-cli 0.148.0'), [0, 148, 0]);
  assert.deepEqual(parseVersion('2.1.237 (Claude Code)'), [2, 1, 237]);
  assert.equal(parseVersion('unknown'), null);
});

test('compares semantic version tuples', () => {
  assert.equal(compareVersions([0, 148, 0], [0, 142, 0]), 1);
  assert.equal(compareVersions([0, 142, 0], [0, 142, 0]), 0);
  assert.equal(compareVersions([0, 141, 9], [0, 142, 0]), -1);
});

test('locks every installed CAD dependency and carries the lock into build isolation', () => {
  const constraints = parseCadRuntimeConstraints(
    readFileSync(CAD_RUNTIME_CONSTRAINTS_PATH, 'utf8')
  );
  assert.equal(constraints.build123d, '0.11.1');
  assert.equal(constraints['cadquery-ocp'], '7.9.3.1.1');
  assert.equal(constraints.ezdxf, '1.4.4');
  assert.equal(constraints.shapely, '2.1.2');
  // IPython selects colorama only on Windows. Keep that platform-only edge
  // locked too, or the strict runtime health check will reject Windows installs.
  assert.equal(constraints.colorama, '0.4.6');
  assert.equal(constraints.pip, '25.2');
  assert.ok(Object.keys(constraints).length > 40);

  const plan = cadRuntimeInstallPlan('/runtime/python', '/bundle/cadgen', '/bundle/lock.txt');
  assert.deepEqual(plan[0], {
    command: '/runtime/python',
    args: [
      '-m',
      'pip',
      'install',
      '--disable-pip-version-check',
      '--upgrade',
      'pip==25.2',
      'setuptools==80.9.0',
      'wheel==0.45.1',
    ],
  });
  assert.deepEqual(plan[1].args.slice(-3), ['--constraint', '/bundle/lock.txt', '/bundle/cadgen']);
  assert.equal(plan[1].environment.PIP_CONSTRAINT, '/bundle/lock.txt');
});

test('rejects a drifting or ranged CAD runtime constraint', () => {
  assert.throws(
    () => parseCadRuntimeConstraints('build123d>=0.11\n'),
    /Invalid CAD runtime constraint/
  );
});

test('recognizes the marketplace and plugin in provider output', () => {
  assert.equal(hasMarketplace('text-to-cad  /tmp/marketplaces/text-to-cad'), true);
  assert.equal(
    hasMarketplaceRoot('text-to-cad  /Applications/Hardcore/CAD', '/Applications/Hardcore/CAD'),
    true
  );
  assert.equal(
    hasMarketplaceRoot('text-to-cad  /tmp/marketplaces/text-to-cad', '/Applications/Hardcore/CAD'),
    false
  );
  assert.equal(hasPlugin('cad@text-to-cad installed, enabled 0.4.23'), true);
  assert.equal(
    hasPlugin('cad@text-to-cad  not installed           /Applications/Hardcore.app/CAD'),
    false
  );
  assert.equal(
    hasPlugin(`❯ cad@text-to-cad
    Version: 0.4.28
    Scope: user
    Status: ✔ enabled`),
    true
  );
  assert.equal(hasPlugin('unrelated@marketplace'), false);
});

test('finds the checked-in plugin bundle and rejects incomplete roots', () => {
  assert.equal(
    resolveBundledPluginRoot(new URL('../..', import.meta.url).pathname),
    new URL('../../vendor/text-to-cad', import.meta.url).pathname.replace(/\/$/, '')
  );
  assert.equal(resolveBundledPluginRoot('/tmp/missing-hardcore-root'), null);
});

test('finds the installed plugin root and version in provider output', () => {
  assert.equal(
    parseCodexPluginRoot(
      'cad@text-to-cad  installed, enabled  0.4.23  /tmp/marketplaces/text-to-cad  \n'
    ),
    '/tmp/marketplaces/text-to-cad'
  );
  assert.equal(
    parseCodexPluginVersion(
      'cad@text-to-cad  installed, enabled  0.4.25  /tmp/marketplaces/text-to-cad'
    ),
    '0.4.25'
  );
  assert.equal(
    parseClaudePluginVersion('❯ cad@text-to-cad\n    Version: 0.4.23\n    Scope: user'),
    null
  );
  assert.equal(
    parseClaudePluginVersion(
      '❯ cad@text-to-cad\n    Version: 0.4.23\n    Scope: user\n    Status: ✔ enabled'
    ),
    '0.4.23'
  );
  assert.equal(parseClaudePluginVersion('Version: 9.9.9\nno CAD plugin'), null);
  assert.equal(
    parseCodexPluginRoot('cad@text-to-cad  not installed           /Applications/Hardcore.app/CAD'),
    null
  );
  assert.equal(
    parseCodexPluginVersion(
      'cad@text-to-cad  not installed           /Applications/Hardcore.app/CAD'
    ),
    null
  );
});

test('stages mutable CAD plugin files outside the read-only bundle', (context) => {
  const projectRoot = mkdtempSync(join(tmpdir(), 'hardcore-bundled-cad-'));
  const userDataRoot = mkdtempSync(join(tmpdir(), 'hardcore-user-data-'));
  context.after(() => {
    rmSync(projectRoot, { recursive: true, force: true });
    rmSync(userDataRoot, { recursive: true, force: true });
  });

  const bundledRoot = join(projectRoot, CAD_SKILL_PACKAGE.source);
  mkdirSync(join(bundledRoot, '.codex-plugin'), { recursive: true });
  mkdirSync(join(bundledRoot, '.claude-plugin'), { recursive: true });
  mkdirSync(join(bundledRoot, 'skills', 'cad', '__pycache__'), { recursive: true });
  mkdirSync(join(bundledRoot, 'skills', 'cad-viewer', '.venv'), { recursive: true });
  writeFileSync(join(bundledRoot, '.codex-plugin', 'plugin.json'), '{}');
  writeFileSync(join(bundledRoot, '.claude-plugin', 'plugin.json'), '{}');
  writeFileSync(join(bundledRoot, 'skills', 'cad', 'SKILL.md'), 'CAD');
  writeFileSync(join(bundledRoot, 'skills', 'cad', '__pycache__', 'runtime.pyc'), 'cache');
  writeFileSync(join(bundledRoot, 'skills', 'cad-viewer', '.venv', 'python'), 'shim');

  const runtimeRoot = resolveCadRuntimeRoot(projectRoot, {
    HARDCORE_CAD_RUNTIME_ROOT: join(userDataRoot, 'cad-runtime'),
  });
  const stagedRoot = stageBundledPlugin(projectRoot, runtimeRoot);

  assert.equal(stagedRoot, resolveStagedPluginRoot(runtimeRoot));
  assert.equal(readFileSync(join(stagedRoot, 'skills', 'cad', 'SKILL.md'), 'utf8'), 'CAD');
  assert.equal(existsSync(join(stagedRoot, 'skills', 'cad', '__pycache__')), false);
  assert.equal(existsSync(join(stagedRoot, 'skills', 'cad-viewer', '.venv')), false);
  assert.equal(stagedRoot.startsWith(projectRoot), false);
});

test('resolves the development CAD runtime locally unless an external root is configured', () => {
  assert.equal(resolveCadRuntimeRoot('/project', {}), join('/project', '.cad-runtime'));
  assert.equal(
    resolveCadRuntimeRoot('/project', { HARDCORE_CAD_RUNTIME_ROOT: '/user-data/cad-runtime' }),
    '/user-data/cad-runtime'
  );
});

test('links viewer Python paths to the shared runtime on Unix and Windows', () => {
  assert.deepEqual(
    viewerRuntimeLinkPlan(
      '/Applications/Hardcore CAD/plugin',
      '/Users/Amy/Library/Application Support/Hardcore/cad-runtime/venv/bin/python',
      'darwin'
    ),
    {
      environmentRoot: '/Applications/Hardcore CAD/plugin/skills/cad-viewer/scripts/viewer/.venv',
      runtimeRoot: '/Users/Amy/Library/Application Support/Hardcore/cad-runtime/venv',
      python: '/Applications/Hardcore CAD/plugin/skills/cad-viewer/scripts/viewer/.venv/bin/python',
      linkType: 'dir',
    }
  );
  assert.deepEqual(
    viewerRuntimeLinkPlan(
      'C:\\Users\\Amy\\.codex\\plugins\\cad',
      'C:\\Users\\Amy\\AppData\\Roaming\\Hardcore\\cad-runtime\\venv\\Scripts\\python.exe',
      'win32'
    ),
    {
      environmentRoot:
        'C:\\Users\\Amy\\.codex\\plugins\\cad\\skills\\cad-viewer\\scripts\\viewer\\.venv',
      runtimeRoot: 'C:\\Users\\Amy\\AppData\\Roaming\\Hardcore\\cad-runtime\\venv',
      python:
        'C:\\Users\\Amy\\.codex\\plugins\\cad\\skills\\cad-viewer\\scripts\\viewer\\.venv\\Scripts\\python.exe',
      linkType: 'junction',
    }
  );
});

test('provisions a working viewer link without copying or rewriting Python', (context) => {
  if (process.platform === 'win32') return;
  const root = mkdtempSync(join(tmpdir(), 'hardcore-viewer-python-'));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  const pluginRoot = join(root, 'plugin');
  const runtimeRoot = join(root, 'runtime', 'venv');
  const executable = join(runtimeRoot, 'bin', 'python');
  mkdirSync(join(pluginRoot, 'skills', 'cad-viewer', 'scripts', 'viewer'), {
    recursive: true,
  });
  mkdirSync(join(runtimeRoot, 'bin'), { recursive: true });
  writeFileSync(executable, '#!/bin/sh\nexit 0\n');
  chmodSync(executable, 0o755);

  assert.equal(ensureViewerPython(pluginRoot, executable, { mutate: true }), true);
  const viewerEnvironment = join(pluginRoot, 'skills', 'cad-viewer', 'scripts', 'viewer', '.venv');
  assert.equal(lstatSync(viewerEnvironment).isSymbolicLink(), true);
  assert.equal(realpathSync(viewerEnvironment), realpathSync(runtimeRoot));
});

test('commits a verified Python environment without moving its installed path', (context) => {
  if (process.platform === 'win32') return;
  const root = mkdtempSync(join(tmpdir(), 'hardcore-staged-python-'));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  const runtimeRoot = join(root, 'runtime');

  const executable = provisionManagedPythonEnvironment(runtimeRoot, (candidate) => {
    const python = join(candidate, 'bin', 'python');
    mkdirSync(join(candidate, 'bin'), { recursive: true });
    writeFileSync(python, '#!/bin/sh\nexit 0\n');
    chmodSync(python, 0o755);
    writeFileSync(join(candidate, 'bin', 'cadgen'), `#!${python}\n`);
  });

  const paths = managedRuntimeTransactionPaths(runtimeRoot);
  const generation = realpathSync(paths.runtime);
  const installedPath = readlinkSync(paths.runtime);
  assert.equal(lstatSync(paths.runtime).isSymbolicLink(), true);
  assert.equal(executable, join(paths.runtime, 'bin', 'python'));
  assert.equal(
    readFileSync(join(generation, 'bin', 'cadgen'), 'utf8'),
    `#!${installedPath}/bin/python\n`
  );
  assert.deepEqual(JSON.parse(readFileSync(paths.marker, 'utf8')), {
    revision: CAD_SKILL_PACKAGE.revision,
  });
  assert.equal(existsSync(paths.backup), false);
  assert.equal(existsSync(paths.transaction), false);
});

test('keeps the previous Python environment when candidate preparation fails', (context) => {
  if (process.platform === 'win32') return;
  const root = mkdtempSync(join(tmpdir(), 'hardcore-staged-python-'));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  const runtimeRoot = join(root, 'runtime');
  const paths = managedRuntimeTransactionPaths(runtimeRoot);
  mkdirSync(join(paths.runtime, 'bin'), { recursive: true });
  writeFileSync(join(paths.runtime, 'bin', 'python'), 'old-python');
  writeFileSync(join(paths.runtime, 'known-good'), 'preserve me');
  writeFileSync(paths.marker, '{"revision":"old"}\n');

  assert.throws(
    () =>
      provisionManagedPythonEnvironment(runtimeRoot, (candidate) => {
        mkdirSync(join(candidate, 'bin'), { recursive: true });
        writeFileSync(join(candidate, 'bin', 'python'), 'new-python');
        throw new Error('network unavailable');
      }),
    /network unavailable/
  );

  assert.equal(readFileSync(join(paths.runtime, 'known-good'), 'utf8'), 'preserve me');
  assert.equal(readFileSync(paths.marker, 'utf8'), '{"revision":"old"}\n');
  assert.equal(existsSync(paths.backup), false);
  assert.equal(existsSync(paths.transaction), false);
  assert.deepEqual(readdirSync(paths.generations), []);
});

test('rolls an interrupted runtime swap back to the known-good environment', (context) => {
  if (process.platform === 'win32') return;
  const root = mkdtempSync(join(tmpdir(), 'hardcore-staged-python-'));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  const runtimeRoot = join(root, 'runtime');
  const paths = managedRuntimeTransactionPaths(runtimeRoot);
  const candidate = join(paths.generations, 'candidate-interrupted');
  mkdirSync(join(candidate, 'bin'), { recursive: true });
  writeFileSync(join(candidate, 'bin', 'python'), 'new-python');
  mkdirSync(join(paths.backup, 'bin'), { recursive: true });
  writeFileSync(join(paths.backup, 'bin', 'python'), 'old-python');
  writeFileSync(join(paths.backup, 'known-good'), 'preserve me');
  symlinkSync(candidate, paths.runtime, 'dir');
  writeFileSync(paths.marker, '{"revision":"new"}\n');
  writeFileSync(paths.markerBackup, '{"revision":"old"}\n');
  writeFileSync(
    paths.transaction,
    `${JSON.stringify({
      version: 1,
      candidate,
      hadRuntime: true,
      hadMarker: true,
    })}\n`
  );

  recoverManagedPythonEnvironment(runtimeRoot);

  assert.equal(lstatSync(paths.runtime).isSymbolicLink(), false);
  assert.equal(readFileSync(join(paths.runtime, 'known-good'), 'utf8'), 'preserve me');
  assert.equal(readFileSync(paths.marker, 'utf8'), '{"revision":"old"}\n');
  assert.equal(existsSync(candidate), false);
  assert.equal(existsSync(paths.backup), false);
  assert.equal(existsSync(paths.transaction), false);
});

test('parses setup options', () => {
  assert.deepEqual(parseOptions([]), { check: false, provider: 'all', runtimeOnly: false });
  assert.deepEqual(parseOptions(['--check', '--provider=codex']), {
    check: true,
    provider: 'codex',
    runtimeOnly: false,
  });
  assert.deepEqual(parseOptions(['--runtime-only']), {
    check: false,
    provider: 'all',
    runtimeOnly: true,
  });
  assert.throws(() => parseOptions(['--runtime-only', '--provider=codex']), /cannot be combined/);
  assert.throws(() => parseOptions(['--provider=other']), /all, codex, or claude/);
});

test('uses the native Python launcher when bootstrapping the pinned runtime', () => {
  assert.equal(bootstrapPythonCommand('win32', {}), 'py.exe');
  assert.equal(bootstrapPythonCommand('darwin', {}), 'python3.11');
  assert.equal(bootstrapPythonCommand('linux', {}), 'python3.11');
  assert.equal(
    bootstrapPythonCommand('linux', { CAD_DESKTOP_BOOTSTRAP_PYTHON: '/opt/python' }),
    '/opt/python'
  );
  assert.deepEqual(bootstrapPythonCandidates('win32', {}), [
    { command: 'py.exe', args: ['-3.11'] },
    { command: 'python.exe', args: [] },
  ]);
});

test('preflights Python 3.11+ and falls back across native launchers', () => {
  const calls = [];
  const selected = resolveBootstrapPython('win32', {}, (command, args) => {
    calls.push([command, args]);
    return command === 'py.exe'
      ? { available: true, ok: false, output: 'Requested Python version not installed' }
      : { available: true, ok: true, output: '3.12.4\n' };
  });
  assert.deepEqual(selected, { command: 'python.exe', args: [], version: [3, 12, 4] });
  assert.equal(calls[0][0], 'py.exe');
  assert.deepEqual(calls[0][1].slice(0, 1), ['-3.11']);
});

test('reports an actionable preflight error instead of promising automatic Python install', () => {
  assert.throws(
    () =>
      resolveBootstrapPython('linux', {}, () => ({
        available: true,
        ok: true,
        output: '3.10.14\n',
      })),
    /requires Python 3\.11 or newer.*Install Python 3\.11\+/s
  );
});

test('ignores project-local CLI shims when resolving providers', () => {
  const separator = process.platform === 'win32' ? ';' : ':';
  const resolved = resolveCommand(
    'missing-provider',
    [`/project/node_modules/.bin`, `/also/missing`].join(separator)
  );
  assert.equal(
    resolved,
    process.platform === 'win32' ? 'missing-provider.cmd' : 'missing-provider'
  );
});

test('keeps native Windows executables distinct from provider command shims', (context) => {
  const root = mkdtempSync(join(tmpdir(), 'hardcore-windows-commands-'));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  writeFileSync(join(root, 'python.exe'), 'fixture');
  writeFileSync(join(root, 'codex.cmd'), 'fixture');

  assert.equal(resolveCommand('python.exe', root, 'win32'), join(root, 'python.exe'));
  assert.equal(resolveCommand('codex', root, 'win32'), join(root, 'codex.cmd'));
  assert.equal(
    resolveCommand('C:\\Python311\\python.exe', root, 'win32'),
    'C:\\Python311\\python.exe'
  );
});
