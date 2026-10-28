/**
 * Drawing a sketch over the viewport: its plane placed in the view (a place on the sketch to the
 * screen and back, through the model's own transform), its curves as screen paths, arrowheads,
 * and the colors a CAD tool gives a sketch, read from the viewer's own text color so a dark
 * viewer draws a defined sketch light.
 */
import { arcSweep, sketchGeometry } from "./sketchMode.js";

/**
 * Whether a viewer's text color is light, so the viewer is dark. The theme writes it as oklch (its
 * lightness first, 0 to 1 or a percentage); a browser may hand it back as rgb.
 */
export function lightText(text) {
  const oklch = /^oklch\(\s*([\d.]+)(%?)/i.exec(text);
  const [r, g, b] = (text.match(/[\d.]+/g) || ["20", "20", "20"]).map(Number);
  const lightness = oklch ? Number(oklch[1]) / (oklch[2] ? 100 : 1) : (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lightness > 0.55;
}

/** The sketch's colors, as SolidWorks gives them: blue while it can move, black (the text color here) once defined. */
export function colorsFor(host) {
  const style = getComputedStyle(host);
  const text = style.color || "rgb(20, 20, 20)";
  const dark = lightText(text);
  return {
    defined: text, under: dark ? "#60a5fa" : "#1d4ed8", over: "#ef4444", selected: "#06b6d4", hover: "#f97316",
    origin: "#dc2626", preview: dark ? "#93c5fd" : "#2563eb", relation: dark ? "#4ade80" : "#15803d", label: dark ? "rgba(24, 24, 27, 0.9)" : "rgba(255, 255, 255, 0.92)",
    quiet: dark ? "rgba(226, 232, 240, 0.75)" : "rgba(30, 41, 59, 0.75)", font: style.fontFamily || "system-ui, sans-serif",
  };
}

/**
 * The CAD colors drawn over the model, from the viewer's tokens, with stand-ins for a host without
 * them: the selection's blue, a preview's amber (its edge darker) for material added and red for a
 * cut, and a tag's text over the blue.
 */
export function cadColors(host) {
  const style = getComputedStyle(host);
  const read = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
  return {
    picked: read("--cad-picked", "#4f9dff"), solid: read("--cad-solid", "#f2b33d"), solidEdge: read("--cad-solid-edge", "#8a5a12"),
    cut: read("--cad-cut", "#e5484d"),
    tagText: lightText(style.color || "") ? "#0b1220" : "#ffffff",
  };
}

/** How strongly a preview's faces are shaded over the model: a sketch's sweep, a feature's change. */
export const PREVIEW_FILL_ALPHA = 0.3;

// What a layout over the model depends on: the view's size, the camera and the model's own transform.
const viewKey = (width, height, camera, modelGroup) => [width, height, camera.matrixWorld.elements.join(),
  camera.projectionMatrix.elements.join(), modelGroup.matrixWorld.elements.join()].join("|");

/**
 * The part in the view: `toScreen(x, y, z)` a place in the part's own millimetres to the
 * viewport's pixels, or null behind the camera; `toView(x, y, z)` the place as the camera sees it
 * (it looks down its -z); `key` what that depends on, to paint again only when it changed. Null
 * before the viewer is up.
 */
export function modelMapping(runtime, width, height) {
  if (!runtime?.camera || !runtime.modelGroup || !runtime.THREE) return null;
  const { THREE, camera, modelGroup } = runtime;
  camera.updateMatrixWorld();
  modelGroup.updateMatrixWorld();
  const scratch = new THREE.Vector3();
  const seen = new THREE.Vector3();
  const toScreen = (x, y, z) => {
    scratch.set(x, y, z).applyMatrix4(modelGroup.matrixWorld);
    if (seen.copy(scratch).applyMatrix4(camera.matrixWorldInverse).z >= 0) return null;
    scratch.project(camera);
    return [((scratch.x + 1) * width) / 2, ((1 - scratch.y) * height) / 2];
  };
  const toView = (x, y, z) => seen.set(x, y, z).applyMatrix4(modelGroup.matrixWorld).applyMatrix4(camera.matrixWorldInverse).toArray();
  return { toScreen, toView, key: viewKey(width, height, camera, modelGroup) };
}

/**
 * The pointer's ray in the part, from the view's pixel (`x`, `y`): where it starts and the way it
 * goes, in the part's millimetres. Null before the viewer is up.
 */
export function modelRay(runtime, width, height, x, y) {
  if (!runtime?.camera || !runtime.modelGroup || !runtime.THREE) return null;
  const { THREE, camera, modelGroup } = runtime;
  camera.updateMatrixWorld();
  modelGroup.updateMatrixWorld();
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(new THREE.Vector2((x / width) * 2 - 1, 1 - (y / height) * 2), camera);
  const ray = raycaster.ray.clone().applyMatrix4(modelGroup.matrixWorld.clone().invert());
  return { origin: ray.origin.toArray(), direction: ray.direction.toArray() };
}

/**
 * How far along a line in the part (`point` plus `along` times it) the place nearest a ray lies,
 * as a drag along a handle's line reads the pointer. Null when the ray runs along the line, so no
 * one place is nearest.
 */
export function lineNearestRay(point, along, origin, direction) {
  const dot = (p, q) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
  const toLine = point.map((value, axis) => value - origin[axis]);
  const a = dot(along, along);
  const b = dot(along, direction);
  const c = dot(direction, direction);
  const d = dot(along, toLine);
  const e = dot(direction, toLine);
  const denominator = a * c - b * b;
  if (!(Math.abs(denominator) > 1e-9 * a * c)) return null;
  return (b * e - c * d) / denominator;
}

/** A place on a sketch (in its units), `offset` millimetres off its plane along its normal: the place in the part's millimetres. */
export function framePoint(frame, unit, [u, v], offset = 0) {
  return [0, 1, 2].map(axis => frame.origin[axis] + (u * frame.x[axis] + v * frame.y[axis]) * unit + frame.z[axis] * offset);
}

/**
 * The middle of what a sketch's outlines bound, for an arrow to start from: their areas' centre, a
 * hole's (`holes`, by outline) taken away; the middle of their points when they bound no area.
 * In the sketch's units; null for no outline.
 */
export function loopsCentroid(loops, holes = []) {
  let area = 0;
  let x = 0;
  let y = 0;
  loops.forEach((loop, index) => {
    let twice = 0;
    let sx = 0;
    let sy = 0;
    loop.forEach(([x0, y0], at) => {
      const [x1, y1] = loop[(at + 1) % loop.length];
      const cross = x0 * y1 - x1 * y0;
      twice += cross;
      sx += (x0 + x1) * cross;
      sy += (y0 + y1) * cross;
    });
    if (Math.abs(twice) < 1e-12) return;
    const weight = (Math.abs(twice) / 2) * (holes[index] ? -1 : 1);
    x += (sx / (3 * twice)) * weight;
    y += (sy / (3 * twice)) * weight;
    area += weight;
  });
  if (Math.abs(area) > 1e-12) return [x / area, y / area];
  const points = loops.flat();
  if (!points.length) return null;
  return [points.reduce((sum, point) => sum + point[0], 0) / points.length, points.reduce((sum, point) => sum + point[1], 0) / points.length];
}

// An arrow's length and its head's, in the view's pixels: the same at any zoom, as a CAD tool's handles are.
const ARROW_PX = 34;
const ARROW_HEAD_PX = 9;
// Nearer the line of sight than this (its sine), a direction is drawn as pointing at the viewer or away.
const END_ON = 0.26;

/**
 * A direction in the part (`along`, a unit vector) at a place of it (`at`, millimetres) as the view
 * draws its arrow: the place's pixel (`from`), the way the arrow goes on the screen (`toward`), and
 * `facing` 1 or -1 when it points so nearly at the viewer or away that it has no way on the screen.
 * `reach` is how far along it to look, in millimetres. Null with the place behind the camera.
 */
export function screenDirection(mapping, at, along, reach = 1) {
  const from = mapping.toScreen(...at);
  if (!from) return null;
  const end = at.map((value, axis) => value + along[axis] * reach);
  const near = mapping.toView(...at);
  const far = mapping.toView(...end);
  const seen = [far[0] - near[0], far[1] - near[1], far[2] - near[2]];
  const length = Math.hypot(...seen) || 1;
  // The camera looks down its -z: a direction with +z comes at the viewer.
  if (Math.hypot(seen[0], seen[1]) / length < END_ON) return { from, toward: [0, 0], facing: seen[2] > 0 ? 1 : -1 };
  const to = mapping.toScreen(...end);
  return { from, toward: to ? [to[0] - from[0], to[1] - from[1]] : [seen[0], -seen[1]], facing: 0 };
}

/**
 * A direction arrow over the model, as a CAD tool draws one on what it previews: from its place
 * along its way on the screen (`screenDirection`), its head filled. One pointing straight at the
 * viewer is drawn as an engineer marks it, a dot in a ring; one pointing away, a cross in a ring.
 * Returns where its label goes (`drawLabel`): past its tip, or beside the ring; and where it was
 * drawn (`from`, `tip`, `facing`), for a press on it to take it as a handle (`handleAt`).
 */
export function drawArrow(context, direction, color, length = ARROW_PX) {
  const { from, toward, facing } = direction;
  context.save();
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = 2;
  context.lineCap = "round";
  if (facing) {
    const radius = 7;
    context.beginPath();
    context.arc(from[0], from[1], radius, 0, Math.PI * 2);
    context.stroke();
    context.beginPath();
    if (facing > 0) {
      context.arc(from[0], from[1], 2.5, 0, Math.PI * 2);
      context.fill();
    } else {
      const arm = radius * 0.6;
      context.moveTo(from[0] - arm, from[1] - arm);
      context.lineTo(from[0] + arm, from[1] + arm);
      context.moveTo(from[0] + arm, from[1] - arm);
      context.lineTo(from[0] - arm, from[1] + arm);
      context.stroke();
    }
    context.restore();
    return { x: from[0] + radius + 6, y: from[1], leftward: false, from, tip: from, facing };
  }
  const span = Math.hypot(toward[0], toward[1]) || 1;
  const [dx, dy] = [toward[0] / span, toward[1] / span];
  const tip = [from[0] + dx * length, from[1] + dy * length];
  context.beginPath();
  context.moveTo(from[0], from[1]);
  context.lineTo(tip[0] - dx * ARROW_HEAD_PX, tip[1] - dy * ARROW_HEAD_PX);
  context.stroke();
  context.restore();
  return { ...drawArrowHead(context, tip, [dx, dy], color), from, tip, facing: 0 };
}

/**
 * A direction arrow ending at its place, as one into a face is drawn (a hole's): it comes from
 * `length` pixels back along its way, its head on the place. Returns where its label goes
 * (`drawLabel`): before its tail, or beside the ring of one end on.
 */
export function drawArrowInto(context, direction, color, length = ARROW_PX) {
  const { from, toward, facing } = direction;
  if (facing) return drawArrow(context, direction, color, length);
  const span = Math.hypot(toward[0], toward[1]) || 1;
  const [dx, dy] = [toward[0] / span, toward[1] / span];
  const tail = [from[0] - dx * length, from[1] - dy * length];
  drawArrow(context, { from: tail, toward, facing: 0 }, color, length);
  return { x: tail[0] - dx * 6, y: tail[1] - dy * 6, leftward: dx > 0 };
}

/**
 * An arrow drawn its true length in the part, from `from` to `to` (millimetres), as a pattern's
 * spacing is: its head at `to`. Too short on the screen to read (looking along it), it is drawn end
 * on at `from`. Returns where its label goes (`drawLabel`), or null with an end behind the camera.
 */
export function drawArrowBetween(context, mapping, from, to, color) {
  const start = mapping.toScreen(...from);
  const end = mapping.toScreen(...to);
  if (!start || !end) return null;
  const way = [end[0] - start[0], end[1] - start[1]];
  const length = Math.hypot(way[0], way[1]);
  if (length < 2 * ARROW_HEAD_PX) {
    const along = to.map((value, axis) => value - from[axis]);
    const reach = Math.hypot(...along) || 1;
    const direction = screenDirection(mapping, from, along.map(value => value / reach), reach);
    return direction ? drawArrow(context, direction.facing ? direction : { ...direction, toward: way }, color) : null;
  }
  return drawArrow(context, { from: start, toward: way, facing: 0 }, color, length);
}

/**
 * An arrow's head at `tip`, pointing along `way` on the screen (a curved arrow's, at the end of its
 * path), filled. Returns where its label goes (`drawLabel`), just past it.
 */
export function drawArrowHead(context, tip, way, color) {
  const span = Math.hypot(way[0], way[1]) || 1;
  const [dx, dy] = [way[0] / span, way[1] / span];
  const base = [tip[0] - dx * ARROW_HEAD_PX, tip[1] - dy * ARROW_HEAD_PX];
  context.save();
  context.fillStyle = color;
  context.beginPath();
  context.moveTo(tip[0], tip[1]);
  context.lineTo(base[0] - dy * ARROW_HEAD_PX * 0.5, base[1] + dx * ARROW_HEAD_PX * 0.5);
  context.lineTo(base[0] + dy * ARROW_HEAD_PX * 0.5, base[1] - dx * ARROW_HEAD_PX * 0.5);
  context.closePath();
  context.fill();
  context.restore();
  return { x: tip[0] + dx * 6, y: tip[1] + dy * 6, leftward: dx < 0 };
}

const LABEL_FONT_PX = 11;
const LABEL_HEIGHT_PX = 18;

/**
 * A value a preview goes by ("5 mm", "90°"), in a tag of the preview's own color beside its arrow:
 * `place` is where the arrow said it goes (`drawArrow`), the tag on the side the arrow points.
 */
export function drawLabel(context, text, place, fill, font) {
  if (!text || !place) return;
  context.save();
  context.font = `${LABEL_FONT_PX}px ${font}`;
  const width = context.measureText(text).width + 10;
  const left = place.leftward ? place.x - width : place.x;
  const top = place.y - LABEL_HEIGHT_PX / 2;
  context.fillStyle = fill;
  context.beginPath();
  if (typeof context.roundRect === "function") context.roundRect(left, top, width, LABEL_HEIGHT_PX, 4);
  else context.rect(left, top, width, LABEL_HEIGHT_PX);
  context.fill();
  context.fillStyle = lightText(fill) ? "#0b1220" : "#ffffff";
  context.textBaseline = "middle";
  context.fillText(text, left + 5, top + LABEL_HEIGHT_PX / 2 + 0.5);
  context.restore();
}

/**
 * A solid shaded over the model once, as a CAD tool shades what it previews: its outlines and
 * faces on the screen (`shapes`, each the pixels around it, a hole of an outline marked `hole`),
 * filled as one, so where they overlap is shaded no darker and a hole lets the model show through
 * where nothing else covers it.
 */
export function fillShapes(context, shapes, color, alpha) {
  context.save();
  context.globalAlpha = alpha;
  context.fillStyle = color;
  context.beginPath();
  for (const { points, hole } of shapes) {
    if (points.length < 3 || points.some(point => !point)) continue;
    let twice = 0;
    points.forEach(([x0, y0], at) => {
      const [x1, y1] = points[(at + 1) % points.length];
      twice += x0 * y1 - x1 * y0;
    });
    // Every outline and face turned one way round, a hole the other, for one nonzero fill.
    const ordered = (twice < 0) !== Boolean(hole) ? [...points].reverse() : points;
    ordered.forEach(([x, y], at) => (at ? context.lineTo(x, y) : context.moveTo(x, y)));
    context.closePath();
  }
  context.fill("nonzero");
  context.restore();
}

/**
 * A solid's triangles in the view's pixels (`positions`, three numbers a corner in the part's
 * millimetres, and `triangles`, three corners each), each turned the same way round on the screen,
 * so one path filled over them shades all they cover once: a closed solid's far side turns the
 * other way, and would cancel its near side out where they overlap. A triangle with a corner
 * behind the camera is left out. Six numbers a triangle.
 */
export function screenTriangles(positions, triangles, toScreen) {
  const corners = Array.from({ length: Math.floor(positions.length / 3) },
    (_, at) => toScreen(positions[3 * at], positions[3 * at + 1], positions[3 * at + 2]));
  const out = [];
  for (let at = 0; at + 2 < triangles.length; at += 3) {
    const a = corners[triangles[at]];
    let b = corners[triangles[at + 1]];
    let c = corners[triangles[at + 2]];
    if (!a || !b || !c) continue;
    if ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0) [b, c] = [c, b];
    out.push(a[0], a[1], b[0], b[1], c[0], c[1]);
  }
  return out;
}

/**
 * A sketch's plane in the view: `toScreen` a place on it (in its units) to the viewport's pixels,
 * or null behind the camera; `toLocal` a pixel to the place on the plane under it; `perUnit` the
 * pixels one unit spans; `key` what the layout depends on, to paint again only when it changed.
 */
export function planeMapping(runtime, width, height, frame, unit = 1) {
  if (!runtime?.camera || !runtime.modelGroup || !runtime.THREE || !frame) return null;
  const { THREE, camera, modelGroup } = runtime;
  camera.updateMatrixWorld();
  modelGroup.updateMatrixWorld();
  const O = new THREE.Vector3(...frame.origin);
  const X = new THREE.Vector3(...frame.x);
  const Y = new THREE.Vector3(...frame.y);
  const Z = new THREE.Vector3(...frame.z);
  const scratch = new THREE.Vector3();
  const toScreen = ([u, v]) => {
    scratch.copy(O).addScaledVector(X, u * unit).addScaledVector(Y, v * unit).applyMatrix4(modelGroup.matrixWorld);
    if (scratch.clone().applyMatrix4(camera.matrixWorldInverse).z >= 0) return null;
    scratch.project(camera);
    return [((scratch.x + 1) * width) / 2, ((1 - scratch.y) * height) / 2];
  };
  const raycaster = new THREE.Raycaster();
  const inverse = modelGroup.matrixWorld.clone().invert();
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(Z, O);
  const hit = new THREE.Vector3();
  const toLocal = ([x, y]) => {
    raycaster.setFromCamera(new THREE.Vector2((x / width) * 2 - 1, 1 - (y / height) * 2), camera);
    const ray = raycaster.ray.clone().applyMatrix4(inverse);
    if (!ray.intersectPlane(plane, hit)) return null;
    const offset = hit.clone().sub(O);
    return [offset.dot(X) / unit, offset.dot(Y) / unit];
  };
  const a = toScreen([0, 0]);
  const b = toScreen([1, 0]);
  const perUnit = a && b ? Math.hypot(b[0] - a[0], b[1] - a[1]) || 1 : 1;
  return { toScreen, toLocal, perUnit, key: viewKey(width, height, camera, modelGroup) };
}

/** Points around a circle, or along an arc of it from `from` sweeping `sweep` radians. */
export function circlePoints(c, r, from = 0, sweep = 2 * Math.PI) {
  const steps = Math.max(12, Math.min(160, Math.ceil(Math.abs(sweep) * 24)));
  return Array.from({ length: steps + 1 }, (_, index) => {
    const angle = from + (sweep * index) / steps;
    return [c[0] + r * Math.cos(angle), c[1] + r * Math.sin(angle)];
  });
}

/** A curve of `sketchGeometry` as points along it. */
export function curvePoints(curve) {
  if (curve.kind === "spline") return curve.samples;
  if (curve.kind === "line") return curve.view || [curve.a, curve.b];
  if (curve.kind === "circle") return circlePoints(curve.c, curve.r);
  const { start, sweep } = arcSweep(curve);
  return circlePoints(curve.c, curve.r, start, sweep);
}

/** A relation glyph's size on screen, in pixels: SolidWorks' small box beside what a relation holds. */
export const GLYPH_PX = 14;

/**
 * A relation's glyph centered at (x, y) on screen: a small box, and in it the relation's sign, as
 * SolidWorks draws Horizontal (a level stroke), Vertical, Parallel (two slants), Perpendicular,
 * Equal, Tangent (a circle under a line), Concentric (two rings), Coincident (a dot), Midpoint (a
 * stroke with a dot at its middle), Symmetric (a centerline between two dots), Collinear (two
 * strokes on one line) and Fixed (an anchor over its ground).
 */
export function drawGlyph(context, kind, x, y, { fill, stroke }) {
  const half = GLYPH_PX / 2;
  const r = 3;
  context.beginPath();
  context.moveTo(x - half + r, y - half);
  context.arcTo(x + half, y - half, x + half, y + half, r);
  context.arcTo(x + half, y + half, x - half, y + half, r);
  context.arcTo(x - half, y + half, x - half, y - half, r);
  context.arcTo(x - half, y - half, x + half, y - half, r);
  context.closePath();
  context.fillStyle = fill;
  context.fill();
  context.strokeStyle = stroke;
  context.lineWidth = 1;
  context.stroke();
  const [l, rt, t, b] = [x - 4, x + 4, y - 4, y + 4];
  context.lineWidth = 1.4;
  context.fillStyle = stroke;
  context.beginPath();
  if (kind === "horizontal") { context.moveTo(l, y); context.lineTo(rt, y); }
  else if (kind === "vertical") { context.moveTo(x, t); context.lineTo(x, b); }
  else if (kind === "parallel") { context.moveTo(l, b); context.lineTo(x - 1, t); context.moveTo(x + 1, b); context.lineTo(rt, t); }
  else if (kind === "perpendicular") { context.moveTo(l, b); context.lineTo(rt, b); context.moveTo(x, b); context.lineTo(x, t); }
  else if (kind === "equal") { context.moveTo(l, y - 2); context.lineTo(rt, y - 2); context.moveTo(l, y + 2); context.lineTo(rt, y + 2); }
  else if (kind === "tangent") { context.moveTo(l, t + 1); context.lineTo(rt, t + 1); context.moveTo(x + 3, y + 1.5); context.arc(x, y + 1.5, 3, 0, 2 * Math.PI); }
  else if (kind === "concentric") { context.moveTo(x + 4, y); context.arc(x, y, 4, 0, 2 * Math.PI); context.moveTo(x + 1.5, y); context.arc(x, y, 1.5, 0, 2 * Math.PI); }
  else if (kind === "symmetric") { context.moveTo(x, t); context.lineTo(x, b); }
  else if (kind === "midpoint") { context.moveTo(l, y); context.lineTo(rt, y); }
  else if (kind === "collinear") { context.moveTo(l, y + 2); context.lineTo(x - 1, y - 0.5); context.moveTo(x + 1, y - 1.2); context.lineTo(rt, y - 3.6); }
  else if (kind === "fixed") {
    context.moveTo(x, t); context.lineTo(x, y + 1); context.moveTo(l, y + 1); context.lineTo(rt, y + 1);
    for (const at of [l + 1, x, rt - 1]) { context.moveTo(at, y + 1); context.lineTo(at - 2, b); }
  }
  context.stroke();
  const dot = (cx, cy, radius) => { context.beginPath(); context.arc(cx, cy, radius, 0, 2 * Math.PI); context.fill(); };
  if (kind === "coincident") dot(x, y, 2.2);
  else if (kind === "midpoint") dot(x, y, 1.8);
  else if (kind === "symmetric") { dot(l, y, 1.4); dot(rt, y, 1.4); }
}

/** Strokes a path through places on the sketch, broken where one is behind the camera. */
export function strokePath(context, points, toScreen, closed = false) {
  let started = false;
  context.beginPath();
  for (const point of points) {
    const screen = toScreen(point);
    if (!screen) { started = false; continue; }
    if (started) context.lineTo(screen[0], screen[1]); else { context.moveTo(screen[0], screen[1]); started = true; }
  }
  if (closed) context.closePath();
  context.stroke();
}

/** An arrowhead at `tip`, pointing away from `from`. */
export function arrowHead(context, tip, from, size) {
  const length = Math.hypot(tip[0] - from[0], tip[1] - from[1]) || 1;
  const ux = (tip[0] - from[0]) / length;
  const uy = (tip[1] - from[1]) / length;
  context.beginPath();
  context.moveTo(tip[0], tip[1]);
  context.lineTo(tip[0] - ux * size - uy * size * 0.4, tip[1] - uy * size + ux * size * 0.4);
  context.lineTo(tip[0] - ux * size + uy * size * 0.4, tip[1] - uy * size - ux * size * 0.4);
  context.closePath();
  context.fill();
}

/** Whether two label boxes ({x, y, w, h}) cover each other. */
export const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * What a selection box takes of a sketch, as SolidWorks' does: dragged left to right (a window) each
 * curve wholly inside it, right to left (a crossing) each it touches too, by its drawn points on the
 * screen (`toScreen`, the sketch's place to the view's pixels). The curves' ids.
 */
// Whether the segment a-b passes through the box (its sides `left`..`right`, `top`..`bottom`).
function crosses(a, b, left, top, right, bottom) {
  if (!a || !b) return false;
  const corners = [[left, top], [right, top], [right, bottom], [left, bottom]];
  const side = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  return corners.some((corner, index) => {
    const next = corners[(index + 1) % 4];
    return side(a, b, corner) !== side(a, b, next) && side(corner, next, a) !== side(corner, next, b);
  });
}

export function boxSelect(state, from, to, toScreen) {
  const [left, right] = [Math.min(from[0], to[0]), Math.max(from[0], to[0])];
  const [top, bottom] = [Math.min(from[1], to[1]), Math.max(from[1], to[1])];
  const crossing = to[0] < from[0];
  const inside = point => Boolean(point) && point[0] >= left && point[0] <= right && point[1] >= top && point[1] <= bottom;
  return sketchGeometry(state).curves.filter(curve => !curve.derived).filter(curve => {
    const drawn = curvePoints(curve).map(point => toScreen(point));
    if (!crossing) return drawn.length > 0 && drawn.every(inside);
    // A crossing takes a curve any piece of which passes through it, its ends outside or not.
    return drawn.some(inside) || drawn.slice(1).some((point, index) => crosses(drawn[index], point, left, top, right, bottom));
  }).map(curve => curve.id);
}

