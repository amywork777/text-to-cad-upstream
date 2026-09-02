import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import {
  cadSourceRebuildToolPlan,
  cadgenPythonEnvironment,
  normalizeCadArtifactRelationship,
  resolveCadBuildArtifactPath,
  resolveCadgenCapability,
  resolveCadSourceArtifactRelationship,
  resolveCadViewerCapability,
} from './cadgen-compatibility';

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true })));
});

describe('Text-to-CAD compatibility boundary', () => {
  it('maps the pinned 0.4 bundled Viewer from its package capability', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const viewerRoot = join(root, 'skills', 'cad-viewer', 'scripts', 'viewer');
    const launcher = join(viewerRoot, 'server', 'main.mjs');
    await mkdir(dirname(launcher), { recursive: true });
    await writeFile(launcher, '');
    await writeViewerManifest(viewerRoot, {
      name: 'cad-viewer-runtime',
      version: '0.4.25',
    });

    expect(resolveCadViewerCapability(root)).toEqual({
      contract: 'pinned-0.4',
      layout: 'bundled-skill',
      viewerRoot,
      launcher,
      urlContract: 'root-query',
      supportsCadgenPython: true,
    });
  });

  it('recognizes the real pinned bundled Viewer manifest', () => {
    const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../../..');
    expect(resolveCadViewerCapability(join(repositoryRoot, 'vendor', 'text-to-cad'))).toMatchObject(
      {
        contract: 'pinned-0.4',
        layout: 'bundled-skill',
      }
    );
  });

  it('prefers the 0.5 app layout when its manifest declares cadgen-js', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const oldViewerRoot = join(root, 'skills', 'cad-viewer', 'scripts', 'viewer');
    const currentViewerRoot = join(root, 'apps', 'viewer');
    const oldLauncher = join(oldViewerRoot, 'server', 'main.mjs');
    const currentLauncher = join(currentViewerRoot, 'server', 'main.mjs');
    await mkdir(dirname(oldLauncher), { recursive: true });
    await mkdir(dirname(currentLauncher), { recursive: true });
    await writeFile(oldLauncher, '');
    await writeFile(currentLauncher, '');
    await writeViewerManifest(oldViewerRoot, {
      name: 'cad-viewer-runtime',
      version: '0.4.25',
    });
    await writeViewerManifest(currentViewerRoot, {
      name: 'cad-viewer',
      version: '0.5.0',
      runtimeDependency: 'cadgen-js',
    });

    expect(resolveCadViewerCapability(root)).toMatchObject({
      contract: 'step-first-0.5',
      layout: 'repository-app',
      viewerRoot: currentViewerRoot,
      launcher: currentLauncher,
    });
  });

  it('detects only supported cadgen package versions from pyproject metadata', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    await writeCadgenManifest(root, '0.4.25');
    expect(resolveCadgenCapability(root)).toMatchObject({
      contract: 'pinned-0.4',
      version: '0.4.25',
    });

    await writeCadgenManifest(root, '0.5.0');
    expect(resolveCadgenCapability(root)).toMatchObject({
      contract: 'step-first-0.5',
      version: '0.5.0',
    });

    await writeCadgenManifest(root, '0.6.0');
    expect(resolveCadgenCapability(root)).toBeNull();
  });

  it('does not infer a viewer contract from directory shape alone', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const launcher = join(root, 'apps', 'viewer', 'server', 'main.mjs');
    await mkdir(dirname(launcher), { recursive: true });
    await writeFile(launcher, '');

    expect(resolveCadViewerCapability(root)).toBeNull();
  });

  it('hands the managed interpreter to Viewer builds without dropping other variables', () => {
    expect(cadgenPythonEnvironment({ PATH: '/usr/bin' }, '/runtime/venv/bin/python')).toEqual({
      PATH: '/usr/bin',
      CADGEN_PYTHON: '/runtime/venv/bin/python',
    });
    expect(cadgenPythonEnvironment({ PATH: '/usr/bin' }, '')).toEqual({ PATH: '/usr/bin' });
  });

  it('resolves current out= project recipes from src into STEP', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const sourcePath = join(root, 'src', 'bracket.py');
    await mkdir(dirname(sourcePath), { recursive: true });
    await writeFile(
      sourcePath,
      [
        'from cadgen import step',
        '',
        '@step(out="../STEP/bracket.step")',
        'def bracket():',
        '    return None',
      ].join('\n')
    );

    expect(resolveCadSourceArtifactRelationship({ workspacePath: root, sourcePath })).toEqual({
      workspacePath: root,
      relativeSourcePath: join('src', 'bracket.py'),
      relativeModelPath: join('STEP', 'bracket.step'),
      declaration: 'out',
    });
  });

  it('keeps write= and sibling output compatibility for the pinned runtime', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const sourcePath = join(root, 'recipes', 'plate.py');
    await mkdir(dirname(sourcePath), { recursive: true });

    expect(
      resolveCadSourceArtifactRelationship({
        workspacePath: root,
        sourcePath,
        source: 'import cadgen as cg\n@cg.step(write="../models/plate.stp")\ndef plate(): ...',
      })
    ).toMatchObject({ relativeModelPath: join('models', 'plate.stp'), declaration: 'write' });
    expect(
      resolveCadSourceArtifactRelationship({
        workspacePath: root,
        sourcePath,
        source: 'from cadgen import step\n@step()\ndef plate(): ...',
      })
    ).toMatchObject({
      relativeModelPath: join('recipes', 'plate.step'),
      declaration: 'sibling-default',
    });
  });

  it('normalizes persisted source and model metadata without consulting cadgen caches', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');

    expect(
      normalizeCadArtifactRelationship({
        workspacePath: root,
        sourcePath: 'src/car.py',
        modelPath: 'STEP/car.step',
      })
    ).toEqual({
      workspacePath: root,
      relativeSourcePath: join('src', 'car.py'),
      relativeModelPath: join('STEP', 'car.step'),
      declaration: 'explicit',
    });
    expect(
      normalizeCadArtifactRelationship({
        workspacePath: root,
        sourcePath: '../outside.py',
        modelPath: 'STEP/car.step',
      })
    ).toBeNull();
  });

  it('keeps rebuild commands and output mapping inside the compatibility boundary', async () => {
    const root = await temporaryDirectory('hardcore-cadgen-compat-');
    const sourcePath = join(root, 'src', 'bracket.py');
    await mkdir(dirname(sourcePath), { recursive: true });
    await writeFile(
      sourcePath,
      'from cadgen import step\n@step(out="../STEP/bracket.step")\ndef bracket(): ...\n'
    );

    expect(cadSourceRebuildToolPlan(join('src', 'bracket.py'), 'step-first-0.5')).toEqual({
      tool: 'model',
      args: [join('src', 'bracket.py'), '--force', '--json'],
    });
    expect(
      resolveCadBuildArtifactPath({
        workspacePath: root,
        relativeSourcePath: join('src', 'bracket.py'),
        build: { ok: true },
        contract: 'step-first-0.5',
      })
    ).toBe(join('STEP', 'bracket.step'));
    expect(
      resolveCadBuildArtifactPath({
        workspacePath: root,
        relativeSourcePath: join('src', 'bracket.py'),
        build: { ok: true, cadPath: 'custom/bracket' },
        contract: 'step-first-0.5',
      })
    ).toBe(join('custom', 'bracket.step'));
  });
});

async function temporaryDirectory(prefix: string): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), prefix));
  temporaryDirectories.push(path);
  return path;
}

async function writeViewerManifest(
  viewerRoot: string,
  input: {
    name: 'cad-viewer' | 'cad-viewer-runtime';
    version: string;
    runtimeDependency?: 'cadgen-js' | 'cadjs';
  }
): Promise<void> {
  await writeFile(
    join(viewerRoot, 'package.json'),
    JSON.stringify({
      name: input.name,
      version: input.version,
      ...(input.runtimeDependency
        ? {
            dependencies: {
              [input.runtimeDependency]: `file:./packages/${input.runtimeDependency}`,
            },
          }
        : {}),
    })
  );
}

async function writeCadgenManifest(pluginRoot: string, version: string): Promise<void> {
  const path = join(pluginRoot, 'packages', 'cadgen', 'pyproject.toml');
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `[project]\nname = "cadgen"\nversion = "${version}"\n`);
}
