import assert from "node:assert/strict";
import test from "node:test";

import { EDIT_COMMANDS, featureTree } from "./editMode.js";
import { SOLID_GROUPS, booleanOf, buildFailure, navigatorLabel, navigatorTitles, workspaceTabs } from "./nx.js";

const titles = options => workspaceTabs(options).map(tab => tab.title);

test("lists Features, Sketch and Evaluate, and Assembly only in an assembly", () => {
  assert.deepEqual(titles({ assembly: false, sketching: false, drawing: false }), ["Features", "Sketch", "Evaluate"]);
  assert.deepEqual(titles({ assembly: true, sketching: false, drawing: false }), ["Features", "Sketch", "Evaluate", "Assembly"]);
  assert.deepEqual(workspaceTabs({ assembly: true, sketching: false, drawing: false }).map(tab => tab.id), ["solid", "sketch", "inspect", "assemble"]);
});

test("keeps Drawing where the drawing's commands are, after the rest", () => {
  assert.deepEqual(titles({ assembly: false, sketching: false, drawing: true }), ["Features", "Sketch", "Evaluate", "Drawing"]);
  assert.deepEqual(titles({ assembly: true, sketching: false, drawing: true }), ["Features", "Sketch", "Evaluate", "Assembly", "Drawing"]);
});

test("a sketch being edited has the Sketch tab alone, as the sketch task environment has", () => {
  assert.deepEqual(workspaceTabs({ assembly: true, sketching: true, drawing: true }), [{ id: "sketch", title: "Sketch" }]);
});

test("puts every modeling command in one group", () => {
  // A subtracting command (Extruded Cut...) is reached by its unite command's Boolean, so it has no place of its own.
  const modeling = EDIT_COMMANDS.filter(({ id }) => booleanOf(id)?.value !== "subtract").map(({ id }) => id);
  const placed = SOLID_GROUPS.flatMap(group => group.items).filter(item => EDIT_COMMANDS.some(({ id }) => id === item));
  assert.deepEqual([...placed].sort(), [...modeling].sort());
  assert.equal(new Set(placed).size, placed.length);
});

test("has no agent in it: no group of Ask, Add to context or Annotate", () => {
  const agents = new Set(["ask", "add-context", "annotate"]);
  assert.equal(SOLID_GROUPS.some(group => group.items.some(item => agents.has(item))), false);
});

test("each group holds only what the toolbar can draw, and shows some of it as buttons", () => {
  const drawn = new Set([...EDIT_COMMANDS.map(({ id }) => id), "sketch", "select"]);
  assert.deepEqual(SOLID_GROUPS.map(group => group.title), ["Create", "Modify", "Construct", "Select"]);
  for (const group of SOLID_GROUPS) {
    for (const item of group.items) assert.ok(drawn.has(item), `${group.title} holds "${item}", which the toolbar has no button for`);
    assert.ok(group.shown >= 1 && group.shown <= group.items.length, `${group.title} shows ${group.shown} of ${group.items.length}`);
  }
});

// The demo's part, as the engine reads it from its script: two extrudes with their sketches, a
// Fillet, a Hole and a Pattern. The design tree numbers each kind on its own: Sketch1, Boss-Extrude1,
// Sketch2, Boss-Extrude2 (named "upright"), Fillet1, Hole1, Pattern1; a row's name stands in place of its label.
const DEMO = featureTree({
  features: [
    { key: "servo.py:12", kind: "Boss-Extrude", name: "base", file: "servo.py", line: 12,
      sketch: { name: "SKETCH_000", plane: "Top", file: "servo.py", line: 10, status: "Fully defined" } },
    { key: "servo.py:20", kind: "Boss-Extrude", name: "wall", file: "servo.py", line: 20, named: "upright",
      sketch: { name: "SKETCH_001", plane: "Front", file: "servo.py", line: 18, status: "Fully defined" } },
    { key: "servo.py:24", kind: "Fillet", name: "wall", file: "servo.py", line: 24 },
    { key: "servo.py:27", kind: "Hole", name: "wall", file: "servo.py", line: 27 },
    { key: "servo.py:30", kind: "Pattern", name: "wall", file: "servo.py", line: 30 },
  ],
}).features;
const [BASE, WALL, BLEND, HOLE, PATTERN] = DEMO;

test("numbers the design tree's rows per kind, a feature's sketch just before it, a name standing in its label's place", () => {
  assert.deepEqual([...navigatorTitles(DEMO)], [
    [BASE.sketch.id, "SKETCH_000"],
    [BASE.id, "Boss-Extrude1"],
    [WALL.sketch.id, "SKETCH_001"],
    [WALL.id, "upright"],
    [BLEND.id, "Fillet1"],
    [HOLE.id, "Hole1"],
    [PATTERN.id, "Pattern1"],
  ]);
});

test("names a row as the design tree numbers it without the name it was given", () => {
  assert.equal(navigatorLabel(DEMO, HOLE.id), "Hole1");
  // The numbered label a named row's name stands in for.
  assert.equal(navigatorLabel(DEMO, WALL.id), "Boss-Extrude2");
  assert.equal(navigatorLabel(DEMO, WALL.sketch.id), "Sketch2");
  assert.equal(navigatorLabel(DEMO, BLEND.id), "Fillet1");
  // A row the design tree does not list has no label, so a caller can keep its own words.
  assert.equal(navigatorLabel(DEMO, "servo.py:99"), "");
  assert.equal(navigatorLabel([], HOLE.id), "");
});

test("a sketch that is a row of its own is numbered like the rest", () => {
  const features = featureTree({
    features: [
      { key: "lid.py:5", kind: "Sketch", file: "lid.py", line: 5, sketch: { name: "Outline", plane: "Top", file: "lid.py", line: 5, status: "Fully defined" } },
      { key: "lid.py:9", kind: "Boss-Extrude", name: "lid", file: "lid.py", line: 9 },
    ],
  }).features;
  assert.equal(navigatorLabel(features, features[0].id), "Sketch1");
  assert.equal(navigatorTitles(features).get(features[0].id), "Outline");
  assert.equal(navigatorLabel(features, features[1].id), "Boss-Extrude1");
});

// What a part's script stops with: the tracer's frame, the part's own line, build123d's, then the error.
const traceback = (...frames) => ["Traceback (most recent call last):", ...frames.flatMap(([file, line, code]) => [
  `  File "${file}", line ${line}, in part`, `    ${code}`]), "OCP.StdFail.StdFail_NotDone: BRep_API: command not done"].join("\n");
const TRACER = ["/work/.venv/lib/python3.13/site-packages/cadgen/edit/tracer.py", 1660, "shape = model.func()"];
const KERNEL = ["/work/.venv/lib/python3.13/site-packages/build123d/operations_generic.py", 541, "return Solid.fillet(...)"];
const WHY = "OCP.StdFail.StdFail_NotDone: BRep_API: command not done";

// The part as the engine reads it: each feature gives its first line as written, and the rows folded
// into one (a profile's line, a cut joined to it) give theirs. The hole is made by a helper the part calls.
const SOURCE = {
  profile: "profile = Circle(RADIUS)", base: "base = extrude(profile, amount=HEIGHT)", blend: "base = fillet(base.edges(), radius=WALL)",
  chamfer: "base = chamfer(base.edges(), length=1)", hole: "base = drill(base, HOLE)",
};
const SOURCED = featureTree({
  rows: [
    { key: "servo.py:11", file: "servo.py", line: 11, code: SOURCE.profile },
    { key: "servo.py:12", file: "servo.py", line: 12, code: SOURCE.base },
    { key: "servo.py:24", file: "servo.py", line: 24, code: SOURCE.blend },
    { key: "servo.py:25", file: "servo.py", line: 25, code: SOURCE.chamfer },
    { key: "servo.py:27", file: "servo.py", line: 27, code: SOURCE.hole },
  ],
  features: [
    { key: "servo.py:12", kind: "Boss-Extrude", name: "base", file: "servo.py", line: 12, text: SOURCE.base, rows: ["servo.py:11", "servo.py:12"] },
    { key: "servo.py:24", kind: "Fillet", name: "base", file: "servo.py", line: 24, text: SOURCE.blend },
    { key: "servo.py:25", kind: "Chamfer", name: "base", file: "servo.py", line: 25, text: SOURCE.chamfer },
    { key: "servo.py:27", kind: "Hole", name: "base", file: "servo.py", line: 27, text: SOURCE.hole },
  ],
});
// How the engine says where the script stopped: the frames of its traceback in the project's own files,
// deepest first, each with its file as the history names it, its line and the line as read.
const at = (line, text, file = "servo.py") => ({ file, line, text });
const stoppedAt = (...frames) => ({ frames });
// The line in a helper's file that raised, which makes no row; the part's call into it is the hole's row.
const IN_DRILL = at(8, "return base - Pos(0, 0, 0) * Cylinder(HOLE, HEIGHT)", "helpers.py");
const FILLET_FAILED = traceback(TRACER, ["/work/servo/servo.py", 24, SOURCE.blend], KERNEL);

test("a failed build marks the feature whose line it stopped at, told by file, number and words, and says why", () => {
  assert.deepEqual(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend))), { id: "servo.py:24", why: WHY });
  // A line folded into a feature, its profile's, is the feature's.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(11, SOURCE.profile)))?.id, "servo.py:12");
  // The files are told by their names, whichever way a system writes its paths.
  const nested = featureTree({ features: [{ key: "parts/servo.py:24", kind: "Fillet", name: "base", file: "parts/servo.py", line: 24, text: SOURCE.blend }] });
  assert.equal(buildFailure(nested, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend, "parts\\servo.py")))?.id, "parts/servo.py:24");
});

test("an error inside a helper marks the feature that called it: the helper's line is no row, so the walk goes on to the call", () => {
  assert.deepEqual(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(IN_DRILL, at(27, SOURCE.hole))), { id: "servo.py:27", why: WHY });
  // However many helpers deep, and with a function of the part's own between, whose line is no row either.
  const deeper = stoppedAt(at(3, "raise ValueError", "helpers.py"), IN_DRILL, at(40, "return drill(base, HOLE)"), at(27, SOURCE.hole));
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, deeper)?.id, "servo.py:27");
});

test("the deepest frame a row agrees with is the one that counts", () => {
  // Both frames are lines of rows, as when a function of the part's own does the fillet and the hole follows it.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend), at(27, SOURCE.hole)))?.id, "servo.py:24");
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(27, SOURCE.hole), at(24, SOURCE.blend)))?.id, "servo.py:27");
});

test("a line that moved marks nothing: not its own row, and not the neighbour now at its number", () => {
  // A line was written above the fillet: it stands at 25 now, where the last good part's chamfer was.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(25, SOURCE.blend))), null);
  // Two lines above it, where the last good part had nothing at all.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(26, SOURCE.blend))), null);
  // The fillet's number with the chamfer's words.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, SOURCE.chamfer))), null);
});

test("a call that moved marks nothing either, though the helper it called is told of", () => {
  // The call into the helper stands at 28 now, where the last good part had nothing; at 25, where its chamfer was.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(IN_DRILL, at(28, SOURCE.hole))), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(IN_DRILL, at(25, SOURCE.hole))), null);
  // The call's number with another line's words.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(IN_DRILL, at(27, SOURCE.chamfer))), null);
  // The helper's own line is told by its words too: a row's number and words are the only way in.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(27, SOURCE.hole, "helpers.py"))), null);
});

test("a line the last good part does not hold marks nothing, whatever sits at its number", () => {
  // Rewritten (the radius typed over in the line) or new: no row of the last good part reads so.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, "base = fillet(base.edges(), radius=40)"))), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(25, "base = shell(base, thickness=1)"))), null);
  // The same words at the same number in another file are another line.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend, "helpers.py"))), null);
  // Nothing to tell it by.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, ""))), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt({ file: "servo.py", text: SOURCE.blend })), null);
  assert.equal(buildFailure({ assembly: false, features: [] }, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend))), null);
});

test("features whose lines read alike are told by their numbers, and a line two features stand for marks neither", () => {
  const twice = featureTree({
    features: [
      { key: "servo.py:24", kind: "Fillet", name: "base", file: "servo.py", line: 24, text: SOURCE.blend },
      { key: "servo.py:30", kind: "Fillet", name: "base", file: "servo.py", line: 30, text: SOURCE.blend },
    ],
  });
  assert.equal(buildFailure(twice, FILLET_FAILED, stoppedAt(at(30, SOURCE.blend)))?.id, "servo.py:30");
  assert.equal(buildFailure(twice, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend)))?.id, "servo.py:24");
  assert.equal(buildFailure(twice, FILLET_FAILED, stoppedAt(at(27, SOURCE.blend))), null);
  // A line both claim cannot say which of them it is, and the calls outwards from it are not asked.
  const shared = featureTree({
    rows: [{ key: "servo.py:3", file: "servo.py", line: 3, code: SOURCE.profile }],
    features: [
      { key: "servo.py:5", kind: "Boss-Extrude", name: "a", file: "servo.py", line: 5, text: SOURCE.base, rows: ["servo.py:3", "servo.py:5"] },
      { key: "servo.py:9", kind: "Boss-Extrude", name: "b", file: "servo.py", line: 9, text: SOURCE.base, rows: ["servo.py:3", "servo.py:9"] },
    ],
  });
  assert.equal(buildFailure(shared, FILLET_FAILED, stoppedAt(at(3, SOURCE.profile))), null);
  assert.equal(buildFailure(shared, FILLET_FAILED, stoppedAt(at(3, SOURCE.profile), at(9, SOURCE.base))), null);
  assert.equal(buildFailure(shared, FILLET_FAILED, stoppedAt(at(9, SOURCE.base)))?.id, "servo.py:9");
});

test("an engine that says no line marks nothing, though the traceback holds a frame", () => {
  // A script that does not parse never ran, so the engine finds no frame of the part's own to name, though
  // its traceback names a line. An engine that says nothing of where leaves only that traceback's line
  // number, the failing script's, which the last good part's rows stop matching once a line is written above.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, null), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt()), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, {}), null);
});

test("says why in the last line of the traceback the tracer gives for a fillet that cannot be made", () => {
  // A real one, its paths shortened: build123d's error, then a second traceback chained to it that holds
  // the part's own line, past the tracer's frame and under build123d's wrapper.
  const error = [
    "Traceback (most recent call last):",
    '  File "/work/.venv/lib/python3.13/site-packages/build123d/topology/three_d.py", line 367, in fillet',
    "    new_shape = self._make_3d_result(fillet_builder.Shape())",
    "OCP.OCP.Standard.Standard_Failure: BRep_API: command not done",
    "",
    "The above exception was the direct cause of the following exception:",
    "",
    "Traceback (most recent call last):",
    '  File "/work/packages/cadgen/src/cadgen/edit/tracer.py", line 1668, in trace',
    "    shape = model.func()",
    '  File "/work/servo/servo.py", line 24, in servo',
    `    ${SOURCE.blend}`,
    '  File "/work/packages/cadgen/src/cadgen/edit/tracer.py", line 431, in wrapper',
    "    result = original(*args, **kwargs)",
    '  File "/work/.venv/lib/python3.13/site-packages/build123d/topology/three_d.py", line 371, in fillet',
    "    raise ValueError(",
    "    ...<2 lines>...",
    "ValueError: Failed creating a fillet with radius of 50, try a smaller value or use max_fillet() to find the largest valid fillet radius",
  ].join("\n");
  assert.deepEqual(buildFailure(SOURCED, error, stoppedAt(at(24, SOURCE.blend))), {
    id: "servo.py:24", why: "ValueError: Failed creating a fillet with radius of 50, try a smaller value or use max_fillet() to find the largest valid fillet radius" });
});

test("says nothing of an error that points at no feature", () => {
  // A refusal in words: the engine names no line of it.
  assert.equal(buildFailure(SOURCED, "Another feature is named Lid. Pick another name."), null);
  assert.equal(buildFailure(SOURCED, "Another feature is named Lid. Pick another name.", null), null);
  // No error to say, whatever place is held.
  assert.equal(buildFailure(SOURCED, "", stoppedAt(at(24, SOURCE.blend))), null);
  assert.equal(buildFailure(SOURCED, undefined, stoppedAt(at(24, SOURCE.blend))), null);
  // A line that makes no feature, and a file the part does not have.
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(99, "x = 1"))), null);
  assert.equal(buildFailure(SOURCED, FILLET_FAILED, stoppedAt(at(24, SOURCE.blend, "notservo.py"))), null);
});

test("a failed build in an assembly points at the part's feature, by its file", () => {
  const assembly = featureTree({
    rows: [{ key: "tray.py:7", file: "tray.py", line: 7, code: "tray = extrude(base, amount=3)" }, { key: "lid.py:7", file: "lid.py", line: 7, code: "lid = extrude(base, amount=3)" }],
    components: [
      { file: "tray.py", name: "tray", features: [{ key: "tray.py:7", kind: "Boss-Extrude", name: "tray", file: "tray.py", line: 7, text: "tray = extrude(base, amount=3)" }] },
      { file: "lid.py", name: "lid", features: [{ key: "lid.py:7", kind: "Boss-Extrude", name: "lid", file: "lid.py", line: 7, text: "lid = extrude(base, amount=3)" }] },
    ],
  });
  // The same line number in two parts' files: the file and the words tell them apart.
  assert.equal(buildFailure(assembly, WHY, stoppedAt(at(7, "lid = extrude(base, amount=3)", "lid.py")))?.id, "lid.py:7");
  assert.equal(buildFailure(assembly, WHY, stoppedAt(at(7, "tray = extrude(base, amount=3)", "tray.py")))?.id, "tray.py:7");
  assert.equal(buildFailure(assembly, WHY, stoppedAt(at(7, "tray = extrude(base, amount=3)", "lid.py"))), null);
  // A helper both parts share, called from the lid: the lid's row.
  assert.equal(buildFailure(assembly, WHY, stoppedAt(at(3, "raise ValueError", "helpers.py"), at(7, "lid = extrude(base, amount=3)", "lid.py")))?.id, "lid.py:7");
});
