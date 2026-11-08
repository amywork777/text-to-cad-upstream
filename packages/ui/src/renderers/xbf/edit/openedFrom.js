/**
 * Where Open Part came from: the assembly a part was opened from, so the part's design tree can
 * lead back to it. One of the tab's settings (`openedFrom`, by the part's file), so it holds while
 * the tab moves between files; a part opened into a view of its own (a host that opens each file
 * in a tab of its own) has no way back, the assembly's view being beside it.
 */

/**
 * Remembers that `part` (its file's absolute path) was opened from `from` ({ file, title }): the
 * newest last, as the tab's settings keep them.
 * @param {{ preferences?: { openedFrom?: Record<string, object> } | null, onPreferenceChange?: (patch: object) => void }} services
 */
export function rememberOpenedFrom({ preferences, onPreferenceChange }, part, from) {
  if (!part || !from?.file) return;
  const { [part]: _previous, ...others } = preferences?.openedFrom || {};
  onPreferenceChange?.({ openedFrom: { ...others, [part]: { file: from.file, title: from.title || "" } } });
}

/** The assembly `file` was opened from, as `{ file, title }`, or null. */
export function openedFrom(preferences, file) {
  const kept = file ? preferences?.openedFrom?.[file] : null;
  return kept && typeof kept.file === "string" && kept.file !== file ? kept : null;
}
