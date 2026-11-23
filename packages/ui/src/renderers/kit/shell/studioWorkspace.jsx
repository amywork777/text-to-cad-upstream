// Studio (studio-base): edit mode's workspace (`renderers/xbf/edit/`) as the frame lays it out over the view, a CAD
// tool's window: the toolbar across the top, the design tree docked at the left, the open command's dialog beside it,
// and the timeline along the bottom. `RendererShell` calls `useStudioWorkspace` and places what it answers; its props
// (`ribbon`, `leftDock`, `bottomDock`, `dialogPlace`, `dialogOpen`) are handed here.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@cad/ui/utils";
import { WORKSPACE_DOCK_CLASS } from "../../../lib/workspaceSurface.js";
import { DOCK_PANEL_HEAD_CLASS } from "../tools/DockedToolPanel.jsx";
import { modelUpdateStatus, ViewUpdateStatus } from "../status/ViewUpdateStatus.jsx";
import { VIEWPORT_INSET_PX, VIEWPORT_STACK_BOTTOM } from "./viewportLayout.js";

const INSET = `${VIEWPORT_INSET_PX}px`;
// The workspace (edit mode's frame) stands over the view. Its toolbar's height, measured onto the stage
// (`--cad-workspace-top`), is what the rest at the top keeps below.
const WORKSPACE_TOP = "var(--cad-workspace-top, 0px)";
const UNDER_TOOLBAR = `calc(${WORKSPACE_TOP} + ${INSET})`;
// The design tree is a column docked at the view's left, 16rem wide, from under the toolbar to the view's foot.
// The canvas and what lines up with it start at the column's hairline, so the model is framed in the room it really
// has; a view too narrow for the column hides it, and they have the whole view back (`PAST_NAVIGATOR_CLASS`).
const NAVIGATOR_POSITION = Object.freeze({ top: WORKSPACE_TOP });
const PAST_NAVIGATOR_CLASS = "left-[16rem] @max-xl/cad-viewport:left-0";
// So too under the toolbar: every fit and every view is centred in the canvas, which under the toolbar put the model's
// top behind it.
const CANVAS_UNDER_TOOLBAR = Object.freeze({ top: WORKSPACE_TOP });
// An active feature's box shows only on its hovered or focused row and keeps its place when hidden,
// so names never shift; a suppressed feature keeps its box. EditTree's Row is held: it moves there after.
const NAVIGATOR_QUIET_CHECKS_CLASS = "[&_[data-cad-edit-tree-row]:not(:hover,:focus-within)_span:has(>input:checked)]:opacity-0";
// The dialog stops an inset above the cube's line, as the tool stack does, whichever bottom corner the cube is in.
const DIALOG_PLACE_POSITION = Object.freeze({ top: UNDER_TOOLBAR, bottom: VIEWPORT_STACK_BOTTOM });
// While a dialog is open there, the top column (a tool's own row and its panels) is the room past it, so none of
// it hides under the dialog: past the navigator (16rem) and the dialog (18rem, an inset past it), or past the
// dialog alone where the navigator gives way to a narrow view. With none open, the column spans the room past the
// navigator's column, so it centres on the canvas; with the navigator folded to its title it spans the view, and
// moves right only as far as clears the title (`usePastNavigator`). The frame places the column
// (`ViewFrame.jsx`'s `data-cad-tool-groups`, its left an inline style): these set its left over that, from the
// frame's root, for the view's width decides it (written out whole, so the stylesheet's scan finds them).
const BESIDE_DIALOG_CLASS = Object.freeze({
  navigator: "[&_[data-cad-tool-groups]]:left-[calc(31.75rem+16px)]! @max-xl/cad-viewport:[&_[data-cad-tool-groups]]:left-[calc(18rem+16px)]!",
  alone: "[&_[data-cad-tool-groups]]:left-[calc(18rem+16px)]!" });
const PAST_NAVIGATOR_COLUMN_CLASS = "[&_[data-cad-tool-groups]]:left-[calc(16rem+8px)]! @max-xl/cad-viewport:[&_[data-cad-tool-groups]]:left-2!";
// The strip's column and the Display card stand in the frame's top layer (`data-view-top-layer`), over the stage, so
// they start an inset under the toolbar by its height, written on the frame's root, never over the ribbon.
const UNDER_TOOLBAR_CLASS = "[&_[data-cad-tool-groups]]:top-[calc(var(--cad-workspace-top,0px)+8px)]! [&_[data-display-settings-dock]]:top-[calc(var(--cad-workspace-top,0px)+8px)]!";
// The timeline runs along the whole bottom edge: the cube stands in the view's top-right corner, under the toolbar
// (`--cad-viewport-corner-top`, set with `--cad-workspace-top` while the toolbar is up).
// The workspace fades in as the layout turns to it and out as Simple view takes its place: one opacity
// transition this long (`duration-150`).
const WORKSPACE_FADE_MS = 150;

/**
 * The workspace's chrome as the frame draws it. While `up` (the tools are), what the renderer hands over
 * (`chrome`); once the layout takes it away (Simple view: the tools still up, nothing handed over), what it
 * was, kept `leaving` for its fade, then gone. Put away with the rest of the tools (a load, Preview, a compact
 * view), it is gone at once, and comes back with them at once: `fadeIn` only as the layout turns to it.
 */
function useWorkspaceChrome(chrome, up) {
  const live = Boolean(chrome) && up;
  const layout = up && !chrome;
  const kept = useRef(null);
  const [phase, setPhase] = useState({ live, layout, fadeIn: false, leaving: null });
  if (phase.live !== live || phase.layout !== layout) {
    setPhase({
      live, layout,
      fadeIn: live && (phase.live ? phase.fadeIn : phase.layout || Boolean(phase.leaving)),
      leaving: live || !layout ? null : phase.live ? kept.current : phase.leaving
    });
  }
  if (live) kept.current = chrome;
  useEffect(() => {
    if (!phase.leaving) return undefined;
    const done = setTimeout(() => setPhase(current => (current.leaving ? { ...current, leaving: null } : current)), WORKSPACE_FADE_MS);
    return () => clearTimeout(done);
  }, [phase.leaving]);
  if (live) return { chrome, leaving: false, fadeIn: phase.fadeIn };
  return phase.leaving ? { chrome: phase.leaving, leaving: true, fadeIn: false } : null;
}

/**
 * The top column kept clear of the design tree folded to its title: centred across the view, it moves right
 * only as far as what it holds (its rows, and the tool stack's panels under them) runs under the title, and an
 * inset past it, and only as far as it has room: one measure, one shift, by its margins, which the frame's style
 * leaves alone. What clears the navigator already stays put. A view too narrow for the navigator hides it, and
 * nothing moves. The frame's measure of the column (`ViewFrame.jsx`'s, `remeasure`) runs again after a shift,
 * so the top-right column (Quick Edit) starts past where the rows now end.
 */
function usePastNavigator(rootRef, up, deps, remeasure) {
  useLayoutEffect(() => {
    const root = rootRef.current;
    const column = root?.querySelector("[data-cad-tool-groups]");
    if (!up || !column) return undefined;
    const shiftFor = () => {
      const edge = root.querySelector('[data-cad-dock="navigator"]')?.getBoundingClientRect();
      if (!edge?.width) return 0;
      const controls = column.querySelector("[data-cad-top-controls]");
      const rows = controls ? [...controls.children].map(row => row.getBoundingClientRect()) : [];
      const panels = [...column.querySelectorAll("[data-cad-tool-stack] [data-tool-panel]")].map(panel => panel.getBoundingClientRect());
      const held = [...rows, ...panels].filter(box => box.width > 0 && box.height > 0);
      if (!held.length) return 0;
      const overlap = edge.right + VIEWPORT_INSET_PX - Math.min(...held.map(box => box.left));
      return Math.max(0, Math.min(overlap, column.getBoundingClientRect().right - Math.max(...held.map(box => box.right))));
    };
    const place = () => {
      const before = column.style.marginLeft;
      column.style.removeProperty("margin-left");
      column.style.removeProperty("margin-right");
      const shift = shiftFor();
      if (shift > 0) {
        column.style.marginLeft = `${shift}px`;
        column.style.marginRight = `${-shift}px`;
      }
      if (column.style.marginLeft !== before) remeasure?.current?.();
    };
    place();
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    resized?.observe(column);
    const navigator = root.querySelector('[data-cad-dock="navigator"]');
    if (navigator) resized?.observe(navigator);
    const stack = column.querySelector("[data-cad-tool-stack]");
    if (stack) resized?.observe(stack);
    return () => { resized?.disconnect(); column.style.removeProperty("margin-left"); column.style.removeProperty("margin-right"); };
  }, [rootRef, up, ...deps]);
}

/**
 * The workspace, laid out as a CAD tool lays out its window: the toolbar across the top (`ribbon`, given the strip's
 * tools for its command search; the strip keeps them, less the view's own controls, under the toolbar with its
 * panels and Quick Edit); the design tree, a column docked at the left under it, holding `leftDock`, which folds to
 * its title and stands in for the view's panel. The column takes its width from the canvas, so the model is never
 * under it and the canvas resizes as the layout turns to the workspace and Simple view's ai layout, or as the column
 * folds: a plain resize, the camera left as it is. Beside it the place the open command's dialog mounts in
 * (`dialogPlace`, a ref callback); and the timeline along the bottom up to the cube (`bottomDock`, drawing its own
 * surface, as the toolbar does). It fades in as the layout turns to it and out as Simple view takes its place, in
 * one transition; it is put away at once with the rest of the tools (`toolsHidden`: loading, a compact view;
 * `previewing`), and the design tree in a view too narrow for it and the model, which then has the whole view. While
 * the toolbar is up the view catching up is its, not the strip's: `ribbon(tools, view)` is handed it
 * (`view.status`; null while it fades). `dialogOpen`: the dialog's place holds something, and the top column, a
 * tool's own row and its panels, keeps to the room past it.
 *
 * What it answers, for the frame to place: `toolbarUp` (the strip's update status gives way to the toolbar's),
 * `holdsPanel` (the design tree stands in for the view's panel), `top` (Preview's chrome starts below the toolbar),
 * `frameClass` and `measureRef` (the top column's place, for `ViewFrame`), `layer` (the workspace, over the view),
 * and `canvasClass`/`canvasStyle` (the canvas past the design tree's column and under the toolbar, so a fit centres
 * in the room the model really has).
 */
export function useStudioWorkspace({ ribbon, leftDock, bottomDock, dialogPlace, dialogOpen, frame, tools, toolsHidden, previewing, compact, failed, mobile, references }) {
  const editFrame = !toolsHidden && !previewing;
  // The workspace, over the canvas while the tools are up, and for its fade as Simple view takes its place.
  const workspace = useWorkspaceChrome(ribbon || leftDock || bottomDock || dialogPlace ? { ribbon, leftDock, bottomDock, dialogPlace } : null, editFrame);
  // The design tree folded to its title, as long as the frame is up.
  const [navigatorFolded, setNavigatorFolded] = useState(false);
  // The canvas starts past the design tree's column. Through a load the tools are away and the room is kept, so
  // the model is framed as it will stay; Simple view, Preview and a compact view have the whole view.
  const pastNavigator = Boolean(leftDock) && !navigatorFolded && !previewing && !compact && !failed;
  // The toolbar's height, which the strip, its panels and Quick Edit keep below, and a renderer's own
  // layers over the top of the view (`--cad-workspace-top` on the stage, `data-cad-canvas`).
  const workspaceToolbar = useRef(null);
  const toolbarUp = Boolean(workspace && !workspace.leaving && workspace.chrome.ribbon);
  // A dialog open beside the design tree: the top column keeps to the room past it. No dialog, and the
  // navigator up: the column keeps clear of it, by its place or, folded, by its margins (`usePastNavigator`).
  const besideDialog = Boolean(dialogOpen && workspace && !workspace.leaving && workspace.chrome.dialogPlace);
  const navigatorUp = Boolean(!besideDialog && workspace && !workspace.leaving && workspace.chrome.leftDock);
  useLayoutEffect(() => {
    const toolbar = workspaceToolbar.current;
    const stage = toolbar?.closest("[data-cad-canvas]");
    const root = frame.hostRef.current;
    if (!toolbarUp || !toolbar || !stage) return undefined;
    // The cube, in the top-right corner, stands under the toolbar as the rest at the top does; the frame's top layer
    // (the strip, the Display card) reads the height from the root.
    const measure = () => {
      const top = `${Math.round(toolbar.getBoundingClientRect().height)}px`;
      stage.style.setProperty("--cad-workspace-top", top);
      stage.style.setProperty("--cad-viewport-corner-top", top);
      root?.style.setProperty("--cad-workspace-top", top);
    };
    measure();
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resized?.observe(toolbar);
    return () => {
      resized?.disconnect();
      stage.style.removeProperty("--cad-workspace-top");
      stage.style.removeProperty("--cad-viewport-corner-top");
      root?.style.removeProperty("--cad-workspace-top");
    };
  }, [toolbarUp, frame.hostRef]);
  const measureColumn = useRef(null);
  usePastNavigator(frame.hostRef, navigatorUp && !mobile, [toolbarUp, navigatorFolded, pastNavigator, Boolean(references)], measureColumn);
  // What the toolbar is handed of the view while it is up: the view catching up, said beside the part's build status.
  const viewUpdateStatus = frame.loading.updating && !frame.viewUpdate.status.error ? modelUpdateStatus(frame.loading.progress) : frame.viewUpdate.status;
  const toolbarView = toolbarUp ? {
    status: failed ? null : <ViewUpdateStatus status={viewUpdateStatus} onRetry={frame.viewUpdate.retry} className="text-tiny" />
  } : null;
  // The top column's left while the workspace is up: past an open dialog, or past the design tree's column.
  const columnClass = besideDialog ? BESIDE_DIALOG_CLASS[workspace.chrome.leftDock ? "navigator" : "alone"] : pastNavigator && PAST_NAVIGATOR_COLUMN_CLASS;
  // The workspace, over the view: the toolbar across the top, the design tree's column at the left under it
  // (folded, its title alone over the canvas, what it holds kept), the open command's dialog beside it, and the
  // timeline along the bottom to the cube. The top-right stays Quick Edit's and the bottom corner the cube's.
  // Inert while it fades.
  const layer = workspace ? <div data-cad-workspace="" inert={workspace.leaving} aria-hidden={workspace.leaving || undefined}
    className={cn("pointer-events-none absolute inset-0 z-20 transition-opacity duration-150 motion-reduce:transition-none",
      workspace.fadeIn && "starting:opacity-0", workspace.leaving && "opacity-0")}>
    {workspace.chrome.ribbon ? <div ref={workspaceToolbar} className="pointer-events-auto absolute inset-x-0 top-0" data-cad-dock="toolbar">
      {workspace.chrome.ribbon(tools, toolbarView)}
    </div> : null}
    {workspace.chrome.leftDock ? <aside aria-label="FeatureManager design tree" data-cad-dock="navigator" style={NAVIGATOR_POSITION}
      className={cn(WORKSPACE_DOCK_CLASS, NAVIGATOR_QUIET_CHECKS_CLASS, "pointer-events-auto absolute left-0 flex w-[16rem] flex-col overflow-hidden @max-xl/cad-viewport:hidden",
        navigatorFolded ? "border-b" : "bottom-0")}>
      <button type="button" aria-expanded={!navigatorFolded} onClick={() => setNavigatorFolded(folded => !folded)}
        className={cn(DOCK_PANEL_HEAD_CLASS, "pr-2 hover:bg-cad-ws-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/45")}>
        <span className="min-w-0 flex-1 truncate">FeatureManager</span>
        <ChevronDown className={cn("size-3 shrink-0 text-muted-foreground", navigatorFolded && "-rotate-90")} aria-hidden="true" />
      </button>
      <div hidden={navigatorFolded} className="flex min-h-0 flex-1 flex-col border-t border-border">{workspace.chrome.leftDock}</div>
    </aside> : null}
    {workspace.chrome.dialogPlace ? <div ref={workspace.chrome.dialogPlace} data-cad-command-card-place="" style={DIALOG_PLACE_POSITION}
      className={cn("pointer-events-none absolute flex w-72 max-w-[calc(100%-1rem)] flex-col items-stretch",
        workspace.chrome.leftDock ? "left-[calc(16rem+0.5rem)] @max-xl/cad-viewport:left-2" : "left-2")} /> : null}
    {workspace.chrome.bottomDock ? <div className={cn("pointer-events-auto absolute inset-x-0 bottom-0", pastNavigator && PAST_NAVIGATOR_CLASS)} data-cad-dock="timeline" >
      {workspace.chrome.bottomDock}
    </div> : null}
  </div> : null;
  return {
    toolbarUp,
    // While the workspace's design tree is docked it stands in for the view's panel.
    holdsPanel: Boolean(leftDock && editFrame),
    // Under the workspace's toolbar, the strip, the top-right and Preview's bar start below it.
    top: toolbarUp ? WORKSPACE_TOP : undefined,
    frameClass: cn(columnClass, toolbarUp && UNDER_TOOLBAR_CLASS),
    measureRef: measureColumn,
    layer,
    canvasClass: pastNavigator && PAST_NAVIGATOR_CLASS,
    canvasStyle: toolbarUp ? CANVAS_UNDER_TOOLBAR : undefined
  };
}

/**
 * A test harness's workspace (`shell-harness/HarnessRenderer.jsx`): what its `data` hands the frame, as a renderer
 * hands its own (`data.iconSprite`, `data.ribbon`, `data.leftDock`, `data.bottomDock`, `data.dialogPlace`,
 * `data.dialogOpen` and `data.quickEditAsked`).
 */
export const harnessWorkspaceProps = data => ({
  iconSprite: data.iconSprite ?? null, ribbon: data.ribbon ?? null, leftDock: data.leftDock ?? null, bottomDock: data.bottomDock ?? null,
  dialogPlace: data.dialogPlace ?? null, dialogOpen: data.dialogOpen ?? false, quickEditAsked: data.quickEditAsked ?? null
});
