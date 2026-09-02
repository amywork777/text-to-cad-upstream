import type { CadMigrationResult } from '@core/features/browser/api';

/**
 * cadgen 0.5 deleted its migration codemod: a legacy `<name>.step.py`
 * generator is migrated by hand (rename to a plain `.py`, decorate one
 * function with `@step`, delete the v0.4 sidecars and caches) per
 * docs/migrating-0.4-to-0.5.md. The desktop keeps legacy files view-only and
 * reports the playbook instead of pretending to rewrite source.
 */
export function migrateLegacyCadModel(input: {
  workspacePath: string;
  filePath: string;
}): CadMigrationResult {
  const name = input.filePath.split(/[\\/]/).at(-1) ?? input.filePath;
  const migrated = name.replace(/\.(?:step|stp)\.py$/i, '.py');
  return {
    success: false,
    error: `cadgen 0.5 has no migration tool. Rename ${name} to ${migrated}, convert gen_step() into one @step function, delete the old __cadgen__ and .step.js files, then rebuild (see docs/migrating-0.4-to-0.5.md).`,
  };
}
