import assert from "node:assert/strict";
import test from "node:test";
import { COLUMN, GAP, NODE, PORT, PROPERTY_HEIGHT, ROW, layoutGraph, nodeHeight, portY, wire } from "./graphLayout.js";

// The skill's bracket, as the field route reads it (`test_gsl_graph.py`).
const BRACKET = {
  nodes: ["wall", "plate", "upright", "solid", "skin", "g", "infill", "return"].map(id => ({ id, ...(id === "wall" ? { kind: "input" } : {}) })),
  edges: [["plate", "solid"], ["upright", "solid"], ["solid", "skin"], ["wall", "skin"], ["g", "infill"], ["solid", "infill"],
    ["skin", "return"], ["infill", "return"]],
};

test("a model's names are laid out in the column after the deepest name each is made from", () => {
  const laid = layoutGraph(BRACKET);
  const at = Object.fromEntries(laid.nodes.map(node => [node.id, [node.column, node.row]]));
  // `g` is made from nothing (the point alone): it waits in the column before `infill`, its one use.
  assert.deepEqual(at, { wall: [0, 0], plate: [0, 1], upright: [0, 2], solid: [1, 0], skin: [2, 0], g: [1, 1], infill: [2, 1], return: [3, 0] });
  assert.equal(laid.nodes.find(node => node.id === "infill").x, 2 * COLUMN);
  assert.equal(laid.nodes.find(node => node.id === "g").y, ROW);
  assert.deepEqual([laid.width, laid.height], [3 * COLUMN + 120, 2 * ROW + 34]);
});

test("an empty graph draws nothing and a wire runs from an output to an input", () => {
  assert.deepEqual(layoutGraph(null), { nodes: [], edges: [], width: 0, height: 0 });
  assert.equal(wire({ x: 0, y: 0 }, { x: COLUMN, y: ROW }), "M120 17 C144 17 124 63 148 63");
});

// A call with several outputs and a property read and set (`test_gsl_graph.py`'s PROPERTIES model).
const PROPERTIES = {
  nodes: [{ id: "plate" }, { id: "plate.dp", kind: "property", op: "dp", of: "plate" }, { id: "n" },
    { id: "mat, col", outputs: ["mat", "col"] }, { id: "plate.color =", kind: "property", op: "color", of: "plate", set: true },
    { id: "return" }],
  edges: [["plate", "plate.dp"], ["plate.dp", "n"], ["plate", "plate.color ="], ["mat, col", "plate.color =", "col"], ["n", "return"]],
};

test("a call with several outputs grows a port per output, and its edge leaves the port of the output it carries", () => {
  const laid = layoutGraph(PROPERTIES);
  const byId = Object.fromEntries(laid.nodes.map(node => [node.id, node]));
  assert.equal(byId["mat, col"].height, PORT.header + 2 * PORT.row + 4);
  assert.equal(nodeHeight({ outputs: ["only"] }), NODE.height);
  assert.equal(byId["plate.dp"].height, PROPERTY_HEIGHT);
  // `mat, col` is made from nothing and first used in the second column: it is under `plate`, a stack of different heights.
  assert.deepEqual([byId["mat, col"].column, byId["mat, col"].y], [0, NODE.height + GAP]);
  assert.equal(portY(byId["mat, col"], "mat"), PORT.header + PORT.row / 2);
  assert.equal(portY(byId["mat, col"], "col"), PORT.header + PORT.row * 1.5);
  assert.equal(portY(byId.plate, undefined), NODE.height / 2);
  const from = byId["mat, col"], to = byId["plate.color ="];
  assert.ok(wire(from, to, "col").startsWith(`M${from.x + NODE.width} ${from.y + PORT.header + PORT.row * 1.5} `));
  assert.ok(wire(from, to, "col").endsWith(` ${to.x} ${to.y + PROPERTY_HEIGHT / 2}`));
  assert.deepEqual(laid.edges[3], ["mat, col", "plate.color =", "col"]);
  // The drawing is as tall as its tallest column.
  assert.equal(laid.height, NODE.height + GAP + byId["mat, col"].height);
});
