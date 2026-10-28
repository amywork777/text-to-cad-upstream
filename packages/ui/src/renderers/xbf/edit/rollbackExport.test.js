import assert from "node:assert/strict";
import test from "node:test";
import { rollbackExport } from "./rollbackExport.js";

const PART = "6f1c0d8e-2b7a-4c1e-9d3f-5a6b7c8d9e0f";
const BAR = "0a1b2c3d-4e5f-5a6b-8c7d-9e0f1a2b3c4d";
const shown = (doc, revision) => ({ doc, revision, file: "/work/plate.py", name: "plate" });

test("Export writes the part while the rollback bar is up, never the body drawn in its place", () => {
  const part = shown(PART, "r1");
  const none = new Set();
  // No bar: the document on screen, a new revision of it as it comes.
  assert.equal(rollbackExport({ current: part, kept: null, rollback: "", bars: none }), part);
  const newer = shown(PART, "r2");
  assert.equal(rollbackExport({ current: newer, kept: part, rollback: "", bars: none }), newer);
  // The bar up: the part's as it last stood, while its body loads and once it is on screen.
  const bars = new Set([BAR]);
  assert.equal(rollbackExport({ current: newer, kept: newer, rollback: BAR, bars }), newer);
  assert.equal(rollbackExport({ current: shown(BAR, "b1"), kept: newer, rollback: BAR, bars }), newer);
  // The bar gone, its body still on screen while the part comes back: still the part's; then the part again.
  assert.equal(rollbackExport({ current: shown(BAR, "b1"), kept: newer, rollback: "", bars }), newer);
  const back = shown(PART, "r3");
  assert.equal(rollbackExport({ current: back, kept: newer, rollback: "", bars }), back);
  // Nothing to export (a picture drawn out of sight) stays nothing.
  assert.equal(rollbackExport({ current: null, kept: null, rollback: "", bars: none }), null);
});
