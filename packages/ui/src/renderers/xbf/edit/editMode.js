/**
 * Edit mode's rules, pure: how a part's history, sizes and dimensions read in the viewer
 * (`cadgen/edit` reads them from the part's script), the modeling commands of the ribbon and
 * what each sends, what the note of a hand change says, and the undo history of hand changes.
 */

import { calloutValues, defaultSize, defaultStandard, holeCallout, holeFill } from "./holeSizes.js";
import { elementOf, isEdgeItem, isFaceItem } from "./selectors.js";

const ACRONYMS = new Set(["id", "od", "pcb", "usb", "led", "cnc", "fdm", "sla"]);
const UNIT_WORDS = Object.freeze({ mm: "Millimeters", in: "Inches", cm: "Centimeters", m: "Meters" });
const UNIT_MARKS = Object.freeze({ mm: "mm", in: "in", cm: "cm", m: "m" });
// The tracer's kinds, in the words a CAD tree uses for them.
const KIND_NAMES = Object.freeze({ Join: "Combine", Move: "Move", Cut: "Cut", Intersect: "Intersect" });
// A command's sizes, in the part's own units, as it opens: small next to a part a hand holds.
// A counterbore and a countersink open twice the hole's diameter (a counterbore as deep as the hole
// is wide), a countersink at 90 degrees in a metric part and 82 in an inch one, as flat-head screws
// are made; a draft at 1 degree. Starting values, typed over.
const DEFAULTS = Object.freeze({
  mm: { radius: "1", distance: "1", diameter: "3", depth: "5", thickness: "1", spacing: "10", cbore: "6", cboreDepth: "3", csk: "6",
    cskAngle: "90", draft: "1" },
  in: { radius: ".03", distance: ".03", diameter: ".125", depth: ".25", thickness: ".04", spacing: ".5", cbore: ".25", cboreDepth: ".125",
    csk: ".25", cskAngle: "82", draft: "1" },
});
const HISTORY_LIMIT = 50;

/** A size's name as an engineer says it: `TRAY_HEIGHT` reads "Tray height"; a bare number stays as written. */
export function sizeName(name) {
  const text = String(name ?? "");
  if (!/^[A-Za-z_]\w*$/.test(text)) return text;
  const words = text.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/[_\s]+/).filter(Boolean);
  if (!words.length) return text;
  const cased = words.map(word => (ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word.length === 1 ? word.toUpperCase() : word.toLowerCase()));
  return cased[0].charAt(0).toUpperCase() + cased[0].slice(1) + (cased.length > 1 ? ` ${cased.slice(1).join(" ")}` : "");
}

/** The project's units in words, for the ribbon: "Inches". */
export const unitWord = units => UNIT_WORDS[units] || String(units || "");

/** A value with its unit as the panels show it: "2.80 in"; an angle or a count keeps its own. */
export function withUnit(text, unit) {
  const mark = UNIT_MARKS[unit] || unit || "";
  return mark ? `${text} ${mark}` : String(text);
}

/**
 * Each feature of the history named as a CAD tree names it, its kind numbered in order
 * ("Extrude1", "Fillet1", "Extrude2"), with the name its script gives it as words ("Cavity") beside.
 */
export function featureNames(rows = []) {
  const counts = new Map();
  return rows.map(row => {
    const kind = KIND_NAMES[row.kind] || row.kind || "Feature";
    const count = (counts.get(kind) || 0) + 1;
    counts.set(kind, count);
    return { key: row.key, kind, title: `${kind}${count}`, name: row.name ? sizeName(row.name) : "" };
  });
}

/** The dimensions a feature draws on the model. */
export const rowDimensions = (state, rowKey) => (state?.dimensions || []).filter(dimension => dimension.row === rowKey);

/** The origin's planes, as a CAD tree lists them under the part (SolidWorks' order). */
export const ORIGIN_PLANES = Object.freeze(["Front", "Top", "Right"]);
// A sketch's own dimensions: its profile's sizes, not the depth its feature gives it.
const SKETCH_DIMENSION = /:(x|y|r|diameter)$/;

/**
 * The part as a CAD tool's design tree shows it (SolidWorks' FeatureManager): its features
 * numbered by kind within each part (Boss-Extrude1, Boss-Extrude2, Cut-Extrude1, Fillet1),
 * each solid's sketch under it (Sketch1, on the plane it lies on), and an assembly's parts as
 * its components (Daisy tray<1>), each with its own features. A feature's id is the line of the
 * history that makes it, so a command that copies a feature finds its row by it. It keeps the lines of
 * the script it stands for (`lines`), each as the engine read it, for a failed build to be told by, and
 * the last line of the statement that makes it (`end`) where the engine read that statement.
 */
export function featureTree(state) {
  const rowOf = new Map((state?.rows || []).map(row => [row.key, row]));
  // A feature's lines, `{ file, line, end, text }` each, a statement it stands for by its first line and its last
  // (`end`, null where the engine did not say it): its own first, then the rows folded into it (the profile it
  // extrudes, a cut joined to it). `text` is the line as written, empty from an engine that gave none.
  const linesOf = feature => {
    const folded = (feature.rows || []).filter(key => key !== feature.key).map(key => {
      const row = rowOf.get(key), at = key.lastIndexOf(":");
      return { file: row?.file ?? key.slice(0, at), line: row?.line ?? Number(key.slice(at + 1)), end: row?.end ?? null,
        text: row?.code || "" };
    });
    return [{ file: feature.file, line: feature.line, end: feature.end ?? null, text: feature.text || "" }, ...folded]
      .filter(each => each.file && each.line);
  };
  const partFeatures = features => {
    const counts = new Map();
    // A sketch with relations keeps the name its script gives it; a profile is numbered in order,
    // past the names those take, so no two sketches of a part share one.
    const taken = new Set((features || []).map(feature => feature.sketch?.name).filter(Boolean));
    let sketches = 0;
    const nextName = () => {
      do { sketches += 1; } while (taken.has(`Sketch${sketches}`));
      return `Sketch${sketches}`;
    };
    const sketchOf = (feature, id) => ({ id, title: feature.sketch.name || nextName(), plane: feature.sketch.plane || "",
      offset: feature.sketch.offset || null,
      status: feature.sketch.status || "", file: feature.sketch.file || null, line: feature.sketch.line || null,
      constrained: Boolean(feature.sketch.name && feature.sketch.file) });
    return (features || []).map(feature => {
      if (feature.kind === "Sketch") {
        // A sketch nothing makes a solid of yet: a row of its own, as a CAD tree lists it.
        const sketch = sketchOf(feature, feature.key);
        return { id: feature.key, kind: "Sketch", title: sketch.title, name: "", count: 1, rows: [], file: feature.file, line: feature.line,
          end: feature.end ?? null, lines: linesOf(feature), sketch };
      }
      const count = (counts.get(feature.kind) || 0) + 1;
      counts.set(feature.kind, count);
      return {
        // A name given in the tree (the comment at the end of its line) over the tree's own, which
        // still counts it, as SolidWorks numbers the next fillet Fillet2 after Fillet1 is renamed.
        id: feature.key, kind: feature.kind, title: feature.named || `${feature.kind}${count}`, named: feature.named || "",
        name: feature.name ? sizeName(feature.name) : "", count: feature.count || 1,
        rows: feature.rows || [feature.key], file: feature.file, line: feature.line, end: feature.end ?? null, lines: linesOf(feature),
        sketch: feature.sketch ? sketchOf(feature, `sketch:${feature.key}`) : null,
        // What Edit Feature opens the feature's command with, when a command writes its line.
        edit: feature.edit || null,
        // A reference Plane's place (its origin and axes), for the view to draw it, and the name
        // the script holds it in, which a command going from it writes.
        plane: feature.plane || null,
        variable: feature.name || null,
        // Set aside by Suppress: its lines are comments in the script, shown greyed where they are.
        suppressed: Boolean(feature.suppressed),
      };
    });
  };
  if (state?.components?.length) {
    return { assembly: true, components: state.components.map(component => ({
      id: `component:${component.file}`, title: `${sizeName(component.name)}<1>`, features: partFeatures(component.features),
      // The part's own model, which Open Part opens to model it: its document's id (cadgen 0.8's
      // `@model`), else the STEP it writes; null for neither.
      document: component.document || null, step: component.step || null, name: sizeName(component.name),
    })) };
  }
  return { assembly: false, features: partFeatures(state?.features) };
}

/** The sketch a tree row is (its own, or a feature's): what Edit Sketch opens and Extrude makes a solid of. */
export function treeSketch(tree, id) {
  if (!id) return null;
  for (const feature of treeFeatures(tree)) {
    if (feature.sketch && (feature.sketch.id === id || (feature.kind === "Sketch" && feature.id === id))) return feature.sketch;
  }
  return null;
}

/**
 * The design tree's id for the sketch a view draws (`{ file, line }`): the sketch's own row, or the
 * row under the feature that takes it. Null for a sketch the tree does not show.
 */
export function sketchTreeId(tree, view) {
  const owner = treeFeatures(tree).find(feature => feature.sketch && feature.sketch.file === view?.file && feature.sketch.line === view?.line);
  if (!owner) return null;
  return owner.kind === "Sketch" ? owner.id : owner.sketch.id;
}

/**
 * Which side of a sketch's plane the part lies on, from the part's extent (`bounds`, millimetres):
 * 1 where the plane's normal points, -1 behind it, 0 when the plane runs through the part or the
 * sketch has no frame. A cut goes toward the part, as a cut from a face of it goes into it.
 */
export function partSide(view, bounds) {
  const frame = view?.state?.frame;
  if (!frame?.origin || !frame?.z || !bounds) return 0;
  const [lo, hi] = bounds;
  const reach = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1;
  const sides = [lo[0], hi[0]].flatMap(x => [lo[1], hi[1]].flatMap(y => [lo[2], hi[2]].map(z =>
    (x - frame.origin[0]) * frame.z[0] + (y - frame.origin[1]) * frame.z[1] + (z - frame.origin[2]) * frame.z[2])));
  const slack = 1e-6 * reach;
  if (sides.every(side => side >= -slack)) return 1;
  if (sides.every(side => side <= slack)) return -1;
  return 0;
}

/** A constrained sketch as the part's last trace solved it, by where its script makes it. */
export const sketchView = (state, sketch) => (state?.sketches || []).find(view => sketch && view.file === sketch.file && view.line === sketch.line) || null;

/** The name a new sketch of the part takes: one past the last its tree shows, as SolidWorks numbers them. */
export function nextSketchName(tree) {
  const numbers = treeFeatures(tree).map(feature => /^Sketch(\d+)$/.exec(feature.sketch?.title || "")?.[1]).filter(Boolean).map(Number);
  return `Sketch${Math.max(0, ...numbers) + 1}`;
}

/**
 * Where the rollback bar sits in a part's tree, as SolidWorks' FeatureManager draws it: the index
 * of the item it is above (`bar.item`), or past the last one when the part is not rolled back.
 */
export function barIndex(tree, bar) {
  const features = tree?.assembly ? [] : tree?.features || [];
  const index = bar?.item ? features.findIndex(feature => feature.id === bar.item) : -1;
  return index < 0 ? features.length : index;
}

/** The items a rollback bar leaves out of the part: those below it, greyed as SolidWorks greys them. */
export const rolledBack = (tree, bar) => new Set((tree?.assembly ? [] : tree?.features || []).slice(barIndex(tree, bar)).map(feature => feature.id));

/** The commands Edit Feature rolls back for, so their edges or faces are picked again on the body before them. */
export const REPICKS = Object.freeze(new Set(["fillet", "chamfer", "shell", "draft", "hole", "offset_face", "delete_face"]));
// Edit Feature on any other feature rolls the part back to just before it too, as SolidWorks' every
// PropertyManager does, so its preview is the feature itself rather than drawn over what it made.
// Not the part's first solid (`edit.first`), which has nothing before it.
export const ROLLS_BACK = Object.freeze(new Set(["extrude", "cut", "revolve", "revolve_cut", "sweep", "sweep_cut", "loft", "loft_cut",
  "rib", "pattern", "mirror", "split", "delete_body", "plane"]));

/** Every feature of a tree, an assembly's parts' too, in order. */
export const treeFeatures = tree => (tree?.assembly ? tree.components.flatMap(component => component.features) : tree?.features || []);

/** What can be selected in a tree: its features, their sketches, the origin, its planes and an assembly's parts. */
export function treeIds(tree) {
  const ids = new Set(["origin", ...ORIGIN_PLANES.map(plane => `plane:${plane}`)]);
  for (const feature of treeFeatures(tree)) {
    ids.add(feature.id);
    if (feature.sketch) ids.add(feature.sketch.id);
  }
  for (const component of tree?.components || []) ids.add(component.id);
  return ids;
}

/**
 * The dimensions the selection draws on the model: a feature's (its sketch's and its depth), a
 * sketch's own (its profile's sizes), none for a plane, the origin or a part.
 */
export function selectionDimensions(state, tree, selected) {
  if (!selected) return [];
  const sketch = selected.startsWith("sketch:");
  const id = sketch ? selected.slice("sketch:".length) : selected;
  const feature = treeFeatures(tree).find(each => each.id === id);
  if (!feature) return [];
  const rows = new Set(feature.rows);
  return (state?.dimensions || []).filter(dimension => rows.has(dimension.row) && (!sketch || SKETCH_DIMENSION.test(dimension.id)));
}

/** How long the origin's axes are drawn: a third of the part's reach, in its millimetres. */
export function originAxis(bounds) {
  const [min, max] = bounds || [[-30, -30, -30], [30, 30, 30]];
  return (Math.max(...[0, 1, 2].map(axis => Math.max(Math.abs(min[axis]), Math.abs(max[axis])))) || 30) / 3;
}

/**
 * An origin plane drawn on the model, as a CAD tool shows a plane: a square through the origin
 * a little larger than the part, in the part's own millimetres. `null` for anything else.
 */
export function planeOutline(name, bounds) {
  if (!ORIGIN_PLANES.includes(name)) return null;
  const [min, max] = bounds || [[-50, -50, -50], [50, 50, 50]];
  const reach = Math.max(...[0, 1, 2].map(axis => Math.max(Math.abs(min[axis]), Math.abs(max[axis])))) * 1.15 || 50;
  const square = (u, v) => [[-reach, -reach], [reach, -reach], [reach, reach], [-reach, reach]].map(([a, b]) => {
    const point = [0, 0, 0];
    point[u] = a;
    point[v] = b;
    return point;
  });
  return name === "Top" ? square(0, 1) : name === "Front" ? square(0, 2) : square(1, 2);
}

// ---- what the view previews of a command, and the way it goes --------------------------------

const MM_PER_UNIT = Object.freeze({ mm: 1, in: 25.4, cm: 10, m: 1000 });
const END_WORDS = Object.freeze({ through: "Through All", next: "Up To Next", surface: "Up To Surface", vertex: "Up To Vertex" });
const AXES = Object.freeze({ X: [1, 0, 0], Y: [0, 1, 0], Z: [0, 0, 1] });
// The origin's planes by the axes they hold, as Mirror names them.
const MIRROR_PLANES = Object.freeze({ XY: "Top", XZ: "Front", YZ: "Right" });

/** A value typed as a plain number ("5", ".25"), or null for anything else: a size's name, a formula. */
export function plainNumber(text) {
  const written = String(text ?? "").trim();
  return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(written) ? Number(written) : null;
}

// A size as its tag reads: a number with its unit ("5 mm"), a size's name in words ("Wall"), a formula as written.
const sizeTag = (text, units) => {
  const written = String(text ?? "").trim();
  return plainNumber(written) !== null ? withUnit(written, units) : sizeName(written);
};

/**
 * What the view draws of an extrude while its panel is open, as SolidWorks previews one: its sweep
 * along the sketch's normal (`depth` in the part's millimetres, `taper` its draft), the way it goes
 * (`reverse`; both ways at Mid Plane) and its depth as a tag ("5 mm", "Through All"). Where the body
 * or a pick ends it, or its depth is written as a size's name, it draws its arrow alone
 * (`arrowOnly`), from the sketch the way it goes: Up To Surface and Up To Vertex go to the side of
 * the sketch's plane what they end on is (`ending`'s centre, `vertex_at`; `frame`, the sketch's).
 * Null without a sketch.
 */
export function extrudePreview(id, values, { units = "mm", sketch = null, frame = null, ending = null } = {}) {
  if (!sketch) return null;
  const end = values.end || "blind";
  const angle = plainNumber(values.draft_angle);
  const taper = values.draft && end !== "next" && angle !== null && angle > 0 && angle < 90 ? (values.outward ? -angle : angle) : 0;
  const base = { kind: id === "cut" ? "cut" : "boss", end, file: sketch.file, line: sketch.line, taper, depth: 0, reverse: false, units,
    ...secondDirection(values, end, units) };
  if (end === "through") return { ...base, reverse: Boolean(values.reverse), label: END_WORDS.through, ...(values.thin ? { arrowOnly: true } : {}) };
  if (end === "surface" || end === "vertex") {
    const target = end === "surface" ? ending?.center : values.vertex_at;
    const behind = target && frame ? [0, 1, 2].reduce((sum, axis) => sum + (Number(target[axis]) - frame.origin[axis]) * frame.z[axis], 0) < 0 : false;
    return { ...base, reverse: behind, arrowOnly: true, label: END_WORDS[end] };
  }
  if (end === "next") return { ...base, arrowOnly: true, label: END_WORDS.next };
  const depth = plainNumber(values.depth);
  const label = sizeTag(values.depth, units);
  const reverse = end !== "mid" && Boolean(values.reverse);
  // A thin feature's wall, like a depth written as a size's name, is the server's to preview.
  if (depth === null || !(depth > 0) || values.thin) return { ...base, reverse, arrowOnly: true, label };
  return { ...base, depth: depth * (MM_PER_UNIT[units] || 1), reverse, label };
}

/**
 * Direction 2 of an extrude's preview, the other way from its sketch: Through All (`through2`) or
 * its depth in the part's millimetres (`depth2`), its own draft (`taper2`) and tag (`label2`). A
 * depth written as a size's name is the server's to preview (`arrowOnly`). Nothing at Mid Plane.
 */
function secondDirection(values, end, units) {
  if (!values.direction2 || end === "mid") return {};
  const angle = plainNumber(values.draft_angle2);
  const taper2 = values.draft2 && angle !== null && angle > 0 && angle < 90 ? (values.outward2 ? -angle : angle) : 0;
  if (values.end2 === "through") return { through2: true, taper2, label2: END_WORDS.through };
  const depth = plainNumber(values.depth2);
  const label2 = sizeTag(values.depth2, units);
  return depth !== null && depth > 0 ? { depth2: depth * (MM_PER_UNIT[units] || 1), taper2, label2 } : { arrowOnly: true, taper2, label2 };
}

/**
 * The Depth an extrude's arrow sets where it is dragged, as SolidWorks' extrude handle sets it:
 * `reached` is how far from the sketch's plane the arrow's end is, the way it points, in the part's
 * millimetres; the depth is that (twice it at Mid Plane, whose arrows sit at half), in the part's
 * units to the places the panel shows (`text`) and back in millimetres for the preview (`mm`).
 * Never less than the smallest the panel shows.
 */
export function draggedDepth(reached, end, units = "mm") {
  const places = units === "in" ? 3 : 2;
  const perUnit = MM_PER_UNIT[units] || 1;
  const depth = Math.max(10 ** -places, ((end === "mid" ? 2 : 1) * reached) / perUnit);
  const text = String(Number(depth.toFixed(places)));
  return { text, mm: Number(text) * perUnit };
}

/**
 * The angle a revolve's arrow is dragged to, as SolidWorks' handle turns one: of the places its
 * arrow's head can reach (`reach`, its place on the screen at each whole degree from 1 to 360), the
 * one nearest the pointer, to the nearest 5 degrees.
 */
export function draggedAngle(reach, point) {
  let best = 1;
  let nearest = Infinity;
  reach.forEach((place, index) => {
    const distance = place ? Math.hypot(place[0] - point[0], place[1] - point[1]) : Infinity;
    if (distance < nearest) {
      nearest = distance;
      best = index + 1;
    }
  });
  const degrees = Math.min(360, Math.max(5, Math.round(best / 5) * 5));
  return { text: String(degrees), degrees };
}

/**
 * A linear pattern's way, for the view to draw over the copies the server previews: the axis it
 * runs along (`along`, the other way when reversed), its spacing in the part's millimetres, how
 * many, and the spacing as a tag. Null for a circular one (it goes all the way round), or a
 * spacing or count written as a size's name.
 */
export function patternPreview(values, units = "mm") {
  if (values.type !== "linear") return null;
  const spacing = plainNumber(values.spacing);
  const count = plainNumber(values.count);
  const axis = AXES[String(values.direction || "X").toUpperCase()];
  if (!axis || spacing === null || !(spacing > 0) || count === null || !(count >= 2)) return null;
  return { mark: "pattern", along: axis.map(value => (values.reverse ? -value || 0 : value)), spacing: spacing * (MM_PER_UNIT[units] || 1),
    count: Math.round(count), label: sizeTag(values.spacing, units) };
}

/**
 * Where a linear pattern's arrow runs (`patternPreview`), from what the server previews of its
 * copies (`positions`, three numbers a corner, in the part's millimetres): from the feature it
 * copies to its first copy. Its copies run from one spacing out to the last, so the middle of
 * what they cover is half the count of spacings out. Null for no copies drawn.
 */
export function patternArrow(mark, positions = []) {
  if (!mark || positions.length < 3) return null;
  const low = [Infinity, Infinity, Infinity];
  const high = [-Infinity, -Infinity, -Infinity];
  for (let at = 0; at + 2 < positions.length; at += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      low[axis] = Math.min(low[axis], positions[at + axis]);
      high[axis] = Math.max(high[axis], positions[at + axis]);
    }
  }
  const middle = low.map((value, axis) => (value + high[axis]) / 2);
  const from = middle.map((value, axis) => value - mark.along[axis] * mark.spacing * (mark.count / 2));
  return { from, to: from.map((value, axis) => value + mark.along[axis] * mark.spacing) };
}

/**
 * A hole's way into its face, for the view to draw while Hole is open: where it goes in (`at`, the
 * face's centre moved by the panel's distances, kept on the face's plane, in the part's
 * millimetres), the way in (`into`, against the face's normal) and its depth as a tag. `face` is
 * the face picked (its `center` and `normal`); null without one.
 */
export function holePreview(values, units = "mm", face = null) {
  const center = face?.center;
  const normal = face?.normal;
  const length = normal ? Math.hypot(Number(normal[0]), Number(normal[1]), Number(normal[2])) : 0;
  if (!center || !(length > 0)) return null;
  const unit = Array.from(normal, value => Number(value) / length);
  const mm = MM_PER_UNIT[units] || 1;
  // Each hole's place on the face: its offsets from the face's center, put back on the face's plane.
  const placeOf = given => {
    const moved = ["x", "y", "z"].map(axis => (plainNumber(given[axis]) ?? 0) * mm);
    const off = moved[0] * unit[0] + moved[1] * unit[1] + moved[2] * unit[2];
    return [0, 1, 2].map(axis => Number(center[axis]) + moved[axis] - unit[axis] * off);
  };
  return { mark: "hole", at: placeOf(values), into: unit.map(value => -value || 0),
    label: values.through ? END_WORDS.through : sizeTag(values.depth, units), ...(values.more?.length ? { also: values.more.map(placeOf) } : {}) };
}

// The origin's planes' normals, the way build123d's Plane.XY, Plane.XZ and Plane.YZ face, and those names.
const PLANE_NORMALS = Object.freeze({ Top: [0, 0, 1], Front: [0, -1, 0], Right: [1, 0, 0] });
/** Each origin plane by the axes it holds: NX names its datum planes so ("XY Plane" for Top, `nx.js`). */
export const PLANE_AXES = Object.freeze({ Top: "XY", Front: "XZ", Right: "YZ" });

/**
 * Whether a draft about an origin plane starts reversed: its direction of pull is the plane's
 * normal turned toward the part, so the part keeps its size at the plane and narrows away from it.
 */
export function draftReversed(plane, bounds, placed = null) {
  // An origin plane by its name, or a reference plane by where it is (`placed`: its origin and z).
  const normal = placed?.z || PLANE_NORMALS[plane];
  if (!normal || !bounds) return false;
  const origin = placed?.origin || [0, 0, 0];
  const middle = [0, 1, 2].map(axis => (bounds[0][axis] + bounds[1][axis]) / 2 - origin[axis]);
  return normal[0] * middle[0] + normal[1] * middle[1] + normal[2] * middle[2] < -1e-9;
}

/**
 * The part's reference planes (Plane1), as a command that goes from a plane lists them: a mirror's,
 * a draft's neutral plane, another plane's reference. Each is `named:plane1` by the name the
 * script holds it in, with its title in the tree, its id there, and where it is.
 */
export const referencePlanes = tree => treeFeatures(tree).filter(feature => feature.kind === "Plane" && feature.variable && feature.plane)
  .map(feature => ({ id: feature.id, value: `named:${feature.variable}`, label: feature.title, plane: feature.plane }));

/** A reference plane's place as a face's is given to a preview: its `center` and `normal`. */
export const planeAt = named => (named?.plane ? { center: named.plane.origin, normal: named.plane.z, x: named.plane.x } : null);

/**
 * A draft's neutral plane and its direction of pull, for the view to draw while Draft is open: the
 * plane drawn as Mirror's is (an origin plane by its axes, or a square on a face's plane), and an
 * arrow from it the way the part narrows (`pull`, from `at`). `face` is a neutral face picked (its
 * `center` and outward `normal`): its plane pulls out of the part, reversed into it. Null for the
 * face a reopened draft keeps, which the panel has no place for.
 */
export function draftPreview(values, face = null, bounds = null) {
  const sign = values.reverse ? -1 : 1;
  if (face?.center && face?.normal) {
    const center = Array.from(face.center, Number);
    const normal = Array.from(face.normal, Number);
    return { mark: "draft", center, normal, at: center, pull: normal.map(value => value * sign || 0) };
  }
  const normal = PLANE_NORMALS[values.neutral];
  if (!normal) return null;
  const [min, max] = bounds || [[0, 0, 0], [0, 0, 0]];
  // From the part's middle, put on the plane.
  const at = [0, 1, 2].map(axis => (normal[axis] ? 0 : (min[axis] + max[axis]) / 2));
  return { mark: "draft", plane: PLANE_AXES[values.neutral], at, pull: normal.map(value => value * sign || 0) };
}

/**
 * A reference plane as it would be made, for the view to draw while Plane is open: the plane at its
 * offset (`center`, `normal`), drawn as Mirror's is, and an arrow from what it is offset from
 * (`at`) the way it goes (`along`), tagged with the distance. `face` is a face picked (its `center`
 * and outward `normal`); else the origin plane `values.reference` names, the arrow from the part's
 * middle put on it. Null for none, or a distance written as a size's name.
 */
export function planePreview(values, face = null, bounds = null, units = "mm") {
  const distance = plainNumber(values.distance);
  if (distance === null) return null;
  let at;
  let normal;
  let x = face?.x ? Array.from(face.x, Number) : null;
  if (face?.center && face?.normal) {
    at = Array.from(face.center, Number);
    normal = Array.from(face.normal, Number);
  } else if (PLANE_NORMALS[values.reference]) {
    normal = PLANE_NORMALS[values.reference];
    x = PLANE_X[values.reference];
    const [min, max] = bounds || [[0, 0, 0], [0, 0, 0]];
    at = [0, 1, 2].map(axis => (normal[axis] ? 0 : (min[axis] + max[axis]) / 2));
  } else return null;
  const length = Math.hypot(...normal) || 1;
  const along = normal.map(value => ((values.flip ? -1 : 1) * value) / length || 0);
  const moved = distance * (MM_PER_UNIT[units] || 1);
  const unitNormal = normal.map(value => value / length);
  // At angle: the normal turned about the plane's own X or Y axis (Y = Z x X), by the right hand.
  const degrees = turnedAngle(values.angle);
  const axis = degrees && x ? (values.about === "y" ? crossOf(unitNormal, x) : x) : null;
  return { mark: "plane", center: at.map((value, index) => value + along[index] * moved),
    normal: axis ? turnedAbout(unitNormal, axis, degrees) : unitNormal, at, along,
    label: degrees ? `${sizeTag(values.distance, units)}, ${degrees}°` : sizeTag(values.distance, units) };
}

// The origin planes' X axes, as build123d's Plane.XY, Plane.XZ and Plane.YZ have them.
const PLANE_X = Object.freeze({ Top: [1, 0, 0], Front: [1, 0, 0], Right: [0, 1, 0] });
// A plane's angle as typed, in degrees, or 0 for none (or one that is not a plain number).
const turnedAngle = typed => plainNumber(typed) || 0;
const crossOf = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
/** `v` turned about the unit `axis` by `degrees`, by the right hand (Rodrigues). */
function turnedAbout(v, axis, degrees) {
  const angle = (degrees * Math.PI) / 180;
  const length = Math.hypot(...axis) || 1;
  const k = axis.map(value => value / length);
  const across = crossOf(k, v);
  const along = k[0] * v[0] + k[1] * v[1] + k[2] * v[2];
  return [0, 1, 2].map(index => v[index] * Math.cos(angle) + across[index] * Math.sin(angle) + k[index] * along * (1 - Math.cos(angle)));
}

/**
 * The plane a mirror goes about, for the view to draw while Mirror is open: a face picked (its
 * `center` and `normal`), or one of the origin's planes by the axes it holds ("YZ"). Null for the
 * face a reopened mirror keeps, which the panel has no place for.
 */
/**
 * SolidWorks' standard views as this viewer's axes have them (Z up, the front looking along +Y): where
 * the camera looks from (`direction`) and which way is up, as the view cube's faces and corners turn it.
 */
export const STANDARD_VIEWS = Object.freeze({
  front: { direction: [0, -1, 0], up: [0, 0, 1] }, back: { direction: [0, 1, 0], up: [0, 0, 1] },
  left: { direction: [-1, 0, 0], up: [0, 0, 1] }, right: { direction: [1, 0, 0], up: [0, 0, 1] },
  top: { direction: [0, 0, 1], up: [0, 1, 0] }, bottom: { direction: [0, 0, -1], up: [0, 1, 0] },
  isometric: { direction: [1, -1, 1], up: [0, 0, 1] },
});

/** A Mid Plane drawn where it will be: midway between its two faces, square to the first (`pickData`s with `center` and `normal`). */
export function midPlanePreview(picks) {
  const [a, b] = picks || [];
  if (!a?.center || !a?.normal || !b?.center) return null;
  const center = [0, 1, 2].map(axis => (Number(a.center[axis]) + Number(b.center[axis])) / 2);
  return { mark: "plane", center, normal: Array.from(a.normal, Number), at: center, along: [0, 0, 0], label: "" };
}

export function mirrorPreview(values, face = null) {
  if (face?.center && face?.normal) return { mark: "mirror", center: Array.from(face.center, Number), normal: Array.from(face.normal, Number) };
  return MIRROR_PLANES[values.plane] ? { mark: "mirror", plane: values.plane } : null;
}

/**
 * A mirror's plane drawn on the model as the origin's planes are (`planeOutline`): an origin plane
 * by its axes, or a square on the face's plane around its centre, a little larger than the part.
 */
export function mirrorOutline(mark, bounds) {
  if (!mark) return null;
  if (mark.plane) return planeOutline(MIRROR_PLANES[mark.plane], bounds);
  const length = Math.hypot(...mark.normal);
  if (!(length > 0)) return null;
  const n = mark.normal.map(value => value / length);
  // Two ways in the plane, square to each other: across an axis the normal is not along.
  const helper = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  const cross = (p, q) => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]];
  const u0 = cross(n, helper);
  const u = u0.map(value => value / Math.hypot(...u0));
  const v = cross(n, u);
  const [min, max] = bounds || [[-50, -50, -50], [50, 50, 50]];
  const reach = (Math.max(...[0, 1, 2].map(axis => max[axis] - min[axis])) / 2) * 1.15 || 50;
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => mark.center.map((value, axis) => value + (a * u[axis] + b * v[axis]) * reach));
}

const GRAMS_PER_OUNCE = 28.349523125;

/**
 * Mass Properties as SolidWorks lists them, in the part's units (`mass`, as `cadgen/edit` works
 * them out in millimetres): its mass in a material of `density` g/cm^3 (grams, or ounces with the
 * grams beside them in an inch part; none without a material), its volume, surface area, center of
 * mass and overall size.
 */
export function massRows(mass, units, density = null) {
  const inch = units === "in";
  const unitWord = inch ? "in" : "mm";
  const said = (value, places) => Number(value.toFixed(places)).toLocaleString("en-US", { maximumFractionDigits: places });
  const length = value => said(inch ? value / 25.4 : value, inch ? 3 : 2);
  const rows = [];
  if (density) {
    const grams = (mass.volume * density) / 1000;
    rows.push({ label: "Mass", value: inch ? `${said(grams / GRAMS_PER_OUNCE, 3)} oz (${said(grams, 2)} g)`
      : grams >= 1000 ? `${said(grams / 1000, 3)} kg` : `${said(grams, 2)} g` });
  }
  rows.push({ label: "Volume", value: `${said(inch ? mass.volume / 25.4 ** 3 : mass.volume, inch ? 4 : 2)} ${unitWord}³` });
  rows.push({ label: "Surface area", value: `${said(inch ? mass.area / 25.4 ** 2 : mass.area, inch ? 4 : 2)} ${unitWord}²` });
  ["X", "Y", "Z"].forEach((axis, index) => rows.push({ label: `Center of mass ${axis}`, value: `${length(mass.center[index])} ${unitWord}` }));
  rows.push({ label: "Overall size", value: `${[0, 1, 2].map(axis => length(mass.box[1][axis] - mass.box[0][axis])).join(" x ")} ${unitWord}` });
  return rows;
}

/**
 * The part's moments of inertia, as SolidWorks' Mass Properties lists them once it has a material:
 * Lxx, Lyy and Lzz about the center of mass along the part's axes, then the principal moments
 * Px <= Py <= Pz with the axis each is about. In g·mm², or lb·in² in an inch part. None without a
 * density, or when the server gave no moments.
 */
export function inertiaRows(mass, units, density = null) {
  if (!density || !mass?.inertia || !mass?.principal) return [];
  const inch = units === "in";
  // The server's per unit density (mm^5), times g/mm^3; in an inch part, pounds and square inches.
  const scale = (density / 1000) * (inch ? 1 / 453.59237 / 25.4 ** 2 : 1);
  const word = inch ? "lb·in²" : "g·mm²";
  const said = value => `${Number((value * scale).toPrecision(5)).toLocaleString("en-US", { maximumFractionDigits: 6 })} ${word}`;
  const axis = vector => `(${vector.map(part => Number(part.toFixed(3)) + 0).join(", ")})`;
  return [
    ...["xx", "yy", "zz"].map((name, index) => ({ label: `L${name}`, value: said(mass.inertia[index][index]) })),
    ...["x", "y", "z"].map((name, index) => ({ label: `P${name}`, value: `${said(mass.principal.moments[index])} about ${axis(mass.principal.axes[index])}` })),
  ];
}

/** The feature edit mode opens on: the first that draws dimensions (the part's base), else the first. */
export function defaultRow(state) {
  const drawn = new Set((state?.dimensions || []).map(dimension => dimension.row));
  return state?.rows?.find(row => drawn.has(row.key))?.key ?? state?.rows?.[0]?.key ?? null;
}

/** Whether a formula only restates its value ("20" for 20), so a panel shows it once. */
export const restates = (formula, display) => !formula || String(formula).replace(/\s+/g, "") === String(display ?? "").replace(/\s+/g, "");

/** The formula behind a value, its sizes in words: `LENGTH-2*WALL` reads "Length - 2 × Wall". */
export function formulaWords(formula) {
  return String(formula || "")
    .replace(/[A-Za-z_]\w*/g, name => sizeName(name))
    .replace(/\s*([+\-/])\s*/g, " $1 ")
    .replace(/\s*\*\s*/g, " × ")
    .replace(/\s+/g, " ")
    .trim();
}

/** What a hand change tells the agent, queued for the person's next message: plain words, the line in parens. */
/**
 * What edit mode says of a profile made from build123d's shapes (a rectangle, a circle) rather
 * than drawn as a sketch with relations: only its sizes change, in the panel.
 */
export function notASketch(title) {
  return `${title} isn't an editable sketch yet: it's built from fixed shapes, so only its sizes change, in the panel.`;
}

/** The job that redraws such a profile as a sketch the person can edit, for the chat. */
export function redrawJob(sketch) {
  const where = sketch.file ? ` (${sketch.file}${sketch.line ? `, line ${sketch.line}` : ""})` : "";
  return `Redraw ${sketch.title}${where} as an editable sketch with cadgen.sketch, keeping its shape and sizes, so I can edit it by hand.`;
}

export function changeNote(change) {
  const name = sizeName(change.name);
  const said = name === change.name ? name : `${name} (${change.name})`;
  return `In edit mode I changed ${said} from ${change.from} to ${change.to} (${change.file}, line ${change.line}).`;
}

const SKETCH_PROMPT = "Select a sketch on the model or in the design tree.";
const SWEEP_PROMPT = "Select the profile sketch, then the path sketch, on the model or in the design tree.";
const LOFT_PROMPT = "Select the profile sketches on the model or in the design tree, in the order the loft goes through them.";

/**
 * The ribbon's modeling commands, as SolidWorks' Features tab sets them out: the bosses a sketch
 * makes (Extruded, Revolved, Swept and Lofted Boss/Base), the cuts (the same four, and Hole), and
 * what changes the body (Fillet, Chamfer, Rib, Draft, Shell, Pattern, Mirror), and the reference
 * geometry a sketch goes on (Plane). `picks` is what the
 * command acts on, which the Select tool's mode turns to when it opens: edges, faces, or none
 * (Pattern copies a history feature). `sketch`: it takes one sketch, selected in the design tree
 * or on the model; `sketches`: it takes several, a sweep its profile then its path, a loft its
 * profiles in order (`"many"`). `many`: its box takes as many faces or edges as are clicked, each
 * click on the model adding one or taking a picked one out, as a PropertyManager's selection box does.
 */
export const EDIT_COMMANDS = Object.freeze([
  { id: "extrude", label: "Extruded Boss/Base", group: "Boss/Base", picks: null, sketch: true, prompt: SKETCH_PROMPT },
  { id: "revolve", label: "Revolved Boss/Base", group: "Boss/Base", picks: null, sketch: true, prompt: SKETCH_PROMPT },
  { id: "sweep", label: "Swept Boss/Base", group: "Boss/Base", picks: null, sketches: ["profile", "path"], prompt: SWEEP_PROMPT },
  { id: "loft", label: "Lofted Boss/Base", group: "Boss/Base", picks: null, sketches: "many", prompt: LOFT_PROMPT },
  { id: "cut", label: "Extruded Cut", group: "Cut", picks: null, sketch: true, prompt: SKETCH_PROMPT },
  { id: "revolve_cut", label: "Revolved Cut", group: "Cut", picks: null, sketch: true, prompt: SKETCH_PROMPT },
  { id: "sweep_cut", label: "Swept Cut", group: "Cut", picks: null, sketches: ["profile", "path"], prompt: SWEEP_PROMPT },
  { id: "loft_cut", label: "Lofted Cut", group: "Cut", picks: null, sketches: "many", prompt: LOFT_PROMPT },
  { id: "hole", label: "Hole", group: "Cut", picks: "faces", prompt: "Click a flat face where the hole goes." },
  { id: "fillet", label: "Fillet", group: "Modify", picks: "edges", many: true, prompt: "Click edges on the model to add them. Click one again to take it out." },
  { id: "chamfer", label: "Chamfer", group: "Modify", picks: "edges", many: true, prompt: "Click edges on the model to add them. Click one again to take it out." },
  { id: "rib", label: "Rib", group: "Modify", picks: null, sketch: true, prompt: "Select a sketch of the rib's line on the model or in the design tree." },
  { id: "draft", label: "Draft", group: "Modify", picks: "faces", many: true, prompt: "Click the faces to draft. Click one again to take it out." },
  { id: "shell", label: "Shell", group: "Modify", picks: "faces", many: true, prompt: "Click faces on the model to add them. Click one again to take it out." },
  // Direct editing, as NX's Synchronous Modeling: faces changed where they are, on any body, an imported one (no history) included.
  { id: "offset_face", label: "Offset Face", group: "Modify", picks: "faces", many: true, prompt: "Click faces on the model to add them. Click one again to take it out." },
  { id: "delete_face", label: "Delete Face", group: "Modify", picks: "faces", many: true, prompt: "Click faces on the model to add them. Click one again to take it out." },
  { id: "pattern", label: "Pattern", group: "Modify", picks: null, prompt: "" },
  { id: "mirror", label: "Mirror", group: "Modify", picks: "faces", prompt: "Select a flat face to mirror about, or pick a plane." },
  { id: "split", label: "Split", group: "Modify", picks: "faces", prompt: "Pick the plane to split the body with, or select a flat face on the model." },
  { id: "delete_body", label: "Delete/Keep Body", group: "Modify", picks: "faces", prompt: "Click a face of the body to delete, or to keep." },
  { id: "plane", label: "Plane", group: "Reference", picks: "all",
    prompt: "Select a flat face or a plane in the design tree to offset from, two parallel faces for a Mid Plane, or an edge for a plane normal to it." },
]);

/** The ribbon's groups of modeling commands, in its order. */
export const COMMAND_GROUPS = Object.freeze(["Boss/Base", "Cut", "Modify", "Reference"]);

export const editCommand = id => EDIT_COMMANDS.find(command => command.id === id) || null;

/** A command's inputs as it opens, in the part's units: what the panel shows before anything is typed. */
export function commandDefaults(id, units) {
  const size = DEFAULTS[units] || DEFAULTS.mm;
  switch (id) {
    case "fillet": return { radius: size.radius };
    // Chamfer's types: one distance both ways, a distance each way, or a distance and an angle.
    case "chamfer": return { type: "equal", distance: size.distance, distance2: size.distance, angle: "45", flip: false };
    case "hole": {
      // Hole Wizard's: a screw of the part's standard, its size and fit filling the sizes, which stay the engineer's to type over.
      const standard = defaultStandard(units);
      const sized = { type: "simple", standard, size: defaultSize(standard), fit: "normal" };
      // Blind by default, as SolidWorks' Hole Wizard opens.
      return { ...sized, diameter: size.diameter, depth: size.depth, through: false, x: "0", y: "0", z: "0", more: [],
        cbore_diameter: size.cbore, cbore_depth: size.cboreDepth, csk_diameter: size.csk, csk_angle: size.cskAngle, ...holeFill(sized, units) };
    }
    case "shell": return { thickness: size.thickness, outward: false };
    case "offset_face": return { distance: size.distance, reverse: false };
    // A draft's neutral plane is picked: an origin plane's name, or "face" for a face of the part.
    case "draft": return { angle: size.draft, neutral: "", reverse: false };
    // A plane's first reference is picked: an origin plane's name, or a face of the part.
    case "plane": return { reference: "", distance: size.depth, flip: false, angle: "0", about: "x", end: "start" };
    case "mirror": return { plane: "YZ" };
    case "split": return { plane: "YZ", keep: "both" };
    case "delete_body": return { mode: "delete" };
    case "pattern": return { type: "linear", direction: "X", spacing: size.spacing, count: "3", reverse: false,
      direction2: false, spacing2: size.spacing, count2: "2", reverse2: false, angle: "360" };
    case "extrude":
    case "cut": return { end: "blind", depth: size.depth, reverse: false, draft: false, draft_angle: size.draft, outward: false,
      thin: false, thin_thickness: size.thickness, thin_side: "inside", direction2: false, end2: "blind", depth2: size.depth, draft2: false,
      draft_angle2: size.draft, outward2: false };
    case "rib": return { thickness: size.thickness, flip: false };
    case "revolve":
    case "revolve_cut": return { axis: "", angle: "360", reverse: false, end: "blind", direction2: false, angle2: "30" };
    default: return {};
  }
}

/**
 * What the viewer's selection is to a command: each face or edge by its selector (the engine's ref to
 * it by number, `selectors.js`), with what the viewer read of it (its kind, centre, and area or length),
 * so `cadgen/edit` finds it on the part as its script makes it now.
 */
export function selectionItems(references = []) {
  return references.filter(reference => reference?.selectorType === "face" || reference?.selectorType === "edge").map(reference => {
    const pick = reference.pickData || {};
    const face = reference.selectorType === "face";
    const center = pick.center && pick.center.length === 3 ? Array.from(pick.center, Number) : null;
    const size = Number(face ? pick.area : pick.length);
    return {
      selector: String(reference.displaySelector || reference.normalizedSelector || ""),
      type: String((face ? pick.surfaceType : pick.curveType) || ""),
      ...(center ? { center } : {}),
      ...(Number.isFinite(size) ? { size } : {}),
    };
  });
}

/** A selected face or edge as the panel lists it: "Edge 12", "Face 4". */
export function selectionLabel(item) {
  const element = elementOf(item?.selector);
  if ((element?.kind !== "face" && element?.kind !== "edge") || element.ordinal === null) return String(item?.selector || "");
  return `${element.kind === "face" ? "Face" : "Edge"} ${element.ordinal}`;
}

/**
 * The axes a hole moves along on a flat face: the two that lie in it, when its normal runs along
 * the third; all three on a slanted face (the server keeps the place on the face's plane).
 */
export function faceOffsetAxes(normal) {
  if (!normal || normal.length !== 3) return [];
  const [x, y, z] = Array.from(normal, value => Math.abs(Number(value)));
  if (Math.abs(z - 1) < 1e-6) return ["x", "y"];
  if (Math.abs(x - 1) < 1e-6) return ["y", "z"];
  if (Math.abs(y - 1) < 1e-6) return ["x", "z"];
  return ["x", "y", "z"];
}

/**
 * The axis a straight edge picked on the model runs along, as a linear pattern's Direction takes
 * an edge: "X", "Y" or "Z" from the edge's extent (`pickData.bbox`), the last one picked counting.
 * Null for an edge along another way, a curved one, or none.
 */
export function edgeAxis(references = []) {
  const edge = [...references].reverse().find(reference => reference?.selectorType === "edge" && reference.pickData?.curveType === "line");
  const { min, max } = edge?.pickData?.bbox || {};
  if (!Array.isArray(min) || !Array.isArray(max)) return null;
  const extent = [0, 1, 2].map(axis => Math.abs(Number(max[axis]) - Number(min[axis])));
  const longest = Math.max(...extent);
  const along = extent.indexOf(longest);
  if (!(longest > 0) || extent.some((value, axis) => axis !== along && value > 1e-6 * longest)) return null;
  return "XYZ"[along];
}

/**
 * What an extrude Up To Surface or Up To Vertex ends on, of the selection's items: the last flat
 * face picked, or the last edge (whose end nearest the click is the vertex). Null for none.
 */
export function extrudeEnd(end, items = []) {
  const wanted = end === "surface" ? item => isFaceItem(item) && item.type === "plane"
    : end === "vertex" ? item => isEdgeItem(item) : null;
  return wanted ? [...items].reverse().find(wanted) || null : null;
}

/**
 * What a circular pattern turns about, picked on the model as SolidWorks' Circular Pattern takes
 * its axis: of the selection's items (`selectionItems`), the last round face (its axis) or
 * straight edge picked. Null for none, when it turns about the Z axis through the origin.
 */
export function patternAxis(items = []) {
  return [...items].reverse().find(item => (isFaceItem(item) && (item.type === "cylinder" || item.type === "cone"))
    || (isEdgeItem(item) && item.type === "line")) || null;
}

/**
 * Where a click on a face puts a hole, as Hole Wizard's Positions place it where the face is
 * clicked: the click's distance from the face's center (`pickData.center`, the point the hole's
 * `Plane(face)` starts from) along each axis the panel moves it on, in the part's units and to
 * the places the panel shows. Null without a click or a center.
 */
export function clickOffsets(point, center, normal, units) {
  if (!point || !center) return null;
  const scale = units === "in" ? 1 / 25.4 : 1;
  const places = units === "in" ? 3 : 2;
  const axes = faceOffsetAxes(normal);
  if (!axes.length) return null;
  return Object.fromEntries(axes.map(axis => {
    const index = "xyz".indexOf(axis);
    return [axis, String(Number(((point[index] - center[index]) * scale).toFixed(places)))];
  }));
}

/**
 * The request a command's OK sends (`cadgen/edit`): the command, its selection, its inputs as
 * typed and, for Mirror and Pattern, the history feature they copy (none copies the body).
 */
/**
 * Which Plane a selection makes, as SolidWorks' Plane reads its references: two faces a Mid Plane,
 * an edge a plane Normal to Curve, else an offset (from one face, or a plane in the tree). Edit
 * Feature keeps its plane's own until something else is picked.
 */
export function planeMode(items, editing = null) {
  const faces = items.filter(item => isFaceItem(item)).length;
  const edges = items.filter(item => isEdgeItem(item)).length;
  if (faces === 2) return "mid";
  if (edges === 1 && !faces) return "normal";
  if (!faces && !edges && ["mid", "normal"].includes(editing?.values?.mode)) return editing.values.mode;
  return "offset";
}

export function commandRequest(id, values, items, feature, sketch = null, editing = null, sketches = []) {
  // Edit Feature: the feature's own line written again, acting on what it acts on now.
  const replace = editing ? { replace: { row: editing.id } } : {};
  const named = each => ({ file: each.file, line: each.line, name: each.title || each.name });
  // A sweep's profile and path, a loft's profiles, in the order they were picked.
  if (editCommand(id)?.sketches) return { command: id, sketches: sketches.filter(Boolean).map(named), inputs: {}, ...replace };
  if (id === "rib") {
    return { command: id, sketch: sketch ? named(sketch) : null, inputs: { thickness: values.thickness, flip: Boolean(values.flip) }, ...replace };
  }
  if (id === "extrude" || id === "cut") {
    // Up To Next has no depth or direction of its own, nor a draft; Through All no depth; Up To
    // Surface and Up To Vertex end on what is picked, a vertex by where its edge was clicked.
    const next = values.end === "next";
    const upTo = values.end === "surface" || values.end === "vertex";
    const inputs = { end: values.end, ...(values.end === "through" || next || upTo ? {} : { depth: values.depth }),
      ...(next || upTo ? {} : { reverse: Boolean(values.reverse) }) };
    if (values.draft && !next) Object.assign(inputs, { draft: true, draft_angle: values.draft_angle, outward: Boolean(values.outward) });
    // Thin Feature: the outline as a wall, inside it unless said otherwise.
    if (values.thin) {
      Object.assign(inputs, { thin: true, thin_thickness: values.thin_thickness, ...(values.thin_side && values.thin_side !== "inside"
        ? { thin_side: values.thin_side } : {}) });
    }
    // Direction 2, the other way: Blind or Through All, its own draft; not at Mid Plane.
    if (values.direction2 && values.end !== "mid") {
      const through2 = id === "cut" && values.end2 === "through";
      Object.assign(inputs, { direction2: true, end2: through2 ? "through" : "blind", ...(through2 ? {} : { depth2: values.depth2 }) });
      if (values.draft2) Object.assign(inputs, { draft2: true, draft_angle2: values.draft_angle2, outward2: Boolean(values.outward2) });
    }
    const ending = upTo ? extrudeEnd(values.end, items) : null;
    if (ending && values.end === "vertex" && values.vertex_at) inputs.vertex_at = values.vertex_at;
    return { command: id, sketch: sketch ? { file: sketch.file, line: sketch.line, name: sketch.title } : null, inputs,
      ...(ending ? { selection: [ending] } : {}), ...replace };
  }
  if (id === "revolve" || id === "revolve_cut") {
    return { command: id, sketch: sketch ? { file: sketch.file, line: sketch.line, name: sketch.title, axis: values.axis } : null,
      inputs: { angle: values.angle, ...(values.end === "mid" ? { end: "mid" } : { reverse: Boolean(values.reverse),
        ...(values.direction2 ? { direction2: true, angle2: values.angle2 } : {}) }) }, ...replace };
  }
  if (id === "plane") {
    // Mid Plane between two faces, or Normal to Curve at an edge, as what is picked says (Edit Feature keeps its own).
    const mode = planeMode(items, editing);
    if (mode === "mid" || mode === "normal") {
      const wanted = items.filter(item => (mode === "mid" ? isFaceItem(item) : isEdgeItem(item)));
      return { command: id, selection: wanted, inputs: { mode, ...(mode === "normal" ? { end: values.end === "end" ? "end" : "start" } : {}) }, ...replace };
    }
    // Offset from a face picked on the model, else from the origin plane picked in the tree.
    const face = items.find(item => isFaceItem(item)) || null;
    // At angle: turned about its own X or Y axis.
    const turned = turnedAngle(values.angle) ? { angle: String(values.angle).trim(), about: values.about === "y" ? "y" : "x" } : {};
    return { command: id, selection: face ? [face] : [], inputs: { reference: face ? "face" : values.reference || "", distance: values.distance,
      flip: Boolean(values.flip), ...turned }, ...replace };
  }
  if (id === "draft") {
    // The neutral plane: an origin plane by its name, or a face picked on the model (marked `neutral` among the items).
    const neutral = items.find(item => item.neutral) || null;
    const faces = items.filter(item => !item.neutral && isFaceItem(item));
    const { neutral: _marked, ...face } = neutral || {};
    return { command: id, selection: faces, inputs: { angle: values.angle, neutral: neutral ? "face" : values.neutral || "", reverse: Boolean(values.reverse) },
      ...(neutral ? { neutral: face } : {}), ...replace };
  }
  const inputs = {};
  switch (id) {
    case "fillet": inputs.radius = values.radius; break;
    case "chamfer":
      inputs.distance = values.distance;
      if (values.type === "distances") Object.assign(inputs, { type: "distances", distance2: values.distance2, flip: Boolean(values.flip) });
      if (values.type === "angle") Object.assign(inputs, { type: "angle", angle: values.angle, ...(values.flip ? { flip: true } : {}) });
      break;
    case "shell": inputs.thickness = values.thickness; if (values.outward) inputs.outward = true; break;
    case "offset_face": Object.assign(inputs, { distance: values.distance, reverse: Boolean(values.reverse) }); break;
    case "hole":
      Object.assign(inputs, { diameter: values.diameter, depth: values.through ? "" : values.depth });
      for (const axis of ["x", "y", "z"]) if (String(values[axis] ?? "").trim() && Number(values[axis]) !== 0) inputs[axis] = values[axis];
      if (values.type === "counterbore") Object.assign(inputs, { type: "counterbore", cbore_diameter: values.cbore_diameter, cbore_depth: values.cbore_depth });
      if (values.type === "countersink") Object.assign(inputs, { type: "countersink", csk_diameter: values.csk_diameter, csk_angle: values.csk_angle });
      if (values.type === "tapped") inputs.type = "tapped";
      // A hole of a standard's size says so beside its line: "M3 clearance hole, normal fit".
      if (holeCallout(values)) inputs.callout = holeCallout(values);
      // Hole Wizard's other positions: the same hole at each, by its place on the face.
      if (values.more?.length) {
        inputs.more = values.more.map(place => Object.fromEntries(["x", "y", "z"].filter(axis => String(place[axis] ?? "").trim())
          .map(axis => [axis, String(place[axis]).trim()])));
      }
      break;
    case "mirror": inputs.plane = values.plane; break;
    // Split by a flat face picked on the model, else the plane picked in the panel.
    case "split": Object.assign(inputs, { plane: items.some(item => isFaceItem(item)) ? "face" : values.plane, keep: values.keep }); break;
    case "delete_body": inputs.mode = values.mode === "keep" ? "keep" : "delete"; break;
    case "pattern": {
      Object.assign(inputs, { type: values.type, count: values.count });
      if (values.type === "linear") {
        const spacing = String(values.spacing ?? "").trim();
        Object.assign(inputs, { direction: values.direction, spacing: values.reverse ? `-(${spacing})` : spacing });
        // Direction 2: a grid, along the other of X and Y.
        if (values.direction2 && (values.direction === "X" || values.direction === "Y")) {
          const spacing2 = String(values.spacing2 ?? "").trim();
          Object.assign(inputs, { direction2: true, spacing2: values.reverse2 ? `-(${spacing2})` : spacing2, count2: values.count2 });
        }
      }
      // A circular pattern's Angle, its instances spread over it, and which way round.
      const spread = String(values.angle ?? "").trim();
      if (values.type === "circular" && ((spread && Number(spread) !== 360) || values.reverse)) {
        Object.assign(inputs, { angle: spread || "360", ...(values.reverse ? { reverse: true } : {}) });
      }
      // A circular pattern's axis, picked on the model; Edit Feature keeps its own unless one is.
      const axis = values.type === "circular" ? patternAxis(items) : null;
      if (editing) return { command: id, selection: axis ? [axis] : [], inputs, ...replace };
      return { command: id, selection: axis ? [axis] : [], inputs, ...(feature?.row ? { feature } : {}) };
    }
    default: break;
  }
  const picks = editCommand(id)?.picks;
  const selection = picks === "edges" ? items : picks === "faces" ? items.filter(item => isFaceItem(item)) : [];
  // Edit Feature keeps what the feature acts on, unless edges or faces were picked again.
  if (editing) return { command: id, selection: REPICKS.has(id) ? selection : [], inputs, ...replace };
  return { command: id, selection, inputs, ...(feature?.row && (id === "mirror" || id === "pattern") ? { feature } : {}) };
}

/** A feature's panel as Edit Feature opens it: the command's inputs, set to the feature's values. */
export function editingValues(editing, units) {
  const opened = { ...commandDefaults(editing.command, units), ...editing.values };
  // A hole reopens as the size its callout names, else Custom: its own sizes, as written.
  return editing.command === "hole" ? { ...opened, size: "", ...calloutValues(editing.values?.callout) } : opened;
}

/** Whether a panel's values are still the ones it opened with, so its OK has nothing to write. */
export const sameValues = (values, opened) => Object.keys({ ...values, ...opened })
  .every(key => valueText(values[key]) === valueText(opened[key]));
// A value as the panel compares it: a list (a hole's other places) by what it holds.
const valueText = value => (value !== null && typeof value === "object" ? JSON.stringify(value) : String(value ?? "").trim());

/** Why a command's OK cannot go yet, or "" when it can. Edit Feature keeps what the feature acts on, so it waits on nothing picked. */
export function commandBlocked(id, items, sketch = null, values = {}, editing = null, sketches = []) {
  const takes = editCommand(id)?.sketches;
  if (takes) {
    if (editing) return "";
    const drawn = sketches.find(each => each && !each.constrained);
    if (drawn) return `${drawn.title} isn't an editable sketch yet. Ask the agent to ${id.startsWith("loft") ? "loft" : "sweep"} it.`;
    if (takes === "many") return sketches.length >= 2 ? "" : sketches.length ? "Select the next profile sketch." : "Select the first profile sketch.";
    // A sweep's two boxes, each its own: the profile, then the path.
    return !sketches[0] ? "Select the profile sketch." : !sketches[1] ? "Select the path sketch." : "";
  }
  if (id === "rib") {
    if (!sketch) return "Select a sketch of the rib's line.";
    return sketch.constrained ? "" : `${sketch.title} isn't an editable sketch yet. Ask the agent to make the rib.`;
  }
  if (id === "extrude" || id === "cut" || id === "revolve" || id === "revolve_cut") {
    if (!sketch) return "Select a sketch in the design tree.";
    const making = id.startsWith("revolve") ? "revolve" : "extrude";
    if (!sketch.constrained) return `${sketch.title} isn't an editable sketch yet. Ask the agent to ${making} it.`;
    if (making === "revolve" && !values.axis) return `Draw a centerline in ${sketch.title} to revolve about.`;
    // Up To Surface and Up To Vertex wait for what they end on; Edit Feature keeps its own.
    const keeps = editing && editing.values?.end === values.end;
    if (values.end === "surface" && !keeps && !extrudeEnd("surface", items)) return "Select a flat face on the model to end on.";
    if (values.end === "vertex" && !keeps && !(extrudeEnd("vertex", items) && values.vertex_at)) return "Click near the end of an edge on the model.";
    return "";
  }
  if (id === "plane") {
    const faces = items.filter(item => isFaceItem(item));
    const edges = items.filter(item => isEdgeItem(item));
    if (faces.length > 2) return "Select one face, or two for a Mid Plane.";
    if (edges.length > 1 || (edges.length && faces.length)) return "Select one edge for a plane normal to it, or faces.";
    if (faces.length === 2 || edges.length === 1 || ["mid", "normal"].includes(editing?.values?.mode)) return "";
    return editing || faces.length || values.reference ? "" : "Select a plane in the design tree, or a flat face on the model.";
  }
  if (id === "draft") {
    if (!editing && !items.some(item => !item.neutral && isFaceItem(item))) return "Select the faces to draft.";
    return values.neutral || items.some(item => item.neutral) ? "" : "Select the neutral plane: a flat face on the model, or a plane in the design tree.";
  }
  const faces = items.filter(item => isFaceItem(item));
  // Edit Feature keeps what the feature acts on: it waits only on a hole picked onto two faces.
  if (editing) return id === "hole" && faces.length > 1 ? "Select one face." : "";
  if (id === "fillet" || id === "chamfer") return items.length ? "" : "Select edges on the model.";
  if (id === "hole") return faces.length === 1 ? "" : faces.length ? "Select one face." : "Select a flat face on the model.";
  if (id === "shell") return faces.length ? "" : "Select the faces to open.";
  if (id === "offset_face") return faces.length ? "" : "Select the faces to offset.";
  if (id === "delete_face") return faces.length ? "" : "Select the faces to delete.";
  if (id === "mirror") return faces.length > 1 ? "Select one face, or none to pick a plane." : "";
  if (id === "split") return faces.length > 1 ? "Select one face, or none to pick a plane." : "";
  if (id === "delete_body") return faces.length === 1 ? "" : faces.length ? "Select one face of the body." : "Click a face of the body.";
  return "";
}

/**
 * Choose: what a command's panel asks to be picked, in order, as a CAD tool's selection boxes walk
 * through them, each named as its step reads ("1 of 2: Select a sketch") and whether it has what it
 * needs. `listed` is the faces or edges the panel lists for it, `ending` what an extrude Up To
 * Surface or Up To Vertex ends on, and `kept` whether a reopened feature keeps what it acts on.
 * Mirror and Pattern have what they need as they open (a plane, a direction, the whole body).
 */
export function chooseSteps(id, { listed = [], sketch = null, values = {}, ending = null, kept = false, sketches = [] } = {}) {
  const takes = editCommand(id)?.sketches;
  if (takes === "many") {
    return [{ input: "the first profile sketch", done: sketches.length >= 1 || kept }, { input: "the next profile sketch", done: sketches.length >= 2 || kept }];
  }
  if (takes) return [{ input: "the profile sketch", done: Boolean(sketches[0]) || kept }, { input: "the path sketch", done: Boolean(sketches[1]) || kept }];
  if (id === "rib") return [{ input: "a sketch of the rib's line", done: Boolean(sketch) }];
  if (editCommand(id)?.sketch) {
    const steps = [{ input: "a sketch", done: Boolean(sketch) }];
    if (id === "revolve" || id === "revolve_cut") steps.push({ input: "a centerline to revolve about", done: Boolean(values.axis) });
    else if (values.end === "surface") steps.push({ input: "a flat face to end on", done: Boolean(ending) || kept });
    else if (values.end === "vertex") steps.push({ input: "a vertex to end at", done: Boolean(ending && values.vertex_at) || kept });
    return steps;
  }
  switch (id) {
    case "fillet": return [{ input: "edges to round", done: listed.length > 0 || kept }];
    case "chamfer": return [{ input: "edges to bevel", done: listed.length > 0 || kept }];
    case "shell": return [{ input: "faces to open", done: listed.length > 0 || kept }];
    case "offset_face": return [{ input: "faces to offset", done: listed.length > 0 || kept }];
    case "delete_face": return [{ input: "faces to delete", done: listed.length > 0 || kept }];
    // As SolidWorks' Draft walks through its boxes: the neutral plane, then the faces it tilts.
    case "draft": return [{ input: "the neutral plane", done: Boolean(values.neutral) }, { input: "faces to draft", done: listed.length > 0 || kept }];
    case "plane": return [{ input: "a plane or a flat face to offset from", done: Boolean(values.reference) || listed.length > 0 || kept }];
    case "hole": return [{ input: "a flat face for the hole", done: listed.length === 1 || (kept && !listed.length) }];
    default: return [];
  }
}

/** The step a panel's line names: the first still waiting for its pick, "2 of 2: Select a flat face to end on"; null once each has it. */
export function chooseLine(steps) {
  const at = steps.findIndex(step => !step.done);
  return at < 0 ? null : `${at + 1} of ${steps.length}: Select ${steps[at].input}`;
}

/**
 * How a revolve's preview turns, in degrees: `angle` from `from`. Mid Plane starts half its angle
 * back; Direction 2 its second angle back; Reverse turns both the other way.
 */
export function revolveSweep(values, angle) {
  if (values.end === "mid") return { from: -angle / 2, angle };
  const back = values.direction2 ? Math.max(0, Number(values.angle2) || 0) : 0;
  const sign = values.reverse ? -1 : 1;
  return { from: -sign * back, angle: sign * (angle + back) };
}

/** The lines of a sketch a revolve can turn about, its centerlines first, as the panel lists them. */
export function revolveAxes(view) {
  const lines = (view?.state?.curves || []).filter(curve => curve.kind === "line");
  return [...lines.filter(line => line.construction), ...lines.filter(line => !line.construction)]
    .map(line => ({ value: line.id, label: line.construction ? `${line.id}, centerline` : line.id }));
}

/**
 * What a command tells the agent: "In edit mode I added Fillet2, radius 0.02 in, 4 edges
 * (parts/tray.py, line 37)."; Edit Feature's: "In edit mode I changed Fillet2 to radius 0.03 in, ...".
 */
export function commandNote(change, title) {
  const said = [...(change.inputs || []).map(input => `${input.label.toLowerCase()} ${withUnit(input.display, input.unit)}`),
    change.what].filter(Boolean);
  const name = title || change.feature;
  if (change.edited) return `In edit mode I changed ${name}${said.length ? ` to ${said.join(", ")}` : ""} (${change.file}, line ${change.line}).`;
  return `In edit mode I added ${name}${said.length ? `, ${said.join(", ")}` : ""} (${change.file}, line ${change.line}).`;
}

/** What Undo or Redo of a command tells the agent. */
export function commandUndoNote(change, title, redo) {
  const name = title || change.feature;
  if (change.edited) return `In edit mode I ${redo ? `changed ${name} again` : `put ${name} back as it was`} (${change.file}, line ${change.line}).`;
  return `In edit mode I ${redo ? "added" : "removed"} ${name}${redo ? " again" : ""} (${change.file}, line ${change.line}).`;
}

// Names in a sentence: "Fillet1", "Fillet1 and Cut-Extrude1", "Fillet1, Hole1 and Shell1".
const listWords = names => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0] || "");

/** What Delete of a feature tells the agent, and what its Undo and Redo do. */
export function deleteNote(change, { undo = false, redo = false } = {}) {
  const done = undo ? "put back" : redo ? "deleted again" : "deleted";
  // Its child features, by the titles Confirm Delete named them with.
  const children = change.children || [];
  const with_ = children.length ? ` and its child feature${children.length > 1 ? "s" : ""} ${listWords(children)}` : "";
  return `In edit mode I ${done} ${change.title}${with_} (${change.file}, line ${change.line}).`;
}

/**
 * Why a feature was not deleted (or suppressed, `verb`), said as the features of the tree that
 * still use what it makes ("Boss-Extrude1 is used by Fillet1. Delete it first, or ask the agent.");
 * the server's own words when it names none.
 */
export function deleteRefusal(reply, tree, title, verb = "Delete") {
  const dependents = reply?.dependents;
  const rows = new Set((dependents?.lines || []).map(line => `${dependents.file}:${line}`));
  const users = treeFeatures(tree).filter(feature => feature.rows.some(row => rows.has(row))).map(feature => feature.title);
  if (!users.length) return reply?.error || `${title} could not be ${verb === "Delete" ? "deleted" : "suppressed"}.`;
  return `${title} is used by ${listWords(users)}. ${verb} ${users.length > 1 ? "them" : "it"} first, or ask the agent.`;
}

/** What a feature dragged to another place in the design tree tells the agent, and its Undo and Redo. */
export function reorderNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  if (undo) return `In edit mode I put ${change.title} back where it was in the design tree ${where}.`;
  return `In edit mode I moved ${change.title}${change.place ? ` ${change.place}` : ""}${redo ? " again" : ""} in the design tree ${where}.`;
}

/** What Suppress or Unsuppress of a feature tells the agent, and what its Undo and Redo do. */
/** A reference plane's offset, as the design tree says it beside its name: "Top Plane, 10 mm", "Face, -4 mm". */
export function planeDetail(feature, units) {
  const values = feature?.edit?.values;
  if (!values?.reference) return "";
  const from = values.reference === "face" ? "Face" : `${values.reference} Plane`;
  const turned = turnedAngle(values.angle) ? `, ${values.angle}° about ${values.about === "y" ? "Y" : "X"}` : "";
  return `${from}, ${values.flip ? "-" : ""}${withUnit(values.distance, units)}${turned}`;
}

/** What the agent is told of an Appearance: the part's new color, and where it is written. */
export function appearanceNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  if (undo) return `In edit mode I took back coloring the part ${change.color} ${where}.`;
  return `In edit mode I colored the part ${change.color}${redo ? " again" : ""} ${where}.`;
}

/** How long ago a time was (seconds since the epoch), as a version list says it: "just now", "4 min ago", "2 h ago". */
export function timeAgo(time, now = Date.now() / 1000) {
  const seconds = Math.max(0, now - time);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

/** A volume a comparison found, in the part's units cubed: "4.29 mm³", "0.26 in³"; a dash when it could not be worked out. */
export function compareVolume(volume, units = "mm") {
  if (typeof volume !== "number" || !Number.isFinite(volume)) return "-";
  const inches = units === "in";
  const value = inches ? volume / 25.4 ** 3 : volume;
  return `${Number(value.toFixed(inches ? 4 : 2))} ${inches ? "in" : "mm"}³`;
}

/** What the agent is told of Make Drawing or a change to the drawing's sheet: what was done, and the PDF it wrote. */
export function drawingNote(change) {
  return `In edit mode I ${change.words} (${change.file}); it wrote ${change.pdf}.`;
}

/** What the agent is told of a Mate: what it did, or the mate taken out, and where (`cadgen/edit/mates.py`). */
export function mateNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  // Insert Components: a part added to the assembly.
  if (change.insert) return undo ? `In edit mode I took ${change.insert} back out of the assembly ${where}.`
    : `In edit mode I ${redo ? "inserted again" : "inserted"} ${change.insert} into the assembly ${where}.`;
  if (undo) return `In edit mode I took back a mate of the assembly ${where}: ${change.words}.`;
  return `In edit mode I ${redo ? "made again" : "made"} a mate of the assembly ${where}: ${change.words}.`;
}

/** What the agent is told of a Rename: the feature or sketch, its name before and after, and where. */
/** What the agent is told of a parameter added in edit mode, or taken back. */
/** What Edit Material tells the agent: the part's material set, taken out, or its Undo and Redo. */
export function materialNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  if (undo) return `In edit mode I took back changing the part's material ${where}.`;
  return change.material ? `In edit mode I set the part's material to ${change.material}${redo ? " again" : ""} ${where}.`
    : `In edit mode I took the part's material out${redo ? " again" : ""} ${where}.`;
}

/** What Edit Feature on a feature's sizes tells the agent (`said`: each size as typed), or its Undo and Redo. */
export function sizesNote(change, title, said = [], { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  const name = title || "a feature";
  if (undo) return `In edit mode I took back changing the sizes of ${name} ${where}.`;
  if (redo) return `In edit mode I changed the sizes of ${name} again ${where}.`;
  return `In edit mode I changed ${name}${said.length ? ` to ${said.join(", ")}` : ""} ${where}.`;
}

export function parameterNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  if (undo) return `In edit mode I took back adding the parameter ${change.name} ${where}.`;
  return `In edit mode I added the parameter ${change.name} = ${change.value}${redo ? " again" : ""} ${where}.`;
}

export function renameNote(change, { undo = false, redo = false } = {}) {
  const where = `(${change.file}, line ${change.line})`;
  if (undo) return `In edit mode I took back renaming ${change.title} ${where}.`;
  const done = change.name ? `renamed ${change.title} to ${change.name}` : `gave ${change.title} back the design tree's own name`;
  return `In edit mode I ${done}${redo ? " again" : ""} ${where}.`;
}

export function suppressNote(change, { undo = false, redo = false } = {}) {
  const on = undo ? !change.on : change.on;
  const children = change.children?.length && on ? ` with its child feature${change.children.length > 1 ? "s" : ""}` : "";
  const done = on ? `suppressed ${change.title}${children}${redo ? " again" : ""}: its lines are comments now`
    : `unsuppressed ${change.title}${redo ? " again" : ""}: its lines are back`;
  return `In edit mode I ${done} (${change.file}, line ${change.line}).`;
}

/** Where a build of the parts that use a change stands, in a line; empty when it is done. */
export function buildingText(building) {
  if (!building || !building.scripts?.length) return "";
  if (building.error) return "A part did not build";
  if (building.done < building.scripts.length) return `Building the parts, ${building.done} of ${building.scripts.length}`;
  return "";
}

/**
 * What edit mode is busy with, as a CAD tool's status bar says it while it rebuilds: the part being
 * read, the body at the rollback bar on its way, a change being made or a sketch solved, the parts
 * that use a change being built again (`progress`, 0 to 100, how many are done). Null when it is idle.
 */
export function busyState(edit) {
  if (edit.status === "reading") return { text: "Reading the part", progress: null };
  if (edit.rolling) return { text: "Rolling back", progress: null };
  if (edit.saving) return { text: edit.sketch ? "Solving" : "Rebuilding", progress: null };
  const building = edit.state?.building;
  if (building?.scripts?.length && !building.error && building.done < building.scripts.length) {
    return { text: buildingText(building), progress: Math.round((100 * building.done) / building.scripts.length) };
  }
  return null;
}

/** The hand changes of this view, for Undo and Redo. */
export const emptyHistory = () => ({ done: [], undone: [] });

/** A change made by hand: Undo may take it back, and nothing undone can be redone after it. */
export const recordChange = (history, change) => ({ done: [...history.done, change].slice(-HISTORY_LIMIT), undone: [] });

/**
 * How many of the history's changes came after `before` (a sketch session's: the change made last
 * before it began). Counted from that change, not a length, as the history keeps only its last
 * changes: once `before` has gone from it, every change left came after.
 */
export function changesSince(history, before) {
  const at = before ? history.done.lastIndexOf(before) : -1;
  return history.done.length - (at + 1);
}

// A change whose lines are put back as they were (a command's, a sketch's), rather than one number.
const spliced = change => Boolean(change.undo?.hunks);

/** Undo: the last change, and the request that takes it back: its number written back, or its lines put back. */
export function undoStep(history) {
  const change = history.done.at(-1);
  if (!change) return null;
  return { change, request: spliced(change) ? { splice: change.undo } : { literal: change.literal, text: change.from },
    next: { done: history.done.slice(0, -1), undone: [...history.undone, change] } };
}

/** Redo: the last change undone, and the request that makes it again. */
export function redoStep(history) {
  const change = history.undone.at(-1);
  if (!change) return null;
  return { change, request: spliced(change) ? { splice: change.redo } : { literal: change.literal, text: change.to },
    next: { done: [...history.done, change], undone: history.undone.slice(0, -1) } };
}

// ---- Draft Analysis ------------------------------------------------------------------------------

/** Draft Analysis' classes, in the server's order (0, 1, 2), with SolidWorks' colors. */
export const DRAFT_ORDER = Object.freeze(["positive", "negative", "needs"]);
export const DRAFT_CLASSES = Object.freeze({
  positive: { label: "Positive draft", css: "#22c55e", rgb: [0.133, 0.773, 0.369] },
  negative: { label: "Negative draft", css: "#ef4444", rgb: [0.937, 0.267, 0.267] },
  needs: { label: "Requires draft", css: "#eab308", rgb: [0.918, 0.702, 0.031] },
});
/** The directions of pull Draft Analysis offers: each origin plane's normal, as the part's own planes face. */
export const PULL_PLANES = Object.freeze([{ value: "Top", label: "Top Plane" }, { value: "Front", label: "Front Plane" }, { value: "Right", label: "Right Plane" }]);
const PULLS = Object.freeze({ Top: [0, 0, 1], Front: [0, -1, 0], Right: [1, 0, 0] });

/** The direction of pull Draft Analysis sends: its plane's normal, reversed when asked. */
export function pullOf(settings) {
  const pull = PULLS[settings?.plane] || PULLS.Top;
  return settings?.reverse ? pull.map(value => -value || 0) : [...pull];
}

/** Draft Analysis' legend: each class's area, in the part's units squared. */
export function draftRows(areas, units) {
  const scale = units === "in" ? 25.4 ** 2 : units === "cm" ? 100 : units === "m" ? 1e6 : 1;
  const unit = units === "in" ? "in²" : units === "cm" ? "cm²" : units === "m" ? "m²" : "mm²";
  return DRAFT_ORDER.map(key => ({ key, label: DRAFT_CLASSES[key].label, value: `${Number(((areas?.[key] || 0) / scale).toFixed(units === "in" ? 3 : 1))} ${unit}` }));
}

// ---- Interference Detection ------------------------------------------------------------------------

/** Interference Detection's results: each overlapping pair, and the volume they share in the part's units cubed. */
export function interferenceRows(pairs, units) {
  const scale = units === "in" ? 25.4 ** 3 : units === "cm" ? 1000 : units === "m" ? 1e9 : 1;
  const unit = units === "in" ? "in³" : units === "cm" ? "cm³" : units === "m" ? "m³" : "mm³";
  return (pairs || []).map((pair, index) => ({ key: `${index}:${pair.a}:${pair.b}`, label: `${pair.a} and ${pair.b}`,
    value: `${Number((pair.volume / scale).toPrecision(3))} ${unit}` }));
}
