import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  assertCadBundleSource,
  assertPackagedCadResources,
  findPackagedCadBundleRoots,
  packagedResourcesRoot,
} from './cad-resources';

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe('CAD release resources', () => {
  it('fails before packaging when the Text-to-CAD submodule is absent', async () => {
    const root = await temporaryRoot();
    expect(() => assertCadBundleSource(root)).toThrow('submodule is incomplete');
  });

  it('accepts the complete pinned CAD source bundle', async () => {
    const root = await temporaryRoot();
    await createFiles(root, [
      'tooling/scripts/setup-cad.mjs',
      'tooling/cad-runtime-constraints.txt',
      'vendor/text-to-cad/.codex-plugin/plugin.json',
      'vendor/text-to-cad/.claude-plugin/plugin.json',
      'vendor/text-to-cad/skills/cad/SKILL.md',
      'vendor/text-to-cad/skills/cad-viewer/SKILL.md',
      'vendor/text-to-cad/skills/cad-viewer/scripts/viewer/package.json',
      'vendor/text-to-cad/skills/cad-viewer/scripts/viewer/dist/index.html',
      'vendor/text-to-cad/skills/cad-viewer/scripts/viewer/server/main.mjs',
      'vendor/text-to-cad/packages/cadgen/pyproject.toml',
    ]);
    expect(() => assertCadBundleSource(root)).not.toThrow();
  });

  it('finds and verifies macOS packaged resources', async () => {
    const root = await temporaryRoot();
    const appOutDir = join(root, 'mac-arm64');
    const resources = join(appOutDir, 'Hardcore.app', 'Contents', 'Resources');
    await createPackagedFiles(resources);
    expect(packagedResourcesRoot(appOutDir)).toBe(resources);
    expect(() => assertPackagedCadResources(appOutDir)).not.toThrow();
  });

  it('finds and verifies unpacked Linux and Windows resources', async () => {
    const root = await temporaryRoot();
    const appOutDir = join(root, 'linux-unpacked');
    const resources = join(appOutDir, 'resources');
    await createPackagedFiles(resources);
    expect(packagedResourcesRoot(appOutDir)).toBe(resources);
    expect(() => assertPackagedCadResources(appOutDir)).not.toThrow();
  });

  it('discovers each unpacked CAD bundle in a release directory', async () => {
    const root = await temporaryRoot();
    const linuxResources = join(root, 'release', 'linux-unpacked', 'resources');
    const macResources = join(
      root,
      'release',
      'mac-arm64',
      'Hardcore.app',
      'Contents',
      'Resources'
    );
    await createPackagedFiles(linuxResources);
    await createPackagedFiles(macResources);

    expect(findPackagedCadBundleRoots(join(root, 'release'))).toEqual(
      [join(linuxResources, 'hardcore-cad'), join(macResources, 'hardcore-cad')].sort()
    );
  });
});

async function temporaryRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'hardcore-cad-release-'));
  roots.push(root);
  return root;
}

async function createPackagedFiles(resources: string): Promise<void> {
  await createFiles(resources, [
    'hardcore-cad/tooling/scripts/setup-cad.mjs',
    'hardcore-cad/tooling/cad-runtime-constraints.txt',
    'hardcore-cad/vendor/text-to-cad/.codex-plugin/plugin.json',
    'hardcore-cad/vendor/text-to-cad/.claude-plugin/plugin.json',
    'hardcore-cad/vendor/text-to-cad/skills/cad/SKILL.md',
    'hardcore-cad/vendor/text-to-cad/skills/cad-viewer/SKILL.md',
    'hardcore-cad/vendor/text-to-cad/skills/cad-viewer/scripts/viewer/package.json',
    'hardcore-cad/vendor/text-to-cad/skills/cad-viewer/scripts/viewer/dist/index.html',
    'hardcore-cad/vendor/text-to-cad/skills/cad-viewer/scripts/viewer/server/main.mjs',
    'hardcore-cad/vendor/text-to-cad/packages/cadgen/pyproject.toml',
  ]);
}

async function createFiles(root: string, paths: readonly string[]): Promise<void> {
  await Promise.all(
    paths.map(async (path) => {
      const target = join(root, path);
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, 'fixture');
    })
  );
}
