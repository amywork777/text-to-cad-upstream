import { existsSync, readdirSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const HARDCORE_REPOSITORY_ROOT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../..'
);

const SOURCE_FILES = [
  '.codex-plugin/plugin.json',
  '.claude-plugin/plugin.json',
  'skills/cad/SKILL.md',
  'skills/cad-viewer/SKILL.md',
  'skills/cad-viewer/scripts/viewer/package.json',
  'skills/cad-viewer/scripts/viewer/dist/index.html',
  'skills/cad-viewer/scripts/viewer/server/main.mjs',
  'packages/cadgen/pyproject.toml',
] as const;

const PACKAGED_FILES = [
  'tooling/scripts/setup-cad.mjs',
  'tooling/cad-runtime-constraints.txt',
  ...SOURCE_FILES.map((path) => join('vendor', 'text-to-cad', path)),
] as const;

export function assertCadBundleSource(repositoryRoot = HARDCORE_REPOSITORY_ROOT): void {
  assertFiles(
    join(repositoryRoot, 'vendor', 'text-to-cad'),
    SOURCE_FILES,
    'The pinned Text-to-CAD submodule is incomplete. Check it out before packaging Hardcore.'
  );
  assertFiles(
    repositoryRoot,
    ['tooling/scripts/setup-cad.mjs', 'tooling/cad-runtime-constraints.txt'],
    'The CAD environment installer or dependency lock is missing from the repository.'
  );
}

export function assertPackagedCadResources(appOutDir: string): void {
  const resourcesRoot = packagedResourcesRoot(appOutDir);
  if (!resourcesRoot) {
    throw new Error(`Packaged app resources were not found under ${appOutDir}.`);
  }
  assertFiles(
    join(resourcesRoot, 'hardcore-cad'),
    PACKAGED_FILES,
    'The packaged app is missing its pinned CAD runtime or skills.'
  );
}

export function packagedResourcesRoot(appOutDir: string): string | null {
  const direct = join(appOutDir, 'resources');
  if (existsSync(direct)) return direct;

  const ownMacResources = basename(appOutDir).endsWith('.app')
    ? join(appOutDir, 'Contents', 'Resources')
    : null;
  if (ownMacResources && existsSync(ownMacResources)) return ownMacResources;

  if (!existsSync(appOutDir)) return null;
  const appBundle = readdirSync(appOutDir, { withFileTypes: true }).find(
    (entry) => entry.isDirectory() && entry.name.endsWith('.app')
  );
  const nestedMacResources = appBundle
    ? join(appOutDir, appBundle.name, 'Contents', 'Resources')
    : null;
  return nestedMacResources && existsSync(nestedMacResources) ? nestedMacResources : null;
}

export function findPackagedCadBundleRoots(releaseDir: string): string[] {
  if (!existsSync(releaseDir)) return [];

  const candidates = [
    releaseDir,
    ...readdirSync(releaseDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => join(releaseDir, entry.name)),
  ];
  const roots = new Set<string>();
  for (const candidate of candidates) {
    const resources = packagedResourcesRoot(candidate);
    if (!resources) continue;
    const bundle = join(resources, 'hardcore-cad');
    if (existsSync(join(bundle, 'tooling', 'scripts', 'setup-cad.mjs'))) {
      roots.add(resolve(bundle));
    }
  }
  return [...roots].sort();
}

function assertFiles(root: string, relativePaths: readonly string[], message: string): void {
  const missing = relativePaths.filter((path) => !existsSync(join(root, path)));
  if (missing.length === 0) return;
  throw new Error(`${message}\nMissing:\n${missing.map((path) => `- ${path}`).join('\n')}`);
}
