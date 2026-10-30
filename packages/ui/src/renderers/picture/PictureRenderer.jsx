import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@text-to-cad/ui/utils";
import { clearSurface, fitTransform } from "@text-to-cad/core/lib/drawing2d/index.js";
import { drawAnnotationMarks } from "@text-to-cad/core/lib/drawing2d/marks.js";
import { planCamera } from "@text-to-cad/core/lib/drawing2d/planView.js";
import { useViewerMobile } from "../../file-viewer/responsive.js";
import { useViewerHost } from "../../host/context.js";
import { annotationAt, withGroups } from "../../annotation/geometry.js";
import { promptView } from "../../annotation/views.js";
import FlatViewFrame, { flatViewTools } from "../kit/shell/FlatViewFrame.jsx";
import { FLAT_TOOL, useFlatHandover, useFlatTools } from "../kit/shell/useFlatView.js";
import { readFileView, writeFileView } from "../kit/shell/fileView.js";
import AnnotationOverlay from "../kit/tools/annotate/AnnotationOverlay.jsx";
import { useSceneReferences } from "../kit/tools/select/sceneReferences.jsx";
import { useSceneSelection } from "../kit/tools/select/useSceneSelection.js";
import { useFlatCanvasView } from "../kit/viewport/useFlatCanvasView.js";
import { TOUCH_HIT_PX } from "../kit/viewport/dom.js";
import { useWorkspaceDocument } from "../workspace/useWorkspaceDocument.js";
import { drawingAnnotationDocument, drawingAnnotationSurface } from "../dxf/drawingAnnotation.js";
import { drawingTransformCamera, readDrawingTransform } from "../dxf/drawingTransform.js";
import { DRAWING_THEME_FALLBACK, readDrawingThemeColors } from "../dxf/themeColors.js";
import { paintSheets, readSheets } from "./pictureSheets.js";
import { PICTURE_DECLINED_LIVE_COMMANDS, PICTURE_NO_CAMERA, PICTURE_NO_DISPLAY, PICTURE_TOOL_MODES } from "./tools.js";
import { useI18n } from "@text-to-cad/ui/i18n";

/**
 * A picture (a drawing's PDF, a render, a photo) is shown as a DXF is: on a canvas, head on, with
 * every flat view's chrome (`kit/shell/FlatViewFrame.jsx`), but read as a page is: the wheel and a
 * two-finger swipe scroll it and a pinch zooms (`scroll`). Select is the view's hand, Pencil and
 * Shapes to mark it up, and Quick Edit to send the marks with a note, whose views are the window on
 * screen as a plan-view camera. A PDF is a sheet per page, top to bottom (`pictureSheets.js`). The
 * ink lies on the sheet in its units (an image's pixels, a PDF's points), so it pans and zooms with
 * the picture. A picture has no entities to pick and no scale to measure in: no Measure, no Layers.
 */

const SAVE_DELAY_MS = 180;
const PICTURE_UPDATE_STATUS = Object.freeze({ pending: true, label: "Updating picture…" });
const PICTURE_LIVE = Object.freeze({ commands: Object.freeze(["clearSelection"]), declined: PICTURE_DECLINED_LIVE_COMMANDS });
const PICK_PX = 6;
const pickPx = pointerType => (pointerType === "touch" ? TOUCH_HIT_PX : PICK_PX);

/** The picture's sheets for this revision of the file: read again when it is rewritten, kept on screen while it is. */
function usePicture({ resources, entry, file, revision }) {
  const [state, setState] = useState({ picture: null, loading: true, updating: false, error: null });
  const url = entry?.url || "";
  useEffect(() => {
    if (!url || !resources) return undefined;
    const controller = new AbortController();
    setState(current => ({ ...current, loading: !current.picture, updating: Boolean(current.picture), error: null }));
    resources.readBytes(url, { signal: controller.signal })
      .then(bytes => readSheets(bytes, file, { signal: controller.signal }))
      .then(picture => { if (!controller.signal.aborted) setState({ picture, loading: false, updating: false, error: null }); })
      .catch(error => { if (!controller.signal.aborted) setState(current => ({ ...current, loading: false, updating: false, error })); });
    return () => controller.abort();
  }, [resources, url, file, revision]);
  return state;
}

function PictureSurface({ view, data }) {
  const { t } = useI18n();
  const mobile = useViewerMobile();
  const workspace = useWorkspaceDocument({ view, data });
  const file = workspace.entry?.file || view.file.path;
  const loaded = usePicture({ resources: workspace.client.resources, entry: workspace.entry, file, revision: workspace.resource.revision });
  const picture = loaded.picture;
  const { onStateChange } = view;
  const colorScheme = view.appearance?.colorScheme === "dark" ? "dark" : "light";

  // ---- the view this file was left at, as a drawing's is ------------------------
  const [restored] = useState(() => readDrawingTransform(readFileView(view.state).camera));
  const storedRef = useRef(JSON.stringify(writeFileView({ camera: drawingTransformCamera(restored, Boolean(restored)) })));
  const saveTimer = useRef(0);
  const stateChangeRef = useRef(onStateChange);
  stateChangeRef.current = onStateChange;
  const rememberView = useCallback((transform) => {
    const record = writeFileView({ camera: drawingTransformCamera(transform, Boolean(transform)) });
    const serialized = JSON.stringify(record);
    if (serialized === storedRef.current) return;
    storedRef.current = serialized;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => stateChangeRef.current?.(record), SAVE_DELAY_MS);
  }, []);
  useEffect(() => () => window.clearTimeout(saveTimer.current), []);

  // ---- tools ----------------------------------------------------------------
  const tools = useFlatTools({ toolModes: PICTURE_TOOL_MODES, file, revision: workspace.resource.revision, ready: Boolean(picture) });
  const { toolMode, annotating, annotation } = tools;
  const annotationRef = useRef(annotation);
  annotationRef.current = annotation;
  const toolRef = useRef(toolMode);
  toolRef.current = toolMode;
  const pictureRef = useRef(picture);
  pictureRef.current = picture;
  const hoveredInkRef = useRef([]);
  const paintRef = useRef(() => {});
  const requestPaint = useCallback(() => paintRef.current(), []);
  // Nothing in a picture is picked by reference: Quick Edit carries the marks and the note.
  const selection = useSceneSelection({ scene: null, requestRender: requestPaint });
  const { references, chips } = useSceneReferences({ scene: null, selection, resource: workspace.resource });

  const paint = useCallback((ctx, { width, height, pixelRatio, transform, element, colorScheme: scheme }) => {
    const { background } = readDrawingThemeColors(element, scheme);
    clearSurface(ctx, { width, height, pixelRatio, background });
    const shown = pictureRef.current;
    if (!shown || !transform) return;
    paintSheets(ctx, shown, { transform, pixelRatio });
    const session = annotationRef.current;
    drawAnnotationMarks(ctx, session.items, { transform, pixelRatio, selected: session.selected, hovered: hoveredInkRef.current });
  }, []);

  const viewRef = useRef(null);
  const annotationSurface = useMemo(() => drawingAnnotationSurface({
    transform: () => viewRef.current?.transformRef.current || null,
    canvas: () => viewRef.current?.canvasRef.current || null
  }), []);

  // ---- pointer: under Select, a tap picks the ink drawn on the picture ---------
  const [pointing, setPointing] = useState(false);
  const handlers = useMemo(() => {
    const inkUnder = (point, pointerType) => (annotationRef.current.items.length
      ? annotationAt(point, annotationSurface.onScreen(annotationRef.current.items), pickPx(pointerType))[0]?.id || null : null);
    const tap = (point, event) => {
      if (!pictureRef.current || toolRef.current !== FLAT_TOOL.SELECT) return;
      const session = annotationRef.current;
      const ink = inkUnder(point, event.pointerType);
      if (!ink) { if (!event.shiftKey && session.selected.length) session.select([]); return; }
      const picked = event.shiftKey ? (session.selected.includes(ink) ? session.selected.filter(id => id !== ink) : [...session.selected, ink]) : [ink];
      session.select(withGroups(picked, session.items));
    };
    const hover = (point, event) => {
      const ink = toolRef.current === FLAT_TOOL.SELECT && point && pictureRef.current ? inkUnder(point, event?.pointerType) : null;
      const inkIds = ink ? withGroups([ink], annotationRef.current.items) : [];
      if (inkIds.join() !== hoveredInkRef.current.join()) { hoveredInkRef.current = inkIds; requestPaint(); }
      setPointing(current => (current === Boolean(ink) ? current : Boolean(ink)));
    };
    return { tap, hover };
  }, [annotationSurface, requestPaint]);

  const flat = useFlatCanvasView({
    content: picture, bounds: picture?.bounds ?? null, restored, colorScheme, onViewMoved: rememberView, paint,
    onTap: handlers.tap, onHover: handlers.hover, scroll: true
  });
  viewRef.current = flat;
  paintRef.current = flat.requestPaint;
  const { canvasRef, containerRef, dragging, fit } = flat;
  useEffect(() => { requestPaint(); }, [annotation.items, annotation.selected, requestPaint]);
  useEffect(() => { handlers.hover(null, null); }, [toolMode, handlers]);

  const capture = useCallback(() => flat.encode("picture"), [flat.encode]);
  // A library card's picture: the first sheet fitted whole, on no background.
  const thumbnail = useCallback(({ width, height }) => new Promise((resolve, reject) => {
    const shown = pictureRef.current;
    const first = shown?.sheets[0];
    if (!first) { reject(new Error("This picture has nothing to show.")); return; }
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    const context = canvas.getContext("2d");
    if (!context) { reject(new Error("The browser cannot draw the picture.")); return; }
    clearSurface(context, { width: canvas.width, height: canvas.height, background: DRAWING_THEME_FALLBACK.light.background });
    const transform = fitTransform([0, -first.height, first.width, 0], canvas.width, canvas.height);
    paintSheets(context, { sheets: [first] }, { transform });
    canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error("The browser could not encode this picture as a PNG."))), "image/png");
  }), []);

  const currentView = useCallback(() => {
    const current = viewRef.current, size = current?.sizeRef.current;
    const camera = current && size ? planCamera(current.transformRef.current, size.width, size.height) : null;
    return camera ? promptView({ camera, width: size.width, height: size.height }) : null;
  }, []);

  const shown = Boolean(picture);
  const alert = useMemo(() => {
    if (workspace.catalogError && !shown) {
      return { severity: "error", kind: "status", title: t("alert.openPictureFailed"), message: t("alert.catalogFailed"),
        recovery: t("alert.catalogRecovery"), details: String(workspace.catalogError), reload: true };
    }
    if (!loaded.error) return null;
    const message = loaded.error instanceof Error ? loaded.error.message : String(loaded.error);
    return { severity: "error", kind: "status", title: t("alert.openPictureFailed"), message, reload: true,
      ...(shown ? { blocking: false } : {}) };
  }, [workspace.catalogError, loaded.error, shown, t]);
  const ready = shown && !loaded.loading && !loaded.updating && !alert;

  // A host asking to select a reference is answered rather than dropped: a picture has none.
  const selectKey = workspace.commands.selectReference?.key ?? null;
  const declinedSelect = useRef(null);
  useEffect(() => {
    if (selectKey === null || declinedSelect.current === selectKey) return;
    declinedSelect.current = selectKey;
    workspace.acknowledgeCommand?.("selectReference", selectKey);
  }, [selectKey, workspace.acknowledgeCommand]);

  // ---- Quick Edit, the keys and the live command surface ------------------------
  const nameReference = useCallback(() => "", []);
  // The ink in the picture's own units: an image's pixels, a PDF's points.
  const annotationDocument = useCallback(items => drawingAnnotationDocument(items, ""), []);
  const runtime = {
    readState: () => ({
      resource: { ...workspace.resource }, revision: String(workspace.resource.revision || ""),
      loading: loaded.loading || loaded.updating, selection: references, camera: null, display: {}
    }),
    setCamera() { throw new Error(PICTURE_NO_CAMERA); },
    resetCamera() { fit(); },
    setDisplaySettings() { throw new Error(PICTURE_NO_DISPLAY); },
    clearSelection() { annotationRef.current.select([]); },
    capture,
    thumbnail
  };
  const handover = useFlatHandover({
    view, data, workspace, file, shown, ready, alert, tools, selection, references, chips, nameReference,
    capture, currentView, annotationDocument, runtime, live: PICTURE_LIVE, captureFailed: t("alert.capturePictureFailed"), fit
  });
  // Nothing draws a picture again from a snapshot packet (`cadgen snapshot` draws CAD files), so a
  // note sends the view itself with its marks, as a PNG the host saves and names by its path,
  // whenever there are marks; else the file alone.
  const host = useViewerHost();
  const fileName = view.file.name;
  const picturePrompt = useMemo(() => ({
    views: () => [],
    files: () => null,
    read: null,
    picture: () => {
      if (!annotationRef.current.items.length) return null;
      const png = capture();
      const save = host.promptFiles?.picture;
      return { png, path: save ? png.then(blob => save({ name: fileName, png: blob })) : null };
    }
  }), [capture, host.promptFiles, fileName]);
  const quickEdit = { ...handover.quickEdit, prompt: picturePrompt };

  // ---- the frame ---------------------------------------------------------------
  const failed = Boolean(alert) && !shown;
  const compact = Boolean(view.appearance?.compact);
  const chromeHidden = loaded.loading || failed;
  // Every flat view's strip, without Measure: a picture has no scale to measure in.
  const flatTools = flatViewTools(tools, { colorScheme, shown, t });
  const strip = flatTools.strip.filter(tool => tool.id !== FLAT_TOOL.MEASURE);
  tools.toolKeys.current = strip;
  const cursor = pointing && !dragging ? "cursor-pointer" : "cursor-default";

  return (
    <FlatViewFrame surface={{ "data-picture-surface": "" }} containerRef={containerRef} busy={loaded.loading || loaded.updating}
      file={file} mobile={mobile} compact={compact} chromeHidden={chromeHidden} loading={loaded.loading} loadingLabel="Reading picture"
      updating={loaded.updating} updateStatus={PICTURE_UPDATE_STATUS} tools={strip} toolRow={annotating ? flatTools.row : null}
      toolStack={handover.toolStack} onToolStackChange={handover.changeToolStack} notice={view.notice} quickEdit={quickEdit}
      alert={alert} cardAlert={handover.cardAlert} alertDismissal={handover.alertDismissal} shown={shown} onReload={view.reload}>
      <canvas ref={canvasRef} aria-label={t("picture.canvas", { name: view.file.name })} role="img" data-picture-tool={toolMode}
        className={cn("absolute inset-0 block touch-none select-none", cursor)} />
      {annotating && shown ? <AnnotationOverlay annotation={annotation} surface={annotationSurface} viewOf={currentView} /> : null}
    </FlatViewFrame>
  );
}

export default function PictureRenderer(props) {
  const { data, ...view } = props;
  return <PictureSurface key={JSON.stringify([view.source.id, view.file.path])} view={view} data={data} />;
}
