/**
 * Where the host's ask to show a line of a part's script lands (Studio's References open a part at the line an answer
 * cites, `tab-store/focusHost.ts`): the feature of the design tree whose statement holds the line, and when the part on
 * screen can answer the ask.
 */

const slashed = path => String(path ?? "").replace(/\\/g, "/").replace(/^(?:\.\/)+/, "");

/** Whether two paths name one script: the same, or one the other's tail at a folder's edge, however each is written. */
function sameScript(a, b) {
  const left = slashed(a), right = slashed(b);
  return Boolean(left && right) && (left === right || left.endsWith(`/${right}`) || right.endsWith(`/${left}`));
}

/** The lines a statement holds, `[first, last]`: to its `end` where the engine read it, else its first line alone. */
const spanOf = ({ line, end }) => [line, Number.isSafeInteger(end) && end >= line ? end : line];

/**
 * The feature whose statement holds a line of a script (`file`, as the host names it), among the design tree's
 * features (`featureTree`'s, a part's or every part's of an assembly); null for none. A feature stands for the statements
 * its `lines` lists, its own and the rows folded into it (the profile it extrudes, a cut joined to it), each from its
 * first line to its last (`end`): a line anywhere in one finds the feature, and a blank line between statements, a
 * comment or an import finds none. Of a statement whose end the engine did not say (a folded row's, an older engine's),
 * only its first line is known. Where several statements hold the line, the innermost is taken: the smallest span.
 */
export function featureAtLine(features, file, line) {
  if (!Number.isSafeInteger(line)) return null;
  let found = null, span = Infinity;
  for (const feature of features || []) {
    for (const each of feature.lines || []) {
      if (!sameScript(each.file, file)) continue;
      const [first, last] = spanOf(each);
      if (line < first || line > last || last - first >= span) continue;
      found = feature;
      span = last - first;
    }
  }
  return found;
}

// The part's read is still on its way: whether it has a script, its first read, or the AI layout's quiet one.
const READING = new Set(["probing", "reading", "idle"]);

/**
 * How the part on screen answers its host's ask (`focus`, `{ path, line }`), as edit mode stands (`useEditMode`'s
 * `status`, the layout it is shown in, the design tree's `features`): null while the part is still being read, as the
 * answer waits for it; else `{ select }`, the id of the feature whose statement holds the line (`featureAtLine`), or null
 * where none is to be selected. Laid out for the AI the view shows no features; a file with no part script (`none`) and
 * a part whose build failed (`error`) have none read. Every answer lets the ask go, so the host never keeps one.
 */
export function focusAnswer(focus, { layout, status, features }) {
  if (layout !== "manual") return { select: null };
  if (READING.has(status)) return null;
  if (status !== "ready") return { select: null };
  return { select: featureAtLine(features, focus.path, focus.line)?.id ?? null };
}
