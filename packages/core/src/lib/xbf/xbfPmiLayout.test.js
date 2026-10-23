// Where an engine document's PMI is drawn (`xbfPmiLayout.js`), on core's bracket
// (`__fixtures__/bracket`: a 40 x 20 x 4 plate on z = -2..2 with a Ø8 hole at the origin, and two
// pegs): from the plate's faces as the scene places them, its annotations stand where the code
// placed them, or out from their feature where it placed none, and a distance is drawn square
// between its two faces.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as THREE from "three";

import { loadXbfDocument } from "./xbfDocument.js";
import { readXbfPmi } from "./xbfPmi.js";
import { pmiConstruction, pmiFeaturePoint, pmiMovedPlacement } from "./xbfPmiLayout.js";
import { createXbfScene } from "./xbfScene.js";

const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), "__fixtures__");
const read = file => fs.readFileSync(path.join(FIXTURES, file));
const STRUCTURE = JSON.parse(read("bracket/structure.json"));
const ENVIRONMENT = new Uint8Array([...new TextEncoder().encode("#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n"), 255, 255, 255, 128]).buffer;

async function bracket() {
  const fetch = async (url) => {
    if (url.endsWith("/api/look")) return new Response(read("look.json"));
    if (url.endsWith("/api/look/environment")) return new Response(ENVIRONMENT);
    const part = /\/part\/([^/]+)$/.exec(url);
    return new Response(part ? read(`bracket/${part[1]}.xbm`) : JSON.stringify(STRUCTURE));
  };
  return createXbfScene(THREE, await loadXbfDocument("http://127.0.0.1:9/api/doc/bracket", { fetch }));
}

const TOP = "i0/face/2", BOTTOM = "i0/face/5", HOLE = "i0/face/11";
const BOUNDS = { min: [-20, -10, -2], max: [20, 10, 14] };
const near = (actual, expected, what = "") => assert.ok(Math.abs(actual - expected) < 1e-6, `${what} ${actual} is not ${expected}`);
const nearPoint = (actual, expected, what = "") => expected.forEach((value, axis) => near(actual[axis], value, `${what}[${axis}]`));
const entry = (item) => readXbfPmi({ pmi: [{ status: "ok", refs: [], presentation: null, ...item }] })[0];
const flatness = (presentation = null) => entry({ id: "top-flat", kind: "geometric_tolerance", presentation,
  geometric_tolerance: { characteristic: "flatness", value: 0.05, unit: "mm", datums: [] } });

test("a leader starts on its feature: a flat face's own node, a hole's rim", async () => {
  const scene = await bracket();
  const top = scene.elementGeometry(TOP, { points: true });
  const start = pmiFeaturePoint(top, [0, 0, 6]);
  near(start[2], 2, "on the top");
  // Not in the hole the face's middle falls in.
  assert.ok(Math.hypot(start[0], start[1]) >= 4 - 1e-6, `${start} is in the hole`);
  const rim = pmiFeaturePoint(scene.elementGeometry(HOLE, { points: true }), [0, 0, 6]);
  near(Math.hypot(rim[0], rim[1]), 4, "on the hole's wall");
  near(Math.abs(rim[2]), 2, "at an end of it");
});

test("an annotation the code placed stands where it was placed; one it never placed stands out from its feature", async () => {
  const scene = await bracket();
  const geometry = { feature: scene.elementGeometry(TOP, { points: true }) };
  const placed = pmiConstruction(flatness({ anchor: [10, 5, 2], offset: [4, 0, 6] }), { geometry, bounds: BOUNDS });
  assert.equal(placed.placed, "given");
  nearPoint(placed.anchor, [10, 5, 2]);
  nearPoint(placed.label, [14, 5, 8]);
  const free = pmiConstruction(flatness(), { geometry, bounds: BOUNDS });
  assert.equal(free.placed, "default");
  near(free.anchor[2], 2, "its leader on the top");
  assert.ok(free.label[2] > 2 + 1, `${free.label} stands above the top`);
  // A second annotation of the same face is turned from the first.
  const second = pmiConstruction(flatness(), { geometry, bounds: BOUNDS, turn: 1 });
  assert.ok(Math.hypot(second.label[0] - free.label[0], second.label[1] - free.label[1]) > 1, "two on one face stand apart");
  // A drag not yet written draws it at the drag's place, as a placement.
  const dragged = pmiConstruction(flatness(), { geometry, bounds: BOUNDS, placement: { anchor: free.anchor, offset: [0, 0, 12] } });
  nearPoint(dragged.label, [free.anchor[0], free.anchor[1], 14]);
});

test("a distance is drawn square between its faces, through its label", async () => {
  const scene = await bracket();
  const thickness = entry({ id: "thickness", kind: "dimension", presentation: { anchor: [20, 0, -2], offset: [6, 0, 2] },
    dimension: { type: "distance", nominal: { value: 4, unit: "mm", source: "geometry" }, tolerance: null } });
  const drawn = pmiConstruction(thickness, { geometry: { from: scene.elementGeometry(BOTTOM, { points: true }), to: scene.elementGeometry(TOP, { points: true }) }, bounds: BOUNDS });
  nearPoint(drawn.label, [26, 0, 0]);
  nearPoint(drawn.dimension.from, [26, 0, -2], "on the bottom's plane");
  nearPoint(drawn.dimension.to, [26, 0, 2], "on the top's plane");
  nearPoint(drawn.dimension.extensions[0][0], [20, 0, -2], "from the anchor");
  nearPoint(drawn.dimension.extensions[1][0], [20, 0, 2], "from its foot on the top");
  // An anchor the code put off the face (on the side, mid-height) still extends from each face's plane.
  const mid = pmiConstruction({ ...thickness, presentation: { anchor: [20, 0, 0], offset: [6, 0, 1] } },
    { geometry: { from: scene.elementGeometry(BOTTOM, { points: true }), to: scene.elementGeometry(TOP, { points: true }) }, bounds: BOUNDS });
  nearPoint(mid.dimension.extensions[0][0], [20, 0, -2], "from the bottom's plane");
  nearPoint(mid.dimension.extensions[1][0], [20, 0, 2], "from the top's plane");
  nearPoint(mid.dimension.extensions[0][1], [26, 0, -2]);
  // Placed by no code, it stands halfway between them, out to the side.
  const free = pmiConstruction({ ...thickness, presentation: null }, { geometry: { from: scene.elementGeometry(BOTTOM, { points: true }), to: scene.elementGeometry(TOP, { points: true }) }, bounds: BOUNDS });
  near(free.label[2], 0, "halfway up");
  near(free.dimension.from[2], -2);
  near(free.dimension.to[2], 2);
});

test("a feature not on the page draws at its placement or not at all, and a move changes only the offset", () => {
  const broken = pmiConstruction(flatness({ anchor: [0, 0, 2], offset: [0, 0, 6] }), { geometry: { feature: null }, bounds: BOUNDS });
  assert.equal(broken.anchor, null);
  nearPoint(broken.label, [0, 0, 8]);
  assert.equal(pmiConstruction(flatness(), { geometry: { feature: null }, bounds: BOUNDS }), null);
  assert.deepEqual(pmiMovedPlacement({ anchor: [1, 2, 3], offset: [0, 0, 1] }, [4, 2, 9]), { anchor: [1, 2, 3], offset: [3, 0, 6] });
});

test("a placement is in its part's frame: drawn where the part stands, and written back in its frame", async () => {
  const { pmiPresentationToPart, pmiPresentationToScene } = await import("./xbfPmiLayout.js");
  // Turned a quarter about z and moved 10 along x: the second peg's kind of placement.
  const matrix = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1];
  const placed = { anchor: [1, 0, 2], offset: [0, 3, 0] };
  const scene = pmiPresentationToScene(placed, matrix);
  nearPoint(scene.anchor, [10, 1, 2]);
  nearPoint(scene.offset, [-3, 0, 0], "an offset turns and does not move");
  const back = pmiPresentationToPart(scene, matrix);
  nearPoint(back.anchor, placed.anchor);
  nearPoint(back.offset, placed.offset);
  assert.equal(pmiPresentationToScene(placed, null), placed, "no placement, one frame");
});
