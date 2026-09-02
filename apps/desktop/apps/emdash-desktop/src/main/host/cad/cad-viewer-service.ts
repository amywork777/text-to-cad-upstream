import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { createServer } from 'node:net';
import { homedir } from 'node:os';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';
import {
  currentCadRuntimePluginRoot,
  currentCadRuntimePythonExecutable,
  provisionCadRuntime,
} from '@main/host/cad/cad-runtime-service';
import {
  cadgenPythonEnvironment,
  resolveCadViewerCapability,
} from '@main/host/cad/cadgen-compatibility';

const HOST = '127.0.0.1';
const DEFAULT_PORT = 3245;
const STARTUP_TIMEOUT_MS = 30_000;

export type EnsureCadViewerResult =
  | { success: true; url: string }
  | { success: false; error: string };

type StartCadViewerResult = { success: true; port: number } | { success: false; error: string };

export type CadViewerChild = {
  kill(): boolean;
  onTerminated(listener: () => void): void;
};

export class CadViewerProcessLifecycle {
  private viewerProcess: CadViewerChild | null = null;
  private viewerPort: number | null = null;
  private ensurePromise: Promise<StartCadViewerResult> | null = null;

  ensureStarted(input: {
    isHealthy: (port: number) => Promise<boolean>;
    start: () => Promise<StartCadViewerResult>;
  }): Promise<StartCadViewerResult> {
    if (this.ensurePromise) return this.ensurePromise;

    const tracked = this.ensureStartedInternal(input).finally(() => {
      if (this.ensurePromise === tracked) this.ensurePromise = null;
    });
    this.ensurePromise = tracked;
    return tracked;
  }

  adopt(child: CadViewerChild): void {
    if (this.viewerProcess && this.viewerProcess !== child) this.stop();
    this.viewerProcess = child;
    this.viewerPort = null;

    const release = () => {
      if (this.viewerProcess !== child) return;
      this.viewerProcess = null;
      this.viewerPort = null;
    };
    child.onTerminated(release);
  }

  owns(child: CadViewerChild): boolean {
    return this.viewerProcess === child;
  }

  markReady(child: CadViewerChild, port: number): boolean {
    if (!this.owns(child)) return false;
    this.viewerPort = port;
    return true;
  }

  stop(child: CadViewerChild | null = this.viewerProcess): void {
    if (!child || this.viewerProcess !== child) return;
    this.viewerProcess = null;
    this.viewerPort = null;
    child.kill();
  }

  private async ensureStartedInternal(input: {
    isHealthy: (port: number) => Promise<boolean>;
    start: () => Promise<StartCadViewerResult>;
  }): Promise<StartCadViewerResult> {
    const currentProcess = this.viewerProcess;
    const currentPort = this.viewerPort;
    if (
      currentProcess &&
      currentPort !== null &&
      (await input.isHealthy(currentPort)) &&
      this.viewerProcess === currentProcess
    ) {
      return { success: true, port: currentPort };
    }

    this.stop();
    try {
      const started = await input.start();
      if (!started.success) this.stop();
      return started;
    } catch (error) {
      this.stop();
      throw error;
    }
  }
}

export class CadViewerLifecycleRegistry {
  private readonly lifecycles = new Map<string, CadViewerProcessLifecycle>();

  forWorkspace(workspacePath: string): CadViewerProcessLifecycle {
    const key = resolve(workspacePath);
    const existing = this.lifecycles.get(key);
    if (existing) return existing;
    const lifecycle = new CadViewerProcessLifecycle();
    this.lifecycles.set(key, lifecycle);
    return lifecycle;
  }

  stopAll(): void {
    for (const lifecycle of this.lifecycles.values()) lifecycle.stop();
    this.lifecycles.clear();
  }

  get size(): number {
    return this.lifecycles.size;
  }
}

const viewerLifecycles = new CadViewerLifecycleRegistry();
let viewerStartupTail: Promise<void> = Promise.resolve();

function enqueueViewerStartup<T>(operation: () => Promise<T>): Promise<T> {
  const result = viewerStartupTail.catch(() => undefined).then(operation);
  viewerStartupTail = result.then(
    () => undefined,
    () => undefined
  );
  return result;
}

export async function ensureCadViewer(input: {
  workspacePath: string;
  filePath: string;
}): Promise<EnsureCadViewerResult> {
  const target = validateTarget(input);
  if (!target.success) return target;

  const lifecycle = viewerLifecycles.forWorkspace(target.workspacePath);
  const started = await lifecycle.ensureStarted({
    isHealthy: (port) => viewerIsHealthy(port, target.workspacePath),
    start: () =>
      enqueueViewerStartup(async () => {
        const port = await selectCadViewerPort(configuredPort());
        if (port === null) {
          return { success: false, error: 'No local port is available for CAD Viewer.' };
        }
        return startViewer(port, target.workspacePath, lifecycle);
      }),
  });
  return started.success
    ? { success: true, url: buildCadViewerUrl({ ...target, port: started.port }) }
    : started;
}

export async function selectCadViewerPort(
  preferredPort: number,
  isAvailable: (port: number) => Promise<boolean> = portIsAvailable
): Promise<number | null> {
  for (let offset = 0; offset < 100; offset += 1) {
    const candidate = preferredPort + offset;
    if (candidate > 65_535) break;
    if (await isAvailable(candidate)) return candidate;
  }
  return null;
}

export function buildCadViewerUrl(input: {
  workspacePath: string;
  relativeFilePath: string;
  port: number;
}): string {
  const url = new URL(`http://${HOST}:${input.port}`);
  // Every supported Viewer is launched with --root, so the page itself stays
  // at the bare origin and only the root-relative artifact belongs in the URL.
  url.pathname = '/';
  url.searchParams.set('file', input.relativeFilePath.split(sep).join('/'));
  return url.toString();
}

function validateTarget(input: {
  workspacePath: string;
  filePath: string;
}):
  | { success: true; workspacePath: string; relativeFilePath: string }
  | { success: false; error: string } {
  const workspacePath = resolve(input.workspacePath);
  const requestedFilePath = resolve(input.filePath);
  const relativeRequestedPath = relative(workspacePath, requestedFilePath);
  if (
    !relativeRequestedPath ||
    relativeRequestedPath.startsWith(`..${sep}`) ||
    isAbsolute(relativeRequestedPath)
  ) {
    return { success: false, error: 'CAD files must be inside the active project workspace.' };
  }
  if (!existsSync(requestedFilePath)) {
    return { success: false, error: `CAD file does not exist: ${requestedFilePath}` };
  }
  const filePath = preferredCadViewerPath(requestedFilePath);
  const relativeFilePath = relative(workspacePath, filePath);
  return { success: true, workspacePath, relativeFilePath };
}

export function preferredCadViewerPath(
  filePath: string,
  _fileExists: (candidate: string) => boolean = existsSync
): string {
  return filePath;
}

async function startViewer(
  port: number,
  cwd: string,
  lifecycle: CadViewerProcessLifecycle
): Promise<StartCadViewerResult> {
  let pluginRoot = findCadPluginRoot();
  if (!pluginRoot) {
    try {
      await provisionCadRuntime();
      pluginRoot = findCadPluginRoot();
    } catch (error) {
      return {
        success: false,
        error: `Could not prepare the pinned CAD environment: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
  }
  if (!pluginRoot) {
    return {
      success: false,
      error: 'The pinned CAD plugin could not be located after automatic setup.',
    };
  }

  let viewer = resolveCadViewerCapability(pluginRoot);
  if (!viewer) {
    try {
      await provisionCadRuntime();
    } catch (error) {
      return {
        success: false,
        error: `Could not prepare the pinned CAD environment: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
    viewer = resolveCadViewerCapability(pluginRoot);
    if (!viewer) {
      return { success: false, error: 'The pinned CAD Viewer environment is incomplete.' };
    }
  }

  let viewerLog = '';
  const viewerProcess = spawn(
    process.execPath,
    [viewer.launcher, '--root', cwd, '--host', HOST, '--port', String(port), '--json'],
    {
      cwd,
      env: cadgenPythonEnvironment(
        {
          ...process.env,
          ELECTRON_RUN_AS_NODE: '1',
          INIT_CWD: cwd,
        },
        viewer.supportsCadgenPython ? findCadPythonExecutable(pluginRoot) : null
      ),
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );
  const viewerChild: CadViewerChild = {
    kill: () => viewerProcess.kill(),
    onTerminated: (listener) => {
      viewerProcess.once('exit', listener);
      viewerProcess.once('error', listener);
    },
  };
  lifecycle.adopt(viewerChild);
  const appendViewerLog = (chunk: Buffer | string) => {
    if (!lifecycle.owns(viewerChild)) return;
    viewerLog = `${viewerLog}${String(chunk)}`.slice(-8_000);
  };
  viewerProcess.stdout?.on('data', appendViewerLog);
  viewerProcess.stderr?.on('data', appendViewerLog);

  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (!lifecycle.owns(viewerChild)) break;
    if ((await viewerIsHealthy(port, cwd)) && lifecycle.markReady(viewerChild, port)) {
      return { success: true, port };
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
  }

  return {
    success: false,
    error: viewerLog.trim() || 'CAD Viewer did not become ready within 30 seconds.',
  };
}

async function portIsAvailable(port: number): Promise<boolean> {
  return new Promise((resolvePort) => {
    const server = createServer();
    server.unref();
    server.once('error', () => resolvePort(false));
    server.listen({ host: HOST, port, exclusive: true }, () => {
      server.close(() => resolvePort(true));
    });
  });
}

async function viewerIsHealthy(port: number, workspacePath: string): Promise<boolean> {
  try {
    const response = await fetch(`http://${HOST}:${port}/__cad/server`, {
      signal: AbortSignal.timeout(750),
    });
    if (!response.ok) return false;
    const payload: unknown = await response.json();
    return (
      typeof payload === 'object' &&
      payload !== null &&
      'rootPath' in payload &&
      typeof payload.rootPath === 'string' &&
      resolve(payload.rootPath) === resolve(workspacePath)
    );
  } catch {
    return false;
  }
}

function configuredPort(): number {
  const value = Number(process.env.HARDCORE_CAD_VIEWER_PORT ?? DEFAULT_PORT);
  return Number.isInteger(value) && value > 0 && value <= 65_535 ? value : DEFAULT_PORT;
}

export function findCadPluginRoot(): string | null {
  const configured = process.env.HARDCORE_CAD_PLUGIN_ROOT;
  const bundledCopy = currentCadRuntimePluginRoot();
  const codexRoot = join(homedir(), '.codex', '.tmp', 'marketplaces', 'text-to-cad');
  for (const candidate of [configured, bundledCopy, codexRoot]) {
    if (candidate && hasViewer(candidate)) return candidate;
  }

  const claudeRoot = join(homedir(), '.claude', 'plugins', 'cache', 'text-to-cad', 'cad');
  if (!existsSync(claudeRoot)) return null;
  const versions = readdirSync(claudeRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
  return versions.map((version) => join(claudeRoot, version)).find(hasViewer) ?? null;
}

export function findCadPythonExecutable(pluginRoot: string): string {
  const configured = process.env.HARDCORE_CAD_PYTHON?.trim();
  if (configured && existsSync(configured)) return configured;
  const runtimePython = currentCadRuntimePythonExecutable();
  if (existsSync(runtimePython)) return runtimePython;
  const repositoryPython = join(
    pluginRoot,
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python'
  );
  if (existsSync(repositoryPython)) return repositoryPython;
  return join(
    pluginRoot,
    'skills',
    'cad-viewer',
    'scripts',
    'viewer',
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python'
  );
}

function hasViewer(pluginRoot: string): boolean {
  return resolveCadViewerCapability(pluginRoot) !== null;
}

process.once('exit', () => {
  viewerLifecycles.stopAll();
});
