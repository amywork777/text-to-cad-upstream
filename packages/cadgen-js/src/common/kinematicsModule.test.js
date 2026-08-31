import assert from "node:assert/strict";
import { test } from "node:test";

import { stepModuleFromKinematics } from "./kinematicsModule.js";

const LEAF_BLOCK = {
  mates: [{
    name: "swing", kind: "revolute", parent: "#base", child: "#arm",
    axis: { origin: [0, 0, 6], dir: [0, 0, 1] }, limits: { value: [0, 90] }
  }]
};

// The build records the resolved instance-tree id beside the authored label.
const GROUP_BLOCK = {
  mates: [{
    name: "swing", kind: "revolute",
    parent: "#base_group", parentId: "o1.1",
    child: "#arm_group", childId: "o1.2",
    axis: { origin: [0, 0, 6], dir: [0, 0, 1] }, limits: { value: [0, 90] }
  }]
};

test("a mate with no resolved id resolves its occurrence by name alone", () => {
  const { manifest } = stepModuleFromKinematics(LEAF_BLOCK);
  assert.deepEqual(manifest.features.base, { names: ["base"] });
  assert.deepEqual(manifest.features.arm, { names: ["arm"] });
});

test("a mated SUBASSEMBLY resolves by occurrence id, which covers its subtree", () => {
  // A group is not a rendered part, so it has no leaf name to match; the id
  // ref is what makes every part beneath it ride the mate.
  const { manifest } = stepModuleFromKinematics(GROUP_BLOCK);
  assert.deepEqual(manifest.features.base_group, { ref: "#o1.1", names: ["base_group"] });
  assert.deepEqual(manifest.features.arm_group, { ref: "#o1.2", names: ["arm_group"] });
});

test("features are keyed by the authored label, which is what the deltas name", () => {
  const { manifest } = stepModuleFromKinematics(GROUP_BLOCK);
  assert.deepEqual(Object.keys(manifest.features).sort(), ["arm_group", "base_group"]);
  assert.equal(manifest.parameters.swing.unit, "deg");
  assert.equal(manifest.parameters.swing.default, 0);
});

test("a block with no mates compiles to nothing to pose", () => {
  assert.equal(stepModuleFromKinematics({ mates: [] }), null);
  assert.equal(stepModuleFromKinematics(null), null);
});
