// An engine document's PMI -- its manufacturing annotations: dimensions with their tolerances,
// datum features and geometric tolerances -- as the page reads them from the document the engine
// serves (`structure.pmi`, the document's XCAF GD&T attributes read by `cadgen.engine.pmi`), and
// as the viewer says them and asks for them.
//
// What is said comes from the document alone: a dimension's nominal is the engine's, measured on
// the geometry; a tolerance is what the model's code supplied, and none where it supplied none --
// the viewer never fills one in. A basic dimension (`pmi.basic`: theoretically exact, as a position
// tolerance's true position is located) is a distance that holds no tolerance at all, drawn boxed.
// Where an annotation stands on screen (`presentation`) is no part of what it means: moving it
// changes how it is drawn, never what it says.
//
// An id is the author's and unique on its part (a datum's is its letter), so an annotation is known
// by its part and its id (`key`), and asked for by both.
//
// The document is made from code (`pmi.annotate(body, pmi.datum("A", ...), ...)` in the model), so
// a change asked for in the viewer is the call it would write there (`pmiCallText`,
// `pmiPlaceText`): what Quick Edit hands the agent, which writes it into the model and builds.

/** The kinds the viewer draws; any other an entry names is told, not drawn. */
const PMI_KINDS = Object.freeze(["dimension", "datum", "geometric_tolerance"]);
/** The dimension types the viewer draws. */
const PMI_DIMENSION_TYPES = Object.freeze(["distance", "diameter"]);
/** The geometric characteristics the viewer draws. */
const PMI_CHARACTERISTICS = Object.freeze(["flatness", "position"]);
/**
 * What a reference's or an annotation's status may be, best first: it names one face it can
 * stand on; several; nothing; or a face it cannot stand on (a diameter on a plane, say).
 */
const PMI_STATUSES = Object.freeze(["ok", "ambiguous", "missing", "invalid"]);

const MINUS = "−";
const finite = value => (typeof value === "number" && Number.isFinite(value) ? value : null);
const text = value => (typeof value === "string" ? value : "");
const point3 = value => (Array.isArray(value) && value.length === 3 && value.every(item => finite(item) !== null) ? value.slice() : null);
const statusOf = value => (PMI_STATUSES.includes(value) ? value : "missing");

function readRefs(refs) {
  return (Array.isArray(refs) ? refs : []).map((ref) => {
    const written = text(ref?.written) || text(ref?.ref);
    return { role: text(ref?.role) || "feature", ref: text(ref?.ref) || written, written, status: statusOf(ref?.status),
      candidates: Array.isArray(ref?.candidates) ? ref.candidates.map(text).filter(Boolean) : [] };
  });
}

// An unsupported entry's values, as far as they read as words: each number, word or list of them.
function readValues(values) {
  const plain = value => (typeof value === "number" && Number.isFinite(value)) || (typeof value === "string" && value);
  return Object.entries(values).flatMap(([key, value]) => (plain(value) ? [[key, String(value)]]
    : Array.isArray(value) && value.length && value.every(plain) ? [[key, value.join(", ")]] : []));
}

function readTolerance(value) {
  if (!value || value.type !== "plus_minus") return null;
  const upper = finite(value.upper), lower = finite(value.lower);
  return upper === null || lower === null ? null : { type: "plus_minus", upper, lower };
}

/**
 * Why an entry the document holds is not one the viewer draws, or "" for one it draws: an unknown
 * kind, a dimension of a type it does not draw, a characteristic it does not draw, or the values
 * its kind needs missing. Where the engine says why (an `unsupported` entry's `reason`), its words
 * are said instead (`readXbfPmi`).
 */
function unsupportedReason(entry) {
  if (entry.kind === "unsupported") return entry.xcafType ? `${entry.xcafType} is not one the viewer draws` : "not one the viewer draws";
  if (!PMI_KINDS.includes(entry.kind)) return `${entry.kind || "an annotation"} is not one the viewer draws`;
  if (entry.kind === "dimension") {
    if (!PMI_DIMENSION_TYPES.includes(entry.dimension?.type)) return `a ${entry.dimension?.type || "dimension"} dimension is not one the viewer draws`;
    if (entry.dimension.basic && entry.dimension.type !== "distance") return `a basic ${entry.dimension.type} is not one the viewer draws`;
    // A broken reference leaves nothing to measure: no nominal, said as unknown. One that resolved has one.
    if (entry.dimension.nominal === null && entry.status === "ok") return "it has no nominal";
  }
  if (entry.kind === "datum" && !entry.datum?.letter) return "it has no letter";
  if (entry.kind === "geometric_tolerance") {
    if (!PMI_CHARACTERISTICS.includes(entry.tolerance?.characteristic)) return `${entry.tolerance?.characteristic || "this characteristic"} is not one the viewer draws`;
    if (entry.tolerance.value === null) return "it has no tolerance value";
  }
  return "";
}

/** What an annotation is known by in its document: its part (`part`, the structure's prototype) and its id. */
export const pmiKey = (part, id) => `${part ?? ""}:${id}`;

/**
 * The document's PMI as the viewer reads it (`structure.pmi`; none where the key is absent), each
 * entry with every field its kind carries, read defensively: a field missing or of the wrong type
 * is null, never guessed. `supported` is whether the viewer draws it, `unsupported` why not.
 *
 * @param {object | null} structure  A served document's structure.
 * @returns {Array<{ key: string, id: string, kind: string, label: string, status: "ok" | "ambiguous" | "missing" | "invalid",
 *   problem: string, refs: Array<{ role: string, ref: string, written: string, status: string, candidates: string[] }>,
 *   dimension: { type: string, basic: boolean, nominal: number | null, unit: string, source: string,
 *     tolerance: { type: "plus_minus", upper: number, lower: number } | null } | null,
 *   datum: { letter: string } | null,
 *   tolerance: { characteristic: string, value: number | null, unit: string, zone: string | null,
 *     modifier: string | null, datums: string[] } | null,
 *   presentation: { anchor: number[], offset: number[] } | null, xcafType: string, part: number | null,
 *   warnings: string[], values: Array<[string, string]> | null, supported: boolean, unsupported: string }>}
 *   `key`: its part's and its id (`pmiKey`), what the viewer knows it by; `part`: the structure's
 *   prototype the annotation is of (its presentation is in that part's frame), null where it is
 *   linked to nothing; `warnings`: what the build that served it warned of (a ref that names another
 *   kind of face than on the last build; a file holds none); `values`: what an unsupported one holds,
 *   as words; `unsupported`: why it is not drawn, the engine's reason where it gives one.
 */
export function readXbfPmi(structure) {
  const list = Array.isArray(structure?.pmi) ? structure.pmi : [];
  const seen = new Set();
  return list.filter(item => item && typeof item === "object").map((item, index) => {
    // One the document lacks an id for, or repeats on a part, is kept apart by its place.
    const part = Number.isInteger(item.part) ? item.part : null;
    const id = text(item.id) || `#${index + 1}`;
    let key = pmiKey(part, id);
    if (seen.has(key)) key = `${key}#${index + 1}`;
    seen.add(key);
    const dimension = item.dimension && typeof item.dimension === "object" ? {
      type: text(item.dimension.type), basic: item.dimension.basic === true, nominal: finite(item.dimension.nominal?.value),
      unit: text(item.dimension.nominal?.unit) || "mm", source: text(item.dimension.nominal?.source),
      // A basic dimension is exact: a tolerance on one is not read as one.
      tolerance: item.dimension.basic === true ? null : readTolerance(item.dimension.tolerance)
    } : null;
    const gdt = item.geometric_tolerance && typeof item.geometric_tolerance === "object" ? {
      characteristic: text(item.geometric_tolerance.characteristic), value: finite(item.geometric_tolerance.value),
      unit: text(item.geometric_tolerance.unit) || "mm", zone: text(item.geometric_tolerance.zone) || null,
      modifier: text(item.geometric_tolerance.modifier) || null,
      datums: Array.isArray(item.geometric_tolerance.datums) ? item.geometric_tolerance.datums.map(text).filter(Boolean) : []
    } : null;
    const presentation = item.presentation && point3(item.presentation.anchor) && point3(item.presentation.offset)
      ? { anchor: point3(item.presentation.anchor), offset: point3(item.presentation.offset) } : null;
    const entry = {
      key, id, kind: text(item.kind), label: text(item.label), status: statusOf(item.status), problem: text(item.problem), part,
      refs: readRefs(item.refs), dimension, datum: item.datum && text(item.datum.letter) ? { letter: text(item.datum.letter) } : null,
      tolerance: gdt, presentation, xcafType: text(item.xcaf_type),
      warnings: Array.isArray(item.warnings) ? item.warnings.map(text).filter(Boolean) : [],
      // What the document holds of an annotation the viewer does not draw: its plain values, to read.
      values: item.values && typeof item.values === "object" && !Array.isArray(item.values) ? readValues(item.values) : null
    };
    // Whether it is drawn is the viewer's to say; why not, the engine's words where it gives them.
    const own = unsupportedReason(entry);
    const unsupported = own && (text(item.reason) || own);
    return { ...entry, supported: !unsupported, unsupported };
  });
}

// ---- saying it --------------------------------------------------------------------------------

// The places a number is given to: what its own value needs, up to four, trailing zeros dropped.
function decimalsOf(value) {
  const fixed = Math.abs(value).toFixed(4).replace(/0+$/, "");
  const dot = fixed.indexOf(".");
  return dot < 0 || dot === fixed.length - 1 ? 0 : fixed.length - dot - 1;
}

/** A number at `places` decimals, with a true minus sign. */
export function pmiNumber(value, places = decimalsOf(value)) {
  const fixed = Math.abs(value).toFixed(places);
  return Number(fixed) === 0 ? fixed : `${value < 0 ? MINUS : ""}${fixed}`;
}

/**
 * A plus-minus tolerance as a drawing writes it: `±0.2` where it is the same both ways, else its
 * two deviations, each signed (`+0.1`, `−0.05`) and a zero bare (`0`), at one number of places.
 */
export function pmiToleranceText(tolerance) {
  if (!tolerance) return null;
  const places = Math.max(decimalsOf(tolerance.upper), decimalsOf(tolerance.lower));
  if (tolerance.upper > 0 && Math.abs(tolerance.upper + tolerance.lower) < 1e-12) {
    return { symmetric: true, text: `±${pmiNumber(tolerance.upper, places)}`, upper: `+${pmiNumber(tolerance.upper, places)}`,
      lower: `${MINUS}${pmiNumber(tolerance.upper, places)}`, places };
  }
  const signed = value => (value === 0 ? "0" : value > 0 ? `+${pmiNumber(value, places)}` : pmiNumber(value, places));
  return { symmetric: false, text: `${signed(tolerance.upper)}/${signed(tolerance.lower)}`, upper: signed(tolerance.upper),
    lower: signed(tolerance.lower), places };
}

const CHARACTERISTIC_NAMES = Object.freeze({ flatness: "Flatness", position: "Position" });
const DIMENSION_NAMES = Object.freeze({ distance: "Distance", diameter: "Diameter" });

/**
 * The places a dimension's numbers are written at: its tolerance's (none without one) or what its
 * nominal needs (up to four), whichever is more -- the nominal's on its callout, and both of its
 * current limits'.
 */
export function pmiDimensionPlaces(dimension) {
  const tolerance = pmiToleranceText(dimension.tolerance);
  return Math.max(tolerance ? tolerance.places : 0, dimension.nominal === null ? 0 : decimalsOf(dimension.nominal));
}

/**
 * What a callout says, in pieces a label draws and in words: a dimension's nominal (at
 * `pmiDimensionPlaces`), its `⌀` for a diameter and its tolerance, `basic` for one that is exact (a
 * drawing boxes its number); a datum's letter;
 * a frame's cells -- its characteristic, its value (with `⌀` for a diameter zone) and each datum it
 * refers to. `text` is the one line a row, a hint or a copy carries.
 *
 * @param {ReturnType<typeof readXbfPmi>[number]} entry
 */
export function pmiCallout(entry) {
  if (!entry?.supported) return { kind: "unsupported", title: entry?.label || entry?.id || "", text: entry?.xcafType || entry?.kind || "PMI" };
  if (entry.kind === "dimension") {
    const tolerance = pmiToleranceText(entry.dimension.tolerance);
    // No nominal where the reference broke: there is nothing to measure it on.
    const nominal = entry.dimension.nominal === null ? "?" : pmiNumber(entry.dimension.nominal, pmiDimensionPlaces(entry.dimension));
    const diameter = entry.dimension.type === "diameter";
    const basic = entry.dimension.basic;
    return { kind: "dimension", type: entry.dimension.type, diameter, basic, nominal, tolerance, unit: entry.dimension.unit,
      title: basic ? "Basic distance" : DIMENSION_NAMES[entry.dimension.type],
      text: `${diameter ? "⌀" : ""}${nominal}${tolerance ? ` ${tolerance.text}` : ""}${basic ? " basic" : ""}` };
  }
  if (entry.kind === "datum") return { kind: "datum", letter: entry.datum.letter, title: "Datum", text: `Datum ${entry.datum.letter}` };
  const { characteristic, value, zone, datums, unit } = entry.tolerance;
  const diameter = zone === "diameter";
  const shown = pmiNumber(value);
  return { kind: "frame", characteristic, diameter, value: shown, datums: [...datums], unit, title: CHARACTERISTIC_NAMES[characteristic],
    text: [`${CHARACTERISTIC_NAMES[characteristic]} ${diameter ? "⌀" : ""}${shown}`, ...datums].join(" | ") };
}

/** What the status of an entry or a reference is, in words, or "" for one that is fine. */
export function pmiStatusText(entry) {
  if (!entry || entry.status === "ok") return "";
  if (entry.problem) return entry.problem;
  const broken = entry.refs?.find(ref => ref.status !== "ok");
  if (entry.status === "ambiguous") return broken ? `${broken.written} names ${broken.candidates.length || "several"} elements` : "A reference names several elements";
  if (entry.status === "invalid") return broken ? `${broken.written} names a face this cannot stand on` : "A reference names a face this cannot stand on";
  return broken ? `${broken.written} names nothing in this version` : "A reference names nothing in this version";
}

// ---- asking for it: the code a change is ------------------------------------------------------

const PY_NUMBER_PLACES = 4;
/** A number as the model's code writes it: at most four places, no float noise, never `-0`. */
export function pyNumber(value) {
  const rounded = Number(Number(value).toFixed(PY_NUMBER_PLACES));
  return String(Object.is(rounded, -0) ? 0 : rounded);
}
// A string as Python reads it: JSON's quoting is Python's for every character a ref or an id holds.
const pyString = value => JSON.stringify(String(value));
const pyTuple = point => `(${point.map(pyNumber).join(", ")})`;

/** The `pmi.place(...)` an annotation's presentation is in code: where it is drawn, never what it means. */
export function pmiPlaceText(presentation) {
  return `pmi.place(anchor=${pyTuple(presentation.anchor)}, offset=${pyTuple(presentation.offset)})`;
}

/** The `pmi.plus_minus(...)` a tolerance is in code; the lower deviation left out where it is the upper's negative. */
function pmiPlusMinusText(tolerance) {
  const symmetric = Math.abs(tolerance.upper + tolerance.lower) < 1e-12;
  return symmetric ? `pmi.plus_minus(${pyNumber(tolerance.upper)})` : `pmi.plus_minus(${pyNumber(tolerance.upper)}, ${pyNumber(tolerance.lower)})`;
}

/**
 * The call that declares an annotation in the model's `pmi.annotate(body, ...)`, as `cadgen.engine.pmi`
 * takes it: its id first, then its references (each its canonical ref, verbatim), then its values:
 *
 * - `{ kind: "datum", id, letter, ref }`: `pmi.datum("A", ref)` (a datum's id is its letter);
 * - `{ kind: "dimension", type: "distance", id, from, to, tolerance? }`: `pmi.distance(id, from, to, tolerance=...)`;
 * - `{ kind: "dimension", type: "distance", basic: true, id, from, to }`: `pmi.basic(id, from, to)` (exact: a
 *   tolerance given it makes no call);
 * - `{ kind: "dimension", type: "diameter", id, ref, tolerance? }`: `pmi.diameter(id, ref, tolerance=...)`;
 * - `{ kind: "geometric_tolerance", characteristic: "flatness", id, ref, value }`: `pmi.flatness(id, ref, value)`;
 * - `{ kind: "geometric_tolerance", characteristic: "position", id, ref, value, datums, diameterZone }`:
 *   `pmi.position(id, ref, value, datums=[...], diameter_zone=True)`, its zone said either way (the
 *   engine's is a diameter's unless the call says it is not).
 *
 * A tolerance is written only where one is given. `label`, where given, is its `label=`, and
 * `presentation` its `pmi.place`. Null for a call that lacks what its kind needs: nothing is filled in.
 */
export function pmiCallText(call) {
  if (!call?.id) return null;
  const tail = [call.label ? `label=${pyString(call.label)}` : null, call.presentation ? `presentation=${pmiPlaceText(call.presentation)}` : null];
  const args = (...items) => [...items, ...tail].filter(item => item !== null && item !== undefined).join(", ");
  if (call.kind === "datum") {
    if (!call.ref || !call.letter) return null;
    return `pmi.datum(${args(pyString(call.letter), pyString(call.ref))})`;
  }
  if (call.kind === "dimension") {
    const tolerance = call.tolerance ? `tolerance=${pmiPlusMinusText(call.tolerance)}` : null;
    if (call.type === "distance") {
      if (!call.from || !call.to) return null;
      if (call.basic) return call.tolerance ? null : `pmi.basic(${args(pyString(call.id), pyString(call.from), pyString(call.to))})`;
      return `pmi.distance(${args(pyString(call.id), pyString(call.from), pyString(call.to), tolerance)})`;
    }
    if (call.type === "diameter") {
      if (!call.ref) return null;
      return `pmi.diameter(${args(pyString(call.id), pyString(call.ref), tolerance)})`;
    }
    return null;
  }
  if (call.kind === "geometric_tolerance") {
    if (!call.ref || finite(call.value) === null || !(call.value > 0)) return null;
    if (call.characteristic === "flatness") return `pmi.flatness(${args(pyString(call.id), pyString(call.ref), pyNumber(call.value))})`;
    if (call.characteristic === "position") {
      const datums = (call.datums || []).filter(Boolean);
      return `pmi.position(${args(pyString(call.id), pyString(call.ref), pyNumber(call.value),
        datums.length ? `datums=[${datums.map(pyString).join(", ")}]` : null, `diameter_zone=${call.diameterZone ? "True" : "False"}`)})`;
    }
  }
  return null;
}

/**
 * An entry the document holds as the call that declares it, with `changes` over its values
 * (`{ tolerance, value, letter, datums, diameterZone, presentation }`, each where given; a tolerance
 * of null takes it away) and its label as it is: what an edit in the viewer asks the code to become.
 * Its references are the canonical refs this build resolved them to (`ref`), which name the same
 * elements however the code wrote them (a variable holding a face, say); the code's own where none
 * resolved.
 */
export function pmiEntryCall(entry, changes = {}) {
  const given = key => (Object.prototype.hasOwnProperty.call(changes, key) ? changes[key] : undefined);
  const refOf = (role) => {
    const found = entry.refs.find(ref => ref.role === role);
    return (found?.status === "ok" ? found.ref : found?.written) || "";
  };
  const presentation = given("presentation") === undefined ? entry.presentation : given("presentation");
  const label = entry.label || null;
  if (entry.kind === "datum") return { kind: "datum", id: entry.id, letter: given("letter") ?? entry.datum.letter, ref: refOf("feature"), label, presentation };
  if (entry.kind === "dimension") {
    const tolerance = given("tolerance") === undefined ? entry.dimension.tolerance : given("tolerance");
    if (entry.dimension.basic) {
      return { kind: "dimension", type: "distance", basic: true, id: entry.id, from: refOf("from"), to: refOf("to"), tolerance: null, label, presentation };
    }
    return entry.dimension.type === "distance"
      ? { kind: "dimension", type: "distance", id: entry.id, from: refOf("from"), to: refOf("to"), tolerance, label, presentation }
      : { kind: "dimension", type: "diameter", id: entry.id, ref: refOf("feature"), tolerance, label, presentation };
  }
  const tolerance = entry.tolerance;
  return { kind: "geometric_tolerance", characteristic: tolerance.characteristic, id: entry.id, ref: refOf("feature"),
    value: given("value") ?? tolerance.value, datums: given("datums") ?? tolerance.datums,
    diameterZone: given("diameterZone") ?? tolerance.zone === "diameter", label, presentation };
}

/** An id for a new annotation that none of `taken` (its part's) has: `stem`, else `stem-2`, `stem-3`... */
export function pmiFreshId(stem, taken) {
  const held = new Set(taken);
  if (!held.has(stem)) return stem;
  for (let n = 2; ; n += 1) if (!held.has(`${stem}-${n}`)) return `${stem}-${n}`;
}

/**
 * What an edit sets, each as the call writes it: `tolerance=...` (or that it has none), its value,
 * `datums=[...]`, `presentation=...` (or that it is placed beside its feature).
 */
function pmiEditSettings(values) {
  const set = [];
  if (Object.prototype.hasOwnProperty.call(values, "tolerance")) set.push(values.tolerance ? `tolerance=${pmiPlusMinusText(values.tolerance)}` : "no tolerance (drop tolerance=)");
  if (Object.prototype.hasOwnProperty.call(values, "value")) set.push(`its tolerance value ${pyNumber(values.value)}`);
  if (Object.prototype.hasOwnProperty.call(values, "datums")) set.push(`datums=[${values.datums.map(pyString).join(", ")}]`);
  if (Object.prototype.hasOwnProperty.call(values, "presentation")) set.push(values.presentation ? `presentation=${pmiPlaceText(values.presentation)}` : "no placement (drop presentation=)");
  return set;
}

/**
 * A change asked for in the viewer as the request Quick Edit hands the agent: one paragraph of what
 * to do to the `pmi.annotate(...)` call of its part (`partName`, where the part has one), then the
 * call itself, exactly. `change`: a new annotation (`{ kind: "add", part, partName, id, call }`) or an
 * edit of one the document holds (`{ kind: "edit", part, partName, id, values, call, placementOnly }`:
 * what it sets, and the call it makes), `id` the author's. "" for a call that lacks what its kind needs.
 */
export function pmiChangeRequest(change) {
  const call = pmiCallText(change.call);
  if (!call) return "";
  const annotate = change.partName ? `the pmi.annotate(...) call of the model's part ${pyString(change.partName)}` : "the model's pmi.annotate(...) call";
  if (change.kind === "add") return `Add this PMI to ${annotate} (from cadgen.engine import pmi):\n${call}`;
  const what = change.placementOnly
    ? `Move the PMI "${change.id}" in ${annotate}, its placement only (what it says is unchanged)`
    : `Change the PMI "${change.id}" in ${annotate}`;
  return `${what}: ${pmiEditSettings(change.values).join("; ")}. Keep its references as the code writes them. `
    + `The whole call, its references as this build resolves them:\n${call}`;
}

/**
 * Whether the document now says what `change` asked for, so it has nothing left to ask: a new
 * annotation its part holds, an edit whose call -- its values, zone, label and placement -- is the
 * one the part's entry of that id makes now. What the viewer drops once a build has it.
 */
export function pmiChangeSettled(change, entries) {
  const entry = entries.find(item => item.part === change.part && item.id === change.id);
  if (change.kind === "add") return Boolean(entry);
  return Boolean(entry?.supported) && pmiCallText(pmiEntryCall(entry)) === pmiCallText(change.call);
}
