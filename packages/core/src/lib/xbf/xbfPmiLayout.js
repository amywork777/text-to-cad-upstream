// Where an engine document's PMI is drawn in the model: for each annotation (`xbfPmi.js`), the
// point on its feature its leader starts from, where its label stands, and a distance's extension
// and dimension lines -- all in the scene's coordinates, made from the elements its references name
// (`xbfScene.js`'s `elementGeometry`: a face's surface and its nodes).
//
// Where the model's code placed it (`presentation`: an anchor on the feature and the label's offset
// from it) is where it is drawn; an annotation the code never placed is put beside its feature, out
// from the part, each of a face's turned a little from the last so two on one face stand apart. A
// placement says where a callout is drawn and nothing else: the feature it is about and every value
// it says are the document's, wherever it stands.
//
// A distance between two parallel faces is drawn as a drawing draws one: its text at the label, the
// dimension line through it square to the faces, from one face's plane to the other's, and the
// extension lines from the anchor on the first face and its foot on the second out to it. One the
// code never placed is anchored at the first face's edge, out from the part, so its extension lines
// are short.

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const length = a => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => { const l = length(a); return l > 1e-12 ? scale(a, 1 / l) : null; };
const mean = points => scale(points.reduce((sum, point) => add(sum, point), [0, 0, 0]), 1 / points.length);
// Any direction square to `n`: what a side is where nothing else says one.
const anyPerpendicular = n => unit(Math.abs(n[0]) < 0.9 ? cross(n, [1, 0, 0]) : cross(n, [0, 1, 0]));
// `v` turned by `angle` about the unit axis `n` (Rodrigues).
const turned = (v, n, angle) => add(add(scale(v, Math.cos(angle)), scale(cross(n, v), Math.sin(angle))), scale(n, dot(n, v) * (1 - Math.cos(angle))));
/** The part of `v` square to the unit `n`. */
const across = (v, n) => sub(v, scale(n, dot(v, n)));

// Each later annotation of a feature is turned this much about its normal from the one before.
const SPREAD = Math.PI / 4.5;
// How far out a label the code never placed stands: this share of the model's diagonal, at least the floor.
const REACH_SHARE = 0.18, REACH_MIN = 4;

const boxCentre = bounds => (bounds ? scale(add(bounds.min, bounds.max), 0.5) : [0, 0, 0]);
const boxDiagonal = bounds => (bounds ? length(sub(bounds.max, bounds.min)) : 0);
/** How far out from its feature a label the code never placed stands. */
export const pmiReach = bounds => Math.max(REACH_MIN, boxDiagonal(bounds) * REACH_SHARE);

/**
 * A point on a face to start a leader from: one of its own nodes, so it is on the face whatever its
 * shape (a plate's top round a hole has its middle in the hole). A flat face's is the node nearest
 * its nodes' middle; a cylinder's is on its rim at its axis's far end, the one farthest out from the
 * model's middle, so a hole's leader leaves its edge.
 *
 * @param {{ surface: object, points?: number[][] } | null} geometry  `elementGeometry(id, { points: true })`.
 * @param {number[]} [centre]  The model's middle.
 */
export function pmiFeaturePoint(geometry, centre = [0, 0, 0]) {
  const points = geometry?.points || [];
  if (!points.length) return geometry?.surface?.origin ? geometry.surface.origin.slice() : null;
  const surface = geometry.surface || {};
  if (surface.type === "cylinder" && surface.axis) {
    const far = Math.max(...points.map(point => dot(point, surface.axis)));
    const rim = points.filter(point => dot(point, surface.axis) > far - 1e-6 * Math.max(1, Math.abs(far)));
    return rim.reduce((best, point) => (length(sub(point, centre)) > length(sub(best, centre)) + 1e-9 ? point : best), rim[0]).slice();
  }
  const middle = mean(points);
  return points.reduce((best, point) => (length(sub(point, middle)) < length(sub(best, middle)) - 1e-9 ? point : best), points[0]).slice();
}

/**
 * A point at a flat face's edge, the node of it farthest out from the model's middle across `n`:
 * where a distance the code never placed has its anchor, so its extension lines run out from the
 * part's side rather than across it.
 */
function edgePoint(geometry, centre, n) {
  const points = geometry?.points || [];
  if (!points.length) return geometry?.surface?.origin ? geometry.surface.origin.slice() : null;
  const out = point => length(across(sub(point, centre), n));
  return points.reduce((best, point) => (out(point) > out(best) + 1e-9 ? point : best), points[0]).slice();
}

/** The direction a face's callouts go out along: a flat face's normal, a cylinder's axis. */
function outward(geometry) {
  const surface = geometry?.surface || {};
  if (surface.type === "plane" && surface.normal) return unit(surface.normal);
  if (surface.type === "cylinder" && surface.axis) return unit(surface.axis);
  return null;
}

/**
 * Where an annotation the code never placed stands: out from its feature along the feature's
 * direction (`out`) and away from the model's middle across it, turned `turn` steps about it.
 */
function defaultOffset({ anchor, out, centre, reach, turn }) {
  const away = unit(across(sub(anchor, centre), out)) || anyPerpendicular(out);
  const side = turned(away, out, turn * SPREAD);
  return add(scale(out, reach), scale(side, reach * 0.6));
}

/**
 * What an annotation is drawn as, in the scene's coordinates, or null where it cannot be: a
 * reference that names no element on the page and no placement to stand at.
 *
 * - `anchor`: where its leader starts on its feature (a distance's: on its first face); null where its
 *   feature is not on the page (a broken reference), the label then standing where it was placed.
 * - `label`: where its text stands.
 * - `dimension`: a distance's dimension line (`from`, `to`: on each face's plane, through the label)
 *   and its extension lines (`extensions`), else null; a distance has no leader.
 * - `presentation`: the placement drawn (`{ anchor, offset }`), as `pmi.place` would write it.
 * - `placed`: `"given"` (its `placement` here, or the code's), or `"default"`.
 *
 * @param {ReturnType<typeof import("./xbfPmi.js").readXbfPmi>[number]} entry
 * @param {{ geometry: Record<string, { surface: object, points?: number[][] } | null>, bounds?: { min: number[], max: number[] } | null,
 *   turn?: number, placement?: { anchor: number[], offset: number[] } | null }} options
 *   `geometry`: each role's element (`feature`, `from`, `to`), null for one not on the page; `turn`:
 *   how many of its feature's annotations came before it; `placement`: one to draw it at in place of
 *   the code's (a drag not yet written).
 */
export function pmiConstruction(entry, { geometry, bounds = null, turn = 0, placement = null }) {
  const centre = boxCentre(bounds);
  const reach = pmiReach(bounds);
  const given = placement || entry.presentation;
  const at = given ? { anchor: given.anchor.slice(), offset: given.offset.slice() } : null;
  const placed = given ? "given" : "default";
  if (entry.kind === "dimension" && entry.dimension?.type === "distance") {
    const from = geometry.from, to = geometry.to;
    const n = outward(from);
    if (!from || !to || !n || to.surface?.type !== "plane" || from.surface?.type !== "plane") {
      return at ? { anchor: null, label: add(at.anchor, at.offset), dimension: null, presentation: at, placed } : null;
    }
    // Each plane through its own origin, along the first face's normal.
    const level = point => dot(point, n);
    const anchor = at ? at.anchor : edgePoint(from, centre, n);
    const offset = at ? at.offset : (() => {
      const away = unit(across(sub(anchor, centre), n)) || anyPerpendicular(n);
      const side = turned(away, n, turn * SPREAD);
      // Halfway between the faces, out to the side.
      return add(scale(n, (level(to.surface.origin) - level(anchor)) / 2), scale(side, reach * 0.5));
    })();
    const label = add(anchor, offset);
    const onFrom = sub(label, scale(n, level(label) - level(from.surface.origin)));
    const onTo = sub(label, scale(n, level(label) - level(to.surface.origin)));
    const foot = sub(anchor, scale(n, level(anchor) - level(to.surface.origin)));
    return { anchor, label, dimension: { from: onFrom, to: onTo, extensions: [[anchor, onFrom], [foot, onTo]] },
      presentation: { anchor, offset }, placed };
  }
  const feature = geometry.feature;
  const out = outward(feature);
  if (!feature || !out) return at ? { anchor: null, label: add(at.anchor, at.offset), dimension: null, presentation: at, placed } : null;
  const anchor = at ? at.anchor : pmiFeaturePoint(feature, centre);
  const offset = at ? at.offset : defaultOffset({ anchor, out, centre, reach, turn });
  return { anchor, label: add(anchor, offset), dimension: null, presentation: { anchor, offset }, placed };
}

/**
 * Where a label dragged to `label` puts the annotation: its anchor where it was, its offset to the
 * label's new place. What it means is not touched.
 */
export function pmiMovedPlacement(presentation, label) {
  return { anchor: presentation.anchor.slice(), offset: sub(label, presentation.anchor) };
}
