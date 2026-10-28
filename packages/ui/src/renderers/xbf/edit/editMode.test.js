import assert from "node:assert/strict";
import test from "node:test";

import {
  COMMAND_GROUPS,
  EDIT_COMMANDS,
  barIndex,
  buildingText,
  clickOffsets,
  busyState,
  changeNote,
  changesSince,
  chooseLine,
  chooseSteps,
  commandBlocked,
  commandDefaults,
  commandNote,
  commandRequest,
  edgeAxis,
  extrudeEnd,
  partSide,
  patternAxis,
  commandUndoNote,
  defaultRow,
  deleteNote,
  reorderNote,
  revolveSweep,
  inertiaRows,
  deleteRefusal,
  editingValues,
  planeDetail,
  planeMode,
  pullOf,
  draftRows,
  interferenceRows,
  parameterNote,
  planePreview,
  referencePlanes,
  appearanceNote,
  renameNote,
  draggedDepth,
  emptyHistory,
  extrudePreview,
  massRows,
  draggedAngle,
  draftPreview,
  draftReversed,
  holePreview,
  mirrorOutline,
  midPlanePreview,
  mirrorPreview,
  STANDARD_VIEWS,
  patternArrow,
  patternPreview,
  plainNumber,
  planeOutline,
  faceOffsetAxes,
  featureNames,
  featureTree,
  formulaWords,
  recordChange,
  redoStep,
  restates,
  rolledBack,
  mateNote,
  timeAgo,
  compareVolume,
  drawingNote,
  sameValues,
  selectionItems,
  selectionLabel,
  sizeName,
  suppressNote,
  undoStep,
  withUnit,
  notASketch,
  redrawJob
} from "./editMode.js";

test("a size reads as an engineer says it", () => {
  assert.equal(sizeName("TRAY_HEIGHT"), "Tray height");
  assert.equal(sizeName("wallThickness"), "Wall thickness");
  assert.equal(sizeName("PCB_OD"), "PCB OD");
  assert.equal(sizeName(".060"), ".060");
  assert.equal(withUnit(".060", "in"), ".060 in");
  assert.equal(withUnit("45", ""), "45");
});

test("the history is numbered as a CAD tree numbers it, the script's names beside", () => {
  const names = featureNames([
    { key: "a", kind: "Extrude", name: "outer" },
    { key: "b", kind: "Fillet", name: "outer" },
    { key: "c", kind: "Extrude", name: "cavity" },
    { key: "d", kind: "Join", name: null },
  ]);
  assert.deepEqual(names.map(name => [name.title, name.name]), [["Extrude1", "Outer"], ["Fillet1", "Outer"], ["Extrude2", "Cavity"], ["Combine1", ""]]);
});

test("edit mode opens on the first feature that draws dimensions", () => {
  const state = { rows: [{ key: "a" }, { key: "b" }], dimensions: [{ id: "1", row: "b" }] };
  assert.equal(defaultRow(state), "b");
  assert.equal(defaultRow({ rows: [{ key: "a" }], dimensions: [] }), "a");
  assert.equal(defaultRow(null), null);
});

test("a formula reads in words, and one that only restates its value is not shown twice", () => {
  assert.equal(formulaWords("LENGTH-2*WALL"), "Length - 2 × Wall");
  assert.ok(restates("20", "20"));
  assert.ok(!restates("LENGTH-2*WALL", "2.68"));
});

test("a hand change's note says what changed and where", () => {
  assert.equal(changeNote({ name: "LENGTH", from: "2.80", to: "3.00", file: "parts/housing_geometry.py", line: 8 }),
    "In edit mode I changed Length (LENGTH) from 2.80 to 3.00 (parts/housing_geometry.py, line 8).");
});

test("a build in progress says how far it has got", () => {
  assert.equal(buildingText({ scripts: ["a.py", "b.py"], done: 1, error: null }), "Building the parts, 1 of 2");
  assert.equal(buildingText({ scripts: ["a.py"], done: 1, error: null }), "");
  assert.equal(buildingText({ scripts: ["a.py"], done: 1, error: "a.py: failed" }), "A part did not build");
});

test("undo writes a change's number back, and redo writes it again", () => {
  const change = { literal: "sizes.py:2:8", from: "20", to: "25" };
  let history = recordChange(emptyHistory(), change);
  const undo = undoStep(history);
  assert.deepEqual(undo.request, { literal: "sizes.py:2:8", text: "20" });
  history = undo.next;
  assert.equal(undoStep(history), null);
  const redo = redoStep(history);
  assert.deepEqual(redo.request, { literal: "sizes.py:2:8", text: "25" });
  // A new change after an undo leaves nothing to redo.
  assert.equal(redoStep(recordChange(history, { literal: "x", from: "1", to: "2" })), null);
});

test("a delete the server refuses names the features that use what it makes", () => {
  const tree = featureTree({ features: [
    { key: "tray.py:7", kind: "Boss-Extrude", rows: ["tray.py:7"], file: "tray.py", line: 7, name: "outer" },
    { key: "tray.py:8", kind: "Fillet", rows: ["tray.py:8"], file: "tray.py", line: 8, name: "outer" },
    { key: "tray.py:9", kind: "Cut-Extrude", rows: ["tray.py:9", "tray.py:10"], file: "tray.py", line: 9, name: "cavity" },
  ] });
  const refused = { ok: false, error: "Boss-Extrude1 makes outer, which line 8 still uses.", dependents: { name: "outer", lines: [8, 10], file: "tray.py" } };
  assert.equal(deleteRefusal(refused, tree, "Boss-Extrude1"), "Boss-Extrude1 is used by Fillet1 and Cut-Extrude1. Delete them first, or ask the agent.");
  // Lines no feature holds: the server's own words.
  assert.equal(deleteRefusal({ ...refused, dependents: { name: "outer", lines: [40], file: "tray.py" } }, tree, "Boss-Extrude1"), refused.error);
  const change = { kind: "delete", title: "Fillet1", file: "tray.py", line: 8 };
  assert.equal(deleteNote(change), "In edit mode I deleted Fillet1 (tray.py, line 8).");
  assert.equal(deleteNote(change, { undo: true }), "In edit mode I put back Fillet1 (tray.py, line 8).");
  // Confirm Delete's child features, by the titles it named them with.
  assert.equal(deleteNote({ ...change, title: "Boss-Extrude1", line: 7, children: ["Fillet1", "Cut-Extrude1"] }),
    "In edit mode I deleted Boss-Extrude1 and its child features Fillet1 and Cut-Extrude1 (tray.py, line 7).");
  const moved = { kind: "reorder", title: "Hole1", place: "above Boss-Extrude2", file: "tray.py", line: 11 };
  assert.equal(reorderNote(moved), "In edit mode I moved Hole1 above Boss-Extrude2 in the design tree (tray.py, line 11).");
  assert.equal(reorderNote(moved, { undo: true }), "In edit mode I put Hole1 back where it was in the design tree (tray.py, line 11).");
});

test("the rollback bar greys what is below it, and sits past the last item when rolled forward", () => {
  const tree = featureTree({ features: [
    { key: "tray.py:7", kind: "Boss-Extrude", rows: ["tray.py:7"], file: "tray.py", line: 7, name: "outer" },
    { key: "tray.py:8", kind: "Fillet", rows: ["tray.py:8"], file: "tray.py", line: 8, name: "outer" },
    { key: "tray.py:9", kind: "Cut-Extrude", rows: ["tray.py:9", "tray.py:10"], file: "tray.py", line: 9, name: "cavity" },
  ] });
  assert.equal(barIndex(tree, null), 3);
  assert.deepEqual([...rolledBack(tree, null)], []);
  const bar = { before: "tray.py:8", item: "tray.py:8", step: "/cache/tray.step" };
  assert.equal(barIndex(tree, bar), 1);
  assert.deepEqual([...rolledBack(tree, bar)], ["tray.py:8", "tray.py:9"]);
  // A bar whose item is gone (the agent changed the file) is past the last item.
  assert.equal(barIndex(tree, { ...bar, item: "tray.py:40" }), 3);
});

test("a suppressed feature stays in the tree, and its note says its lines are comments", () => {
  const tree = featureTree({ features: [
    { key: "tray.py:7", kind: "Boss-Extrude", rows: ["tray.py:7"], file: "tray.py", line: 7, name: "outer" },
    { key: "suppressed@tray.py:8", kind: "Fillet", rows: [], file: "tray.py", line: 8, name: "outer", suppressed: true },
    { key: "tray.py:10", kind: "Fillet", rows: ["tray.py:10"], file: "tray.py", line: 10, name: "outer" },
  ] });
  // Numbered with the rest, so a feature keeps its title while it is suppressed.
  assert.deepEqual(tree.features.map(f => [f.title, f.suppressed]), [["Boss-Extrude1", false], ["Fillet1", true], ["Fillet2", false]]);
  const change = { kind: "suppress", on: true, title: "Fillet1", file: "tray.py", line: 8 };
  assert.equal(suppressNote(change), "In edit mode I suppressed Fillet1: its lines are comments now (tray.py, line 8).");
  assert.equal(suppressNote(change, { undo: true }), "In edit mode I unsuppressed Fillet1: its lines are back (tray.py, line 8).");
  assert.equal(suppressNote({ ...change, on: false }, { redo: true }), "In edit mode I unsuppressed Fillet1 again: its lines are back (tray.py, line 8).");
  const refused = { ok: false, error: "", dependents: { name: "outer", lines: [10], file: "tray.py" } };
  assert.equal(deleteRefusal(refused, tree, "Boss-Extrude1", "Suppress"), "Boss-Extrude1 is used by Fillet2. Suppress it first, or ask the agent.");
});

test("Edit Feature opens a command with the feature's values and writes its line again", () => {
  const editing = { id: "a.py:9", title: "Fillet1", command: "fillet", values: { radius: ".05" }, keeps: "4 edges" };
  const opened = editingValues(editing, "in");
  assert.deepEqual(opened, { radius: ".05" });
  assert.ok(sameValues({ radius: " .05" }, opened));
  assert.ok(!sameValues({ radius: ".06" }, opened));
  // What the feature acts on stays as it is unless edges are picked again (on the body before it),
  // so none is waited for.
  const items = selectionItems([EDGE]);
  assert.deepEqual(commandRequest("fillet", { radius: ".06" }, [], null, null, editing),
    { command: "fillet", selection: [], inputs: { radius: ".06" }, replace: { row: "a.py:9" } });
  assert.deepEqual(commandRequest("fillet", { radius: ".06" }, items, null, null, editing).selection, items);
  assert.equal(commandBlocked("fillet", [], null, {}, editing), "");
  const [face] = selectionItems([FACE]);
  assert.equal(commandBlocked("hole", [face, { ...face, selector: "f2" }], null, {}, { ...editing, command: "hole" }), "Select one face.");
  const sketch = { file: "a.py", line: 4, title: "Sketch1", constrained: true };
  assert.deepEqual(commandRequest("extrude", { end: "mid", depth: "8", reverse: false }, [], null, sketch, { ...editing, command: "extrude" }), {
    command: "extrude", sketch: { file: "a.py", line: 4, name: "Sketch1" }, inputs: { end: "mid", depth: "8", reverse: false },
    replace: { row: "a.py:9" },
  });
  const change = { kind: "command", edited: true, feature: "Fillet", what: "4 edges", inputs: [{ label: "Radius", display: "0.06", unit: "in" }],
    file: "a.py", line: 9 };
  assert.equal(commandNote(change, "Fillet1"), "In edit mode I changed Fillet1 to radius 0.06 in, 4 edges (a.py, line 9).");
  assert.equal(commandUndoNote(change, "Fillet1", false), "In edit mode I put Fillet1 back as it was (a.py, line 9).");
  assert.equal(commandUndoNote(change, "Fillet1", true), "In edit mode I changed Fillet1 again (a.py, line 9).");
});

test("a sketch session's changes are counted from the change before it, past the history's limit", () => {
  const before = { literal: "a", from: "1", to: "2" };
  let history = recordChange(emptyHistory(), before);
  assert.equal(changesSince(history, before), 0);
  for (let stroke = 0; stroke < 60; stroke += 1) history = recordChange(history, { undo: { hunks: [] }, stroke });
  // The history keeps its last 50 changes: all of them the session's once `before` has gone.
  assert.equal(changesSince(history, before), 50);
  assert.equal(changesSince(recordChange(recordChange(emptyHistory(), before), { stroke: 0 }), before), 1);
  assert.equal(changesSince(recordChange(emptyHistory(), { stroke: 0 }), null), 1);
});

// The viewer's references for a face and an edge, as the selector runtime hands them over.
const EDGE = { selectorType: "edge", displaySelector: "e3", pickData: { curveType: "line", center: [0, 5, 2], length: 20 } };
const FACE = { selectorType: "face", displaySelector: "f1", pickData: { surfaceType: "plane", center: new Float32Array([0, 0, 2]), area: 200 } };

test("a selection is each face and edge by its selector, with what the viewer read of it", () => {
  const items = selectionItems([EDGE, FACE, { selectorType: "occurrence", displaySelector: "o1" }]);
  assert.deepEqual(items, [
    { selector: "e3", type: "line", center: [0, 5, 2], size: 20 },
    { selector: "f1", type: "plane", center: [0, 0, 2], size: 200 },
  ]);
  assert.deepEqual(items.map(selectionLabel), ["Edge 3", "Face 1"]);
  // The xbf viewer's picks, by the engine's refs: the same items, labelled the same.
  const engine = selectionItems([{ ...EDGE, displaySelector: "plate/edge 3" }, { ...FACE, displaySelector: "plate/face 1" }]);
  assert.deepEqual(engine.map(item => item.selector), ["plate/edge 3", "plate/face 1"]);
  assert.deepEqual(engine.map(selectionLabel), ["Edge 3", "Face 1"]);
});

test("a command sends what it acts on, its inputs as typed, and the feature it copies", () => {
  const items = selectionItems([EDGE, FACE]);
  assert.deepEqual(commandRequest("fillet", { radius: ".03" }, items, { row: "a.py:4" }),
    { command: "fillet", selection: items, inputs: { radius: ".03" } });
  // A hole takes the face alone, through all unless a depth is set, moved only where it is told; an
  // inch part's opens as a #4-40 screw's clearance hole, and says so.
  const hole = commandRequest("hole", { ...commandDefaults("hole", "in"), through: true, y: ".2" }, items);
  assert.deepEqual([hole.selection, hole.inputs],
    [[items[1]], { diameter: ".1285", depth: "", y: ".2", callout: "#4-40 clearance hole, normal fit" }]);
  assert.equal(commandRequest("hole", { ...commandDefaults("hole", "mm"), through: false }, items).inputs.depth, "5");
  assert.deepEqual(commandRequest("pattern", { type: "linear", direction: "Y", spacing: "10", count: "3", reverse: true }, items,
    { row: "a.py:4", name: "Hole1" }), {
    command: "pattern", selection: [], inputs: { type: "linear", count: "3", direction: "Y", spacing: "-(10)" },
    feature: { row: "a.py:4", name: "Hole1" },
  });
  assert.deepEqual(commandRequest("mirror", commandDefaults("mirror", "mm"), [], null), { command: "mirror", selection: [], inputs: { plane: "YZ" } });
});

test("a command's OK waits for what it acts on", () => {
  const [edge, face] = selectionItems([EDGE, FACE]);
  assert.equal(commandBlocked("fillet", []), "Select edges on the model.");
  assert.equal(commandBlocked("fillet", [edge]), "");
  assert.equal(commandBlocked("hole", [edge]), "Select a flat face on the model.");
  assert.equal(commandBlocked("hole", [face, { ...face, selector: "f2" }]), "Select one face.");
  assert.equal(commandBlocked("shell", [face]), "");
  assert.equal(commandBlocked("mirror", []), "");
  assert.equal(commandBlocked("pattern", []), "");
});

test("Choose names the pick still wanted, in order, and none once each is made", () => {
  const [edge, face] = selectionItems([EDGE, FACE]);
  const line = (id, picks = {}) => chooseLine(chooseSteps(id, picks));
  assert.equal(line("fillet"), "1 of 1: Select edges to round");
  assert.equal(line("fillet", { listed: [edge] }), null);
  // A reopened feature keeps what it acts on until others are picked.
  assert.equal(line("chamfer", { kept: true }), null);
  assert.equal(line("hole", { listed: [face, { ...face, selector: "f2" }] }), "1 of 1: Select a flat face for the hole");
  // An extrude takes its sketch first, then what an Up To Surface ends on.
  const sketch = { title: "Sketch1" };
  assert.equal(line("extrude", { values: { end: "surface" } }), "1 of 2: Select a sketch");
  assert.equal(line("extrude", { sketch, values: { end: "surface" } }), "2 of 2: Select a flat face to end on");
  assert.equal(line("extrude", { sketch, values: { end: "surface" }, ending: face }), null);
  assert.equal(line("extrude", { sketch, values: { end: "blind" } }), null);
  assert.equal(line("revolve", { sketch, values: { axis: "" } }), "2 of 2: Select a centerline to revolve about");
  // Mirror and Pattern have what they need as they open.
  assert.equal(line("mirror"), null);
  assert.equal(line("pattern"), null);
});

test("a hole moves along the two axes that lie in its face, or all three on a slanted one", () => {
  assert.deepEqual(faceOffsetAxes([0, 0, 1]), ["x", "y"]);
  assert.deepEqual(faceOffsetAxes([-1, 0, 0]), ["y", "z"]);
  assert.deepEqual(faceOffsetAxes([0, -1, 0]), ["x", "z"]);
  assert.deepEqual(faceOffsetAxes([0.6, 0.8, 0]), ["x", "y", "z"], "a slanted face moves its hole in all three");
});

test("a command's note says what was added and where, and Undo takes its lines back", () => {
  const change = { kind: "command", feature: "Fillet", what: "4 edges", inputs: [{ label: "Radius", display: "0.02", unit: "in" }],
    file: "parts/tray.py", line: 37, undo: { file: "parts/tray.py", hunks: [] }, redo: { file: "parts/tray.py", hunks: [] } };
  assert.equal(commandNote(change, "Fillet2"), "In edit mode I added Fillet2, radius 0.02 in, 4 edges (parts/tray.py, line 37).");
  assert.equal(commandUndoNote(change, "Fillet2", false), "In edit mode I removed Fillet2 (parts/tray.py, line 37).");
  assert.equal(commandUndoNote(change, "Fillet2", true), "In edit mode I added Fillet2 again (parts/tray.py, line 37).");
  const history = recordChange(emptyHistory(), change);
  assert.deepEqual(undoStep(history).request, { splice: change.undo });
  assert.deepEqual(redoStep(undoStep(history).next).request, { splice: change.redo });
});

test("the design tree numbers features by kind and sketches in order, as SolidWorks does", async () => {
  const { featureTree, treeIds, selectionDimensions, planeOutline } = await import("./editMode.js");
  const state = {
    features: [
      { key: "p.py:3", kind: "Boss-Extrude", name: "outer", rows: ["p.py:3"], sketch: { op: "RectangleRounded", plane: "Top" } },
      { key: "p.py:4", kind: "Fillet", name: "outer", rows: ["p.py:4"], sketch: null },
      { key: "p.py:5", kind: "Cut-Extrude", name: "cavity", rows: ["p.py:5", "p.py:6"], sketch: { op: "Rectangle", plane: "Top" } },
      { key: "p.py:7", kind: "Boss-Extrude", name: "pad", count: 2, rows: ["p.py:7", "p.py:8"], sketch: { op: "Rectangle", plane: "Top" } },
    ],
    dimensions: [{ id: "1:x", row: "p.py:5" }, { id: "1:z", row: "p.py:5" }, { id: "0:x", row: "p.py:3" }],
  };
  const tree = featureTree(state);
  assert.deepEqual(tree.features.map(f => [f.title, f.name, f.sketch?.title || ""]),
    [["Boss-Extrude1", "Outer", "Sketch1"], ["Fillet1", "Outer", ""], ["Cut-Extrude1", "Cavity", "Sketch2"], ["Boss-Extrude2", "Pad", "Sketch3"]]);
  assert.ok(treeIds(tree).has("plane:Top") && treeIds(tree).has("origin") && treeIds(tree).has("sketch:p.py:5"));
  // A feature draws its sketch's sizes and its depth; its sketch draws the sizes alone.
  assert.deepEqual(selectionDimensions(state, tree, "p.py:5").map(d => d.id), ["1:x", "1:z"]);
  assert.deepEqual(selectionDimensions(state, tree, "sketch:p.py:5").map(d => d.id), ["1:x"]);
  assert.deepEqual(selectionDimensions(state, tree, "plane:Top"), []);
  // The Top plane is a square through the origin on XY, a little larger than the part.
  const top = planeOutline("Top", [[-10, -5, 0], [10, 5, 4]]);
  assert.ok(top.every(([, , z]) => z === 0) && Math.abs(top[2][0] - 11.5) < 1e-9);
});

test("an assembly's tree lists its parts as components, each numbered on its own", async () => {
  const { featureTree } = await import("./editMode.js");
  const tree = featureTree({ components: [
    { name: "daisy_tray", file: "parts/daisy_tray.py", features: [{ key: "h.py:26", kind: "Boss-Extrude", name: "outer", sketch: null }] },
    { name: "daisy_cover", file: "parts/daisy_cover.py", features: [{ key: "h.py:43", kind: "Boss-Extrude", name: "lid", sketch: null }] },
  ] });
  assert.ok(tree.assembly);
  assert.deepEqual(tree.components.map(c => [c.title, c.features[0].title]), [["Daisy tray<1>", "Boss-Extrude1"], ["Daisy cover<1>", "Boss-Extrude1"]]);
});

test("a feature stands for the lines of the script it is made from, each with its text as the engine read it", async () => {
  const { featureTree } = await import("./editMode.js");
  const state = {
    // The history's rows read their own line as written; a feature's own line is the one it names.
    rows: [
      { key: "box.py:5", file: "box.py", line: 5, code: "profile = Circle(RADIUS)" },
      { key: "box.py:6", file: "box.py", line: 6, code: "body = extrude(profile, amount=HEIGHT)" },
      { key: "box.py:8", file: "box.py", line: 8, code: "body -= Pos(0, 0, 2) * Cylinder(1, 9)" },
    ],
    features: [
      { key: "box.py:6", kind: "Boss-Extrude", name: "body", file: "box.py", line: 6, text: "body = extrude(profile, amount=HEIGHT)",
        rows: ["box.py:5", "box.py:6", "box.py:8"] },
      { key: "sketch@box.py:12", kind: "Sketch", name: null, file: "box.py", line: 12, text: "s = Sketch('Outline', plane='Top')", rows: [],
        sketch: { name: "Outline", file: "box.py", line: 12, plane: "Top" } },
    ],
  };
  const [body, sketch] = featureTree(state).features;
  // Its own line first, then those folded into it: its profile's and the cut joined to it. This engine read no
  // statement's last line (`end`).
  assert.deepEqual(body.lines, [
    { file: "box.py", line: 6, end: null, text: "body = extrude(profile, amount=HEIGHT)" },
    { file: "box.py", line: 5, end: null, text: "profile = Circle(RADIUS)" },
    { file: "box.py", line: 8, end: null, text: "body -= Pos(0, 0, 2) * Cylinder(1, 9)" },
  ]);
  assert.deepEqual(sketch.lines, [{ file: "box.py", line: 12, end: null, text: "s = Sketch('Outline', plane='Top')" }]);
  // An older engine gives a feature no text: its lines say where they are, and nothing of what they read.
  const older = featureTree({ features: [{ key: "box.py:6", kind: "Boss-Extrude", file: "box.py", line: 6, rows: ["box.py:6"] }] });
  assert.deepEqual(older.features[0].lines, [{ file: "box.py", line: 6, end: null, text: "" }]);
});

test("what edit mode is busy with is said, with how far a rebuild has got", () => {
  assert.deepEqual(busyState({ status: "reading" }), { text: "Reading the part", progress: null });
  assert.deepEqual(busyState({ status: "ready", rolling: true }), { text: "Rolling back", progress: null });
  assert.deepEqual(busyState({ status: "ready", saving: true, sketch: {} }), { text: "Solving", progress: null });
  assert.deepEqual(busyState({ status: "ready", saving: true }), { text: "Rebuilding", progress: null });
  const building = { scripts: ["a.py", "b.py", "c.py"], done: 1, error: null };
  assert.deepEqual(busyState({ status: "ready", state: { building } }), { text: "Building the parts, 1 of 3", progress: 33 });
  assert.equal(busyState({ status: "ready", state: { building: { ...building, done: 3 } } }), null);
  assert.equal(busyState({ status: "ready", state: { building: { ...building, error: "failed" } } }), null);
});

test("a cut goes toward the part: which side of a sketch's plane the part lies on", () => {
  const bounds = [[-10, -5, 0], [10, 5, 4]];
  const on = (z, normal = 1) => ({ state: { frame: { origin: [0, 0, z], z: [0, 0, normal] } } });
  assert.equal(partSide(on(4), bounds), -1, "a sketch on the top face: the part is behind it");
  assert.equal(partSide(on(-3), bounds), 1, "a plane under the part: the part is in front");
  assert.equal(partSide(on(2), bounds), 0, "a plane through the part");
  assert.equal(partSide(on(0, -1), bounds), -1, "the bottom face, its normal out of the part");
  assert.equal(partSide({ state: {} }, bounds), 0);
});

test("an extrude's draft and Up To Next, and a hole's counterbore or countersink, go to the command", () => {
  const sketch = { file: "part.py", line: 9, title: "Sketch2" };
  const drafted = commandRequest("extrude", { end: "blind", depth: "5", reverse: false, draft: true, draft_angle: "3", outward: true }, [], null, sketch);
  assert.deepEqual(drafted.inputs, { end: "blind", depth: "5", reverse: false, draft: true, draft_angle: "3", outward: true });
  const next = commandRequest("cut", { end: "next", depth: "5", reverse: true, draft: true, draft_angle: "3" }, [], null, sketch);
  assert.deepEqual(next.inputs, { end: "next" });
  // Direction 2: the other way, Blind or (for a cut) Through All, with its own draft; never at Mid Plane.
  const both = commandRequest("extrude", { end: "blind", depth: "6", reverse: false, direction2: true, end2: "blind", depth2: "14", draft2: true,
    draft_angle2: "2" }, [], null, sketch);
  assert.deepEqual(both.inputs, { end: "blind", depth: "6", reverse: false, direction2: true, end2: "blind", depth2: "14", draft2: true,
    draft_angle2: "2", outward2: false });
  assert.deepEqual(commandRequest("cut", { end: "blind", depth: "2", reverse: false, direction2: true, end2: "through", depth2: "14" }, [], null, sketch).inputs,
    { end: "blind", depth: "2", reverse: false, direction2: true, end2: "through" });
  assert.deepEqual(commandRequest("extrude", { end: "mid", depth: "6", direction2: true, depth2: "4" }, [], null, sketch).inputs,
    { end: "mid", depth: "6", reverse: false });
  // Up To a face, Direction 2 goes the other side of the plane from it, which the server works out.
  const flat = { selector: "f1", type: "plane", center: [0, 0, -14], size: 800 };
  assert.deepEqual(commandRequest("extrude", { end: "surface", direction2: true, end2: "blind", depth2: "5" }, [flat], null, sketch),
    { command: "extrude", sketch: { file: "part.py", line: 9, name: "Sketch2" }, selection: [flat],
      inputs: { end: "surface", direction2: true, end2: "blind", depth2: "5" } });
  const face = [{ selector: "f6", type: "plane" }];
  const bored = commandRequest("hole", { type: "counterbore", diameter: "3", through: true, cbore_diameter: "6", cbore_depth: "3" }, face);
  assert.deepEqual(bored.inputs, { diameter: "3", depth: "", type: "counterbore", cbore_diameter: "6", cbore_depth: "3" });
  const sunk = commandRequest("hole", { type: "countersink", diameter: "3", through: false, depth: "8", csk_diameter: "6", csk_angle: "90" }, face);
  assert.deepEqual(sunk.inputs, { diameter: "3", depth: "8", type: "countersink", csk_diameter: "6", csk_angle: "90" });
  assert.deepEqual(commandRequest("hole", { type: "simple", diameter: "3", through: true }, face).inputs, { diameter: "3", depth: "" });
  // The same hole at each other place clicked on its face, by its offsets as typed.
  assert.deepEqual(commandRequest("hole", { type: "simple", diameter: "3", through: true, x: "5", more: [{ x: "-5", y: "0" }, { x: "0", y: " 2.5 " }] }, face).inputs,
    { diameter: "3", depth: "", x: "5", more: [{ x: "-5", y: "0" }, { x: "0", y: "2.5" }] });
  // A list of places compares by what it holds: one taken out is a change to write.
  assert.equal(sameValues({ more: [{ x: "1" }] }, { more: [{ x: "1" }] }), true);
  assert.equal(sameValues({ more: [{ x: "1" }] }, { more: [{ x: "2" }] }), false);
});

test("a click on a face puts the hole there: its distance from the face's center, in the part's units", () => {
  const center = [10, 5, 4];
  assert.deepEqual(clickOffsets([22.5, 1.004, 4], center, [0, 0, 1], "mm"), { x: "12.5", y: "-4" });
  assert.deepEqual(clickOffsets([10, 5, 4.0001], center, [0, 0, 1], "mm"), { x: "0", y: "0" });
  assert.deepEqual(clickOffsets([10 + 25.4, 5, 4 - 12.7], center, [0, 1, 0], "in"), { x: "1", z: "-0.5" });
  assert.deepEqual(clickOffsets([14, 5, 1], center, [0.6, 0, 0.8], "mm"), { x: "4", y: "0", z: "-3" }, "a slanted face's, in all three");
  assert.equal(clickOffsets(null, center, [0, 0, 1], "mm"), null);
});

test("a straight edge picked for a pattern gives its direction, X, Y or Z, the last one counting", () => {
  const edge = (min, max, curveType = "line") => ({ selectorType: "edge", pickData: { curveType, bbox: { min, max } } });
  assert.equal(edgeAxis([edge([0, 2, 4], [20, 2, 4])]), "X");
  assert.equal(edgeAxis([edge([0, 2, 4], [20, 2, 4]), edge([5, -3, 0], [5, 7, 0])]), "Y");
  assert.equal(edgeAxis([edge([0, 0, 0], [0, 0, 8])]), "Z");
  assert.equal(edgeAxis([edge([0, 0, 0], [6, 8, 0])]), null, "a slanted edge");
  assert.equal(edgeAxis([edge([0, 0, 0], [6, 6, 0], "circle")]), null, "a curved edge");
  assert.equal(edgeAxis([{ selectorType: "face", pickData: {} }]), null);
});

test("a circular pattern turns about the round face or straight edge picked last, and sends it", () => {
  const round = { selector: "f7", type: "cylinder", center: [5, 5, 4], size: 100.5 };
  const flat = { selector: "f2", type: "plane", center: [0, 0, 2], size: 1600 };
  const straight = { selector: "e3", type: "line", center: [20, 20, 0], size: 4 };
  assert.equal(patternAxis([flat]), null, "a flat face has no axis: Z through the origin");
  assert.equal(patternAxis([round, flat]), round);
  assert.equal(patternAxis([round, straight]), straight);
  const feature = { row: "a.py:4", name: "Hole1" };
  assert.deepEqual(commandRequest("pattern", { type: "circular", count: "6" }, [flat, round], feature),
    { command: "pattern", selection: [round], inputs: { type: "circular", count: "6" }, feature });
  assert.deepEqual(commandRequest("pattern", { type: "circular", count: "6" }, [], feature).selection, []);
  // Its Angle and Reverse direction, sent once they are not all the way round one way.
  assert.deepEqual(commandRequest("pattern", { type: "circular", count: "4", angle: "90", reverse: true }, [round], feature).inputs,
    { type: "circular", count: "4", angle: "90", reverse: true });
  // Edit Feature keeps its axis unless another is picked.
  const editing = { id: "a.py:9", command: "pattern" };
  assert.deepEqual(commandRequest("pattern", { type: "circular", count: "8" }, [], null, null, editing),
    { command: "pattern", selection: [], inputs: { type: "circular", count: "8" }, replace: { row: "a.py:9" } });
});

test("an extrude Up To Surface ends on the flat face picked, Up To Vertex at the clicked edge's end", () => {
  const flat = { selector: "f2", type: "plane", center: [0, 0, -2.5], size: 800 };
  const round = { selector: "f7", type: "cylinder", center: [5, 5, 4], size: 100.5 };
  const edge = { selector: "e3", type: "line", center: [0, -10, -7.5], size: 40 };
  assert.equal(extrudeEnd("surface", [flat, round]), flat, "a round face is not one to end on");
  assert.equal(extrudeEnd("vertex", [flat, edge]), edge);
  assert.equal(extrudeEnd("blind", [flat]), null);
  const sketch = { file: "plate.py", line: 9, title: "Sketch1", constrained: true };
  const values = { ...commandDefaults("extrude", "mm"), end: "surface" };
  assert.deepEqual(commandRequest("extrude", values, [flat], null, sketch),
    { command: "extrude", sketch: { file: "plate.py", line: 9, name: "Sketch1" }, inputs: { end: "surface" }, selection: [flat] });
  assert.equal(commandBlocked("extrude", [], sketch, values), "Select a flat face on the model to end on.");
  const atVertex = { ...values, end: "vertex", vertex_at: [-19, -10, -7.4] };
  assert.deepEqual(commandRequest("extrude", atVertex, [edge], null, sketch).inputs, { end: "vertex", vertex_at: [-19, -10, -7.4] });
  assert.equal(commandBlocked("extrude", [edge], sketch, { ...atVertex, vertex_at: undefined }), "Click near the end of an edge on the model.");
  assert.equal(commandBlocked("extrude", [edge], sketch, atVertex), "");
  // Edit Feature keeps what it ends on, so it waits on no pick.
  assert.equal(commandBlocked("extrude", [], sketch, values, { values: { end: "surface" } }), "");
});

// The fields of an answer a test reads.
const pick = (object, keys) => Object.fromEntries(keys.map(key => [key, object?.[key]]));

test("an extrude's preview sweeps its depth in millimetres with an arrow the way it goes, or draws the arrow alone", () => {
  const sketch = { file: "a.py", line: 4 };
  const top = { origin: [0, 0, 10], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
  const opened = commandDefaults("extrude", "in");
  assert.deepEqual(extrudePreview("extrude", { ...opened, depth: ".25" }, { units: "in", sketch }),
    { kind: "boss", end: "blind", file: "a.py", line: 4, taper: 0, depth: 6.35, reverse: false, units: "in", label: ".25 in" });
  // Mid Plane goes both ways, so Reverse does not apply; Through All is tagged by its name.
  assert.equal(extrudePreview("cut", { ...opened, end: "mid", reverse: true }, { units: "in", sketch }).reverse, false);
  assert.equal(extrudePreview("cut", { ...opened, end: "through" }, { units: "in", sketch }).label, "Through All");
  // Direction 2 goes the other way by its own depth, with its own draft; one written as a name is the server's to sweep.
  assert.deepEqual(pick(extrudePreview("extrude", { ...opened, depth: ".25", direction2: true, depth2: ".5", draft2: true, draft_angle2: "3" },
    { units: "in", sketch }), ["depth", "depth2", "taper2", "label2"]), { depth: 6.35, depth2: 12.7, taper2: 3, label2: ".5 in" });
  assert.equal(extrudePreview("extrude", { ...opened, depth: ".25", direction2: true, depth2: "WALL" }, { units: "in", sketch }).arrowOnly, true);
  // A depth written as a size's name, Up To Next, Up To Surface: the arrow alone, from the sketch.
  assert.deepEqual(pick(extrudePreview("extrude", { ...opened, depth: "WALL" }, { sketch }), ["arrowOnly", "label"]), { arrowOnly: true, label: "Wall" });
  assert.deepEqual(pick(extrudePreview("extrude", { ...opened, end: "next" }, { sketch }), ["arrowOnly", "reverse", "label"]),
    { arrowOnly: true, reverse: false, label: "Up To Next" });
  // Up To Surface goes the side of the sketch's plane its face is: below it here.
  const below = { selector: "f2", type: "plane", center: [0, 0, 2] };
  assert.equal(extrudePreview("extrude", { ...opened, end: "surface" }, { sketch, frame: top, ending: below }).reverse, true);
  assert.equal(extrudePreview("extrude", opened, {}), null);
  assert.equal(plainNumber("2*WALL"), null);
});

test("a linear pattern's arrow runs from the feature it copies to its first copy, from where the copies are", () => {
  const mark = patternPreview({ type: "linear", direction: "Y", spacing: "10", count: "3", reverse: true }, "mm");
  assert.deepEqual(mark, { mark: "pattern", along: [0, -1, 0], spacing: 10, count: 3, label: "10 mm" });
  // Two copies, 10 and 20 below a feature at the origin, each 2 across.
  const copies = [-1, -11, 0, 1, -9, 1, -1, -21, 0, 1, -19, 1];
  const { from, to } = patternArrow(mark, copies);
  assert.deepEqual([from.map(Math.round), to.map(Math.round)], [[0, 0, 1], [0, -10, 1]].map(point => point.map(Math.round)));
  assert.equal(patternPreview({ type: "circular", count: "6" }), null);
  assert.equal(patternPreview({ type: "linear", direction: "X", spacing: "PITCH", count: "3" }), null);
});

test("a hole's arrow goes into its face where it goes in, and a mirror's plane is drawn about what it mirrors", () => {
  const top = { center: [0, 0, 2], normal: [0, 0, 1] };
  // A distance up the face's normal stays on the face.
  assert.deepEqual(holePreview({ x: "3", y: "-1", z: "5", through: false, depth: "4" }, "mm", top),
    { mark: "hole", at: [3, -1, 2], into: [0, 0, -1], label: "4 mm" });
  assert.equal(holePreview({ through: true }, "mm", top).label, "Through All");
  // Hole Wizard's other positions: an arrow into the face at each, from the face's center.
  assert.deepEqual(holePreview({ x: "3", y: "0", through: true, more: [{ x: "-3" }, { y: "2" }] }, "mm", top).also,
    [[-3, 0, top.center[2]], [0, 2, top.center[2]]]);
  assert.equal(holePreview({}, "mm", null), null);
  const bounds = [[-10, -5, -2], [10, 5, 2]];
  // About an origin plane, as the design tree draws it; about a face, a square on its plane.
  assert.deepEqual(mirrorOutline(mirrorPreview({ plane: "YZ" }), bounds), planeOutline("Right", bounds));
  const side = mirrorOutline(mirrorPreview({ plane: "YZ" }, { center: [10, 0, 0], normal: [1, 0, 0] }), bounds);
  assert.equal(side.length, 4);
  assert.ok(side.every(([x]) => Math.abs(x - 10) < 1e-9));
  assert.equal(mirrorPreview({ plane: "face" }), null);
});

test("a draft asks for its neutral plane, then its faces, and pulls the way the part narrows", () => {
  const side = { selector: "f2", type: "plane", center: [10, 0, 0], size: 40 };
  const bottom = { selector: "f6", type: "plane", center: [0, 0, -2], size: 200 };
  const opened = commandDefaults("draft", "mm");
  assert.deepEqual(opened, { angle: "1", neutral: "", reverse: false });
  assert.equal(chooseLine(chooseSteps("draft", { values: opened })), "1 of 2: Select the neutral plane");
  assert.equal(chooseLine(chooseSteps("draft", { values: { ...opened, neutral: "Top" } })), "2 of 2: Select faces to draft");
  assert.equal(commandBlocked("draft", [side], null, opened), "Select the neutral plane: a flat face on the model, or a plane in the design tree.");
  assert.equal(commandBlocked("draft", [{ ...bottom, neutral: true }], null, { ...opened, neutral: "face" }), "Select the faces to draft.");
  // A neutral face goes apart from the faces it drafts; an origin plane by its name.
  assert.deepEqual(commandRequest("draft", { ...opened, neutral: "face", reverse: true }, [side, { ...bottom, neutral: true }], null),
    { command: "draft", selection: [side], inputs: { angle: "1", neutral: "face", reverse: true }, neutral: bottom });
  assert.deepEqual(commandRequest("draft", { ...opened, neutral: "Front" }, [side], null),
    { command: "draft", selection: [side], inputs: { angle: "1", neutral: "Front", reverse: false } });
  // A reopened draft keeps its faces and its neutral plane as written.
  const editing = { id: "block.py:8", command: "draft", values: { angle: "2", neutral: "face", reverse: true } };
  assert.equal(commandBlocked("draft", [], null, editingValues(editing, "mm"), editing), "");
  assert.deepEqual(commandRequest("draft", editingValues(editing, "mm"), [], null, null, editing),
    { command: "draft", selection: [], inputs: { angle: "2", neutral: "face", reverse: true }, replace: { row: "block.py:8" } });
  // The pull: out of a face as picked, into the part reversed; an origin plane's normal, toward the part.
  assert.deepEqual(draftPreview({ reverse: true }, { center: [0, 0, -2], normal: [0, 0, -1] }).pull, [0, 0, 1]);
  const bounds = [[-10, -5, 0], [10, 5, 4]];
  assert.deepEqual(draftPreview({ neutral: "Top" }, null, bounds), { mark: "draft", plane: "XY", at: [0, 0, 0], pull: [0, 0, 1] });
  assert.deepEqual(mirrorOutline(draftPreview({ neutral: "Right" }, null, bounds), bounds), planeOutline("Right", bounds));
  assert.equal(draftReversed("Top", bounds), false);
  assert.equal(draftReversed("Top", [[-10, -5, -4], [10, 5, 0]]), true);
  // Front Plane faces -Y: a part in front of it, at -Y, is pulled that way as it is.
  assert.equal(draftReversed("Front", [[-10, -8, 0], [10, -2, 4]]), false);
  assert.equal(draftPreview({ neutral: "face" }), null);
});

test("a revolve's arrow dragged turns to the degree nearest the pointer, in steps of 5", () => {
  // Its head's places round a circle of radius 100 about (0, 0), a degree apart.
  const reach = Array.from({ length: 360 }, (_, step) => [100 * Math.cos(((step + 1) * Math.PI) / 180), 100 * Math.sin(((step + 1) * Math.PI) / 180)]);
  assert.deepEqual(draggedAngle(reach, [0, 100]), { text: "90", degrees: 90 });
  assert.deepEqual(draggedAngle(reach, [100 * Math.cos(1.2), 100 * Math.sin(1.2)]), { text: "70", degrees: 70 });
  // Never less than 5, nor more than a full turn.
  assert.equal(draggedAngle(reach, [100, 1]).degrees, 5);
  assert.equal(draggedAngle(reach, [100, -1]).degrees, 360);
});

test("an extrude's arrow dragged sets the depth it reaches, in the part's units to the places the panel shows", () => {
  assert.deepEqual(draggedDepth(12.3456, "blind", "mm"), { text: "12.35", mm: 12.35 });
  // Mid Plane's arrows sit at half the depth; an inch part shows three places.
  assert.equal(draggedDepth(6, "mid", "mm").text, "12");
  assert.equal(draggedDepth(25.4, "blind", "in").text, "1");
  // Dragged back past the sketch: the smallest depth the panel shows.
  assert.equal(draggedDepth(-4, "blind", "mm").text, "0.01");
});

test("a sweep takes its profile then its path, a loft its profiles in order, a rib one sketch and its thickness", () => {
  const sketch = (title, line) => ({ title, file: "a.py", line, constrained: true });
  const [one, two, three] = [sketch("Sketch1", 4), sketch("Sketch2", 7), sketch("Sketch3", 9)];
  assert.deepEqual(commandRequest("sweep", {}, [], null, null, null, [one, two]), { command: "sweep", inputs: {},
    sketches: [{ file: "a.py", line: 4, name: "Sketch1" }, { file: "a.py", line: 7, name: "Sketch2" }] });
  assert.equal(commandBlocked("sweep", [], null, {}, null, [one]), "Select the path sketch.");
  assert.equal(commandBlocked("loft_cut", [], null, {}, null, [one, two, three]), "");
  assert.equal(commandBlocked("loft", [], null, {}, null, [{ ...one, constrained: false }, two]),
    "Sketch1 isn't an editable sketch yet. Ask the agent to loft it.");
  assert.equal(chooseLine(chooseSteps("sweep", { sketches: [one] })), "2 of 2: Select the path sketch");
  assert.equal(chooseLine(chooseSteps("loft", {})), "1 of 2: Select the first profile sketch");
  assert.deepEqual(commandRequest("rib", { thickness: "2", flip: true }, [], null, one), { command: "rib",
    sketch: { file: "a.py", line: 4, name: "Sketch1" }, inputs: { thickness: "2", flip: true } });
  assert.equal(commandBlocked("rib", [], null, commandDefaults("rib", "mm")), "Select a sketch of the rib's line.");
  // The ribbon's groups, as SolidWorks' Features tab sets them out.
  assert.deepEqual(COMMAND_GROUPS.map(group => EDIT_COMMANDS.filter(command => command.group === group).map(command => command.id)),
    [["extrude", "revolve", "sweep", "loft"], ["cut", "revolve_cut", "sweep_cut", "loft_cut", "hole"], ["fillet", "chamfer", "rib", "draft", "shell", "offset_face", "delete_face", "pattern", "mirror", "split", "delete_body"],
      ["plane"]]);
});

test("an extrude's Thin Feature sends its wall, inside the outline unless said otherwise, and is the server's to preview", () => {
  const sketch = { title: "Sketch1", file: "a.py", line: 4, constrained: true };
  const values = { ...commandDefaults("extrude", "mm"), thin: true, thin_thickness: "1.5" };
  assert.deepEqual(commandRequest("extrude", values, [], null, sketch).inputs, { end: "blind", depth: "5", reverse: false, thin: true, thin_thickness: "1.5" });
  assert.equal(commandRequest("extrude", { ...values, thin_side: "mid" }, [], null, sketch).inputs.thin_side, "mid");
  assert.equal(extrudePreview("extrude", values, { sketch }).arrowOnly, true);
});

test("Mass Properties read in the part's units, its mass in the material picked", () => {
  // A 20 x 10 x 4 mm block of PETG, balanced at its middle.
  const block = { volume: 800, area: 640, center: [0, 0, 0], box: [[-10, -5, -2], [10, 5, 2]] };
  assert.deepEqual(massRows(block, "mm", 1.27).map(row => `${row.label}: ${row.value}`), [
    "Mass: 1.02 g", "Volume: 800 mm³", "Surface area: 640 mm²", "Center of mass X: 0 mm", "Center of mass Y: 0 mm",
    "Center of mass Z: 0 mm", "Overall size: 20 x 10 x 4 mm",
  ]);
  // Without a material, no mass; an inch part in ounces, its grams beside them, and in inches.
  assert.equal(massRows(block, "mm")[0].label, "Volume");
  const plate = { volume: 25.4 ** 3 * 2, area: 25.4 ** 2 * 10, center: [25.4, 0, 12.7], box: [[0, 0, 0], [50.8, 25.4, 25.4]] };
  const inch = massRows(plate, "in", 2.7);
  assert.deepEqual([inch[0].value, inch[1].value, inch[3].value, inch[6].value],
    ["3.121 oz (88.49 g)", "2 in³", "1 in", "2 x 1 x 1 in"]);
  assert.equal(massRows({ ...block, volume: 1e6 }, "mm", 7.85)[0].value, "7.85 kg");
});

test("a rename tells the agent the names before and after, and a name taken off says so", () => {
  const change = { kind: "rename", title: "Fillet1", name: "Top edge round", file: "block.py", line: 7 };
  assert.equal(renameNote(change), "In edit mode I renamed Fillet1 to Top edge round (block.py, line 7).");
  assert.equal(renameNote({ ...change, name: "" }), "In edit mode I gave Fillet1 back the design tree's own name (block.py, line 7).");
  assert.equal(renameNote(change, { undo: true }), "In edit mode I took back renaming Fillet1 (block.py, line 7).");
});

test("a color picked tells the agent the hex and where it is written", () => {
  const change = { kind: "appearance", color: "#B7A1D7", file: "parts/tray.py", line: 38 };
  assert.equal(appearanceNote(change), "In edit mode I colored the part #B7A1D7 (parts/tray.py, line 38).");
  assert.equal(appearanceNote(change, { undo: true }), "In edit mode I took back coloring the part #B7A1D7 (parts/tray.py, line 38).");
});

test("a reference plane is offset from an origin plane picked in the tree, or from a face, and says so in the tree", () => {
  const top = { selector: "f1", type: "plane", center: [0, 0, 2], size: 200 };
  const opened = commandDefaults("plane", "mm");
  assert.deepEqual(opened, { reference: "", distance: "5", flip: false, angle: "0", about: "x", end: "start" });
  assert.equal(chooseLine(chooseSteps("plane", { values: opened })), "1 of 1: Select a plane or a flat face to offset from");
  assert.equal(commandBlocked("plane", [], null, opened), "Select a plane in the design tree, or a flat face on the model.");
  assert.deepEqual(commandRequest("plane", { ...opened, reference: "Front" }, [], null),
    { command: "plane", selection: [], inputs: { reference: "Front", distance: "5", flip: false } });
  // A face picked is what it is offset from.
  assert.deepEqual(commandRequest("plane", { ...opened, reference: "Front", flip: true }, [top], null),
    { command: "plane", selection: [top], inputs: { reference: "face", distance: "5", flip: true } });
  // Drawn 10 above the Top Plane over the part's middle, its arrow up; flipped, down.
  const bounds = [[-10, -5, 0], [10, 5, 4]];
  assert.deepEqual(planePreview({ reference: "Top", distance: "10" }, null, bounds),
    { mark: "plane", center: [0, 0, 10], normal: [0, 0, 1], at: [0, 0, 0], along: [0, 0, 1], label: "10 mm" });
  assert.deepEqual(planePreview({ reference: "Top", distance: "1", flip: true }, { center: [0, 0, 2], normal: [0, 0, 1] }, bounds, "in").center,
    [0, 0, 2 - 25.4]);
  assert.equal(planePreview({ reference: "Top", distance: "OFFSET" }, null, bounds), null);
  assert.equal(planeDetail({ edit: { values: { reference: "Top", distance: "10", flip: true } } }, "mm"), "Top Plane, -10 mm");
  assert.equal(planeDetail({ edit: { values: { reference: "face", distance: ".5", flip: false } } }, "in"), "Face, .5 in");
  // At angle: the Front Plane's normal, -Y, turned 30 degrees about its X axis by the right hand; sent with the axis.
  const turned = planePreview({ reference: "Front", distance: "0", angle: "30", about: "x" }, null, bounds);
  assert.deepEqual(turned.normal.map(value => Math.round(value * 1e6) / 1e6 + 0), [0, -0.866025, -0.5]);
  assert.equal(turned.label, "0 mm, 30°");
  assert.deepEqual(commandRequest("plane", { ...opened, reference: "Front", angle: "30", about: "y" }, [], null).inputs,
    { reference: "Front", distance: "5", flip: false, angle: "30", about: "y" });
  assert.equal(planeDetail({ edit: { values: { reference: "Top", distance: "10", flip: false, angle: "15", about: "y" } } }, "mm"),
    "Top Plane, 10 mm, 15° about Y");
});

test("compare says when a version was read and how much material changed, in the part's units", () => {
  assert.equal(timeAgo(1000, 1030), "just now");
  assert.equal(timeAgo(1000, 1000 + 240), "4 min ago");
  assert.equal(timeAgo(1000, 1000 + 7200), "2 h ago");
  assert.equal(compareVolume(4.2920367), "4.29 mm³");
  assert.equal(compareVolume(16387.064, "in"), "1 in³");
  assert.equal(compareVolume(null), "-");
});

test("the agent is told of a drawing made or its sheet changed, and the PDF it wrote", () => {
  assert.equal(drawingNote({ words: "changed its drawing's sheet: revision B", file: "parts/block_drawing.py", pdf: "parts/block_drawing.pdf" }),
    "In edit mode I changed its drawing's sheet: revision B (parts/block_drawing.py); it wrote parts/block_drawing.pdf.");
});

test("the agent is told of a mate made, made again, or taken back, and where", () => {
  const change = { file: "assemblies/stack.py", line: 14, words: "Coincident1: pin face to face with base" };
  assert.equal(mateNote(change), "In edit mode I made a mate of the assembly (assemblies/stack.py, line 14): Coincident1: pin face to face with base.");
  assert.match(mateNote(change, { undo: true }), /^In edit mode I took back a mate/);
  assert.match(mateNote(change, { redo: true }), /made again/);
});

test("the part's reference planes are what a mirror, a draft or a plane can go from, by the names the script holds them in", () => {
  const state = { features: [
    { key: "a.py:6", kind: "Boss-Extrude", name: "part", file: "a.py", line: 6 },
    { key: "a.py:7", kind: "Plane", name: "plane1", file: "a.py", line: 7, named: "Lid line",
      plane: { origin: [0, 0, 10], x: [1, 0, 0], z: [0, 0, 1] } },
  ] };
  const [lid] = referencePlanes(featureTree(state));
  assert.deepEqual(lid, { id: "a.py:7", value: "named:plane1", label: "Lid line", plane: { origin: [0, 0, 10], x: [1, 0, 0], z: [0, 0, 1] } });
  // A part under the plane pulls down from it.
  assert.equal(draftReversed(null, [[-10, -5, 0], [10, 5, 4]], lid.plane), true);
  assert.equal(draftReversed(null, [[-10, -5, 12], [10, 5, 20]], lid.plane), false);
});

test("a chamfer goes as its type says: one distance, a distance each way (flipped), or a distance and an angle", () => {
  const edges = [{ selector: "e1", type: "line", center: [0, -5, 2], size: 20 }];
  const opened = commandDefaults("chamfer", "mm");
  assert.deepEqual(commandRequest("chamfer", opened, edges, null).inputs, { distance: "1" });
  assert.deepEqual(commandRequest("chamfer", { ...opened, type: "distances", distance2: "2", flip: true }, edges, null).inputs,
    { distance: "1", type: "distances", distance2: "2", flip: true });
  assert.deepEqual(commandRequest("chamfer", { ...opened, type: "angle", angle: "30" }, edges, null).inputs,
    { distance: "1", type: "angle", angle: "30" });
  // Flipped, the distance runs along each edge's other face.
  assert.deepEqual(commandRequest("chamfer", { ...opened, type: "angle", angle: "30", flip: true }, edges, null).inputs,
    { distance: "1", type: "angle", angle: "30", flip: true });
  // A reopened chamfer of two distances opens as one.
  const editing = { id: "a.py:7", command: "chamfer", values: { distance: "0.5", type: "distances", distance2: "1" } };
  assert.deepEqual(editingValues(editing, "mm"), { type: "distances", distance: "0.5", distance2: "1", angle: "45", flip: false });
});

test("a Plane's picks say which it is: two faces a Mid Plane, an edge Normal to Curve, else an offset", () => {
  const face = n => ({ selector: `f${n}`, type: "plane" });
  const edge = { selector: "e3", type: "line" };
  assert.equal(planeMode([face(1), face(2)]), "mid");
  assert.equal(planeMode([edge]), "normal");
  assert.equal(planeMode([face(1)]), "offset");
  assert.equal(planeMode([], { values: { mode: "mid" } }), "mid");
  const mid = commandRequest("plane", commandDefaults("plane", "mm"), [face(1), face(2)], null);
  assert.deepEqual(mid.inputs, { mode: "mid" });
  assert.equal(mid.selection.length, 2);
  const normal = commandRequest("plane", { ...commandDefaults("plane", "mm"), end: "end" }, [edge], null);
  assert.deepEqual(normal.inputs, { mode: "normal", end: "end" });
  // Picks named as the xbf viewer names them, by the engine's refs: the same planes.
  const plateFace = n => ({ selector: `plate/face ${n}`, type: "plane" });
  assert.equal(planeMode([plateFace(1), plateFace(2)]), "mid");
  assert.equal(planeMode([{ selector: "plate/edge 3", type: "line" }]), "normal");
  assert.equal(planeMode([plateFace(1)]), "offset");
  const engineMid = commandRequest("plane", commandDefaults("plane", "mm"), [plateFace(1), plateFace(2)], null);
  assert.deepEqual([engineMid.inputs, engineMid.selection.map(item => item.selector)], [{ mode: "mid" }, ["plate/face 1", "plate/face 2"]]);
});

test("Draft Analysis pulls along an origin plane's normal, reversed when asked, and says each class's area", () => {
  assert.deepEqual(pullOf({ plane: "Top" }), [0, 0, 1]);
  assert.deepEqual(pullOf({ plane: "Front", reverse: true }), [0, 1, 0]);
  assert.deepEqual(draftRows({ positive: 200, negative: 200, needs: 240 }, "mm").map(row => row.value), ["200 mm²", "200 mm²", "240 mm²"]);
  assert.equal(draftRows({ positive: 645.16, negative: 0, needs: 0 }, "in")[0].value, "1 in²");
});

test("Interference Detection lists each overlapping pair with its shared volume", () => {
  assert.deepEqual(interferenceRows([{ a: "base", b: "pin", volume: 12.566 }], "mm").map(row => [row.label, row.value]), [["base and pin", "12.6 mm³"]]);
});

test("a parameter added tells the agent its name, value and line", () => {
  const change = { kind: "parameter", name: "WALL", value: "2.5", file: "block.py", line: 4 };
  assert.equal(parameterNote(change), "In edit mode I added the parameter WALL = 2.5 (block.py, line 4).");
  assert.equal(parameterNote(change, { undo: true }), "In edit mode I took back adding the parameter WALL (block.py, line 4).");
});

test("a profile made from build123d's shapes says what it is and how to make it editable", () => {
  assert.equal(notASketch("Sketch1"),
    "Sketch1 isn't an editable sketch yet: it's built from fixed shapes, so only its sizes change, in the panel.");
  assert.equal(redrawJob({ title: "Sketch1", file: "parts/hook.py", line: 12 }),
    "Redraw Sketch1 (parts/hook.py, line 12) as an editable sketch with cadgen.sketch, keeping its shape and sizes, so I can edit it by hand.");
  assert.equal(redrawJob({ title: "Sketch2", file: null, line: null }),
    "Redraw Sketch2 as an editable sketch with cadgen.sketch, keeping its shape and sizes, so I can edit it by hand.");
});

test("a Mid Plane is drawn midway between its two faces, square to the first, and the standard views look as SolidWorks' do", () => {
  const mid = midPlanePreview([{ center: [0, 0, 10], normal: [0, 0, 1] }, { center: [0, 0, -4], normal: [0, 0, -1] }]);
  assert.deepEqual([mid.mark, mid.center, mid.normal], ["plane", [0, 0, 3], [0, 0, 1]]);
  assert.equal(midPlanePreview([{ center: [0, 0, 1], normal: [0, 0, 1] }]), null);
  // Z up, the front looking along +Y; Isometric from the front, right and top.
  assert.deepEqual(STANDARD_VIEWS.front.direction, [0, -1, 0]);
  assert.deepEqual(STANDARD_VIEWS.isometric.direction, [1, -1, 1]);
  assert.deepEqual(Object.keys(STANDARD_VIEWS), ["front", "back", "left", "right", "top", "bottom", "isometric"]);
});


test("a revolve's preview turns from where Mid Plane and Direction 2 start it", () => {
  assert.deepEqual(revolveSweep({ end: "blind" }, 90), { from: -0, angle: 90 });
  assert.deepEqual(revolveSweep({ end: "mid" }, 90), { from: -45, angle: 90 });
  assert.deepEqual(revolveSweep({ end: "blind", direction2: true, angle2: "30" }, 90), { from: -30, angle: 120 });
  assert.deepEqual(revolveSweep({ end: "blind", direction2: true, angle2: "30", reverse: true }, 90), { from: 30, angle: -120 });
});

test("Mass Properties lists the moments of inertia once a material gives the density", () => {
  // A 10 x 20 x 30 box: per unit density Lxx = V(b² + c²)/12 = 650000 mm^5, and so on.
  const mass = { volume: 6000, inertia: [[650000, 0, 0], [0, 500000, 0], [0, 0, 250000]],
    principal: { moments: [250000, 500000, 650000], axes: [[0, 0, 1], [0, 1, 0], [1, 0, 0]] } };
  assert.deepEqual(inertiaRows(mass, "mm"), []);
  const rows = inertiaRows(mass, "mm", 1);
  assert.deepEqual(rows.map(row => row.label), ["Lxx", "Lyy", "Lzz", "Px", "Py", "Pz"]);
  assert.equal(rows[0].value, "650 g·mm²");
  assert.equal(rows[3].value, "250 g·mm² about (0, 0, 1)");
  assert.match(inertiaRows(mass, "in", 1)[0].value, / lb·in²$/);
});
