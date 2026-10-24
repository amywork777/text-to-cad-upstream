// An engine document's PMI as the viewer reads, says and asks for it (`xbfPmi.js`): the entries
// `structure.pmi` carries, read defensively; the callout each says; and the `cadgen.engine.pmi` call
// a change in the viewer is, which Quick Edit hands the agent to write into the model.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  assert.deepEqual(thickness.dimension, { type: "distance", basic: false, nominal: 4.000000001, unit: "mm", source: "geometry", tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } });
  assert.deepEqual(thickness.refs.map(item => [item.role, item.ref, item.status]), [["from", BOTTOM, "ok"], ["to", TOP, "ok"]]);
  assert.deepEqual(thickness.presentation, { anchor: [20, 0, -2], offset: [6, 0, 2] });
  assert.deepEqual(read[4].tolerance, { characteristic: "position", value: 0.1, unit: "mm", zone: "diameter", modifier: null, datums: ["A"] });
});

test("a basic dimension is an exact distance: boxed, with no tolerance, made by pmi.basic", () => {
  const SIDE = "plate/f:bracket.make_box1.1;M:bracket.fillet1";
  const [basic] = readXbfPmi({ pmi: [{ id: "hole-from-side", kind: "dimension", status: "ok", refs: [ref("from", SIDE), ref("to", HOLE)],
    // A tolerance a document puts on one is not read: it is exact.
    dimension: { type: "distance", basic: true, nominal: { value: 20, unit: "mm", source: "geometry" }, tolerance: { type: "plus_minus", upper: 0.1, lower: -0.1 } },
    presentation: { anchor: [-10, -10, 2], offset: [0, -6, 0] } }] });
  assert.equal(basic.supported, true);
  assert.deepEqual([basic.dimension.basic, basic.dimension.tolerance], [true, null]);
  const said = pmiCallout(basic);
  assert.deepEqual([said.basic, said.nominal, said.tolerance, said.title, said.text], [true, "20", null, "Basic distance", "20 basic"]);
  assert.equal(pmiCallText(pmiEntryCall(basic, { presentation: null })), `pmi.basic("hole-from-side", "${SIDE}", "${HOLE}")`);
  assert.equal(pmiCallText(pmiEntryCall(basic)),
    `pmi.basic("hole-from-side", "${SIDE}", "${HOLE}", presentation=pmi.place(anchor=(-10, -10, 2), offset=(0, -6, 0)))`);
  // Exact: a tolerance given one makes no call, rather than one the engine refuses.
  assert.equal(pmiCallText({ kind: "dimension", type: "distance", basic: true, id: "b", from: SIDE, to: HOLE, tolerance: { type: "plus_minus", upper: 0.1, lower: -0.1 } }), null);
  // A basic of another type is told, not drawn.
  const [diameter] = readXbfPmi({ pmi: [{ id: "d", kind: "dimension", status: "ok", refs: [], dimension: { type: "diameter", basic: true, nominal: { value: 8 }, tolerance: null } }] });
  assert.match(diameter.unsupported, /basic diameter/);
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

test("one the viewer does not draw says the engine's reason where it gives one, the viewer's own where not", () => {
  const read = readXbfPmi({ pmi: [
    { id: "profile", kind: "unsupported", status: "ok", refs: [], xcaf_type: "XCAFDimTolObjects_GeomToleranceType_ProfileOfSurface",
      reason: "profile of surface is not a characteristic this holds; it has modifiers" },
    { id: "edge", kind: "unsupported", status: "ok", refs: [], xcaf_type: "XCAFDimTolObjects_DatumObject", reason: null },
    // What is drawn is the viewer's to say: a reason given beside one it draws makes it no less drawn.
    { id: "A", kind: "datum", status: "ok", refs: [], datum: { letter: "A" }, reason: "linked to an edge" },
  ] });
  assert.deepEqual(read.map(entry => [entry.id, entry.supported, entry.unsupported]), [
    ["profile", false, "profile of surface is not a characteristic this holds; it has modifiers"],
    ["edge", false, "XCAFDimTolObjects_DatumObject is not one the viewer draws"],
    ["A", true, ""]]);
});

test("a build's warnings on an annotation are read as served, and a file's none are none", () => {
  const warned = "f:edit_plate.cut.1;M:edit_plate.body named a cylinder face on the last build and names a plane face now: another face "
    + "than the annotation was made on, measured as it is. Point the ref at the face meant, or remove the annotation";
  const read = readXbfPmi({ pmi: [
    { id: "hole-from-left", kind: "datum", status: "ok", refs: [], datum: { letter: "B" }, warnings: [warned, 4, ""] },
    { id: "A", kind: "datum", status: "ok", refs: [], datum: { letter: "A" }, warnings: [] },
    { id: "C", kind: "datum", status: "ok", refs: [], datum: { letter: "C" } },
  ] });
  assert.deepEqual(read.map(entry => entry.warnings), [[warned], [], []]);
});

test("a dimension whose reference broke has no nominal, and is said as unknown, not unsupported", () => {
  const [broken] = readXbfPmi({ pmi: [{ id: "thickness", kind: "dimension", status: "missing", problem: null,
    refs: [{ role: "from", ref: BOTTOM, written: BOTTOM, status: "ok" }, { role: "to", ref: "plate/f:gone", written: "plate/f:gone", status: "missing", candidates: null }],
    dimension: { type: "distance", nominal: null, tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } }, presentation: { anchor: [0, 0, -2], offset: [8, 0, 2] } }] });
  assert.equal(broken.supported, true);
  assert.equal(pmiCallout(broken).text, "? ±0.2");
  // The engine's foreign entries name no written ref: theirs is read as nothing, never "null".
  const [foreign] = readXbfPmi({ pmi: [{ id: "datum", kind: "datum", status: "ok", refs: [{ role: "feature", ref: TOP, written: null, status: "ok", candidates: null }], datum: { letter: "B" } }] });
  assert.deepEqual([foreign.refs[0].ref, foreign.refs[0].written], [TOP, TOP]);
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

test("a nominal is written at its tolerance's places or at what it needs, whichever is more", () => {
  const said = (type, value, tolerance, basic = false) => pmiCallout(readXbfPmi({ pmi: [{ id: "d", kind: "dimension", status: "ok", refs: [],
    dimension: { type, basic, nominal: { value, unit: "mm", source: "geometry" }, tolerance } }] })[0]).text;
  const plusMinus = value => ({ type: "plus_minus", upper: value, lower: -value });
  assert.equal(said("diameter", 6.35, plusMinus(0.1)), "⌀6.35 ±0.1");
  assert.equal(said("distance", 25.4, plusMinus(0.05)), "25.40 ±0.05");
  // With no tolerance, and exact: what the value needs, up to four places.
  assert.equal(said("distance", 3.175, null, true), "3.175 basic");
  assert.equal(said("distance", 12.345678, null), "12.3457");
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
  const change = { kind: "edit", part: null, id: "thickness", values, call: pmiEntryCall(thickness, values) };
  assert.equal(pmiChangeSettled(change, read), false);
  const built = readXbfPmi({ pmi: PMI.map(item => (item.id === "thickness" ? { ...item, dimension: { ...item.dimension, tolerance: values.tolerance } } : item)) });
  assert.equal(pmiChangeSettled(change, built), true);
  assert.equal(pmiChangeSettled({ kind: "add", part: null, id: "flatness", call: {} }, read), false);
  assert.equal(pmiChangeSettled({ kind: "add", part: null, id: "top-flat", call: {} }, read), true);
  // An edit of an annotation the document no longer holds is not settled: it is the person's to drop.
  assert.equal(pmiChangeSettled({ ...change, id: "gone" }, read), false);
});

test("an edit keeps what the code said beside its values: a position's zone, round or not, and its label", () => {
  const position = (item = {}) => readXbfPmi({ pmi: [{ id: "hole-pos", kind: "geometric_tolerance", label: "Hole location", status: "ok",
    refs: [ref("feature", HOLE)], geometric_tolerance: { characteristic: "position", value: 0.1, unit: "mm", zone: null, modifier: null, datums: ["A"] }, ...item }] });
  const values = { value: 0.2 };
  const call = pmiEntryCall(position()[0], values);
  // A zone that is not a diameter's says so: the engine's position takes a diameter's unless told.
  assert.equal(pmiCallText(call), `pmi.position("hole-pos", "${HOLE}", 0.2, datums=["A"], diameter_zone=False, label="Hole location")`);
  const change = { kind: "edit", part: null, id: "hole-pos", values, call };
  const built = gdt => position({ geometric_tolerance: { characteristic: "position", value: 0.2, unit: "mm", zone: null, datums: ["A"], ...gdt } });
  assert.equal(pmiChangeSettled(change, built({})), true);
  // A build that made the zone round, or dropped the label, has not done what was asked.
  assert.equal(pmiChangeSettled(change, built({ zone: "diameter" })), false);
  assert.equal(pmiChangeSettled(change, built({}).map(entry => ({ ...entry, label: "" }))), false);
});

test("an id is unique on its part only: two parts' datum A are two entries, each asked for by its part and its own id", () => {
  const PEG_END = "bracket/peg/f:bracket.make_cylinder1.2";
  const datum = (part, at) => ({ id: "A", kind: "datum", status: "ok", part, refs: [ref("feature", at)], datum: { letter: "A" } });
  const raw = [datum(0, BOTTOM), datum(1, PEG_END)];
  const read = readXbfPmi({ pmi: raw });
  assert.deepEqual(read.map(entry => [entry.key, entry.id, entry.part]), [["0:A", "A", 0], ["1:A", "A", 1]]);
  // One the document repeats on a part is kept apart by its place.
  assert.deepEqual(readXbfPmi({ pmi: [...raw, datum(1, PEG_END)] }).map(entry => entry.key), ["0:A", "1:A", "1:A#3"]);
  // The peg's moved: asked for by its own id, in its part's call, and settled by the peg's alone.
  const presentation = { anchor: [0, 0, 8], offset: [0, 0, 6] };
  const values = { presentation };
  const change = { kind: "edit", part: 1, partName: "peg", id: "A", values, call: pmiEntryCall(read[1], values), placementOnly: true };
  assert.match(pmiChangeRequest(change), /^Move the PMI "A" in the pmi\.annotate\(\.\.\.\) call of the model's part "peg", its placement only/);
  const placed = part => readXbfPmi({ pmi: raw.map(item => (item.part === part ? { ...item, presentation } : item)) });
  assert.equal(pmiChangeSettled(change, placed(1)), true);
  assert.equal(pmiChangeSettled(change, placed(0)), false, "the plate's A placed there is not the peg's");
  // A new one is its part's: the plate's A is not the peg's B, nor the peg's A the plate's.
  assert.equal(pmiChangeSettled({ kind: "add", part: 0, id: "A", call: {} }, readXbfPmi({ pmi: [datum(1, PEG_END)] })), false);
  assert.match(pmiChangeRequest({ kind: "add", part: 0, partName: "plate", id: "B", call: { kind: "datum", id: "B", letter: "B", ref: TOP } }),
    /^Add this PMI to the pmi\.annotate\(\.\.\.\) call of the model's part "plate" \(from cadgen\.engine import pmi\):\npmi\.datum\("B"/);
});

// The engine's own, as it served a plate built with `cadgen.engine.pmi` (`__fixtures__/pmi_plate`,
// which its `make_fixtures.py` builds and captures again): as made (v1), and after an edit put a
// square cut where the hole was (v3): the hole's name now on a flat face, which a diameter, a
// position and a distance from a face square to it cannot stand on, and a distance from a parallel
// face measures to as it now is (the build warns that its kind changed; a file carries no warning).
test("the PMI the engine serves reads whole, and a reference an edit left on the wrong kind of face is invalid", () => {
  const served = version => JSON.parse(readFileSync(new URL(`./__fixtures__/pmi_plate/${version}/structure.json`, import.meta.url), "utf8"));
  const made = readXbfPmi(served("v1"));
  assert.deepEqual(made.map(entry => [entry.id, entry.supported, entry.status, entry.part]), [
    ["A", true, "ok", 0], ["thickness", true, "ok", 0], ["hole-diameter", true, "ok", 0], ["hole-from-front", true, "ok", 0],
    ["hole-from-left", true, "ok", 0], ["top-flatness", true, "ok", 0], ["hole-position", true, "ok", 0]]);
  assert.deepEqual(made.map(entry => pmiCallout(entry).text), ["Datum A", "10.0 ±0.2", "⌀10.0 +0.1/0", "30 basic", "50 basic", "Flatness 0.05", "Position ⌀0.1 | A"]);
  const cut = readXbfPmi(served("v3"));
  // What broke is still its part's: linked to no geometry, known by the same key.
  assert.deepEqual(cut.map(entry => [entry.key, entry.status, entry.warnings]), [
    ["0:A", "ok", []], ["0:thickness", "ok", []], ["0:hole-diameter", "invalid", []], ["0:hole-from-front", "invalid", []],
    ["0:hole-from-left", "ok", []], ["0:top-flatness", "ok", []], ["0:hole-position", "invalid", []]]);
  const hole = cut.find(entry => entry.id === "hole-diameter");
  assert.deepEqual([hole.supported, hole.dimension.nominal], [true, null]);
  assert.match(pmiStatusText(hole), /is a plane face; a diameter is on a cylinder face/);
  assert.match(pmiStatusText(cut.find(entry => entry.id === "hole-position")), /is a plane face; a position is on a cylinder face/);
  const fromFront = cut.find(entry => entry.id === "hole-from-front");
  assert.deepEqual([fromFront.dimension.basic, pmiCallout(fromFront).text], [true, "? basic"]);
  assert.match(pmiStatusText(fromFront), /are not parallel planes/);
  // One that can stand on the cut's flat face is measured to it.
  const fromLeft = cut.find(entry => entry.id === "hole-from-left");
  assert.deepEqual([fromLeft.dimension.nominal, pmiCallout(fromLeft).text, pmiStatusText(fromLeft)], [44, "44 basic", ""]);
});
