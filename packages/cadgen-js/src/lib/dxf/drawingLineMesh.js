/** A dimensioned DRAWING as a snapshot-able MESH: line work extruded to hairline ribbons.
 *
 * The interactive viewer draws a document-profile DXF (dimensions, sections, a title
 * block — no cut geometry) as `LineSegments` built by `buildDrawingLines.js`. The
 * headless snapshot pipeline consumes a triangle GLB, and teaching that whole chain
 * (writeGlb, the browser renderer, theming) about line primitives is a lot of new
 * surface for one consumer. So the SAME line groups are turned into thin quads lying
 * in the sheet plane: every segment becomes a ribbon two triangles wide, at a width
 * scaled from the drawing's extent so hairlines stay hairlines at any sheet size.
 *
 * Text markings are NOT rendered here — the viewer draws strings onto the sheet
 * itself; a snapshot of a dimensioned drawing shows its line graphics (dimension,
 * extension and geometry lines) without glyphs.
 */

import { buildDxfDrawingLineGroups, drawingLineBounds } from "./buildDrawingLines.js";

// Ribbon half-width as a fraction of the drawing's bounding diagonal, with an
// absolute floor so a tiny detail drawing still produces visible (and non-degenerate)
// geometry. 0.075% of the diagonal reads as a crisp hairline at snapshot resolutions.
const RELATIVE_HALF_WIDTH = 7.5e-4;
const MIN_HALF_WIDTH_MM = 0.05;

/** Triangle-soup positions (Float32Array, xyz per vertex) for one drawing's line work,
 * or an empty array when the drawing holds nothing renderable. Deterministic for a
 * given parse: segment order follows the layer grouping, width follows the bounds. */
export function drawingLinesToRibbonPositions(dxfData, options = null) {
  const groups = buildDxfDrawingLineGroups(dxfData, options);
  if (!groups.layers.length) {
    return new Float32Array(0);
  }
  const bounds = drawingLineBounds(groups);
  const spanX = bounds.max[0] - bounds.min[0];
  const spanZ = bounds.max[2] - bounds.min[2];
  const diagonal = Math.hypot(spanX, spanZ);
  const halfWidth = Math.max(
    Number(options?.halfWidth) || 0,
    diagonal * RELATIVE_HALF_WIDTH,
    MIN_HALF_WIDTH_MM,
  );

  const out = [];
  for (const layer of groups.layers) {
    const { positions } = layer;
    // Segments arrive as xyz pairs in the sheet plane (y out of the sheet).
    for (let index = 0; index + 5 < positions.length; index += 6) {
      const ax = positions[index];
      const ay = positions[index + 1];
      const az = positions[index + 2];
      const bx = positions[index + 3];
      const by = positions[index + 4];
      const bz = positions[index + 5];
      const dx = bx - ax;
      const dz = bz - az;
      const length = Math.hypot(dx, dz);
      if (!(length > 0)) {
        continue;
      }
      // Perpendicular in the sheet plane, half-width long.
      const px = (-dz / length) * halfWidth;
      const pz = (dx / length) * halfWidth;
      // Quad corners: a-p, a+p, b+p, b-p — two triangles, both wound to face +Y
      // (out of the sheet; the material is double-sided, so this is for lighting).
      out.push(
        ax - px, ay, az - pz,
        ax + px, ay, az + pz,
        bx + px, by, bz + pz,

        ax - px, ay, az - pz,
        bx + px, by, bz + pz,
        bx - px, by, bz - pz,
      );
    }
  }
  return Float32Array.from(out);
}
