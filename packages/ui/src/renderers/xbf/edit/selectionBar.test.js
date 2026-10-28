import assert from "node:assert/strict";
import test from "node:test";

import * as THREE from "three";

import { formatPromptMessage, formatPromptReference } from "@text-to-cad/core/prompt";
import { createQuickEditContext } from "../../kit/tools/quick-edit/quickEditPrompt.js";
import { cadChosen } from "./editLayout.js";
import { featureTree } from "./editMode.js";
import {
  boundsCorners, facePick, featurePick, featureReference, pickedReferences, placeBar, projectRoot, quickEditLetsGo, mustPutDownTool, quickEditCarries, quickEditShown, rowLabel, screenBox, selectionBarActions, stripDrawingTools
} from "./selectionBar.js";

// The workspace with Select in hand and nothing open: what the bar is offered under.
const WORKSPACE = { editing: true, commandOpen: false, sketching: false, featureOf: () => null };
const face = { kind: "face", id: "i0/face/12" };
const edge = { kind: "edge", id: "i0/edge/3" };
const ids = actions => actions.map(action => action.id);

test("offers Ask, Add to context and Annotate on a face", () => {
  const actions = selectionBarActions({ ...WORKSPACE, picks: [face] });
  assert.deepEqual(ids(actions), ["ask", "add-context", "annotate"]);
  assert.ok(actions.every(action => action.enabled === true), "all there to use");
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [edge] })), ["ask", "add-context", "annotate"]);
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [face, edge] })), ["ask", "add-context", "annotate"]);
});

test("adds Edit once the face's feature is known", () => {
  const hole = pick => (pick.id === face.id ? "hole" : null);
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [face], featureOf: hole })), ["ask", "add-context", "annotate", "edit"]);
  // The feature of another face is not this one's: while any pick's is not known, there is no feature to edit.
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [face, edge], featureOf: hole })), ["ask", "add-context", "annotate"]);
  // Two faces of one feature are that feature's.
  const both = () => "hole";
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [face, edge], featureOf: both })).at(-1), "edit");
  // Faces made by two features are not one feature's to edit.
  const split = pick => (pick.kind === "face" ? "hole" : "blend");
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [face, edge], featureOf: split })), ["ask", "add-context", "annotate"]);
});

test("offers Edit on a row of the design tree or the timeline, which is its own feature, unless it has nothing to edit", () => {
  const row = { kind: "feature", id: "e2" };
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [row] })), ["ask", "add-context", "annotate", "edit"]);
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: [{ ...row, editable: false }] })), ["ask", "add-context", "annotate"]);
});

test("holds Edit, saying why, while a change is on its way", () => {
  const row = { kind: "feature", id: "e2" };
  const edit = selectionBarActions({ ...WORKSPACE, picks: [row], busy: true }).find(action => action.id === "edit");
  assert.equal(edit.enabled, false);
  assert.match(edit.reason, /change/i);
  // What does not change the part stays at hand.
  assert.ok(selectionBarActions({ ...WORKSPACE, picks: [row], busy: true }).filter(action => action.id !== "edit").every(action => action.enabled));
});

test("stays out of an open command", () => {
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [face], commandOpen: true }), []);
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [{ kind: "feature", id: "e2" }], commandOpen: true }), []);
});

test("stays out of an open sketch", () => {
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [face], sketching: true }), []);
});

test("is the workspace's alone: Simple view has none", () => {
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, editing: false, picks: [face] }), []);
});

test("is about faces, edges and a feature, and nothing else", () => {
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [] }), []);
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: undefined }), []);
  // A part, a vertex or a plane is none of the three.
  for (const kind of ["part", "vertex", "plane"]) assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [{ kind, id: "x" }] }), [], kind);
  assert.deepEqual(selectionBarActions({ ...WORKSPACE, picks: [face, { kind: "part", id: "x" }] }), []);
});

test("shows Quick Edit in the workspace only after Ask", () => {
  assert.equal(quickEditShown({ cad: true, asked: false, selectionActionVisible: true }), false);
  assert.equal(quickEditShown({ cad: true, asked: true, selectionActionVisible: true }), true);
  // Ask with nothing picked is Quick Edit on the whole part.
  assert.equal(quickEditShown({ cad: true, asked: true, selectionActionVisible: false }), true);
  assert.equal(quickEditShown({ cad: true, asked: false, selectionActionVisible: false }), false);
  // The AI layout shows it as it always has: with what is picked, and not otherwise, whether or not anything was asked.
  assert.equal(quickEditShown({ cad: false, asked: false, selectionActionVisible: true }), true);
  assert.equal(quickEditShown({ cad: false, asked: false, selectionActionVisible: false }), false);
  assert.equal(quickEditShown({ cad: false, asked: true, selectionActionVisible: false }), false);
});

// The sample bracket as the engine reads it: two extrudes a command made from sketches, a fillet written by hand,
// and a sketch nothing uses yet.
const command = { command: "extrude", values: {}, keeps: "" };
const sketched = (name, line) => ({ name, plane: "Top", file: "bracket.py", line, status: "Fully defined" });
const PART = featureTree({
  features: [
    { key: "e1", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 8, edit: command, sketch: sketched("SKETCH_000", 5) },
    { key: "b1", kind: "Fillet", name: "plate", file: "bracket.py", line: 15 },
    { key: "s9", kind: "Sketch", file: "bracket.py", line: 20, sketch: sketched("SKETCH_001", 20) },
  ],
});

test("finds the row a selection in the design tree or the timeline is", () => {
  const extrude = featurePick(PART, "e1");
  assert.deepEqual([extrude.kind, extrude.id, extrude.editable, extrude.sketch], ["feature", "e1", true, null]);
  assert.equal(extrude.feature, PART.features[0]);
  // A feature no command made has no panel to reopen: it is a pick, and has nothing to edit.
  assert.deepEqual([featurePick(PART, "b1").id, featurePick(PART, "b1").editable], ["b1", false]);
  // A sketch of its own is edited as a sketch; so is the one a feature was made from, selected by the id the tree gives it.
  const loose = featurePick(PART, "s9");
  assert.deepEqual([loose.id, loose.editable, loose.sketch], ["s9", true, PART.features[2].sketch]);
  const nested = featurePick(PART, "sketch:e1");
  assert.deepEqual([nested.id, nested.editable, nested.sketch], ["sketch:e1", true, PART.features[0].sketch]);
  assert.equal(nested.feature, PART.features[0]);
});

test("finds no row in what is not a feature: the origin, a plane, nothing, a row the tree does not have", () => {
  for (const selected of [null, "", "origin", "plane:Top", "e9", "component:base.py"]) assert.equal(featurePick(PART, selected), null, String(selected));
});

// Faces picked on the model, as the bar sees them: each its reference, by the selector the view gives it (the engine's
// ref to it, `selectors.js`'s `xbfEditReference`).
const picked = (...numbers) => numbers.map(number => ({ kind: "face", id: `i0/face/${number}`,
  reference: { id: `i0/face/${number}`, selectorType: "face", normalizedSelector: `part/face ${number}`, displaySelector: `part/face ${number}` } }));
// The engine's map for the faces on screen: faces 12 and 3 the extrude's, 4 the fillet's.
const FACES = { faceFeatures: { "12": "e1", "3": "e1", "4": "b1" } };

test("finds the row faces picked on the model are, where one feature made them all and it has something to edit", () => {
  const pick = facePick(PART, picked(12, 3), FACES);
  assert.deepEqual([pick.kind, pick.id, pick.editable, pick.sketch], ["feature", "e1", true, null]);
  assert.equal(pick.feature, PART.features[0]);
  // Its Edit is the feature's, as a row's is: the bar offers it when every pick is that feature's.
  assert.deepEqual(ids(selectionBarActions({ ...WORKSPACE, picks: picked(12, 3), featureOf: () => pick.id })).at(-1), "edit");
});

test("finds no row for faces it cannot say one feature with something to edit made", () => {
  // A face the engine does not know; faces of two features; an edge among them; a fillet no command made; no map at all.
  assert.equal(facePick(PART, picked(12, 9), FACES), null);
  assert.equal(facePick(PART, picked(12, 4), FACES), null);
  assert.equal(facePick(PART, [...picked(12), edge], FACES), null);
  assert.equal(facePick(PART, picked(4), FACES), null);
  assert.equal(facePick(PART, picked(12), null), null);
  assert.equal(facePick(PART, [], FACES), null);
});

test("an assembly's parts are opened to be edited, so none of its features is edited from here", () => {
  const assembly = featureTree({ components: [{ file: "base.py", name: "base", features: [
    { key: "c1", kind: "Boss-Extrude", name: "base", file: "base.py", line: 3, edit: command }] }] });
  const pick = featurePick(assembly, "c1");
  assert.deepEqual([pick.id, pick.editable], ["c1", false]);
});

// A 600 × 400 view, kept 8 px in from its edges and below a 32 px toolbar; a bar 200 × 28.
const BOUNDS = Object.freeze({ left: 8, top: 40, right: 592, bottom: 392 });
const SIZE = Object.freeze({ width: 200, height: 28 });
const box = (left, top, right, bottom) => ({ left, top, right, bottom });

test("places the bar above the pick, centred on it, 10 px off", () => {
  assert.deepEqual(placeBar({ box: box(250, 200, 350, 260), size: SIZE, bounds: BOUNDS }), { left: 200, top: 162 });
});

test("places it below where there is no room above", () => {
  assert.deepEqual(placeBar({ box: box(250, 50, 350, 90), size: SIZE, bounds: BOUNDS }), { left: 200, top: 100 });
});

test("keeps it inside the view's edges", () => {
  assert.deepEqual(placeBar({ box: box(0, 200, 20, 220), size: SIZE, bounds: BOUNDS }), { left: 8, top: 162 });
  assert.deepEqual(placeBar({ box: box(580, 200, 600, 220), size: SIZE, bounds: BOUNDS }), { left: 392, top: 162 });
});

test("keeps out of the cards over the view: above or below the pick, else beside it", () => {
  // Centred above the pick it would run under the navigator, and so below it; beside it, right of the pick, it is clear.
  const navigator = box(8, 40, 264, 300);
  assert.deepEqual(placeBar({ box: box(270, 150, 330, 200), size: SIZE, bounds: BOUNDS, obstacles: [navigator] }), { left: 340, top: 161 });
  // Where the right is taken too (a dialog beside the pick), the left of the pick is what is left.
  const dialog = box(330, 100, 592, 300);
  assert.deepEqual(placeBar({ box: box(270, 150, 330, 200), size: SIZE, bounds: BOUNDS, obstacles: [dialog] }), { left: 60, top: 161 });
  // A card above the pick, and the bar goes below it.
  assert.deepEqual(placeBar({ box: box(250, 200, 350, 260), size: SIZE, bounds: BOUNDS, obstacles: [box(100, 150, 500, 190)] }), { left: 200, top: 270 });
});

test("sits over a pick that fills the view, held inside it, where nothing beside it is free", () => {
  const placed = placeBar({ box: box(-100, -50, 700, 500), size: SIZE, bounds: BOUNDS });
  assert.deepEqual(placed, { left: 200, top: 40 });
});

test("is nowhere for a pick out of the view", () => {
  assert.equal(placeBar({ box: box(-300, 100, -100, 200), size: SIZE, bounds: BOUNDS }), null);
  assert.equal(placeBar({ box: box(100, 450, 200, 500), size: SIZE, bounds: BOUNDS }), null);
  assert.equal(placeBar({ box: null, size: SIZE, bounds: BOUNDS }), null);
});

test("takes the corners of a box of the model, where the model's matrix puts them", () => {
  const corners = boundsCorners({ min: [0, 0, 0], max: [2, 4, 6] });
  assert.equal(corners.length, 8);
  assert.deepEqual(corners.map(corner => corner.join()).sort(), ["0,0,0", "0,0,6", "0,4,0", "0,4,6", "2,0,0", "2,0,6", "2,4,0", "2,4,6"]);
  // A matrix as three.js lays its 16 numbers out, column by column: a move by (10, 20, 30).
  const move = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1];
  assert.deepEqual(boundsCorners({ min: [0, 0, 0], max: [1, 1, 1] }, move).map(corner => corner.join()).sort()[0], "10,20,30");
  // No box, no corners.
  assert.deepEqual(boundsCorners(null), []);
  assert.deepEqual(boundsCorners({ min: [0, 0], max: [1, 1] }), []);
});

test("puts the model's points on the screen where the camera sees them, the model group's place included", () => {
  // A 600 × 400 view, an orthographic camera straight over it, one pixel a unit: (x, y, 0) falls at (300 + x, 200 − y).
  const camera = new THREE.OrthographicCamera(-300, 300, 200, -200, 0.1, 1000);
  camera.position.set(0, 0, 100);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const modelGroup = new THREE.Group();
  const runtime = { THREE, camera, modelGroup };
  const plate = [[-50, -20, 0], [50, -20, 0], [-50, 20, 0], [50, 20, 0]];
  const rounded = box => box && Object.fromEntries(Object.entries(box).map(([edge, value]) => [edge, Math.round(value * 1000) / 1000]));
  assert.deepEqual(rounded(screenBox(runtime, plate, 600, 400)), { left: 250, top: 180, right: 350, bottom: 220 });
  // The model sits under a group that moves it (the part is centred in the view), and the box moves with it.
  modelGroup.position.set(10, -30, 0);
  modelGroup.updateMatrixWorld();
  assert.deepEqual(rounded(screenBox(runtime, plate, 600, 400)), { left: 260, top: 210, right: 360, bottom: 250 });
  // Behind the camera, or out past what it sees, is nowhere; with some of the points in front, the box is theirs.
  assert.equal(screenBox(runtime, [[0, 0, 500]], 600, 400), null);
  assert.equal(screenBox(runtime, [], 600, 400), null);
  assert.deepEqual(rounded(screenBox(runtime, [...plate, [0, 0, 500]], 600, 400)), { left: 260, top: 210, right: 360, bottom: 250 });
});

// The sample bracket as the engine reads it: two extrudes a command made from sketches, a Fillet and a Hole written
// by hand, and a Pattern. The design tree numbers each kind on its own, a sketch just before the extrude that takes it:
// Sketch1, Boss-Extrude1, Sketch2, Boss-Extrude2, Fillet1, Hole1, Pattern1.
const BRACKET_STATE = {
  units: "mm", name: "bracket", root: "/work/bracket", script: "/work/bracket/bracket.py", files: { "bracket.py": "ab12" },
  features: [
    { key: "e1", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 8, edit: command, sketch: sketched("SKETCH_000", 5) },
    { key: "e2", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 13, edit: command, sketch: sketched("SKETCH_001", 10) },
    { key: "b1", kind: "Fillet", name: "plate", file: "bracket.py", line: 15 },
    { key: "h1", kind: "Hole", name: "plate", file: "bracket.py", line: 17 },
    { key: "p1", kind: "Pattern", name: "plate", file: "bracket.py", line: 19 },
  ],
};
const BRACKET = featureTree(BRACKET_STATE);
const STEP = { kind: "workspace-file", path: "/work/bracket/bracket.step", revision: "r1" };

test("works out where the project starts: the engine says, else the script's own path says", () => {
  assert.equal(projectRoot({ root: "/work/bracket" }), "/work/bracket");
  assert.equal(projectRoot({ root: "C:\\work\\bracket\\" }), "C:/work/bracket");
  // A reply that says none: the script's path less its own name among the files read, the longest if two agree.
  assert.equal(projectRoot({ script: "/work/bracket/plate.py", files: { "plate.py": "a" } }), "/work/bracket");
  assert.equal(projectRoot({ script: "/work/bracket/parts/plate.py", files: { "plate.py": "a", "parts/plate.py": "b", "sizes.py": "c" } }), "/work/bracket");
  assert.equal(projectRoot({ script: "C:\\work\\plate.py", files: { "plate.py": "a" } }), "C:/work");
  // Nothing to go by is no root, never a guess.
  assert.equal(projectRoot({ script: "/work/bracket/plate.py", files: { "sizes.py": "a" } }), "");
  assert.equal(projectRoot({}), "");
  assert.equal(projectRoot(null), "");
});

test("labels a row as the design tree numbers it", () => {
  assert.equal(rowLabel(BRACKET, "h1"), "Hole1");
  assert.equal(rowLabel(BRACKET, "e2"), "Boss-Extrude2");
  assert.equal(rowLabel(BRACKET, "sketch:e2"), "Sketch2");
  assert.equal(rowLabel(BRACKET, "nowhere"), "");
  // An assembly's parts are numbered each from its own start.
  const assembly = featureTree({ components: [
    { file: "base.py", name: "base", features: [{ key: "c1", kind: "Boss-Extrude", name: "base", file: "base.py", line: 3 }] },
    { file: "pin.py", name: "pin", features: [{ key: "d1", kind: "Hole", name: "pin", file: "pin.py", line: 4 }] }] });
  assert.deepEqual([rowLabel(assembly, "c1"), rowLabel(assembly, "d1")], ["Boss-Extrude1", "Hole1"]);
});

test("names a feature's statement as a range of its script: its whole line, in the script's absolute path, under its design tree name", () => {
  const reference = featureReference({ root: "/work/bracket", pick: featurePick(BRACKET, "h1"), label: "Hole1" });
  assert.deepEqual(reference, {
    resource: { kind: "workspace-file", path: "/work/bracket/bracket.py" },
    target: { kind: "text-range", start: { line: 16, character: 0 }, end: { line: 17, character: 0 } },
    label: "Hole1",
  });
  // As the prompt spells a range: line 17, whole.
  assert.equal(formatPromptReference(reference), "/work/bracket/bracket.py:17:1-18:1");
  // A sketch picked is its own statement, not the extrude's it was made for.
  const sketch = featureReference({ root: "/work/bracket", pick: featurePick(BRACKET, "sketch:e2"), label: "Sketch2" });
  assert.equal(formatPromptReference(sketch), "/work/bracket/bracket.py:10:1-11:1");
  // A file the engine names in full (outside the project's top folder) is kept as it is; a root's trailing slash makes no double.
  const outside = featureTree({ features: [{ key: "h2", kind: "Hole", name: "plate", file: "/shared/holes.py", line: 3 }] });
  assert.equal(formatPromptReference(featureReference({ root: "/work/bracket/", pick: featurePick(outside, "h2"), label: "Hole1" })), "/shared/holes.py:3:1-4:1");
  assert.equal(formatPromptReference(featureReference({ root: "/work/bracket/", pick: featurePick(BRACKET, "b1"), label: "Fillet1" })),
    "/work/bracket/bracket.py:15:1-16:1");
});

test("names a statement written over several lines as all of them, to the end the engine read", () => {
  // A hole written over lines 17 to 20: the range runs to the start of the line after its last, so the agent has it whole.
  const spread = featureTree({ ...BRACKET_STATE, features: BRACKET_STATE.features.map(feature => (feature.key === "h1" ? { ...feature, end: 20 } : feature)) });
  const reference = featureReference({ root: "/work/bracket", pick: featurePick(spread, "h1"), label: "Hole1" });
  assert.deepEqual(reference.target, { kind: "text-range", start: { line: 16, character: 0 }, end: { line: 20, character: 0 } });
  assert.equal(formatPromptReference(reference), "/work/bracket/bracket.py:17:1-21:1");
  // An end the engine did not read, or one before the line, keeps the line alone.
  for (const end of [null, undefined, 16, 17.5, "20"]) {
    const read = featureTree({ ...BRACKET_STATE, features: BRACKET_STATE.features.map(feature => (feature.key === "h1" ? { ...feature, end } : feature)) });
    assert.equal(formatPromptReference(featureReference({ root: "/work/bracket", pick: featurePick(read, "h1"), label: "Hole1" })),
      "/work/bracket/bracket.py:17:1-18:1", String(end));
  }
});

test("makes no reference where it would have to guess: no project, no file or line, a path the prompt refuses", () => {
  const hole = featurePick(BRACKET, "h1");
  assert.equal(featureReference({ root: "", pick: hole, label: "Hole1" }), null);
  const moved = (patch) => ({ ...hole, feature: { ...hole.feature, ...patch } });
  assert.equal(featureReference({ root: "/work/bracket", pick: moved({ file: "" }), label: "Hole1" }), null);
  assert.equal(featureReference({ root: "/work/bracket", pick: moved({ line: 0 }), label: "Hole1" }), null);
  assert.equal(featureReference({ root: "/work/bracket", pick: moved({ line: undefined }), label: "Hole1" }), null);
  assert.equal(featureReference({ root: "/work/bracket", pick: moved({ file: "../other.py" }), label: "Hole1" }), null);
  // A sketch the script does not name has no place of its own to point at, and the feature's is not its.
  const profile = featurePick(featureTree({ features: [{ key: "e9", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 8,
    sketch: { plane: "Top", status: "" } }] }), "sketch:e9");
  assert.equal(featureReference({ root: "/work/bracket", pick: profile, label: "Sketch1" }), null);
  assert.equal(featureReference({ root: "/work/bracket", pick: null, label: "Hole1" }), null);
});

// What a face is to Quick Edit, as the surface hands it over: a reference in the prompt grammar, and its chip.
const FACE = { resource: STEP, target: { kind: "cad-selector", selectors: ["bracket/face 12"] } };
const FACE_CHIP = { key: "face", label: "bracket · face 12" };
const HOLE = { reference: featureReference({ root: "/work/bracket", pick: featurePick(BRACKET, "h1"), label: "Hole1" }),
  chip: { key: "feature:h1", label: "Hole1" } };

test("carries a face's picks as it always has, the very references and chips the surface read", () => {
  const selection = [FACE], chips = [FACE_CHIP];
  const picked = pickedReferences({ selectionActionVisible: true, selection, selectionChips: chips, feature: null });
  assert.equal(picked.references, selection);
  assert.equal(picked.chips, chips);
  // A selection that cannot be read carries nothing.
  const unread = pickedReferences({ selectionActionVisible: false, selection, selectionChips: chips, feature: null });
  assert.deepEqual([unread.references, unread.chips], [[], []]);
});

test("carries the chosen feature's statement, and its chip, when Ask is on a feature", () => {
  const picked = pickedReferences({ selectionActionVisible: false, selection: [], selectionChips: [], feature: HOLE });
  assert.deepEqual(picked.references, [HOLE.reference]);
  assert.deepEqual(picked.chips, [HOLE.chip]);
  // Beside a selection of parts that can be read, after it.
  const part = { resource: STEP, target: { kind: "cad-selector", selectors: ["bracket"] } };
  const both = pickedReferences({ selectionActionVisible: true, selection: [part], selectionChips: [{ key: "part", label: "base" }], feature: HOLE });
  assert.deepEqual(both.references, [part, HOLE.reference]);
  assert.deepEqual(both.chips.map(chip => chip.key), ["part", "feature:h1"]);
});

test("puts a feature's statement in the context Quick Edit would send, named for the person as the design tree names it", () => {
  const { references } = pickedReferences({ selectionActionVisible: false, selection: [], selectionChips: [], feature: HOLE });
  const context = createQuickEditContext({ resource: STEP, references, text: "Make the hole 3.4 mm." });
  assert.deepEqual(context.parts.map(part => [part.id, part.kind]), [["text", "text"], ["file", "reference"], ["reference-0", "reference"]]);
  const range = context.parts[2].reference;
  assert.deepEqual([range.target.kind, range.label, range.resource.path], ["text-range", "Hole1", "/work/bracket/bracket.py"]);
  assert.equal(formatPromptMessage(context),
    "Make the hole 3.4 mm.\n\nFile: /work/bracket/bracket.step\nReferences:\n/work/bracket/bracket.py:17:1-18:1");
  // A face goes as it did, a selector in the STEP.
  const face = createQuickEditContext({ resource: STEP, references: pickedReferences({ selectionActionVisible: true, selection: [FACE],
    selectionChips: [FACE_CHIP], feature: null }).references, text: "Round it." });
  assert.equal(formatPromptMessage(face), "Round it.\n\nFile: /work/bracket/bracket.step\nReferences:\n/work/bracket/bracket.step#bracket/face 12");
});

test("Quick Edit's X or a send lets go of everything picked, but only of the box while a command holds the picks", () => {
  assert.equal(quickEditLetsGo({ held: false }), "selection");
  // A note written, then Fillet opened and its edges picked: sending the note keeps the edges.
  assert.equal(quickEditLetsGo({ held: true }), "box");
});

test("the strip has Pencil and Shapes in the AI layout and none in the CAD workspace", () => {
  const drawing = [{ id: "pencil" }, { id: "shapes" }];
  assert.deepEqual(stripDrawingTools({ cad: false, drawing }), drawing);
  assert.deepEqual(stripDrawingTools({ cad: true, drawing }), []);
});

test("Quick Edit is handed the picks in the AI layout, and no box at all in the CAD workspace", () => {
  const carried = { references: ["r"], chips: ["c"] }, empty = [];
  assert.deepEqual(quickEditCarries({ cad: false, open: true, carried, empty }), { references: ["r"], chips: ["c"] });
  assert.deepEqual(quickEditCarries({ cad: false, open: false, carried, empty }), { references: empty, chips: empty });
  assert.deepEqual(quickEditCarries({ cad: true, open: true, carried, empty }), { references: null, chips: empty });
});

test("Pencil or Shapes in hand is put down when the CAD workspace is up, and left alone in the AI layout", () => {
  for (const toolMode of ["pencil", "shapes"]) {
    assert.equal(mustPutDownTool({ cad: true, toolMode }), true);
    assert.equal(mustPutDownTool({ cad: false, toolMode }), false);
  }
  for (const toolMode of ["select", "measure", ""]) assert.equal(mustPutDownTool({ cad: true, toolMode }), false);
});

test("none of the agent's pieces shows with CAD chosen while the engine is still asked about the part script", () => {
  const drawing = [{ id: "pencil" }, { id: "shapes" }];
  const carried = { references: ["r"], chips: ["c"] }, empty = [];
  // Chosen, not yet editable: the workspace is not up, and still no Pencil, Shapes or Quick Edit on a pick.
  const cad = cadChosen("manual", { status: "probing" });
  assert.equal(cad, true);
  assert.deepEqual(stripDrawingTools({ cad, drawing }), []);
  assert.equal(quickEditShown({ cad, asked: false, selectionActionVisible: true }), false);
  assert.deepEqual(quickEditCarries({ cad, open: false, carried, empty }), { references: null, chips: empty });
  assert.equal(mustPutDownTool({ cad, toolMode: "pencil" }), true);
  // A model with no part script is the viewer as it is, CAD chosen or not; the AI layout always has them.
  for (const [layout, status] of [["manual", "none"], ["ai", "probing"], ["ai", "ready"]]) {
    const other = cadChosen(layout, { status });
    assert.deepEqual(stripDrawingTools({ cad: other, drawing }), drawing, `${layout} ${status}`);
    assert.equal(quickEditShown({ cad: other, asked: false, selectionActionVisible: true }), true, `${layout} ${status}`);
  }
  for (const status of ["reading", "idle", "ready", "error"]) assert.equal(cadChosen("manual", { status }), true, status);
});
