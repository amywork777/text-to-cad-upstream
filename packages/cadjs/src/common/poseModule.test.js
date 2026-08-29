// The articulation runtime's contract: pose blocks compile to step-module
// definitions whose update pass reproduces the driver law exactly
// (value = offset + scale * f(param)), composes joint chains root-outward,
// and hands the escape hatch the SAME ctx after the declarative pass.
import assert from "node:assert/strict";
import test from "node:test";

import {
  applyPose,
  drivenValue,
  evaluateJointValues,
  jointTransformsByFeature,
  sampleTrack,
  stepModuleFromPoseBlock
} from "./poseModule.js";
import { normalizeStepModuleDefinition } from "./stepModule.js";

function fakeEffects() {
  const calls = { transform: [], style: [], visible: [] };
  return {
    calls,
    transform: (target, spec) => calls.transform.push([target, spec]),
    style: (target, style) => calls.style.push([target, style]),
    visible: (target, visible) => calls.visible.push([target, visible]),
    highlight: () => {},
    clear: () => {}
  };
}

const GEAR_POSE = {
  schemaVersion: 1,
  params: {
    drive: { type: "number", min: 0, max: 360, default: 0 },
    explode: { type: "number", min: 0, max: 1, default: 0 },
    ringVisible: { type: "boolean", default: true }
  },
  features: {
    sun: { names: ["sun"], origin: [0, 0, 0] },
    carrier: { names: ["carrier"] },
    planet: { names: ["planet"] },
    ring: { names: ["ring"] }
  },
  joints: [
    { id: "sunSpin", feature: "sun", kind: "rotate", axis: [0, 0, 1], origin: [0, 0, 0] },
    { id: "carrierSpin", feature: "carrier", kind: "rotate", axis: [0, 0, 1], origin: [0, 0, 0] },
    { id: "planetSpin", feature: "planet", kind: "rotate", axis: [0, 0, 1], parent: "carrierSpin" }
  ],
  drivers: [
    { kind: "joint", joint: "sunSpin", param: "drive", scale: 1, offset: 0 },
    { kind: "ratio", joint: "carrierSpin", source: "sunSpin", ratio: 0.25, offset: 0 },
    { kind: "ratio", joint: "planetSpin", source: "sunSpin", ratio: -0.5, offset: 0 },
    { kind: "translate", features: ["planet"], param: "explode", direction: "radial", distance: 30 },
    { kind: "visible", targets: ["ring"], param: "ringVisible" }
  ],
  animations: {
    sweep: {
      label: "Sweep",
      duration: 4,
      loop: true,
      tracks: [{ param: "drive", keys: [{ t: 0, value: 0 }, { t: 1, value: 360, easing: "linear" }] }]
    }
  }
};

test("drivenValue: the scalar law, windowed and eased", () => {
  assert.equal(drivenValue(90, { scale: 2, offset: 5 }), 185);
  // window [10, 20]: param 15 -> t = 0.5, smoothstep(0.5) = 0.5
  assert.equal(drivenValue(15, { window: [10, 20], easing: "smoothstep", scale: 10, offset: 1 }), 6);
  // outside the window clamps
  assert.equal(drivenValue(-5, { window: [10, 20], scale: 10 }), 0);
  assert.equal(drivenValue(99, { window: [10, 20], scale: 10 }), 10);
  // booleans coerce to 0/1
  assert.equal(drivenValue(true, { scale: 3 }), 3);
});

test("joint evaluation: declaration order with ratio couplings", () => {
  const values = evaluateJointValues(GEAR_POSE, { drive: 100 });
  assert.equal(values.get("sunSpin"), 100);
  assert.equal(values.get("carrierSpin"), 25);
  assert.equal(values.get("planetSpin"), -50);
});

test("joint chains compose self-first (premultiply makes the root outermost)", () => {
  const values = evaluateJointValues(GEAR_POSE, { drive: 100 });
  const resolved = { planet: { center: [42, 0, 0] }, carrier: { center: [0, 0, 0] }, sun: { center: [0, 0, 0] } };
  const byFeature = jointTransformsByFeature(GEAR_POSE, values, resolved);
  const planetSteps = byFeature.get("planet");
  assert.equal(planetSteps.length, 2);
  assert.equal(planetSteps[0].rotate.angleDeg, -50); // self
  assert.equal(planetSteps[1].rotate.angleDeg, 25);  // parent (carrier)
  // undriven-at-zero features simply emit no transform
  const ringSteps = byFeature.get("ring");
  assert.equal(ringSteps, undefined);
});

test("applyPose issues effects: transforms, radial explode, visibility", () => {
  const effects = fakeEffects();
  applyPose(GEAR_POSE, {
    params: { drive: 100, explode: 0.5, ringVisible: false },
    effects,
    features: { planet: { center: [42, 0, 0] }, sun: { center: [0, 0, 0] }, carrier: { center: [0, 0, 0] }, ring: { center: [0, 0, 0] } }
  });
  const translate = effects.calls.transform.find(([target, spec]) => target === "planet" && spec.translate);
  assert.ok(translate, "radial explode emitted");
  assert.deepEqual(translate[1].translate, [15, 0, 0]); // 30mm * 0.5 along +X (center at [42,0,0])
  const visible = effects.calls.visible.find(([target]) => target === "ring");
  assert.deepEqual(visible, ["ring", false]);
});

test("style drivers: ranged lerp and palettes", () => {
  const pose = {
    schemaVersion: 1,
    params: {
      fade: { type: "number", min: 0, max: 1, default: 0 },
      look: { type: "enum", options: ["day", "night"], default: "day" }
    },
    features: { skin: { names: ["skin"] }, frame: { names: ["frame"] } },
    drivers: [
      { kind: "style", targets: ["skin"], param: "fade", style: { opacity: { from: 1, to: 0.2 }, emissive: "#ff0000" } },
      { kind: "style", targets: ["frame"], param: "look", palettes: { night: { frame: { color: "#112233" } } } }
    ]
  };
  const effects = fakeEffects();
  applyPose(pose, { params: { fade: 0.5, look: "night" }, effects, features: {} });
  const skin = effects.calls.style.find(([target]) => target === "skin");
  assert.equal(skin[1].opacity, 0.6);
  assert.equal(skin[1].emissive, "#ff0000");
  const frame = effects.calls.style.find(([target]) => target === "frame");
  assert.deepEqual(frame[1], { color: "#112233" });
});

test("sampleTrack: eased lerp for numbers, step-hold for the rest", () => {
  const numeric = { param: "x", keys: [{ t: 0, value: 0 }, { t: 0.5, value: 10 }, { t: 1, value: 0, easing: "easeOut" }] };
  assert.equal(sampleTrack(numeric, 0.25), 5);
  assert.equal(sampleTrack(numeric, 0.5), 10);
  assert.equal(sampleTrack(numeric, 1), 0);
  const stepped = { param: "mode", keys: [{ t: 0, value: "a" }, { t: 0.6, value: "b" }] };
  assert.equal(sampleTrack(stepped, 0.3), "a");
  assert.equal(sampleTrack(stepped, 0.6), "b");
  assert.equal(sampleTrack(stepped, 0.9), "b");
});

test("compiles to a definition the step-module machinery accepts end-to-end", () => {
  const raw = stepModuleFromPoseBlock(GEAR_POSE);
  const definition = normalizeStepModuleDefinition(raw, { cadPath: "models/gear" });
  assert.equal(definition.parameters.length, 3);
  assert.equal(definition.parameterMap.drive.max, 360);
  assert.equal(definition.features.length, 4);
  assert.equal(definition.animations.length, 1);
  // the generated animation drives params through set() exactly like a sidecar
  const values = {};
  definition.animations[0].update({ progress: 0.5, set: (id, value) => { values[id] = value; } });
  assert.equal(values.drive, 180);
});

test("the hatch receives the same ctx after the declarative pass", () => {
  const order = [];
  const hatch = {
    setup: (ctx) => order.push(["setup", typeof ctx.cleanup]),
    update: (ctx) => order.push(["update", ctx.params.drive]),
    dispose: () => order.push(["dispose", null])
  };
  const module = stepModuleFromPoseBlock(GEAR_POSE, { hatch });
  const effects = fakeEffects();
  const ctx = { params: { drive: 10 }, effects, features: {}, cleanup: () => {} };
  module.setup(ctx);
  module.update(ctx);
  module.dispose(ctx);
  assert.deepEqual(order, [["setup", "function"], ["update", 10], ["dispose", null]]);
  assert.ok(effects.calls.transform.length > 0, "declarative pass ran before the hatch");
});

test("unsupported pose schema versions are refused", () => {
  assert.throws(() => stepModuleFromPoseBlock({ schemaVersion: 99 }), /schemaVersion/);
});
