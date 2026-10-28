/**
 * The sketch task environment's icons, from the icon generator (`scripts/nx-icons.py`), drawn flat in
 * the sketch's blue as NX draws its curve tools: what each tool draws, or does to what is drawn, with
 * a handle where each of its clicks goes.
 */
import { generatedIcon } from "./cadIcons.jsx";

/** The generator's icon of each sketch tool, by its id in `SKETCH_TOOLS`. */
export const SKETCH_TOOL_ICON_NAMES = Object.freeze({
  line: "sketch-line", rectangle: "sketch-rectangle", center_rectangle: "sketch-center-rectangle",
  three_point_rectangle: "sketch-three-point-rectangle", circle: "sketch-circle", perimeter_circle: "sketch-three-point-circle",
  arc: "sketch-arc", three_point_arc: "sketch-three-point-arc", tangent_arc: "sketch-tangent-arc", slot: "sketch-slot",
  centerpoint_slot: "sketch-center-slot", polygon: "sketch-polygon", spline: "sketch-spline", centerline: "sketch-reference-line",
  point: "sketch-point", dimension: "sketch-dimension", fillet: "sketch-fillet", chamfer: "sketch-chamfer", trim: "sketch-trim",
  extend: "sketch-extend", offset: "sketch-offset", mirror: "sketch-mirror", move_entities: "sketch-move", copy_entities: "sketch-copy",
  rotate_entities: "sketch-rotate", scale_entities: "sketch-scale", linear_pattern: "sketch-linear-pattern",
  circular_pattern: "sketch-circular-pattern", convert: "sketch-project", intersection: "sketch-intersection",
});

/** Each sketch tool's icon, by its id in `SKETCH_TOOLS`. */
export const SKETCH_TOOL_ICONS = Object.freeze(Object.fromEntries(Object.entries(SKETCH_TOOL_ICON_NAMES).map(([id, name]) => [id, generatedIcon(name)])));

/** Convert To/From Reference: what is selected made reference geometry, or back. */
export const ConstructionIcon = generatedIcon("sketch-convert-reference");
/** Orient View, and Orient View to Sketch: square on to the face or plane picked. */
export const NormalToIcon = generatedIcon("orient-view");
/** The drawing sheet's dimension tool, Rapid Dimension's. */
export const SmartDimensionIcon = SKETCH_TOOL_ICONS.dimension;
