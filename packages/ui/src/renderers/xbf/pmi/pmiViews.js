import { pmiKey } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { placeXbfDirection, placeXbfPoint } from "@text-to-cad/core/lib/xbf/xbfEntities.js";
import { pmiShownOccurrence } from "./pmiRefs.js";

// A part's named view (`readXbfPmi`'s `views`) where the part stands: its camera and its section
// are served in the part's frame, and are seen from the first occurrence of the part that is shown,
// as its PMI is drawn there (`pmiRefs.js`). The camera turns with that occurrence's placement; the
// section is the Clip's own shape (one plane square to an axis, `{ axis, at, invert }`), so it is
// cut only where the placement keeps its axis a world axis. Turned off one (a part placed at an
// angle in an assembly), it is not cut along another, nearest axis: the view says it cannot be.

const AXES = Object.freeze(["x", "y", "z"]);
const IDENTITY = Object.freeze([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
// How near a world axis a placed section's normal must be: a placement's own rounding, no more.
const ON_AXIS = 1e-9;
// A coordinate free of the float noise a placement leaves (and of a negative zero).
const clean = value => Number(value.toPrecision(12)) + 0;

/**
 * A view's section (`{ axis, at, invert }`, its part's frame) where `matrix` places the part (4 x 4,
 * column-major): the Clip's settings in the scene's, or null where the placement turns its axis off
 * every world axis. Its plane keeps the side it kept: turned to point down a world axis, its
 * `invert` flips.
 */
function placedSection(section, matrix) {
  const index = AXES.indexOf(section.axis);
  const along = [0, 0, 0];
  along[index] = 1;
  const normal = placeXbfDirection(matrix, along);
  const world = normal.findIndex(component => Math.abs(Math.abs(component) - 1) <= ON_AXIS);
  if (world < 0) return null;
  const point = [0, 0, 0];
  point[index] = section.at;
  return { axis: AXES[world], at: clean(placeXbfPoint(matrix, point)[world]), invert: normal[world] < 0 ? !section.invert : section.invert };
}

/**
 * Where a view is seen from: the first occurrence of its part shown (`instance`, the structure's
 * index), its camera's `direction` (from the part toward the eye) and `up` placed by that
 * occurrence, and its section as the Clip cuts it there (`section`), null where it has none or
 * where the placement turns its axis off a world axis (`sectionOff`). Null where no occurrence of
 * its part is shown, or the view is one the viewer cannot apply.
 *
 * @param {import("@text-to-cad/core/lib/xbf/xbfPmi.js").XbfPmiView} view
 * @param {readonly object[]} instances  The structure's.
 * @param {{ hidden?: readonly string[], isolated?: readonly string[] }} [shown]
 * @returns {{ instance: number, direction: number[], up: number[], section: { axis: string, at: number, invert: boolean } | null,
 *   sectionOff: boolean } | null}
 */
export function pmiViewAt(view, instances, shown = {}) {
  if (!view.supported || view.part === null) return null;
  const instance = pmiShownOccurrence(view.part, instances, shown);
  if (instance === undefined) return null;
  const matrix = instances[instance]?.matrix || IDENTITY;
  const section = view.section ? placedSection(view.section, matrix) : null;
  return { instance, direction: placeXbfDirection(matrix, view.camera.direction), up: placeXbfDirection(matrix, view.camera.up),
    section, sectionOff: Boolean(view.section) && !section };
}

/** Whether a view shows an annotation: one of its part it names, or any of its part where it names none. */
export function pmiViewShows(view, entry) {
  return entry.part === view.part && (view.shows === null || view.shows.includes(entry.id));
}

/** A view's own placements of what it shows, by each annotation's key (`pmiKey`), in its part's frame. */
export function pmiViewPlacements(view) {
  return new Map(Object.entries(view.place).map(([id, placement]) => [pmiKey(view.part, id), placement]));
}

/** What a view's row says it shows: how many it names, or all of its part's. */
export function pmiViewShowsText(view) {
  if (view.shows === null) return "All";
  return `${view.shows.length} annotation${view.shows.length === 1 ? "" : "s"}`;
}
