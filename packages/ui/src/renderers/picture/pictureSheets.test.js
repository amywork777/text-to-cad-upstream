import assert from "node:assert/strict";
import test from "node:test";

import { layoutSheets, paintSheets, SHEET_GAP } from "./pictureSheets.js";

test("a PDF's sheets stack top to bottom a gap apart, framed whole, y up", () => {
  const a3 = { bitmap: "a", width: 1191, height: 842 };
  const a4 = { bitmap: "b", width: 595, height: 842 };
  const { sheets, bounds } = layoutSheets([a3, a4]);
  assert.deepEqual(sheets.map(sheet => sheet.top), [0, 842 + SHEET_GAP]);
  assert.deepEqual(bounds, [0, -(842 * 2 + SHEET_GAP), 1191, 0]);
});

test("an image is one sheet, and nothing has no bounds", () => {
  assert.deepEqual(layoutSheets([{ bitmap: "p", width: 640, height: 480 }]).bounds, [0, -480, 640, 0]);
  assert.equal(layoutSheets([]).bounds, null);
});

test("each sheet is painted where the view's transform puts its top-left corner", () => {
  const drawn = [];
  const ctx = { save() {}, restore() {}, setTransform() {}, drawImage: (...args) => drawn.push(args) };
  const { sheets } = layoutSheets([{ bitmap: "a", width: 100, height: 50 }, { bitmap: "b", width: 100, height: 50 }]);
  paintSheets(ctx, { sheets }, { transform: { scale: 2, offsetX: 10, offsetY: 20 } });
  assert.deepEqual(drawn, [["a", 10, 20, 200, 100], ["b", 10, (50 + SHEET_GAP) * 2 + 20, 200, 100]]);
});
