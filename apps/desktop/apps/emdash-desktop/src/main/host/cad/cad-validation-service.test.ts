import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  cadMigrationMarkerPath,
  cadMigrationSha256,
  readCadVerifiedMigrationMarker,
  writeCadVerifiedMigrationMarker,
} from './cad-migration-marker';
import { cadgenProvenanceRecordPath, cadgenProvenanceRecordPaths } from './cad-recipe';
import {
  applyCadModelParameters,
  assertLegacyCadArtifactIsCurrent,
  cadArtifactOperationKey,
  cadArtifactIdentity,
  cadInspectionToolPlan,
  cadSourceRebuildToolPlan,
  cadToolEnvironment,
  cadValidationModelPath,
  cadValidationInputRevision,
  forgetCadModelProvenance,
  readCadModelHistory,
  resolveCadArtifactTarget,
  validateCadModel,
} from './cad-validation-service';

vi.mock('electron', () => ({ app: { getPath: () => '/tmp/hardcore-test-user-data' } }));

const temporaryDirectories: string[] = [];
const originalCadgenCacheDir = process.env.CADGEN_CACHE_DIR;
const originalCadPython = process.env.HARDCORE_CAD_PYTHON;
const originalCadTestLog = process.env.HARDCORE_CAD_TEST_LOG;

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true })));
  restoreEnvironment('CADGEN_CACHE_DIR', originalCadgenCacheDir);
  restoreEnvironment('HARDCORE_CAD_PYTHON', originalCadPython);
  restoreEnvironment('HARDCORE_CAD_TEST_LOG', originalCadTestLog);
});

describe('CAD validation service path boundary', () => {
  it('rejects a CAD target outside its model workspace', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);

    const result = await validateCadModel({
      workspacePath,
      filePath: join(tmpdir(), 'outside.step'),
    });

    expect(result).toEqual({
      success: false,
      error: 'CAD files must be inside the active model workspace.',
    });
  });

  it('reports a missing CAD file before starting the runtime', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'missing.step.py');

    const result = await validateCadModel({ workspacePath, filePath });

    expect(result).toEqual({
      success: false,
      error: `Canonical CAD artifact does not exist: ${join(workspacePath, 'missing.step')}. Rebuild its source explicitly to create it.`,
    });
  });

  it('resolves relative CAD paths against the active workspace', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    await mkdir(join(workspacePath, 'models'));
    await writeFile(join(workspacePath, 'models', 'car.step'), 'accepted-step');

    expect(resolveCadArtifactTarget({ workspacePath, filePath: 'models/car.step' })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'models/car.step',
    });
    expect(cadArtifactOperationKey({ workspacePath, filePath: 'models/car.step' })).toBe(
      cadArtifactOperationKey({
        workspacePath,
        filePath: join(workspacePath, 'models', 'car.step'),
      })
    );
  });

  it('derives the canonical revision from the accepted artifact bytes', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    await writeFile(join(workspacePath, 'car.py'), 'source-v2');
    await writeFile(join(workspacePath, 'car.step'), 'step-v2');

    const sourceHash = createHash('sha256').update('source-v2').digest('hex');
    const modelHash = createHash('sha256').update('step-v2').digest('hex');
    expect(cadArtifactIdentity(workspacePath, 'car.step', 'car.py')).toEqual({
      revisionId: `sha256:${modelHash}`,
      modelPath: 'car.step',
      modelHash,
      sourcePath: 'car.py',
      sourceHash,
    });
  });

  it('distinguishes same-path validation requests by current source bytes', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'car.py');
    await writeFile(filePath, 'OVERALL_LENGTH = 4200');
    await writeFile(join(workspacePath, 'car.step'), 'step-v1');
    const initial = cadValidationInputRevision({ workspacePath, filePath });

    await writeFile(filePath, 'OVERALL_LENGTH = 4300');

    expect(cadValidationInputRevision({ workspacePath, filePath })).not.toBe(initial);
  });

  it("follows cadgen's provenance record from a STEP back to its recipe", async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'models', 'car.py');
    const stepPath = join(workspacePath, 'models', 'car.step');
    await mkdir(dirname(stepPath), { recursive: true });
    await writeFile(
      sourcePath,
      'from cadgen import build123d as bd\nfrom cadgen import step\n\n@step()\ndef car():\n    return bd.Box(10, 10, 10)\n'
    );
    await writeFile(stepPath, 'step-v1');
    await writeProvenanceRecord(workspacePath, stepPath, {
      sourceKind: 'python',
      sourcePath: 'car.py',
    });
    const initial = cadValidationInputRevision({ workspacePath, filePath: stepPath });

    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'models/car.step',
      relativeSourcePath: 'models/car.py',
    });

    await writeFile(
      sourcePath,
      'from cadgen import build123d as bd\nfrom cadgen import step\n\n@step()\ndef car():\n    return bd.Box(10, 10, 10)\n'.replace(
        '10, 10, 10',
        '12, 10, 10'
      )
    );

    expect(cadValidationInputRevision({ workspacePath, filePath: stepPath })).not.toBe(initial);
  });

  it("forgets cadgen's records for a restored STEP so the doors read its bytes again", async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const stepPath = join(workspacePath, 'plate.step');
    await writeFile(
      join(workspacePath, 'plate.py'),
      'from cadgen import step\n\n@step()\ndef plate(): ...\n'
    );
    await writeFile(stepPath, 'accepted-step');
    await writeProvenanceRecord(workspacePath, stepPath, {
      sourceKind: 'python',
      sourcePath: 'plate.py',
    });
    const [, ledgerPath] = cadgenProvenanceRecordPaths(stepPath, process.env.CADGEN_CACHE_DIR);
    await writeFile(
      ledgerPath,
      JSON.stringify({ exports: { 'plate.step': { closure: 'rejected' } } })
    );
    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toMatchObject({
      relativeSourcePath: 'plate.py',
    });

    const forgotten = forgetCadModelProvenance({ workspacePath, filePath: stepPath });

    expect(forgotten).toEqual({
      success: true,
      removed: cadgenProvenanceRecordPaths(stepPath, process.env.CADGEN_CACHE_DIR),
    });
    expect(existsSync(ledgerPath)).toBe(false);
    // Without a record the STEP reads as an import: bytes only, no recipe link.
    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'plate.step',
    });
    expect(forgetCadModelProvenance({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      removed: [],
    });
  });

  it('keeps stale linked source bytes from redefining the accepted STEP revision', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'car.py');
    await writeFile(sourcePath, 'OVERALL_LENGTH = 4200');
    await writeFile(join(workspacePath, 'car.step'), 'accepted-step');
    const accepted = cadArtifactIdentity(workspacePath, 'car.step', 'car.py');

    await writeFile(sourcePath, 'OVERALL_LENGTH = 4300');
    const reopened = cadArtifactIdentity(workspacePath, 'car.step', 'car.py');

    expect(reopened.revisionId).toBe(accepted.revisionId);
    expect(reopened.modelHash).toBe(accepted.modelHash);
    expect(reopened.sourceHash).not.toBe(accepted.sourceHash);
    expect(resolveCadArtifactTarget({ workspacePath, filePath: sourcePath })).toMatchObject({
      success: true,
      relativeModelPath: 'car.step',
      relativeSourcePath: 'car.py',
    });
  });

  it('accepts a valid STEP when the recipe its record names is missing', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const stepPath = join(workspacePath, 'models', 'car.step');
    await mkdir(dirname(stepPath), { recursive: true });
    await writeFile(stepPath, 'accepted-step');
    await writeProvenanceRecord(workspacePath, stepPath, {
      sourceKind: 'python',
      sourcePath: 'car.py',
    });

    const target = resolveCadArtifactTarget({ workspacePath, filePath: stepPath });
    expect(target).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'models/car.step',
    });
    expect(cadArtifactIdentity(workspacePath, 'models/car.step')).toEqual({
      revisionId: `sha256:${createHash('sha256').update('accepted-step').digest('hex')}`,
      modelPath: 'models/car.step',
      modelHash: createHash('sha256').update('accepted-step').digest('hex'),
    });
  });

  it('does not guess that a same-stem Python file owns an imported STEP', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const stepPath = join(workspacePath, 'vendor.step');
    await writeFile(stepPath, 'imported-step');
    await writeFile(join(workspacePath, 'vendor.py'), 'UNRELATED_HELPER = True');

    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'vendor.step',
    });
  });

  it('rejects record provenance that escapes the model workspace', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    const outsidePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-outside-'));
    temporaryDirectories.push(workspacePath, outsidePath);
    const stepPath = join(workspacePath, 'models', 'car.step');
    const outsideSource = join(outsidePath, 'car.py');
    await mkdir(dirname(stepPath), { recursive: true });
    await writeFile(stepPath, 'step-v1');
    await writeFile(
      outsideSource,
      'from cadgen import build123d as bd\nfrom cadgen import step\n\n@step()\ndef car():\n    return bd.Box(10, 10, 10)\n'
    );
    await writeProvenanceRecord(workspacePath, stepPath, {
      sourceKind: 'python',
      sourcePath: relative(dirname(stepPath), outsideSource),
    });
    const initial = cadValidationInputRevision({ workspacePath, filePath: stepPath });

    await writeFile(
      outsideSource,
      'from cadgen import build123d as bd\nfrom cadgen import step\n\n@step()\ndef car():\n    return bd.Box(10, 10, 10)\n'.replace(
        '10, 10, 10',
        '12, 10, 10'
      )
    );

    expect(cadValidationInputRevision({ workspacePath, filePath: stepPath })).toBe(initial);
  });

  it('runs a recipe only through the explicit source rebuild path, never with --force', () => {
    expect(cadSourceRebuildToolPlan('car.py')).toEqual({
      tool: 'model',
      args: ['car.py', '--json', '--lock-timeout', '120'],
    });
  });

  it('serializes source rebuilds and read-only inspection by canonical STEP', () => {
    const workspacePath = join(tmpdir(), 'hardcore-operation-key');

    expect(
      cadArtifactOperationKey({ workspacePath, filePath: join(workspacePath, 'car.py') })
    ).toBe(cadArtifactOperationKey({ workspacePath, filePath: join(workspacePath, 'car.step') }));
  });

  it('serializes a custom @step(out=...) recipe with its canonical STEP', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-custom-operation-key-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'src', 'STEP', 'plate.py');
    const modelPath = join(workspacePath, 'STEP', 'plate.step');
    await mkdir(dirname(sourcePath), { recursive: true });
    await writeFile(
      sourcePath,
      [
        'from cadgen import step',
        '',
        '@step(out="../../STEP/plate.step")',
        'def plate():',
        '    return None',
      ].join('\n')
    );

    expect(cadArtifactOperationKey({ workspacePath, filePath: sourcePath })).toBe(
      cadArtifactOperationKey({ workspacePath, filePath: modelPath })
    );
  });

  it('serializes a 0.5 @step(out=...) project recipe with its format-folder STEP', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-current-operation-key-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'src', 'plate.py');
    const modelPath = join(workspacePath, 'STEP', 'plate.step');
    await mkdir(dirname(sourcePath), { recursive: true });
    await writeFile(
      sourcePath,
      [
        'from cadgen import step',
        '',
        '@step(out="../STEP/plate.step")',
        'def plate():',
        '    return None',
      ].join('\n')
    );
    await mkdir(dirname(modelPath), { recursive: true });
    await writeFile(modelPath, 'accepted-step');

    expect(cadArtifactOperationKey({ workspacePath, filePath: sourcePath })).toBe(
      cadArtifactOperationKey({ workspacePath, filePath: modelPath })
    );
    expect(resolveCadArtifactTarget({ workspacePath, filePath: sourcePath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: join('STEP', 'plate.step'),
      relativeSourcePath: join('src', 'plate.py'),
    });
  });

  it('prefers persisted model/source provenance over removed render-package metadata', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-explicit-cad-link-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'src', 'car.py');
    const stepPath = join(workspacePath, 'STEP', 'car.step');
    await mkdir(dirname(sourcePath), { recursive: true });
    await mkdir(dirname(stepPath), { recursive: true });
    await writeFile(sourcePath, 'from cadgen import step\n@step()\ndef car(): ...\n');
    await writeFile(stepPath, 'accepted-step');

    expect(
      resolveCadArtifactTarget({
        workspacePath,
        filePath: stepPath,
        sourcePath: join('src', 'car.py'),
      })
    ).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: join('STEP', 'car.step'),
      relativeSourcePath: join('src', 'car.py'),
    });
  });

  it('does not invent source provenance from an unestablished .step.json file', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-untrusted-cad-link-'));
    temporaryDirectories.push(workspacePath);
    const stepPath = join(workspacePath, 'STEP', 'arm.step');
    await mkdir(dirname(stepPath), { recursive: true });
    await writeFile(stepPath, 'accepted-step');
    await writeFile(
      `${stepPath}.json`,
      JSON.stringify({ sourcePath: '../src/arm.py', sourceHash: 'untrusted' })
    );

    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: join('STEP', 'arm.step'),
    });
  });

  it('recognizes aliased multiline custom STEP output declarations', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-custom-operation-key-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'recipes', 'plate.py');
    const modelPath = join(workspacePath, 'artifacts', 'plate.stp');
    await mkdir(dirname(sourcePath), { recursive: true });
    await writeFile(
      sourcePath,
      [
        'import cadgen as cg',
        '',
        '@cg.step(',
        '    kind="part",',
        '    out="../artifacts/plate.stp",',
        ')',
        'def plate():',
        '    return None',
      ].join('\n')
    );

    expect(cadArtifactOperationKey({ workspacePath, filePath: sourcePath })).toBe(
      cadArtifactOperationKey({ workspacePath, filePath: modelPath })
    );
  });

  it('does not borrow out= from a different decorator on the same function', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-custom-operation-key-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'plate.py');
    await writeFile(
      sourcePath,
      [
        'from cadgen import step',
        '',
        '@step',
        '@metadata(out="elsewhere/plate.step")',
        'def plate():',
        '    return None',
      ].join('\n')
    );

    expect(cadArtifactOperationKey({ workspacePath, filePath: sourcePath })).toBe(
      cadArtifactOperationKey({ workspacePath, filePath: join(workspacePath, 'plate.step') })
    );
  });

  it('opens a canonical STEP using only read-only inspection commands', () => {
    const plan = cadInspectionToolPlan('vendor.step');
    expect(plan).toEqual([
      {
        tool: 'cadgen',
        args: ['step', 'inspect', 'refs', 'vendor.step', '--facts', '--planes', '--positioning'],
      },
      { tool: 'cadgen', args: ['step', 'inspect', 'validate', 'vendor.step'] },
    ]);
    expect(plan.flatMap((command) => command.args)).not.toContain('import');
    expect(plan.flatMap((command) => command.args)).not.toContain('--force');
  });

  it('never executes or imports a linked recipe during open validation', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-read-only-'));
    temporaryDirectories.push(workspacePath);
    const sourcePath = join(workspacePath, 'car.py');
    const stepPath = join(workspacePath, 'car.step');
    const commandLog = join(workspacePath, 'commands.log');
    const fakePython = join(workspacePath, 'fake-python');
    await writeFile(
      fakePython,
      '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HARDCORE_CAD_TEST_LOG"\ncase "$*" in\n  *"inspect refs"*) printf "%s\\n" \'{"ok":true,"tokens":[]}\' ;;\n  *) printf "%s\\n" \'{"ok":true}\' ;;\nesac\n'
    );
    await chmod(fakePython, 0o755);
    await writeFile(sourcePath, 'raise RuntimeError("must never run on open")\n');
    await writeFile(stepPath, 'accepted-step');
    process.env.HARDCORE_CAD_PYTHON = fakePython;
    process.env.HARDCORE_CAD_TEST_LOG = commandLog;

    const result = await validateCadModel({ workspacePath, filePath: sourcePath });

    expect(result).toMatchObject({
      success: true,
      artifact: { modelPath: 'car.step', sourcePath: 'car.py' },
    });
    expect(await readFile(stepPath, 'utf8')).toBe('accepted-step');
    const commands = await readFile(commandLog, 'utf8');
    expect(commands).toContain('step inspect refs car.step');
    expect(commands).toContain('step inspect validate car.step');
    expect(commands).not.toContain('import');
    expect(commands).not.toContain('--force');
    expect(commands).not.toContain('car.py');
  });

  it('resolves cadgen CAD references to the accepted STEP artifact', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);

    expect(
      cadValidationModelPath(workspacePath, 'emdash-smoke.py', {
        ok: true,
        sourceRef: 'emdash-smoke.py',
        cadPath: 'emdash-smoke',
        kind: 'part',
        outcome: 'built',
        packagePath: '/home/amy/.cache/cadgen/packages/abc-v17',
      })
    ).toBe('emdash-smoke.step');
  });

  it('keeps an unchanged legacy source viewable through its accepted STEP', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const source = 'from build123d import Box\n\ndef gen_step():\n    return Box(10, 10, 10)\n';
    const sourceHash = createHash('sha256').update(source).digest('hex');
    await writeFile(join(workspacePath, 'legacy.step.py'), source);
    await writeFile(
      join(workspacePath, 'legacy.step'),
      `ISO-10303-21;\nDESCRIPTIVE_REPRESENTATION_ITEM('cadgen:sourceHash','${sourceHash}');\nEND-ISO-10303-21;\n`
    );

    expect(assertLegacyCadArtifactIsCurrent(workspacePath, 'legacy.step.py')).toBe('legacy.step');
    expect(
      resolveCadArtifactTarget({
        workspacePath,
        filePath: join(workspacePath, 'legacy.step.py'),
      })
    ).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'legacy.step',
      relativeSourcePath: 'legacy.step.py',
    });
  });

  it('refuses stale legacy geometry instead of validating an edited source against an old STEP', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const original = 'def gen_step():\n    return 10\n';
    const originalHash = createHash('sha256').update(original).digest('hex');
    await writeFile(join(workspacePath, 'legacy.step.py'), 'def gen_step():\n    return 20\n');
    await writeFile(
      join(workspacePath, 'legacy.step'),
      `DESCRIPTIVE_REPRESENTATION_ITEM('cadgen:sourceHash','${originalHash}');\n`
    );

    expect(() => assertLegacyCadArtifactIsCurrent(workspacePath, 'legacy.step.py')).toThrow(
      'cannot be proven to match'
    );
  });

  it('does not trust a plain sibling when both naming conventions exist without a marker', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const legacyPath = join(workspacePath, 'bracket.step.py');
    const plainPath = join(workspacePath, 'bracket.py');
    const stepPath = join(workspacePath, 'bracket.step');
    const packagePath = join(workspacePath, '__cadgen__', 'models', 'bracket.step');
    await mkdir(packagePath, { recursive: true });
    await writeFile(legacyPath, 'LEGACY = 1');
    await writeFile(plainPath, 'WIDTH = 20');
    await writeFile(stepPath, 'step-v1');
    await writeFile(
      join(packagePath, 'assembly.json'),
      JSON.stringify({ sourceKind: 'python', sourcePath: 'bracket.step.py' })
    );
    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'bracket.step',
      relativeSourcePath: 'bracket.step.py',
    });
  });

  it('uses proven migrated provenance when restart sees a verified crash marker', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const legacyPath = join(workspacePath, 'bracket.step.py');
    const plainPath = join(workspacePath, 'bracket.py');
    const stepPath = join(workspacePath, 'bracket.step');
    const packagePath = join(workspacePath, '__cadgen__', 'models', 'bracket.step');
    const legacy = Buffer.from('LEGACY = 1');
    const migrated = Buffer.from('WIDTH = 20');
    const step = Buffer.from('step-v1');
    await mkdir(packagePath, { recursive: true });
    await writeFile(legacyPath, legacy);
    await writeFile(plainPath, migrated);
    await writeFile(stepPath, step);
    await writeFile(
      join(packagePath, 'assembly.json'),
      JSON.stringify({ sourceKind: 'python', sourcePath: 'bracket.step.py' })
    );
    writeCadVerifiedMigrationMarker(cadMigrationMarkerPath(legacyPath), {
      version: 1,
      state: 'verified',
      legacySourcePath: 'bracket.step.py',
      migratedSourcePath: 'bracket.py',
      modelPath: 'bracket.step',
      originalSourceHash: cadMigrationSha256(legacy),
      modelHash: cadMigrationSha256(step),
      migratedSourceHash: cadMigrationSha256(migrated),
      sourceMode: 0o644,
      migratedSourceBase64: migrated.toString('base64'),
    });

    expect(
      readCadVerifiedMigrationMarker({
        workspacePath,
        legacySourcePath: legacyPath,
        migratedSourcePath: plainPath,
        modelPath: stepPath,
        requireMigratedSource: true,
      })
    ).toMatchObject({ success: true, marker: { state: 'verified' } });

    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'bracket.step',
      relativeSourcePath: 'bracket.py',
    });
  });

  it('preserves migrated provenance after successful cleanup removes the legacy source', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-validation-'));
    temporaryDirectories.push(workspacePath);
    const legacyPath = join(workspacePath, 'bracket.step.py');
    const plainPath = join(workspacePath, 'bracket.py');
    const stepPath = join(workspacePath, 'bracket.step');
    const packagePath = join(workspacePath, '__cadgen__', 'models', 'bracket.step');
    const migrated = Buffer.from('WIDTH = 20');
    const step = Buffer.from('step-v1');
    await mkdir(packagePath, { recursive: true });
    await writeFile(plainPath, migrated);
    await writeFile(stepPath, step);
    await writeFile(
      join(packagePath, 'assembly.json'),
      JSON.stringify({ sourceKind: 'python', sourcePath: 'bracket.step.py' })
    );
    writeCadVerifiedMigrationMarker(cadMigrationMarkerPath(legacyPath), {
      version: 1,
      state: 'committed',
      legacySourcePath: 'bracket.step.py',
      migratedSourcePath: 'bracket.py',
      modelPath: 'bracket.step',
      originalSourceHash: cadMigrationSha256(Buffer.from('LEGACY = 1')),
      modelHash: cadMigrationSha256(step),
      migratedSourceHash: cadMigrationSha256(migrated),
      sourceMode: 0o644,
    });

    expect(resolveCadArtifactTarget({ workspacePath, filePath: stepPath })).toEqual({
      success: true,
      workspacePath,
      relativeModelPath: 'bracket.step',
      relativeSourcePath: 'bracket.py',
    });
  });

  it('runs generators without reusing same-second Python bytecode', () => {
    const environment = cadToolEnvironment({ PATH: '/usr/bin' });

    expect(environment).toMatchObject({
      PATH: '/usr/bin',
      PYTHONDONTWRITEBYTECODE: '1',
    });
    expect(environment.PYTHONPYCACHEPREFIX).toContain('hardcore-cad-no-bytecode-');
  });

  it('reads source-derived features and explicit design parameters', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-history-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'bracket.py');
    await writeFile(
      filePath,
      '# @cad-parameter {"label":"Width","min":10,"max":30,"step":1,"unit":"mm"}\nWIDTH = 20\n\nfrom cadgen import step\n\n@step()\ndef bracket():\n    with BuildPart() as part:\n        Box(WIDTH, 10, 4)\n    return part.part\n'
    );

    const result = readCadModelHistory({ workspacePath, filePath });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.history.groups).toEqual([expect.objectContaining({ functionName: 'bracket' })]);
    expect(result.history.parameters).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'width',
          defaultValue: 20,
          unit: 'mm',
          origin: 'declared',
        }),
        expect.objectContaining({ symbol: 'Box.width', origin: 'feature-literal' }),
        expect.objectContaining({ symbol: 'Box.height', origin: 'feature-literal' }),
      ])
    );
  });

  it('applies parameters only against the expected source hash', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-history-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'bracket.py');
    await writeFile(
      filePath,
      '# @cad-parameter {"label":"Width","min":10,"max":30,"step":1}\nWIDTH = 20\n'
    );
    const loaded = readCadModelHistory({ workspacePath, filePath });
    expect(loaded.success).toBe(true);
    if (!loaded.success) return;

    const applied = applyCadModelParameters({
      workspacePath,
      filePath,
      expectedSourceHash: loaded.sourceHash,
      values: { width: 24 },
    });

    expect(applied).toMatchObject({ success: true, appliedValues: { width: 24 } });
    expect(await readFile(filePath, 'utf8')).toContain('WIDTH = 24');
    expect(
      applyCadModelParameters({
        workspacePath,
        filePath,
        expectedSourceHash: loaded.sourceHash,
        values: { width: 25 },
      })
    ).toMatchObject({ success: false, conflict: true });
  });

  it('keeps parameter editing read-only for unmigrated legacy sources', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-history-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'bracket.step.py');
    const source = 'WIDTH = 20\n\ndef gen_step():\n    return WIDTH\n';
    await writeFile(filePath, source);

    const history = readCadModelHistory({ workspacePath, filePath });
    expect(history).toMatchObject({
      success: true,
      history: {
        parameters: [],
        diagnostics: expect.arrayContaining([expect.stringContaining('view-only')]),
      },
    });

    expect(
      applyCadModelParameters({
        workspacePath,
        filePath,
        expectedSourceHash: createHash('sha256').update(source).digest('hex'),
        values: { width: 30 },
      })
    ).toMatchObject({ success: false, error: expect.stringContaining('view-only') });
    expect(await readFile(filePath, 'utf8')).toBe(source);
  });

  it('applies automatically exposed feature dimensions through the same hash guard', async () => {
    const workspacePath = await mkdtemp(join(tmpdir(), 'hardcore-cad-history-'));
    temporaryDirectories.push(workspacePath);
    const filePath = join(workspacePath, 'automatic.py');
    await writeFile(
      filePath,
      'OVERALL_HEIGHT = 100\nROOF_Z = OVERALL_HEIGHT\n\ndef gen_step():\n    with BuildPart() as part:\n        Box(20, 10, ROOF_Z)\n    return part.part\n'
    );
    const loaded = readCadModelHistory({ workspacePath, filePath });
    expect(loaded.success).toBe(true);
    if (!loaded.success) return;
    const height = loaded.history.parameters.find(
      (parameter) => parameter.symbol === 'OVERALL_HEIGHT'
    );
    const length = loaded.history.parameters.find((parameter) => parameter.symbol === 'Box.length');
    expect(height).toBeDefined();
    expect(length).toBeDefined();

    const applied = applyCadModelParameters({
      workspacePath,
      filePath,
      expectedSourceHash: loaded.sourceHash,
      values: { [height!.id]: 150, [length!.id]: 25 },
    });

    expect(applied).toMatchObject({
      success: true,
      appliedValues: { [height!.id]: 150, [length!.id]: 25 },
    });
    expect(await readFile(filePath, 'utf8')).toContain('OVERALL_HEIGHT = 150');
    expect(await readFile(filePath, 'utf8')).toContain('Box(25, 10, ROOF_Z)');
  });
});

async function writeProvenanceRecord(
  workspacePath: string,
  stepPath: string,
  payload: Record<string, unknown>
): Promise<void> {
  const cacheRoot = join(workspacePath, '.cadgen-cache');
  process.env.CADGEN_CACHE_DIR = cacheRoot;
  const recordPath = cadgenProvenanceRecordPath(stepPath, cacheRoot);
  await mkdir(dirname(recordPath), { recursive: true });
  await writeFile(recordPath, JSON.stringify({ schemaVersion: 5, ...payload }));
}

function restoreEnvironment(name: string, value: string | undefined): void {
  if (value === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = value;
  }
}
