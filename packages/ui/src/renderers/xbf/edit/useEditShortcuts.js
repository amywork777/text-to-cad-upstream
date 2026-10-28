import { useContext, useEffect, useRef } from "react";
import { ViewerElementContext } from "../../../host/context.js";
import { shortcutOfEvent } from "../../kit/tools/toolShortcuts.js";
import { isEditableTarget } from "../../kit/viewport/dom.js";

/**
 * Undo and Redo from the keyboard while edit mode is up, as a CAD tool takes them: Cmd+Z (Ctrl+Z),
 * and Shift+Cmd+Z or Ctrl+Y; F2, Rename on what the design tree has selected; and S, which asks the toolbar
 * for its command search (`edit.findCommand`, answered by `EditRibbon.jsx`). Only the viewer that owns the key acts on it, as the viewer's own
 * shortcuts decide (`kit/shell/useViewerShortcuts.js`): focus inside it, or the page background
 * after the last press was inside it. A text field keeps its own Undo, and its S.
 *
 * While edit mode is not up (Simple view, the AI layout) none of this is taken: S is whatever the strip gives it.
 *
 * @param {ReturnType<typeof import("./useEditMode.js").useEditMode>} edit
 * @param {boolean} active edit mode is up for this file.
 */
// SolidWorks' standard view keys, Ctrl (Cmd) with a digit, by the view each turns to (`STANDARD_VIEWS` in `editMode.js`).
const STANDARD_VIEW_KEYS = Object.freeze({ 1: "front", 2: "back", 3: "left", 4: "right", 5: "top", 6: "bottom", 7: "isometric" });

export function useEditShortcuts(edit, active) {
  const viewerElement = useContext(ViewerElementContext);
  const latest = useRef(edit);
  latest.current = edit;
  useEffect(() => {
    if (!active) return undefined;
    let pointerInside = false;
    const onPointerDown = event => { pointerInside = Boolean(viewerElement?.current?.contains(event.target)); };
    const onKeyDown = event => {
      const element = viewerElement?.current;
      if (!element || event.defaultPrevented || event.altKey) return;
      // F2 renames what is selected in the design tree, as in SolidWorks.
      if (event.key === "F2" && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
        const target = event.target;
        const inViewer = target instanceof Node && element.contains(target);
        const background = target === document.body || target === document.documentElement || target === document;
        if ((!inViewer && !(background && pointerInside)) || isEditableTarget(target) || !latest.current.selected) return;
        event.preventDefault();
        latest.current.startRename?.(latest.current.selected);
        return;
      }
      // S, the command search: a single key as a tool's letter is (`kit/tools/toolShortcuts.js`), so with Cmd, Ctrl, Alt or Shift held it
      // is not S, and held down it asks once. The viewer's own letters are off while the toolbar stands, so the key is free.
      if (shortcutOfEvent(event) === "S") {
        const target = event.target;
        const inViewer = target instanceof Node && element.contains(target);
        const background = target === document.body || target === document.documentElement || target === document;
        if ((!inViewer && !(background && pointerInside)) || isEditableTarget(target) || event.repeat) return;
        event.preventDefault();
        latest.current.findCommand?.();
        return;
      }
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      // Cmd+1 to Cmd+7 (Ctrl+1 to Ctrl+7), SolidWorks' standard views: Front, Back, Left, Right, Top, Bottom, Isometric.
      if (STANDARD_VIEW_KEYS[key] && !event.shiftKey) {
        const target = event.target;
        if (!(target instanceof Node && element.contains(target)) && !(pointerInside && (target === document.body || target === document.documentElement))) return;
        if (isEditableTarget(target)) return;
        event.preventDefault();
        latest.current.lookStandard?.(STANDARD_VIEW_KEYS[key]);
        return;
      }
      // Cmd+8 (Ctrl+8), Normal To, as SolidWorks takes it: the sketch's plane, or the face or plane selected.
      if (key === "8" && !event.shiftKey) {
        const target = event.target;
        if (!(target instanceof Node && element.contains(target)) && !(pointerInside && (target === document.body || target === document.documentElement))) return;
        if (isEditableTarget(target)) return;
        event.preventDefault();
        latest.current.lookNormalTo?.();
        return;
      }
      const redo = (key === "z" && event.shiftKey) || (key === "y" && event.ctrlKey && !event.metaKey && !event.shiftKey);
      if (key !== "z" && !redo) return;
      const target = event.target;
      const inViewer = target instanceof Node && element.contains(target);
      const background = target === document.body || target === document.documentElement || target === document;
      if ((!inViewer && !(background && pointerInside)) || isEditableTarget(target)) return;
      const current = latest.current;
      if (redo ? !current.canRedo : !current.canUndo) return;
      event.preventDefault();
      event.stopPropagation();
      void (redo ? current.redo() : current.undo());
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [active, viewerElement]);
}
