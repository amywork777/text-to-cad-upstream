import { useCallback } from "react";

/**
 * How a model with a part script opens: laid out for modeling it by hand (`manual`: edit mode,
 * the ribbon, design tree and PropertyManager of a CAD tool) or for asking the AI (`ai`: the
 * viewer as it is, where a selection on the model goes to the agent). One of the tab's settings
 * (`editLayout`, kept by the host's tab store), so it holds for every file the tab shows, as a
 * person keeps working one way.
 */
export const LAYOUTS = Object.freeze(["manual", "ai"]);

/** A pick on the model laid out for modeling it by hand (the workspace), and what the pointer rests on: orange, as the
 * design has the selection (its walkthrough's selected face). The ai layout keeps the viewer's own colour. */
export const WORKSPACE_SELECTION_COLOR = "#ff9a2e";

/**
 * What the switch between the layouts hangs on, from edit mode (`useEditMode`): `editable` once the
 * server says the file has a part script (the two layouts; a build that failed still has them), and
 * `busy` while a command, a sketch or a pick is open or a change is being saved, which holds the
 * switch until it is finished or cancelled. The navbar's switch and a host's own (Studio's Simple
 * view, `tab-store/editLayoutHost.ts`) read the same.
 * @param {{ status: string, command?: unknown, sketch?: unknown, picking?: boolean, saving?: boolean }} edit
 * @returns {{ editable: boolean, busy: boolean }}
 */
export function editLayoutState(edit) {
  return {
    editable: edit.status !== "none" && edit.status !== "probing",
    busy: Boolean(edit.command || edit.sketch || edit.picking || edit.saving),
  };
}

/**
 * Whether the CAD workspace is the layout chosen, for what has no agent in it (Pencil and Shapes, Quick Edit): `manual`
 * chosen for a model with a part script, or one the server has not yet answered for (`probing`), so none of the AI's
 * pieces shows while it is asked and then goes. A model it says has none (`none`) is the viewer as it is, with them all.
 * The workspace itself (`editing`) waits for the answer.
 * @param {string} layout
 * @param {{ status: string }} edit
 */
export function cadChosen(layout, edit) {
  return layout === "manual" && edit.status !== "none";
}

/**
 * What a double-click on the model asks of a host that lays the workspace out (Studio's AI | CAD switch,
 * `tab-store/editLayoutHost.ts`), with the Select tool in hand (`selecting`; Measure's, Explode's or Clip's double-click is
 * theirs): `manual` for a face of a part laid out for the AI, to step into the CAD workspace with the feature that made
 * the face selected (`pendingFaceStep`); `ai` for empty space in the workspace with nothing open in it (`open`: a command,
 * sketch, pick or sheet, or something isolated), to go back. Null where the double-click does what it always has: Normal
 * To on a face, a feature selected in the workspace. A STEP with no part script (`editable` false), an assembly's faces,
 * and a viewer no host lays out (Jake's own, which keeps its layout) ask nothing.
 * @param {{ layout: string, hosted: boolean, editable: boolean, assembly: boolean, target: "face" | "empty" | "other", selecting: boolean, open: boolean }} press
 * @returns {"manual" | "ai" | null}
 */
export function doubleClickLayout({ layout, hosted, editable, assembly, target, selecting, open }) {
  if (!hosted || !editable || !selecting) return null;
  if (layout === "ai") return target === "face" && !assembly ? "manual" : null;
  return target === "empty" && !open ? "ai" : null;
}

/**
 * What becomes of a face double-clicked laid out for the AI, the host asked for CAD (`doubleClickLayout`), as the part on
 * screen stands now: `select` its feature once the workspace has read the part and mapped its faces (`faces`), `wait`
 * while CAD's layout comes and the part is read, or `drop` it. It goes on another file, on a part that reads to nothing
 * (no part script after all, a build that failed), on the AI's layout again once CAD's came (`reached`, which the caller
 * keeps with the face), and after one try at a part read whose faces are not mapped, so it is never selected long after.
 * @param {{ file: string, reached: boolean }} face
 * @param {{ layout: string, file: string, status: string, editing: boolean, faces: boolean }} part
 * @returns {{ step: "select" | "wait" | "drop", reached: boolean }}
 */
export function pendingFaceStep(face, { layout, file, status, editing, faces }) {
  const reached = face.reached || layout === "manual";
  const gone = face.file !== file || (reached && layout !== "manual") || status === "none" || status === "error";
  if (gone) return { step: "drop", reached };
  if (!editing || status !== "ready") return { step: "wait", reached };
  return { step: faces ? "select" : "drop", reached };
}

/**
 * The layout and the way to change it, from the shell's services: `preferences` (the tab's
 * settings) and `onPreferenceChange` (its writer).
 * @param {{ preferences?: { editLayout?: string } | null, onPreferenceChange?: (patch: object) => void }} services
 * @returns {[string, (next: string) => void]}
 */
export function useEditLayout({ preferences, onPreferenceChange }) {
  const layout = LAYOUTS.includes(preferences?.editLayout) ? preferences.editLayout : "manual";
  const change = useCallback(next => {
    if (LAYOUTS.includes(next)) onPreferenceChange?.({ editLayout: next });
  }, [onPreferenceChange]);
  return [layout, change];
}
