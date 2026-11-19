/**
 * Studio's settings in the tab record (`tabRecord.ts`'s `normalizeTabSettings` reads them with this): edit mode's layout
 * for a part script (`xbf/edit/editLayout.js`), and where each part it opened came from (`xbf/edit/openedFrom.js`), so
 * the part's design tree leads back to the assembly. Tab-wide, as every setting is.
 */

/** How a part script's model opens: laid out for modeling it by hand (edit mode), or for asking the AI. */
export type EditLayout = 'manual' | 'ai';
/** The assembly a part was opened from (Open Part), so the part's design tree leads back to it. */
export interface OpenedFrom { file: string; title: string }
/** How many parts' way back the tab keeps: the latest opened. */
export const OPENED_FROM_LIMIT = 20;

declare module './tabRecord.js' {
  interface TabSettings {
    /** Edit mode's layout for a part script (`xbf/edit/editLayout.js`): Manual (the default) or AI. */
    editLayout: EditLayout;
    /** Where Open Part came from (`xbf/edit/openedFrom.js`), by the part's absolute path, oldest first. */
    openedFrom: Record<string, OpenedFrom>;
  }
}

const plainObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const EDIT_LAYOUTS: readonly EditLayout[] = ['manual', 'ai'];

// Each part's way back: an assembly's file (not the part's own) and its title; the latest `OPENED_FROM_LIMIT`.
function normalizeOpenedFrom(value: unknown): Record<string, OpenedFrom> {
  const kept: Record<string, OpenedFrom> = {};
  const entries = Object.entries(plainObject(value) ? value : {}).filter(([part, from]) => part !== '' && plainObject(from)
    && typeof from.file === 'string' && from.file !== '' && from.file !== part && typeof from.title === 'string');
  for (const [part, from] of entries.slice(-OPENED_FROM_LIMIT)) {
    const { file, title } = from as OpenedFrom;
    kept[part] = { file, title };
  }
  return kept;
}

/** Studio's settings as the tab keeps them, from the record a store handed back. */
export function normalizeStudioSettings(record: Record<string, unknown>): { editLayout: EditLayout; openedFrom: Record<string, OpenedFrom> } {
  return {
    editLayout: EDIT_LAYOUTS.includes(record.editLayout as EditLayout) ? (record.editLayout as EditLayout) : 'manual',
    openedFrom: normalizeOpenedFrom(record.openedFrom),
  };
}
