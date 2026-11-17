import assert from "node:assert/strict";
import test from "node:test";
import { COLUMN, ROW, layoutGraph, wire } from "./graphLayout.js";

// The skill's bracket, as the field route reads it (`test_gsl_graph.py`).
const BRACKET = {
  nodes: ["wall", "plate", "upright", "solid", "skin", "g", "infill", "return"].map(id => ({ id })),
  edges: [["plate", "solid"], ["upright", "solid"], ["solid", "skin"], ["wall", "skin"], ["g", "infill"], ["solid", "infill"],
    ["skin", "return"], ["infill", "return"]],
};

test("a model's names are laid out in the column after the deepest name each is made from", () => {
  const laid = layoutGraph(BRACKET);
  const at = Object.fromEntries(laid.nodes.map(node => [node.id, [node.column, node.row]]));
  assert.deepEqual(at, { wall: [0, 0], plate: [0, 1], upright: [0, 2], solid: [1, 0], skin: [2, 0], g: [0, 3], infill: [2, 1], return: [3, 0] });
  assert.equal(laid.nodes.find(node => node.id === "infill").x, 2 * COLUMN);
  assert.equal(laid.nodes.find(node => node.id === "g").y, 3 * ROW);
  assert.deepEqual([laid.width, laid.height], [3 * COLUMN + 120, 3 * ROW + 34]);
});

test("an empty graph draws nothing and a wire runs from an output to an input", () => {
  assert.deepEqual(layoutGraph(null), { nodes: [], edges: [], width: 0, height: 0 });
  assert.equal(wire({ x: 0, y: 0 }, { x: COLUMN, y: ROW }), "M120 17 C144 17 124 63 148 63");
});
