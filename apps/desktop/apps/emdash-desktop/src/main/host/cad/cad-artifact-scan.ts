import { readdirSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import type { CadArtifactScanResult } from '@core/features/browser/api';

/** Model artifacts the CAD Viewer can show. Recipe sources are edited, not revealed. */
const REVEALABLE_SUFFIXES = ['.step', '.stp', '.stl', '.3mf', '.glb', '.dxf'] as const;

/** Directories that only ever hold runtime, cache, dependency, or build files. */
const SKIPPED_DIRECTORIES = new Set([
  '.git',
  '.hg',
  '.svn',
  'node_modules',
  '.venv',
  'venv',
  '.cad-runtime',
  '__pycache__',
  '__cadgen__',
  '.nx',
  '.cache',
  'dist',
  'build',
  'release',
  'out',
]);
const MAX_DEPTH = 8;
const MAX_ENTRIES = 50_000;

export function isRevealableCadArtifact(path: string): boolean {
  const lower = path.toLowerCase();
  return REVEALABLE_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

/**
 * Model artifacts under a workspace written at or after `sinceMs`, newest
 * last. The desktop calls this when an agent turn ends so a model produced by
 * the agent, or by any subagent writing into the same workspace, can be
 * opened without the file tree having that folder expanded.
 */
export function listCadArtifacts(input: {
  workspacePath: string;
  sinceMs: number;
}): CadArtifactScanResult {
  const root = resolve(input.workspacePath);
  try {
    if (!statSync(root).isDirectory()) {
      return { success: false, error: `Workspace is not a directory: ${root}` };
    }
  } catch {
    return { success: false, error: `Workspace does not exist: ${root}` };
  }

  const artifacts: Array<{ path: string; mtimeMs: number }> = [];
  let visited = 0;
  let truncated = false;

  const walk = (directory: string, depth: number): void => {
    if (depth > MAX_DEPTH || truncated) return;
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (++visited > MAX_ENTRIES) {
        truncated = true;
        return;
      }
      const full = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!SKIPPED_DIRECTORIES.has(entry.name)) walk(full, depth + 1);
        continue;
      }
      if (!entry.isFile() || !isRevealableCadArtifact(entry.name)) continue;
      let mtimeMs: number;
      try {
        mtimeMs = statSync(full).mtimeMs;
      } catch {
        continue;
      }
      if (mtimeMs < input.sinceMs) continue;
      artifacts.push({ path: relative(root, full).split(sep).join('/'), mtimeMs });
    }
  };
  walk(root, 0);

  artifacts.sort(
    (left, right) => left.mtimeMs - right.mtimeMs || left.path.localeCompare(right.path)
  );
  return { success: true, artifacts, truncated };
}
