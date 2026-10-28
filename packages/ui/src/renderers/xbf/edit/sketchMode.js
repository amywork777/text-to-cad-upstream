/**
 * Sketch mode's rules, pure: a constrained sketch (`cadgen.sketch`, solved by `cadgen/edit`) read
 * for drawing, what a click lands on (an existing point, a curve, a line's midpoint), what a
 * stroke infers (a line drawn horizontal), what each sketch tool sends, which dimension Smart
 * Dimension makes of what is picked, which relations a selection can take, where a dimension is
 * drawn, and what the agent is told. Everything is in the sketch's own units, on its plane.
 */
import { isFaceItem } from "./selectors.js";

/** The sketch tools, as SolidWorks' Sketch tab names them, and what each asks for, click by click. */
export const SKETCH_TOOLS = Object.freeze([
  { id: "line", label: "Line", prompts: ["Click where the line starts.", "Click where it ends. Keep clicking to chain lines; Escape stops."] },
  { id: "rectangle", label: "Corner Rectangle", prompts: ["Click a corner of the rectangle.", "Click the opposite corner."] },
  { id: "center_rectangle", label: "Center Rectangle", prompts: ["Click the center of the rectangle.", "Click a corner."] },
  { id: "three_point_rectangle", label: "3 Point Corner Rectangle", prompts: ["Click a corner.", "Click the end of its first side.", "Click to set how wide it is."] },
  { id: "circle", label: "Circle", prompts: ["Click the center of the circle.", "Click to set its radius."] },
  { id: "perimeter_circle", label: "Perimeter Circle", prompts: ["Click a point the circle passes through.", "Click a second.", "Click a third."] },
  { id: "arc", label: "Centerpoint Arc", prompts: ["Click the center of the arc.", "Click where the arc starts.", "Click where it ends."] },
  { id: "three_point_arc", label: "3 Point Arc", prompts: ["Click where the arc starts.", "Click where it ends.", "Click to set how far it bows."] },
  { id: "tangent_arc", label: "Tangent Arc", prompts: ["Click the end of a line or an arc to go on from.", "Click where the arc ends."] },
  { id: "slot", label: "Straight Slot", prompts: ["Click the center of one end.", "Click the center of the other end.", "Click to set its width."] },
  { id: "centerpoint_slot", label: "Centerpoint Straight Slot", prompts: ["Click the slot's center.", "Click the center of one end.", "Click to set its width."] },
  { id: "polygon", label: "Polygon", prompts: ["Click the center of the polygon.", "Click a corner."] },
  { id: "spline", label: "Spline", prompts: ["Click where the spline starts.",
    "Click each point it passes through. Double-click or press Enter to end it; click its first point to close it."] },
  { id: "centerline", label: "Centerline", prompts: ["Click where the centerline starts.", "Click where it ends."] },
  { id: "point", label: "Point", prompts: ["Click to place a point."] },
  { id: "dimension", label: "Smart Dimension", prompts: ["Pick a line, a circle, or two items to dimension. An edge of the model comes in dashed to dimension to.", "Pick a second item or a model edge, or click to place the dimension.", "Click to place the dimension."] },
  { id: "fillet", label: "Sketch Fillet", prompts: ["Click a corner to round, or the first of two lines that meet.", "Click the second line."] },
  { id: "chamfer", label: "Sketch Chamfer", prompts: ["Click a corner to cut, or the first of two lines that meet.", "Click the second line."] },
  { id: "trim", label: "Trim Entities", prompts: ["Click the part of a curve to cut away, or drag across curves to cut each where you cross it. It is cut back to the curves that cross it; a curve nothing crosses is deleted."] },
  { id: "extend", label: "Extend Entities", prompts: ["Click a line or an arc near the end to run on. It goes on to the first curve it meets."] },
  { id: "offset", label: "Offset Entities", prompts: ["Click a line, an arc or a circle to offset it, and the chain it is part of."] },
  { id: "mirror", label: "Mirror Entities", prompts: ["Click the entities to mirror.", "Click more of them, or the centerline to mirror about."] },
  { id: "move_entities", label: "Move Entities", prompts: ["Select what to move (Shift adds), then click a base point.", "Click where the base point goes."] },
  { id: "copy_entities", label: "Copy Entities", prompts: ["Select what to copy (Shift adds), then click a base point.", "Click where the copy's base point goes."] },
  { id: "rotate_entities", label: "Rotate Entities", prompts: ["Select what to rotate (Shift adds), then click the center to turn it about.",
    "Click a direction to turn from, or type the angle.", "Click the direction to turn to."] },
  { id: "scale_entities", label: "Scale Entities", prompts: ["Select what to scale (Shift adds), then click the point to scale it about.",
    "Click a reference point, or type the scale factor.", "Click where the reference point goes."] },
  { id: "linear_pattern", label: "Linear Sketch Pattern", prompts: ["Click the entities to copy in a row, set the spacing and instances, then make the pattern."] },
  { id: "circular_pattern", label: "Circular Sketch Pattern", prompts: ["Click the entities to copy round, and a point to turn them about (else the origin), then make the pattern."] },
  { id: "convert", label: "Convert Entities", prompts: ["Select edges or a face of the model, then Convert. They come into the sketch and stay on the model as it changes."] },
  { id: "intersection", label: "Intersection Curve", prompts: ["Brings in where the part crosses this sketch's plane, and keeps it there as the part changes."] },
]);

/** The tools that change what is drawn rather than draw: each takes its own clicks (see `SketchOverlay.jsx`). */
export const MODIFY_TOOLS = Object.freeze(["fillet", "chamfer", "trim", "extend", "offset", "mirror", "linear_pattern", "circular_pattern", "intersection"]);
/** The sketch patterns: each takes what is selected, and its panel's settings, and is made by its OK. */
export const PATTERN_TOOLS = Object.freeze(["linear_pattern", "circular_pattern"]);
/** The tools that take a corner: a point where two lines meet, or the two lines. */
export const CORNER_TOOLS = Object.freeze(["fillet", "chamfer"]);
/** The tools that pick on the model rather than the sketch: Convert Entities takes its edges and faces, so the model has the presses. */
export const MODEL_TOOLS = Object.freeze(["convert"]);

/** The ids of the curves `after` has that `before` did not, in the order they were made. */
export const newCurves = (before, after) => {
  const had = new Set((before?.curves || []).map(curve => curve.id));
  return (after?.curves || []).filter(curve => !had.has(curve.id)).map(curve => curve.id);
};

/** The size a sketch tool uses until one is typed, in the part's units: a fillet's radius, a chamfer's or an offset's distance. */
export const toolSize = (typed, units, tool) => String(typed ?? "").trim()
  || (tool === "pattern" ? (units === "in" ? ".5" : "10") : units === "in" ? (tool === "fillet" ? "0.1" : "0.06") : (tool === "fillet" ? "2" : "1"));

// How near, as a share of the sketch's size, two places are one.
const nearness = state => 1e-6 * Math.max(1, ...(state?.points || []).flatMap(point => [Math.abs(point.x), Math.abs(point.y)]));

export const sketchTool = id => SKETCH_TOOLS.find(tool => tool.id === id) || null;

/**
 * Sketch mode's one-key shortcuts, as Fusion's and SolidCraft's sketchers have them: the tool each
 * letter picks up (again, puts it down). X, Construction Geometry, is the ribbon's button.
 */
export const SKETCH_KEYS = Object.freeze({ l: "line", r: "rectangle", c: "circle", p: "point", d: "dimension", t: "trim", o: "offset" });
/** The key that picks up a sketch tool, for its tooltip, or null. */
export const sketchKey = id => (Object.entries(SKETCH_KEYS).find(([, tool]) => tool === id)?.[0] || "").toUpperCase() || null;

/** How many clicks a drawing tool takes; a line chains, so its count restarts from its end. */
export const TOOL_CLICKS = Object.freeze({ line: 2, centerline: 2, rectangle: 2, center_rectangle: 2, three_point_rectangle: 3, circle: 2,
  perimeter_circle: 3, arc: 3, three_point_arc: 3, tangent_arc: 2, slot: 3, centerpoint_slot: 3, polygon: 2, point: 1, spline: Infinity });

/**
 * The tools drawn as one family, as SolidWorks' Sketch tab puts them in one flyout: the family's
 * button is the tool last picked of it, its chevron the others.
 */
export const SKETCH_FAMILIES = Object.freeze({
  move_entities: ["move_entities", "copy_entities", "rotate_entities", "scale_entities"],
  rectangle: ["rectangle", "center_rectangle", "three_point_rectangle"],
  circle: ["circle", "perimeter_circle"],
  arc: ["arc", "three_point_arc", "tangent_arc"],
  slot: ["slot", "centerpoint_slot"],
});

/**
 * The sketch toolbar's tools, as NX's sketch task environment groups them: what draws (Curve), then what changes
 * what is drawn (Edit Curve), each a button by its first tool's id, and a family's (`SKETCH_FAMILIES`) the first
 * of its flyout. Rapid Dimension and Convert To/From Reference stand in the Constraints group after them.
 */
export const SKETCH_ENTITIES = Object.freeze(["line", "rectangle", "circle", "arc", "slot", "polygon", "spline", "centerline", "point"]);
export const SKETCH_MODIFY = Object.freeze(["fillet", "chamfer", "trim", "extend", "convert", "intersection", "offset", "mirror", "move_entities",
  "linear_pattern", "circular_pattern"]);

/** The sketch tools that move, copy, turn or size what is selected, as SolidWorks' Move Entities flyout has them. */
export const TRANSFORM_TOOLS = Object.freeze(["move_entities", "copy_entities", "rotate_entities", "scale_entities"]);
/** How many clicks each transform tool takes: a base and a target, or a center and a turn (or size) from one direction to another. */
export const TRANSFORM_CLICKS = Object.freeze({ move_entities: 2, copy_entities: 2, rotate_entities: 3, scale_entities: 3 });

/** The points the selected entities stand on, once each: a line's ends, an arc's center and ends, a circle's center, a spline's points, a point itself. */
export function entityPoints(state, selection) {
  const known = new Set((state?.points || []).map(point => point.id));
  const found = [];
  const take = id => { if (id && id !== "Origin" && known.has(id) && !found.includes(id)) found.push(id); };
  for (const id of selection) {
    if (known.has(id)) { take(id); continue; }
    const curve = (state?.curves || []).find(each => each.id === id);
    if (!curve || curve.derived) continue;
    for (const key of ["start", "end", "center"]) take(curve[key]);
    for (const point of curve.points || []) take(point);
  }
  return found;
}

/**
 * What a transform tool does to a place, from its clicks (`placed`, the pointer standing for the
 * next): Move and Copy by the second click less the first; Rotate about the first by the turn from
 * the second to the third (or `angle` typed, in degrees); Scale about the first by the third's
 * distance over the second's (or `factor` typed). Null until it has what it needs.
 */
export function transformOf(tool, placed, { angle = null, factor = null, by: typed = null } = {}) {
  const [a, b, c] = placed;
  if (tool === "move_entities" || tool === "copy_entities") {
    if (!a || (!b && !typed)) return null;
    const by = typed || sub(b, a);
    return { by, factor: 1, place: p => add(p, by) };
  }
  if (!a) return null;
  if (tool === "rotate_entities") {
    const turn = angle !== null ? (angle * Math.PI) / 180
      : b && c ? Math.atan2(c[1] - a[1], c[0] - a[0]) - Math.atan2(b[1] - a[1], b[0] - a[0]) : null;
    if (turn === null || !Number.isFinite(turn)) return null;
    const [cs, sn] = [Math.cos(turn), Math.sin(turn)];
    return { turn, factor: 1, place: p => { const d = sub(p, a); return [a[0] + cs * d[0] - sn * d[1], a[1] + sn * d[0] + cs * d[1]]; } };
  }
  if (tool === "scale_entities") {
    const by = factor !== null ? factor : b && c && hypot(a, b) ? hypot(a, c) / hypot(a, b) : null;
    if (!by || !Number.isFinite(by) || by <= 0) return null;
    return { factor: by, place: p => add(a, scale(sub(p, a), by)) };
  }
  return null;
}

/** The change a transform sends for what is selected: its points moved (scaled, its circles' radii too), or Copy's copies. */
export function transformOp(tool, state, selection, transform) {
  if (!transform) return null;
  if (tool === "copy_entities") return selection.length ? { kind: "copy", items: [...selection], by: transform.by } : null;
  const { points } = sketchGeometry(state);
  const moved = entityPoints(state, selection).map(id => ({ point: id, to: transform.place(at(points.get(id))) }));
  const curves = transform.factor === 1 ? [] : (state?.curves || [])
    .filter(curve => selection.includes(curve.id) && curve.kind === "circle").map(curve => ({ curve: curve.id, radius: curve.radius * transform.factor }));
  return moved.length || curves.length ? { kind: "move", points: moved, ...(curves.length ? { curves } : {}) } : null;
}

/** The selected curves as a transform would leave them, to draw where they would go. */
export function transformedCurves(state, selection, transform) {
  if (!transform) return [];
  const { place, factor } = transform;
  return sketchGeometry(state).curves.filter(curve => selection.includes(curve.id) && !curve.derived).map(curve => {
    if (curve.kind === "line") return { ...curve, a: place(curve.a), b: place(curve.b), view: null };
    if (curve.kind === "spline") return { ...curve, samples: curve.samples.map(place) };
    if (curve.kind === "circle") return { ...curve, c: place(curve.c), r: curve.r * factor };
    return { ...curve, c: place(curve.c), s: place(curve.s), e: place(curve.e), r: curve.r * factor };
  });
}

/** A 3 Point Corner Rectangle's other two corners: square off its first side, as wide as `third` is off it; null when it has no width. */
export function threePointRectangle(a, b, third) {
  const along = sub(b, a);
  const length = Math.hypot(along[0], along[1]);
  if (!length) return null;
  const n = [-along[1] / length, along[0] / length];
  const width = dot(sub(third, a), n);
  if (Math.abs(width) < 1e-9 * Math.max(1, length)) return null;
  return { opposite: add(b, scale(n, width)), fourth: add(a, scale(n, width)) };
}

/**
 * Places along a smooth curve through `places` in order (a Catmull-Rom curve), `closed` round from
 * the last back to the first: a spline as it is drawn before the sketch solves it (being drawn,
 * or its points dragged). The solved one passes through the same points.
 */
export function splineThrough(places, closed = false, steps = 16) {
  const count = places.length;
  if (count < 2) return places.map(place => [...place]);
  const end = index => (index < 0 ? sub(scale(places[0], 2), places[1]) : sub(scale(places[count - 1], 2), places[count - 2]));
  const get = index => (closed ? places[((index % count) + count) % count] : index < 0 || index >= count ? end(index) : places[index]);
  const out = [];
  for (let i = 0; i < (closed ? count : count - 1); i += 1) {
    const [p0, p1, p2, p3] = [get(i - 1), get(i), get(i + 1), get(i + 2)];
    for (let k = 0; k < steps; k += 1) {
      const t = k / steps;
      out.push([0, 1].map(axis => 0.5 * (2 * p1[axis] + (p2[axis] - p0[axis]) * t + (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * t * t
        + (3 * p1[axis] - p0[axis] - 3 * p2[axis] + p3[axis]) * t * t * t)));
    }
  }
  out.push([...places[closed ? 0 : count - 1]]);
  return out;
}

/** How many sides Polygon draws, as typed in its panel: a whole number from 3 to 64, else 6. */
export function polygonSides(typed) {
  const sides = Number(String(typed ?? "").trim());
  return Number.isInteger(sides) && sides >= 3 && sides <= 64 ? sides : 6;
}

const KIND_NAMES = Object.freeze({ line: "line", circle: "circle", arc: "arc" });
// A line drawn within this many degrees of level, or of plumb, is drawn so (and kept so).
export const INFER_DEGREES = 4;

const hypot = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const scale = (a, s) => [a[0] * s, a[1] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const unit = a => { const length = Math.hypot(a[0], a[1]) || 1; return [a[0] / length, a[1] / length]; };
const at = point => [point.x, point.y];

/**
 * The sketch as drawing reads it: its points by name, and each curve with its points in place
 * (a line's two ends, a circle's center and radius, an arc's center, ends and radius).
 */
export function sketchGeometry(state) {
  const points = new Map((state?.points || []).map(point => [point.id, point]));
  const curves = (state?.curves || []).map(curve => {
    const base = { id: curve.id, kind: curve.kind, construction: Boolean(curve.construction), defined: Boolean(curve.defined) };
    // A chamfer's line, and a fillet's arc, worked out from its lines: its places, no points of its own.
    if (curve.derived === "chamfer") return { ...base, derived: curve.derived, a: curve.s, b: curve.e, dimension: curve.dimension };
    if (curve.derived) return { ...base, derived: curve.derived, c: curve.c, s: curve.s, e: curve.e, r: curve.radius, clockwise: Boolean(curve.clockwise), dimension: curve.dimension };
    // A line drawn up to the fillet at an end (`view`), its ends still at the corner.
    if (curve.kind === "line") return { ...base, a: at(points.get(curve.start)), b: at(points.get(curve.end)), start: curve.start, end: curve.end, view: curve.shown || null };
    if (curve.kind === "circle") return { ...base, c: at(points.get(curve.center)), r: curve.radius, center: curve.center };
    // A spline: its points, and the places along it the sketch solved it through.
    if (curve.kind === "spline") return { ...base, samples: curve.samples || [], points: curve.points || [], closed: Boolean(curve.closed),
      start: curve.start, end: curve.end };
    return { ...base, c: at(points.get(curve.center)), s: at(points.get(curve.start)), e: at(points.get(curve.end)), r: curve.radius,
      clockwise: Boolean(curve.clockwise), center: curve.center, start: curve.start, end: curve.end };
  });
  return { points, curves };
}

/** An arc's start angle and sweep, in radians, negative when it turns clockwise. */
export function arcSweep(curve) {
  const a0 = Math.atan2(curve.s[1] - curve.c[1], curve.s[0] - curve.c[0]);
  const a1 = Math.atan2(curve.e[1] - curve.c[1], curve.e[0] - curve.c[0]);
  let sweep = (a1 - a0) % (2 * Math.PI);
  if (sweep <= 0) sweep += 2 * Math.PI;
  return { start: a0, sweep: curve.clockwise ? sweep - 2 * Math.PI : sweep };
}

function onArc(curve, angle) {
  const { start, sweep } = arcSweep(curve);
  let offset = (angle - start) % (2 * Math.PI);
  if (sweep >= 0) { if (offset < 0) offset += 2 * Math.PI; return offset <= sweep; }
  if (offset > 0) offset -= 2 * Math.PI;
  return offset >= sweep;
}

/** The point of a curve nearest a place, and how far it is. */
export function nearestOnCurve(curve, place) {
  if (curve.kind === "spline") {
    // The nearest place on its drawn run of places.
    let best = { point: curve.samples[0] || place, distance: Infinity };
    curve.samples.forEach((a, index) => {
      const b = curve.samples[index + 1];
      if (!b) return;
      const d = sub(b, a);
      const length = dot(d, d);
      const point = add(a, scale(d, length ? Math.max(0, Math.min(1, dot(sub(place, a), d) / length)) : 0));
      const distance = hypot(point, place);
      if (distance < best.distance) best = { point, distance };
    });
    return best;
  }
  if (curve.kind === "line") {
    const [a, b] = curve.view || [curve.a, curve.b];
    const d = sub(b, a);
    const length = dot(d, d);
    const t = length ? Math.max(0, Math.min(1, dot(sub(place, a), d) / length)) : 0;
    const point = add(a, scale(d, t));
    return { point, distance: hypot(point, place) };
  }
  const toward = sub(place, curve.c);
  const point = add(curve.c, scale(unit(toward), curve.r));
  if (curve.kind === "circle" || onArc(curve, Math.atan2(toward[1], toward[0]))) return { point, distance: hypot(point, place) };
  const ends = [curve.s, curve.e].map(end => ({ point: end, distance: hypot(end, place) }));
  return ends[0].distance <= ends[1].distance ? ends[0] : ends[1];
}

/**
 * What a click at `place` lands on, within `tolerance` (in sketch units: a few pixels on screen),
 * as a CAD tool's inference reads it: an existing point (shared, not a new one), a line's
 * midpoint, or a curve (a new point kept on it); else a new point where it was clicked.
 * `exclude` names points a stroke must not land on (its own start).
 */
export function snap(state, place, tolerance, { exclude = [] } = {}) {
  const { points, curves } = sketchGeometry(state);
  let best = null;
  for (const point of points.values()) {
    if (exclude.includes(point.id)) continue;
    const distance = hypot(at(point), place);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { distance, ref: { point: point.id, at: at(point) } };
  }
  if (best) return best.ref;
  for (const curve of curves) {
    if (curve.kind !== "line" || curve.view || curve.derived) continue;
    const middle = scale(add(curve.a, curve.b), 0.5);
    const distance = hypot(middle, place);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { distance, ref: { at: middle, on: curve.id, midpoint: true } };
  }
  if (best) return best.ref;
  for (const curve of curves) {
    // A spline is landed on at its points only: a point kept on one is not a relation the sketch has.
    if (curve.derived || curve.kind === "spline") continue;
    const { point, distance } = nearestOnCurve(curve, place);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { distance, ref: { at: point, on: curve.id } };
  }
  return best ? best.ref : { at: [...place] };
}

/**
 * A place lined up with the sketch's points, as SolidWorks' inference lines take it: within
 * `tolerance` of a point's x it takes that x, and of a point's y that y (the nearest point on each
 * axis), with a guide from each point lined up with to the place, for the stroke to draw dotted.
 * `x` and `y` say which of the place's two numbers came from a point.
 */
export function alignTo(state, place, tolerance, { exclude = [] } = {}) {
  const { points } = sketchGeometry(state);
  let x = null;
  let y = null;
  for (const point of points.values()) {
    if (exclude.includes(point.id)) continue;
    const dx = Math.abs(point.x - place[0]);
    const dy = Math.abs(point.y - place[1]);
    if (dx <= tolerance && (!x || dx < x.d - 1e-12 || (Math.abs(dx - x.d) <= 1e-12 && dy < x.far))) x = { d: dx, far: dy, point };
    if (dy <= tolerance && (!y || dy < y.d - 1e-12 || (Math.abs(dy - y.d) <= 1e-12 && dx < y.far))) y = { d: dy, far: dx, point };
  }
  const aligned = [x ? x.point.x : place[0], y ? y.point.y : place[1]];
  const guides = [x, y].filter(Boolean).map(({ point }) => ({ from: [point.x, point.y], to: aligned }));
  return { at: aligned, guides, x: Boolean(x), y: Boolean(y) };
}

/** The sketch tools whose size can be typed after their first click, as a CAD sketcher's numeric input takes it. */
export const TYPED_TOOLS = Object.freeze(["line", "centerline", "rectangle", "center_rectangle", "circle"]);

/**
 * A stroke's size typed after its first click: a line's length, the way the pointer points (level
 * or plumb when it is near); a rectangle's width and height ("40 x 20", "40 20", or one number for
 * a square), toward the pointer's side; a circle's diameter. The second click it stands for, and the
 * dimensions to add once the stroke is made (`side`: which of a rectangle's lines takes each). Null
 * when what was typed is not sizes.
 */
export function typedStroke(tool, state, first, cursor, text) {
  if (!TYPED_TOOLS.includes(tool) || !first) return null;
  const numbers = String(text ?? "").trim().split(/\s*[x×*,]\s*|\s+/i).filter(Boolean).map(Number);
  if (!numbers.length || numbers.length > 2 || numbers.some(n => !Number.isFinite(n) || n <= 0)) return null;
  const start = refAt(state, first);
  const toward = sub(cursor || start, start);
  if (tool === "line" || tool === "centerline") {
    let way = Math.hypot(toward[0], toward[1]) ? unit(toward) : [1, 0];
    const inferred = inferLine([0, 0], way);
    if (inferred.relation === "horizontal") way = [Math.sign(way[0]) || 1, 0];
    if (inferred.relation === "vertical") way = [0, Math.sign(way[1]) || 1];
    return { second: { at: add(start, scale(way, numbers[0])) }, dimensions: [{ dimension: "length", value: numbers[0] }] };
  }
  if (tool === "circle") return { second: { at: add(start, [numbers[0] / 2, 0]) }, dimensions: [{ dimension: "diameter", value: numbers[0] }] };
  const [width, height = numbers[0]] = numbers;
  const half = tool === "center_rectangle" ? 0.5 : 1;
  const corner = [(toward[0] < 0 ? -1 : 1) * width * half, (toward[1] < 0 ? -1 : 1) * height * half];
  return { second: { at: add(start, corner) },
    dimensions: [{ dimension: "length", value: width, side: "level" }, { dimension: "length", value: height, side: "plumb" }] };
}

/** The dimension changes a typed stroke adds once it is made: each on the new curve it sizes. */
export function typedDimensions(typed, before, after) {
  const fresh = new Set(newCurves(before, after));
  const made = sketchGeometry(after).curves.filter(curve => fresh.has(curve.id));
  const near = nearness(after);
  const level = curve => curve.kind === "line" && Math.abs(curve.a[1] - curve.b[1]) <= near;
  const plumb = curve => curve.kind === "line" && Math.abs(curve.a[0] - curve.b[0]) <= near;
  return (typed?.dimensions || []).map(wanted => {
    const curve = wanted.side === "level" ? made.find(level) : wanted.side === "plumb" ? made.find(plumb)
      : made.find(each => each.kind === (wanted.dimension === "diameter" ? "circle" : "line"));
    return curve ? { kind: "dimension", dimension: wanted.dimension, refs: [curve.id], value: String(wanted.value) } : null;
  }).filter(Boolean);
}

/**
 * A line's end drawn within a few degrees of level or plumb, put on it, with the relation that keeps it
 * so; else, as SolidWorks infers them, within a few degrees of square to or along one of the sketch's
 * lines (`lines`: `{ id, a, b }`, the one the line starts from first), put there, with its
 * perpendicular or parallel relation to that line (`to`).
 */
export function inferLine(start, end, degrees = INFER_DEGREES, lines = []) {
  const d = sub(end, start);
  if (!d[0] && !d[1]) return { end, relation: null };
  const slope = Math.tan((degrees * Math.PI) / 180);
  if (Math.abs(d[1]) <= slope * Math.abs(d[0])) return { end: [end[0], start[1]], relation: "horizontal" };
  if (Math.abs(d[0]) <= slope * Math.abs(d[1])) return { end: [start[0], end[1]], relation: "vertical" };
  const length = Math.hypot(d[0], d[1]);
  const near = Math.sin((degrees * Math.PI) / 180);
  for (const line of lines) {
    const run = sub(line.b, line.a);
    if (!Math.hypot(run[0], run[1])) continue;
    const along = unit(run);
    // A line level or plumb itself is the horizontal or vertical one just tried.
    if (Math.abs(along[0]) < 1e-9 || Math.abs(along[1]) < 1e-9) continue;
    const across = [-along[1], along[0]];
    const parallel = (d[0] * along[0] + d[1] * along[1]) / length;
    const square = (d[0] * across[0] + d[1] * across[1]) / length;
    if (Math.abs(parallel) <= near) return { end: add(start, scale(across, Math.sign(square) * length)), relation: "perpendicular", to: line.id };
    if (Math.abs(square) <= near) return { end: add(start, scale(along, Math.sign(parallel) * length)), relation: "parallel", to: line.id };
  }
  return { end, relation: null };
}

/** The sketch's lines as `inferLine` takes them: each `{ id, a, b }`, those that start or end at `from` (a point ref) first. */
export function inferenceLines(state, from = null) {
  const lines = sketchGeometry(state).curves.filter(curve => curve.kind === "line" && !curve.derived && curve.a && curve.b);
  const touches = curve => Boolean(from?.point) && (curve.start === from.point || curve.end === from.point);
  return [...lines.filter(touches), ...lines.filter(curve => !touches(curve))].map(curve => ({ id: curve.id, a: curve.a, b: curve.b }));
}

/** Where a point ref is: an existing point's place, or the place clicked. */
export const refAt = (state, ref) => (ref?.point ? at(sketchGeometry(state).points.get(ref.point) || { x: 0, y: 0 }) : ref?.at || [0, 0]);

// A ref as the server takes it: an existing point by name, or a place (and the curve it is on).
const plain = ref => (ref.point ? { point: ref.point } : { at: [...ref.at], ...(ref.on ? { on: ref.on } : {}), ...(ref.midpoint ? { midpoint: true } : {}) });

/**
 * A 3 Point Arc as it would be drawn: the circle through its start, the place it passes and its
 * end, and its sweep from the start to the end the way that passes through the middle place, in
 * radians (negative clockwise). Null for three places in a line.
 */
export function threePointArc(start, through, end) {
  const [ax, ay] = start;
  const [bx, by] = through;
  const [cx, cy] = end;
  const d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
  const size = Math.max(1, Math.hypot(cx - ax, cy - ay)) ** 2;
  if (Math.abs(d) < 1e-9 * size) return null;
  const center = [((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d,
    ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d];
  const angle = place => Math.atan2(place[1] - center[1], place[0] - center[0]);
  const turn = value => ((value % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const from = angle(start);
  const round = turn(angle(end) - from);
  // Counterclockwise when the middle place comes before the end that way round.
  const sweep = turn(angle(through) - from) < round ? round : round - 2 * Math.PI;
  return { center, radius: Math.hypot(ax - center[0], ay - center[1]), from, sweep };
}

/**
 * Where a Tangent Arc starts, from a point of the sketch (`ref`): the line or arc it goes on from
 * (`from`: the last drawn that ends there, as a chain goes on from its last line, else the last
 * that starts there), the point's place, and the way the curve was going there (`way`, a unit
 * vector on past its end). Null for a place, or a point no line or arc ends at.
 */
export function tangentStart(state, ref) {
  if (!ref?.point) return null;
  const { points, curves } = sketchGeometry(state);
  const point = points.get(ref.point);
  const touching = [...curves].reverse().filter(each => !each.derived && (each.kind === "line" || each.kind === "arc")
    && (each.start === ref.point || each.end === ref.point));
  const curve = touching.find(each => each.end === ref.point) || touching[0];
  if (!point || !curve) return null;
  const start = at(point);
  let way;
  if (curve.kind === "line") way = curve.end === ref.point ? sub(curve.b, curve.a) : sub(curve.a, curve.b);
  else {
    // An arc runs counterclockwise from its start unless it is clockwise: on from its end, back from its start.
    const radial = sub(start, curve.c);
    const along = curve.clockwise ? [radial[1], -radial[0]] : [-radial[1], radial[0]];
    way = curve.end === ref.point ? along : scale(along, -1);
  }
  return { from: curve.id, start, way: unit(way) };
}

/**
 * A Tangent Arc from the end of a line or an arc (`startRef`, a point of the sketch) to `end`: the
 * curve it goes on from (`from`), and its center and turn, so it leaves that end the way the curve
 * was going there (`tangentStart`). Null where it has no such start, or where `end` lies straight
 * on along it.
 */
export function tangentArc(state, startRef, end) {
  const begun = tangentStart(state, startRef);
  if (!begun) return null;
  const { from, start, way: t } = begun;
  const n = [-t[1], t[0]];
  const d = sub(end, start);
  const k = dot(n, d);
  if (Math.abs(k) < 1e-9 * Math.max(1, Math.hypot(d[0], d[1]))) return null;
  const r = dot(d, d) / (2 * k);
  return { from, center: add(start, scale(n, r)), clockwise: r < 0, radius: Math.abs(r) };
}

/** A Polygon's corners as it would be drawn: `sides` of them round `center`, the first at `vertex`. */
export function polygonCorners(center, vertex, sides) {
  const radius = hypot(center, vertex);
  const start = Math.atan2(vertex[1] - center[1], vertex[0] - center[0]);
  return Array.from({ length: sides }, (_, k) => [center[0] + radius * Math.cos(start + (2 * Math.PI * k) / sides),
    center[1] + radius * Math.sin(start + (2 * Math.PI * k) / sides)]);
}

/**
 * The change a drawing tool sends once it has its clicks (`picks`, refs from `snap`): an entity
 * drawn (`cadgen/edit`'s `draw`), with what it infers. `options.construction` draws it for
 * construction; `options.clockwise` says which way an arc was swept; `options.sides`, a polygon's.
 */
export function drawOp(tool, picks, state, { construction = false, clockwise = false, sides = 6, closed = false } = {}) {
  const built = construction ? { construction: true } : {};
  const [first, second, third] = picks;
  switch (tool) {
    case "line":
    case "centerline": {
      const start = refAt(state, first);
      const inferred = second.point || second.on ? { end: refAt(state, second), relation: null }
        : inferLine(start, second.at, INFER_DEGREES, inferenceLines(state, first));
      const end = second.point || second.on ? plain(second) : { at: inferred.end };
      return { kind: "draw", entity: tool, start: plain(first), end, ...built,
        relations: inferred.relation ? [{ kind: inferred.relation, ...(inferred.to ? { to: inferred.to } : {}) }] : [] };
    }
    case "rectangle":
      return { kind: "draw", entity: "rectangle", corner: plain(first), opposite: plain(second), ...built };
    case "center_rectangle":
      return { kind: "draw", entity: "center_rectangle", center: plain(first), corner: plain(second), ...built };
    case "circle":
      return { kind: "draw", entity: "circle", center: plain(first), radius: hypot(refAt(state, first), refAt(state, second)), ...built };
    case "arc": {
      const center = refAt(state, first);
      const start = refAt(state, second);
      const radius = hypot(center, start);
      const end = third.point ? plain(third) : { at: add(center, scale(unit(sub(refAt(state, third), center)), radius)) };
      return { kind: "draw", entity: "arc", center: plain(first), start: plain(second), end, clockwise: Boolean(clockwise), ...built };
    }
    case "three_point_arc":
      return { kind: "draw", entity: "three_point_arc", start: plain(first), end: plain(second), through: { at: [...refAt(state, third)] }, ...built };
    case "tangent_arc": {
      // A centerpoint arc from the curve's end, kept tangent to it.
      const arc = tangentArc(state, first, refAt(state, second));
      if (!arc) return null;
      return { kind: "draw", entity: "arc", center: { at: arc.center }, start: plain(first), end: plain(second), clockwise: arc.clockwise,
        tangent: arc.from, ...built };
    }
    case "polygon":
      return { kind: "draw", entity: "polygon", center: plain(first), vertex: plain(second), sides: polygonSides(sides), ...built };
    case "spline":
      // Through each point clicked; closed when its first point was clicked again.
      if (picks.length < (closed ? 3 : 2)) return null;
      return { kind: "draw", entity: "spline", points: picks.map(plain), ...(closed ? { closed: true } : {}), ...built };
    case "slot": {
      const a = refAt(state, first);
      const b = refAt(state, second);
      const along = unit(sub(b, a));
      const radius = Math.abs(cross(along, sub(refAt(state, third), a)));
      return { kind: "draw", entity: "slot", center1: plain(first), center2: plain(second), radius, ...built };
    }
    case "three_point_rectangle": {
      const corners = threePointRectangle(refAt(state, first), refAt(state, second), refAt(state, third));
      if (!corners) return null;
      return { kind: "draw", entity: "three_point_rectangle", corner: plain(first), along: plain(second),
        opposite: { at: corners.opposite }, fourth: { at: corners.fourth }, ...built };
    }
    case "perimeter_circle": {
      // A circle through the three places clicked, made as a circle about the center they give.
      const circle = threePointArc(refAt(state, first), refAt(state, second), refAt(state, third));
      return circle ? { kind: "draw", entity: "circle", center: { at: circle.center }, radius: circle.radius, ...built } : null;
    }
    case "centerpoint_slot": {
      // A straight slot about its center: the other end's center as far the other way.
      const center = refAt(state, first);
      const end = refAt(state, second);
      const other = sub(scale(center, 2), end);
      const along = unit(sub(end, other));
      const radius = Math.abs(cross(along, sub(refAt(state, third), other)));
      return { kind: "draw", entity: "slot", center1: { at: other }, center2: plain(second), radius, ...built };
    }
    case "point":
      return { kind: "draw", entity: "point", at: plain(first), ...built };
    default:
      return null;
  }
}

/** What Smart Dimension measures, as its value starts: a length, a radius, a distance, an angle in degrees. */
export function measure(state, dimension, refs) {
  const { points, curves } = sketchGeometry(state);
  const curve = id => curves.find(each => each.id === id);
  const place = id => (points.has(id) ? at(points.get(id)) : curve(id)?.c);
  const [a, b] = refs;
  switch (dimension) {
    case "length": { const line = curve(a); return hypot(line.a, line.b); }
    case "radius": return curve(a).r;
    case "diameter": return curve(a).r * 2;
    case "horizontal_distance": return Math.abs(place(b)[0] - place(a)[0]);
    case "vertical_distance": return Math.abs(place(b)[1] - place(a)[1]);
    case "distance": {
      const lineA = curve(a)?.kind === "line" ? curve(a) : null;
      const lineB = curve(b)?.kind === "line" ? curve(b) : null;
      if (lineA && lineB) return Math.abs(cross(unit(sub(lineB.b, lineB.a)), sub(lineA.a, lineB.a)));
      const line = lineA || lineB;
      if (line) {
        const point = place(line === lineA ? b : a);
        return Math.abs(cross(unit(sub(line.b, line.a)), sub(point, line.a)));
      }
      return hypot(place(a), place(b));
    }
    case "angle": {
      const lineA = curve(a);
      const lineB = curve(b);
      const u = sub(lineA.b, lineA.a);
      const v = sub(lineB.b, lineB.a);
      return (Math.atan2(Math.abs(cross(u, v)), dot(u, v)) * 180) / Math.PI;
    }
    default:
      return 0;
  }
}

/**
 * The dimension Smart Dimension makes of what is picked, as SolidWorks makes it: a line's
 * length, a circle's diameter, an arc's radius; between two points (or centers) the horizontal
 * distance when it is placed above or below them, the vertical one beside them, the straight one
 * between; a point and a line their distance; two lines the angle between them, or their distance
 * when they are parallel. `place` is where the pointer is, to place it. Null when it cannot.
 */
export function dimensionFor(state, picks, place = null) {
  const { points, curves } = sketchGeometry(state);
  const curve = id => curves.find(each => each.id === id);
  const kindOf = id => (points.has(id) ? "point" : curve(id)?.kind);
  const make = (dimension, refs) => ({ dimension, refs, value: measure(state, dimension, refs) });
  if (picks.some(id => curve(id)?.derived)) return null;
  if (picks.length === 1) {
    const kind = kindOf(picks[0]);
    if (kind === "line") return make("length", picks);
    if (kind === "circle") return make("diameter", picks);
    if (kind === "arc") return make("radius", picks);
    return null;
  }
  if (picks.length !== 2) return null;
  const [a, b] = picks;
  const kinds = [kindOf(a), kindOf(b)];
  // A circle or an arc beside a point or another of them is measured at its center.
  const centered = picks.map((id, index) => (kinds[index] === "circle" || kinds[index] === "arc" ? curve(id).center : id));
  if (kinds.every(kind => kind === "line")) {
    const u = unit(sub(curve(a).b, curve(a).a));
    const v = unit(sub(curve(b).b, curve(b).a));
    return Math.abs(cross(u, v)) < 1e-6 ? make("distance", picks) : make("angle", picks);
  }
  if (kinds.includes("line")) {
    const other = kinds[0] === "line" ? centered[1] : centered[0];
    const line = kinds[0] === "line" ? a : b;
    return make("distance", [other, line]);
  }
  const [p, q] = centered.map(id => at(points.get(id)));
  if (place) {
    const [xLow, xHigh] = [Math.min(p[0], q[0]), Math.max(p[0], q[0])];
    const [yLow, yHigh] = [Math.min(p[1], q[1]), Math.max(p[1], q[1])];
    const beside = place[0] < xLow || place[0] > xHigh;
    const aboveOrBelow = place[1] < yLow || place[1] > yHigh;
    if (aboveOrBelow && !beside) return make("horizontal_distance", centered);
    if (beside && !aboveOrBelow) return make("vertical_distance", centered);
  }
  return make("distance", centered);
}

/**
 * The relations SolidWorks' Add Relations offers for a selection, in its order: Horizontal and
 * Vertical for a line or two points, Coincident and Midpoint for a point and a line, Tangent for a
 * line and an arc or circle, Parallel, Perpendicular and Equal for two lines, and so on.
 */
export function relationsFor(state, selection) {
  const { points, curves } = sketchGeometry(state);
  if (selection.some(id => curves.find(curve => curve.id === id)?.derived)) return [];
  const kinds = selection.map(id => (points.has(id) ? "point" : curves.find(curve => curve.id === id)?.kind)).filter(Boolean);
  if (kinds.length !== selection.length || !kinds.length) return [];
  const count = kind => kinds.filter(each => each === kind).length;
  const round = count("circle") + count("arc");
  const offer = [];
  const add_ = (relation, label = relation[0].toUpperCase() + relation.slice(1)) => offer.push({ relation, label });
  if (kinds.length === 1) {
    if (kinds[0] === "line") { add_("horizontal"); add_("vertical"); }
    if (kinds[0] === "point" && selection[0] !== "Origin") add_("fix");
    return offer;
  }
  if (kinds.length === 2) {
    if (count("point") === 2) { add_("horizontal"); add_("vertical"); add_("coincident"); }
    if (count("point") === 1 && count("line") === 1) { add_("coincident"); add_("midpoint"); }
    if (count("point") === 1 && round === 1) { add_("coincident"); add_("concentric"); }
    if (count("line") === 2) { add_("parallel"); add_("perpendicular"); add_("collinear"); add_("equal"); }
    if (count("line") === 1 && round === 1) add_("tangent");
    if (round === 2) { add_("tangent"); add_("concentric"); add_("equal"); }
    // A spline's end tangent to the line or arc that meets it there.
    if (count("spline") === 1 && (count("line") === 1 || count("arc") === 1)) {
      const spline = curves.find(curve => selection.includes(curve.id) && curve.kind === "spline");
      const other = curves.find(curve => selection.includes(curve.id) && curve.kind !== "spline");
      if ([spline.start, spline.end].some(id => id && (id === other.start || id === other.end))) add_("tangent");
    }
    return offer;
  }
  if (kinds.length === 3 && count("point") === 2 && count("line") === 1) add_("symmetric");
  return offer;
}

/** The relations and dimensions on what is selected, for the PropertyManager's Existing Relations. */
export function relationsOn(state, selection) {
  const wanted = new Set(selection);
  // A relation picked by its glyph is listed itself.
  return [...(state?.relations || []), ...(state?.dimensions || [])].filter(item => wanted.has(item.id) || item.refs.some(ref => wanted.has(ref)));
}

/** The relations drawn as glyphs on the sketch: the ones SolidWorks shows beside what they hold. */
export const GLYPH_KINDS = Object.freeze(["horizontal", "vertical", "parallel", "perpendicular", "collinear", "equal", "tangent", "concentric",
  "coincident", "midpoint", "symmetric", "fixed"]);

/**
 * Where each relation's glyph goes, as SolidWorks shows sketch relations: one beside each entity
 * the relation holds (a line at its middle, pushed off it square; a circle or an arc on its rim;
 * a point beside it), each with the way it is pushed off (`away`, a unit vector in the sketch's
 * plane). A symmetric relation's glyphs go by its two points, not by its centerline; Coincident's
 * and Midpoint's by the point they put on a curve.
 */
export function relationGlyphs(state) {
  const { points, curves } = sketchGeometry(state);
  const curve = id => curves.find(each => each.id === id);
  const unit = v => { const length = Math.hypot(v[0], v[1]) || 1; return [v[0] / length, v[1] / length]; };
  const anchor = ref => {
    if (points.has(ref)) return { at: at(points.get(ref)), away: unit([1, 1]), along: [1, 0] };
    const found = curve(ref);
    if (!found) return null;
    if (found.kind === "line") {
      const d = unit(sub(found.b, found.a));
      const n = d[1] > 0 || (d[1] === 0 && d[0] < 0) ? [d[1], -d[0]] : [-d[1], d[0]];
      return { at: [(found.a[0] + found.b[0]) / 2, (found.a[1] + found.b[1]) / 2], away: n, along: d };
    }
    if (found.kind === "spline") {
      const middle = found.samples[Math.floor(found.samples.length / 2)];
      return middle ? { at: middle, away: [0, 1], along: [1, 0] } : null;
    }
    // A circle on its rim up and to the right; an arc at the middle of its sweep.
    const angle = found.kind === "circle" ? Math.PI / 4 : (() => { const { start, sweep } = arcSweep(found); return start + sweep / 2; })();
    const away = [Math.cos(angle), Math.sin(angle)];
    return { at: [found.c[0] + found.r * away[0], found.c[1] + found.r * away[1]], away, along: [-away[1], away[0]] };
  };
  const glyphs = [];
  for (const relation of state?.relations || []) {
    if (!GLYPH_KINDS.includes(relation.kind)) continue;
    const refs = relation.kind === "symmetric" ? relation.refs.slice(0, 2)
      : relation.kind === "coincident" || relation.kind === "midpoint" ? relation.refs.filter(ref => points.has(ref)) : relation.refs;
    for (const ref of refs) {
      const placed = anchor(ref);
      if (placed) glyphs.push({ id: relation.id, kind: relation.kind, on: ref, refs: relation.refs, redundant: Boolean(relation.redundant), ...placed });
    }
  }
  return glyphs;
}

// A relation as SolidWorks lists it: "Horizontal1", "Coincident2"; a dimension by its value.
const RELATION_WORDS = Object.freeze({ horizontal_distance: "Horizontal distance", vertical_distance: "Vertical distance" });
export const relationLabel = item => RELATION_WORDS[item.kind] && item.value !== undefined ? `${item.id}, ${RELATION_WORDS[item.kind].toLowerCase()}` : item.id;

/** A sketch value as its dimension shows it: an angle in degrees, a size to the part's precision. */
export function formatValue(value, units, dimension) {
  if (!Number.isFinite(value)) return "";
  if (dimension === "angle") return `${Number(value.toFixed(1))}°`;
  const places = units === "in" ? 3 : 2;
  const text = Number(value.toFixed(places)).toString();
  if (dimension === "diameter") return `Ø${text}`;
  if (dimension === "radius" || dimension === "fillet") return `R${text}`;
  if (dimension === "circular_pattern") return `${Number(value.toFixed(1))}°`;
  return text;
}

/** The middle of a sketch's drawn curves, to place a dimension away from the shape. */
export function sketchCenter(state) {
  const { curves } = sketchGeometry(state);
  const places = curves.flatMap(curve => (curve.kind === "line" ? [curve.a, curve.b] : curve.kind === "spline" ? curve.samples : [curve.c]));
  if (!places.length) return [0, 0];
  return scale(places.reduce(add, [0, 0]), 1 / places.length);
}

/**
 * Where a dimension is drawn, in the sketch's units: its extension lines, its dimension line
 * (an arrow at each end, `single` for a radius's one), or the arc of an angle, and where its value
 * goes, set `gap` away from what it measures. It goes on the side away from the shape unless
 * `side` says (1 or -1: above or below a horizontal one, right or left of a vertical one, along a
 * line's left-hand normal or against it), and `level` steps it further out, so dimensions stacked
 * on one side do not cover each other. `at`: where it was dragged to, as SolidWorks lets a placed
 * dimension be moved: its value there, a linear one's dimension line moved out to it.
 */
export function dimensionLayout(state, dimension, gap, { side = 0, level = 0, at: to = null } = {}) {
  const laid = layoutOf(state, dimension, gap, { side, level, to });
  return laid && to && !laid.placed ? { ...laid, anchor: to } : laid;
}

function layoutOf(state, dimension, gap, { side, level, to }) {
  const { points, curves } = sketchGeometry(state);
  const curve = id => curves.find(each => each.id === id);
  const place = id => (points.has(id) ? at(points.get(id)) : curve(id)?.c);
  const middle = sketchCenter(state);
  const out = gap * (1 + level * 1.15);
  const aligned = (p, q) => {
    const d = unit(sub(q, p));
    const left = [-d[1], d[0]];
    // Dragged: on the side it went, its dimension line out where its value is, its value along it there.
    const across = to ? dot(sub(to, p), left) : 0;
    const n = to ? scale(left, across < 0 ? -1 : 1)
      : side ? scale(left, side) : dot(sub(scale(add(p, q), 0.5), middle), left) < 0 ? scale(left, -1) : left;
    const far = to ? Math.max(gap * 0.3, Math.abs(across) - gap * 0.45) : out;
    const p1 = add(p, scale(n, far));
    const q1 = add(q, scale(n, far));
    const along = to ? scale(d, dot(sub(to, scale(add(p, q), 0.5)), d)) : [0, 0];
    return { lines: [[p, add(p1, scale(n, gap * 0.25))], [q, add(q1, scale(n, gap * 0.25))]], dimension: [p1, q1],
      anchor: add(add(scale(add(p1, q1), 0.5), scale(n, gap * 0.45)), along), placed: Boolean(to) };
  };
  const [a, b] = dimension.refs;
  switch (dimension.kind) {
    case "length": { const line = curve(a); return line ? aligned(line.a, line.b) : null; }
    // A linear pattern's spacing, from an entity's point to the same point of the first copy; a
    // circular pattern's angle, from the center out to the first copy.
    case "linear_pattern":
    case "circular_pattern": {
      const first = (dimension.data?.pairs || []).find(pair => pair[2] === 1);
      const from = first && points.has(first[0]) ? at(points.get(first[0])) : null;
      const to = first && points.has(first[1]) ? at(points.get(first[1])) : null;
      if (!from || !to) return null;
      if (dimension.kind === "linear_pattern") return aligned(from, to);
      const pivot = points.has(dimension.data?.center) ? at(points.get(dimension.data.center)) : [0, 0];
      const toward = unit(sub(to, pivot));
      return { lines: [], dimension: [pivot, to], single: true, anchor: add(to, scale(toward, gap * (1 + level))) };
    }
    // A chamfer's distance, as SolidWorks shows it: along its first line, from the corner it cuts to where it meets it.
    case "chamfer": {
      const cut = curves.find(each => each.id === dimension.data?.line);
      const corner = dimension.data?.corner && points.has(dimension.data.corner) ? at(points.get(dimension.data.corner)) : null;
      return cut && corner ? aligned(corner, cut.a) : null;
    }
    case "horizontal_distance":
    case "vertical_distance": {
      const p = place(a);
      const q = place(b);
      if (!p || !q) return null;
      const axis = dimension.kind === "horizontal_distance" ? 1 : 0;
      const outward = to ? (to[axis] >= (p[axis] + q[axis]) / 2 ? 1 : -1) : side || ((p[axis] + q[axis]) / 2 >= middle[axis] ? 1 : -1);
      const level_ = to ? to[axis] - outward * gap * 0.45
        : (outward > 0 ? Math.max(p[axis], q[axis]) : Math.min(p[axis], q[axis])) + outward * out;
      const put = (point, value) => (axis === 1 ? [point[0], value] : [value, point[1]]);
      const p1 = put(p, level_);
      const q1 = put(q, level_);
      const middle_ = scale(add(p1, q1), 0.5);
      return { lines: [[p, put(p, level_ + outward * gap * 0.25)], [q, put(q, level_ + outward * gap * 0.25)]], dimension: [p1, q1],
        anchor: put(to ? (axis === 1 ? [to[0], 0] : [0, to[1]]) : middle_, level_ + outward * gap * 0.45), placed: Boolean(to) };
    }
    case "distance": {
      const lineB = curve(b)?.kind === "line" ? curve(b) : null;
      const lineA = curve(a)?.kind === "line" ? curve(a) : null;
      const across = (from, line) => {
        const foot = nearestOnInfinite(line, from);
        const along = unit(sub(line.b, line.a));
        return { lines: [], dimension: [from, foot], anchor: add(scale(add(from, foot), 0.5), scale(along, gap * (0.6 + level * 1.15))) };
      };
      if (lineA && lineB) return across(scale(add(lineA.a, lineA.b), 0.5), lineB);
      if (lineB) return across(place(a), lineB);
      const p = place(a);
      const q = place(b);
      return p && q ? aligned(p, q) : null;
    }
    case "offset": {
      // Across from the first offset curve to the one it is offset from.
      const made = curve(dimension.refs[0]);
      const source = curve(dimension.refs[dimension.data?.count || 1]);
      if (!made || !source) return null;
      if (made.kind === "line" && source.kind === "line") {
        const from = scale(add(made.a, made.b), 0.5);
        const foot = nearestOnInfinite(source, from);
        return { lines: [], dimension: [foot, from], anchor: add(scale(add(from, foot), 0.5), scale(unit(sub(made.b, made.a)), gap * (0.6 + level * 1.15))) };
      }
      const toward = unit(made.kind === "arc" ? sub(scale(add(made.s, made.e), 0.5), made.c) : [Math.SQRT1_2, -Math.SQRT1_2]);
      const near = add(source.c, scale(toward, source.r));
      const far = add(made.c, scale(toward, made.r));
      return { lines: [], dimension: [near, far], anchor: add(far, scale(toward, gap * (0.8 + level))) };
    }
    case "fillet":
    case "radius":
    case "diameter": {
      const round = dimension.kind === "fillet" ? curves.find(each => each.id === dimension.data?.arc) : curve(a);
      if (!round) return null;
      const toward = unit(round.kind === "arc" ? sub(scale(add(round.s, round.e), 0.5), round.c) : [Math.SQRT1_2, Math.SQRT1_2]);
      const rim = add(round.c, scale(toward, round.r));
      const far = dimension.kind === "diameter" ? add(round.c, scale(toward, -round.r)) : round.c;
      return { lines: [], dimension: [far, rim], single: dimension.kind !== "diameter", anchor: add(rim, scale(toward, gap * (1 + level))) };
    }
    case "angle": {
      const lineA = curve(a);
      const lineB = curve(b);
      if (!lineA || !lineB) return null;
      const u = sub(lineA.b, lineA.a);
      const v = sub(lineB.b, lineB.a);
      const denominator = cross(u, v);
      if (Math.abs(denominator) < 1e-12) return null;
      const t = cross(sub(lineB.a, lineA.a), v) / denominator;
      const corner = add(lineA.a, scale(u, t));
      // Each ray from the corner toward the far end of its line.
      const ray = line => unit(sub(hypot(line.a, corner) > hypot(line.b, corner) ? line.a : line.b, corner));
      const r1 = ray(lineA);
      const r2 = ray(lineB);
      const radius = gap * (2.2 + level * 1.15);
      const from = Math.atan2(r1[1], r1[0]);
      let sweep = Math.atan2(r2[1], r2[0]) - from;
      while (sweep > Math.PI) sweep -= 2 * Math.PI;
      while (sweep < -Math.PI) sweep += 2 * Math.PI;
      const half = from + sweep / 2;
      return { lines: [], arc: { center: corner, radius, from, sweep }, anchor: add(corner, [Math.cos(half) * (radius + gap * 0.6), Math.sin(half) * (radius + gap * 0.6)]) };
    }
    default:
      return null;
  }
}

/** Which side of what it measures a dimension placed at `place` goes on (see `dimensionLayout`). */
export function placedSide(state, dimension, place) {
  const { points, curves } = sketchGeometry(state);
  const curve = id => curves.find(each => each.id === id);
  const where = id => (points.has(id) ? at(points.get(id)) : curve(id)?.c);
  const [a, b] = dimension.refs;
  if (dimension.kind === "horizontal_distance" || dimension.kind === "vertical_distance") {
    const axis = dimension.kind === "horizontal_distance" ? 1 : 0;
    const p = where(a);
    const q = where(b);
    if (!p || !q) return 0;
    return place[axis] >= (p[axis] + q[axis]) / 2 ? 1 : -1;
  }
  const ends = dimension.kind === "length" ? [curve(a)?.a, curve(a)?.b] : dimension.kind === "distance" && !curve(b) ? [where(a), where(b)] : null;
  if (!ends || !ends[0] || !ends[1]) return 0;
  const d = unit(sub(ends[1], ends[0]));
  return dot(sub(place, ends[0]), [-d[1], d[0]]) >= 0 ? 1 : -1;
}

function nearestOnInfinite(line, place) {
  const d = sub(line.b, line.a);
  const length = dot(d, d) || 1;
  return add(line.a, scale(d, dot(sub(place, line.a), d) / length));
}

/** What is under the pointer, for picking and hovering: a point first, then a dimension's value, then a curve. */
export function hitTest(state, place, tolerance) {
  const { points, curves } = sketchGeometry(state);
  let best = null;
  for (const point of points.values()) {
    const distance = hypot(at(point), place);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { id: point.id, distance };
  }
  if (best) return best.id;
  for (const curve of curves) {
    const { distance } = nearestOnCurve(curve, place);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { id: curve.id, distance };
  }
  return best?.id || null;
}

// ---- Trim Entities and Offset Entities: what a click takes --------------------------------------

/** Where along a curve a place is: a line from 0 to 1, an arc or a circle in radians from its start, the way it turns. */
function alongCurve(curve, place) {
  if (curve.kind === "line") {
    const d = sub(curve.b, curve.a);
    return dot(sub(place, curve.a), d) / (dot(d, d) || 1);
  }
  const angle = Math.atan2(place[1] - curve.c[1], place[0] - curve.c[0]);
  if (curve.kind === "circle") return ((angle % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const { start, sweep } = arcSweep(curve);
  const turn = sweep < 0 ? -1 : 1;
  return ((((angle - start) * turn) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
}

// A curve as points along it, to draw it whole.
function wholeCurve(curve) {
  if (curve.kind === "line") return curve.view || [curve.a, curve.b];
  const { start, sweep } = curve.kind === "circle" ? { start: 0, sweep: 2 * Math.PI } : arcSweep(curve);
  const steps = Math.max(12, Math.ceil(Math.abs(sweep) * 24));
  return Array.from({ length: steps + 1 }, (_, index) => {
    const angle = start + (sweep * index) / steps;
    return [curve.c[0] + curve.r * Math.cos(angle), curve.c[1] + curve.r * Math.sin(angle)];
  });
}

function spanOf(curve) {
  return curve.kind === "line" ? 1 : curve.kind === "circle" ? 2 * Math.PI : Math.abs(arcSweep(curve).sweep);
}

function lineCircle(p, q, c, r) {
  const d = sub(q, p);
  const f = sub(p, c);
  const a = dot(d, d);
  const b = 2 * dot(f, d);
  const disc = b * b - 4 * a * (dot(f, f) - r * r);
  if (a < 1e-24 || disc < 0) return [];
  const root = Math.sqrt(disc);
  return [(-b - root) / (2 * a), (-b + root) / (2 * a)].map(t => add(p, scale(d, t)));
}

function circleCircle(c1, r1, c2, r2) {
  const d = hypot(c1, c2);
  if (d < 1e-12 || d > r1 + r2 || d < Math.abs(r1 - r2)) return [];
  const a = (r1 * r1 - r2 * r2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, r1 * r1 - a * a));
  const m = add(c1, scale(sub(c2, c1), a / d));
  const n = [-(c2[1] - c1[1]) / d, (c2[0] - c1[0]) / d];
  return [add(m, scale(n, h)), add(m, scale(n, -h))];
}

/** Where two curves meet, each as drawn (a line between its ends, an arc along its sweep). */
function meetings(first, second, tolerance) {
  const on = (curve, place) => {
    const t = alongCurve(curve, place);
    if (curve.kind === "line") return t >= -tolerance / (hypot(curve.a, curve.b) || 1) && t <= 1 + tolerance / (hypot(curve.a, curve.b) || 1);
    if (curve.kind === "circle") return true;
    return t <= spanOf(curve) + tolerance / (curve.r || 1) || t >= 2 * Math.PI - tolerance / (curve.r || 1);
  };
  let found;
  if (first.kind === "line" && second.kind === "line") {
    const d = sub(first.b, first.a);
    const e = sub(second.b, second.a);
    const across = cross(d, e);
    found = Math.abs(across) < 1e-12 ? [] : [add(first.a, scale(d, cross(sub(second.a, first.a), e) / across))];
  } else if (first.kind === "line" || second.kind === "line") {
    const [line, round] = first.kind === "line" ? [first, second] : [second, first];
    found = lineCircle(line.a, line.b, round.c, round.r);
  } else {
    found = circleCircle(first.c, first.r, second.c, second.r);
  }
  return found.filter(place => on(first, place) && on(second, place));
}

/**
 * The piece of a curve Trim Entities cuts away when it is clicked at `place`, as points along it
 * to draw: up to the nearest curves that cross it either side (or its ends); the whole curve
 * when nothing crosses it (it is deleted). Null for what cannot be trimmed (a fillet's arc).
 */
export function trimPiece(state, id, place, tolerance = nearness(state) * 10) {
  const { curves } = sketchGeometry(state);
  const curve = curves.find(each => each.id === id);
  if (!curve || curve.derived || curve.kind === "spline") return null;
  const span = spanOf(curve);
  const slack = curve.kind === "line" ? tolerance / (hypot(curve.a, curve.b) || 1) : tolerance / (curve.r || 1);
  const cuts = [];
  for (const other of curves) {
    if (other.id === id || other.derived) continue;
    for (const where of meetings(curve, other, tolerance)) {
      let t = alongCurve(curve, where);
      if (curve.kind === "arc" && t > 2 * Math.PI - slack) t -= 2 * Math.PI;
      if (curve.kind !== "circle" && (t <= slack || t >= span - slack)) continue;
      if (!cuts.some(each => Math.abs(each - t) <= slack)) cuts.push(t);
    }
  }
  cuts.sort((p, q) => p - q);
  const whole = { id, points: wholeCurve(curve), whole: true };
  let clicked = Math.max(0, Math.min(span, alongCurve(curve, place)));
  if (curve.kind === "arc" && alongCurve(curve, place) > span) clicked = alongCurve(curve, place) - span < 2 * Math.PI - alongCurve(curve, place) ? span : 0;
  let low;
  let high;
  if (curve.kind === "circle") {
    if (cuts.length < 2) return whole;
    const k = cuts.findIndex((each, index) => index < cuts.length - 1 && each <= clicked && clicked < cuts[index + 1]);
    [low, high] = k >= 0 ? [cuts[k], cuts[k + 1]] : [cuts[cuts.length - 1], cuts[0] + 2 * Math.PI];
  } else {
    if (!cuts.length) return whole;
    low = Math.max(0, ...cuts.filter(each => each < clicked));
    high = Math.min(span, ...cuts.filter(each => each > clicked));
  }
  if (curve.kind === "line") {
    const d = sub(curve.b, curve.a);
    return { id, points: [add(curve.a, scale(d, low)), add(curve.a, scale(d, high))], whole: false };
  }
  const start = curve.kind === "circle" ? 0 : arcSweep(curve).start;
  const turn = curve.kind === "arc" && arcSweep(curve).sweep < 0 ? -1 : 1;
  const from = start + turn * low;
  const sweep = turn * (high - low);
  const steps = Math.max(8, Math.ceil(Math.abs(sweep) * 24));
  return { id, whole: false, points: Array.from({ length: steps + 1 }, (_, index) => {
    const angle = from + (sweep * index) / steps;
    return [curve.c[0] + curve.r * Math.cos(angle), curve.c[1] + curve.r * Math.sin(angle)];
  }) };
}

/**
 * What Extend Entities would add to the line `id` clicked at `place`: from its end nearer the click
 * on to the first curve it meets past it (`points`, to draw). Null where nothing lies ahead, where
 * another curve shares that end, or for what is not a line.
 */
export function extendPiece(state, id, place, tolerance = nearness(state) * 10) {
  const { curves } = sketchGeometry(state);
  const line = curves.find(each => each.id === id);
  if (line?.kind === "arc" && !line.derived) return arcRunOn(curves, line, place, tolerance);
  if (!line || line.kind !== "line" || line.derived) return null;
  const [from, end, role] = hypot(place, line.b) <= hypot(place, line.a) ? [line.a, line.b, "end"] : [line.b, line.a, "start"];
  if (curves.some(each => each.id !== id && [each.start, each.end, each.center].includes(line[role]))) return null;
  const way = sub(end, from);
  const reach = dot(way, way) || 1;
  // The line run on a long way, to find what it meets ahead.
  const ray = { kind: "line", a: from, b: add(from, scale(way, 1e4)) };
  let nearest = null;
  for (const other of curves) {
    if (other.id === id || other.derived) continue;
    for (const hit of meetings(ray, other, tolerance)) {
      const t = dot(sub(hit, from), way) / reach;
      if (t > 1 + 1e-9 && (nearest === null || t < nearest.t)) nearest = { t, hit };
    }
  }
  return nearest ? { id, points: [end, nearest.hit] } : null;
}

/**
 * An arc's end nearer `place` run on round its circle the way it turns (back from its start) to the
 * first curve it meets, never as far as the arc itself: the piece it adds, as places along it.
 */
function arcRunOn(curves, arc, place, tolerance) {
  const role = hypot(place, arc.e) <= hypot(place, arc.s) ? "end" : "start";
  if (curves.some(each => each.id !== arc.id && [each.start, each.end, each.center].includes(arc[role]))) return null;
  const { start, sweep } = arcSweep(arc);
  const way = (sweep >= 0 ? 1 : -1) * (role === "end" ? 1 : -1);
  const from = role === "end" ? start + sweep : start;
  const gap = 2 * Math.PI - Math.abs(sweep);
  const circle = { kind: "circle", c: arc.c, r: arc.r };
  let nearest = null;
  for (const other of curves) {
    if (other.id === arc.id || other.derived || other.kind === "spline") continue;
    for (const hit of meetings(circle, other, tolerance)) {
      let run = ((Math.atan2(hit[1] - arc.c[1], hit[0] - arc.c[0]) - from) * way) % (2 * Math.PI);
      if (run < 0) run += 2 * Math.PI;
      if (run > 1e-9 && run < gap - 1e-9 && (nearest === null || run < nearest)) nearest = run;
    }
  }
  if (nearest === null) return null;
  const steps = Math.max(2, Math.ceil(nearest / (Math.PI / 32)));
  return { id: arc.id, points: Array.from({ length: steps + 1 }, (_, k) => {
    const angle = from + (way * nearest * k) / steps;
    return [arc.c[0] + arc.r * Math.cos(angle), arc.c[1] + arc.r * Math.sin(angle)];
  }) };
}

// A count typed in a panel: a whole number from 2 to 100, else the tool's own.
const instances = (typed, fallback) => {
  const count = Number(String(typed ?? "").trim());
  return Number.isInteger(count) && count >= 2 && count <= 100 ? count : fallback;
};

/**
 * What a sketch pattern takes and makes, as its panel sets it out: the entities selected (a
 * circular one's center the point selected last, else the sketch's origin), how many instances,
 * and a linear one's spacing and angle, a circular one's total angle, as typed.
 */
export function patternSettings(tool, settings = {}, selection = [], state = null, units = "mm") {
  const circular = tool === "circular_pattern";
  const { points } = sketchGeometry(state);
  const center = circular ? [...selection].reverse().find(id => points.has(id) && id !== "Origin") || null : null;
  const items = selection.filter(id => id !== center);
  if (circular) {
    return { type: "circular", items, count: instances(settings.circularCount, 6), angle: String(settings.circularAngle ?? "").trim() || "360", center };
  }
  return { type: "linear", items, count: instances(settings.linearCount, 3), spacing: toolSize(settings.linearSpacing, units, "pattern"),
    angle: String(settings.linearAngle ?? "").trim() || "0" };
}

/** A sketch pattern's change (`patternSettings`), as `cadgen/edit` takes it. */
export function patternOp(pattern) {
  const { center, ...rest } = pattern;
  return { kind: "pattern", ...rest, count: String(pattern.count), ...(center ? { center } : {}) };
}

/**
 * Where a sketch pattern's copies would go, drawn before it is made: each instance past the first,
 * each entity moved down the row (or turned about the center) as the pattern would place it. Empty
 * while a size is written as a name the view cannot work out.
 */
export function patternCopies(state, pattern) {
  const { points, curves } = sketchGeometry(state);
  const angle = Number(pattern.angle);
  const spacing = Number(pattern.spacing);
  if (!Number.isFinite(angle) || (pattern.type === "linear" && !Number.isFinite(spacing))) return [];
  const pivot = pattern.center && points.has(pattern.center) ? at(points.get(pattern.center)) : [0, 0];
  const full = Math.abs(Math.abs(angle) - 360) < 1e-9;
  const step = (angle * Math.PI) / 180 / (full ? pattern.count : pattern.count - 1);
  const way = [Math.cos((angle * Math.PI) / 180), Math.sin((angle * Math.PI) / 180)];
  const moved = (k, p) => {
    if (pattern.type === "linear") return add(p, scale(way, k * spacing));
    const [c, s] = [Math.cos(k * step), Math.sin(k * step)];
    const r = sub(p, pivot);
    return add(pivot, [c * r[0] - s * r[1], s * r[0] + c * r[1]]);
  };
  const out = [];
  for (let k = 1; k < pattern.count; k += 1) {
    for (const id of pattern.items) {
      if (points.has(id)) { out.push({ kind: "point", at: moved(k, at(points.get(id))) }); continue; }
      const curve = curves.find(each => each.id === id);
      if (!curve || curve.derived || curve.kind === "spline") continue;
      if (curve.kind === "line") out.push({ kind: "line", a: moved(k, curve.a), b: moved(k, curve.b) });
      else if (curve.kind === "circle") out.push({ kind: "circle", c: moved(k, curve.c), r: curve.r });
      else out.push({ kind: "arc", c: moved(k, curve.c), s: moved(k, curve.s), e: moved(k, curve.e), r: curve.r, clockwise: curve.clockwise });
    }
  }
  return out;
}

/** The curves joined end to end with `id` (lines and arcs meeting at a point or one place), as Offset Entities' Select chain takes them. */
export function chainOf(state, id, tolerance = nearness(state) * 10) {
  const { curves } = sketchGeometry(state);
  const start = curves.find(each => each.id === id);
  if (!start || start.derived) return [];
  if (start.kind === "circle" || start.kind === "spline") return [id];
  const ends = curve => (curve.kind === "line" ? [curve.a, curve.b] : curve.kind === "arc" ? [curve.s, curve.e] : []);
  const joined = (p, q) => curves.filter(each => !each.derived && each.kind !== "circle" && each.id !== p.id
    && ends(each).some(end => ends(p).some(other => hypot(end, other) <= tolerance)) && q(each));
  const chain = [id];
  for (let index = 0; index < chain.length; index += 1) {
    const curve = curves.find(each => each.id === chain[index]);
    for (const next of joined(curve, each => !chain.includes(each.id))) chain.push(next.id);
  }
  return chain;
}

/** An entity as a CAD tool says it in a sentence: "a line", "Line3". */
export const entityWord = (state, id) => {
  const curve = (state?.curves || []).find(each => each.id === id);
  return curve ? KIND_NAMES[curve.kind] || "curve" : "point";
};

function counted(count, one, many = `${one}s`) {
  if (count !== 1) return `${count} ${many}`;
  return `${/^[aeiou]/.test(one) ? "an" : "a"} ${one}`;
}

function listed(parts) {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

/**
 * What the agent is told when the engineer leaves a sketch they changed: the sketch, where it is
 * written, and what they did, counted ("drew 4 lines and a circle, added 3 dimensions").
 * `made` counts the session's changes by kind: lines, circles, arcs, points, dimensions,
 * relations, corners rounded, curves trimmed, chains offset, entities mirrored, the model's edges
 * and faces converted, deleted, moved.
 */
export function sketchNote(session) {
  const made = session.made || {};
  const drew = [["line", "lines"], ["circle", "circles"], ["arc", "arcs"], ["spline", "splines"], ["point", "points"]]
    .filter(([one]) => made[one]).map(([one, many]) => counted(made[one], one, many));
  const added = [["dimension", "dimensions"], ["relation", "relations"]].filter(([one]) => made[one]).map(([one, many]) => counted(made[one], one, many));
  const parts = [];
  if (drew.length) parts.push(`drew ${listed(drew)}`);
  if (added.length) parts.push(`added ${listed(added)}`);
  if (made.value) parts.push(`changed ${counted(made.value, "dimension")}`);
  if (made.fillet) parts.push(`rounded ${counted(made.fillet, "corner")}`);
  if (made.chamfer) parts.push(`cut ${counted(made.chamfer, "corner")}`);
  if (made.trimmed) parts.push(`trimmed ${counted(made.trimmed, "curve")}`);
  if (made.extended) parts.push(`extended ${counted(made.extended, "line")}`);
  if (made.pattern) parts.push(`made ${counted(made.pattern, "sketch pattern")}`);
  if (made.offset) parts.push(`offset ${counted(made.offset, "chain")}`);
  if (made.mirrored) parts.push(`mirrored ${counted(made.mirrored, "entity", "entities")}`);
  const converted = [["convertedEdge", "edge", "edges"], ["convertedFace", "face", "faces"]].filter(([key]) => made[key])
    .map(([key, one, many]) => counted(made[key], one, many));
  if (converted.length) parts.push(`converted ${listed(converted)} of the model`);
  if (made.intersection) parts.push("brought in where the part crosses its plane");
  if (made.moved) parts.push(`moved ${counted(made.moved, "point")}`);
  if (made.deleted) parts.push(`deleted ${counted(made.deleted, "item")}`);
  const where = `(${session.file}, line ${session.line})`;
  const plane = session.plane && session.plane !== "Plane" ? ` on the ${session.plane} Plane` : "";
  const done = parts.length ? `: ${parts.join(", ")}` : "";
  if (session.created) return `In edit mode I drew ${session.name}${plane} ${where}${done}.`;
  return `In edit mode I changed ${session.name} ${where}${done}.`;
}

/** What a sketch change counts as for the note: a stroke by what it draws, and the rest by kind. */
export function countChange(made, op) {
  const next = { ...made };
  const bump = (key, by = 1) => { next[key] = (next[key] || 0) + by; };
  if (op.kind === "draw") {
    if (op.entity === "rectangle" || op.entity === "center_rectangle" || op.entity === "three_point_rectangle") bump("line", 4);
    else if (op.entity === "slot") { bump("arc", 2); bump("line", 2); }
    else if (op.entity === "polygon") bump("line", op.sides || 6);
    else if (op.entity === "three_point_arc") bump("arc");
    else if (op.entity === "centerline") bump("line");
    else bump(op.entity);
  } else if (op.kind === "dimension" || op.kind === "driven") bump("dimension");
  else if (op.kind === "relate") bump("relation");
  else if (op.kind === "value") bump("value");
  else if (op.kind === "move") bump("moved", (op.points || []).length || 1);
  else if (op.kind === "delete") bump("deleted", (op.items || []).length || 1);
  else if (op.kind === "fillet") bump("fillet");
  else if (op.kind === "chamfer") bump("chamfer");
  else if (op.kind === "trim") bump("trimmed");
  else if (op.kind === "extend") bump("extended");
  else if (op.kind === "pattern") bump("pattern");
  else if (op.kind === "offset") bump("offset");
  else if (op.kind === "mirror") bump("mirrored", (op.items || []).length || 1);
  else if (op.kind === "intersection") bump("intersection");
  else if (op.kind === "convert") {
    const faces = (op.items || []).filter(item => isFaceItem(item)).length;
    if (faces) bump("convertedFace", faces);
    if ((op.items || []).length > faces) bump("convertedEdge", op.items.length - faces);
  }
  return next;
}
