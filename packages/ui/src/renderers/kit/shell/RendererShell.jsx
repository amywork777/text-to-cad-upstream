import { VIEWPORT_CORNER_INSET_PX, VIEWPORT_CUBE_SIZE, VIEWPORT_INSET_PX, VIEWPORT_STACK_BOTTOM } from "./viewportLayout.js";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, LoaderCircle, Play, SlidersHorizontal, X } from "lucide-react";
import { WORKSPACE_DOCK_CLASS } from "../../../lib/floatingSurface.js";
import { Button } from "@cad/ui/primitives/button";
import { ToolbarButton } from "@cad/ui/primitives/toolbar-button";
import { TooltipHint } from "@cad/ui/primitives/tooltip";
import { NAVBAR_CONTROL_CLASS } from "../../../lib/navbarRow.js";
import { cn } from "@cad/ui/utils";
import { useI18n } from "@cad/ui/i18n";
import { usePreviewIdle } from "../tools/PreviewChrome.jsx";
import { useViewerMobile } from "../../../file-viewer/responsive.js";
import { alertDismissible, useAlertDismissal } from "../status/ViewerAlertCard.jsx";
import { modelUpdateStatus, ViewUpdateStatus } from "../status/ViewUpdateStatus.jsx";
import DisplayPopover, { DisplayMenuItems } from "./DisplayPopover.jsx";
import ProjectionToggle, { otherProjection } from "./ProjectionToggle.jsx";
import { viewportZoom, zoomViewControl } from "./ZoomControl.jsx";
import { OrthographicProjectionIcon, PerspectiveProjectionIcon } from "../camera/ProjectionModeIcons.js";
import PreviewSettings from "./PreviewSettings.jsx";
import { withGroups } from "../../../annotation/geometry.js";
import { BoxSelectGesture } from "../tools/select/useBoxSelectGesture.js";
import { takeInkInBox } from "../tools/select/boxTake.js";
import { useStripButtonClass } from "../tools/FloatingToolBar.js";
import { AnnotationToolbar } from "../../../annotation/toolbar.jsx";
import ToolStack from "../tools/ToolStack.jsx";
import { DOCK_PANEL_HEAD_CLASS } from "../tools/ToolPanel.jsx";
import PreviewPlaybar from "../tools/playbar/PreviewPlaybar.jsx";
import { animationControlsHaveContent } from "../tools/playbar/AnimationTimeControl.js";
import QuickEdit, { quickEditDocked } from "../tools/quick-edit/QuickEdit.jsx";
import ShellViewport from "./ShellViewport.jsx";
import PreviewView from "./PreviewView.jsx";
import { previewCoverStep } from "./previewCover.js";
import ViewportContextMenu from "./ViewportContextMenu.jsx";
import DoubleClickFit from "./DoubleClickFit.jsx";
import AnnotationSelectionBar from "../tools/annotate/AnnotationSelectionBar.jsx";
import ViewFrame from "./ViewFrame.jsx";
import { useControlUsage } from "../../../usage/controls.js";

// The sidebar sections Preview offers: posing the model and playing its routines.
// Preview's cover: at least this long, then until publication and the picture are ready.
// The picture is checked this often until it has converged.
// The cover waits at least MIN; at MAX it stops waiting for more components, and lets the picture on
// screen finish converging for at most FINISH more.
const PREVIEW_COVER_MIN_MS = 700, PREVIEW_COVER_QUIET_MS = 400, PREVIEW_COVER_MAX_MS = 5000, PREVIEW_COVER_FINISH_MS = 1000,
  PREVIEW_COVER_CONVERGE_MS = 50;
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
// The timeline runs along the bottom edge up to the cube, its corner's room (the cube's box and an inset) kept
// on the cube's side. A corner a host leaves to the default reads `auto` (`ViewPlaneControl`), which makes the
// margin on that side invalid, and an invalid margin is none: the timeline reaches the edge where the cube is not.
const cubeRoom = (side, fallback) => `calc(var(--cad-viewport-corner-${side}, ${fallback}) + ${VIEWPORT_CUBE_SIZE} + ${INSET})`;
const TIMELINE_POSITION = Object.freeze({ marginLeft: cubeRoom("left", "auto"), marginRight: cubeRoom("right", `${VIEWPORT_CORNER_INSET_PX}px`) });
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

/** One of Preview's bar's controls: the navbar's icon button, named on hover, below it. */
function BarControl({ label, active = undefined, disabled = false, onClick, children, ...props }) {
  return <TooltipHint content={label} side="bottom" disabled={active === true}>
    <Button type="button" variant="ghost" size="icon-xs" aria-label={label} aria-pressed={active} disabled={disabled} onClick={onClick}
      className={NAVBAR_CONTROL_CLASS} {...props}>{children}</Button>
  </TooltipHint>;
}
// The projection on screen, as an icon (a More menu's row on a phone's strip).
function ProjectionIcon({ value }) {
  const Icon = value === "perspective" ? PerspectiveProjectionIcon : OrthographicProjectionIcon;
  return <Icon />;
}

function ViewControl({ label, disabled = false, tooltipSide = "top", onClick, children }) {
  return <ToolbarButton label={label} tooltipSide={tooltipSide} disabled={disabled} onClick={onClick} className={useStripButtonClass()}>
    {children}
  </ToolbarButton>;
}

// Two presses on the same ink this close together are one double-click.
const DOUBLE_PRESS_MS = 600;

/**
 * A 3D view's frame: every view's one frame (`ViewFrame.jsx`: the root, the docked panel, the strip
 * at the centre of the whole view, the top-right, the corner, the cards) with what a 3D view puts in
 * it — its viewport (`ShellViewport`) as the canvas, Preview's view over it and Preview's cover, the
 * strip's view controls (Projection, Display, then Preview), the tool stack, the playbar at the
 * bottom centre and Preview's own chrome; its corner is the viewport's cube alone. The same
 * structure, classes and data attributes for every renderer: hosts, stylesheets and tests key on
 * them. The toolbar is for using tools, the sidebar for reading the file: a tool's own controls are
 * panels in the tool stack, shown by the tool they belong to; what there is to read of the file (a
 * tree, joints, metadata) is the sidebar's sections, whatever the tool.
 *
 * @param {{ shell: ReturnType<typeof import("./useRendererShell.js").useRendererShell>,
 *   tools: import("../tools/FloatingToolBar.js").ViewportTool[],
 *   toolPanels?: import("react").ReactNode, sidebar?: import("react").ReactNode,
 *   references?: readonly import("@cad/core/prompt").PromptReference[],
 *   referenceChips?: readonly import("../tools/quick-edit/ReferenceChips.jsx").ReferenceChip[] | null,
 *   requests?: ReadonlyArray<import("../tools/quick-edit/ReferenceChips.jsx").ReferenceChip & { request: string }> | null,
 *   onClearRequests?: (() => void) | null,
 *   nameReference?: ((reference: import("@cad/core/prompt").PromptReference) => string | import("../inspector/pickGlyph.jsx").CompactName) | null,
 *   copySelection?: (() => unknown) | null,
 *   contextMenuItems?: ((press: { clientX: number, clientY: number, shiftKey: boolean }) => object[] | null) | null,
 *   onContextMenuOpenChange?: ((open: boolean) => void) | null,
 *   frameProvider?: ((frame: import("react").ReactNode) => import("react").ReactNode) | null,
 *   onCanvasPointerDown?: ((event: import("react").PointerEvent) => void) | null,
 *   viewportOverlay?: import("react").ReactNode | ((viewport: { runtimeRef: object, hostRef: object,
 *     mountRef: object, viewerReadyTick: number, commitScene: () => boolean }) => import("react").ReactNode) }} props
 *   `tools`: left to right, from `shell.tools`; an EMPTY list draws no strip at all, which is what
 *   a file whose viewport only orbits, pans and zooms hands over. A tool the
 *   file cannot offer is left out, never handed over disabled.
 *   `toolPanels`: the tool stack's panels, top to bottom — each a `ToolPanel`
 *   (`kit/tools/ToolPanel.jsx`), shown or `hidden` by the renderer as its tools say: the
 *   effects a person keeps. The stack is one column under the strip, gone in preview. The
 *   shell's own tool's panel leads it: Annotate's.
 *   `subToolbar`: the renderer's tool in hand's own row under the strip (`kit/tools/SubToolbar.jsx`:
 *   the active tool); the shell's own tool's row (Annotate's) takes its place while it is up.
 *   `sidebar`: the file's sections, in order — each a `ToolPanel`, drawn as a tab of the view's panel
 *   (`FlatPanel.jsx`): a tree, joints, metadata. None (null): no panel.
 *   `inspect`: what is picked and how the renderer describes it (`inspector/inspect.js`): the frame's
 *   Selected pane under the panel's tabs, the hover tip under Select, and the rows of both.
 *   Gone in preview, kept mounted, so a tree keeps its expansion and scroll.
 *   `referenceChips`: the renderer's description of that selection, as Quick Edit shows it (its
 *   chips, `kit/tools/quick-edit/ReferenceChips.jsx`): a chip each for one or several picks of a kind
 *   on one part, its card, its hover and its removal. Without them Quick Edit counts the references.
 *   `nameReference`: what the renderer calls a reference into its file, for a reference pasted
 *   into Quick Edit's note ("cam"); "" for one it cannot name.
 *   `references`: what is selected, in the prompt grammar — the references a Quick Edit attaches
 *   (`kit/tools/quick-edit/QuickEdit.jsx`), counted in its header; the file itself always goes. A
 *   renderer that hands none has no Quick Edit: only a view whose picks and annotations a note can
 *   carry offers one. The box sizes itself, for as long as it is open: a drag of its corner renders nothing
 *   here. `onClearReferences`: the renderer's clear of that selection, as a press on the
 *   background makes it; Quick Edit's X calls it, and clears Annotate's ink too.
 *   `requests`: the changes the renderer was asked for in the view that its file's code should make
 *   (a value or a placement the code holds, say), each a chip in Quick Edit
 *   with what its prompt carries (`request`); `onClearRequests`: drops them all, as Quick Edit's
 *   X does and a note that has gone does.
 *   `copySelection`: the viewer's copy key (⌘C / Ctrl+C) while the renderer's own tool is up and
 *   something is selected (Annotate's copies the view with its ink); null when there is nothing to copy.
 *   `zoomToSelection`: `{ run(), available }`, the zoom menu's Zoom to selection (`ZoomControl.jsx`): what
 *   is picked, framed; off without it.
 *   `doubleClickFits`: a double-click on empty space under Select fits the model (`DoubleClickFit`);
 *   false for a renderer whose double-click is its own (an engine document's isolates and looks at).
 *   `contextMenuItems`: what THIS renderer offers on a secondary tap over the canvas; the
 *   gesture, the anchor and the dismissal are the shell's (`ViewportContextMenu.jsx`), and a
 *   renderer that passes none has no viewport menu at all. `onContextMenuOpenChange(open)`
 *   says while that menu is up, for a renderer that marks what the menu is about.
 *   `viewportOverlay`: the renderer's own layer over the canvas; as a function it is given
 *   the viewport, which is five things: its live runtime, the element its pointer events
 *   arrive on, the element the canvas is mounted in, a tick that changes when the runtime is
 *   replaced, and `commitScene()` for a scene that changed IN PLACE. A handle overlay or a
 *   pointer pick (`kit/tools/select/usePointerPick.js`) reads the first, second and fourth;
 *   a renderer that draws its own canvas over the model or publishes a scene progressively
 *   needs the other two.
 *   `frameProvider`: the renderer wraps the WHOLE frame — its own context, above the tool
 *   stack as well as the viewport, because both read it. It is given the frame and returns
 *   it wrapped; a renderer that passes none is mounted exactly as it is.
 *   `onCanvasPointerDown`: a press that landed on the canvas, before anything in the viewport sees
 *   it. The frame focuses itself on such a press whatever the renderer does; this is for a renderer
 *   that also has something to put down when the person reaches for the model.
 *   `onSelectPress`: under Select, a press on the canvas, before the annotation's ink and any part:
 *   the renderer's own pickable overlays (a measurement). True when it picked something, and the
 *   press goes no further; false to let it on.
 *   `onSelectHover`: under Select, the pointer resting on the canvas (null: it left, or Select went
 *   down): the renderer lights its own overlay under it, and returns true when there is one.
 *   `selectsAnnotations`: whether Select picks the annotation's ink, as the renderer's Select filter says; the
 *   ink is drawn either way.
 *   `boxSelect`: `{ enabled, onBox(box), mayStart?(event) }`, a renderer's Box select
 *   (`kit/tools/select/useBoxSelectGesture.js`). While Select is up and `enabled`, a drag that starts on
 *   empty space draws a box -- not on the annotation's ink (the shell's own test) nor wherever the
 *   renderer's `mayStart` says no (the model, a measurement): a drag from there is Select's, the camera's
 *   -- and its release takes the annotation's ink it touches (`selectsAnnotations`; with what was drawn
 *   with it), then hands the box to `onBox` for what is the renderer's own: the model and its overlays
 *   (a measurement, `measureSelectHandlers`' `box`). Shift adds to each; otherwise the box replaces
 *   each, the ink included, so parts, measurements and ink one box takes stay picked together
 *   (`kit/tools/select/boxTake.js`). Without it, no box.
 *   `inkTouches`: what the model is under a point of the view, `(clientX, clientY) => [{ part, ref? }]` —
 *   the part, with the face or edge there as a prompt reference where the renderer can name one: what
 *   Annotate records a mark as touching. Without it, a mark touches parts alone.
 *   `previewView`: Preview's own, while it is open (`shell.previewing`), for a 3D view: the scene the
 *   renderer built for it (`scene`, its family's builder over the editor's geometry, null until it can be
 *   drawn), what drives that scene from inside Preview's viewport (`overlay(viewport, drawn)`, given
 *   the Render scene Preview draws), its routine (`animation`, the Animation section's in Preview),
 *   its publication readiness (`complete`, false while components are arriving),
 *   and Preview viewport's `runtimeLifecycle` and `onCameraSettled`. Preview is a view of its own
 *   (`PreviewView.jsx`) over the editor's, which nothing of it reaches.
 *   `iconSprite`: the hidden SVG sprite the renderer's chrome draws its icons from (`<use href="#…"/>`),
 *   mounted once in the frame; a renderer that draws its icons itself passes none.
 *   `alertBody`, `alertStartsDismissed`: what a renderer lists under the alert it raised itself (a
 *   result's findings: `kit/status/findings.jsx`), a function of the card's `dismiss`, so a row
 *   chosen can put the card away, and whether that alert starts put away (suggestions only).
 *   `ribbon`, `leftDock`, `bottomDock`, `dialogPlace`: edit mode's frame (`xbf/edit/`), the workspace,
 *   laid out as a CAD tool lays out its window: the toolbar across the top (`ribbon`, given the strip's
 *   tools for its command search; the strip keeps them, less the view's own controls, under the toolbar
 *   with its panels and Quick Edit); the design tree, a column docked at the left under it, holding
 *   `leftDock`, which folds to its title and stands in for the view's panel. The column takes its width
 *   from the canvas, so the model is never under it and the canvas resizes as the layout turns to the
 *   workspace and Simple view's ai layout, or as the column folds: a plain resize, the camera left as
 *   it is. Beside it the place the open command's dialog mounts in (`dialogPlace`, a ref callback); and the
 *   timeline along the bottom up to the cube (`bottomDock`, drawing its own surface, as the toolbar
 *   does). It fades in as the layout turns to it and out as Simple view takes its place, in one
 *   transition; it is put away at once with the rest of the tools (loading, Preview, a compact view),
 *   and the design tree in a view too narrow for it and the model, which then has the whole view. While the toolbar is up the
 *   view's own controls (Projection, Display, Preview) and the view catching up are its, not the
 *   strip's: `ribbon(tools, view)` is handed them (`view.controls`, small tiles for its tab row's right
 *   end, and `view.status`; null while it fades). `dialogOpen`: the dialog's place holds something,
 *   and the top column, a tool's own row and its panels, keeps to the room past it.
 *   `notice`: a notice of the renderer's own about its file (one brought in, offered to model on),
 *   in the top-right corner under the host's (`view.notice`): Quick Edit opens under both, so
 *   neither ever covers the other, at any width.
 *   `layoutControl`: a control of the renderer's own that lays the view out (a `ViewportViewControl`,
 *   `FloatingToolBar.js`), the first of the view's own controls: at the strip's end before Projection,
 *   or at the toolbar's tab row's right end while the workspace is up (edit mode's switch between
 *   modeling by hand and asking the AI, `xbf/edit/EditLayoutSwitch.jsx`).
 *   `quickEditAsked`: for a renderer with a button of its own to ask for Quick Edit (the workspace's Ask). `true`:
 *   it is open, whatever is picked or drawn, and with nothing picked on the file as a whole; `false`: it is shut
 *   until asked, a written note excepted; null (the default): it follows what it would carry (`references`).
 */
export default function RendererShell({ shell, tools, toolPanels = null, subToolbar = null, sidebar = null, references = null, referenceChips = null, nameReference = null, onClearReferences = null,
  requests = null, onClearRequests = null, copySelection = null, contextMenuItems = null,
  onContextMenuOpenChange = null, viewportOverlay = null, previewView = null,
  frameProvider = null, iconSprite = null, onCanvasPointerDown = null, onSelectPress = null, onSelectHover = null, selectsAnnotations = true, boxSelect = null, inkTouches = null,
  doubleClickFits = true, zoomToSelection = null, inspect = null,
  alertBody = null, alertStartsDismissed = false, ribbon = null, leftDock = null, bottomDock = null, dialogPlace = null, dialogOpen = false,
  layoutControl = null, quickEditAsked = null, notice = null }) {
  const { t } = useI18n();
  const frame = shell.frame;
  // What a tool's letter takes up (`useRendererShell`'s `onKey`): the strip as drawn now, in edit
  // mode too (its S, the command search, is taken first: `xbf/edit/useEditShortcuts.js`).
  frame.toolKeys.current = tools;
  const mobile = useViewerMobile();
  const { view, resolvedScene, viewerLoading, scene } = frame;
  // The one presentation state: every gate — the viewport's, the renderer's — reads it.
  const { previewing, setPreviewing } = shell;
  // A phone's open section is a sheet up from the bottom, where Quick Edit's peek is: it steps aside.
  // Preview's settings panel: closed as Preview opens, until its button brings it out.
  const [previewPanelOpen, setPreviewPanelOpen] = useState(false);
  // Preview is a view of its own, mounted over the editor's as it opens (`PreviewView.jsx`), and
  // its first picture takes a moment on a large model — its scene built from the published mesh
  // and remaining components arriving — so it is covered ("Preparing preview…") until
  // its first frame is presented (`previewPresented`), the publication is complete,
  // and its picture converged (every sample of its frame drawn: the view's `pictureProgress`) — unless
  // it starts over, the view moving (a routine playing), when there is nothing to wait for — or at most
  // a few seconds. Then the cover fades away from the finished picture. Leaving needs no cover: the
  // Preview's view goes, and under it is the editor's, as it was.
  const previewViewRef = frame.previewViewRef;
  const [previewPresented, setPreviewPresented] = useState(false);
  const previewPresentedRef = useRef(false);
  previewPresentedRef.current = previewing && previewPresented;
  // A press covers the view first, in its own frame, and preview is entered under it: preview's
  // first render can take a moment on a large model, and the cover answers the press at once.
  const [coverRequested, setCoverRequested] = useState(false);
  // The cover is preview's from the render that enters it, so not one frame of preview shows
  // before it: settled is reset there, and set once preview has come together. Each crossing is
  // taken in the render that makes it, never in an effect after it (another commit): entering also
  // answers the press's request and closes the settings panel.
  const [previewSettled, setPreviewSettled] = useState(false);
  const [coverFor, setCoverFor] = useState(previewing);
  if (coverFor !== previewing) {
    setCoverFor(previewing);
    setPreviewSettled(false);
    setPreviewPresented(false);
    if (previewing) { setCoverRequested(false); setPreviewPanelOpen(false); }
  }
  const previewCovered = coverRequested || (previewing && !previewSettled);
  // What moves Preview's picture on purpose: its Orbit, or its routine playing (`previewCover.js`).
  const previewMovingRef = useRef(false);
  previewMovingRef.current = shell.orbiting || previewView?.animation?.playing === true;
  const previewLoadingRef = useRef(false);
  previewLoadingRef.current = previewView?.complete === false;
  useEffect(() => {
    if (!previewing) return undefined;
    let quiet = 0, done = false, capped = false;
    const finish = () => { if (done) return; done = true; setPreviewSettled(true); };
    // Published components still streaming (a model opened cold) is waited for this long, no longer; then the
    // picture on screen converges, and the cover lifts on it, or at the last at FINISH more.
    const cap = setTimeout(() => { capped = true; settle(0); }, PREVIEW_COVER_MAX_MS);
    const last = setTimeout(finish, PREVIEW_COVER_MAX_MS + PREVIEW_COVER_FINISH_MS);
    const settle = (delay = PREVIEW_COVER_QUIET_MS) => {
      clearTimeout(quiet);
      quiet = setTimeout(() => {
        const step = previewCoverStep({ presented: previewPresentedRef.current, loading: previewLoadingRef.current && !capped, moving: previewMovingRef.current,
          progress: previewViewRef.current?.pictureProgress?.() ?? null });
        if (step === "wait") settle();
        else if (step === "converge") settle(PREVIEW_COVER_CONVERGE_MS);
        else finish();
      }, delay);
    };
    settle(PREVIEW_COVER_MIN_MS);
    return () => { done = true; clearTimeout(cap); clearTimeout(last); clearTimeout(quiet); };
  }, [previewing]);
  // The routine the Animation section plays: the tools view's, or in Preview its own.
  const animation = previewing ? previewView?.animation ?? null : frame.animation;
  const hasAnimation = animationControlsHaveContent(animation);
  // Speed and Loop, once chosen in the Animation section's Playback settings, are the file's, and what its
  // routines play with, whatever they authored, until they are chosen again. Unset, the routine's own apply.
  const { speed: chosenSpeed, loop: chosenLoop } = shell.playback;
  const controls = useControlUsage();
  const animationRef = useRef(animation);
  animationRef.current = animation;
  useEffect(() => {
    const runtime = animationRef.current;
    if (!animationControlsHaveContent(runtime)) return;
    if (chosenSpeed != null && Number(runtime.speed) !== chosenSpeed) runtime.onSpeedChange(chosenSpeed);
    if (chosenLoop != null && (runtime.loopEnabled !== false) !== chosenLoop) runtime.onLoopToggle(chosenLoop);
  }, [previewing, hasAnimation, animation?.speed, animation?.loopEnabled, animation?.activeClipId, chosenSpeed, chosenLoop]);
  // Preview opens at rest, its routine started only by Autoplay.
  const autoplayRef = useRef(shell.autoplay);
  autoplayRef.current = shell.autoplay;
  useEffect(() => {
    const runtime = animationRef.current;
    if (previewing && autoplayRef.current && animationControlsHaveContent(runtime) && !runtime.playing) runtime.onPlayToggle();
  }, [previewing, hasAnimation]);
  // What those settings change is the file's, and applied to its routine at once.
  // The person's presses on them are counted (`usage/controls.js`); the shell's own, above, are not.
  const playbackRuntime = hasAnimation ? {
    ...animation,
    onPlayToggle: (...args) => { controls.used("animation_play"); return animation.onPlayToggle?.(...args); },
    onClipSelect: (...args) => { controls.used("animation_clip"); return animation.onClipSelect?.(...args); },
    onRelease: (...args) => { controls.used("animation_release"); return animation.onRelease?.(...args); },
    onSpeedChange: value => { controls.used("animation_speed"); shell.setPlayback({ speed: value }); animation.onSpeedChange(value); },
    onLoopToggle: value => { controls.used("animation_loop"); shell.setPlayback({ loop: value }); animation.onLoopToggle(value); }
  } : null;
  // Preview opens still: its Orbit tile starts the camera turning, and a second press stops it.
  const orbitPlaying = shell.orbiting;
  // Under Select, what the pointer rests on is lit as a part is: the annotation's mark (and the marks
  // drawn with it) or the renderer's overlay, and the part under it is not.
  const [hoveredAnnotation, setHoveredAnnotation] = useState(null);
  const overSelectable = useRef(false);
  // The ink a press under Select last picked, and the ink picked before it: a double-click on it
  // puts that back, as it selects nothing.
  const inkPress = useRef(null);
  // The pointer cursor over them, as a renderer shows over a part.
  const [pointing, setPointing] = useState(false);
  const selectHover = useRef(onSelectHover);
  selectHover.current = onSelectHover;
  const leaveSelectHover = () => {
    overSelectable.current = false;
    setPointing(false);
    selectHover.current?.(null);
    setHoveredAnnotation(current => (current ? null : current));
  };
  useEffect(() => { if (!frame.selecting) leaveSelectHover(); }, [frame.selecting]);
  const hoverSelectable = event => {
    if (!frame.selecting || event.buttons !== 0 || !(event.target instanceof Element) || !event.target.closest("canvas")) {
      if (overSelectable.current || hoveredAnnotation) leaveSelectHover();
      return;
    }
    const session = frame.annotation;
    const overlay = Boolean(selectHover.current?.(event));
    const id = !overlay && selectsAnnotations && session.items.length ? frame.viewerRef.current?.annotationAt?.(event.clientX, event.clientY, event.pointerType) : null;
    const ids = id ? withGroups([id], session.items) : null;
    setHoveredAnnotation(current => (ids && current && current.join() === ids.join()) || (!ids && !current) ? current : ids);
    const over = overlay || Boolean(id);
    if (over && !overSelectable.current) {
      // The part lit under the pointer lets go, as when the pointer leaves the model.
      for (let node = event.target; node && node !== event.currentTarget; node = node.parentElement) {
        node.dispatchEvent(new PointerEvent("pointerleave", { bubbles: false, pointerId: event.pointerId, pointerType: event.pointerType }));
      }
    }
    overSelectable.current = over;
    setPointing(over);
    // Over a mark or a measurement the part under it hears nothing of the pointer.
    if (over) event.stopPropagation();
  };
  useEffect(() => { setPreviewing(false); }, [frame.modelKey, setPreviewing]);
  // Preview is a view of its own (`PreviewView.jsx`): it opens on the model as authored, in Render,
  // still, its routine at rest and started only by Autoplay, and leaving it takes it away.
  const enterPreview = () => {
    setCoverRequested(true);
    // After the frame the cover is painted in (a hidden page paints none: a timer stands in).
    let entered = false;
    const enter = () => { if (!entered) { entered = true; setPreviewing(true); } };
    requestAnimationFrame(() => setTimeout(enter, 0));
    setTimeout(enter, 100);
  };
  const leavePreview = () => setPreviewing(false);
  // Preview's bar names what it shows: the file's name, or its path's last part.
  const previewName = view.file?.name || String(view.file?.path ?? "").split("/").pop() || "";
  // While Preview is up the host's chrome steps aside (FileViewer's navbar): said as it opens, and as
  // it closes or the view goes.
  // Preview's bar and its playbar, shown and gone together while the pointer rests; its settings open hold them.
  const previewIdle = usePreviewIdle(frame.hostElement, previewing, previewPanelOpen);
  const onPreviewChange = view.onPreviewChange;
  useEffect(() => {
    if (!previewing || !onPreviewChange) return undefined;
    onPreviewChange(true);
    return () => onPreviewChange(false);
  }, [previewing, onPreviewChange]);
  // The drawing tools' sub-toolbar, one row under the strip while Pencil or Shapes is the tool: what it draws with, what the next mark
  // looks like, and Undo, Redo and Clear (`annotation/toolbar.jsx`). The annotation itself has no
  // panel: it is Quick Edit's chip (its X clears it, a click copies it).
  const colorScheme = view.appearance?.colorScheme === "dark" ? "dark" : "light";
  // Otherwise the renderer supplies its active tool's row.
  const toolRow = frame.annotateToolActive
    ? <AnnotationToolbar annotation={frame.annotation} colorScheme={colorScheme} />
    : subToolbar;

  const hasContent = Boolean(scene) && !viewerLoading;
  // A load the model did not survive: an alert that cannot be put away (a failed update that
  // keeps the previous version on screen can be, and keeps its chrome).
  const failed = Boolean(frame.viewerAlert) && !alertDismissible(frame.viewerAlert, hasContent);
  // The card's dismissal is the frame's, so it outlives the card (gone in preview): while the person
  // has the card put away, its icon is the navbar's way back to it, leftmost of the right-hand group.
  const alertDismissal = useAlertDismissal(frame.viewerAlert, { hasContent, scope: frame.modelKey,
    startDismissed: alertStartsDismissed, onNavigationActionsChange: view.onNavigationActionsChange });
  // While the model loads, or once it has failed to, the viewer shows none of its own chrome: no
  // tools, no Quick Edit, no cube, no view actions and no update status -- only the load itself,
  // or the card saying why it failed. They arrive with the model, and stay through a rebuild that
  // keeps it on screen (that is `updating`, not loading).
  const chromeHidden = viewerLoading || failed;
  // A host showing the view small (inline in a conversation: `appearance.compact`) gets the model
  // alone, not the tools, Quick Edit, the view actions or the cube; shown full size, all return.
  const compact = Boolean(view.appearance?.compact);
  const toolsHidden = chromeHidden || compact;
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
    if (!toolbarUp || !toolbar || !stage) return undefined;
    const measure = () => stage.style.setProperty("--cad-workspace-top", `${Math.round(toolbar.getBoundingClientRect().height)}px`);
    measure();
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resized?.observe(toolbar);
    return () => { resized?.disconnect(); stage.style.removeProperty("--cad-workspace-top"); };
  }, [toolbarUp]);
  const measureColumn = useRef(null);
  usePastNavigator(frame.hostRef, navigatorUp && !mobile, [toolbarUp, navigatorFolded, pastNavigator, Boolean(references)], measureColumn);
  // The view's panel (`FlatPanel.jsx`, placed by the frame): docked at the left, its tabs the renderer's
  // sections, one state with every view's; none on a phone; Preview keeps it mounted out of sight. While the
  // workspace's design tree is docked it stands in for the panel.
  const panel = sidebar && !(leftDock && editFrame) ? { kind: "model", label: t("flatPanel.modelPanel"), searchLabel: t("flatPanel.searchModel"), sections: sidebar } : null;
  // Display's tile is its mode's sphere; on a phone with no room for it, its More row shows the same.
  const DisplayIcon = (frame.displayMode?.options?.find(option => option.value === frame.displayMode.value) || frame.displayMode?.options?.[0])?.Icon;
  const copyAction = () => {
    if (previewing) return false;
    if (frame.annotateToolActive) { frame.copyAnnotation(); return true; }
    if (copySelection) { copySelection(); return true; }
    return false;
  };
  frame.copyActionRef.current = copyAction;
  // Quick Edit's X: nothing picked and nothing drawn, as the person would clear each.
  const clearQuickEdit = () => { onClearReferences?.(); onClearRequests?.(); if (frame.annotation.hasAnnotation) frame.annotation.forget(); };
  const forgetAnnotation = frame.annotation.forget;
  // Quick Edit's annotation: while Annotate is up or there is ink. The annotation goes with a note whenever
  // there is one (its views and annotation file, `frame.quickEditPrompt`); its Annotation chip's X wipes it.
  const annotation = useMemo(() => frame.annotateToolActive || frame.annotation.hasAnnotation
    ? { present: frame.annotation.hasAnnotation, clear: forgetAnnotation } : null,
  [frame.annotateToolActive, frame.annotation.hasAnnotation, forgetAnnotation]);
  // The renderer's overlay and the shell's own layers share one viewport context.
  // The view's zoom (`ZoomControl.jsx`'s `ViewZoom`): the viewport's zoom against the authored box, read live,
  // for the keys and a phone's More.
  const viewerRef = frame.viewerRef;
  // A model's viewport, once it is up: its camera is the one the readout follows.
  const zoomBase = useMemo(() => viewportZoom(viewerRef), [viewerRef, scene, viewerLoading]);
  const zoom = { ...zoomBase, zoomToSelection: zoomToSelection?.run || null, selectionAvailable: Boolean(zoomToSelection?.available) };
  // What the zoom's keys reach (`useRendererShell`'s `zoom`): the zoom as the strip has it now.
  frame.zoomKeys.current = zoom;
  // Box select's box: the ink it touches, as it takes the model (`annotationsInBox`), then
  // the renderer's own. Shift adds; otherwise the ink picked is what the box took, none if nothing.
  const takeBox = box => {
    const session = frame.annotation;
    const touched = selectsAnnotations && session.items.length ? frame.viewerRef.current?.annotationsInBox?.(box.client) || [] : [];
    takeInkInBox(session, touched, box.additive);
    boxSelect?.onBox?.(box);
  };
  // A drag from the ink is Select's, never a box: the ink is drawn there whatever the filter picks.
  const boxMayStart = event => !(frame.annotation.items.length && frame.viewerRef.current?.annotationAt?.(event.clientX, event.clientY, event.pointerType))
    && (boxSelect?.mayStart ? boxSelect.mayStart(event) : true);
  const overlay = viewport => <>
    {previewing || !contextMenuItems ? null : <ViewportContextMenu viewport={viewport} items={contextMenuItems} onOpenChange={onContextMenuOpenChange} />}
    {previewing || !doubleClickFits ? null : <DoubleClickFit viewport={viewport} scene={scene} viewerRef={frame.viewerRef} />}
    {/* The ink Select has picked, its bar: restyle, fill, delete. */}
    {frame.selecting && frame.annotation.selected.length ? <AnnotationSelectionBar annotation={frame.annotation} colorScheme={colorScheme} runtimeRef={viewport.runtimeRef}
      viewerReadyTick={viewport.viewerReadyTick} onDelete={frame.deletePicked} disabled={viewerLoading || !scene} /> : null}
    {typeof viewportOverlay === "function" ? viewportOverlay(viewport) : viewportOverlay}
    {boxSelect ? <BoxSelectGesture viewport={viewport} enabled={frame.selecting && Boolean(boxSelect.enabled)} onBox={takeBox} mayStart={boxMayStart} /> : null}
  </>;
  // One place says the view is catching up: a newer revision of the file loading behind the model on
  // screen, or a Display change being prepared — the latter's failure first, since it is the one with
  // something to retry. Under the strip at the top centre, or in its place where there is no strip.
  // While the workspace's toolbar is up it says it there instead, beside the part's build status.
  const viewUpdateStatus = frame.loading.updating && !frame.viewUpdate.status.error ? modelUpdateStatus(frame.loading.progress) : frame.viewUpdate.status;
  const updateStatus = toolbarUp ? null : { preview: Boolean(frame.loading.preview), onRetry: frame.viewUpdate.retry, update: viewUpdateStatus };
  const quickEdit = references ? <QuickEdit key={frame.modelKey} className="self-stretch" hidden={chromeHidden} docked={quickEditDocked(mobile)}
    resource={frame.resource} references={references} chips={referenceChips} nameReference={nameReference} annotation={annotation} requests={requests} prompt={frame.quickEditPrompt}
    asked={quickEditAsked} onCopy={copyAction} onEscape={frame.escape} onClear={clearQuickEdit} disabled={viewerLoading || !scene} /> : null;
  // The view's own controls: the renderer's layout (`layoutControl`), Projection (the state button), Display (its
  // menu), then Preview. They end the strip, after its rule, or, while the workspace's toolbar is up, are its small
  // tiles at its tab row's right end, their names below them. A phone has no room for them on its strip: they are
  // rows of its More, with the zoom.
  const viewControls = tooltipSide => (shell.previewable && !previewing ? [
    ...(layoutControl ? [layoutControl] : []),
    { id: "projection", label: t("projection.label"), icon: <ProjectionIcon value={frame.projection.value} />, disabled: shell.idle,
      tile: <ProjectionToggle disabled={shell.idle} projection={frame.projection} tooltipSide={tooltipSide} />,
      // In a phone's More, a row that switches it the same way.
      onSelect: () => frame.projection.onChange(otherProjection(frame.projection.value)) },
    { id: "display", label: t("display.label"), icon: DisplayIcon ? <DisplayIcon /> : null, disabled: shell.idle,
      tile: <DisplayPopover disabled={shell.idle} boundary={frame.hostElement} mode={frame.displayMode} grid={frame.grid} gates={frame.displayGates}
        tooltipSide={tooltipSide} />,
      // In a phone's More, the same list opened under its row, in More itself (`FloatingToolBar.js`'s TouchStrip):
      // the modes, then Grid and the renderer's own gates.
      submenu: () => <DisplayMenuItems mode={frame.displayMode} grid={frame.grid} gates={frame.displayGates} /> },
    ...(mobile ? [zoomViewControl(zoom, { t, disabled: shell.idle })] : []),
    { id: "preview", label: t("preview.label"), icon: <Play aria-hidden="true" />, disabled: shell.idle, onSelect: enterPreview,
      tile: <ViewControl label={t("preview.label")} tooltipSide={tooltipSide} disabled={shell.idle} onClick={enterPreview}><Play aria-hidden="true" /></ViewControl> }
  ] : []);
  const views = toolbarUp ? [] : viewControls("top");
  // What the toolbar is handed of the view while it is up.
  const toolbarView = toolbarUp ? {
    controls: viewControls("bottom").map(control => <Fragment key={control.id}>{control.tile}</Fragment>),
    status: failed ? null : <ViewUpdateStatus status={viewUpdateStatus} onRetry={frame.viewUpdate.retry} className="text-tiny" />
  } : null;
  // Under Select a press on the canvas picks, front to back: the renderer's own overlays (a
  // measurement), then the annotation's mark (and the marks drawn with it), then a part. Shift adds or
  // takes away; a press that picks one kind lets go of the others, unless Shift keeps them.
  const pressCanvas = event => {
    onCanvasPointerDown?.(event);
    if (!frame.selecting || event.button !== 0) return;
    const session = frame.annotation;
    if (onSelectPress?.(event)) {
      event.stopPropagation();
      event.preventDefault();
      if (!event.shiftKey && session.selected.length) session.select([]);
      return;
    }
    const id = selectsAnnotations && session.items.length ? frame.viewerRef.current?.annotationAt?.(event.clientX, event.clientY, event.pointerType) : null;
    if (!id) { if (!event.shiftKey && session.selected.length) session.select([]); return; }
    event.stopPropagation();
    event.preventDefault();
    // The second press of a double-click keeps what the first found.
    const again = inkPress.current?.id === id && event.timeStamp - inkPress.current.at < DOUBLE_PRESS_MS;
    inkPress.current = { id, before: again ? inkPress.current.before : session.selected, at: event.timeStamp };
    const picked = event.shiftKey
      ? (session.selected.includes(id) ? session.selected.filter(other => other !== id) : [...session.selected, id])
      : [id];
    if (!event.shiftKey) onClearReferences?.();
    session.select(withGroups(picked, session.items));
  };
  const rootHandlers = {
    // Under Select a double-click on ink turns the view square to it (`ShellViewport.jsx`'s
    // `lookAtAnnotation`), as one on a face or edge does, and selects nothing: the ink picked is as
    // its first click found it. Never on to the part under it.
    onDoubleClickCapture: event => {
      if (!frame.selecting || !selectsAnnotations || !frame.annotation.items.length) return;
      if (!(event.target instanceof Element) || !event.target.closest("canvas")) return;
      const id = frame.viewerRef.current?.annotationAt?.(event.clientX, event.clientY, event.nativeEvent?.pointerType || "");
      if (!id) return;
      event.stopPropagation();
      event.preventDefault();
      if (inkPress.current?.id === id) frame.annotation.select(inkPress.current.before);
      inkPress.current = null;
      frame.viewerRef.current?.lookAtAnnotation?.(id);
    },
    onPointerMoveCapture: hoverSelectable,
    onPointerLeave: () => { if (overSelectable.current || hoveredAnnotation) leaveSelectHover(); }
  };
  // Preview: the tools put away and the host's navbar too (FileViewer hides it while
  // `view.onPreviewChange` says Preview is up), the model in Render — the tools view never is — and
  // still until Orbit is turned on. In the navbar's place, Preview's own bar over the view's top edge,
  // on no surface, gone while the pointer rests (`PreviewChrome`): the file's name, and at its right its
  // settings (a toggle, the panel docked under it at the view's right edge: Orbit, Render's own), closed
  // as it opens, and the way out. The same in every host.
  // Under the workspace's toolbar, the strip, the top-right and Preview's bar start below it (`top`).
  const preview = { active: previewing, top: toolbarUp ? WORKSPACE_TOP : undefined, name: previewName, idle: previewIdle, panelOpen: previewPanelOpen,
    controls: <>
      <BarControl label={t("preview.settings")} active={previewPanelOpen} disabled={shell.idle}
        onClick={() => { if (!previewPanelOpen) controls.used("preview_settings"); setPreviewPanelOpen(open => !open); }} data-preview-settings=""><SlidersHorizontal className="size-3.5" aria-hidden="true" /></BarControl>
      <BarControl label={t("preview.exit")} onClick={leavePreview}><X className="size-3.5" aria-hidden="true" /></BarControl>
    </>,
    panel: <PreviewSettings orbit={orbitPlaying} onOrbitChange={shell.setOrbiting}
      speed={frame.previewOrbitSpeed || 1} onSpeedChange={frame.setPreviewOrbitSpeed}
      onClose={() => setPreviewPanelOpen(false)} render={frame.previewSettings} /> };
  // The top column's left while the workspace is up: past an open dialog, or past the design tree's column.
  const columnClass = besideDialog ? BESIDE_DIALOG_CLASS[workspace.chrome.leftDock ? "navigator" : "alone"] : pastNavigator && PAST_NAVIGATOR_COLUMN_CLASS;
  // The workspace, over the view: the toolbar across the top, the design tree's column at the left under it
  // (folded, its title alone over the canvas, what it holds kept), the open command's dialog beside it, and the
  // timeline along the bottom to the cube. The top-right stays Quick Edit's and the bottom corner the cube's.
  // Inert while it fades.
  const workspaceLayer = workspace ? <div data-cad-workspace="" inert={workspace.leaving} aria-hidden={workspace.leaving || undefined}
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
    {workspace.chrome.bottomDock ? <div className={cn("pointer-events-auto absolute inset-x-0 bottom-0", pastNavigator && PAST_NAVIGATOR_CLASS)} data-cad-dock="timeline" style={TIMELINE_POSITION}>
      {workspace.chrome.bottomDock}
    </div> : null}
  </div> : null;
  const body = (
    <ViewFrame rootRef={frame.hostRef} measureRef={measureColumn} className={cn(pointing && "cursor-pointer", columnClass)} rootHandlers={rootHandlers} onCanvasPress={pressCanvas} selecting={frame.selecting}
      inspect={inspect}
      stageColor={frame.stageColor} file={frame.modelKey} mobile={mobile} compact={compact} chromeHidden={chromeHidden} previewing={previewing}
      preview={preview} tools={tools} views={views} toolRow={toolRow} status={updateStatus}
      toolStack={<ToolStack hidden={previewing} layout={frame.toolStack} onLayoutChange={frame.changeToolStack}>{toolPanels}</ToolStack>}
      panel={panel} panelControl={frame.panelControl} layout={frame.toolStack} onLayoutChange={frame.changeToolStack}
      // The host's notice (`view.notice`), the renderer's own under it (`notice`), and Quick Edit under them.
      notice={view.notice || notice ? <div className="flex flex-col gap-2">{view.notice}{notice}</div> : null} quickEdit={quickEdit}
      // Preview: a view of its own over the editor's, mounted while it is open.
      underlay={previewing && previewView ? <div className="pointer-events-auto absolute inset-0 z-[1]" data-preview-view="">
        <PreviewView view={previewView} desired={frame.previewDesiredScene} modelKey={frame.modelKey}
          sceneScaleMode={frame.sceneScaleMode} viewRef={previewViewRef} onPresented={setPreviewPresented}
          orbit={orbitPlaying} orbitSpeed={frame.previewOrbitSpeed ?? 1} />
      </div> : null}
      // A file with routines: its playbar under the model, in the tools view as in Preview (the same
      // transparent row, with Reset first, and on a phone over Quick Edit's peek), Preview's its own routine.
      bottomCentre={<>
        {!previewing && !toolsHidden && hasAnimation ? <PreviewPlaybar key={`tools-${frame.modelKey}`} runtime={playbackRuntime} disabled={viewerLoading || !scene}
          autoplay={shell.autoplay} onAutoplayChange={shell.setAutoplay} toolsView phone={mobile} /> : null}
        {previewing && hasAnimation ? <PreviewPlaybar key={frame.modelKey} runtime={playbackRuntime} disabled={viewerLoading || !scene}
          autoplay={shell.autoplay} onAutoplayChange={shell.setAutoplay} idle={previewIdle} /> : null}
      </>}
      // The workspace over the view, then Preview coming together underneath: the view as it was, held, until
      // the picture is ready.
      overlays={<>{workspaceLayer}<div aria-hidden={!previewCovered} data-preview-cover={previewCovered ? "" : undefined}
        className={cn("absolute inset-0 z-40 flex items-center justify-center",
          // At once over the press, so nothing of preview shows first; it fades only as it lifts.
          previewCovered ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0 transition-opacity duration-300 motion-reduce:transition-none")}
        style={{ backgroundColor: frame.stageColor }}>
        {previewCovered ? <span role="status" className="flex items-center gap-2 text-tiny text-muted-foreground">
          <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />{t("preview.preparing")}
        </span> : null}
      </div></>}
      loading={frame.presentationState?.file === frame.modelKey && frame.presentationState?.covering ? null : frame.loading}
      // The card: the file as the alert names it (the catalog's absolute path), which Report Issue keeps out of its issue.
      alert={{ alert: frame.viewerAlert, hasContent, dismissed: alertDismissal.dismissed, onDismiss: alertDismissal.dismiss,
        onReload: view.reload, file: frame.modelKey || view.file?.path,
        // What a renderer lists under the alert it raised itself (a result's findings).
        body: alertBody ? alertBody(alertDismissal.dismiss) : null }}>
      {iconSprite}
      {/* The canvas is clipped to the stage; the strip is not, so it reaches over the docked panel. Its
          box's background is the scene's edge colour (the stage's): the scene is resized on the next
          frame, and one frame of another colour above a dark stage is a visible band. With the
          workspace up it starts past the design tree's column and under the toolbar, so a fit centres
          in the room the model really has. */}
      <div className={cn("pointer-events-auto absolute inset-0 z-0 overflow-hidden", pastNavigator && PAST_NAVIGATOR_CLASS)}
        style={toolbarUp ? CANVAS_UNDER_TOOLBAR : undefined} data-cad-scene-canvas="">
        <div className="absolute inset-0">
          <ShellViewport
            ref={frame.viewerRef}
            scene={scene}
            modelKey={frame.modelKey}
            presentationKey={frame.presentationKey}
            sceneScaleMode={frame.sceneScaleMode}
            perspective={frame.viewerPerspective}
            perspectiveRef={frame.activePerspectiveRef}
            projection={resolvedScene.camera.projection}
            focalLength={resolvedScene.camera.focalLength}
            themeSettings={resolvedScene.theme}
            displaySettings={resolvedScene.display}
            sceneEffects={frame.sceneEffects}
            appearance={resolvedScene.appearance}
            receiveShadows={resolvedScene.view.lighting.enabled}
            renderMode={resolvedScene.render.enabled}
            renderConfiguration={resolvedScene.render.configuration}
            quality={resolvedScene.quality}
            // Under Preview the editor draws nothing; it draws what it owes as Preview goes.
            suspended={previewing}
            isLoading={viewerLoading}
            viewCube={!compact && !failed && !mobile}
            viewUpdate={frame.viewUpdate}
            loadingPresentation={frame.loading}
            annotationEnabled={frame.annotateToolActive}
            annotation={frame.annotation}
            hoveredAnnotation={hoveredAnnotation}
            annotationView={frame.currentView}
            annotationTouches={inkTouches}
            onPerspectiveChange={frame.handlePerspectiveChange}
            onPresentationChange={frame.handlePresentationChange}
            onViewerAlertChange={frame.setRuntimeAlert}
            onCameraSettled={frame.onCameraSettled}
            preserveInteractionPixelRatio={frame.preserveInteractionPixelRatio}
            runtimeLifecycle={frame.runtimeLifecycle}
          >{overlay}</ShellViewport>
        </div>
      </div>
    </ViewFrame>
  );
  return frameProvider ? frameProvider(body) : body;
}
