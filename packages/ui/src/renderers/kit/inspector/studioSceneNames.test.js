// Studio: a scene's Model tab as an engineer reads it (`studioSceneNames.js`).
import assert from "node:assert/strict";
import test from "node:test";

import { humanName, middleTruncate, sceneNodeName, studioSceneTree } from "./studioSceneNames.js";

test("a node's name is written as a name, its instance tag a muted suffix, a fastener by its size", () => {
  assert.equal(humanName("led_module"), "LED module");
  assert.equal(humanName("headAssembly"), "Head assembly");
  assert.deepEqual(sceneNodeName("weight"), { name: "Weight", suffix: "", full: "weight", kind: "part" });
  assert.deepEqual(sceneNodeName("m5x30_screw:base_hinge"), { name: "M5×30 screw", suffix: "base hinge", full: "m5x30_screw:base_hinge", kind: "fastener" });
  assert.equal(sceneNodeName("m5_locknut:base_hinge").name, "M5 locknut");
  assert.equal(sceneNodeName("iso4762_m3x8").name, "M3×8 socket head screw");
  assert.equal(sceneNodeName("arm_assembly/head_assembly/led_module").name, "LED module");
  assert.equal(sceneNodeName("arm_assembly", { branch: true }).kind, "assembly");
});

test("a long name gives way in its middle, a short one is kept whole", () => {
  assert.equal(middleTruncate("Head"), "Head");
  const cut = middleTruncate("Arm assembly head assembly LED module screw", 20);
  assert.equal(cut.length <= 20, true);
  assert.match(cut, /^Arm assemb.*….*screw$/);
});

test("nodes named by their place nest under groups of those places, ids kept; a tree with no places is only renamed", () => {
  const leaf = (id, label) => ({ id, label, part: id, children: [] });
  const flat = [leaf("a", "weight"), leaf("b", "arm_assembly/arm"), leaf("c", "arm_assembly/head_assembly/led_module"),
    leaf("d", "arm_assembly/head_assembly/head")];
  const tree = studioSceneTree(flat);
  const shape = nodes => nodes.map(node => (node.children.length ? [node.label, shape(node.children)] : [node.id, node.label]));
  assert.deepEqual(shape(tree), [["a", "Weight"], ["Arm assembly", [["b", "Arm"], ["Head assembly", [["c", "LED module"], ["d", "Head"]]]]]]);
  assert.equal(tree[1].id, "studio-group:arm_assembly");
  assert.equal(tree[1].studio.kind, "assembly");
  const nested = studioSceneTree([{ id: "r", label: "desk_lamp", part: null, children: [leaf("s", "m5x30_screw:base_hinge")] }]);
  assert.deepEqual([nested[0].label, nested[0].children[0].label, nested[0].children[0].studio.kind], ["Desk lamp", "M5×30 screw base hinge", "fastener"]);
});
