import { pmiFreshId } from "@text-to-cad/core/lib/xbf/xbfPmi.js";

// What a new annotation can be made of the faces Select has picked, as the supported subset has
// them: a datum or a flatness on one flat face, a distance between two parallel flat faces, a basic
// (exact) distance between two of flat faces and holes, each hole by its axis, all parallel, a
// diameter or a position on one cylindrical face. Each is the call it would be (`pmiCallText`'s
// input), its references the picked faces' canonical refs and its id one no annotation has; what a
// tolerance is stays the person's to give -- nothing here fills one in. A distance's and a
// diameter's nominal here is the page's reading of the mesh, shown while the call is made: the
// engine measures the exact one when the model builds with it.

// ASME Y14.5 leaves I, O and Q out of datum letters: they read as 1, 0 and O.
const DATUM_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ".split("");
const PARALLEL = 1 - 1e-6;
// How far an axis may lean off square to a plane's normal, or off another axis (sin), as the layout allows.
const SQUARE = 1e-3;
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const length = a => Math.hypot(a[0], a[1], a[2]);

/**
 * What two faces a basic dimension goes between measure, or null where they make none: two parallel
 * planes, a plane and an axis square to its normal (a hole's centre line), or two parallel axes.
 */
function basicSeparation(a, b) {
  const plane = item => item.surface.type === "plane", round = item => item.surface.type === "cylinder";
  if (plane(a) && plane(b)) return Math.abs(dot(a.surface.normal, b.surface.normal)) >= PARALLEL ? Math.abs(dot(sub(b.surface.origin, a.surface.origin), a.surface.normal)) : null;
  if (round(a) && round(b)) {
    const axis = a.surface.axis;
    if (length(cross(axis, b.surface.axis)) > SQUARE) return null;
    const between = sub(b.surface.origin, a.surface.origin);
    return length(sub(between, axis.map(value => value * dot(between, axis))));
  }
  const [flat, hole] = plane(a) ? [a, b] : [b, a];
  if (!plane(flat) || !round(hole) || Math.abs(dot(hole.surface.axis, flat.surface.normal)) > SQUARE) return null;
  return Math.abs(dot(sub(hole.surface.origin, flat.surface.origin), flat.surface.normal));
}

/** The first datum letter none of `entries` has, nor any new datum asked for (`pending` calls). */
export function nextDatumLetter(entries, pending = []) {
  const taken = new Set([...entries.filter(entry => entry.kind === "datum").map(entry => entry.datum?.letter),
    ...pending.filter(call => call.kind === "datum").map(call => call.letter)]);
  return DATUM_LETTERS.find(letter => !taken.has(letter)) || "";
}

/**
 * The kinds a new annotation can be, in the order the menu lists them, each with whether the pick
 * makes one (`available`), what it needs when it does not (`need`), and the call it starts as.
 *
 * @param {{ picked: Array<{ id: string, ref: string, surface: { type: string, normal?: number[], axis?: number[], origin?: number[], radius?: number } | null }>,
 *   entries: ReturnType<typeof import("@text-to-cad/core/lib/xbf/xbfPmi.js").readXbfPmi>, pending?: object[] }} options
 *   `picked`: the faces Select has picked, each with its canonical ref and its surface; anything else
 *   picked makes nothing. `pending`: the new annotations already asked for (their calls), whose ids
 *   and letters are taken too.
 */
export function pmiCreateOptions({ picked, entries, pending = [] }) {
  const ids = [...entries.map(entry => entry.id), ...pending.map(call => call.id)];
  const faces = picked.filter(item => item.surface && item.ref);
  const only = picked.length === faces.length;
  const planes = only ? faces.filter(item => item.surface.type === "plane") : [];
  const cylinders = only ? faces.filter(item => item.surface.type === "cylinder") : [];
  const oneFlat = faces.length === 1 && planes.length === 1 ? planes[0] : null;
  const oneRound = faces.length === 1 && cylinders.length === 1 ? cylinders[0] : null;
  const pair = faces.length === 2 && planes.length === 2 ? planes : null;
  const ends = only && faces.length === 2 && planes.length + cylinders.length === 2 ? faces : null;
  const basic = ends ? basicSeparation(ends[0], ends[1]) : null;
  const parallel = pair && Math.abs(dot(pair[0].surface.normal, pair[1].surface.normal)) >= PARALLEL ? pair : null;
  const letter = nextDatumLetter(entries, pending);
  const datums = entries.filter(entry => entry.kind === "datum" && entry.datum?.letter).map(entry => entry.datum.letter);
  return [
    { kind: "datum", label: "Datum", need: "Pick one flat face", available: Boolean(oneFlat && letter),
      call: oneFlat ? { kind: "datum", id: letter, letter, ref: oneFlat.ref } : null },
    { kind: "distance", label: "Distance", need: "Pick two parallel flat faces", available: Boolean(parallel),
      call: parallel ? { kind: "dimension", type: "distance", id: pmiFreshId("distance", ids), from: parallel[0].ref, to: parallel[1].ref, tolerance: null } : null,
      nominal: parallel ? Math.abs(dot(parallel[1].surface.origin.map((value, axis) => value - parallel[0].surface.origin[axis]), parallel[0].surface.normal)) : null },
    { kind: "basic", label: "Basic dimension", need: "Pick two parallel flat faces or holes", available: basic !== null,
      call: basic !== null ? { kind: "dimension", type: "distance", basic: true, id: pmiFreshId("basic", ids), from: ends[0].ref, to: ends[1].ref, tolerance: null } : null,
      nominal: basic },
    { kind: "diameter", label: "Diameter", need: "Pick one round face", available: Boolean(oneRound),
      call: oneRound ? { kind: "dimension", type: "diameter", id: pmiFreshId("diameter", ids), ref: oneRound.ref, tolerance: null } : null,
      nominal: oneRound ? 2 * oneRound.surface.radius : null },
    { kind: "flatness", label: "Flatness", need: "Pick one flat face", available: Boolean(oneFlat),
      call: oneFlat ? { kind: "geometric_tolerance", characteristic: "flatness", id: pmiFreshId("flatness", ids), ref: oneFlat.ref, value: null } : null },
    { kind: "position", label: "Position", need: datums.length ? "Pick one round face" : "Pick one round face, after a datum", available: Boolean(oneRound && datums.length),
      call: oneRound ? { kind: "geometric_tolerance", characteristic: "position", id: pmiFreshId("position", ids), ref: oneRound.ref, value: null,
        datums: datums.slice(0, 1), diameterZone: true } : null },
  ];
}

/** A tolerance typed in: "±0.1", "0.1" (both ways), "+0.1/-0.05" or "+0.1 -0.05"; "" is none, never a guess. */
export function parseToleranceInput(text) {
  const value = String(text || "").trim().replaceAll("−", "-");
  if (!value) return { tolerance: null };
  const numbers = value.replace(/^±/, "").split(/[\s/]+/).filter(Boolean).map(Number);
  if (!numbers.length || numbers.some(number => !Number.isFinite(number))) return { error: "A tolerance is ±0.1, or +0.1/-0.05" };
  if (numbers.length === 1) return numbers[0] > 0 ? { tolerance: { type: "plus_minus", upper: numbers[0], lower: -numbers[0] } } : { error: "A tolerance is more than 0" };
  const [upper, lower] = numbers;
  if (numbers.length > 2 || upper < lower) return { error: "The upper deviation comes first, and is not under the lower" };
  return { tolerance: { type: "plus_minus", upper, lower } };
}

// A feature control frame refers to a primary, a secondary and a tertiary datum, no more.
export const MAX_DATUMS = 3;

/**
 * A frame's datums with `letter` taken out, or put in last: in the order picked, primary first (the
 * order is what the frame means, never sorted), and never past three.
 */
export function toggleDatum(datums, letter) {
  if (datums.includes(letter)) return datums.filter(item => item !== letter);
  return datums.length >= MAX_DATUMS ? datums : [...datums, letter];
}
