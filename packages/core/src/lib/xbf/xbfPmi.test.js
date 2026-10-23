// An engine document's PMI as the viewer reads, says and asks for it (`xbfPmi.js`): the entries
// `structure.pmi` carries, read defensively; the callout each says; and the `cadgen.engine.pmi` call
// a change in the viewer is, which Quick Edit hands the agent to write into the model.
import assert from "node:assert/strict";
import test from "node:test";

import { pmiCallText, pmiCallout, pmiChangeRequest, pmiChangeSettled, pmiEntryCall, pmiFreshId, pmiNumber, pmiPlaceText, pmiStatusText, pmiToleranceText, pyNumber, readXbfPmi } from "./xbfPmi.js";

const TOP = "plate/f:bracket.fillet1~d3f70920d846";
const BOTTOM = "plate/f:bracket.fillet1~908aee34f872";
const HOLE = "plate/f:bracket.make_cylinder1.1;M:bracket.cut1";
const ref = (role, at, extra = {}) => ({ role, ref: at, written: at, status: "ok", candidates: null, ...extra });

// The supported subset, as `cadgen.engine.pmi` serves it.
const PMI = [
  { id: "A", kind: "datum", label: null, status: "ok", problem: null, refs: [ref("feature", BOTTOM)], datum: { letter: "A" }, presentation: null, xcaf_type: null },
  { id: "thickness", kind: "dimension", label: null, status: "ok", problem: null, refs: [ref("from", BOTTOM), ref("to", TOP)],
    dimension: { type: "distance", nominal: { value: 4.000000001, unit: "mm", source: "geometry" }, tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } },
    presentation: { anchor: [20, 0, -2], offset: [6, 0, 2] }, xcaf_type: null },
  { id: "hole-dia", kind: "dimension", label: null, status: "ok", problem: null, refs: [ref("feature", HOLE)],
    dimension: { type: "diameter", nominal: { value: 8, unit: "mm", source: "geometry" }, tolerance: { type: "plus_minus", upper: 0.1, lower: 0 } },
    presentation: null, xcaf_type: null },
  { id: "top-flat", kind: "geometric_tolerance", label: null, status: "ok", problem: null, refs: [ref("feature", TOP)],
    geometric_tolerance: { characteristic: "flatness", value: 0.05, unit: "mm", zone: null, modifier: null, datums: [] }, presentation: null, xcaf_type: null },
  { id: "hole-pos", kind: "geometric_tolerance", label: null, status: "ok", problem: null, refs: [ref("feature", HOLE)],
    geometric_tolerance: { characteristic: "position", value: 0.1, unit: "mm", zone: "diameter", modifier: null, datums: ["A"] }, presentation: null, xcaf_type: null },
];

test("the document's PMI is read as it is served, and a document without any has none", () => {
  assert.deepEqual(readXbfPmi({ name: "bracket" }), []);
  const read = readXbfPmi({ pmi: PMI });
  assert.deepEqual(read.map(entry => [entry.id, entry.kind, entry.supported]), [
    ["A", "datum", true], ["thickness", "dimension", true], ["hole-dia", "dimension", true], ["top-flat", "geometric_tolerance", true], ["hole-pos", "geometric_tolerance", true]]);
  const thickness = read[1];
  assert.deepEqual(thickness.dimension, { type: "distance", nominal: 4.000000001, unit: "mm", source: "geometry", tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } });
  assert.deepEqual(thickness.refs.map(item => [item.role, item.ref, item.status]), [["from", BOTTOM, "ok"], ["to", TOP, "ok"]]);
  assert.deepEqual(thickness.presentation, { anchor: [20, 0, -2], offset: [6, 0, 2] });
  assert.deepEqual(read[4].tolerance, { characteristic: "position", value: 0.1, unit: "mm", zone: "diameter", modifier: null, datums: ["A"] });
});

test("an entry the viewer does not draw is kept and says why, never dropped or guessed", () => {
  const read = readXbfPmi({ pmi: [
    { id: "profile", kind: "unsupported", status: "ok", refs: [], presentation: null, xcaf_type: "XCAFDimTolObjects_GeomToleranceType_ProfileOfSurface" },
    { id: "angle", kind: "dimension", status: "ok", refs: [], dimension: { type: "angle", nominal: { value: 90, unit: "deg" }, tolerance: null } },
    { id: "runout", kind: "geometric_tolerance", status: "ok", refs: [], geometric_tolerance: { characteristic: "total_runout", value: 0.1, datums: [] } },
    { id: "bad", kind: "dimension", status: "ok", refs: [], dimension: { type: "distance", nominal: { value: "4" }, tolerance: null } },
  ] });
  assert.deepEqual(read.map(entry => [entry.id, entry.supported]), [["profile", false], ["angle", false], ["runout", false], ["bad", false]]);
  assert.match(read[0].unsupported, /ProfileOfSurface is not one the viewer draws/);
  assert.match(read[1].unsupported, /angle dimension/);
  assert.match(read[2].unsupported, /total_runout/);
  // A nominal that is not a number is no nominal: the viewer never reads one into it.
  assert.equal(read[3].dimension.nominal, null);
  assert.match(read[3].unsupported, /no nominal/);
});

test("a tolerance the code did not supply is none, and a malformed one is none too", () => {
  const read = readXbfPmi({ pmi: [
    { id: "a", kind: "dimension", status: "ok", refs: [], dimension: { type: "distance", nominal: { value: 4, unit: "mm" }, tolerance: null } },
    { id: "b", kind: "dimension", status: "ok", refs: [], dimension: { type: "distance", nominal: { value: 4, unit: "mm" }, tolerance: { type: "plus_minus", upper: 0.1 } } },
  ] });
  assert.equal(read[0].dimension.tolerance, null);
  assert.equal(read[1].dimension.tolerance, null);
  assert.equal(pmiCallout(read[0]).text, "4");
});

test("a callout says the nominal at the tolerance's places, and each kind as a drawing writes it", () => {
  const [datum, thickness, diameter, flatness, position] = readXbfPmi({ pmi: PMI }).map(pmiCallout);
  assert.deepEqual([datum.kind, datum.letter, datum.text], ["datum", "A", "Datum A"]);
  assert.equal(thickness.text, "4.0 ±0.2");
  assert.deepEqual([thickness.tolerance.upper, thickness.tolerance.lower], ["+0.2", "−0.2"]);
  assert.equal(diameter.text, "⌀8.0 +0.1/0");
  assert.equal(diameter.diameter, true);
  assert.deepEqual([flatness.kind, flatness.characteristic, flatness.value, flatness.datums], ["frame", "flatness", "0.05", []]);
  assert.equal(flatness.text, "Flatness 0.05");
  assert.equal(position.text, "Position ⌀0.1 | A");
});

test("tolerances and numbers are written with true minus signs and one count of places", () => {
  assert.deepEqual(pmiToleranceText({ upper: 0.05, lower: -0.1 }), { symmetric: false, text: "+0.05/−0.10", upper: "+0.05", lower: "−0.10", places: 2 });
  assert.equal(pmiToleranceText({ upper: 0, lower: -0.1 }).text, "0/−0.1");
  assert.equal(pmiToleranceText(null), null);
  assert.equal(pmiNumber(-0.0000001, 2), "0.00");
  assert.equal(pmiNumber(12.5), "12.5");
});

test("a reference that names nothing, or several things, is said in words", () => {
  const [missing, ambiguous] = readXbfPmi({ pmi: [
    { id: "top-flat", kind: "geometric_tolerance", status: "missing", problem: null, refs: [{ role: "feature", ref: "plate/f:gone", written: "plate/f:gone", status: "missing", candidates: null }],
      geometric_tolerance: { characteristic: "flatness", value: 0.05, unit: "mm", datums: [] }, presentation: { anchor: [0, 0, 2], offset: [0, 0, 6] } },
    { id: "A", kind: "datum", status: "ambiguous", problem: null, refs: [{ role: "feature", ref: "face 3", written: "face 3", status: "ambiguous", candidates: [TOP, BOTTOM] }],
      datum: { letter: "A" } },
  ] });
  assert.equal(missing.status, "missing");
  assert.equal(pmiStatusText(missing), "plate/f:gone names nothing in this version");
  assert.deepEqual(missing.presentation, { anchor: [0, 0, 2], offset: [0, 0, 6] });
  assert.equal(pmiStatusText(ambiguous), "face 3 names 2 elements");
  assert.deepEqual(ambiguous.refs[0].candidates, [TOP, BOTTOM]);
  // The engine's own words win where it gives them.
  assert.equal(pmiStatusText({ status: "missing", problem: "plate.body.6 is now f:plate.body.6", refs: [] }), "plate.body.6 is now f:plate.body.6");
  assert.equal(pmiStatusText({ status: "ok", refs: [] }), "");
});

test("a new annotation is the cadgen.engine.pmi call that declares it, its refs verbatim", () => {
  assert.equal(pmiCallText({ kind: "datum", id: "B", letter: "B", ref: TOP }), `pmi.datum("B", "${TOP}")`);
  assert.equal(pmiCallText({ kind: "dimension", type: "distance", id: "thickness", from: BOTTOM, to: TOP, tolerance: { upper: 0.2, lower: -0.2 } }),
    `pmi.distance("thickness", "${BOTTOM}", "${TOP}", tolerance=pmi.plus_minus(0.2))`);
  assert.equal(pmiCallText({ kind: "dimension", type: "diameter", id: "hole-dia", ref: HOLE, tolerance: { upper: 0.1, lower: 0 } }),
    `pmi.diameter("hole-dia", "${HOLE}", tolerance=pmi.plus_minus(0.1, 0))`);
  // No tolerance given, none written: a dimension is not toleranced by the viewer.
  assert.equal(pmiCallText({ kind: "dimension", type: "diameter", id: "hole-dia", ref: HOLE, tolerance: null }), `pmi.diameter("hole-dia", "${HOLE}")`);
  assert.equal(pmiCallText({ kind: "geometric_tolerance", characteristic: "flatness", id: "top-flat", ref: TOP, value: 0.05 }), `pmi.flatness("top-flat", "${TOP}", 0.05)`);
  assert.equal(pmiCallText({ kind: "geometric_tolerance", characteristic: "position", id: "hole-pos", ref: HOLE, value: 0.1, datums: ["A"], diameterZone: true }),
    `pmi.position("hole-pos", "${HOLE}", 0.1, datums=["A"], diameter_zone=True)`);
  // What a kind needs and lacks is never filled in.
  assert.equal(pmiCallText({ kind: "geometric_tolerance", characteristic: "flatness", id: "top-flat", ref: TOP, value: null }), null);
  assert.equal(pmiCallText({ kind: "dimension", type: "distance", id: "x", from: BOTTOM, to: "" }), null);
  assert.equal(pmiCallText({ kind: "datum", id: "", letter: "A", ref: TOP }), null);
});

test("an edit names its references as this build resolves them and changes only what was changed", () => {
  const [, thickness, , flatness] = readXbfPmi({ pmi: PMI });
  assert.equal(pmiCallText(pmiEntryCall(thickness, { tolerance: { upper: 0.1, lower: -0.05 } })),
    `pmi.distance("thickness", "${BOTTOM}", "${TOP}", tolerance=pmi.plus_minus(0.1, -0.05), presentation=pmi.place(anchor=(20, 0, -2), offset=(6, 0, 2)))`);
  assert.equal(pmiCallText(pmiEntryCall(thickness, { tolerance: null, presentation: null })), `pmi.distance("thickness", "${BOTTOM}", "${TOP}")`);
  assert.equal(pmiCallText(pmiEntryCall(flatness, { value: 0.02 })), `pmi.flatness("top-flat", "${TOP}", 0.02)`);
  // A placement is where it is drawn: the call says the same, placed.
  assert.equal(pmiCallText(pmiEntryCall(flatness, { presentation: { anchor: [1.23456, 0, 2], offset: [0, -0.00001, 8] } })),
    `pmi.flatness("top-flat", "${TOP}", 0.05, presentation=pmi.place(anchor=(1.2346, 0, 2), offset=(0, 0, 8)))`);
});

test("numbers are written without float noise, and fresh ids never collide", () => {
  assert.equal(pyNumber(0.1 + 0.2), "0.3");
  assert.equal(pyNumber(-0.00001), "0");
  assert.equal(pmiPlaceText({ anchor: [1, 2, 3], offset: [0.5, 0, -1] }), "pmi.place(anchor=(1, 2, 3), offset=(0.5, 0, -1))");
  assert.equal(pmiFreshId("flatness", ["top-flat"]), "flatness");
  assert.equal(pmiFreshId("flatness", ["flatness", "flatness-2"]), "flatness-3");
});

test("a reference the code wrote as a face of the body is called by its canonical ref, which names the same face", () => {
  const [entry] = readXbfPmi({ pmi: [{ id: "top-flat", kind: "geometric_tolerance", status: "ok", refs: [{ role: "feature", ref: TOP, written: "face 2", status: "ok" }],
    geometric_tolerance: { characteristic: "flatness", value: 0.05, unit: "mm", datums: [] } }] });
  assert.equal(pmiCallText(pmiEntryCall(entry, { value: 0.02 })), `pmi.flatness("top-flat", "${TOP}", 0.02)`);
  // One that names nothing now is called as the code wrote it: there is nothing else to call it.
  const [broken] = readXbfPmi({ pmi: [{ id: "top-flat", kind: "geometric_tolerance", status: "missing", refs: [{ role: "feature", ref: "plate/f:gone", written: "plate/f:gone", status: "missing" }],
    geometric_tolerance: { characteristic: "flatness", value: 0.05, unit: "mm", datums: [] } }] });
  assert.equal(pmiCallText(pmiEntryCall(broken)), `pmi.flatness("top-flat", "plate/f:gone", 0.05)`);
});

test("a change goes to the agent as what to do to the model's pmi.annotate call, then the call exactly", () => {
  const [, thickness] = readXbfPmi({ pmi: PMI });
  const add = { kind: "geometric_tolerance", characteristic: "flatness", id: "flatness", ref: BOTTOM, value: 0.02 };
  assert.equal(pmiChangeRequest({ kind: "add", call: add }),
    `Add this PMI to the model's pmi.annotate(...) call (from cadgen.engine import pmi):\npmi.flatness("flatness", "${BOTTOM}", 0.02)`);
  const values = { tolerance: { upper: 0.1, lower: -0.05 } };
  assert.equal(pmiChangeRequest({ kind: "edit", id: "thickness", values, call: pmiEntryCall(thickness, values), placementOnly: false }),
    `Change the PMI "thickness" in the model's pmi.annotate(...) call: tolerance=pmi.plus_minus(0.1, -0.05). Keep its references as the code writes them. `
    + `The whole call, its references as this build resolves them:\npmi.distance("thickness", "${BOTTOM}", "${TOP}", tolerance=pmi.plus_minus(0.1, -0.05), presentation=pmi.place(anchor=(20, 0, -2), offset=(6, 0, 2)))`);
  const moved = { presentation: { anchor: [20, 0, -2], offset: [10, 0, 2] } };
  assert.match(pmiChangeRequest({ kind: "edit", id: "thickness", values: moved, call: pmiEntryCall(thickness, moved), placementOnly: true }),
    /^Move the PMI "thickness" in the model's pmi.annotate\(\.\.\.\) call, its placement only \(what it says is unchanged\): presentation=pmi\.place\(anchor=\(20, 0, -2\), offset=\(10, 0, 2\)\)\./);
  assert.equal(pmiChangeRequest({ kind: "add", call: { ...add, value: null } }), "");
});

test("a change the document now says is settled, and one it does not yet say is not", () => {
  const read = readXbfPmi({ pmi: PMI });
  const thickness = read[1];
  const values = { tolerance: { type: "plus_minus", upper: 0.1, lower: -0.05 } };
  const change = { kind: "edit", id: "thickness", values, call: pmiEntryCall(thickness, values) };
  assert.equal(pmiChangeSettled(change, read), false);
  const built = readXbfPmi({ pmi: PMI.map(item => (item.id === "thickness" ? { ...item, dimension: { ...item.dimension, tolerance: values.tolerance } } : item)) });
  assert.equal(pmiChangeSettled(change, built), true);
  assert.equal(pmiChangeSettled({ kind: "add", id: "flatness", call: {} }, read), false);
  assert.equal(pmiChangeSettled({ kind: "add", id: "top-flat", call: {} }, read), true);
  // An edit of an annotation the document no longer holds is not settled: it is the person's to drop.
  assert.equal(pmiChangeSettled({ ...change, id: "gone" }, read), false);
});
