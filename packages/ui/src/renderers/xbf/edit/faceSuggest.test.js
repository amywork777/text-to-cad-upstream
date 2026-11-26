import assert from "node:assert/strict";
import test from "node:test";

import { faceSuggestions, lengthText, suggestedMateType } from "./faceSuggest.js";

const plane = (normal, origin) => ({ type: "plane", normal, origin });
const cylinder = (radius, origin = [0, 0, 0], axis = [0, 0, 1]) => ({ type: "cylinder", axis, origin, radius });
const faces = (a, b, instances = [0, 0]) => [{ id: "i0/face/1", surface: a, instance: instances[0] }, { id: "i0/face/2", surface: b, instance: instances[1] }];
const ids = list => list.map(item => `${item.kind}:${item.id}`);

test("two parallel flat faces of a part read their gap, and setting it is a preview", () => {
  const found = faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 0]), plane([0, 0, -1], [5, 5, 6])) });
  assert.deepEqual(ids(found), ["reading:distance", "preview:set-distance"]);
  assert.equal(found[0].label, "6 mm apart");
});

test("two parts' flat faces mate: flush ones coincident, apart ones at a distance", () => {
  const flush = faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 3]), plane([0, 0, -1], [9, 0, 3]), [0, 1]), assembly: true });
  assert.deepEqual(ids(flush), ["reading:distance", "mate:mate"]);
  assert.equal(flush[0].label, "Flush");
  assert.equal(flush[1].mateType, "coincident");
  const apart = faceSuggestions({ faces: faces(plane([1, 0, 0], [0, 0, 0]), plane([1, 0, 0], [2.5, 0, 0]), [0, 1]), assembly: true });
  assert.equal(apart[1].mateType, "distance");
});

test("faces meeting at an edge offer Fillet and Chamfer on the edges they share, with their angle", () => {
  const found = faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 0]), plane([1, 0, 0], [0, 0, 0])), shared: ["i0/edge/7"] });
  assert.deepEqual(ids(found), ["reading:angle", "command:fillet", "command:chamfer"]);
  assert.equal(found[0].label, "Square");
  assert.deepEqual(found[1].edges, ["i0/edge/7"]);
  assert.equal(found[2].command, "chamfer");
  // An assembly's faces are placed, not modeled: no corner to round there.
  assert.deepEqual(ids(faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 0]), plane([1, 0, 0], [0, 0, 0])), shared: ["i0/edge/7"], assembly: true })),
    ["reading:angle"]);
});

test("a hole and the shaft in it ask for an ISO fit at their nominal size, and two parts' mate concentric", () => {
  const found = faceSuggestions({ faces: faces(cylinder(11), cylinder(10.995, [0, 0, 8]), [0, 1]), assembly: true });
  assert.deepEqual(ids(found), ["reading:coaxial", "ask:iso-fit", "mate:mate"]);
  assert.match(found[1].request, /\$iso-fits/);
  assert.match(found[1].request, /Ø22 mm hole/);
  assert.equal(found[2].mateType, "concentric");
  // Off its axis, or far apart in size, it is no fit.
  assert.deepEqual(ids(faceSuggestions({ faces: faces(cylinder(11), cylinder(11, [30, 0, 0])) })), []);
  assert.deepEqual(ids(faceSuggestions({ faces: faces(cylinder(11), cylinder(3)) })), ["reading:coaxial"]);
  // ISO 286 is metric: an inch part is not offered it.
  assert.deepEqual(ids(faceSuggestions({ faces: faces(cylinder(0.25), cylinder(0.25)), units: "in" })), ["reading:coaxial"]);
});

test("a hole's rim offers its chamfer, and anything but two faces the scene describes suggests nothing", () => {
  assert.deepEqual(ids(faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 6]), cylinder(3)), shared: ["i0/edge/2"] })),
    ["reading:square", "command:fillet", "command:chamfer"]);
  assert.deepEqual(faceSuggestions({ faces: faces(plane([0, 0, 1], [0, 0, 0]), null) }), []);
  assert.deepEqual(faceSuggestions({ faces: [faces(cylinder(1), cylinder(1))[0]] }), []);
});

test("lengths read as a drawing writes them, and Mate starts concentric on two round faces", () => {
  assert.equal(lengthText(6), "6 mm");
  assert.equal(lengthText(12.3456), "12.35 mm");
  assert.equal(lengthText(0.25, "in"), "0.25 in");
  assert.equal(suggestedMateType([{ type: "cylinder" }, { type: "cylinder" }]), "concentric");
  assert.equal(suggestedMateType([{ type: "plane" }, { type: "cylinder" }]), "coincident");
  assert.equal(suggestedMateType([{ type: "cylinder" }]), "coincident");
});
