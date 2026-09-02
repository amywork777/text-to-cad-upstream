import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, posix, resolve, win32 } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { findPackagedCadBundleRoots } from './cad-resources.ts';
import { fail, info, step } from './lib/log.ts';

const SMOKE_MODEL = `from cadgen import build123d as bd
from cadgen import step

@step()
def packaged_smoke():
    plate = bd.Box(30, 20, 6)
    hole = bd.Pos(0, 0, -1) * bd.Cylinder(3, 8)
    return plate - hole
`;

const PARALLEL_SMOKE_MODEL = `from cadgen import build123d as bd
from cadgen import step

@step()
def packaged_parallel_smoke():
    return bd.Box(18, 12, 4)
`;

export interface PackagedCadSmokePlan {
  bundleRoot: string;
  setupScript: string;
  constraints: string;
  bundledCadgenSource: string;
  installedCadgenSource: string;
  runtimeRoot: string;
  python: string;
  viewerPython: string;
  viewerLauncher: string;
  workspace: string;
  source: string;
  artifact: string;
  parallelWorkspace: string;
  parallelSource: string;
  parallelArtifact: string;
}

export function createPackagedCadSmokePlan(
  bundleRoot: string,
  scratchRoot: string,
  platform = process.platform
): PackagedCadSmokePlan {
  const path = platform === 'win32' ? win32 : posix;
  const runtimeRoot = path.join(scratchRoot, 'runtime');
  const workspace = path.join(scratchRoot, 'workspace');
  const python =
    platform === 'win32'
      ? path.join(runtimeRoot, 'venv', 'Scripts', 'python.exe')
      : path.join(runtimeRoot, 'venv', 'bin', 'python');
  const viewerPython = path.join(
    runtimeRoot,
    'plugins',
    'text-to-cad',
    'skills',
    'cad-viewer',
    'scripts',
    'viewer',
    '.venv',
    platform === 'win32' ? 'Scripts' : 'bin',
    platform === 'win32' ? 'python.exe' : 'python'
  );
  const viewerLauncher = path.join(
    runtimeRoot,
    'plugins',
    'text-to-cad',
    'skills',
    'cad-viewer',
    'scripts',
    'viewer',
    'server',
    'main.mjs'
  );
  const parallelWorkspace = path.join(scratchRoot, 'parallel-workspace');
  return {
    bundleRoot,
    setupScript: path.join(bundleRoot, 'tooling', 'scripts', 'setup-cad.mjs'),
    constraints: path.join(bundleRoot, 'tooling', 'cad-runtime-constraints.txt'),
    bundledCadgenSource: path.join(bundleRoot, 'vendor', 'text-to-cad', 'packages', 'cadgen'),
    installedCadgenSource: path.join(runtimeRoot, 'plugins', 'text-to-cad', 'packages', 'cadgen'),
    runtimeRoot,
    python,
    viewerPython,
    viewerLauncher,
    workspace,
    source: path.join(workspace, 'packaged-smoke.py'),
    artifact: path.join(workspace, 'packaged-smoke.step'),
    parallelWorkspace,
    parallelSource: path.join(parallelWorkspace, 'packaged-parallel-smoke.py'),
    parallelArtifact: path.join(parallelWorkspace, 'packaged-parallel-smoke.step'),
  };
}

export async function verifyPackagedCadRuntime(bundleRoot: string): Promise<void> {
  const scratch = mkdtempSync(join(tmpdir(), 'hardcore-packaged-cad-'));
  const plan = createPackagedCadSmokePlan(bundleRoot, scratch);
  const environment = {
    ...process.env,
    CADGEN_WARM: '0',
    CADGEN_PYTHON: plan.python,
    HARDCORE_CAD_RUNTIME_ROOT: plan.runtimeRoot,
    PIP_DISABLE_PIP_VERSION_CHECK: '1',
  };

  try {
    step('Provisioning the packaged CAD runtime');
    run(process.execPath, [plan.setupScript, '--runtime-only'], { env: environment });

    step('Importing cadgen from the packaged source');
    assertSameFile(plan.bundledCadgenSource, plan.installedCadgenSource, 'pyproject.toml');
    assertSameFile(
      plan.bundledCadgenSource,
      plan.installedCadgenSource,
      join('src', 'cadgen', '__init__.py')
    );
    run(
      plan.viewerPython,
      [
        '-c',
        [
          'import importlib.metadata,json,os,pathlib,sys,urllib.parse,urllib.request',
          "direct=json.loads(importlib.metadata.distribution('cadgen').read_text('direct_url.json') or '{}')",
          "actual=pathlib.Path(urllib.request.url2pathname(urllib.parse.urlparse(direct.get('url','')).path))",
          'expected=pathlib.Path(sys.argv[1])',
          "assert os.path.samefile(actual,expected), f'cadgen came from {actual}, expected {expected}'",
          'from cadgen import build123d,step',
        ].join(';'),
        plan.installedCadgenSource,
      ],
      { env: environment }
    );
    step('Verifying the packaged CAD dependency lock');
    const freeze = capture(plan.viewerPython, ['-m', 'pip', 'freeze', '--all'], {
      env: environment,
    });
    verifyCadRuntimeLock(readFileSync(plan.constraints, 'utf8'), freeze);

    mkdirSync(plan.workspace, { recursive: true });
    mkdirSync(plan.parallelWorkspace, { recursive: true });
    writeFileSync(plan.source, SMOKE_MODEL, { encoding: 'utf8', flag: 'wx' });
    writeFileSync(plan.parallelSource, PARALLEL_SMOKE_MODEL, { encoding: 'utf8', flag: 'wx' });
    step('Generating STEP artifacts concurrently in two project roots');
    await runConcurrentProcesses([
      {
        command: plan.viewerPython,
        args: [plan.source, '--force', '--json'],
        cwd: plan.workspace,
        env: environment,
      },
      {
        command: plan.viewerPython,
        args: [plan.parallelSource, '--force', '--json'],
        cwd: plan.parallelWorkspace,
        env: environment,
      },
    ]);
    for (const artifact of [plan.artifact, plan.parallelArtifact]) {
      if (!existsSync(artifact)) {
        fail(`Packaged CAD generation did not create ${artifact}`);
      }
    }

    step('Validating and inspecting the packaged STEP artifact');
    run(plan.viewerPython, ['-m', 'cadgen.cli', 'step', 'inspect', 'validate', plan.artifact], {
      cwd: plan.workspace,
      env: environment,
    });
    run(
      plan.viewerPython,
      ['-m', 'cadgen.cli', 'step', 'inspect', 'refs', plan.artifact, '--facts'],
      {
        cwd: plan.workspace,
        env: environment,
      }
    );
    run(
      plan.viewerPython,
      ['-m', 'cadgen.cli', 'step', 'inspect', 'validate', plan.parallelArtifact],
      { cwd: plan.parallelWorkspace, env: environment }
    );

    step('Launching isolated CAD Viewers for two project roots');
    const viewerStarts = await Promise.allSettled([
      startPackagedViewer(plan.viewerLauncher, plan.workspace, environment),
      startPackagedViewer(plan.viewerLauncher, plan.parallelWorkspace, environment),
    ]);
    const viewers = viewerStarts.flatMap((result) =>
      result.status === 'fulfilled' ? [result.value] : []
    );
    const failedStart = viewerStarts.find(
      (result): result is PromiseRejectedResult => result.status === 'rejected'
    );
    if (failedStart) {
      await stopChildren(viewers.map((viewer) => viewer.child));
      throw failedStart.reason;
    }
    const viewer = viewers[0];
    const parallelViewer = viewers[1];
    if (!viewer || !parallelViewer) {
      await stopChildren(viewers.map((runningViewer) => runningViewer.child));
      throw new Error('Packaged CAD smoke did not start both root-bound Viewers.');
    }
    try {
      if (new URL(viewer.url).port === new URL(parallelViewer.url).port) {
        throw new Error('Packaged CAD Viewers for different roots reused the same server port.');
      }
      await Promise.all([
        verifyViewerArtifact({
          viewerUrl: viewer.url,
          workspace: plan.workspace,
          artifact: plan.artifact,
          excludedArtifact: plan.parallelArtifact,
        }),
        verifyViewerArtifact({
          viewerUrl: parallelViewer.url,
          workspace: plan.parallelWorkspace,
          artifact: plan.parallelArtifact,
          excludedArtifact: plan.artifact,
        }),
      ]);
    } finally {
      await stopChildren(viewers.map((runningViewer) => runningViewer.child));
    }
    info(
      'Packaged CAD runtime generated two isolated artifacts and opened each from its own root-bound Viewer'
    );
  } finally {
    rmSync(scratch, { force: true, recursive: true });
  }
}

type PackagedViewer = {
  child: ChildProcess;
  url: string;
};

async function startPackagedViewer(
  launcher: string,
  workspace: string,
  environment: NodeJS.ProcessEnv
): Promise<PackagedViewer> {
  if (!existsSync(launcher)) {
    throw new Error(`Packaged CAD Viewer launcher is missing: ${launcher}`);
  }
  const child = spawn(
    process.execPath,
    [launcher, '--root', workspace, '--host', '127.0.0.1', '--json', '--new'],
    {
      cwd: workspace,
      env: environment,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );
  let stdout = '';
  let stderr = '';
  let spawnError: Error | null = null;
  child.stdout?.on('data', (chunk: Buffer | string) => {
    stdout += String(chunk);
  });
  child.stderr?.on('data', (chunk: Buffer | string) => {
    stderr += String(chunk);
  });
  child.once('error', (error) => {
    spawnError = error;
  });

  try {
    const url = await waitFor(
      () => {
        if (spawnError) throw spawnError;
        for (const line of stdout.split(/\r?\n/).map((candidate) => candidate.trim())) {
          if (!line.startsWith('{')) continue;
          try {
            const payload: unknown = JSON.parse(line);
            if (
              typeof payload === 'object' &&
              payload !== null &&
              'url' in payload &&
              typeof payload.url === 'string'
            ) {
              return payload.url;
            }
          } catch {
            // Wait for the complete JSON line.
          }
        }
        if (child.exitCode !== null) {
          throw new Error(
            `Packaged CAD Viewer exited before becoming ready: ${stderr.trim() || stdout.trim()}`
          );
        }
        return null;
      },
      30_000,
      'Packaged CAD Viewer did not report a URL within 30 seconds.'
    );
    return { child, url };
  } catch (error) {
    await stopChild(child);
    throw error;
  }
}

async function verifyViewerArtifact(input: {
  viewerUrl: string;
  workspace: string;
  artifact: string;
  excludedArtifact: string;
}): Promise<void> {
  const base = new URL(input.viewerUrl);
  const serverResponse = await fetch(new URL('/__cad/server', base));
  if (!serverResponse.ok) {
    throw new Error(`Packaged CAD Viewer health check failed with ${serverResponse.status}.`);
  }
  const serverInfo: unknown = await serverResponse.json();
  if (
    typeof serverInfo !== 'object' ||
    serverInfo === null ||
    !('rootPath' in serverInfo) ||
    typeof serverInfo.rootPath !== 'string' ||
    resolve(serverInfo.rootPath) !== resolve(input.workspace)
  ) {
    throw new Error(`Packaged CAD Viewer served the wrong root: ${JSON.stringify(serverInfo)}`);
  }

  const catalogResponse = await fetch(new URL('/__cad/catalog', base));
  if (!catalogResponse.ok) {
    throw new Error(`Packaged CAD Viewer catalog failed with ${catalogResponse.status}.`);
  }
  const catalog: unknown = await catalogResponse.json();
  const entries =
    typeof catalog === 'object' && catalog !== null && 'entries' in catalog
      ? (catalog.entries as unknown)
      : null;
  const artifactName = input.artifact.split(/[\\/]/).at(-1);
  const excludedArtifactName = input.excludedArtifact.split(/[\\/]/).at(-1);
  if (!Array.isArray(entries)) {
    throw new Error('Packaged CAD Viewer catalog did not return entries.');
  }
  if (
    !entries.some(
      (entry) =>
        typeof entry === 'object' &&
        entry !== null &&
        'rootRelativeFile' in entry &&
        entry.rootRelativeFile === artifactName
    )
  ) {
    throw new Error('Packaged CAD Viewer catalog did not include the generated STEP artifact.');
  }
  if (
    entries.some(
      (entry) =>
        typeof entry === 'object' &&
        entry !== null &&
        'rootRelativeFile' in entry &&
        entry.rootRelativeFile === excludedArtifactName
    )
  ) {
    throw new Error('Packaged CAD Viewer catalog leaked an artifact from another project root.');
  }

  const artifactUrl = new URL('/__cad/artifact', base);
  artifactUrl.searchParams.set('file', input.artifact);
  const artifactResponse = await fetch(artifactUrl);
  const artifactStatus: unknown = await artifactResponse.json();
  if (
    !artifactResponse.ok ||
    typeof artifactStatus !== 'object' ||
    artifactStatus === null ||
    !('state' in artifactStatus) ||
    artifactStatus.state !== 'ready'
  ) {
    throw new Error(
      `Packaged CAD Viewer did not open the generated artifact: ${JSON.stringify(artifactStatus)}`
    );
  }
}

async function waitFor<T>(
  read: () => T | null,
  timeoutMs: number,
  timeoutMessage: string
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = read();
    if (result !== null) return result;
    if (Date.now() >= deadline) throw new Error(timeoutMessage);
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 50));
  }
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (child.pid === undefined) return;
  await new Promise<void>((resolveExit, rejectExit) => {
    const cleanup = () => {
      clearTimeout(forceTimer);
      clearTimeout(failureTimer);
    };
    const forceTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    }, 5_000);
    const failureTimer = setTimeout(() => {
      cleanup();
      rejectExit(
        new Error(`Child process ${child.pid ?? '(unknown)'} did not exit after SIGKILL.`)
      );
    }, 10_000);
    child.once('exit', () => {
      cleanup();
      resolveExit();
    });
    child.kill('SIGTERM');
  });
}

async function stopChildren(children: ChildProcess[]): Promise<void> {
  const stopped = await Promise.allSettled(children.map((child) => stopChild(child)));
  const failed = stopped.find(
    (result): result is PromiseRejectedResult => result.status === 'rejected'
  );
  if (failed) throw failed.reason;
}

export function verifyCadRuntimeLock(constraintsSource: string, freezeSource: string): void {
  const expected = parsePinnedDistributions(constraintsSource, 'constraint');
  const installed = parsePinnedDistributions(freezeSource, 'installed package', {
    ignoreCadgenSource: true,
  });
  const required = ['build123d', 'cadquery-ocp', 'ezdxf', 'shapely'];
  const problems = [
    ...[...installed].flatMap(([name, version]) =>
      expected.get(name) === version
        ? []
        : [`${name}==${version} is not the locked ${expected.get(name) ?? 'version'}`]
    ),
    ...required.flatMap((name) =>
      installed.get(name) === expected.get(name)
        ? []
        : [`required ${name} is missing or does not match the lock`]
    ),
  ];
  if (problems.length > 0) {
    throw new Error(`Packaged CAD dependency lock mismatch:\n${problems.join('\n')}`);
  }
}

function parsePinnedDistributions(
  source: string,
  label: string,
  options: { ignoreCadgenSource?: boolean } = {}
): Map<string, string> {
  const versions = new Map<string, string>();
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    if (
      options.ignoreCadgenSource &&
      (/^cadgen\s+@\s+/i.test(line) || /#egg=cadgen(?:&|$)/i.test(line))
    ) {
      continue;
    }
    const match = line.match(/^([A-Za-z0-9_.-]+)==([^\s;]+)$/);
    if (!match) throw new Error(`Unpinned ${label}: ${line}`);
    versions.set(normalizeDistributionName(match[1]), match[2]);
  }
  return versions;
}

function normalizeDistributionName(name: string): string {
  return name.toLowerCase().replace(/[-_.]+/g, '-');
}

function assertSameFile(leftRoot: string, rightRoot: string, relativePath: string): void {
  const left = readFileSync(join(leftRoot, relativePath));
  const right = readFileSync(join(rightRoot, relativePath));
  if (!left.equals(right)) {
    throw new Error(`Packaged CAD staging changed ${relativePath}`);
  }
}

function run(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv }
): void {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

async function runConcurrentProcesses(
  processes: Array<{
    command: string;
    args: string[];
    cwd?: string;
    env?: NodeJS.ProcessEnv;
  }>
): Promise<void> {
  const children = processes.map((processSpec) =>
    spawn(processSpec.command, processSpec.args, {
      cwd: processSpec.cwd,
      env: processSpec.env,
      stdio: 'inherit',
    })
  );
  try {
    await Promise.all(
      children.map((child, index) => waitForChildSuccess(child, processes[index]?.command))
    );
  } catch (error) {
    await stopChildren(children);
    throw error;
  }
}

function waitForChildSuccess(child: ChildProcess, command = 'CAD process'): Promise<void> {
  if (child.exitCode !== null) {
    return child.exitCode === 0
      ? Promise.resolve()
      : Promise.reject(new Error(`${command} exited with status ${child.exitCode}`));
  }
  if (child.signalCode !== null) {
    return Promise.reject(new Error(`${command} exited with signal ${child.signalCode}`));
  }
  return new Promise<void>((resolveRun, rejectRun) => {
    child.once('error', rejectRun);
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolveRun();
        return;
      }
      rejectRun(
        new Error(
          `${command} exited with ${code === null ? `signal ${signal ?? 'unknown'}` : `status ${code}`}`
        )
      );
    });
  });
}

function capture(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv }
): string {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: 'utf8',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}: ${result.stderr}`);
  }
  return result.stdout;
}

export async function main(args = process.argv.slice(2)): Promise<void> {
  const { values } = parseArgs({
    args,
    options: {
      'release-dir': { default: 'release', type: 'string' },
    },
    strict: true,
  });
  const bundles = findPackagedCadBundleRoots(values['release-dir']);
  if (bundles.length === 0) {
    fail(`No packaged CAD bundle was found under ${values['release-dir']}`);
  }

  // The bundle is byte-identical between installer targets in the same release job.
  // electron-builder's afterPack hook already checks every target; run the expensive
  // Python provisioning/generation smoke once per operating-system release job.
  await verifyPackagedCadRuntime(bundles[0]);
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
