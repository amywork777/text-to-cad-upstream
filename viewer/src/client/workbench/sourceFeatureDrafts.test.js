import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSourceEdits,
  decorateSourceFeatures,
  featureParameterRows,
  sourceDraftsValid,
} from "./sourceFeatureDrafts.js";

test("decorates construction features with SolidWorks-style labels and nested sketches", () => {
  const features = decorateSourceFeatures([
    { id: "box-1", op: "Box" },
    { id: "extrude-1", op: "extrude", mode: "subtract", sketch: { id: "sketch-1", entities: [] } },
    { id: "fillet-1", op: "fillet" },
  ]);
  assert.deepEqual(features.map((feature) => feature.label), ["Boss-Extrude1", "Cut-Extrude1", "Fillet1"]);
  assert.equal(features[1].sketch.label, "Sketch1");
});

test("sketch selection exposes entity dimensions while a feature exposes its operation dimensions", () => {
  const feature = {
    id: "extrude-1",
    params: [{ name: "amount", value: 6, span: [90, 91] }],
    sketch: {
      id: "sketch-1",
      entities: [{ op: "Rectangle", params: [{ name: "width", value: 24, span: [40, 42] }] }],
    },
  };
  assert.deepEqual(featureParameterRows(feature, "extrude-1").map((row) => row.name), ["amount"]);
  assert.deepEqual(featureParameterRows(feature, "sketch-1").map((row) => row.name), ["width"]);
});

test("buildSourceEdits preserves expected text and orders replacements by span", () => {
  const source = "Box(10, 20, 30)";
  const edits = buildSourceEdits(source, {
    "12:14": { span: [12, 14], value: "35" },
    "4:6": { span: [4, 6], value: "12" },
  });
  assert.deepEqual(edits, [
    { start: 4, end: 6, expected: "10", replacement: "12" },
    { start: 12, end: 14, expected: "30", replacement: "35" },
  ]);
  assert.equal(sourceDraftsValid({ a: { value: "1.25" }, b: { value: "-3" } }), true);
  assert.equal(sourceDraftsValid({ a: { value: "-" } }), false);
});
