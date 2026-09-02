import { execFileSync, spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdtempSync, rmSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { basename, delimiter, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  parseClaudePluginVersion,
  parseCodexPluginRoot,
  resolveCadRuntimeRoot,
  resolveCommand,
} from './setup-cad.mjs';

const PROJECT_ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const JAKE_TEST_CHECKOUT = resolve(
  process.env.JAKE_TEST_CHECKOUT ?? join(PROJECT_ROOT, 'vendor', 'text-to-cad')
);
const CAD_RUNTIME_ROOT = resolveCadRuntimeRoot(PROJECT_ROOT);
const PYTHON = join(
  CAD_RUNTIME_ROOT,
  'venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'
);

function capture(command, args) {
  return execFileSync(resolveCommand(command), args, { encoding: 'utf8' });
}

function run(label, command, args, options = {}) {
  console.log(`\n==> ${label}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? PROJECT_ROOT,
    env: {
      ...process.env,
      PATH: [dirname(process.execPath), process.env.PATH].filter(Boolean).join(delimiter),
      ...options.env,
    },
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${label} failed with status ${result.status}`);
}

function installedProviders() {
  const codexOutput = capture('codex', ['plugin', 'list']);
  const claudeOutput = capture('claude', ['plugin', 'list']);
  const claudeVersion = parseClaudePluginVersion(claudeOutput);
  return [
    { name: 'Codex', root: parseCodexPluginRoot(codexOutput) },
    {
      name: 'Claude Code',
      root: claudeVersion
        ? join(homedir(), '.claude', 'plugins', 'cache', 'text-to-cad', 'cad', claudeVersion)
        : null,
    },
  ];
}

function main() {
  run('CAD integration health check', process.execPath, [
    join(PROJECT_ROOT, 'tooling/scripts/setup-cad.mjs'),
    '--check',
  ]);

  if (!existsSync(PYTHON)) throw new Error('CAD Python runtime is missing; run pnpm cad:setup');
  const viewerTest = join(JAKE_TEST_CHECKOUT, 'scripts/test/test-viewer-launch.sh');
  if (!existsSync(viewerTest)) {
    throw new Error(
      `Jake test checkout is missing. Set JAKE_TEST_CHECKOUT or create ${JAKE_TEST_CHECKOUT}`
    );
  }

  const providers = installedProviders();
  for (const provider of providers) {
    if (!provider.root || !existsSync(provider.root)) {
      throw new Error(`${provider.name} CAD plugin root was not found`);
    }
  }

  run("Jake's selected release/0.5 Python tests", PYTHON, [
    join(PROJECT_ROOT, 'tooling/scripts/run-jake-cad-tests.py'),
    '--tests-root',
    JAKE_TEST_CHECKOUT,
  ]);
  run("Jake's bundled viewer launch/import test", 'bash', [viewerTest]);

  const scratch = mkdtempSync(join(tmpdir(), 'emdash-cad-'));
  try {
    const source = join(scratch, basename('emdash-smoke.py'));
    const step = join(scratch, 'emdash-smoke.step');
    copyFileSync(join(PROJECT_ROOT, 'tooling/fixtures/cad/emdash-smoke.py'), source);

    run(
      'Bundled 0.5 runtime: generate a real STEP artifact',
      PYTHON,
      [basename(source), '--force', '--json'],
      { cwd: scratch }
    );
    if (!existsSync(step)) throw new Error(`generator did not write ${step}`);

    run(
      'Bundled 0.5 runtime: validate the generated STEP artifact',
      PYTHON,
      ['-m', 'cadgen.cli', 'step', 'inspect', 'validate', basename(step)],
      { cwd: scratch }
    );
    run(
      'Bundled 0.5 runtime: inspect topology and bounds',
      PYTHON,
      ['-m', 'cadgen.cli', 'step', 'inspect', 'refs', basename(step), '--facts'],
      { cwd: scratch }
    );
    console.log(`\nCross-provider CAD artifact passed: ${step}`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
