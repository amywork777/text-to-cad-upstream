import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, parse } from 'node:path';
import { promisify } from 'node:util';
import { app } from 'electron';

const execFileAsync = promisify(execFile);
let provisioning: Promise<void> | null = null;

export type CadRuntimeStatus = {
  state: 'idle' | 'installing' | 'ready' | 'error';
  packageName: 'cad@text-to-cad';
  message: string;
  updatedAt: string | null;
};

let status: CadRuntimeStatus = {
  state: 'idle',
  packageName: 'cad@text-to-cad',
  message: 'CAD setup requires Python 3.11 or newer and will verify it before installing.',
  updatedAt: null,
};

export function getCadRuntimeStatus(): CadRuntimeStatus {
  return { ...status };
}

export async function provisionCadRuntime(): Promise<void> {
  if (provisioning) return provisioning;
  status = {
    ...status,
    state: 'installing',
    message: 'Checking Python 3.11+ and preparing the built-in CAD skills…',
    updatedAt: new Date().toISOString(),
  };
  provisioning = runProvisioning()
    .then(() => {
      status = {
        ...status,
        state: 'ready',
        message: 'The pinned CAD runtime and skills are ready.',
        updatedAt: new Date().toISOString(),
      };
    })
    .catch((error: unknown) => {
      status = {
        ...status,
        state: 'error',
        message: cadRuntimeProvisioningErrorMessage(error),
        updatedAt: new Date().toISOString(),
      };
      throw error;
    })
    .finally(() => {
      provisioning = null;
    });
  return provisioning;
}

export function cadRuntimeProvisioningErrorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const stderr = readableProcessOutput('stderr' in error ? error.stderr : null);
    if (stderr) return stderr;
    const stdout = readableProcessOutput('stdout' in error ? error.stdout : null);
    if (stdout) return stdout;
  }
  return error instanceof Error ? error.message : String(error);
}

function readableProcessOutput(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (Buffer.isBuffer(value)) return value.toString('utf8').trim() || null;
  return null;
}

async function runProvisioning(): Promise<void> {
  const script = findSetupScript(process.cwd(), process.resourcesPath);
  if (!script) throw new Error('Hardcore could not locate its pinned CAD environment installer.');
  const runtimeRoot = currentCadRuntimeRoot();
  await execFileAsync(process.execPath, [script], {
    cwd: dirname(dirname(dirname(script))),
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: '1',
      HARDCORE_CAD_RUNTIME_ROOT: runtimeRoot,
      PYTHONDONTWRITEBYTECODE: '1',
    },
    timeout: 10 * 60_000,
    maxBuffer: 10 * 1024 * 1024,
  });
}

export function resolveCadRuntimeRoot(
  userDataPath: string,
  configuredRoot = process.env.HARDCORE_CAD_RUNTIME_ROOT
): string {
  const configured = configuredRoot?.trim();
  return configured || join(userDataPath, 'cad-runtime');
}

export function cadRuntimePythonExecutable(runtimeRoot: string): string {
  return join(
    runtimeRoot,
    'venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python'
  );
}

export function cadRuntimePluginRoot(runtimeRoot: string): string {
  return join(runtimeRoot, 'plugins', 'text-to-cad');
}

export function currentCadRuntimeRoot(): string {
  return resolveCadRuntimeRoot(app.getPath('userData'));
}

export function currentCadRuntimePythonExecutable(): string {
  return cadRuntimePythonExecutable(currentCadRuntimeRoot());
}

export function currentCadRuntimePluginRoot(): string {
  return cadRuntimePluginRoot(currentCadRuntimeRoot());
}

export function findSetupScript(start: string, resourcesPath?: string): string | null {
  if (resourcesPath) {
    const packaged = join(resourcesPath, 'hardcore-cad', 'tooling', 'scripts', 'setup-cad.mjs');
    if (existsSync(packaged)) return packaged;
  }
  let current = start;
  const root = parse(current).root;
  while (true) {
    const candidate = join(current, 'tooling', 'scripts', 'setup-cad.mjs');
    if (existsSync(candidate)) return candidate;
    if (current === root) return null;
    current = dirname(current);
  }
}
