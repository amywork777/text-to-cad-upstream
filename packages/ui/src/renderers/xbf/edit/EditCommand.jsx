import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetCheckboxRow,
  FileSheetControlRow,
  FileSheetSelectRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import {
  chooseLine,
  chooseSteps,
  clickOffsets,
  commandBlocked,
  edgeAxis,
  commandDefaults,
  commandRequest,
  draftPreview,
  draftReversed,
  planeAt,
  planePreview,
  referencePlanes,
  editCommand,
  editingValues,
  extrudeEnd,
  extrudePreview,
  faceOffsetAxes,
  holePreview,
  midPlanePreview,
  mirrorPreview,
  REPICKS,
  partSide,
  patternAxis,
  patternPreview,
  plainNumber,
  revolveAxes,
  revolveSweep,
  sameValues,
  selectionItems,
  selectionLabel,
  sizeName,
  sketchView,
  treeSketch, planeMode } from "./editMode.js";
import { COMMAND_ICONS } from "./cadIcons.jsx";
import { HOLE_STANDARDS, defaultSize, holeFill, holeFits, holeSizeOptions } from "./holeSizes.js";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { booleanOf, nxCommand } from "./nx.js";
import { sketchGeometry } from "./sketchMode.js";
import { isEdgeItem, isFaceItem } from "./selectors.js";
// An extrude's end conditions, as SolidWorks' Direction 1 names them and in its order; a cut can go through all.
// The end conditions as SolidWorks names them.
const END = Object.freeze({ blind: "Blind", through: "Through All", next: "Up To Next", vertex: "Up To Vertex", surface: "Up To Surface",
  mid: "Mid Plane" });
// NX's Boolean, for the commands that add material or take the same shape away (`nx.js`).
// A Boss/Base or a Cut: the switch between them, carrying what was typed and picked.
const BOOLEAN_OPTIONS = Object.freeze([{ value: "unite", label: "Boss/Base" }, { value: "subtract", label: "Cut" }]);
// What a dialog switching its Boolean hands the dialog opening for the other command: the values
// typed so far and the sketches picked, read as that one opens (`to`, its command).
let carry = null;
const ends = values => Object.freeze(values.map(value => ({ value, label: END[value] })));
const BOSS_ENDS = ends(["blind", "next", "vertex", "surface", "mid"]);
const CUT_ENDS = ends(["blind", "through", "next", "vertex", "surface", "mid"]);
// A revolve's Revolve Type: one way, or half each way.
const REVOLVE_ENDS = ends(["blind", "mid"]);
// Direction 2's: Blind, and Through All for a cut.
const BOSS_ENDS2 = ends(["blind"]);
const CUT_ENDS2 = ends(["blind", "through"]);
// The end conditions with no depth of their own: the body or what is picked says how far.
const NO_DEPTH = new Set(["through", "next", "vertex", "surface"]);
// Hole Wizard's types: a plain hole, one with a counterbore or a countersink for a screw's head, or
// one drilled for a tap.
const HOLE_TYPES = Object.freeze([{ value: "simple", label: "Hole" }, { value: "counterbore", label: "Counterbore" },
  { value: "countersink", label: "Countersink" }, { value: "tapped", label: "Straight Tap" }]);
// A hole whose sizes are the engineer's own, typed rather than a standard screw's.
const CUSTOM = "custom";
const UNIT_MARKS = Object.freeze({ mm: "mm", in: "in" });
// Chamfer's types, as SolidWorks' Chamfer names them.
const CHAMFER_TYPES = Object.freeze([{ value: "equal", label: "Equal distance" }, { value: "distances", label: "Distance distance" },
  { value: "angle", label: "Angle distance" }]);
// The origin's planes a draft's neutral plane can be, as the design tree names them.
const ORIGIN_PLANE_NAMES = new Set(["Top", "Front", "Right"]);
const LISTED = 8;
// The origin's planes Mirror goes about, by their axes, named as the design tree names them.
const PLANES = Object.freeze([{ value: "XZ", label: "Front Plane" }, { value: "XY", label: "Top Plane" }, { value: "YZ", label: "Right Plane" }]);
const PATTERNS = Object.freeze([{ value: "linear", label: "Linear" }, { value: "circular", label: "Circular" }]);
const SPLIT_KEEPS = Object.freeze([{ value: "both", label: "Both bodies" }, { value: "top", label: "The side the plane faces" },
  { value: "bottom", label: "The side behind the plane" }]);
const BODY_MODES = Object.freeze([{ value: "delete", label: "Delete Bodies" }, { value: "keep", label: "Keep Bodies" }]);
// The axes a plane At angle turns about: its own.
const CURVE_ENDS = Object.freeze([{ value: "start", label: "Its start" }, { value: "end", label: "Its end" }]);
const TURN_AXES = Object.freeze([{ value: "x", label: "Its X axis" }, { value: "y", label: "Its Y axis" }]);
const DIRECTIONS = Object.freeze([{ value: "X", label: "Along X" }, { value: "Y", label: "Along Y" }, { value: "Z", label: "Along Z" }]);
// A mirror Edit Feature reopens that was made about a face of the part: that face again.
const SAME_FACE = Object.freeze({ value: "face", label: "Same face" });
// Thin Feature's wall, as SolidWorks' Thin Feature sets it: inside the outline, outside it, or astride it.
const THIN_SIDES = Object.freeze([{ value: "inside", label: "Inside" }, { value: "outside", label: "Outside" }, { value: "mid", label: "Mid-Plane" }]);
// How long the panel waits after a change before asking for its preview: picks and values that
// come together are asked for once.
const PREVIEW_WAIT_MS = 250;

/**
 * Hole Wizard's other positions, as its Positions tab lists the points it drills at: each hole's
 * place from the face's center, typed over, and an X to take it out.
 */
function OtherHoles({ places, axes, units, disabled, onChange, onRemove }) {
  return places.map((place, index) => {
    const name = `Hole ${index + 2}`;
    return <FileSheetControlRow key={index} label={name} trailing={<span className="flex shrink-0 items-center gap-1">
      {axes.map(axis => <FileSheetValueInput key={axis} value={place[axis] ?? "0"} ariaLabel={`${name} ${axis.toUpperCase()}`} disabled={disabled}
        className="w-14" onValueCommit={draft => onChange(index, axis, String(draft).trim())} />)}
      <span className="w-6 text-micro text-muted-foreground">{units}</span>
      <button type="button" aria-label={`Remove ${name}`} disabled={disabled}
        className="flex size-4 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent/70 hover:text-foreground"
        onClick={() => onRemove(index)}><X className="size-3" aria-hidden="true" /></button>
    </span>} />;
  });
}

/** A number the command takes, typed over as the design tree's are, with its unit. */
function NumberRow({ label, value, unit = "", disabled, onChange }) {
  return <FileSheetControlRow label={label} trailing={<span className="flex shrink-0 items-center gap-1">
    <FileSheetValueInput value={value} ariaLabel={label} disabled={disabled} onValueCommit={draft => onChange(String(draft).trim())} />
    <span className="w-4 text-micro text-muted-foreground">{UNIT_MARKS[unit] || unit}</span>
  </span>} />;
}

/**
 * A selection box as SolidWorks' PropertyManager draws one: what the command acts on, each marked
 * in the blue the model shows it picked in, with an X to let it go (`onClear`, given the item);
 * empty, it waits in that blue for a pick and says how to pick.
 */
export function SelectionBox({ items, prompt, more = 0, onClear = null, clearLabel = "Clear" }) {
  if (!items.length) {
    return <p role="status" className="mx-2 mb-1 rounded-md border border-dashed border-cad-picked/70 bg-cad-picked/5 px-2 py-1.5 text-tiny leading-4 text-foreground">
      {prompt}</p>;
  }
  return <ul aria-label="Selected" className="mx-2 mb-1 flex flex-col rounded-md border border-cad-picked/60 px-2 py-1 text-tiny leading-5 text-foreground">
    {items.map(item => <li key={item.key} className="flex min-w-0 items-center gap-1.5">
      <span className="size-2 shrink-0 rounded-full bg-cad-picked" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {onClear ? <button type="button" aria-label={`${clearLabel} ${item.label}`} className="flex size-4 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent/70 hover:text-foreground"
        onClick={() => onClear(item)}><X className="size-3" aria-hidden="true" /></button> : null}
    </li>)}
    {more > 0 ? <li className="pl-3.5 text-muted-foreground">{`and ${more} more`}</li> : null}
  </ul>;
}

/**
 * What the command acts on: the faces and edges selected on the model, listed, or how to select
 * them; with `onRemove`, each taken out by its X (given its selector), as a click on it does.
 */
export function SelectionList({ items, prompt, onRemove = null }) {
  const shown = items.slice(0, LISTED);
  return <SelectionBox items={shown.map(item => ({ key: item.selector, label: selectionLabel(item) }))} prompt={prompt}
    more={items.length - shown.length} onClear={onRemove ? item => onRemove(item.key) : null} clearLabel="Remove" />;
}

/** What a preview draws, by its colour: amber for material added, red for material taken away. */
function PreviewKey({ added, removed }) {
  const swatch = (tone, text) => <span className="flex items-center gap-1.5">
    <span className={`size-2 shrink-0 rounded-sm ${tone}`} aria-hidden="true" />{text}</span>;
  return <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} flex flex-col gap-0.5 pb-1`}>
    {added ? swatch("bg-cad-solid", "Material it adds") : null}
    {removed ? swatch("bg-cad-cut", "Material it takes away") : null}
  </p>;
}

/** What a reopened feature acts on, kept as it is: "4 edges", with how to pick others. */
function KeptList({ text, hint }) {
  return <>
    <SelectionBox items={[{ key: "kept", label: text }]} prompt="" />
    <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{hint}</p>
  </>;
}

/**
 * A modeling command's panel, as SolidWorks' PropertyManager, in a card of its own over the model
 * (`EditBrowser.jsx`): OK and Cancel in its title row, a green check and a red cross; what it acts
 * on in selection boxes (the faces or edges selected on the model, the
 * sketch an extrude takes, picked on the model or in the design tree, or the history feature it
 * copies); and its inputs in the part's units. OK writes the command's line into the part's script
 * (`cadgen/edit`) and the new feature is selected in the history below; Cancel, or Escape, leaves
 * the script as it was.
 *
 * Choose, as SolidCraft's feature dialogs walk through their inputs: a line under the title names
 * the pick still wanted ("1 of 2: Select a sketch"), then says to review the preview and press OK. A
 * box that takes many (a fillet's edges) takes each click on the model as one more, or one fewer,
 * and each pick listed has an X (`onDeselect`, given the reference's id).
 *
 * Preview, while its switch is on: an extrude or a revolve is swept on the model at once, with an
 * arrow the way it goes and its depth or angle (`edit.preview`); any other command, once it has
 * what it needs, is made by the server without being written and drawn over the model
 * (`edit.previewFeature`), its key and its state below, with the way it goes drawn too where it
 * has one (a linear pattern's, a hole's into its face, a mirror's plane).
 *
 * Reopened by Edit Feature (`edit.editing`), it opens with the feature's values and keeps what the
 * feature acts on (a fillet's edges, a hole's face), unless others are picked on the body as it was
 * before it, which the view shows while the panel is open; its OK writes the feature's line again.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>,
 *   names: ReturnType<typeof import("./editMode.js").featureNames>, references: object[],
 *   onDeselect?: ((referenceId: string) => void) | null }} props
 */
export default function EditCommand({ edit, names, references, tree = null, onDeselect = null }) {
  const command = editCommand(edit.command);
  const units = edit.state?.units || "mm";
  const editing = edit.editing?.command === edit.command ? edit.editing : null;
  // Values handed over by the Boolean's other command, as this dialog opened.
  const [carried] = useState(() => (carry?.to === edit.command ? carry : null));
  useEffect(() => { if (carry === carried) carry = null; }, [carried]);
  const opened = useMemo(() => {
    const base = editing ? editingValues(editing, units) : commandDefaults(edit.command, units);
    // Carried over: what both commands have.
    return carried ? { ...base, ...Object.fromEntries(Object.entries(carried.values).filter(([key]) => key in base)) } : base;
  }, [editing, edit.command, units, carried]);
  const [values, setValues] = useState(opened);
  useEffect(() => { setValues(opened); }, [opened]);
  // The sketch an extrude makes a solid of: the one selected in the design tree, or the feature's
  // own when it is reopened. One on a face of the part cuts into it, as SolidWorks' Extruded Cut does.
  const sketch = command?.sketch ? (editing ? editing.sketch : treeSketch(tree, edit.selected)) : null;
  // A cut goes into the part: reversed when the part lies behind the sketch's plane (a sketch on a
  // face of it, or on a plane over it), as a cut from a face goes in.
  const side = sketch ? partSide(sketchView(edit.state, sketch), edit.state?.bounds) : 0;
  const onFace = sketch ? (sketchView(edit.state, sketch)?.plane || sketch.plane) === "Plane" : false;
  const intoPart = side !== 0 ? side < 0 : onFace;
  useEffect(() => { if (edit.command === "cut" && !editing) setValues(current => ({ ...current, reverse: intoPart })); }, [edit.command, intoPart, editing]);
  // A sweep's profile and path (two boxes, each its own: either may be empty), a loft's profiles
  // (a list): each sketch picked in turn, on the model or in the design tree, as SolidWorks' boxes
  // take them, in order; a reopened feature keeps its own.
  const takes = command?.sketches || null;
  const [picked, setPicked] = useState(() => carried?.picked || (editing?.sketches || []).map(each => ({ ...each, title: each.name, constrained: true })));
  const selectedSketch = takes && !editing ? treeSketch(tree, edit.selected) : null;
  useEffect(() => {
    if (!selectedSketch) return;
    setPicked(current => {
      if (current.some(each => each && each.file === selectedSketch.file && each.line === selectedSketch.line)) return current;
      if (takes === "many") return [...current, selectedSketch];
      // A sweep's first empty box takes it; both full, the path is picked again.
      const boxes = [current[0] || null, current[1] || null];
      const empty = boxes.indexOf(null);
      return empty < 0 ? [boxes[0], selectedSketch] : boxes.map((each, index) => (index === empty ? selectedSketch : each));
    });
  }, [selectedSketch?.file, selectedSketch?.line]); // eslint-disable-line react-hooks/exhaustive-deps
  const extruding = edit.command === "extrude" || edit.command === "cut";
  // A revolve turns about a line of its sketch: its centerline, as it opens, when it has one.
  const revolving = edit.command === "revolve" || edit.command === "revolve_cut";
  const axes = useMemo(() => (revolving && sketch ? revolveAxes(sketchView(edit.state, sketch)) : []), [revolving, sketch, edit.state]);
  const firstAxis = axes[0]?.value || "";
  useEffect(() => {
    if (revolving) setValues(current => (axes.some(axis => axis.value === current.axis) ? current : { ...current, axis: firstAxis }));
  }, [revolving, axes, firstAxis]);
  const items = useMemo(() => selectionItems(references), [references]);
  const rows = edit.state?.rows || [];
  const featureIndex = rows.findIndex(row => row.key === edit.selected);
  // A feature picked in the history is what Mirror and Pattern copy; the first one is the body.
  const [wholeBody, setWholeBody] = useState(featureIndex <= 0);
  useEffect(() => { setWholeBody(featureIndex <= 0); }, [featureIndex, edit.command]);
  // A straight edge picked while Pattern is open sets a linear one's direction, as SolidWorks'
  // Direction 1 takes an edge; a circular one turns about it, or about a round face's axis.
  const pickedAxis = edit.command === "pattern" ? edgeAxis(references) : null;
  useEffect(() => { if (pickedAxis) setValues(current => (current.type === "linear" ? { ...current, direction: pickedAxis } : current)); }, [pickedAxis]);
  // A click on the hole's face puts a hole there, its distance from the face's center, as Hole
  // Wizard's Positions place a hole at each click: the first click on a face starts its holes there,
  // each click after it on that face adds one. Edit Feature's clicks add to the holes it has.
  const { facePoint } = edit;
  const clickedFace = useRef(null);
  useEffect(() => {
    if (edit.command !== "hole" || !facePoint) return;
    const moved = clickOffsets(facePoint.point, facePoint.center, facePoint.normal, units);
    const adds = clickedFace.current === null ? Boolean(editing) : clickedFace.current === facePoint.id;
    clickedFace.current = facePoint.id;
    if (!moved) return;
    setValues(current => (adds ? { ...current, more: [...(current.more || []), moved] } : { ...current, ...moved, more: [] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facePoint, edit.command, units]);
  // Up To Vertex: the end of the edge nearest where it was clicked.
  useEffect(() => {
    if ((edit.command === "extrude" || edit.command === "cut") && facePoint?.point) setValues(current => ({ ...current, vertex_at: facePoint.point }));
  }, [facePoint, edit.command]);
  const { setPreview, previewFeature } = edit;
  const previewOn = edit.previewOn !== false;
  const disabled = edit.saving || edit.status !== "ready";
  const faces = items.filter(item => isFaceItem(item));
  const listed = command?.picks === "edges" ? items : faces;
  // A draft's neutral plane, as SolidWorks' Draft takes it: while its box is empty, the next face
  // clicked on the model goes there (a flat one), held apart from the faces it drafts; a plane
  // clicked in the design tree goes there at any time. It starts with the part narrowing away
  // from it, the direction of pull into the part, which Reverse direction turns.
  const drafting = edit.command === "draft";
  const [neutralFace, setNeutralFace] = useState(null);
  const [neutralNote, setNeutralNote] = useState("");
  const waitingNeutral = drafting && !values.neutral;
  const seenFaces = useRef(null);
  const facesKey = faces.map(item => item.selector).join(",");
  useEffect(() => {
    if (!drafting) { seenFaces.current = null; return; }
    const before = seenFaces.current;
    seenFaces.current = new Set(faces.map(item => item.selector));
    if (!before || !waitingNeutral) return;
    const added = references.filter(reference => reference?.selectorType === "face"
      && !before.has(String(reference.displaySelector || reference.normalizedSelector || "")));
    const last = added.at(-1);
    if (!last) return;
    onDeselect?.(last.id);
    const [item] = selectionItems([last]);
    if (item.type !== "plane") { setNeutralNote("The neutral plane is a flat face. Select a flat one."); return; }
    setNeutralNote("");
    setNeutralFace({ item, pick: last.pickData || null });
    setValues(current => ({ ...current, neutral: "face", reverse: true }));
  }, [drafting, facesKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const planing = edit.command === "plane";
  // Which Plane what is picked makes (`planeMode`), and what it is picked on.
  const planeKind = planing ? planeMode(items, editing) : "offset";
  const planeRefs = planing ? items.filter(item => (isFaceItem(item) || isEdgeItem(item))) : [];
  const treePlane = (drafting || planing) && typeof edit.selected === "string" && edit.selected.startsWith("plane:")
    ? edit.selected.slice("plane:".length) : "";
  // The part's reference planes (Plane1): one clicked in the tree is a draft's neutral plane or
  // another plane's reference, as an origin plane is; Mirror lists them to mirror about.
  const planes = useMemo(() => referencePlanes(tree), [tree]);
  const namedPlane = value => planes.find(each => each.value === value) || null;
  const pickedPlane = drafting || planing ? planes.find(each => each.id === edit.selected) || null : null;
  useEffect(() => {
    if (!pickedPlane) return;
    if (planing) { setValues(current => ({ ...current, reference: pickedPlane.value })); return; }
    setNeutralFace(null);
    setNeutralNote("");
    setValues(current => ({ ...current, neutral: pickedPlane.value, reverse: draftReversed(null, edit.state?.bounds, pickedPlane.plane) }));
  }, [pickedPlane?.value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!ORIGIN_PLANE_NAMES.has(treePlane)) return;
    // A Plane's first reference; a draft's neutral plane.
    if (planing) { setValues(current => ({ ...current, reference: treePlane })); return; }
    setNeutralFace(null);
    setNeutralNote("");
    setValues(current => ({ ...current, neutral: treePlane, reverse: draftReversed(treePlane, edit.state?.bounds) }));
  }, [treePlane]); // eslint-disable-line react-hooks/exhaustive-deps
  const clearNeutral = () => {
    setNeutralFace(null);
    setValues(current => ({ ...current, neutral: "" }));
    if (treePlane) edit.select(null);
  };
  // What the command acts on: the faces and edges picked, and a draft's neutral face beside them.
  const acted = drafting && neutralFace ? [...items, { ...neutralFace.item, neutral: true }] : items;
  const blocked = command ? commandBlocked(command.id, acted, sketch, values, editing, picked) : "";
  const feature = !editing && !wholeBody && featureIndex > 0 ? { row: rows[featureIndex].key, name: names[featureIndex]?.title || "" } : null;
  // A circular pattern's axis, picked on the model; what an extrude Up To Surface or Up To Vertex ends on.
  const turnsAbout = edit.command === "pattern" && values.type === "circular" ? patternAxis(items) : null;
  const upTo = Boolean(command?.sketch) && (values.end === "surface" || values.end === "vertex");
  const ending = upTo ? extrudeEnd(values.end, items) : null;
  // Edges or faces picked while a feature is reopened replace its own, as a new axis does a
  // pattern's and a new face or vertex an extrude's end.
  const repicked = Boolean(editing) && ((REPICKS.has(edit.command) && listed.length > 0) || Boolean(turnsAbout) || Boolean(ending)
    || (drafting && Boolean(neutralFace)));
  // What the view draws itself while the panel is open, with the way the command goes, as
  // SolidWorks previews it: an extrude swept along its sketch's normal, its arrow and its depth
  // (its arrow alone where the body or a pick ends it, the server's preview drawn apart); a revolve
  // turned about its axis line, its arrow and its angle; a linear pattern's way; a hole's way into
  // its face; a mirror's plane. A size written as a name is not swept here.
  const kind = edit.command === "cut" || edit.command === "revolve_cut" ? "cut" : "boss";
  const sketchState = sketch ? sketchView(edit.state, sketch)?.state || null : null;
  const angle = plainNumber(values.angle);
  const axisLine = revolving && sketch ? sketchGeometry(sketchState).curves.find(curve => curve.id === values.axis && curve.kind === "line") : null;
  const facePick = references.find(reference => reference?.selectorType === "face")?.pickData || null;
  // An extrude's arrow is a handle, as SolidWorks' is: dragged, it sets the Depth (one typed as a
  // number, at Blind and Mid Plane); clicked, it turns the extrude the other way (not at Mid Plane,
  // nor where the body or a pick ends it).
  const extruded = edit.command === "extrude" || edit.command === "cut"
    ? extrudePreview(edit.command, values, { units, sketch, frame: sketchState?.frame || null, ending }) : null;
  const handled = extruded ? {
    ...extruded,
    // What the boxes beside its arrows show, as the panel has it (`SketchesLayer`'s `ValueBox`).
    text: String(values.depth ?? "").trim(), text2: String(values.depth2 ?? "").trim(),
    ...((extruded.end === "blind" || extruded.end === "mid") && !extruded.arrowOnly
      ? { onDepth: text => setValues(current => ({ ...current, depth: text })) } : {}),
    ...(extruded.end === "blind" || extruded.end === "through" ? { onReverse: () => setValues(current => ({ ...current, reverse: !current.reverse })) } : {}),
    // Direction 2's arrow sets its own depth, dragged; it always goes the other way.
    ...(extruded.depth2 > 0 && !extruded.arrowOnly ? { onDepth2: text => setValues(current => ({ ...current, depth2: text })) } : {}),
  } : null;
  const local = !previewOn ? null
    : edit.command === "extrude" || edit.command === "cut" ? handled
      : revolving ? (axisLine && angle !== null && angle > 0 ? { kind, revolve: { a: axisLine.a, b: axisLine.b, ...revolveSweep(values, angle) },
        file: sketch.file, line: sketch.line, label: `${String(values.angle).trim()}°`, text: String(values.angle).trim(),
        // Its arrow a handle, as an extrude's: dragged round, it sets the Angle; clicked, it turns the other way.
        // Dragged, the arrow is the whole turn; with Direction 2 its own angle is what is left of it.
        onAngle: text => setValues(current => ({ ...current, angle: current.end !== "mid" && current.direction2
          ? String(Math.max(1, Number(text) - (Number(current.angle2) || 0))) : text })),
        onReverse: () => setValues(current => ({ ...current, reverse: !current.reverse })) } : null)
        : edit.command === "pattern" ? patternPreview(values, units)
          : edit.command === "hole" ? holePreview(values, units, editing && !repicked ? null : facePick)
            : edit.command === "mirror" ? mirrorPreview(values, editing || !faces.length ? planeAt(namedPlane(values.plane)) : facePick)
            // Split's plane, where it cuts the body, as SolidWorks draws its trim tool.
            : edit.command === "split" ? mirrorPreview(values, editing || !faces.length ? planeAt(namedPlane(values.plane)) : facePick)
              // A draft's neutral plane, and its direction of pull.
              : drafting ? draftPreview(values, neutralFace?.pick || planeAt(namedPlane(values.neutral)), edit.state?.bounds)
                // A reference plane where it would be, and the way it is offset.
                : planing && planeKind === "offset" ? planePreview(values, (editing && !repicked ? null : facePick) || planeAt(namedPlane(values.reference)),
                  edit.state?.bounds, units)
                // A Mid Plane, midway between its two faces, where it will be.
                : planing && planeKind === "mid" ? midPlanePreview(references.filter(each => each?.selectorType === "face").map(each => each.pickData))
              // A sweep's or a loft's sketches, shaded as picked while the server previews what they make.
              : takes && picked.some(Boolean) ? { mark: "picked", sketches: picked.filter(Boolean).map(each => ({ file: each.file, line: each.line })) }
                : null;
  // The size SolidWorks puts on the model beside what the command acts on, typed over there as in
  // the dialog: a fillet's radius by its first edge, a chamfer's distance, a shell's thickness, a face's
  // offset, a draft's angle; a plane's offset where the plane will be.
  const calledOut = { fillet: ["radius", "Radius", units], chamfer: ["distance", "Distance", units], shell: ["thickness", "Thickness", units],
    offset_face: ["distance", "Distance", units], draft: ["angle", "Angle", "°"], plane: ["distance", "Distance", units] }[edit.command] || null;
  // A draft's neutral face is held apart from its picks, so its first pick is a face it drafts.
  const firstPick = (drafting ? references.find(each => each?.selectorType === "face") : references[0])?.pickData?.center
    || (planing && local?.center) || null;
  const calloutKey = calledOut && previewOn && firstPick && !(planing && planeKind !== "offset")
    ? JSON.stringify([calledOut, Array.from(firstPick, Number), String(values[calledOut[0]] ?? "")]) : "";
  const { setCallout } = edit;
  useEffect(() => {
    if (typeof setCallout !== "function") return undefined;
    if (!calloutKey) { setCallout(null); return undefined; }
    const [[key, label, unit], at, text] = JSON.parse(calloutKey);
    setCallout({ at, label, unit, text, onCommit: typed => setValues(current => ({ ...current, [key]: typed })) });
    return () => setCallout(null);
  }, [calloutKey, setCallout]);
  // An extrude's or a revolve's solid swept here is not asked of the server.
  // Not for a sketch with no closed outline (an open one, not Thin): nothing would be swept, so the server previews it.
  const sweeps = Boolean(local && !local.arrowOnly && !local.mark && sketchState?.loops?.length);
  const localKey = local ? JSON.stringify(local) : "";
  const localRef = useRef(local);
  localRef.current = local;
  useEffect(() => {
    setPreview(localRef.current);
    return () => setPreview(null);
  }, [localKey, setPreview]);
  // Any other preview is the server's: what OK would send, made without writing it once the panel
  // has what it needs, and made again as the part changes under it or the rollback bar moves.
  // A plane's preview is its outline, drawn here; the server's would only say it changes nothing on the body.
  const wanted = command && previewOn && !disabled && !blocked && !sweeps && !planing
    ? commandRequest(command.id, values, acted, feature, sketch, editing, picked) : null;
  const wantedRef = useRef(wanted);
  wantedRef.current = wanted;
  const wantedKey = wanted ? JSON.stringify(wanted) : "";
  useEffect(() => {
    if (typeof previewFeature !== "function") return undefined;
    const timer = setTimeout(() => previewFeature(wantedRef.current), wantedKey ? PREVIEW_WAIT_MS : 0);
    return () => clearTimeout(timer);
  }, [wantedKey, edit.state, edit.bar, previewFeature]);
  if (!command) return null;
  const Icon = COMMAND_ICONS[command.id];
  const set = key => value => setValues(current => ({ ...current, [key]: value }));
  // Hole Wizard: a type, standard, size or fit picked fills the hole's sizes from the screw's; a size
  // the standard or the type has not becomes the standard's own. One of its sizes typed over is Custom.
  const sized = key => value => setValues(current => {
    const next = { ...current, [key]: value === CUSTOM ? "" : value };
    if (key !== "size" && next.size && !holeSizeOptions(next.standard, next.type).some(each => each.value === next.size)) {
      next.size = defaultSize(next.standard);
    }
    return { ...next, ...holeFill(next, units) };
  });
  const typedOver = key => value => setValues(current => ({ ...current, [key]: value, ...(value !== current[key] ? { size: "" } : {}) }));
  const ok = () => {
    if (blocked || disabled) return;
    // A reopened feature left as it was: nothing to write.
    if (editing && !repicked && sameValues(values, opened)) { edit.close(); return; }
    void edit.run(commandRequest(command.id, values, acted, feature, sketch, editing, picked));
  };
  // Apply, as NX's: the feature made, and the dialog open again for the next one.
  const apply = async () => {
    if (blocked || disabled) return;
    const id = command.id;
    const reply = await edit.run(commandRequest(command.id, values, acted, feature, sketch, editing, picked));
    if (reply?.ok) edit.open(id);
  };
  // The Boolean switched: the other command's dialog, with what was typed and picked.
  const bool = editing ? null : booleanOf(command.id);
  const switchBoolean = value => {
    if (!bool || value === bool.value) return;
    carry = { to: bool.other, values, picked };
    edit.open(bool.other);
  };
  const copies = command.id === "mirror" || command.id === "pattern";
  const pickedFace = references.find(reference => reference?.selectorType === "face")?.pickData?.normal;
  const offsets = command.id !== "hole" ? [] : editing && !repicked ? editing.axes || [] : faceOffsetAxes(pickedFace);
  // Its name as NX's ribbon has it, a reopened feature's too (Extrude, Edge Blend).
  const title = nxCommand(command);
  // What a reopened feature acts on stays as it is until others are picked, on the body before it.
  const keptHint = command.id === "hole" ? "Click its face on the model to add a hole there."
    : `Select ${command.picks === "edges" ? "edges" : "faces"} on the model to pick others.`;

  const confirm = { onOk: ok, onApply: editing ? null : () => void apply(), onCancel: edit.close, okDisabled: Boolean(blocked) || disabled,
    okReason: blocked || "", busy: edit.saving };
  const sketchLabel = sketch ? (sketch.plane && sketch.plane !== "Plane" ? `${sketch.title}, ${sketch.plane} Plane` : sketch.title) : "";
  // Choose: the pick still wanted, or, with each made, the preview to look at before OK. A reopened
  // feature keeps what it acts on, and an extrude its end while the end condition is its own.
  // A reopened draft keeps its faces until others are picked, whatever becomes of its neutral plane.
  const kept = Boolean(editing) && (command.sketch || takes ? editing.values?.end === values.end : drafting || !repicked);
  const step = chooseLine(chooseSteps(command.id, { listed, sketch, values, ending, kept, sketches: picked }));
  const next = step || (blocked ? "" : previewOn ? "Review the preview, then press OK." : "Press OK to make it.");
  // A pick listed, taken out by its X as a click on it on the model takes it out.
  const removePick = onDeselect ? selector => {
    const reference = references.find(each => String(each?.displaySelector || each?.normalizedSelector || "") === selector);
    if (reference?.id) onDeselect(reference.id);
  } : null;
  const shown = edit.featurePreview || null;
  // A sweep's or a loft's sketch, let go by its X; let go in the design tree too, so it can be picked again.
  const unpick = item => {
    const gone = each => each && `${each.file}:${each.line}` === item.key;
    setPicked(current => (takes === "many" ? current.filter(each => !gone(each)) : current.map(each => (gone(each) ? null : each))));
    if (selectedSketch && `${selectedSketch.file}:${selectedSketch.line}` === item.key) edit.select(null);
  };
  const sketchItem = (each, prefix = "") => ({ key: `${each.file}:${each.line}`, label: `${prefix}${each.title}` });

  return <div role="dialog" aria-label={title} data-cad-edit-command={command.id} className="flex shrink-0 flex-col"
    onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); edit.close(); return; }
      // Enter is OK, as in SolidWorks' PropertyManager; in a box it sets the value typed there first.
      if (event.key === "Enter" && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) { event.preventDefault(); event.stopPropagation(); ok(); }
    }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <Icon className="size-5 shrink-0" aria-hidden="true" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">{title}</h2>
      {/* OK, Apply and Cancel are at the dialog's foot, as NX has them; its title row closes it. */}
      <button type="button" aria-label="Close" title="Close" disabled={edit.saving} onClick={edit.close}
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:opacity-40 [&_svg]:size-3.5">
        <X aria-hidden="true" />
      </button>
    </div>
    {next ? <p role="status" data-cad-choose-step="" className="flex items-center gap-1.5 border-b border-border px-2 py-1.5 text-tiny leading-4 text-foreground">
      <span className={`size-2 shrink-0 rounded-full ${step ? "bg-cad-picked" : "bg-muted-foreground/50"}`} aria-hidden="true" />
      <span className="min-w-0 flex-1">{next}</span>
    </p> : null}
    {/* A draft's neutral plane first, as SolidWorks' Draft asks for it, with Reverse direction
        beside it: the plane the faces keep their size at, and the way the part narrows from it. */}
    {drafting ? <FileSheetSettingsSection title="Neutral Plane" sectionId="edit-command-neutral">
      <SelectionBox items={values.neutral ? [{ key: "neutral", label: ORIGIN_PLANE_NAMES.has(values.neutral) ? `${values.neutral} Plane`
        : namedPlane(values.neutral)?.label || (neutralFace ? selectionLabel(neutralFace.item) : "Its face, as written") }] : []}
        prompt="Select a flat face on the model, or a plane in the design tree." onClear={clearNeutral} clearLabel="Clear" />
      {neutralNote ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">{neutralNote}</p> : null}
      <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(values.reverse)} disabled={disabled || !values.neutral}
        onCheckedChange={set("reverse")} />
    </FileSheetSettingsSection> : null}
    {/* Plane's First Reference, as SolidWorks' Plane asks for it: a flat face picked on the model, or
        an origin plane picked in the design tree; then how far it is offset, and which way. */}
    {planing && planeKind !== "offset" ? <FileSheetSettingsSection title={planeKind === "mid" ? "Mid Plane" : "Normal to Curve"} sectionId="edit-command-reference">
      {planeRefs.length ? <SelectionList items={planeRefs} prompt="" onRemove={removePick} />
        : <KeptList text={editing?.keeps || ""} hint="Pick faces or an edge on the model to place it again." />}
      {planeKind === "mid"
        ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Midway between the two faces, and kept there as the part changes.</p>
        : <FileSheetSelectRow label="At" value={values.end === "end" ? "end" : "start"} options={CURVE_ENDS} onValueChange={set("end")} />}
    </FileSheetSettingsSection> : null}
    {planing && planeKind === "offset" ? <FileSheetSettingsSection title="First Reference" sectionId="edit-command-reference">
      {faces.length ? <SelectionList items={faces} prompt="" onRemove={removePick} />
        : <SelectionBox items={values.reference ? [{ key: "reference", label: namedPlane(values.reference)?.label || `${values.reference} Plane` }]
          : editing && editing.values?.reference === "face" ? [{ key: "reference", label: "Its face, as written" }] : []}
          prompt={command.prompt} />}
      <NumberRow label="Offset distance" value={values.distance} unit={units} disabled={disabled} onChange={set("distance")} />
      <FileSheetCheckboxRow label="Flip offset" checked={Boolean(values.flip)} disabled={disabled} onCheckedChange={set("flip")} />
      {/* At angle, as SolidWorks' Plane turns one: about its own X or Y axis, through its origin. */}
      <NumberRow label="Angle" value={values.angle ?? "0"} unit="deg" disabled={disabled} onChange={set("angle")} />
      {Number(values.angle) ? <FileSheetSelectRow label="About" value={values.about === "y" ? "y" : "x"} options={TURN_AXES}
        onValueChange={set("about")} /> : null}
    </FileSheetSettingsSection> : null}
    {command.picks && !(editing && command.id === "mirror") && !planing ? <FileSheetSettingsSection
      title={command.picks === "edges" ? "Edges" : command.id === "mirror" ? "Mirror face" : drafting ? "Faces to Draft" : "Faces"}
      sectionId="edit-command-selection">
      {editing && !repicked ? <KeptList text={editing.keeps} hint={keptHint} />
        : <SelectionList items={listed} prompt={command.prompt} onRemove={removePick} />}
    </FileSheetSettingsSection> : null}
    {command.sketch ? <FileSheetSettingsSection title="Section" sectionId="edit-command-sketch">
      {/* The sketch it takes, picked on the model or in the design tree and shaded there; a
          reopened feature keeps its own. */}
      <SelectionBox items={sketch ? [{ key: `${sketch.file}:${sketch.line}`, label: sketchLabel }] : []}
        prompt="Select a sketch on the model or in the design tree." clearLabel="Deselect"
        onClear={editing ? null : () => edit.select(null)} />
    </FileSheetSettingsSection> : null}
    {copies ? <FileSheetSettingsSection title={command.id === "mirror" ? "Mirror" : "Copies"} sectionId="edit-command-copies">
      {editing ? <FileSheetControlRow label="Of" value={sizeName(editing.keeps)} /> : <>
        <FileSheetSelectRow label="Of" value={feature ? "feature" : "body"} onValueChange={value => setWholeBody(value === "body")}
          options={[...(featureIndex > 0 ? [{ value: "feature", label: names[featureIndex]?.title || "Feature" }] : []), { value: "body", label: "Whole body" }]} />
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Pick a feature in the history to copy it.</p>
      </>}
    </FileSheetSettingsSection> : null}
    {revolving ? <FileSheetSettingsSection title="Axis of Revolution" sectionId="edit-command-axis">
      {axes.length ? <FileSheetSelectRow label="About" value={values.axis} options={axes} onValueChange={set("axis")} />
        : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{sketch ? "Draw a centerline in the sketch to revolve about." : command.prompt}</p>}
    </FileSheetSettingsSection> : null}
    {takes ? <FileSheetSettingsSection title={takes === "many" ? "Profiles" : "Profile and Path"} sectionId="edit-command-sketches">
      {/* Each sketch it is made from, picked on the model or in the design tree and shaded there,
          in order; a reopened sweep or loft keeps its own. */}
      {editing ? <KeptList text={editing.keeps} hint="A sweep or a loft keeps the sketches it is made from." />
        : takes === "many" ? <SelectionBox items={picked.map((each, index) => sketchItem(each, `${index + 1}. `))} prompt={command.prompt}
          onClear={unpick} clearLabel="Remove" />
          : <>
            <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Profile</p>
            <SelectionBox items={picked[0] ? [sketchItem(picked[0])] : []} prompt="Select the profile sketch: the closed outline it runs."
              onClear={unpick} clearLabel="Remove" />
            <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Path</p>
            <SelectionBox items={picked[1] ? [sketchItem(picked[1])] : []} prompt="Select the path sketch: the curves it runs along."
              onClear={unpick} clearLabel="Remove" />
          </>}
    </FileSheetSettingsSection> : null}
    {takes || planing ? null : <FileSheetSettingsSection title={revolving || extruding ? "Direction 1" : "Parameters"} sectionId="edit-command-parameters">
      {revolving ? <>
        <FileSheetSelectRow label="Revolve Type" value={values.end || "blind"} options={REVOLVE_ENDS} onValueChange={set("end")} />
        <NumberRow label="Angle" value={values.angle} unit="deg" disabled={disabled} onChange={set("angle")} />
        {values.end === "mid" ? null
          : <FileSheetCheckboxRow label="Reverse direction" checked={values.reverse} disabled={disabled} onCheckedChange={set("reverse")} />}
      </> : extruding ? <>
        <FileSheetSelectRow label="End condition" value={values.end} options={command.id === "cut" ? CUT_ENDS : BOSS_ENDS} onValueChange={set("end")} />
        {upTo ? <>
          {/* What it ends on, picked on the model: a flat face, or an edge clicked near the vertex. */}
          <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{values.end === "surface" ? "Face" : "Vertex"}</p>
          {ending ? <SelectionBox items={[{ key: ending.selector, label: values.end === "surface" ? selectionLabel(ending)
            : `${selectionLabel(ending)}, the end nearest the click` }]} prompt="" />
            : editing?.values?.end === values.end ? <KeptList text={values.end === "surface" ? "Its face, as written" : "Its vertex, as written"}
              hint={values.end === "surface" ? "Select another flat face on the model to end there." : "Click near another edge's end to end there."} />
              : <SelectionBox items={[]} prompt={values.end === "surface" ? "Select a flat face on the model to end on."
                : "Click near the end of an edge on the model: that vertex ends it."} />}
        </> : null}
        {NO_DEPTH.has(values.end) ? null
          : <NumberRow label="Depth" value={values.depth} unit={units} disabled={disabled} onChange={set("depth")} />}
        {values.end === "mid" || values.end === "next" || upTo ? null
          : <FileSheetCheckboxRow label="Reverse direction" checked={values.reverse} disabled={disabled} onCheckedChange={set("reverse")} />}
        {/* Draft, as SolidWorks' Draft On/Off: the sides lean in by the angle, or out. */}
        {values.end === "next" ? null : <>
          <FileSheetCheckboxRow label="Draft" checked={values.draft} disabled={disabled} onCheckedChange={set("draft")} />
          {values.draft ? <>
            <NumberRow label="Draft angle" value={values.draft_angle} unit="deg" disabled={disabled} onChange={set("draft_angle")} />
            <FileSheetCheckboxRow label="Draft outward" checked={values.outward} disabled={disabled} onCheckedChange={set("outward")} />
          </> : null}
        </>}
      </> : null}
      {command.id === "fillet" ? <NumberRow label="Radius" value={values.radius} unit={units} disabled={disabled} onChange={set("radius")} /> : null}
      {/* Rib, as SolidWorks' Rib grows parallel to its sketch: its thickness across the sketch's
          plane, and which side of its line it grows to the body. */}
      {command.id === "rib" ? <>
        <NumberRow label="Thickness" value={values.thickness} unit={units} disabled={disabled} onChange={set("thickness")} />
        <FileSheetCheckboxRow label="Flip material side" checked={Boolean(values.flip)} disabled={disabled} onCheckedChange={set("flip")} />
      </> : null}
      {command.id === "chamfer" ? <>
        <FileSheetSelectRow label="Chamfer type" value={values.type || "equal"} options={CHAMFER_TYPES} onValueChange={set("type")} />
        <NumberRow label={values.type === "distances" ? "Distance 1" : "Distance"} value={values.distance} unit={units} disabled={disabled}
          onChange={set("distance")} />
        {values.type === "distances" ? <>
          <NumberRow label="Distance 2" value={values.distance2} unit={units} disabled={disabled} onChange={set("distance2")} />
          <FileSheetCheckboxRow label="Flip direction" checked={Boolean(values.flip)} disabled={disabled} onCheckedChange={set("flip")} />
        </> : null}
        {values.type === "angle" ? <>
          <NumberRow label="Angle" value={values.angle} unit="deg" disabled={disabled} onChange={set("angle")} />
          {/* Which face the distance runs along, as SolidWorks' Angle distance flips it. */}
          <FileSheetCheckboxRow label="Flip direction" checked={Boolean(values.flip)} disabled={disabled} onCheckedChange={set("flip")} />
        </> : null}
      </> : null}
      {command.id === "shell" ? <>
        <NumberRow label="Thickness" value={values.thickness} unit={units} disabled={disabled} onChange={set("thickness")} />
        <FileSheetCheckboxRow label="Shell outward" checked={Boolean(values.outward)} disabled={disabled} onCheckedChange={set("outward")} />
      </> : null}
      {/* Offset Region: how far the faces move, outward unless reversed. */}
      {command.id === "offset_face" ? <>
        <NumberRow label="Distance" value={values.distance} unit={units} disabled={disabled} onChange={set("distance")} />
        <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(values.reverse)} disabled={disabled} onCheckedChange={set("reverse")} />
      </> : null}
      {drafting ? <NumberRow label="Draft angle" value={values.angle} unit="deg" disabled={disabled} onChange={set("angle")} /> : null}
      {command.id === "hole" ? <>
        <FileSheetSelectRow label="Hole type" value={values.type || "simple"} options={HOLE_TYPES} onValueChange={sized("type")} />
        {/* Hole Wizard's Hole Specifications: a standard's screw, and its fit, fill the sizes below. */}
        <FileSheetSelectRow label="Standard" value={values.standard || "iso"} options={HOLE_STANDARDS} onValueChange={sized("standard")} />
        <FileSheetSelectRow label="Size" value={values.size || CUSTOM} onValueChange={sized("size")}
          options={[...holeSizeOptions(values.standard, values.type), { value: CUSTOM, label: "Custom" }]} />
        {values.type === "tapped" ? null
          : <FileSheetSelectRow label="Fit" value={values.fit || "normal"} options={holeFits(values.standard)} onValueChange={sized("fit")} />}
        <NumberRow label={values.type === "tapped" ? "Tap drill diameter" : "Diameter"} value={values.diameter} unit={units} disabled={disabled}
          onChange={typedOver("diameter")} />
        <FileSheetCheckboxRow label="Through all" checked={values.through} disabled={disabled} onCheckedChange={set("through")} />
        {values.through ? null : <NumberRow label="Depth" value={values.depth} unit={units} disabled={disabled} onChange={set("depth")} />}
        {values.type === "counterbore" ? <>
          <NumberRow label="Counterbore diameter" value={values.cbore_diameter} unit={units} disabled={disabled} onChange={typedOver("cbore_diameter")} />
          <NumberRow label="Counterbore depth" value={values.cbore_depth} unit={units} disabled={disabled} onChange={typedOver("cbore_depth")} />
        </> : null}
        {values.type === "countersink" ? <>
          <NumberRow label="Countersink diameter" value={values.csk_diameter} unit={units} disabled={disabled} onChange={typedOver("csk_diameter")} />
          <NumberRow label="Countersink angle" value={values.csk_angle} unit="deg" disabled={disabled} onChange={typedOver("csk_angle")} />
        </> : null}
        {offsets.map(axis => <NumberRow key={axis} label={`${axis.toUpperCase()} from center`} value={values[axis]} unit={units}
          disabled={disabled} onChange={set(axis)} />)}
        <OtherHoles places={values.more || []} axes={offsets} units={units} disabled={disabled}
          onChange={(index, axis, text) => setValues(current => ({ ...current,
            more: (current.more || []).map((place, at) => (at === index ? { ...place, [axis]: text } : place)) }))}
          onRemove={index => setValues(current => ({ ...current, more: (current.more || []).filter((_, at) => at !== index) }))} />
        {/* A face picked before Hole opened holds its hole at its center until it is clicked, which on a rim is
            over the opening: the first click puts the hole there, and each after it adds one. */}
        {offsets.length ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{editing || facePoint
          ? "Click the face again to add a hole there." : "Click the face where the hole goes."}</p> : null}
      </> : null}
      {command.id === "mirror" ? faces.length && !editing ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>About the selected face.</p>
        : <FileSheetSelectRow label="About" value={values.plane} onValueChange={set("plane")}
          options={[...PLANES, ...planes.map(each => ({ value: each.value, label: each.label })), ...(editing?.values?.plane === "face" ? [SAME_FACE] : [])]} />
        : null}
      {/* Split, as SolidWorks splits a part into bodies: by a face picked, or a plane; both bodies kept, or one side. */}
      {command.id === "split" ? <>
        {faces.length ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>By the selected face's plane.</p>
          : <FileSheetSelectRow label="Splitting plane" value={values.plane} onValueChange={set("plane")}
            options={[...PLANES, ...planes.map(each => ({ value: each.value, label: each.label }))]} />}
        <FileSheetSelectRow label="Keep" value={values.keep} options={SPLIT_KEEPS} onValueChange={set("keep")} />
      </> : null}
      {command.id === "delete_body" ? <FileSheetSelectRow label="Type" value={values.mode} options={BODY_MODES} onValueChange={set("mode")} /> : null}
      {command.id === "pattern" ? <>
        <FileSheetSelectRow label="Type" value={values.type} options={PATTERNS} onValueChange={set("type")} />
        {values.type === "linear" ? <>
          <FileSheetSelectRow label="Direction" value={values.direction} options={DIRECTIONS} onValueChange={set("direction")} />
          <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Or pick a straight edge along X, Y or Z on the model.</p>
          <NumberRow label="Spacing" value={values.spacing} unit={units} disabled={disabled} onChange={set("spacing")} />
          <FileSheetCheckboxRow label="Reverse direction" checked={values.reverse} disabled={disabled} onCheckedChange={set("reverse")} />
        </> : <>
          {/* The axis it turns about: a round face or a straight edge picked on the model, else the
              Z axis through the origin. */}
          <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Axis</p>
          {turnsAbout ? <SelectionBox items={[{ key: turnsAbout.selector, label: `${selectionLabel(turnsAbout)}, ${turnsAbout.type === "line" ? "straight edge" : "round face"}` }]} prompt="" />
            : editing?.values?.axis ? <KeptList text={`${editing.values.axis.charAt(0).toUpperCase()}${editing.values.axis.slice(1)}`}
              hint="Pick a round face or a straight edge on the model to turn about it instead." />
              : <SelectionBox items={[]} prompt="The Z axis through the origin. Pick a round face or a straight edge on the model to turn about it instead." />}
          {/* Equal spacing over its Angle: all the way round at 360, else from the first to the last. */}
          <NumberRow label="Angle" value={values.angle || "360"} unit="deg" disabled={disabled} onChange={set("angle")} />
          <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(values.reverse)} disabled={disabled} onCheckedChange={set("reverse")} />
        </>}
        <NumberRow label="Instances" value={values.count} disabled={disabled} onChange={set("count")} />
      </> : null}
    </FileSheetSettingsSection>}
    {/* Direction 2, as SolidWorks' Linear Pattern lays out a grid: along the other of X and Y. */}
    {command.id === "pattern" && values.type === "linear" && (values.direction === "X" || values.direction === "Y")
      ? <FileSheetSettingsSection title="Direction 2" sectionId="edit-command-pattern-direction2"
        enabled={Boolean(values.direction2)} onEnabledChange={set("direction2")}>
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Along {values.direction === "X" ? "Y" : "X"}</p>
        <NumberRow label="Spacing" value={values.spacing2} unit={units} disabled={disabled} onChange={set("spacing2")} />
        <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(values.reverse2)} disabled={disabled} onCheckedChange={set("reverse2")} />
        <NumberRow label="Instances" value={values.count2} disabled={disabled} onChange={set("count2")} />
      </FileSheetSettingsSection> : null}
    {/* Direction 2, as SolidWorks' extrude goes both ways from its sketch: switched on, the other way
        Blind (or Through All for a cut), with its own draft. Not at Mid Plane, which goes both ways
        already. */}
    {/* A revolve's Direction 2: a second angle turned the other way from the sketch. */}
    {revolving && values.end !== "mid" ? <FileSheetSettingsSection title="Direction 2" sectionId="edit-command-revolve-direction2"
      enabled={Boolean(values.direction2)} onEnabledChange={set("direction2")}>
      <NumberRow label="Angle" value={values.angle2} unit="deg" disabled={disabled} onChange={set("angle2")} />
    </FileSheetSettingsSection> : null}
    {extruding && values.end !== "mid" ? <FileSheetSettingsSection title="Direction 2" sectionId="edit-command-direction2"
      enabled={Boolean(values.direction2)} onEnabledChange={set("direction2")}>
      <FileSheetSelectRow label="End condition" value={values.end2 || "blind"} options={command.id === "cut" ? CUT_ENDS2 : BOSS_ENDS2}
        onValueChange={set("end2")} />
      {values.end2 === "through" ? null : <NumberRow label="Depth" value={values.depth2} unit={units} disabled={disabled} onChange={set("depth2")} />}
      <FileSheetCheckboxRow label="Draft" checked={Boolean(values.draft2)} disabled={disabled} onCheckedChange={set("draft2")} />
      {values.draft2 ? <>
        <NumberRow label="Draft angle" value={values.draft_angle2} unit="deg" disabled={disabled} onChange={set("draft_angle2")} />
        <FileSheetCheckboxRow label="Draft outward" checked={Boolean(values.outward2)} disabled={disabled} onCheckedChange={set("outward2")} />
      </> : null}
    </FileSheetSettingsSection> : null}
    {/* Thin Feature, as SolidWorks' extrude has it: the outline made a wall of a thickness, inside
        it, outside it or astride it, rather than filled. */}
    {/* Boolean, as NX's Extrude sets it: the shape added to the body (Unite) or taken from it
        (Subtract), one dialog for both. */}
    {bool ? <FileSheetSettingsSection title="Boolean" sectionId="edit-command-boolean">
      <FileSheetSelectRow label="Boolean" value={bool.value} options={BOOLEAN_OPTIONS} onValueChange={switchBoolean} />
    </FileSheetSettingsSection> : null}
    {extruding ? <FileSheetSettingsSection title="Thin Feature" sectionId="edit-command-thin" enabled={Boolean(values.thin)}
      onEnabledChange={set("thin")}>
      <NumberRow label="Thickness" value={values.thin_thickness} unit={units} disabled={disabled} onChange={set("thin_thickness")} />
      <FileSheetSelectRow label="Wall" value={values.thin_side || "inside"} options={THIN_SIDES} onValueChange={set("thin_side")} />
    </FileSheetSettingsSection> : null}
    {/* Preview, switched as Fusion's dialogs switch it: what OK would make, drawn on the model, and
        what its colours are; while a new one is made the last stays drawn. One that failed draws
        nothing, and says why. */}
    <FileSheetSettingsSection title="Preview" sectionId="edit-command-preview" enabled={previewOn}
      onEnabledChange={on => edit.setPreviewOn?.(on)}>
      {sweeps ? <PreviewKey added={kind === "boss"} removed={kind === "cut"} />
        : shown?.status === "updating" ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">Updating the preview</p>
          : shown?.status === "failed" ? <p className="px-2 pb-1 text-tiny leading-4 text-destructive" aria-live="polite">{shown.error}</p>
            : shown?.status === "ready" ? (shown.added || shown.removed ? <PreviewKey added={Boolean(shown.added)} removed={Boolean(shown.removed)} />
              : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{command.id === "split" && values.keep === "both"
                ? "It splits the body in two, along the plane drawn." : "It changes nothing on the body."}</p>)
              : null}
    </FileSheetSettingsSection>
    {/* Why OK waits, where the list does not already say: two faces for one hole. */}
    {blocked && (listed.length || !command.picks) && !(command.sketch && !sketch) && !takes ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>{blocked}</p> : null}
    {edit.saving ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`} aria-live="polite">Applying</p> : null}
    <ConfirmButtons {...confirm} className="border-t border-border px-2 py-2" />
  </div>;
}
