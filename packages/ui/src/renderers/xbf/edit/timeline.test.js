import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";

import { barIndex, featureTree, rolledBack, sketchTreeId } from "./editMode.js";
import { slotAtX, timelineItems } from "./timeline.js";

const traverse = traverseModule.default ?? traverseModule;
const sketched = (name, line) => ({ name, plane: "Top", file: "bracket.py", line, status: "Fully defined" });

// The sample bracket as the engine reads it (`tracer.py`): an extrude takes the sketch it was made from, and the
// engine nests that sketch under the extrude (`sketch`), so a sketch is a feature of its own only while nothing
// uses it. Two extrudes made from sketches, then a Fillet. The design tree numbers each kind on its own, a sketch just
// before the extrude that takes it: Sketch1, Boss-Extrude1, Sketch2, Boss-Extrude2 (named "upright"), Fillet1.
const PART = featureTree({
  features: [
    { key: "e1", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 8, sketch: sketched("SKETCH_000", 5) },
    { key: "e2", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 13, named: "upright", sketch: sketched("SKETCH_001", 10) },
    { key: "b1", kind: "Fillet", name: "plate", file: "bracket.py", line: 15 },
  ],
});
const IDS = ["e1", "e2", "b1"];
// What the timeline draws, left to right: each feature's own sketch just before it.
const iconsOf = items => items.flatMap(item => [item.sketch, item].filter(Boolean));

test("lists items in the design tree's order", () => {
  const { items } = timelineItems(PART, null);
  // One item, and one place for the marker, for each feature the design tree lists as a row of the part.
  assert.deepEqual(items.map(item => item.id), IDS);
  assert.deepEqual(items.map(item => item.kind), ["Boss-Extrude", "Boss-Extrude", "Fillet"]);
  items.forEach((item, index) => assert.equal(item.feature, PART.features[index]));
  // Drawn, the sketch each extrude was made from stands just before it, and every icon has the title the design tree
  // numbers it under (its kind numbered on its own, or the name given in the tree in its place).
  assert.deepEqual(iconsOf(items).map(icon => icon.title),
    ["SKETCH_000", "Boss-Extrude1", "SKETCH_001", "upright", "Fillet1"]);
  assert.deepEqual(iconsOf(items).map(icon => icon.kind), ["Sketch", "Boss-Extrude", "Sketch", "Boss-Extrude", "Fillet"]);
});

test("draws the sketch a feature was made from just before it, under the id the design tree selects it by", () => {
  const [first, second, blend] = timelineItems(PART, null).items;
  // The id a sketch picked on the model selects (`sketchTreeId`), and the design tree's row for it carries.
  assert.equal(first.sketch.id, sketchTreeId(PART, { file: "bracket.py", line: 5 }));
  assert.equal(second.sketch.id, sketchTreeId(PART, { file: "bracket.py", line: 10 }));
  assert.equal(first.sketch.id, PART.features[0].sketch.id);
  assert.notEqual(first.sketch.id, first.id);
  // The feature is what edits it: Edit Sketch opens the sketch the feature holds.
  assert.equal(first.sketch.feature, PART.features[0]);
  assert.equal(second.sketch.feature.sketch, PART.features[1].sketch);
  // A feature made from no sketch has none to draw.
  assert.equal(blend.sketch, null);
});

test("draws a sketch nothing uses yet once, as an item of its own", () => {
  const loose = featureTree({
    features: [
      { key: "e1", kind: "Boss-Extrude", name: "plate", file: "bracket.py", line: 8, sketch: sketched("SKETCH_000", 5) },
      { key: "s9", kind: "Sketch", file: "bracket.py", line: 12, sketch: sketched("SKETCH_001", 12) },
    ],
  });
  const { items } = timelineItems(loose, null);
  assert.deepEqual(items.map(item => item.id), ["e1", "s9"]);
  // Its sketch is the item itself, not one more before it, and it is selected by its own id.
  assert.equal(items[1].sketch, null);
  assert.equal(items[1].id, sketchTreeId(loose, { file: "bracket.py", line: 12 }));
  assert.deepEqual(iconsOf(items).map(icon => icon.title), ["SKETCH_000", "Boss-Extrude1", "SKETCH_001"]);
});

test("puts the marker after the last active item", () => {
  assert.equal(timelineItems(PART, null).marker, 3);
  const { items, marker } = timelineItems(PART, { item: "e2" });
  // Above the second extrude: what stands past the marker is rolled back, and the sketch an extrude was made from goes with it.
  assert.equal(marker, 1);
  assert.deepEqual(items.map(item => item.rolledBack), [false, true, true]);
  assert.deepEqual(items.map(item => item.sketch?.rolledBack ?? null), [false, true, null]);
  assert.deepEqual(timelineItems(PART, null).items.map(item => item.rolledBack), [false, false, false]);
  // A bar over an item the tree no longer holds leaves the part whole, as the design tree does.
  assert.equal(timelineItems(PART, { item: "gone" }).marker, 3);
});

test("agrees with the design tree's rollback bar wherever it is", () => {
  for (const bar of [null, ...IDS.map(item => ({ item }))]) {
    const { items, marker } = timelineItems(PART, bar);
    assert.equal(marker, barIndex(PART, bar));
    const rolled = rolledBack(PART, bar);
    assert.deepEqual(items.filter(item => item.rolledBack).map(item => item.id), IDS.filter(id => rolled.has(id)));
    // Every item past the marker is rolled back, and none before it; a sketch is as its feature is.
    assert.deepEqual(items.map((item, index) => item.rolledBack), items.map((item, index) => index >= marker));
    assert.ok(items.every(item => !item.sketch || item.sketch.rolledBack === item.rolledBack));
  }
});

test("lists no items for an assembly, whose design tree has no rollback bar", () => {
  const assembly = featureTree({ components: [{ file: "tray.py", name: "tray", features: [{ key: "t1", kind: "Boss-Extrude", file: "tray.py", line: 4 }] }] });
  assert.deepEqual(timelineItems(assembly, null), { items: [], marker: 0 });
  assert.deepEqual(timelineItems(null, null), { items: [], marker: 0 });
});

test("places a dragged marker between items", () => {
  // The marker's index is how many centres the pointer has passed: those of the items, each with the sketch drawn before it.
  assert.equal(slotAtX(25, [10, 30, 50]), 1);
  assert.equal(slotAtX(60, [10, 30, 50]), 3);
  assert.equal(slotAtX(5, [10, 30, 50]), 0);
  // On a centre it has passed it, as the design tree's bar goes below the row the pointer is past the middle of.
  assert.equal(slotAtX(30, [10, 30, 50]), 2);
  assert.equal(slotAtX(12, []), 0);
});

test("marks who made each item, and nothing unknown", () => {
  const { items } = timelineItems(PART, null, { e2: "agent" });
  assert.deepEqual(items.map(item => item.author), [null, "agent", null]);
  // A sketch has no author of its own: it carries its feature's, if the feature has one.
  assert.deepEqual(items.map(item => item.sketch?.author ?? null), [null, "agent", null]);
  assert.deepEqual(timelineItems(PART, null, { e1: "you", b1: "agent" }).items.map(item => item.author), ["you", null, "agent"]);
  // No record, a record of someone else, or one that is not a name: nothing is marked.
  const unmarked = authors => iconsOf(timelineItems(PART, null, authors).items).every(icon => icon.author === null);
  assert.ok(unmarked(undefined));
  assert.ok(unmarked(null));
  assert.ok(unmarked({}));
  assert.ok(unmarked({ e1: "someone", e2: 1, b1: null }));
  assert.ok(unmarked({ e1: {}, e2: "Agent" }));
});

/**
 * CAD mode's own condition for handing the frame its timeline (`bottomDock`, `useXbfCadMode.jsx`), as written there, to be run on
 * a state of the view: the view itself cannot be mounted here (its viewport is the browser suite's), and a copy of the rule
 * written in this test would pin nothing.
 */
function timelineCondition() {
  const source = fs.readFileSync(new URL("./useXbfCadMode.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const found = [];
  traverse(ast, {
    ObjectProperty(path) {
      const { key, value } = path.node;
      if (key.name === "bottomDock" && value?.type === "ConditionalExpression") found.push(value.test);
    },
  });
  assert.equal(found.length, 1, "CAD mode hands the frame its timeline under one condition");
  const condition = source.slice(found[0].start, found[0].end);
  return scope => Boolean(Function("scope", `with (scope) { return (${condition}); }`)(scope));
}

test("is up while the part is edited, and not in Simple view", () => {
  const up = timelineCondition();
  assert.equal(up({ editing: true, edit: {} }), true);
  // Simple view lays the view out for asking the AI, with no timeline.
  assert.equal(up({ editing: false, edit: {} }), false);
});
