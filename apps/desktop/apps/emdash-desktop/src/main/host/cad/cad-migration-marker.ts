import { createHash, randomUUID } from 'node:crypto';
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';

const MARKER_VERSION = 1;
const MAX_SOURCE_BYTES = 2 * 1024 * 1024;
const MAX_MARKER_BYTES = 4 * MAX_SOURCE_BYTES;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export interface CadVerifiedMigrationMarker {
  version: 1;
  state: 'verified' | 'committed';
  legacySourcePath: string;
  migratedSourcePath: string;
  modelPath: string;
  originalSourceHash: string;
  modelHash: string;
  migratedSourceHash: string;
  sourceMode: number;
  migratedSourceBase64?: string;
}

export type CadMigrationMarkerReadResult =
  | {
      success: true;
      marker: CadVerifiedMigrationMarker | null;
      markerPath: string;
      migratedSourcePath: string;
    }
  | { success: false; error: string };

export function cadMigrationMarkerPath(legacySourcePath: string): string {
  return join(
    dirname(legacySourcePath),
    `.${basename(legacySourcePath)}.hardcore-migration-verified.json`
  );
}

export function cadMigrationSha256(value: Buffer): string {
  return createHash('sha256').update(value).digest('hex');
}

export function readCadVerifiedMigrationMarker(input: {
  workspacePath: string;
  legacySourcePath: string;
  migratedSourcePath: string;
  modelPath: string;
  requireMigratedSource?: boolean;
}): CadMigrationMarkerReadResult {
  try {
    const workspacePath = realpathSync(resolve(input.workspacePath));
    const legacyParent = realpathSync(dirname(resolve(input.legacySourcePath)));
    const legacySourcePath = resolve(legacyParent, basename(input.legacySourcePath));
    const migratedSourcePath = resolve(legacyParent, basename(input.migratedSourcePath));
    const modelPath = resolve(legacyParent, basename(input.modelPath));
    for (const path of [legacySourcePath, migratedSourcePath, modelPath]) {
      if (!isInsideWorkspace(relative(workspacePath, path))) {
        return { success: false, error: 'CAD migration files must stay inside the workspace.' };
      }
    }

    const markerPath = cadMigrationMarkerPath(legacySourcePath);
    if (!existsSync(markerPath)) {
      return { success: true, marker: null, markerPath, migratedSourcePath };
    }
    if (lstatSync(markerPath).isSymbolicLink() || !statSync(markerPath).isFile()) {
      return { success: false, error: 'The CAD migration marker is not a regular project file.' };
    }
    const markerBytes = readFileSync(markerPath);
    if (markerBytes.byteLength > MAX_MARKER_BYTES) {
      return { success: false, error: 'The CAD migration marker is unexpectedly large.' };
    }
    const parsed: unknown = JSON.parse(markerBytes.toString('utf8'));
    if (!isRecord(parsed)) {
      return { success: false, error: 'The CAD migration marker is invalid.' };
    }
    const marker = parseMarker(parsed);
    if (!marker) {
      return { success: false, error: 'The CAD migration marker is invalid.' };
    }

    const expectedPaths = {
      legacySourcePath: relative(workspacePath, legacySourcePath),
      migratedSourcePath: relative(workspacePath, migratedSourcePath),
      modelPath: relative(workspacePath, modelPath),
    };
    if (
      marker.legacySourcePath !== expectedPaths.legacySourcePath ||
      marker.migratedSourcePath !== expectedPaths.migratedSourcePath ||
      marker.modelPath !== expectedPaths.modelPath
    ) {
      return {
        success: false,
        error: 'The CAD migration marker belongs to different project files.',
      };
    }
    if (!isRegularFileInside(workspacePath, modelPath)) {
      return { success: false, error: 'The accepted STEP is no longer a regular project file.' };
    }
    if (cadMigrationSha256(readFileSync(modelPath)) !== marker.modelHash) {
      return {
        success: false,
        error: 'The accepted STEP changed after the CAD migration was verified.',
      };
    }
    if (existsSync(legacySourcePath)) {
      if (!isRegularFileInside(workspacePath, legacySourcePath)) {
        return { success: false, error: 'The legacy CAD source is no longer a regular file.' };
      }
      if (cadMigrationSha256(readFileSync(legacySourcePath)) !== marker.originalSourceHash) {
        return {
          success: false,
          error: 'The legacy CAD source changed after the migration was verified.',
        };
      }
    }

    if (existsSync(migratedSourcePath)) {
      if (!isRegularFileInside(workspacePath, migratedSourcePath)) {
        return { success: false, error: 'The migrated CAD source is not a regular project file.' };
      }
      if (cadMigrationSha256(readFileSync(migratedSourcePath)) !== marker.migratedSourceHash) {
        return {
          success: false,
          error: 'The migrated CAD source does not match its verified content.',
        };
      }
    } else if (input.requireMigratedSource || marker.state === 'committed') {
      return { success: false, error: 'The verified migrated CAD source is missing.' };
    }

    return { success: true, marker, markerPath, migratedSourcePath };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Could not read the CAD migration marker.',
    };
  }
}

export function verifiedMigratedCadSourceForLegacy(input: {
  workspacePath: string;
  legacySourcePath: string;
  migratedSourcePath: string;
  modelPath: string;
}): string | null {
  const result = readCadVerifiedMigrationMarker({ ...input, requireMigratedSource: true });
  if (!result.success || !result.marker) return null;
  // Preserve the caller's lexical workspace root (for example /var versus
  // /private/var on macOS) after the marker reader has verified real paths.
  return resolve(dirname(resolve(input.legacySourcePath)), basename(input.migratedSourcePath));
}

export function writeCadVerifiedMigrationMarker(
  markerPath: string,
  marker: CadVerifiedMigrationMarker
): void {
  atomicReplaceFile(markerPath, Buffer.from(`${JSON.stringify(marker)}\n`, 'utf8'), 0o600);
}

export function removeCadVerifiedMigrationMarker(markerPath: string): void {
  if (existsSync(markerPath)) rmSync(markerPath);
}

function parseMarker(value: Record<string, unknown>): CadVerifiedMigrationMarker | null {
  if (
    value.version !== MARKER_VERSION ||
    (value.state !== 'verified' && value.state !== 'committed') ||
    typeof value.legacySourcePath !== 'string' ||
    typeof value.migratedSourcePath !== 'string' ||
    typeof value.modelPath !== 'string' ||
    typeof value.originalSourceHash !== 'string' ||
    typeof value.modelHash !== 'string' ||
    typeof value.migratedSourceHash !== 'string' ||
    typeof value.sourceMode !== 'number' ||
    !Number.isInteger(value.sourceMode) ||
    value.sourceMode < 0 ||
    value.sourceMode > 0o777 ||
    !SHA256_PATTERN.test(value.originalSourceHash) ||
    !SHA256_PATTERN.test(value.modelHash) ||
    !SHA256_PATTERN.test(value.migratedSourceHash)
  ) {
    return null;
  }
  const base = {
    version: MARKER_VERSION,
    state: value.state,
    legacySourcePath: value.legacySourcePath,
    migratedSourcePath: value.migratedSourcePath,
    modelPath: value.modelPath,
    originalSourceHash: value.originalSourceHash,
    modelHash: value.modelHash,
    migratedSourceHash: value.migratedSourceHash,
    sourceMode: value.sourceMode,
  } satisfies Omit<CadVerifiedMigrationMarker, 'migratedSourceBase64'>;
  if (value.state === 'committed') return base;
  if (typeof value.migratedSourceBase64 !== 'string') return null;
  const migratedSource = Buffer.from(value.migratedSourceBase64, 'base64');
  if (
    migratedSource.byteLength === 0 ||
    migratedSource.byteLength > MAX_SOURCE_BYTES ||
    cadMigrationSha256(migratedSource) !== value.migratedSourceHash
  ) {
    return null;
  }
  return { ...base, migratedSourceBase64: value.migratedSourceBase64 };
}

function atomicReplaceFile(path: string, contents: Buffer, mode: number): void {
  const temporaryPath = join(dirname(path), `.${basename(path)}.${randomUUID()}.tmp`);
  let descriptor: number | null = null;
  try {
    descriptor = openSync(temporaryPath, 'wx', mode);
    writeFileSync(descriptor, contents);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = null;
    chmodSync(temporaryPath, mode);
    renameSync(temporaryPath, path);
    fsyncDirectory(dirname(path));
  } finally {
    if (descriptor !== null) closeSync(descriptor);
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

function isRegularFileInside(workspacePath: string, path: string): boolean {
  try {
    return (
      existsSync(path) &&
      !lstatSync(path).isSymbolicLink() &&
      statSync(path).isFile() &&
      isInsideWorkspace(relative(workspacePath, realpathSync(path)))
    );
  } catch {
    return false;
  }
}

function isInsideWorkspace(path: string): boolean {
  return Boolean(path) && path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
