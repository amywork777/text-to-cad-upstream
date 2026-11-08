/**
 * Hole Wizard's sizes, as SolidWorks' Hole Wizard sets them out by standard: for each screw, the
 * hole it passes through at each fit, the drill its thread is tapped in, and the counterbore or
 * countersink its head sits in. ISO in millimetres, ANSI Inch in inches; each filled into the
 * Hole panel in the part's own units, where the engineer can still type over it.
 *
 * Where the numbers come from: clearance holes are ISO 273's fine, medium and coarse series (Close,
 * Normal, Loose) and, for inch screws, Machinery's Handbook's close and free fits (Close, Normal).
 * Tap drills are an ISO coarse thread's diameter less its pitch, and the number or letter drill for
 * a 75% inch thread. A counterbore takes a socket head cap screw (ISO 4762, ASME B18.3): the head's
 * largest diameter and 1 mm (1/32 in) more across, as deep as the head is tall and a tenth more. A
 * countersink takes a flat head (ISO 10642 at 90°, ASME B18.6.3 at 82°), as wide as the head's
 * largest diameter, so the head sits flush.
 */

// size, pitch, tap drill, clearance [close, normal, loose], socket head [diameter, height], flat head diameter (none below M3).
const ISO = Object.freeze([
  ["M1.6", 0.35, 1.25, [1.7, 1.8, 2.0], [3.0, 1.6], null],
  ["M2", 0.4, 1.6, [2.2, 2.4, 2.6], [3.8, 2.0], null],
  ["M2.5", 0.45, 2.05, [2.7, 2.9, 3.1], [4.5, 2.5], null],
  ["M3", 0.5, 2.5, [3.2, 3.4, 3.6], [5.5, 3.0], 6.72],
  ["M4", 0.7, 3.3, [4.3, 4.5, 4.8], [7.0, 4.0], 8.96],
  ["M5", 0.8, 4.2, [5.3, 5.5, 5.8], [8.5, 5.0], 11.2],
  ["M6", 1.0, 5.0, [6.4, 6.6, 7.0], [10.0, 6.0], 13.44],
  ["M8", 1.25, 6.8, [8.4, 9.0, 10.0], [13.0, 8.0], 17.92],
  ["M10", 1.5, 8.5, [10.5, 11.0, 12.0], [16.0, 10.0], 22.4],
  ["M12", 1.75, 10.2, [13.0, 13.5, 14.5], [18.0, 12.0], 26.88],
]);
// size, tap drill, clearance [close, free], socket head [diameter, height], 82° flat head diameter.
const ANSI = Object.freeze([
  ["#2-56", 0.07, [0.089, 0.1015], [0.14, 0.086], 0.172],
  ["#4-40", 0.089, [0.116, 0.1285], [0.183, 0.112], 0.225],
  ["#6-32", 0.1065, [0.144, 0.1695], [0.226, 0.138], 0.279],
  ["#8-32", 0.136, [0.1695, 0.196], [0.27, 0.164], 0.332],
  ["#10-24", 0.1495, [0.196, 0.221], [0.312, 0.19], 0.385],
  ["#10-32", 0.159, [0.196, 0.221], [0.312, 0.19], 0.385],
  ["1/4-20", 0.201, [0.257, 0.266], [0.375, 0.25], 0.507],
  ["5/16-18", 0.257, [0.323, 0.332], [0.469, 0.3125], 0.635],
  ["3/8-16", 0.3125, [0.386, 0.397], [0.5625, 0.375], 0.762],
]);

/** The standards, as Hole Wizard's Standard names them, each in its own unit. */
export const HOLE_STANDARDS = Object.freeze([{ value: "iso", label: "ISO" }, { value: "ansi", label: "ANSI Inch" }]);
const UNIT = Object.freeze({ iso: "mm", ansi: "in" });
// What a counterbore clears the head by, across: 1 mm, or 1/32 in.
const HEAD_CLEARANCE = Object.freeze({ iso: 1, ansi: 1 / 32 });
const CSK_ANGLE = Object.freeze({ iso: 90, ansi: 82 });
const FITS = Object.freeze({
  iso: [{ value: "close", label: "Close" }, { value: "normal", label: "Normal" }, { value: "loose", label: "Loose" }],
  ansi: [{ value: "close", label: "Close" }, { value: "normal", label: "Normal" }],
});

/** The standard a part starts with: ANSI Inch in an inch part, else ISO. */
export const defaultStandard = units => (units === "in" ? "ansi" : "iso");

/** The size a part's Hole opens with: M3, or #4-40 in an inch part. */
export const defaultSize = standard => (standard === "ansi" ? "#4-40" : "M3");

function row(standard, size) {
  const table = standard === "ansi" ? ANSI : ISO;
  const found = table.find(each => each[0] === size);
  if (!found) return null;
  return standard === "ansi"
    ? { size: found[0], tap: found[1], clearance: found[2], head: found[3], flat: found[4] }
    : { size: found[0], pitch: found[1], tap: found[2], clearance: found[3], head: found[4], flat: found[5] };
}

/** The fits a standard offers its clearance holes. */
export const holeFits = standard => FITS[standard] || FITS.iso;

/** The sizes a hole type offers in a standard: a countersink only those a flat head is made in. */
export function holeSizeOptions(standard, type) {
  const table = standard === "ansi" ? ANSI : ISO;
  return table.filter(each => type !== "countersink" || each[each.length - 1] !== null)
    .map(each => ({ value: each[0], label: each[0] }));
}

// A length in a standard's unit, in the part's, as the panel types one: ".1285" in inches, "3.4" in millimetres.
function typed(value, from, units) {
  const to = units === "in" ? "in" : "mm";
  const converted = from === to ? value : from === "mm" ? value / 25.4 : value * 25.4;
  const text = Number(converted.toFixed(to === "in" ? 4 : 2)).toString();
  return to === "in" ? text.replace(/^0\./, ".") : text;
}

/**
 * The sizes a hole of `values.size` takes, in the part's units, for its type and fit: its
 * diameter (a tapped hole's, its tap drill), and its counterbore's or countersink's. Empty for a
 * size the standard does not have (Custom: the engineer's own).
 */
export function holeFill(values, units) {
  const standard = values.standard === "ansi" ? "ansi" : "iso";
  const found = row(standard, values.size);
  if (!found) return {};
  const unit = UNIT[standard];
  // A fit the standard does not have (Loose, in inches) reads as Normal.
  const at = holeFits(standard).findIndex(fit => fit.value === values.fit);
  const fit = at >= 0 ? at : 1;
  const filled = { diameter: typed(values.type === "tapped" ? found.tap : found.clearance[fit], unit, units) };
  if (values.type === "counterbore") {
    filled.cbore_diameter = typed(found.head[0] + HEAD_CLEARANCE[standard], unit, units);
    filled.cbore_depth = typed(found.head[1] * 1.1, unit, units);
  }
  if (values.type === "countersink" && found.flat) {
    filled.csk_diameter = typed(found.flat, unit, units);
    filled.csk_angle = String(CSK_ANGLE[standard]);
  }
  return filled;
}

const KINDS = Object.freeze({ simple: "clearance hole", counterbore: "socket head counterbore", countersink: "flat head countersink",
  tapped: "tapped hole" });

/**
 * A sized hole's callout, as the script keeps it beside the hole's line and a drawing would label
 * it: "M3 clearance hole, normal fit", "M3x0.5 tapped hole", "#4-40 socket head counterbore,
 * close fit". Empty for a Custom hole.
 */
export function holeCallout(values) {
  const standard = values.standard === "ansi" ? "ansi" : "iso";
  const found = row(standard, values.size);
  const kind = KINDS[values.type || "simple"];
  if (!found || !kind) return "";
  if (values.type === "tapped") return `${found.size}${standard === "iso" ? `x${found.pitch}` : ""} ${kind}`;
  const fit = holeFits(standard).find(each => each.value === values.fit) || holeFits(standard)[1];
  return `${found.size} ${kind}, ${fit.label.toLowerCase()} fit`;
}

/** A callout read back (`holeCallout`'s words) as the panel's standard, size, fit and type; empty for any other words. */
export function calloutValues(callout) {
  const match = /^(M[\d.]+|#\d+-\d+|\d+\/\d+-\d+)(?:x[\d.]+)? (clearance hole|socket head counterbore|flat head countersink|tapped hole)(?:, (close|normal|loose) fit)?$/
    .exec(String(callout || "").trim());
  if (!match) return {};
  const standard = match[1].startsWith("M") ? "iso" : "ansi";
  if (!row(standard, match[1])) return {};
  const type = Object.keys(KINDS).find(key => KINDS[key] === match[2]);
  return { standard, size: match[1], type, ...(match[3] ? { fit: match[3] } : {}) };
}
