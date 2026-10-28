/**
 * Add to context in the workspace (`useXbfCadMode.jsx` wires it): the selection bar's button and the toolbar's put what Ask would
 * carry into the host's chat box, with no note and nothing sent, so faces, edges, features and ink can be collected and one message
 * written (`quickEditPrompt.js`'s `addToContext`, which is what Quick Edit's Queue does without the note).
 */
import { useCallback, useMemo, useRef } from "react";
import { usePromptDestination, useViewerHost } from "../../../host/context.js";
import {
  addToContext, canAddToContext, deliveryFailure, promptAttachments, quickEditSelection
} from "../../kit/tools/quick-edit/quickEditPrompt.js";

/**
 * Add to context for what is picked (`references`, in the prompt grammar: what Ask carries, `pickedReferences`) in the file on
 * screen (`resource`), what is drawn (`annotated`: there is ink), and the changes the view was asked for (`requests`: a
 * renderer's chips, PMI's among them, each with its `request`). `add()` hands them to the host within the press, with the
 * views, files and marks on a face the Quick Edit `prompt` would attach and none that Queue would not, and takes one press at a
 * time. Once the host has them `onAdded()` is called, for the surface to let go of the picks and the ink so the next one starts
 * fresh; if it does not take them `onFailed(message)` is, with them kept, in the words Quick Edit shows under its note.
 *
 * `offered`: the host has a chat box to fill (`canAddToContext`), and Add to context is shown nowhere else. `picked`: there is
 * something to add beyond the file, which always goes: a pick, a change asked for, or ink, which goes as the snapshot's annotation
 * and the marks on a face; `add()` with none of them does nothing. `held`: a command, a sketch
 * or a panel is open, and the selection is its own (an open Edge Blend's edges are the model's picks): `add()` waits for it to
 * be finished or cancelled, and a delivery that is answered after one has opened lets go of nothing, since what it would let
 * go of is the command's now (a refusal is still said).
 *
 * @param {{ resource: object, references: readonly object[], prompt: object | null, held?: boolean, annotated?: boolean,
 *   requests?: readonly { request: string }[] | null, onAdded: () => void, onFailed: (message: string) => void }} input
 * @returns {{ offered: boolean, picked: boolean, add: () => void }}
 */
export function useAddToContext({ resource, references, prompt, held = false, annotated = false, requests = null, onAdded, onFailed }) {
  const host = useViewerHost();
  const destination = usePromptDestination();
  const picks = useMemo(() => quickEditSelection(references), [references]);
  const asked = useMemo(() => (requests || []).map(item => item?.request).filter(Boolean), [requests]);
  // What a press reads is what is live then, and what settles it is what is live when the host answers.
  const live = useRef(null);
  live.current = { host, resource, picks, asked, prompt, held, annotated, onAdded, onFailed };
  const pending = useRef(false);
  const add = useCallback(() => {
    const { host: now, resource: file, picks: carried, asked: changes, prompt: source, held: waiting, annotated: inked } = live.current;
    if (pending.current || waiting || (!carried.length && !changes.length && !inked)) return;
    pending.current = true;
    let outcome;
    try { outcome = addToContext(now, { resource: file, references: carried, requests: changes, ...promptAttachments(source) }); }
    catch (caught) { outcome = Promise.reject(caught); }
    outcome.then(
      result => deliveryFailure(result),
      caught => (caught instanceof Error ? caught.message : String(caught)) || "The prompt did not go.",
    ).then(message => {
      pending.current = false;
      if (message) live.current.onFailed(message);
      else if (!live.current.held) live.current.onAdded();
    });
  }, []);
  return { offered: canAddToContext(destination), picked: picks.length > 0 || asked.length > 0 || annotated, add };
}
