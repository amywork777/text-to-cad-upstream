import assert from "node:assert/strict";
import test from "node:test";
import { onSceneRendered } from "./sceneRendered.js";

const screen = { getRenderTarget: () => null };
const target = { getRenderTarget: () => ({}) };

test("a layer hears each render of its scene to the screen, after what the scene had, and leaves it as it was", () => {
  const heard = [];
  const own = function own() { heard.push("own"); };
  const scene = { onAfterRender: own };
  const camera = { id: "camera" };
  const stopA = onSceneRendered(scene, seen => heard.push(["a", seen.id]));
  const stopB = onSceneRendered(scene, () => heard.push("b"));
  scene.onAfterRender(screen, scene, camera);
  assert.deepEqual(heard, ["own", ["a", "camera"], "b"]);
  // A picture's or a pick's render, into a target, is not the view drawn.
  heard.length = 0;
  scene.onAfterRender(target, scene, camera);
  assert.deepEqual(heard, ["own"]);
  stopA();
  heard.length = 0;
  scene.onAfterRender(screen, scene, camera);
  assert.deepEqual(heard, ["own", "b"]);
  stopB();
  assert.equal(scene.onAfterRender, own, "the last layer gone puts back what the scene had");
});

test("layers coming and going under another overlay's wrapper of the hook leave each render heard once", () => {
  const scene = { onAfterRender() {} };
  let heard = 0;
  const stop = onSceneRendered(scene, () => { heard += 1; });
  const hook = scene.onAfterRender;
  // Another overlay wraps the hook, and the hook is put over it again: each calls the other first.
  let other = 0;
  const wrapper = function wrapper(...args) { other += 1; hook.apply(this, args); };
  scene.onAfterRender = wrapper;
  stop();
  const again = onSceneRendered(scene, () => { heard += 1; });
  scene.onAfterRender(screen, scene, {});
  assert.equal(heard, 1);
  assert.equal(other, 1);
  again();
});
