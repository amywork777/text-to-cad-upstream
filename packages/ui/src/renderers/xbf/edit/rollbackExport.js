/**
 * What Export writes (`useExportView`) while CAD mode's rollback bar may be up: the displayed document and revision alone,
 * which is the part's, never the bar's body drawn in its place. `current` is the export of what is on screen now (null for
 * none); `kept` the one written last; `rollback` the bar's body's id while the bar is up; `bars` every bar body's id opened
 * here, so a body still on screen just after the bar went (the part on its way back) is not taken for the part. The part's
 * own export is taken whenever it is the one on screen, a new revision of it included.
 *
 * @param {{ current: { doc: string } | null, kept: object | null, rollback: string, bars: ReadonlySet<string> }} state
 * @returns {object | null}
 */
export function rollbackExport({ current, kept, rollback, bars }) {
  const body = Boolean(rollback) || (current !== null && bars.has(current.doc));
  return body ? kept : current;
}
