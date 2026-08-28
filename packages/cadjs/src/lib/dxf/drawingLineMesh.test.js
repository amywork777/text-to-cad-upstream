import assert from "node:assert/strict";
import test from "node:test";

import { drawingLinesToRibbonPositions } from "./drawingLineMesh.js";

// A document profile's geometry: two open dimension-style lines, no contours.
const DXF_DATA = {
  geometry: {
    lines: [
      { layer: "DIM", start: [0, 0], end: [100, 0] },
      { layer: "DIM", start: [0, -5], end: [0, 5] },
    ],
    arcs: [],
    circles: [],
  },
};

test("open line work becomes ribbon triangles in the sheet plane", () => {
  const positions = drawingLinesToRibbonPositions(DXF_DATA);
  // Two segments, two triangles each, three vertices each.
  assert.equal(positions.length, 2 * 2 * 3 * 3);
  // Every vertex stays in the sheet plane (y = elevation = 0).
  for (let index = 1; index < positions.length; index += 3) {
    assert.equal(positions[index], 0);
  }
  // Ribbon width scales from the drawing diagonal but never below the floor.
  const zs = [];
  for (let index = 0; index < 18; index += 3) {
    zs.push(positions[index + 2]);
  }
  const width = Math.max(...zs) - Math.min(...zs);
  assert.ok(width >= 0.1, `hairline must be at least the 2x0.05mm floor, got ${width}`);
  assert.ok(width < 1, `hairline must stay hairline on a 100mm drawing, got ${width}`);
});

test("triangles face +Y (out of the sheet)", () => {
  const positions = drawingLinesToRibbonPositions(DXF_DATA);
  for (let t = 0; t < positions.length; t += 9) {
    const ax = positions[t], az = positions[t + 2];
    const bx = positions[t + 3], bz = positions[t + 5];
    const cx = positions[t + 6], cz = positions[t + 8];
    // y-component of the cross product in the XZ plane: (c-a) x (b-a) ... glTF
    // winding is counter-clockwise seen from +Y, i.e. cross((b-a),(c-a)).y > 0.
    const crossY = ((bz - az) * (cx - ax)) - ((bx - ax) * (cz - az));
    assert.ok(crossY > 0, `triangle at ${t} winds away from +Y (${crossY})`);
  }
});

test("degenerate and empty inputs produce empty output", () => {
  assert.equal(drawingLinesToRibbonPositions({ geometry: { lines: [] } }).length, 0);
  assert.equal(drawingLinesToRibbonPositions(null).length, 0);
  assert.equal(
    drawingLinesToRibbonPositions({
      geometry: { lines: [{ layer: "", start: [3, 3], end: [3, 3] }] },
    }).length,
    0,
  );
});
