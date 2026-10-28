import assert from "node:assert/strict";
import test from "node:test";

import { featureTree } from "./editMode.js";
import { faceChipName, faceFeature, faceReference, shownFaces } from "./faceChips.js";

// A part as the engine reads it, numbered as the design tree numbers it, each kind on its own: Sketch1,
// Boss-Extrude1, Sketch2, Boss-Extrude2, Fillet1, Hole1.
const sketched = (name, line) => ({ name, plane: "Top", file: "servo.py", line, status: "Fully defined" });
const features = featureTree({
  features: [
    { key: "row:base", kind: "Boss-Extrude", name: "base", file: "servo.py", line: 12, sketch: sketched("SKETCH_000", 10) },
    { key: "row:wall", kind: "Boss-Extrude", name: "wall", file: "servo.py", line: 20, sketch: sketched("SKETCH_001", 18) },
    { key: "row:blend", kind: "Fillet", name: "wall", file: "servo.py", line: 24 },
    { key: "row:hole", kind: "Hole", name: "wall", file: "servo.py", line: 27 },
  ],
}).features;
const face12 = { target: { kind: "face", face: 12 } };
// A chip's compact name in its pieces, as the chip says "Hole1 · face 12": the feature where today's has the part.
const hole12 = { name: "Hole1", kind: "face", number: "12" };

test("names a face by the feature that made it, in the design tree's words", () => {
  assert.deepEqual(faceChipName(face12, { faceFeatures: { "12": "row:hole" } }, features), hole12);
  assert.deepEqual(faceChipName(face12, { faceFeatures: { "12": "row:base" } }, features), { name: "Boss-Extrude1", kind: "face", number: "12" });
});

test("keeps today's label for a face the engine does not say made it", () => {
  assert.equal(faceChipName(face12, { faceFeatures: {} }, features), null);
  assert.equal(faceChipName(face12, { faceFeatures: { "3": "row:hole" } }, features), null);
  assert.equal(faceChipName(face12, {}, features), null);
  assert.equal(faceChipName(face12, null, features), null);
  // A feature the design tree does not list is no name for it.
  assert.equal(faceChipName(face12, { faceFeatures: { "12": "row:gone" } }, features), null);
  assert.equal(faceChipName(face12, { faceFeatures: { "12": "row:hole" } }, []), null);
});

test("reads the face from a reference to one face's selector, the engine's ref, and names nothing else", () => {
  const state = { faceFeatures: { "12": "row:hole" } };
  // As the xbf renderer copies a face: by its number under its part, or the document's root.
  assert.deepEqual(faceChipName(faceReference("part/face 12"), state, features), hole12);
  assert.deepEqual(faceChipName(faceReference("face 12"), state, features), hole12);
  assert.deepEqual(faceChipName(faceReference("hand/finger.2/face 12"), state, features), hole12);
  assert.equal(faceFeature(faceReference("part/face 12"), state), "row:hole");
  // A ref copied before 0.8 still reads.
  assert.deepEqual(faceChipName(faceReference("o1.f12"), state, features), hole12);
  assert.deepEqual(faceChipName(faceReference("f12"), state, features), hole12);
  // An edge of the same number, a face named by its derivation, several faces, a whole part: none is a face the map names.
  for (const reference of [faceReference("part/edge 12"), faceReference("o1.e12"), faceReference("part/f:part.extrude1.12"), faceReference("part"),
    faceReference("o1"), { target: { kind: "cad-selector", selectors: ["part/face 12", "part/face 3"] } },
    { target: { kind: "whole-resource" } }, { target: { kind: "face", face: 0 } }, null]) {
    assert.equal(faceChipName(reference, state, features), null, JSON.stringify(reference));
  }
});

// The part's map as a reading of it carries it: seven faces, the edit service's builds done.
const READ = { faceFeatures: { "1": "row:base", "7": "row:hole" }, faceCount: 7, building: { scripts: ["servo.py"], done: 1, error: null } };
const ON_SCREEN = { editing: true, assembly: false, state: READ, bar: null, updating: false, rebuilding: false, faces: 7 };

test("uses the part's map in the workspace while the model on screen is the one the engine read", () => {
  assert.deepEqual(shownFaces(ON_SCREEN), { faceFeatures: READ.faceFeatures });
  assert.deepEqual(shownFaces({ ...ON_SCREEN, state: { ...READ, building: { scripts: [], done: 0, error: null } } }), { faceFeatures: READ.faceFeatures });
});

test("uses no map outside the workspace or in an assembly", () => {
  assert.equal(shownFaces({ ...ON_SCREEN, editing: false }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, assembly: true }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, state: null }), null);
});

test("uses no map while the model on screen may be another build than the one read", () => {
  // A new one loading; its STEP being built again, by the build feed or the edit service; one that failed to build.
  assert.equal(shownFaces({ ...ON_SCREEN, updating: true }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, rebuilding: true }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, state: { ...READ, building: { scripts: ["servo.py"], done: 0, error: null } } }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, state: { ...READ, building: { scripts: ["servo.py"], done: 1, error: "servo.py: failed" } } }), null);
  // Faces on screen other than the body read has: built from another script.
  assert.equal(shownFaces({ ...ON_SCREEN, faces: 8 }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, faces: 0 }), null);
  // An engine that sends no count is not known to match.
  assert.equal(shownFaces({ ...ON_SCREEN, state: { ...READ, faceCount: undefined } }), null);
});

test("uses no map while the rollback bar's body is drawn in place of the part's", () => {
  // Picks on that body carry no chips, and a reference pasted then is numbered on the part's model: the part's map is not of
  // what is on screen, and the bar has none of its own.
  const bar = { before: "servo.py:27", item: "row:hole", kind: "part", document: { id: "6f1c0d8e-2b7a-4c1e-9d3f-5a6b7c8d9e0f", name: "servo at the rollback bar 1a2b3c4d" } };
  assert.equal(shownFaces({ ...ON_SCREEN, bar, faces: 6 }), null);
  assert.equal(shownFaces({ ...ON_SCREEN, bar, faces: 7 }), null);
  // A bar with no body of its own drawn (one that could not be made) leaves the part's on screen, and its map.
  assert.deepEqual(shownFaces({ ...ON_SCREEN, bar: { before: "servo.py:27", error: "no body" } }), { faceFeatures: READ.faceFeatures });
});
