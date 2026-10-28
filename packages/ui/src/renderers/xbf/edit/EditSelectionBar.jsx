import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@text-to-cad/ui/utils";
import { WORKSPACE_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { VIEWER_DOUBLE_CLICK_ACTIVATION_DELAY_MS } from "../clickActivation.js";
import { AddContextIcon, AnnotateIcon, AskIcon } from "./cadIcons.jsx";
import { FeatureIcon } from "./featureIcons.jsx";
import { useSceneRendered } from "./sceneRendered.js";
import { SELECTION_BAR_EDGE_PX, placeBar, screenBox } from "./selectionBar.js";

// A button of the bar: its icon and its name in a row, the workspace's pale blue under the pointer and its deeper one
// while it is pressed, and nothing that grows, glows or moves.
const BUTTON_CLASS = "flex h-6 shrink-0 items-center gap-1.5 rounded-sm px-2 text-tiny font-medium leading-none text-foreground transition-colors hover:bg-cad-ws-hover active:bg-cad-ws-selected focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0";
const AGENT_BUTTONS = Object.freeze({
  ask: { label: "Ask", Icon: AskIcon },
  "add-context": { label: "Add to context", Icon: AddContextIcon },
  annotate: { label: "Annotate", Icon: AnnotateIcon },
});
// The cards the workspace floats over the view, which the bar keeps clear of: its toolbar (the top of the room the bar
// has), the design tree, the open command's card, the timeline, and Quick Edit's box.
const CARDS = '[data-cad-dock="toolbar"], [data-cad-dock="navigator"], [data-cad-command-card], [data-cad-edit-timeline], [data-quick-edit-box]';

// What the bar is placed by: the picks' box on the screen, the room it has (the view inset from its edges, below the
// toolbar) and the cards over that room, all in the view's pixels. Null where the picks are not in front of the camera.
function frameOf(runtime, points, width, height, host) {
  const box = screenBox(runtime, points, width, height);
  if (!box) return null;
  const view = host?.closest?.("[data-cad-scene-backdrop]");
  const origin = host?.getBoundingClientRect?.();
  const obstacles = [];
  let top = SELECTION_BAR_EDGE_PX;
  for (const card of view && origin ? view.querySelectorAll(CARDS) : []) {
    const rect = card.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) continue;
    const at = { left: rect.left - origin.left, top: rect.top - origin.top, right: rect.right - origin.left, bottom: rect.bottom - origin.top };
    if (card.matches('[data-cad-dock="toolbar"]')) top = Math.max(top, at.bottom + SELECTION_BAR_EDGE_PX);
    else obstacles.push(at);
  }
  return { box, bounds: { left: SELECTION_BAR_EDGE_PX, top, right: width - SELECTION_BAR_EDGE_PX, bottom: height - SELECTION_BAR_EDGE_PX }, obstacles };
}

/**
 * Where the picks are on the screen, each frame the camera has moved since the last (the bar follows them as the
 * model turns), and not otherwise: nothing is laid out for a view that holds still.
 */
function useFrame(viewport, anchorKey, anchorRef, active) {
  const { runtimeRef, hostRef } = viewport;
  const [frame, setFrame] = useState(null);
  const lastRef = useRef(null);
  // Laid out after each render of the view, and once for new picks (`useSceneRendered`): nothing runs at rest.
  const request = useSceneRendered(viewport, () => {
    const runtime = runtimeRef.current, canvas = runtime?.renderer?.domElement;
    if (!runtime?.camera || !runtime.modelGroup || !canvas) return;
    runtime.camera.updateMatrixWorld();
    runtime.modelGroup.updateMatrixWorld();
    const width = canvas.clientWidth, height = canvas.clientHeight;
    const signature = [width, height, ...runtime.camera.matrixWorld.elements, ...runtime.camera.projectionMatrix.elements,
      ...runtime.modelGroup.matrixWorld.elements];
    const last = lastRef.current;
    if (last && last.every((value, index) => value === signature[index])) return;
    lastRef.current = signature;
    setFrame(frameOf(runtime, anchorRef.current?.() || [], width, height, hostRef?.current));
  }, active);
  useEffect(() => {
    lastRef.current = null;
    if (!active) { setFrame(null); return; }
    request();
  }, [active, anchorKey, request]);
  return frame;
}

/**
 * The bar beside a pick in the workspace: Ask, Add to context, Annotate and Edit, each only where the renderer has a handler
 * to give it (`onAsk`, `onAddContext`, `onAnnotate`, `onEdit`) and the pick allows it (`actions`, `selectionBarActions`). It
 * stands above what is picked, centred on it, and below it, or beside it, where there is no room above, kept inside the
 * view and clear of the cards over it (`placeBar`), and follows it as the camera moves. `anchor()` gives the points it is
 * about, in the part's own units; `anchorKey` changes with the picks. It shows once the double-click window since it
 * came has passed, so a second click of a double-click on the model is the model's, and it takes no press or double-click
 * of its own that the model could hear. Edit draws the picked feature's own icon (`editKind`) and names what it opens
 * (`editHint`: Edit Feature, Edit Sketch).
 *
 * @param {{ viewport: { runtimeRef: object, hostRef?: object, viewerReadyTick?: number },
 *   actions: { id: string, enabled: boolean, reason?: string }[], anchor: () => number[][], anchorKey: string,
 *   editKind?: string, editHint?: string, onAsk?: () => void, onAddContext?: () => void, onAnnotate?: () => void,
 *   onEdit?: () => void }} props
 */
export default function EditSelectionBar({ viewport, actions, anchor, anchorKey, editKind = "", editHint = "", onAsk, onAddContext, onAnnotate, onEdit }) {
  const handlers = { ask: onAsk, "add-context": onAddContext, annotate: onAnnotate, edit: onEdit };
  const drawn = actions.filter(action => handlers[action.id]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setReady(true), VIEWER_DOUBLE_CLICK_ACTIVATION_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;
  const frame = useFrame(viewport, anchorKey, anchorRef, drawn.length > 0);
  const bar = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = bar.current;
    if (element && (element.offsetWidth !== size.width || element.offsetHeight !== size.height)) setSize({ width: element.offsetWidth, height: element.offsetHeight });
  });
  const place = ready && frame && drawn.length ? placeBar({ ...frame, size }) : null;
  if (!place) return null;
  const press = handler => event => {
    // The keyboard goes back to the viewer, so its keys (Escape) are heard once the bar has gone.
    event.currentTarget.closest("[data-cad-surface]")?.focus({ preventScroll: true });
    handler();
  };
  return <div ref={bar} role="toolbar" aria-label="Selection" data-cad-selection-bar=""
    className={cn(WORKSPACE_SURFACE_CLASS, "pointer-events-auto absolute z-20 flex items-center gap-0.5 p-0.5", size.width ? null : "invisible")}
    style={{ left: Math.round(place.left), top: Math.round(place.top) }}
    onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
    {drawn.map(action => {
      const agent = AGENT_BUTTONS[action.id];
      const label = agent ? agent.label : "Edit";
      const describes = action.enabled ? (action.id === "edit" ? editHint : "") : action.reason;
      return <button key={action.id} type="button" className={BUTTON_CLASS} disabled={!action.enabled} aria-description={describes || undefined}
        onClick={press(handlers[action.id])}>
        {agent ? <agent.Icon /> : <FeatureIcon kind={editKind} />}
        {label}
      </button>;
    })}
  </div>;
}
