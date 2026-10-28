import assert from "node:assert/strict";
import test from "node:test";

import { featureTree, treeFeatures } from "./editMode.js";
import { featureAtLine, focusAnswer } from "./focus.js";

// A bracket as the engine reads its script (`featureTree`): each feature by the statements it stands for, each by its first
// line and, where the engine read the statement, its last (`end`):
//    9  @step
//   10  def bracket():
//   11      base = Box(40, 20, 5)
//   12      base = fillet(base.edges().filter_by(Axis.Z), radius=2)
//   13
//   14      base -= Pos(10, 0) * Cylinder(
//   15          radius=1.6,
//   16          height=5,
//   17      )
//   18
//   19      # The cable's slot
//   20      slot = SlotOverall(12, 3)
//   21      base -= extrude(slot, amount=5)
//   22      return base
// The hole is one statement written over four lines. The slot's profile is its Cut-Extrude's sketch, its line folded into
// the feature, and of that statement the engine says only where it starts.
const row = (line, code) => ({ key: `parts/bracket.py:${line}`, file: "parts/bracket.py", line, code });
const ROWS = [
  row(11, "base = Box(40, 20, 5)"),
  row(12, "base = fillet(base.edges().filter_by(Axis.Z), radius=2)"),
  row(14, "base -= Pos(10, 0) * Cylinder("),
  row(20, "slot = SlotOverall(12, 3)"),
  row(21, "base -= extrude(slot, amount=5)"),
];
const feature = (line, end, kind, rows = [line]) => ({ key: `parts/bracket.py:${line}`, kind, name: "base", file: "parts/bracket.py",
  line, end, text: ROWS.find(each => each.line === line).code, rows: rows.map(each => `parts/bracket.py:${each}`) });
const BRACKET = treeFeatures(featureTree({
  rows: ROWS,
  features: [feature(11, 11, "Boss-Extrude"), feature(12, 12, "Fillet"), feature(14, 17, "Hole"),
    feature(21, 21, "Cut-Extrude", [20, 21])],
}));
const HOLE = "parts/bracket.py:14";
const SLOT = "parts/bracket.py:21";

test("featureTree keeps the last line of each statement the engine read, and of a folded row's none", () => {
  const hole = BRACKET.find(each => each.id === HOLE);
  assert.equal(hole.end, 17);
  assert.deepEqual(hole.lines, [{ file: "parts/bracket.py", line: 14, end: 17, text: "base -= Pos(10, 0) * Cylinder(" }]);
  assert.deepEqual(BRACKET.find(each => each.id === SLOT).lines.map(each => [each.line, each.end]), [[21, 21], [20, null]]);
  // An engine that reads no statement's end.
  const older = treeFeatures(featureTree({ features: [{ key: "a.py:3", kind: "Fillet", file: "a.py", line: 3 }] }));
  assert.deepEqual([older[0].end, older[0].lines[0].end], [null, null]);
});

test("featureAtLine finds the hole feature for a line inside its statement, and null for a blank line", () => {
  for (const line of [14, 15, 16, 17]) assert.equal(featureAtLine(BRACKET, "parts/bracket.py", line)?.id, HOLE, `line ${line}`);
  // The blank lines on either side of it are between statements.
  for (const line of [13, 18]) assert.equal(featureAtLine(BRACKET, "parts/bracket.py", line), null, `line ${line}`);
  // A profile's line is the feature it is the sketch of.
  assert.equal(featureAtLine(BRACKET, "parts/bracket.py", 20)?.id, SLOT);
  // Lines outside every statement a feature stands for: a comment, the part's function, its return, past the end.
  for (const line of [19, 9, 10, 22, 400]) assert.equal(featureAtLine(BRACKET, "parts/bracket.py", line), null, `line ${line}`);
});

test("a feature whose statement's end the engine did not say holds its first line only", () => {
  const older = treeFeatures(featureTree({ features: [{ key: "a.py:14", kind: "Hole", file: "a.py", line: 14 },
    { key: "a.py:20", kind: "Fillet", file: "a.py", line: 20, end: 18 }] }));
  assert.equal(featureAtLine(older, "a.py", 14)?.id, "a.py:14");
  assert.equal(featureAtLine(older, "a.py", 15), null);
  // An end before its statement's first line is no end.
  assert.equal(featureAtLine(older, "a.py", 20)?.id, "a.py:20");
  assert.equal(featureAtLine(older, "a.py", 19), null);
});

test("the script is told by its path at a folder's edge, however the host names it", () => {
  // In full, from a folder above the project's, or less of it; Windows' separators too.
  for (const file of ["/work/rover/parts/bracket.py", "rover/parts/bracket.py", "bracket.py", "./parts/bracket.py", "parts\\bracket.py"]) {
    assert.equal(featureAtLine(BRACKET, file, 15)?.id, HOLE, file);
  }
  // Another script's line 15 is none of this part's, nor is a name that only ends the same.
  for (const file of ["parts/clip.py", "racket.py", "parts/bracket.pyc", ""]) assert.equal(featureAtLine(BRACKET, file, 15), null, file);
});

test("featureAtLine takes the innermost statement: the smallest span that holds the line", () => {
  // A builder's block (20 to 30) holds a hole's statement (24 to 26) and a fillet the engine read the first line of (28).
  const nested = treeFeatures(featureTree({ features: [
    { key: "a.py:20", kind: "Boss-Extrude", file: "a.py", line: 20, end: 30 },
    { key: "a.py:24", kind: "Hole", file: "a.py", line: 24, end: 26 },
    { key: "a.py:28", kind: "Fillet", file: "a.py", line: 28 },
  ] }));
  for (const features of [nested, [...nested].reverse()]) {
    for (const line of [24, 25, 26]) assert.equal(featureAtLine(features, "a.py", line)?.id, "a.py:24", `line ${line}`);
    assert.equal(featureAtLine(features, "a.py", 28)?.id, "a.py:28");
    for (const line of [20, 23, 27, 29, 30]) assert.equal(featureAtLine(features, "a.py", line)?.id, "a.py:20", `line ${line}`);
    assert.equal(featureAtLine(features, "a.py", 31), null);
  }
  // Nothing to find in no features, or at no line.
  assert.equal(featureAtLine([], "a.py", 24), null);
  for (const line of [0, undefined, Number.NaN, 25.5]) assert.equal(featureAtLine(nested, "a.py", line), null, `line ${line}`);
});

test("the part on screen answers its host's ask once the part is read, however it went", () => {
  const ask = { path: "parts/bracket.py", line: 15, nonce: 7 };
  const reading = { layout: "manual", features: [] };
  // While the server says whether there is a script, and while the part is read: no answer yet.
  assert.equal(focusAnswer(ask, { ...reading, status: "probing" }), null);
  assert.equal(focusAnswer(ask, { ...reading, status: "reading" }), null);
  // Read: the feature there selected; at a blank line nothing, answered all the same.
  assert.deepEqual(focusAnswer(ask, { layout: "manual", status: "ready", features: BRACKET }), { select: HOLE });
  assert.deepEqual(focusAnswer({ ...ask, line: 13 }, { layout: "manual", status: "ready", features: BRACKET }), { select: null });
  // A file with no part script, and a part whose build failed, have no features read: answered, nothing selected.
  assert.deepEqual(focusAnswer(ask, { ...reading, status: "none" }), { select: null });
  assert.deepEqual(focusAnswer(ask, { ...reading, status: "error" }), { select: null });
  // Laid out for the AI, the view shows no features to select: answered at once, the part read or not.
  assert.deepEqual(focusAnswer(ask, { layout: "ai", status: "idle", features: [] }), { select: null });
  assert.deepEqual(focusAnswer(ask, { layout: "ai", status: "ready", features: BRACKET }), { select: null });
});
