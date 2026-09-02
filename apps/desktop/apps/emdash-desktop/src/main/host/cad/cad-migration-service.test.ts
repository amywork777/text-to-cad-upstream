import { createHash } from 'node:crypto';
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  stat,
  symlink,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  cadMigrationMarkerPath,
  cadMigrationSha256,
  writeCadVerifiedMigrationMarker,
} from './cad-migration-marker';
import { migrateLegacyCadModel, type CadMigrationDependencies } from './cad-migration-service';

const temporaryDirectories: string[] = [];
const LEGACY_SOURCE = 'from cadgen import gen_step\n\ndef gen_step():\n    return object()\n';
const MIGRATED_SOURCE = 'from cadgen import step\n\n@step\ndef bracket():\n    return object()\n';
const LEGACY_SOURCE_HASH = createHash('sha256').update(LEGACY_SOURCE).digest('hex');
const LEGACY_COMPONENT_HASH = 'a'.repeat(64);
const CHANGED_COMPONENT_HASH = 'b'.repeat(64);
const ACCEPTED_STEP = [
  'ISO-10303-21;',
  `DESCRIPTIVE_REPRESENTATION_ITEM('cadgen:sourceHash','${LEGACY_SOURCE_HASH}');`,
  'END-ISO-10303-21;',
].join('\n');

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true }))
  );
});

async function migrationWorkspace(
  options: { suffix?: '.step.py' | '.stp.py'; canonicalPackage?: boolean } = {}
) {
  const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-migration-'));
  temporaryDirectories.push(workspacePath);
  const suffix = options.suffix ?? '.step.py';
  const sourcePath = join(workspacePath, `bracket${suffix}`);
  const migratedSourcePath = join(workspacePath, 'bracket.py');
  const modelPath = join(workspacePath, `bracket${suffix.slice(0, -3)}`);
  const pythonPath = join(workspacePath, 'python');
  const canonicalPackagePath = join(workspacePath, '__cadgen__', 'models', basename(modelPath));
  await writeFile(sourcePath, LEGACY_SOURCE);
  await chmod(sourcePath, 0o640);
  await writeFile(modelPath, ACCEPTED_STEP);
  await writeFile(pythonPath, '');
  if (options.canonicalPackage) {
    await mkdir(canonicalPackagePath, { recursive: true });
    await writeFile(
      join(canonicalPackagePath, 'assembly.json'),
      JSON.stringify({ sourceKind: 'step', sentinel: 'original-viewer-package' })
    );
    await writeFile(join(canonicalPackagePath, 'original.cache'), 'preserve me');
  }
  return {
    workspacePath,
    sourcePath,
    migratedSourcePath,
    modelPath,
    pythonPath,
    canonicalPackagePath,
  };
}

async function writeGeometryBuild(modelPath: string, contentHash: string) {
  await writeFile(modelPath, `isolated-${basename(modelPath)}`);
  const packagePath = join(dirname(modelPath), '__cadgen__', 'models', basename(modelPath));
  await mkdir(packagePath, { recursive: true });
  await writeFile(
    join(packagePath, 'assembly.json'),
    JSON.stringify({
      components: { component: { contentHash } },
      occurrences: [
        {
          id: 'o1.1',
          component: 'component',
          transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
      ],
      assemblyRoot: null,
      assemblyMates: [],
      bbox: { min: [0, 0, 0], max: [1, 1, 1] },
    })
  );
}

async function emulateIsolatedCommand(
  args: readonly string[],
  options: { cwd: string },
  candidateHash = LEGACY_COMPONENT_HASH
): Promise<{ stdout: string; stderr: string }> {
  const script = String(args[0] ?? '');
  if (script.endsWith('legacy-wrapper.py')) {
    await writeGeometryBuild(join(dirname(script), 'legacy.step'), LEGACY_COMPONENT_HASH);
  } else if (args[0] === '-m' && args[1] === 'cadgen.migrate') {
    const legacyPath = join(options.cwd, String(args[2]));
    const plainPath = legacyPath.replace(/\.(?:step|stp)\.py$/i, '.py');
    await writeFile(plainPath, MIGRATED_SOURCE);
    await unlink(legacyPath);
  } else if (script.endsWith('candidate-wrapper.py')) {
    await writeGeometryBuild(join(dirname(script), 'candidate.step'), candidateHash);
  }
  return { stdout: '{"ok":true}', stderr: '' };
}

function dependencies(
  pythonPath: string,
  run: CadMigrationDependencies['run']
): CadMigrationDependencies {
  return {
    prepareRuntime: vi.fn(async () => {}),
    pythonExecutable: () => pythonPath,
    run,
  };
}

describe('legacy CAD migration service', () => {
  it('commits only the verified source while preserving the canonical STEP and viewer package', async () => {
    const paths = await migrationWorkspace({ canonicalPackage: true });
    const originalDescriptor = await readFile(
      join(paths.canonicalPackagePath, 'assembly.json'),
      'utf8'
    );
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) =>
      emulateIsolatedCommand(args, options)
    );

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result).toEqual({
      success: true,
      sourcePath: 'bracket.py',
      modelPath: 'bracket.step',
      openPath: 'bracket.step',
    });
    expect(run).toHaveBeenCalledTimes(5);
    expect(run.mock.calls[0]?.[1][0]).toMatch(/legacy-wrapper\.py$/);
    expect(run.mock.calls[1]?.[1]).toEqual(['-m', 'cadgen.migrate', 'bracket.step.py']);
    expect(run.mock.calls[2]?.[1][0]).toMatch(/candidate-wrapper\.py$/);
    expect(run.mock.calls.slice(3).map((call) => call[1].slice(0, 5))).toEqual([
      ['-m', 'cadgen.cli', 'step', 'inspect', 'validate'],
      ['-m', 'cadgen.cli', 'step', 'inspect', 'validate'],
    ]);
    expect(await readFile(paths.modelPath, 'utf8')).toBe(ACCEPTED_STEP);
    expect(await readFile(join(paths.canonicalPackagePath, 'assembly.json'), 'utf8')).toBe(
      originalDescriptor
    );
    expect(await readFile(join(paths.canonicalPackagePath, 'original.cache'), 'utf8')).toBe(
      'preserve me'
    );
    expect(await readFile(paths.migratedSourcePath, 'utf8')).toBe(MIGRATED_SOURCE);
    await expect(stat(paths.sourcePath)).rejects.toThrow();
    expect((await stat(paths.migratedSourcePath)).mode & 0o777).toBe(0o640);
    const marker = JSON.parse(
      await readFile(cadMigrationMarkerPath(paths.sourcePath), 'utf8')
    ) as Record<string, unknown>;
    expect(marker).toMatchObject({
      version: 1,
      state: 'committed',
      legacySourcePath: 'bracket.step.py',
      migratedSourcePath: 'bracket.py',
      modelPath: 'bracket.step',
    });
    expect(marker).not.toHaveProperty('migratedSourceBase64');
  });

  it('rejects geometry mismatch without changing any project file', async () => {
    const paths = await migrationWorkspace();
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) =>
      emulateIsolatedCommand(args, options, CHANGED_COMPONENT_HASH)
    );

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toContain('rebuilt different geometry or placements');
    expect(result.error).toContain('remain unchanged');
    expect(await readFile(paths.sourcePath, 'utf8')).toBe(LEGACY_SOURCE);
    expect(await readFile(paths.modelPath, 'utf8')).toBe(ACCEPTED_STEP);
    await expect(stat(paths.migratedSourcePath)).rejects.toThrow();
    await expect(stat(cadMigrationMarkerPath(paths.sourcePath))).rejects.toThrow();
  });

  it('keeps project files intact after an isolated migration command fails', async () => {
    const paths = await migrationWorkspace();
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) => {
      if (args[0] === '-m' && args[1] === 'cadgen.migrate') {
        throw Object.assign(new Error('migration failed'), { stderr: 'unsupported legacy syntax' });
      }
      return emulateIsolatedCommand(args, options);
    });

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result).toEqual({
      success: false,
      error: 'unsupported legacy syntax The original source and STEP remain unchanged.',
    });
    expect(await readFile(paths.sourcePath, 'utf8')).toBe(LEGACY_SOURCE);
    expect(await readFile(paths.modelPath, 'utf8')).toBe(ACCEPTED_STEP);
  });

  it('fails closed when only an unverified plain source remains', async () => {
    const paths = await migrationWorkspace();
    await writeFile(paths.migratedSourcePath, MIGRATED_SOURCE);
    await unlink(paths.sourcePath);
    const run = vi.fn<CadMigrationDependencies['run']>();

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toContain('legacy CAD source is missing');
    expect(result.error).toContain('no verified migration marker');
    expect(run).not.toHaveBeenCalled();
    expect(await readFile(paths.migratedSourcePath, 'utf8')).toBe(MIGRATED_SOURCE);
  });

  it('resumes cleanup from a durable verified marker after a crash', async () => {
    const paths = await migrationWorkspace();
    const model = await readFile(paths.modelPath);
    await unlink(paths.sourcePath);
    writeCadVerifiedMigrationMarker(cadMigrationMarkerPath(paths.sourcePath), {
      version: 1,
      state: 'verified',
      legacySourcePath: 'bracket.step.py',
      migratedSourcePath: 'bracket.py',
      modelPath: 'bracket.step',
      originalSourceHash: cadMigrationSha256(Buffer.from(LEGACY_SOURCE)),
      modelHash: cadMigrationSha256(model),
      migratedSourceHash: cadMigrationSha256(Buffer.from(MIGRATED_SOURCE)),
      sourceMode: 0o640,
      migratedSourceBase64: Buffer.from(MIGRATED_SOURCE).toString('base64'),
    });
    const run = vi.fn<CadMigrationDependencies['run']>();

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result).toEqual({
      success: true,
      sourcePath: 'bracket.py',
      modelPath: 'bracket.step',
      openPath: 'bracket.step',
    });
    expect(run).not.toHaveBeenCalled();
    expect(await readFile(paths.migratedSourcePath, 'utf8')).toBe(MIGRATED_SOURCE);
    expect(
      JSON.parse(await readFile(cadMigrationMarkerPath(paths.sourcePath), 'utf8'))
    ).toMatchObject({ state: 'committed' });
  });

  it('coalesces duplicate migration requests into one isolated build', async () => {
    const paths = await migrationWorkspace();
    let releaseMigration!: () => void;
    const release = new Promise<void>((resolve) => {
      releaseMigration = resolve;
    });
    let markStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      markStarted = resolve;
    });
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) => {
      if (args[0] === '-m' && args[1] === 'cadgen.migrate') {
        markStarted();
        await release;
      }
      return emulateIsolatedCommand(args, options);
    });
    const deps = dependencies(paths.pythonPath, run);

    const first = migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      deps
    );
    await started;
    const second = migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      deps
    );
    releaseMigration();

    await expect(first).resolves.toMatchObject({ success: true, sourcePath: 'bracket.py' });
    await expect(second).resolves.toMatchObject({ success: true, sourcePath: 'bracket.py' });
    expect(run).toHaveBeenCalledTimes(5);
  });

  it('uses the correct artifact identity for legacy .stp.py models', async () => {
    const paths = await migrationWorkspace({ suffix: '.stp.py' });
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) =>
      emulateIsolatedCommand(args, options)
    );

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result).toEqual({
      success: true,
      sourcePath: 'bracket.py',
      modelPath: 'bracket.stp',
      openPath: 'bracket.stp',
    });
    expect(run.mock.calls[1]?.[1]).toEqual(['-m', 'cadgen.migrate', 'bracket.stp.py']);
    expect(await readFile(paths.modelPath, 'utf8')).toBe(ACCEPTED_STEP);
  });

  it('rejects sources outside the workspace and symlinked project sources', async () => {
    const workspace = await migrationWorkspace();
    const outside = await migrationWorkspace();
    const run = vi.fn<CadMigrationDependencies['run']>();
    const outsideResult = await migrateLegacyCadModel(
      { workspacePath: workspace.workspacePath, filePath: outside.sourcePath },
      dependencies(workspace.pythonPath, run)
    );
    expect(outsideResult).toEqual({
      success: false,
      error: 'CAD files must stay inside the active project workspace.',
    });

    await unlink(workspace.sourcePath);
    await symlink(outside.sourcePath, workspace.sourcePath);
    const symlinkResult = await migrateLegacyCadModel(
      { workspacePath: workspace.workspacePath, filePath: workspace.sourcePath },
      dependencies(workspace.pythonPath, run)
    );
    expect(symlinkResult).toEqual({
      success: false,
      error: 'The legacy CAD source must be a regular project file.',
    });
    expect((await lstat(workspace.sourcePath)).isSymbolicLink()).toBe(true);
    expect(run).not.toHaveBeenCalled();
  });

  it('atomically restores the accepted STEP when an external command mutates it', async () => {
    const paths = await migrationWorkspace();
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) => {
      if (args[0] === '-m' && args[1] === 'cadgen.migrate') {
        await writeFile(paths.modelPath, 'unexpected-step-v2');
      }
      return emulateIsolatedCommand(args, options);
    });

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toContain('unexpectedly changed the accepted STEP');
    expect(result.error).toContain('restored atomically');
    expect(await readFile(paths.modelPath, 'utf8')).toBe(ACCEPTED_STEP);
    expect(await readFile(paths.sourcePath, 'utf8')).toBe(LEGACY_SOURCE);
  });

  it('reports rollback failure instead of claiming recovery', async () => {
    const paths = await migrationWorkspace();
    const run = vi.fn<CadMigrationDependencies['run']>(async (_executable, args, options) => {
      if (args[0] === '-m' && args[1] === 'cadgen.migrate') {
        await unlink(paths.modelPath);
        await mkdir(paths.modelPath);
      }
      return emulateIsolatedCommand(args, options);
    });

    const result = await migrateLegacyCadModel(
      { workspacePath: paths.workspacePath, filePath: paths.sourcePath },
      dependencies(paths.pythonPath, run)
    );

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toContain('Rollback failed');
    expect(result.error).toContain('Manual recovery is required');
    expect(result.error).not.toContain('restored atomically');
  });
});
