// Callouts set apart on screen (`separateLabels.js`): one that would cover another steps below it,
// clear; one the code placed never moves, and the others keep clear of it.
import assert from "node:assert/strict";
import test from "node:test";
import { labelInView, separateLabels } from "./separateLabels.js";

const box = (x, y, movable = true) => ({ x, y, w: 60, h: 16, movable });

test("labels that would cover one another are stacked, clear", () => {
  assert.deepEqual(separateLabels([box(100, 100), box(110, 104), box(400, 100)]), [{ x: 100, y: 100 }, { x: 110, y: 119 }, { x: 400, y: 100 }]);
  // A third on the first two goes under both.
  assert.deepEqual(separateLabels([box(100, 100), box(100, 100), box(100, 100)]).map(at => at.y), [100, 119, 138]);
});

test("a label the code placed stays put, and the others keep clear of it", () => {
  assert.deepEqual(separateLabels([box(100, 100), box(100, 104, false)]), [{ x: 100, y: 123 }, { x: 100, y: 104 }]);
});

test("past the bottom of the view a label steps up, not off it", () => {
  const area = { bottom: 112 };
  assert.deepEqual(separateLabels([box(100, 100), box(100, 100)], area).map(at => at.y), [100, 81]);
});

const AREA = { left: 8, top: 8, right: 792, bottom: 592 };

test("a label past the edge of the view comes back inside it", () => {
  assert.deepEqual(labelInView(box(-40, 300), AREA), { x: 38, y: 300 });
  assert.deepEqual(labelInView(box(400, 640), AREA), { x: 400, y: 584 });
  assert.deepEqual(labelInView(box(400, 300), AREA), { x: 400, y: 300 }, "one in the view stays where it stands");
});

test("a label under what covers the view leaves by the shortest way that stays in the view", () => {
  const panel = { left: 600, top: 0, right: 800, bottom: 600 };
  assert.deepEqual(labelInView(box(620, 300), AREA, [panel]), { x: 567, y: 300 });
  // The strip across the top: it cannot go up, so it goes below.
  const strip = { left: 0, top: 0, right: 800, bottom: 48 };
  assert.deepEqual(labelInView(box(400, 20), AREA, [strip]), { x: 400, y: 59 });
  // A cover that fills the view leaves it nowhere to go: it stays.
  const all = { left: 0, top: 0, right: 800, bottom: 600 };
  assert.deepEqual(labelInView(box(400, 300), AREA, [all]), { x: 400, y: 300 });
});
