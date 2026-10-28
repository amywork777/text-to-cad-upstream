import assert from "node:assert/strict";
import test from "node:test";

import { PICK_PX, extrudeSpan, handleAt, holeLoops, revolvedFrame, screenSketch, sideIndexes, sketchAt, tagPlace, taperedLoop, turnArrowStart } from "./sketchPicking.js";

const square = (x, y, size) => [[x, y], [x + size, y], [x + size, y + size], [x, y + size]];
// A sketch as the view draws it: its lines and its outlines, in pixels.
const drawn = (loops, curves = loops.map(loop => [...loop, loop[0]])) => ({ curves, loops });

test("a click near a sketch's line picks that sketch, the nearest of two", () => {
  const left = drawn([square(0, 0, 100)]);
  const right = drawn([square(103, 0, 100)]);
  assert.equal(sketchAt([left, right], [102, 50]), 1);
  assert.equal(sketchAt([left, right], [101, 50]), 0);
  assert.equal(sketchAt([left, right], [50, 100 + PICK_PX + 1]), -1);
});

test("inside an outline picks only while a feature waits for a sketch, never in its hole", () => {
  const plate = drawn([square(0, 0, 100), square(40, 40, 20)]);
  assert.equal(sketchAt([plate], [20, 20]), -1);
  assert.equal(sketchAt([plate], [20, 20], { profiles: true }), 0);
  assert.equal(sketchAt([plate], [50, 50], { profiles: true }), -1);
});

test("of two sketches one inside the other, the smaller is picked inside it", () => {
  const big = drawn([square(0, 0, 200)]);
  const small = drawn([square(50, 50, 40)]);
  assert.equal(sketchAt([big, small], [70, 70], { profiles: true }), 1);
  assert.equal(sketchAt([big, small], [20, 20], { profiles: true }), 0);
});

test("a sketch partly behind the camera is not there to be picked", () => {
  const state = { points: [{ id: "a", x: 0, y: 0 }, { id: "b", x: 10, y: 0 }], curves: [{ id: "Line1", kind: "line", start: "a", end: "b" }],
    loops: [[[0, 0], [10, 0], [10, 10]]] };
  const shown = screenSketch(state, ([x, y]) => (x > 5 ? null : [x, y]));
  assert.deepEqual(shown, { curves: [], loops: [] });
  assert.equal(screenSketch(state, ([x, y]) => [x * 2, y * 2]).curves.length, 1);
});

test("an extrude's preview spans its depth along the normal, the other way reversed", () => {
  assert.deepEqual(extrudeSpan({ end: "blind", depth: 10, reverse: false }), [0, 10]);
  assert.deepEqual(extrudeSpan({ end: "blind", depth: 10, reverse: true }), [-10, 0]);
  assert.deepEqual(extrudeSpan({ end: "mid", depth: 10, reverse: false }), [-5, 5]);
  assert.deepEqual(extrudeSpan({ end: "through", depth: 0, reverse: true }, 80), [-80, 0]);
  assert.equal(extrudeSpan({ end: "blind", depth: Number.NaN, reverse: false }), null);
  // Direction 2 runs the other way from the plane, by its depth or through all.
  assert.deepEqual(extrudeSpan({ end: "blind", depth: 10, reverse: false, depth2: 4 }), [-4, 10]);
  assert.deepEqual(extrudeSpan({ end: "blind", depth: 10, reverse: true, depth2: 4 }), [-10, 4]);
  assert.deepEqual(extrudeSpan({ end: "through", depth: 0, reverse: false, through2: true }, 80), [-80, 80]);
});

test("the preview joins an outline to its copy at its corners, or four times around a round one", () => {
  assert.deepEqual(sideIndexes(square(0, 0, 10)), [0, 1, 2, 3]);
  const circle = Array.from({ length: 64 }, (_, index) => [Math.cos((index / 64) * 2 * Math.PI), Math.sin((index / 64) * 2 * Math.PI)]);
  assert.deepEqual(sideIndexes(circle), [0, 16, 32, 48]);
});

test("the sketch's name is tagged at its left, clear of a preview rising off it, or above it at the view's edge", () => {
  assert.deepEqual(tagPlace(drawn([square(100, 40, 20)]), 50, 18), [42, 41]);
  assert.deepEqual(tagPlace(drawn([square(30, 40, 20)]), 50, 18), [30, 16]);
  assert.equal(tagPlace({ curves: [], loops: [] }, 50, 18), null);
});

test("a revolve's preview turns the sketch's frame about its axis line", () => {
  const top = { origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
  const close = (got, want) => got.forEach((value, index) => assert.ok(Math.abs(value - want[index]) < 1e-9, `${got} vs ${want}`));
  // About the sketch's own y axis: a quarter turn takes x to -z, as the right hand turns.
  const quarter = revolvedFrame(top, 1, [0, 0], [0, 1], 90);
  close(quarter.x, [0, 0, -1]);
  close(quarter.y, [0, 1, 0]);
  close(quarter.origin, [0, 0, 0]);
  // About a line off the origin, in inches: the origin swings around it.
  const half = revolvedFrame(top, 25.4, [1, 0], [1, 1], 180);
  close(half.origin, [50.8, 0, 0]);
  close(half.x, [-1, 0, 0]);
  assert.equal(revolvedFrame(top, 1, [2, 2], [2, 2], 90), null);
});

test("a drafted extrude's preview leans in: each side moved in square to itself, a hole's out", () => {
  const close = (got, want) => got.forEach((point, index) => point.forEach((value, axis) => assert.ok(Math.abs(value - want[index][axis]) < 1e-9, `${got} vs ${want}`)));
  close(taperedLoop(square(0, 0, 10), 1), [[1, 1], [9, 1], [9, 9], [1, 9]]);
  // Drawn the other way round, it still shrinks; outward, it grows; a hole grows as the material shrinks.
  close(taperedLoop([...square(0, 0, 10)].reverse(), 1), [[1, 9], [9, 9], [9, 1], [1, 1]]);
  close(taperedLoop(square(0, 0, 10), -1), [[-1, -1], [11, -1], [11, 11], [-1, 11]]);
  close(taperedLoop(square(4, 4, 2), 1, true), [[3, 3], [7, 3], [7, 7], [3, 7]]);
  assert.deepEqual(holeLoops([square(0, 0, 10), square(4, 4, 2), square(20, 0, 5)]), [false, true, false]);
});

test("a revolve's arrow turns just outside its profile, on the side of the axis the profile is", () => {
  // A 10 x 20 profile beside the axis up Y at x = 0: the arrow runs past its outer side.
  const profile = [[5, 0], [15, 0], [15, 20], [5, 20]];
  const [x, y] = turnArrowStart([profile], [0, 0], [0, 1]);
  assert.ok(Math.abs(x - 15 * 1.15) < 1e-9);
  assert.ok(Math.abs(y - 10) < 1e-9);
  // On the axis's other side, the other way out; none for an axis of no length.
  assert.ok(turnArrowStart([profile.map(([u, v]) => [-u, v])], [0, 0], [0, 1])[0] < -15);
  assert.equal(turnArrowStart([profile], [0, 0], [0, 0]), null);
});

test("a press on an arrow's shaft or head takes it as a handle, and one end on by its ring", () => {
  const across = { from: [100, 100], tip: [134, 100], facing: 0 };
  const endOn = { from: [300, 300], tip: [300, 300], facing: 1 };
  assert.equal(handleAt([across, endOn], [120, 105]), across);
  assert.equal(handleAt([across, endOn], [120, 112]), null);
  assert.equal(handleAt([across, endOn], [306, 306]), endOn);
  assert.equal(handleAt([], [0, 0]), null);
});
