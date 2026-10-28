import { useEffect, useRef, useSyncExternalStore } from "react";
import { focusHost } from "../../../tab-store/focusHost.js";
import { treeFeatures } from "./editMode.js";
import { focusAnswer } from "./focus.js";

/**
 * Answers the host's ask to show a line of the part's script (Studio's References, `tab-store/focusHost.ts`), for the part
 * on screen (`useXbfCadMode.jsx` hands it edit mode's `status`, the layout it is shown in, the design tree's `tree` and
 * edit mode's `select`). Once the part is read, the feature whose statement holds the line is selected, as a press in the
 * design tree selects it, and the timeline follows; the ask is said taken however that went (`focusAnswer`), nothing
 * there or nothing read included, so the host never keeps it, and whether a feature was found, so where none was (a
 * constant, an import, a helper's line, a build that failed) the host opens the script at the line instead and the press
 * is never lost. Each ask once. A part drawn out of sight (`onScreen` false: the library's picture) is not the part on
 * screen, and answers nothing.
 *
 * @param {{ onScreen: boolean, layout: string, status: string, tree: object, select: (id: string) => void }} part
 */
export function useHostFocus({ onScreen, layout, status, tree, select }) {
  const focus = useSyncExternalStore(focusHost.subscribe, focusHost.get, focusHost.get);
  const taken = useRef(null);
  useEffect(() => {
    if (!focus || !onScreen || taken.current === focus.nonce) return;
    const answer = focusAnswer(focus, { layout, status, features: treeFeatures(tree) });
    if (!answer) return;
    taken.current = focus.nonce;
    if (answer.select) select(answer.select);
    focusHost.take(focus.nonce, Boolean(answer.select));
  }, [focus, onScreen, layout, status, tree, select]);
}
