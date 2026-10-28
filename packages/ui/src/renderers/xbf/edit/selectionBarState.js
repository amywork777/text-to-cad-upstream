/**
 * The state the selection bar and Quick Edit keep in the workspace (`useXbfCadMode.jsx` wires it): whether the person has asked
 * for Quick Edit (`useAsked`), and whether they have chosen the feature that is selected (`useChosenFeature`, which
 * `chosenThrough` has the design tree and the timeline set).
 */
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A state that is set (`set`), put away (`clear`), and put away by what has happened since the render before
 * (`gone(before)`, given what that render saw: it is told from the render before, kept after each commit, so the
 * render that sees it is already without it, and the surface, which is large, renders once more only to forget it).
 */
function useLatch(seen, gone) {
  const [on, setOn] = useState(false);
  const before = useRef(seen);
  const away = on && gone(before.current);
  useEffect(() => {
    before.current = seen;
    if (away) setOn(false);
  });
  const set = useCallback(() => setOn(true), []);
  const clear = useCallback(() => setOn(false), []);
  return [on && !away, set, clear];
}

/**
 * Whether the person has asked for Quick Edit in the workspace (`asked`): the answer to Ask, in the selection bar or the
 * toolbar, which Quick Edit waits for (`quickEditShown`). It is the workspace's, and a file's: the AI layout
 * has none, and another file opening starts without. It goes with the picks it was asked about, when they are let go
 * of (a click on the background, a box's Clear), and when a command or a sketch opens (`held`: one is open); asked
 * with nothing picked, which is Quick Edit on the part as a whole, it stays until something puts it away. Escape, a
 * send and the box's X put it away through `clear`.
 *
 * @param {{ editing: boolean, picked: boolean, held: boolean, file: string }} state
 *   `picked`: something is picked, a face, an edge, a part or a feature.
 * @returns {{ asked: boolean, ask: () => void, clear: () => void }}
 */
export function useAsked({ editing, picked, held, file }) {
  const [asked, ask, clear] = useLatch({ picked, held, file },
    before => !editing || (before.picked && !picked) || (held && !before.held) || before.file !== file);
  return { asked, ask, clear };
}

/**
 * Whether the person has chosen the feature selected in the design tree (`chosen`): pressed its row there or on the
 * timeline, or picked its sketch on the model. Only a feature they chose is a pick for the selection bar; the one a command's
 * OK selects, the one left selected from before, is not, or the bar would stand over the part all the while it is
 * being worked on. It lasts until their next click on the model's background (`drop`; an orbit drag to look at it, or a
 * press that picks a face, keeps it), or a command or a sketch opens, or the workspace or the file goes.
 *
 * @param {{ editing: boolean, held: boolean, file: string }} state
 * @returns {{ chosen: boolean, choose: () => void, drop: () => void }}
 */
export function useChosenFeature({ editing, held, file }) {
  const [chosen, choose, drop] = useLatch({ held, file }, before => !editing || (held && !before.held) || before.file !== file);
  return { chosen, choose, drop };
}

/**
 * The edit state as the design tree and the timeline are handed it: selecting a row there is the person choosing its
 * feature (`choose`), and clearing the selection (no id) chooses nothing. All else is the edit state's own.
 */
export const chosenThrough = (edit, choose) => ({ ...edit, select: id => { edit.select(id); if (id) choose(); } });
