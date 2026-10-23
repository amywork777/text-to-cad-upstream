// What a new annotation can be made of the faces Select has picked (`pmiCreate.js`): each kind of
// the supported subset offered only where the pick makes one, with what it needs where it does not,
// starting as its call with the picked faces' refs, a fresh id, and no tolerance filled in.
import assert from "node:assert/strict";
import test from "node:test";
import { readXbfPmi } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { nextDatumLetter, parseToleranceInput, pmiCreateOptions, toggleDatum } from "./pmiCreate.js";

const TOP = { id: "i0/face/2", ref: "plate/f:top", surface: { type: "plane", normal: [0, 0, 1], origin: [0, 0, 2] } };
const BOTTOM = { id: "i0/face/5", ref: "plate/f:bottom", surface: { type: "plane", normal: [0, 0, -1], origin: [0, 0, -2] } };
const SIDE = { id: "i0/face/1", ref: "plate/f:side", surface: { type: "plane", normal: [-1, 0, 0], origin: [-20, 0, 0] } };
const HOLE = { id: "i0/face/11", ref: "plate/f:hole", surface: { type: "cylinder", axis: [0, 0, 1], origin: [0, 0, 0], radius: 4 } };
const PART = { id: "i0", ref: "", surface: null };
const available = options => options.filter(option => option.available).map(option => option.kind);
const of = (options, kind) => options.find(option => option.kind === kind);

test("one flat face makes a datum or a flatness; two parallel ones a distance; a round one a diameter", () => {
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP], entries: [] })), ["datum", "flatness"]);
  const pair = pmiCreateOptions({ picked: [BOTTOM, TOP], entries: [] });
  assert.deepEqual(available(pair), ["distance"]);
  assert.deepEqual(of(pair, "distance").call, { kind: "dimension", type: "distance", id: "distance", from: BOTTOM.ref, to: TOP.ref, tolerance: null });
  assert.equal(of(pair, "distance").nominal, 4);
  const round = pmiCreateOptions({ picked: [HOLE], entries: [] });
  assert.deepEqual(available(round), ["diameter"]);
  assert.equal(of(round, "diameter").nominal, 8);
  assert.equal(of(round, "position").need, "Pick one round face, after a datum");
});

test("a pick that makes nothing offers nothing, and says what each kind needs", () => {
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP, SIDE], entries: [] })), [], "two faces at an angle");
  assert.deepEqual(available(pmiCreateOptions({ picked: [TOP, PART], entries: [] })), [], "a face and a part");
  assert.deepEqual(available(pmiCreateOptions({ picked: [], entries: [] })), []);
  assert.equal(of(pmiCreateOptions({ picked: [], entries: [] }), "distance").need, "Pick two parallel flat faces");
});

test("a new one's id and letter are ones the document does not have, and a position refers to its datums", () => {
  const entries = readXbfPmi({ pmi: [
    { id: "A", kind: "datum", status: "ok", refs: [], datum: { letter: "A" } },
    { id: "flatness", kind: "geometric_tolerance", status: "ok", refs: [], geometric_tolerance: { characteristic: "flatness", value: 0.05, datums: [] } },
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
  assert.ok(parseToleranceInput("loose").error);
  assert.ok(parseToleranceInput("0").error);
});

test("a new one asked for but not yet built takes its id and letter, so a second never replaces it", () => {
  const pending = [{ kind: "geometric_tolerance", characteristic: "flatness", id: "flatness", ref: TOP.ref, value: 0.05 },
    { kind: "datum", id: "A", letter: "A", ref: BOTTOM.ref }];
  const options = pmiCreateOptions({ picked: [TOP], entries: [], pending });
  assert.equal(of(options, "flatness").call.id, "flatness-2");
  assert.equal(of(options, "datum").call.letter, "B");
});

test("a frame's datums keep the order they were picked in, primary first, and stop at three", () => {
  assert.deepEqual(toggleDatum(["B", "A"], "C"), ["B", "A", "C"]);
  assert.deepEqual(toggleDatum(["B", "A", "C"], "A"), ["B", "C"]);
  assert.deepEqual(toggleDatum(["B", "C"], "A"), ["B", "C", "A"]);
  assert.deepEqual(toggleDatum(["A", "B", "C"], "D"), ["A", "B", "C"]);
});
