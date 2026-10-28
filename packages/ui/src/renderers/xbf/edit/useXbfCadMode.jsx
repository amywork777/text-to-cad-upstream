import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useViewerHost } from "../../../host/context.js";
import { NxIconSprite } from "../../../lib/nxIcons.generated.jsx";
import { editLayoutHost } from "../../../tab-store/editLayoutHost.js";
import { transitionCameraToViewPreset } from "../../kit/camera/runtimeCamera.js";
import { requestSceneFrame } from "../../kit/viewport/sceneFrames.js";
import { XBF_TOOL } from "../tools.js";
import { XBF_SELECT_DEFAULT } from "../XbfSelectionModes.jsx";
import DraftAnalysisLayer from "./DraftAnalysisLayer.jsx";
import EditBrowser, { floatsCard } from "./EditBrowser.jsx";
import EditDimensions from "./EditDimensions.jsx";
import { editLayoutControl } from "./EditLayoutSwitch.jsx";
import EditRibbon from "./EditRibbon.jsx";
import EditSelectionBar from "./EditSelectionBar.jsx";
import EditTimeline from "./EditTimeline.jsx";
import ImportedBody from "./ImportedBody.jsx";
import PreviewLayer from "./PreviewLayer.jsx";
import SketchOverlay from "./SketchOverlay.jsx";
import SketchesLayer from "./SketchesLayer.jsx";
import ValueCallout from "./ValueCallout.jsx";
import { cadChosen, doubleClickLayout, editLayoutState, pendingFaceStep, useEditLayout } from "./editLayout.js";
import {
  ORIGIN_PLANES, STANDARD_VIEWS, editCommand, featureNames, featureTree, mirrorOutline, nextSketchName, notASketch, originAxis,
  planeOutline, rolledBack, selectionDimensions, selectionItems, sizeName, sketchTreeId, sketchView, treeFeatures, treeSketch
} from "./editMode.js";
import { faceChipName, faceNumber, faceReference, shownFaces } from "./faceChips.js";
import { openedFrom, rememberOpenedFrom } from "./openedFrom.js";
import { boundsCorners, facePick, featurePick, mustPutDownTool, quickEditCarries, selectionBarActions, stripDrawingTools } from "./selectionBar.js";
import { chosenThrough, useChosenFeature } from "./selectionBarState.js";
import { isFaceItem, xbfEditReference } from "./selectors.js";
import { useEditMode } from "./useEditMode.js";
import { useEditShortcuts } from "./useEditShortcuts.js";
import { useFaceFeatures } from "./useFaceFeatures.js";
import { useHostFocus } from "./useHostFocus.js";

const EMPTY = Object.freeze([]);
// A file a part's script writes (`useXbfEditLayout`): opened in CAD, the part is shown by its document instead.
const OPENED_AS_FILE = /\.(?:step|stp|xbf)$/i;
// What the part says when the rollback bar's body is gone from the engine, and the bar is rolled to the end.
export const ROLLBACK_GONE = "The body at the rollback bar is no longer in the engine, so the part is shown whole. Move the bar again to see it.";

/**
 * Where a click on a face or an edge puts a hole or ends an extrude (`edit.setFacePoint`): the point clicked, and the
 * face's centre and normal the panel measures it from. The centre is the engine's where it has measured the face, else
 * the middle of what the scene holds of it, so the first click on a face not yet picked keeps its place.
 */
export function facePoint({ scene, tree, hit, facts = null }) {
  const reference = xbfEditReference({ scene, tree, id: hit.id, facts });
  const box = reference?.pickData.center ? null : scene?.selectionBounds?.([hit.id]) || null;
  const center = reference?.pickData.center || (box ? box.min.map((value, axis) => (value + box.max[axis]) / 2) : null);
  return { id: hit.id, point: hit.point, center, normal: reference?.pickData.normal || null };
}

/**
 * How CAD mode lays a document out (`editLayout.js`), from the edit service: whether its part has a
 * script CAD mode edits (`editable`, the probe's answer, so a plain STEP with no script never mounts
 * it), the layout the tab keeps (`layout`, the AI's or CAD's), and so whether the workspace is up
 * (`editing`). The host's switch (Studio's, `tab-store/editLayoutHost.ts`) hears what the view's own
 * would, and nothing once this part leaves the screen; a picture drawn out of sight for the library
 * (`compact`) is not the part on screen.
 *
 * In CAD's layout a part opened as a file its script wrote (a STEP, an .xbf) is shown by its document, built first where the
 * engine holds none, so CAD mode's changes are seen as they build: the file is only what an export wrote once. The host hears
 * of every build the part saw end (`editLayoutHost.reportBuilt`), to list its parts anew.
 *
 * @param {{ client: object | null, file: string, services: object, active: boolean, compact?: boolean }} options
 */
export function useXbfEditLayout({ client, file, services, active, compact = false }) {
  const [layout, setLayout] = useEditLayout(services);
  // A host that switches the layout itself (Studio's Simple view) leaves the view without the switch.
  const hosted = useSyncExternalStore(editLayoutHost.subscribe, editLayoutHost.get, editLayoutHost.get);
  const edit = useEditMode({ client, file, active, reading: layout === "manual" });
  const { editable, busy } = editLayoutState(edit);
  const onScreen = !compact;
  useEffect(() => { if (onScreen) editLayoutHost.reportEditState({ editable, busy }); }, [onScreen, editable, busy]);
  useEffect(() => (onScreen ? () => editLayoutHost.reportEditState(null) : undefined), [onScreen]);
  useEffect(() => { if (onScreen && edit.builds) editLayoutHost.reportBuilt(); }, [onScreen, edit.builds]);
  const openFile = useViewerHost()?.navigation?.openFile;
  const openRef = useRef(openFile);
  openRef.current = openFile;
  const { builtModel } = edit;
  const swap = onScreen && layout === "manual" && Boolean(openFile) && Boolean(edit.model?.id) && OPENED_AS_FILE.test(file);
  useEffect(() => {
    if (!swap) return undefined;
    let gone = false;
    builtModel().then(id => { if (!gone && id) openRef.current?.(id); }, () => {});
    return () => { gone = true; };
  }, [swap, builtModel]);
  return { edit, layout, setLayout, hosted, editable, busy, editing: editable && layout === "manual", cad: cadChosen(layout, edit), onScreen };
}

/**
 * CAD mode on an engine document (`XbfRenderer.jsx`): the edit service's part (`useEditMode`) laid out
 * as a CAD tool lays out its window, over the xbf renderer's own view and selection. It is up where
 * the document's part has a script CAD mode edits and the tab keeps the CAD layout (`useXbfEditLayout`).
 * Up, it gives the shell its toolbar (`ribbon`), design tree (`leftDock`), timeline (`bottomDock`) and
 * the place an open command's dialog floats (`dialogPlace`); the AI | CAD switch is the first of the
 * view's own controls (`layoutControl`) wherever a host does not switch it itself. It reads the
 * renderer's picks as the panels and commands read them (`selectors.js`'s `xbfEditReference`: the
 * engine's refs by number), names a face picked by the feature that made it (`useFaceFeatures`: its
 * chip, the selection bar's Edit, a double-click selecting the feature, the face's menu), and turns
 * Select to what a command picks. The agent's pieces (Pencil and Shapes, Quick Edit, and so Ask, Add to
 * context and Annotate) are the AI layout's alone: the CAD workspace has no agent in it.
 *
 * Over the viewport (`overlay`) it draws on the shell's runtime, whose model group holds the xbf scene:
 * the sketches, an open sketch, a feature's preview, the draft and mass marks, a command's value
 * callout and the drawing's sheet, each in the part's millimetres through the model group's transform,
 * as a STEP's were. The rollback bar's body is a document of its own (`rollback`, its id), which the
 * renderer opens in the part's place. A host that lays the workspace out (Studio's AI | CAD switch,
 * `tab-store/editLayoutHost.ts`) is asked for CAD by a face's double-click laid out for the AI, the
 * face's feature selected once the workspace has read the part, and for the AI by a double-click on
 * empty space in CAD with nothing open (`doubleClickFace`, `doubleClickEmpty`).
 *
 * @param {object} options
 * @param {object} options.view  The renderer's view props (`file.path`, `appearance`).
 * @param {object} options.document  `useWorkspaceDocument`'s: its `client` and `services`.
 * @param {object | null} options.scene  The xbf scene on screen.
 * @param {object} options.tree  `presentXbfTree`'s tree of the scene.
 * @param {boolean} options.assembly  The document places two or more parts.
 * @param {boolean} options.loading  The document has no scene yet and is being read.
 * @param {boolean} options.updating  A new version is loading behind the one on screen.
 * @param {string} options.revision  The version on screen.
 * @param {string[]} options.selectedElementIds  The faces and edges picked (`i0/face/12`), in order.
 * @param {(update: (ids: string[]) => string[]) => void} options.setChosen  The renderer's selection setter.
 * @param {Map<string, object>} options.facts  What the engine measured of each face or edge picked.
 * @param {string} options.toolMode  The tool in hand.
 * @param {boolean} options.previewing  Preview is up.
 * @param {() => void} options.ensureSelect  Takes Select up.
 * @param {(filter: readonly string[]) => void} options.setSelectFilter  Select's filter.
 * @param {{ current: object | null }} options.viewportRef  The viewport the shell gives the overlay.
 * @param {(id: string) => void} options.lookAt  Normal To a face or an edge (`xbfLookAt.js`).
 * @param {((clientX: number, clientY: number) => object | null) | null} [options.pickAt]  What a press at a point of the
 *   view takes, as Select's filter has it (the renderer's `pickAtClient`): Smart Dimension's and Convert Entities' edge.
 * @param {boolean} [options.isolated]  Something is isolated: a double-click on empty space leaves the isolation first.
 */
export function useXbfCadMode({ view, document, scene, tree, assembly, loading, updating, revision, selectedElementIds, setChosen, facts, toolMode,
  previewing, ensureSelect, setSelectFilter, viewportRef, lookAt, pickAt = null, isolated = false }) {
  const host = useViewerHost();
  const file = view.file.path;
  const services = document.services;
  const layout = useXbfEditLayout({ client: document.client, file, services, active: !loading, compact: Boolean(view.appearance?.compact) });
  const { edit, editing, cad, editable, busy: layoutHeld } = layout;
  useEditShortcuts(edit, editing);
  const editTree = useMemo(() => featureTree(edit.state), [edit.state]);
  const editNames = useMemo(() => featureNames(edit.state?.rows || EMPTY), [edit.state?.rows]);
  // A host that opens the part at a line of its script (Studio's References) has the feature there selected once the part is read.
  useHostFocus({ onScreen: layout.onScreen, layout: layout.layout, status: edit.status, tree: editTree, select: edit.select });
  // A command, a sketch or a plane being waited for, or a panel the toolbar opened: the selection bar
  // stays out of them. The feature selected is a pick for the bar only once the person has chosen it.
  const commandOpen = Boolean(edit.command || edit.picking || edit.inspecting);
  const sketchOpen = Boolean(edit.sketch);
  const { chosen: featureChosen, choose: chooseFeature, drop: dropFeature } = useChosenFeature({ editing, held: commandOpen || sketchOpen, file });

  // ---- the picks, as CAD mode reads them --------------------------------------------------------
  const references = useMemo(() => (editing && scene ? selectedElementIds.map(id => xbfEditReference({ scene, tree, id, facts: facts.get(id) || null }))
    .filter(Boolean) : EMPTY), [editing, scene, tree, selectedElementIds, facts]);
  // Which feature made each face picked, as the engine says: on a part's document whose model on screen is the one the
  // edit service read -- not an assembly, not while the rollback bar's body is drawn in its place (`bar.document`), not
  // while a new version loads or the part builds again (the service says those faces are `stale`).
  const partFeatures = editTree.assembly ? EMPTY : editTree.features;
  const building = edit.state?.building;
  const built = !building?.scripts?.length || (!building.error && building.done >= building.scripts.length);
  const facesShown = editing && !assembly && edit.status === "ready" && !edit.bar?.document && !updating && built;
  // The trace's own map of the faces, the geometric one, as each is known before the engine is asked of it (`shownFaces`):
  // only while the part on screen has as many faces as the part the service read, so a model built from another script is
  // never named by its numbers.
  const facesOnScreen = scene && !assembly ? scene.faceCount(0) : 0;
  const traced = useMemo(() => shownFaces({ editing: facesShown, assembly, state: edit.state, bar: edit.bar, updating, rebuilding: false,
    faces: facesOnScreen }), [facesShown, assembly, edit.state, edit.bar, updating, facesOnScreen]);
  const faceNumbers = useMemo(() => [...new Set(references.filter(reference => reference.selectorType === "face")
    .map(reference => faceNumber(faceReference(reference.displaySelector))).filter(Boolean))], [references]);
  const { faces: answered, featureOf } = useFaceFeatures({ client: document.client, file, shown: facesShown,
    version: JSON.stringify([edit.state?.files || null, building?.done ?? 0, revision]), files: edit.state?.files || null, numbers: faceNumbers });
  // What the engine answered for a face stands over the trace's map; a face it was asked of and named nothing for names nothing.
  const faces = useMemo(() => {
    if (!facesShown) return null;
    const map = { ...(traced?.faceFeatures || {}) };
    for (const number of faceNumbers) delete map[String(number)];
    Object.assign(map, answered?.faceFeatures || {});
    return { faceFeatures: map };
  }, [facesShown, traced, answered, faceNumbers]);
  // A row of the design tree under the pointer lights the faces it made, as SolidWorks' FeatureManager does: the faces the
  // map credits it with, on the part (`i0`), lit as picked ones are.
  const litFaces = useMemo(() => {
    const map = faces?.faceFeatures;
    if (!map || edit.sketch || typeof edit.hovered !== "string" || !edit.hovered) return EMPTY;
    const lit = Object.entries(map).filter(([, key]) => key === edit.hovered).map(([number]) => `i0/face/${number}`);
    return lit.length ? lit : EMPTY;
  }, [faces, edit.sketch, edit.hovered]);
  /** Quick Edit's chips, a face's named by the feature that made it, as the design tree numbers it ("Hole1 · face 12"). */
  const nameChips = useCallback(chips => (faces ? chips.map((chip) => {
    const number = Number(chip.compact?.number);
    if (chip.glyph !== "face" || !Number.isSafeInteger(number)) return chip;
    const named = faceChipName({ target: { kind: "face", face: number } }, faces, partFeatures);
    return named ? { ...chip, label: `${named.name} · face ${named.number}`, compact: named } : chip;
  }) : chips), [faces, partFeatures]);

  // ---- Select turned to what a command picks ----------------------------------------------------
  const changeSelectMode = useCallback((picks) => {
    setSelectFilter(picks === "all" ? XBF_SELECT_DEFAULT : picks === "topology" ? ["faces", "edges"] : [picks]);
    ensureSelect();
  }, [setSelectFilter, ensureSelect]);
  const clearPicks = useCallback(() => setChosen(() => EMPTY), [setChosen]);
  // A modeling command opens with Select in hand, its mode turned to what the command picks (a fillet's edges, a hole's
  // face), keeping what is already selected: picked first, then Fillet.
  const startEditCommand = (id) => {
    const command = editCommand(id);
    const picks = command?.picks || (id === "pattern" || command?.sketch || command?.sketches ? "all" : null);
    if (picks) changeSelectMode(picks); else ensureSelect();
    edit.open(id);
  };
  // Sketch, as SolidWorks' Sketch button: on the plane or the flat face already selected, or waiting for one; with a
  // sketch selected in the tree, Edit Sketch.
  const selectedTreeSketch = treeSketch(editTree, edit.selected);
  const openTreeSketch = (sketch) => {
    const shown = sketchView(edit.state, sketch);
    edit.openSketch(shown || { error: notASketch(sketch.title), redraw: { title: sketch.title, file: sketch.file, line: sketch.line } });
  };
  const sketchOnPlane = plane => void edit.startSketch(plane, nextSketchName(editTree), edit.planeOffset);
  const selectedReferencePlane = treeFeatures(editTree).find(feature => feature.id === edit.selected && feature.kind === "Plane") || null;
  const startSketchCommand = () => {
    if (selectedTreeSketch) { openTreeSketch(selectedTreeSketch); return; }
    if (typeof edit.selected === "string" && edit.selected.startsWith("plane:")) { sketchOnPlane(edit.selected.slice("plane:".length)); return; }
    if (selectedReferencePlane) { sketchOnPlane({ feature: selectedReferencePlane.id }); return; }
    const picked = selectionItems(references).filter(isFaceItem);
    if (picked.length === 1 && picked[0].type === "plane") { sketchOnPlane(picked[0]); return; }
    changeSelectMode("faces");
    edit.startPicking();
  };
  // While Sketch waits: a plane picked in the tree, or one flat face on the model, starts the sketch.
  const pickedFaces = edit.picking ? selectionItems(references).filter(isFaceItem) : EMPTY;
  const pickedFace = pickedFaces.length === 1 && pickedFaces[0].type === "plane" ? pickedFaces[0] : null;
  useEffect(() => {
    if (!edit.picking || edit.saving) return;
    if (typeof edit.selected === "string" && edit.selected.startsWith("plane:")) sketchOnPlane(edit.selected.slice("plane:".length));
    else if (selectedReferencePlane) sketchOnPlane({ feature: selectedReferencePlane.id });
    else if (pickedFace) sketchOnPlane(pickedFace);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit.picking, edit.selected, pickedFace?.selector]);
  // Edit Feature on a fillet, a chamfer, a shell or a hole rolls the part back to just before it: Select is in hand,
  // turned to what the feature picks, so others can be picked on that body.
  const repickKey = edit.editing?.rolled ? edit.editing.id : "";
  useEffect(() => {
    const picks = repickKey ? editCommand(edit.editing.command)?.picks : null;
    if (!picks) return;
    clearPicks();
    changeSelectMode(picks);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repickKey]);
  // A sketch opened: what was selected on the model is let go, as the sketch takes the presses.
  const sketchKey = edit.sketch ? `${edit.sketch.file}:${edit.sketch.line}` : "";
  useEffect(() => { if (sketchKey) clearPicks(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sketchKey]);
  // Convert Entities picks the model's edges and faces with the sketch open, Smart Dimension its edges, and Mate the
  // parts' faces and edges: Select turned to them; leaving the tool lets what was picked go.
  const converting = Boolean(edit.sketch) && edit.sketchTool === "convert";
  const dimensioning = Boolean(edit.sketch) && edit.sketchTool === "dimension";
  const mating = editing && edit.inspecting === "mate";
  useEffect(() => {
    if (!converting && !dimensioning && !mating) return undefined;
    changeSelectMode(converting ? "all" : mating ? "topology" : "edges");
    return () => clearPicks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [converting, dimensioning, mating]);

  // ---- a press on the model, as CAD mode takes it -----------------------------------------------
  // Picks add up for a command that takes many, and for Mate's two; a face clicked while Hole is open says where on it
  // the hole goes, an edge clicked while an extrude is open where along it Up To Vertex ends; a click on the
  // background lets go of the feature chosen too.
  const many = editing && !edit.sketch && (Boolean(editCommand(edit.command)?.many) || edit.inspecting === "mate");
  const pointed = editing && ["hole", "extrude", "cut"].includes(edit.command);
  // A face double-clicked laid out for the AI, waiting for CAD's layout and the part read (`pendingFaceStep`, below).
  const pendingFace = useRef(null);
  const beforePick = (hit, multiSelect) => {
    // Every press lets go of a face still waiting for the workspace: the newest one wins.
    pendingFace.current = null;
    if (!editing) return { multiSelect, skip: false };
    if (!hit) { if (!multiSelect) dropFeature(); return { multiSelect: multiSelect || many, skip: false }; }
    if (pointed && (hit.kind === "face" || hit.kind === "edge") && hit.point) {
      edit.setFacePoint(facePoint({ scene, tree, hit, facts: facts.get(hit.id) || null }));
      // Hole adds a hole at each click on its face: a click on the face already picked keeps it.
      if (edit.command === "hole" && selectedElementIds.length === 1 && selectedElementIds[0] === hit.id) return { multiSelect, skip: true };
    }
    return { multiSelect: multiSelect || many, skip: false };
  };
  // While a sketch is edited the presses are the sketch's, but for Convert Entities and Smart Dimension, which take the
  // model's edges.
  const modelPicks = !editing || !edit.sketch || converting || dimensioning;
  // The model's edge under a point of the view, as an edit item (`selectionItems`), or null: what Smart Dimension and Convert
  // Entities ask after while the sketch has the presses.
  const modelEdgeAt = useCallback((clientX, clientY) => {
    const hit = scene ? pickAt?.(clientX, clientY) : null;
    if (hit?.kind !== "edge") return null;
    const reference = xbfEditReference({ scene, tree, id: hit.id, facts: facts.get(hit.id) || null });
    return reference ? selectionItems([reference])[0] || null : null;
  }, [pickAt, scene, tree, facts]);

  // ---- the selection bar and a face's feature ---------------------------------------------------
  // Picking a face, an edge or a feature with Select in hand and no command open offers a small bar beside it: its Edit
  // opens the feature a row is, or the one the engine says made the faces picked. Ask, Add to context and Annotate are
  // the bar's too, where the renderer gives them handlers.
  const barModelPicks = useMemo(() => references.map(reference => ({ kind: reference.selectorType, id: reference.id, reference })), [references]);
  const rowPick = useMemo(() => (featureChosen ? featurePick(editTree, edit.selected) : null), [featureChosen, editTree, edit.selected]);
  const barPicks = barModelPicks.length ? barModelPicks : rowPick ? [rowPick] : EMPTY;
  const faceRow = useMemo(() => (barModelPicks.length ? facePick(editTree, barModelPicks, faces) : null), [barModelPicks, editTree, faces]);
  const selecting = toolMode === XBF_TOOL.SELECT && !previewing;
  const barActions = selecting ? selectionBarActions({ editing, picks: barPicks, commandOpen, sketching: sketchOpen, busy: edit.saving || edit.rolling,
    featureOf: faceRow ? pick => (pick.kind === "face" ? faceRow.id : null) : null }) : EMPTY;
  const rowChosen = barPicks.length === 1 && barPicks[0].kind === "feature" ? barPicks[0] : null;
  const rowEdited = rowChosen || faceRow;
  // The bar beside a feature chosen is put away by Escape, the feature staying selected.
  const featureBarShown = barActions.length > 0 && rowChosen !== null;
  const editRow = () => { if (rowEdited?.sketch) openTreeSketch(rowEdited.sketch); else if (rowEdited) edit.editFeature(rowEdited.feature); };
  const barAnchor = () => {
    if (!barModelPicks.length) {
      const bounds = edit.state?.bounds;
      return boundsCorners(bounds ? { min: bounds[0], max: bounds[1] } : null);
    }
    return barModelPicks.flatMap(({ id }) => boundsCorners(scene?.selectionBounds([id]) || null));
  };
  // The feature that made a face selected and chosen, its dimensions on the model, as SolidWorks' double-click does: as the
  // engine says (`featureOf`, answered at once for a face already asked of, as the first click of the double-click asks);
  // a face whose feature has nothing to open, or that names none, is Normal To, as a STEP's is.
  const selectFaceFeature = (feature) => {
    const row = feature ? featurePick(editTree, feature) : null;
    if (!row?.editable) return false;
    edit.select(row.feature.id);
    chooseFeature();
    return true;
  };
  // In Studio, a part laid out for the AI steps into the workspace on the face double-clicked, and the workspace goes back to the
  // AI on a double-click on empty space with nothing open (`doubleClickLayout`): under Select only. A host that takes no ask
  // (`editLayoutHost.request` false), a plain STEP, an assembly's faces and Jake's own viewer keep their double-click.
  const nothingOpen = !commandOpen && !sketchOpen && !layoutHeld && !isolated;
  const layoutAsked = target => doubleClickLayout({ layout: layout.layout, hosted: layout.hosted, editable, assembly, target, selecting,
    open: !nothingOpen });
  const doubleClickFace = (hit) => {
    if (hit?.kind === "face" && layoutAsked("face") === "manual") {
      const pending = { hit, file, reached: false };
      // A host that says no (a command open in it) leaves the face behind, if it is still the one waiting.
      const refused = () => { if (pendingFace.current === pending) pendingFace.current = null; };
      if (!editLayoutHost.request("manual", { refused })) return false;
      pendingFace.current = pending;
      return true;
    }
    if (!editing || edit.command || edit.sketch || hit?.kind !== "face" || assembly || !facesShown) return false;
    void featureOf(hit.ordinal).then(feature => { if (!selectFaceFeature(feature)) lookAt(hit.id); });
    return true;
  };
  /** A double-click on empty space: back to the AI's layout, where the host takes the ask; true when it was asked. */
  const doubleClickEmpty = () => layoutAsked("empty") === "ai" && editLayoutHost.request("ai");
  // The face waits for CAD's layout and the part read, then has its feature selected, once (`pendingFaceStep`); the next press
  // lets it go too (`beforePick`).
  useEffect(() => {
    const pending = pendingFace.current;
    if (!pending) return;
    const { step, reached } = pendingFaceStep(pending, { layout: layout.layout, file, status: edit.status, editing, faces: Boolean(faces) });
    // Kept on the face itself, which a refusal knows it by.
    pending.reached = reached;
    if (step === "wait") return;
    pendingFace.current = null;
    if (step === "select") void featureOf(pending.hit.ordinal).then(selectFaceFeature);
    // Once per face handed over, on the render that can take it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout.layout, file, editing, edit.status, faces]);
  // SolidWorks' menu on a face: Edit Feature and Edit Sketch of the feature that made it, Normal To a flat one, and Appearance.
  const faceMenu = (hit) => {
    if (!editing || edit.sketch || hit?.kind !== "face") return EMPTY;
    const id = faces?.faceFeatures?.[String(hit.ordinal)];
    const row = id ? featurePick(editTree, id) : null;
    const held = edit.saving || edit.rolling || Boolean(edit.command);
    const items = [];
    if (row?.editable && row.feature?.edit) items.push({ id: "edit-feature", label: "Edit Feature", disabled: held, onSelect: () => edit.editFeature(row.feature) });
    const sketch = row?.feature?.sketch;
    if (sketch?.constrained) items.push({ id: "edit-sketch", label: "Edit Sketch", disabled: held, onSelect: () => openTreeSketch(sketch) });
    if (scene?.elementGeometry(hit.id)?.surface?.type === "plane") items.push({ id: "normal-to", label: "Normal To", onSelect: () => lookAt(hit.id) });
    if (!assembly) items.push({ id: "appearance", label: "Appearance", disabled: held, onSelect: () => edit.inspect("appearance") });
    return items;
  };

  // ---- Escape, innermost first ------------------------------------------------------------------
  // The bar beside a feature chosen, then a command's dialog (cancelled, and what it picked let go with it); the
  // renderer's own layers after.
  const commandHeld = Boolean(edit.command && !edit.sketch);
  const escape = () => {
    if (!editing) return false;
    if (featureBarShown) { dropFeature(); return true; }
    if (commandHeld) { edit.close(); clearPicks(); return true; }
    return false;
  };

  // ---- the view: Normal To and the standard views -----------------------------------------------
  // Normal To outside a sketch, as SolidWorks' Ctrl+8 turns the view: to look straight at the one flat face selected on the
  // model, or the plane selected in the design tree.
  const normalTarget = useMemo(() => {
    if (!editing || edit.sketch) return null;
    const flat = references.filter(reference => reference.selectorType === "face");
    if (flat.length === 1 && flat[0].pickData.surfaceType === "plane" && flat[0].pickData.normal) return flat[0].pickData.normal;
    const origin = typeof edit.selected === "string" && edit.selected.startsWith("plane:")
      ? { Top: [0, 0, 1], Front: [0, -1, 0], Right: [1, 0, 0] }[edit.selected.slice("plane:".length)] : null;
    return origin || treeFeatures(editTree).find(feature => feature.id === edit.selected && feature.kind === "Plane")?.plane?.z || null;
  }, [editing, edit.sketch, references, edit.selected, editTree]);
  const normalTargetRef = useRef(normalTarget);
  normalTargetRef.current = normalTarget;
  const turnTo = (direction, up) => {
    const runtime = viewportRef.current?.runtimeRef.current;
    if (!runtime?.THREE || !runtime.modelGroup) return;
    const { THREE, modelGroup } = runtime;
    modelGroup.updateMatrixWorld();
    const origin = new THREE.Vector3(0, 0, 0).applyMatrix4(modelGroup.matrixWorld);
    const toward = axis => new THREE.Vector3(...axis).applyMatrix4(modelGroup.matrixWorld).sub(origin).normalize().toArray();
    if (transitionCameraToViewPreset(runtime, { direction: toward(direction), up: toward(up) })) {
      runtime.userMovedCamera = true;
      requestSceneFrame(runtime, false);
    }
  };
  useEffect(() => {
    const normal = normalTargetRef.current;
    if (!edit.normalTo || edit.sketch || !normal) return;
    turnTo(normal, Math.abs(normal[2]) < 0.9 ? [0, 0, 1] : [0, 1, 0]);
    // Once per Normal To asked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit.normalTo]);
  // A standard view asked from the keyboard (Ctrl+1 to Ctrl+7), turned to as the view cube turns to its faces.
  useEffect(() => {
    const preset = STANDARD_VIEWS[edit.standardView?.name];
    if (preset) turnTo(preset.direction, preset.up);
    // Once per view asked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit.standardView?.tick]);

  // ---- Open Part, and back to the assembly ------------------------------------------------------
  // Open Part, on a part of an assembly: its own model shown in this view, by its document's id (or the STEP it writes),
  // to be modeled there. A host that shows one file alone has none.
  const openFile = host?.navigation?.openFile;
  const assemblyTitle = sizeName(edit.state?.name || "");
  const openPart = useMemo(() => (openFile ? (component) => {
    const target = component?.document || component?.step;
    if (!target) return;
    rememberOpenedFrom(services, target, { file, title: assemblyTitle || "the assembly" });
    openFile(target);
  } : null), [openFile, file, assemblyTitle, services]);
  const backTo = useMemo(() => {
    const from = openFile ? openedFrom(services.preferences, file) : null;
    return from ? { title: from.title, open: () => openFile(from.file) } : null;
  }, [openFile, file, services.preferences]);

  // ---- the frame --------------------------------------------------------------------------------
  // The place beside the design tree where an open command's or sketch's panel floats in a card of its own.
  const [commandCard, setCommandCard] = useState(null);
  const deselect = useCallback(id => setChosen(now => now.filter(each => each !== id)), [setChosen]);
  const editWithRows = chosenThrough(edit, chooseFeature);
  // A feature below the rollback bar is not on the model: its dimensions are not drawn.
  const dimensions = useMemo(() => (edit.status === "ready" && !edit.sketch && !rolledBack(editTree, edit.bar).has(edit.selected)
    ? selectionDimensions(edit.state, editTree, edit.selected) : EMPTY), [edit.status, edit.state, editTree, edit.selected, edit.sketch, edit.bar]);
  // A plane or the origin the design tree selects, or has under its pointer, drawn on the model; all three while the
  // Sketch command waits for one; Mirror's, a draft's and a new plane's while their panel is open.
  const planes = useMemo(() => {
    const referencePlane = id => treeFeatures(editTree).find(feature => feature.id === id && feature.kind === "Plane" && feature.plane)?.plane;
    const drawn = (edit.sketch ? [] : [...(edit.picking ? ORIGIN_PLANES.map(plane => [`plane:${plane}`, false]) : []),
      [edit.selected, true], [edit.hovered, false]]).flatMap(([id, strong]) => {
      const reference = typeof id === "string" && !id.startsWith("plane:") ? referencePlane(id) : null;
      const points = typeof id === "string" && id.startsWith("plane:") ? planeOutline(id.slice("plane:".length), edit.state?.bounds)
        : reference ? mirrorOutline({ center: reference.origin, normal: reference.z }, edit.state?.bounds) : null;
      return points ? [{ points, strong }] : [];
    });
    const mark = edit.preview?.mark;
    const mirrored = ((edit.command === "mirror" || edit.command === "split") && mark === "mirror") || (edit.command === "draft" && mark === "draft")
      || (edit.command === "plane" && mark === "plane") ? mirrorOutline(edit.preview, edit.state?.bounds) : null;
    return mirrored ? [...drawn, { points: mirrored, strong: true }] : drawn;
  }, [edit.selected, edit.hovered, edit.picking, edit.sketch, edit.state?.bounds, edit.command, edit.preview, editTree]);
  const origin = !edit.sketch && (edit.selected === "origin" || edit.hovered === "origin") ? originAxis(edit.state?.bounds) : null;

  /** The strip as CAD mode has it: the CAD workspace chosen has no agent, so no Pencil or Shapes (which write to it). */
  const drawingTools = useCallback(drawing => stripDrawingTools({ cad, drawing }), [cad]);
  // Pencil or Shapes in hand when the CAD workspace is chosen is put down for Select.
  const putDown = mustPutDownTool({ cad, toolMode });
  useEffect(() => { if (putDown) ensureSelect(); }, [putDown, ensureSelect]);
  /** What Quick Edit is handed: the AI layout's picks, and in the CAD workspace chosen no box at all (it has no agent). */
  const quickEdit = ({ references: carried, chips }) => quickEditCarries({ cad, open: true, carried: { references: carried, chips }, empty: EMPTY });

  const frame = {
    // The edit chrome's icons, and the CAD workspace's Select and Measure, are drawn from the generator's sprite, which the frame mounts once.
    iconSprite: <NxIconSprite />,
    layoutControl: editable && !layout.hosted ? editLayoutControl({ value: layout.layout, onChange: layout.setLayout, disabled: layoutHeld }) : null,
    ribbon: editing ? (stripTools, shown) => <EditRibbon tools={stripTools} view={shown} edit={edit} onCommand={startEditCommand} onSketch={startSketchCommand}
      sketchLabel={selectedTreeSketch ? "Edit Sketch" : "Sketch"} canOpenParts={Boolean(openPart)} onNormalTo={normalTarget ? edit.lookNormalTo : null} /> : null,
    leftDock: editing ? <EditBrowser edit={editWithRows} names={editNames} tree={editTree} references={references} onEditSketch={openTreeSketch}
      onPlane={sketchOnPlane} onOpenPart={openPart} backTo={backTo} card={commandCard} onDeselect={deselect} /> : null,
    bottomDock: editing ? <EditTimeline edit={editWithRows} tree={editTree} onEditSketch={openTreeSketch} /> : null,
    dialogPlace: editing ? setCommandCard : null,
    dialogOpen: editing && floatsCard(edit),
  };

  // ---- what is drawn on the model ---------------------------------------------------------------
  // The sketches drawn on the model while none is edited: those nothing uses yet, the one selected in the tree, and the one an
  // extrude or a revolve previews (a reopened feature's own).
  const previewedSketch = edit.preview?.file ? edit.preview : null;
  const previewedSketches = edit.preview?.mark === "picked" ? edit.preview.sketches : null;
  const shownSketches = useMemo(() => (edit.sketch ? EMPTY : (edit.state?.sketches || EMPTY).filter(shown => shown.state
    && (shown.consumed === null || (selectedTreeSketch && shown.file === selectedTreeSketch.file && shown.line === selectedTreeSketch.line)
      || (previewedSketch && shown.file === previewedSketch.file && shown.line === previewedSketch.line)
      || (previewedSketches || []).some(each => shown.file === each.file && shown.line === each.line)))),
  [edit.sketch, edit.state?.sketches, selectedTreeSketch, previewedSketch, previewedSketches]);
  // A sketch is picked on the model as in the design tree, with Select in hand and nothing else asking for a pick: the sketch
  // an extrude takes (inside its outline too, while it waits for one), or one to work on next; a sweep's or a loft's
  // sketches one after another. The part's extent is how far Through All goes in a preview.
  const sketchFeature = Boolean(edit.command && (editCommand(edit.command)?.sketch || editCommand(edit.command)?.sketches));
  const takesSketches = Boolean(edit.command && editCommand(edit.command)?.sketches);
  const sketchesPickable = editing && selecting && !edit.sketch && !edit.picking && !edit.editing && (!edit.command || sketchFeature);
  const selectEdit = edit.select;
  const pickSketch = useCallback((shown) => {
    const id = sketchTreeId(editTree, shown);
    if (id) { selectEdit(id); chooseFeature(); }
  }, [editTree, selectEdit, chooseFeature]);
  const partBounds = edit.state?.bounds;
  const partExtent = partBounds ? Math.hypot(...partBounds[1].map((value, axis) => value - partBounds[0][axis])) : 0;
  // Mass Properties' center of mass, marked on the model while its card is open.
  const massCenter = edit.mass?.center;
  const massMark = useMemo(() => (massCenter ? { mark: "center", at: massCenter } : null), [massCenter]);
  const units = edit.state?.units || "";
  const colorScheme = view.appearance?.colorScheme === "dark" ? "dark" : "light";
  // The rollback bar's body, a document of its own the renderer opens by its id in the part's place while the bar is up.
  const rollback = editing && typeof edit.bar?.document?.id === "string" ? edit.bar.document.id : "";
  /** The bar's body is gone from the engine (it answered 404 for it): the bar is rolled to the end, and the part says why. */
  const rollbackGone = () => { if (rollback) edit.dropBar(ROLLBACK_GONE); };
  // The dimensions layer only while it has something to draw: a feature's sizes, a plane or the origin, or a choice to make.
  const dimensionsShown = dimensions.length > 0 || planes.length > 0 || Boolean(origin) || Boolean(edit.choice);

  /**
   * CAD mode's layers over the viewport, on the shell's runtime (the model group the xbf scene is in): the selection bar beside a
   * pick, the feature selected's dimensions and planes, the sketches, an open sketch, a feature's preview and its value callout,
   * and the inspections' marks. Each is mounted only while it has something to draw, and
   * paints when the view is drawn, never per frame at rest. A STEP brought in with no part script is offered as a part to
   * model on, in either layout (the switch has nothing to switch on it).
   */
  const overlay = viewport => <>
    {editing ? <>
      {barActions.length ? <EditSelectionBar viewport={viewport} actions={barActions} anchor={barAnchor}
        anchorKey={barPicks.map(pick => `${pick.kind}:${pick.id}`).join(",")}
        editKind={rowEdited?.sketch ? "Sketch" : rowEdited?.feature.kind} editHint={rowEdited?.sketch ? "Edit Sketch" : "Edit Feature"}
        onEdit={rowEdited ? editRow : undefined} /> : null}
      {edit.command && edit.callout ? <ValueCallout viewport={viewport} callout={edit.callout} /> : null}
      {dimensionsShown ? <EditDimensions viewport={viewport} dimensions={dimensions} units={units}
        // Held while a command's dialog is open, as its sizes are the dialog's, which Cancel puts back.
        disabled={edit.saving || Boolean(edit.command)} planes={planes} origin={origin}
        choice={edit.choice} onChange={(dimension, text) => void edit.change({ dimension: dimension.id, text })}
        onChoose={edit.choose} onDismissChoice={edit.dismissChoice} /> : null}
      {edit.sketch ? <SketchOverlay viewport={viewport} edit={edit} units={units} modelEdgeAt={modelEdgeAt} /> : null}
      {shownSketches.length ? <SketchesLayer viewport={viewport} sketches={shownSketches} selected={previewedSketches || selectedTreeSketch}
        onPick={sketchesPickable ? pickSketch : null} profiles={sketchFeature && (!selectedTreeSketch || takesSketches)} preview={edit.preview}
        onEdit={sketchesPickable && !edit.command ? shown => openTreeSketch({ file: shown.file, line: shown.line, title: shown.name }) : null}
        through={partExtent} /> : null}
      {edit.inspecting === "mass" && massMark ? <PreviewLayer viewport={viewport} preview={null} mark={massMark} extent={partExtent} /> : null}
      {edit.inspecting === "draft" && edit.draftCheck?.positions ? <DraftAnalysisLayer viewport={viewport} check={edit.draftCheck} /> : null}
      {edit.inspecting === "interference" && edit.interference?.shown
        ? <PreviewLayer viewport={viewport} preview={edit.interference.shown} mark={null} extent={partExtent} /> : null}
      {/* Compare: what the part gained since the version picked, and what it lost. */}
      {edit.inspecting === "compare" && edit.comparison?.shown
        ? <PreviewLayer viewport={viewport} preview={edit.comparison.shown} mark={null} extent={partExtent} /> : null}
      {edit.command && (edit.featurePreview || ["pattern", "hole", "draft", "plane"].includes(edit.preview?.mark))
        ? <PreviewLayer viewport={viewport} preview={edit.featurePreview} mark={edit.preview?.mark ? edit.preview : null} extent={partExtent} />
        : null}
    </> : null}
    {edit.status === "none" && edit.imported && openFile
      ? <ImportedBody imported={edit.imported} onAdopt={edit.adopt} onOpenPart={edit.importedPart} onOpen={openFile} /> : null}
  </>;

  return {
    edit, editing, cad, editable, frame, overlay, references, faces, litFaces, nameChips, drawingTools, quickEdit,
    beforePick, modelPicks, doubleClickFace, doubleClickEmpty, faceMenu, escape, escapeActive: editing && (featureBarShown || commandHeld),
    rollback, rollbackGone,
    // The units the part reads in, which Measure reads in too, as SolidWorks' does.
    units: editing ? edit.state?.units || "" : ""
  };
}
