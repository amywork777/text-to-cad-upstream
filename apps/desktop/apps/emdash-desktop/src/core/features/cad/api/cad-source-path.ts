const LEGACY_PYTHON_CAD_SOURCE_RE = /\.(?:step|stp)\.py$/i;

export function isLegacyCadSourcePath(path: string): boolean {
  return LEGACY_PYTHON_CAD_SOURCE_RE.test(path.trim());
}

export function isEditableCadSourcePath(path: string): boolean {
  const normalized = path.trim();
  return /\.py$/i.test(normalized) && !isLegacyCadSourcePath(normalized);
}

export function cadSourcePanelPresentation(path: string): {
  legacy: boolean;
  readOnly: boolean;
  subtitle: string;
} {
  const legacy = isLegacyCadSourcePath(path);
  return legacy
    ? { legacy: true, readOnly: true, subtitle: 'Legacy model · view only' }
    : {
        legacy: false,
        readOnly: false,
        subtitle: 'Model recipe · rebuilds canonical STEP · ⌘S to save',
      };
}

export function migratedCadSourcePath(path: string): string | null {
  const normalized = path.trim();
  return isLegacyCadSourcePath(normalized)
    ? normalized.replace(/\.(?:step|stp)\.py$/i, '.py')
    : null;
}

export function canonicalCadModelPathForLegacySource(path: string): string | null {
  const normalized = path.trim();
  return isLegacyCadSourcePath(normalized) ? normalized.slice(0, -3) : null;
}
