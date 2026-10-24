// What a new annotation can be made of the faces Select has picked (`pmiCreate.js`): each kind of
// the supported subset offered only where the pick makes one, with what it needs where it does not,
// starting as its call with the picked faces' refs, a fresh id, and no tolerance filled in.
import assert from "node:assert/strict";
import test from "node:test";
import { readXbfPmi } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { newPmiName, nextDatumLetter, parseToleranceInput, pmiCreateOptions, toggleDatum } from "./pmiCreate.js";

const TOP = { id: "i0/face/2", part: 0, ref: "plate/f:top", surface: { type: "plane", normal: [0, 0, 1], origin: [0, 0, 2] } };
const BOTTOM = { id: "i0/face/5", part: 0, ref: "plate/f:bottom", surface: { type: "plane", normal: [0, 0, -1], origin: [0, 0, -2] } };
const SIDE = { id: "i0/face/1", part: 0, ref: "plate/f:side", surface: { type: "plane", normal: [-1, 0, 0], origin: [-20, 0, 0] } };
const HOLE = { id: "i0/face/11", part: 0, ref: "plate/f:hole", surface: { type: "cylinder", axis: [0, 0, 1], origin: [0, 0, 0], radius: 4 } };
const PEG = { id: "i1/face/1", part: 1, ref: "peg/f:wall", surface: { type: "cylinder", axis: [0, 0, -1], origin: [12, 0, 8], radius: 3 } };
const PART = { id: "i0", part: 0, ref: "", surface: null };
const available = options => options.filter(option => option.available).map(option => option.kind);
const of = (options, kind) => options.find(option => option.kind === kind);

test("one flat face makes a datum or a flatness; two parallel ones a distance; a round one a datum or a diameter", () => {
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP], entries: [] })), ["datum", "flatness"]);
  const pair = pmiCreateOptions({ picked: [BOTTOM, TOP], entries: [] });
  assert.deepEqual(available(pair), ["distance", "basic"]);
  assert.deepEqual(of(pair, "distance").call, { kind: "dimension", type: "distance", id: "distance", from: BOTTOM.ref, to: TOP.ref, tolerance: null });
  assert.equal(of(pair, "distance").nominal, 4);
  // A datum stands on a planar or a cylindrical face, as the engine's does.
  const round = pmiCreateOptions({ picked: [HOLE], entries: [] });
  assert.deepEqual(available(round), ["datum", "diameter"]);
  assert.deepEqual(of(round, "datum").call, { kind: "datum", id: "A", letter: "A", ref: HOLE.ref });
  assert.equal(of(round, "diameter").nominal, 8);
  assert.equal(of(round, "position").need, "Pick one round face, after a datum");
});

test("a basic dimension goes between flat faces and holes, each hole by its axis, and takes no tolerance", () => {
  const fromSide = pmiCreateOptions({ picked: [SIDE, HOLE], entries: [] });
  assert.deepEqual(available(fromSide), ["basic"]);
  assert.deepEqual(of(fromSide, "basic").call, { kind: "dimension", type: "distance", basic: true, id: "basic", from: SIDE.ref, to: HOLE.ref, tolerance: null });
  assert.equal(of(fromSide, "basic").nominal, 20, "to the hole's centre line");
  // Two holes: square to both axes, whichever way each runs.
  assert.equal(of(pmiCreateOptions({ picked: [HOLE, PEG], entries: [] }), "basic").nominal, 12);
  // A hole whose axis crosses the face makes none.
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP, HOLE], entries: [] })), []);
});

test("a pick that makes nothing offers nothing, and says what each kind needs", () => {
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP, SIDE], entries: [] })), [], "two faces at an angle");
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP, PART], entries: [] })), [], "a face and a part");
  assert.deepEqual(available(pmiCreateOptions({ picked: [], entries: [] })), []);
  assert.equal(of(pmiCreateOptions({ picked: [], entries: [] }), "distance").need, "Pick two parallel flat faces");
});

test("a new one's id and letter are ones the document does not have, and a position refers to its datums", () => {
  const entries = readXbfPmi({ pmi: [
    { id: "A", kind: "datum", status: "ok", part: 0, refs: [], datum: { letter: "A" } },
    { id: "flatness", kind: "geometric_tolerance", status: "ok", part: 0, refs: [], geometric_tolerance: { characteristic: "flatness", value: 0.05, datums: [] } },
  ] });
  assert.deepEqual(of(pmiCreateOptions({ picked: [TOP], entries }), "datum").call, { kind: "datum", id: "B", letter: "B", ref: TOP.ref });
  assert.equal(of(pmiCreateOptions({ picked: [TOP], entries }), "flatness").call.id, "flatness-2");
  const position = of(pmiCreateOptions({ picked: [HOLE], entries }), "position");
  assert.equal(position.available, true);
  assert.deepEqual([position.call.datums, position.call.value, position.call.diameterZone], [["A"], null, true]);
  // I, O and Q are never datum letters.
  assert.equal(nextDatumLetter(readXbfPmi({ pmi: "ABCDEFGH".split("").map(letter => ({ id: letter, kind: "datum", datum: { letter } })) })), "J");
});

test("a tolerance typed in is read as a drawing writes one, and none is none", () => {
  assert.deepEqual(parseToleranceInput(""), { tolerance: null });
  assert.deepEqual(parseToleranceInput("±0.2"), { tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } });
  assert.deepEqual(parseToleranceInput("0.2"), { tolerance: { type: "plus_minus", upper: 0.2, lower: -0.2 } });
  assert.deepEqual(parseToleranceInput("+0.1/−0.05"), { tolerance: { type: "plus_minus", upper: 0.1, lower: -0.05 } });
  assert.deepEqual(parseToleranceInput("+0.1 0"), { tolerance: { type: "plus_minus", upper: 0.1, lower: 0 } });
  assert.ok(parseToleranceInput("-0.1/+0.1").error, "the upper comes first");
  assert.ok(parseToleranceInput("+0.1/+0.1").error, "and is above the lower, as the engine's plus_minus has it");
  assert.ok(parseToleranceInput("loose").error);
  assert.ok(parseToleranceInput("0").error);
});

test("a new one asked for but not yet built takes its id and letter, so a second never replaces it", () => {
  const pending = [{ part: 0, call: { kind: "geometric_tolerance", characteristic: "flatness", id: "flatness", ref: TOP.ref, value: 0.05 } },
    { part: 0, call: { kind: "datum", id: "A", letter: "A", ref: BOTTOM.ref } }];
  const options = pmiCreateOptions({ picked: [TOP], entries: [], pending });
  assert.equal(of(options, "flatness").call.id, "flatness-2");
  assert.equal(of(options, "datum").call.letter, "B");
});

test("ids and datum letters are a part's own: another part's never take them, nor are its datums offered", () => {
  const entries = readXbfPmi({ pmi: [
    { id: "A", kind: "datum", status: "ok", part: 0, refs: [], datum: { letter: "A" } },
    { id: "B", kind: "datum", status: "ok", part: 1, refs: [], datum: { letter: "B" } },
    { id: "diameter", kind: "dimension", status: "ok", part: 0, refs: [], dimension: { type: "diameter", nominal: { value: 8 }, tolerance: null } },
  ] });
  const onPeg = pmiCreateOptions({ picked: [PEG], entries, pending: [{ part: 0, call: { kind: "datum", id: "C", letter: "C", ref: TOP.ref } }] });
  assert.equal(onPeg.every(option => option.part === 1), true, "made on the peg");
  assert.deepEqual([of(onPeg, "datum").call.letter, of(onPeg, "diameter").call.id], ["A", "diameter"]);
  // A position on the peg refers to the peg's datums alone.
  assert.deepEqual([of(onPeg, "position").call.datums, of(onPeg, "position").datums], [["B"], ["B"]]);
  const onPlate = pmiCreateOptions({ picked: [HOLE], entries });
  assert.deepEqual([of(onPlate, "datum").call.letter, of(onPlate, "diameter").call.id, of(onPlate, "position").datums], ["B", "diameter-2", ["A"]]);
});

test("a new one is called by its id until it is built, and a datum by its letter", () => {
  assert.equal(newPmiName({ kind: "geometric_tolerance", characteristic: "flatness", id: "flatness" }), "flatness");
  assert.equal(newPmiName({ kind: "dimension", type: "distance", basic: true, id: "basic-2" }), "basic-2");
  assert.equal(newPmiName({ kind: "datum", id: "B", letter: "B" }), "datum B");
});

test("a frame's datums keep the order they were picked in, primary first, and stop at three", () => {
  assert.deepEqual(toggleDatum(["B", "A"], "C"), ["B", "A", "C"]);
  assert.deepEqual(toggleDatum(["B", "A", "C"], "A"), ["B", "C"]);
  assert.deepEqual(toggleDatum(["B", "C"], "A"), ["B", "C", "A"]);
  assert.deepEqual(toggleDatum(["A", "B", "C"], "D"), ["A", "B", "C"]);
});
