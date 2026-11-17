import assert from "node:assert/strict";
import test from "node:test";

import { customChanged, customCommandId, customDefinition, customGroups, customRequest, customValues, isCustomCommand, pickWords } from "./customFeature.js";

// The engine's reading of a flange whose bolt holes are a custom feature's (`test_edit_custom_features.py`).
const PARAMS = [
  { name: "diameter", kind: "length", label: "Diameter", group: null, value: "60", code: "BOLT_CIRCLE", input: 0, unit: "mm" },
  { name: "count", kind: "count", label: "Count", group: null, value: "6", code: "6", input: 1, unit: "" },
  { name: "spread", kind: "enum", label: "Spread", group: "Options", value: "full", code: null, default: "full",
    choices: [{ value: "full", label: "Full circle" }, { value: "half", label: "Half circle" }] },
  { name: "staggered", kind: "bool", label: "Staggered", group: "Options", value: false, code: null, default: false },
];
const STATE = {
  rows: [{ key: "flange.py:12", custom: { name: "Bolt Circle", function: "flange_features.bolt_circle", params: PARAMS, collapsed: ["Options"] } }],
  customFeatures: [{ name: "Edge Break", function: "flange_features.edge_break", doc: "Breaks sharp edges.", collapsed: [], params: [
    { name: "edges", kind: "edges", label: "Edges", group: null, required: true, max: null },
    { name: "size", kind: "length", label: "Size", group: null, required: false, default: 1 },
    { name: "style", kind: "enum", label: "Style", group: null, required: false, default: "round",
      choices: [{ value: "round", label: "Round" }, { value: "chamfer", label: "Chamfer" }] }] }],
};
const EDITING = { command: "custom", row: "flange.py:12" };

test("a custom feature's dialog opens Edit Feature on the call's values, and a new call on the declared defaults", () => {
  const edited = customDefinition(STATE, "custom", EDITING);
  assert.deepEqual([edited.name, edited.editing, edited.row], ["Bolt Circle", true, "flange.py:12"]);
  assert.deepEqual(customValues(edited), { diameter: "60", count: "6", spread: "full", staggered: false });
  const fresh = customDefinition(STATE, customCommandId("flange_features.edge_break"), null);
  assert.deepEqual([fresh.name, fresh.editing], ["Edge Break", false]);
  assert.deepEqual(customValues(fresh), { size: "1", style: "round" });
  assert.equal(customDefinition(STATE, customCommandId("flange_features.gone"), null), null);
  assert.deepEqual([isCustomCommand("custom"), isCustomCommand("custom:a.b"), isCustomCommand("fillet")], [true, true, false]);
});

test("a custom feature's dialog shows the ungrouped parameters first, then each group, a collapsed one folded", () => {
  const sections = customGroups(customDefinition(STATE, "custom", EDITING));
  assert.deepEqual(sections.map(each => [each.title, each.params.map(param => param.name), each.folded]),
    [[null, ["diameter", "count"], false], ["Options", ["spread", "staggered"], true]]);
});

test("a custom feature's dialog asks Edit Feature for what changed only, so a size written by name stays so", () => {
  const definition = customDefinition(STATE, "custom", EDITING);
  assert.equal(customChanged(customRequest(definition, customValues(definition))), false);
  const request = customRequest(definition, { ...customValues(definition), count: "8", staggered: true });
  assert.deepEqual(request, { command: "custom", function: "flange_features.bolt_circle", inputs: { count: "8", staggered: true }, picks: {},
    replace: { row: "flange.py:12" } });
  assert.equal(customChanged(request), true);
});

test("a custom feature's dialog sends a new call's values and its picks, each pick field's own", () => {
  const definition = customDefinition(STATE, customCommandId("flange_features.edge_break"), null);
  const rim = { selector: "e3", type: "circle", center: [0, 0, 4], size: 251.3 };
  assert.deepEqual(customRequest(definition, { size: "1", style: "chamfer" }, { edges: [rim], other: [] }), {
    command: "custom", function: "flange_features.edge_break", inputs: { size: "1", style: "chamfer" }, picks: { edges: [rim] } });
});

test("a custom feature's dialog says what a pick field holds", () => {
  const edges = { kind: "edges", max: null, value: 0 };
  assert.equal(pickWords(edges, [], false), "Select edges");
  assert.equal(pickWords({ kind: "faces", max: 1, value: 0 }, [], false), "Select a face");
  assert.equal(pickWords(edges, [{}, {}], true), "2 edges");
  assert.equal(pickWords({ ...edges, value: 4 }, [], true), "4 edges, as written");
});
