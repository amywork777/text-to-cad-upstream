// The generic articulation runtime for descriptor `pose` blocks.
//
// A pose block (authored via cadgen.pose(), validated there, carried in
// assembly.json) COMPILES into the exact raw-module shape the step-module
// machinery already consumes: `{manifest, setup, update, dispose}` feeding
// normalizeStepModuleDefinition(). Everything downstream — the viewer's
// setup/update loop, the effects application, the params panel, animation UI,
// the snapshot headless entry — is unchanged; this file is just a second
// SOURCE of a step-module definition, written once instead of per model.
//
// The escape hatch: a pose block may reference a content-addressed JS module
// inside the package. Its exports receive the SAME ctx after the declarative
// pass, preserving the full legacy sidecar contract (setup({THREE, modelGroup,
// cleanup}), update({params, features, effects, time}), effects.*,
// features[id].center).
//
// Driver semantics (mirrors cadgen/posedef.py — the authoring-side validator):
//   value = offset + scale * f(param)
//   f = identity, or window [a,b] normalization + easing when window present.
// Joints evaluate in declaration order; ratio sources must precede their
// joint; parent chains compose root-outward. Rotations are degrees,
// translations millimetres — the units the effects API already speaks.

import { normalizeStepModuleDefinition } from "./stepModule.js";

export const POSE_SCHEMA_VERSION = 1;

const EASINGS = {
  linear: (t) => t,
  smoothstep: (t) => t * t * (3 - 2 * t),
  sine: (t) => 0.5 - 0.5 * Math.cos(Math.PI * t),
  easeIn: (t) => t * t,
  easeOut: (t) => 1 - (1 - t) * (1 - t),
  easeInOut: (t) => (t < 0.5 ? 2 * t * t : 1 - 2 * (1 - t) * (1 - t))
};

function toNumber(value, fallback = 0) {
  if (value === true) {
    return 1;
  }
  if (value === false) {
    return 0;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function clamp01(value) {
  return Math.min(Math.max(value, 0), 1);
}

export function ease(name, t) {
  return (EASINGS[name] || EASINGS.linear)(clamp01(t));
}

/** offset + scale * f(param): the one scalar law every driver input obeys. */
export function drivenValue(rawParamValue, { window = null, easing = "linear", scale = 1, offset = 0 } = {}) {
  const raw = toNumber(rawParamValue, 0);
  let input = raw;
  if (Array.isArray(window) && window.length === 2) {
    const [start, end] = window;
    const span = end - start;
    input = ease(easing, span > 0 ? (raw - start) / span : 0);
  } else if (easing && easing !== "linear") {
    input = ease(easing, raw);
  }
  return offset + scale * input;
}

function normalizeVector3(value, fallback = [0, 0, 1]) {
  if (!Array.isArray(value) || value.length !== 3) {
    return [...fallback];
  }
  return value.map((component) => toNumber(component, 0));
}

function unit(vector) {
  const [x, y, z] = vector;
  const length = Math.hypot(x, y, z);
  return length > 1e-12 ? [x / length, y / length, z / length] : [0, 0, 1];
}

function featureOrigin(joint, feature, resolvedFeature) {
  if (Array.isArray(joint?.origin)) {
    return normalizeVector3(joint.origin, [0, 0, 0]);
  }
  if (Array.isArray(feature?.origin)) {
    return normalizeVector3(feature.origin, [0, 0, 0]);
  }
  if (Array.isArray(resolvedFeature?.center)) {
    return normalizeVector3(resolvedFeature.center, [0, 0, 0]);
  }
  return [0, 0, 0];
}

/** Evaluate every joint's scalar value from the drivers, declaration order. */
export function evaluateJointValues(pose, params) {
  const values = new Map();
  for (const joint of pose.joints || []) {
    values.set(joint.id, 0);
  }
  for (const driver of pose.drivers || []) {
    if (driver.kind === "joint") {
      values.set(driver.joint, drivenValue(params?.[driver.param], driver));
    } else if (driver.kind === "ratio") {
      const source = toNumber(values.get(driver.source), 0);
      values.set(driver.joint, toNumber(driver.ratio, 1) * source + toNumber(driver.offset, 0));
    }
  }
  return values;
}

function jointTransformSpec(joint, value, pose, resolvedFeatures) {
  const feature = pose.features?.[joint.feature] || null;
  const resolved = resolvedFeatures?.[joint.feature] || null;
  const origin = featureOrigin(joint, feature, resolved);
  const axis = unit(normalizeVector3(joint.axis));
  if (joint.kind === "translate") {
    return { translate: axis.map((component) => component * value) };
  }
  return { rotate: { axis, origin, angleDeg: value } };
}

/** Per-feature transform step lists, self-first then ancestors (the effects
 * matrix builder premultiplies, so the LAST step is the outermost/root). */
export function jointTransformsByFeature(pose, jointValues, resolvedFeatures) {
  const byId = new Map((pose.joints || []).map((joint) => [joint.id, joint]));
  const specs = new Map();
  for (const joint of pose.joints || []) {
    const steps = [];
    let current = joint;
    let guard = 0;
    while (current && guard < 64) {
      const value = toNumber(jointValues.get(current.id), 0);
      if (value !== 0) {
        steps.push(jointTransformSpec(current, value, pose, resolvedFeatures));
      }
      current = current.parent ? byId.get(current.parent) : null;
      guard += 1;
    }
    if (steps.length) {
      specs.set(joint.feature, steps);
    }
  }
  return specs;
}

function radialDirection(resolvedFeature) {
  const center = Array.isArray(resolvedFeature?.center) ? resolvedFeature.center : [0, 0, 0];
  const length = Math.hypot(toNumber(center[0]), toNumber(center[1]));
  if (length <= 1e-9) {
    return [1, 0, 0];
  }
  return [toNumber(center[0]) / length, toNumber(center[1]) / length, 0];
}

function styleValuesFor(styleMap, t) {
  const resolved = {};
  for (const [prop, value] of Object.entries(styleMap || {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const from = toNumber(value.from, 0);
      const to = toNumber(value.to, 0);
      resolved[prop] = from + (to - from) * clamp01(t);
    } else {
      resolved[prop] = value;
    }
  }
  return resolved;
}

/** The generic update pass: evaluates every driver against ctx.params and
 * issues effects calls. Exported for direct unit testing. */
export function applyPose(pose, ctx) {
  const params = ctx?.params || {};
  const effects = ctx?.effects;
  const resolvedFeatures = ctx?.features || {};
  if (!effects) {
    return;
  }
  const jointValues = evaluateJointValues(pose, params);
  for (const [featureId, steps] of jointTransformsByFeature(pose, jointValues, resolvedFeatures)) {
    effects.transform(featureId, { transforms: steps });
  }
  for (const driver of pose.drivers || []) {
    if (driver.kind === "translate") {
      const magnitude = drivenValue(params[driver.param], {
        ...driver,
        scale: toNumber(driver.distance, 1),
        offset: 0
      });
      if (magnitude === 0) {
        continue;
      }
      for (const featureId of driver.features || []) {
        const direction = driver.direction === "radial"
          ? radialDirection(resolvedFeatures[featureId])
          : unit(normalizeVector3(driver.direction, [0, 0, 1]));
        effects.transform(featureId, {
          translate: direction.map((component) => component * magnitude)
        });
      }
    } else if (driver.kind === "visible") {
      const raw = params[driver.param];
      let visible = driver.value !== undefined ? String(raw) === String(driver.value) : raw !== false && raw !== 0;
      if (driver.invert) {
        visible = !visible;
      }
      for (const target of driver.targets || []) {
        effects.visible(target, visible);
      }
    } else if (driver.kind === "style") {
      if (driver.palettes) {
        const palette = driver.palettes[String(params[driver.param])];
        if (palette) {
          for (const [target, styles] of Object.entries(palette)) {
            effects.style(target, styleValuesFor(styles, 1));
          }
        }
      } else {
        const t = driver.param !== undefined
          ? drivenValue(params[driver.param], { ...driver, scale: 1, offset: 0 })
          : 1;
        for (const target of driver.targets || []) {
          effects.style(target, styleValuesFor(driver.style, t));
        }
      }
    } else if (driver.kind === "scale") {
      const t = drivenValue(params[driver.param], { ...driver, scale: 1, offset: 0 });
      const from = toNumber(driver.from, 1);
      const to = toNumber(driver.to, 1);
      const scale = from + (to - from) * clamp01(t);
      for (const target of driver.targets || []) {
        effects.transform(target, {
          scale,
          origin: normalizeVector3(driver.origin, [0, 0, 0])
        });
      }
    }
  }
}

/** Sample one keyframe track at normalized progress (0..1). Numbers lerp with
 * the DESTINATION key's easing; everything else step-holds. */
export function sampleTrack(track, progress) {
  const keys = Array.isArray(track?.keys) ? track.keys : [];
  if (!keys.length) {
    return undefined;
  }
  const t = clamp01(toNumber(progress, 0));
  if (t <= keys[0].t) {
    return keys[0].value;
  }
  for (let index = 1; index < keys.length; index += 1) {
    const previous = keys[index - 1];
    const next = keys[index];
    if (t <= next.t) {
      if (typeof previous.value === "number" && typeof next.value === "number") {
        const span = next.t - previous.t;
        const local = span > 0 ? (t - previous.t) / span : 1;
        return previous.value + (next.value - previous.value) * ease(next.easing || "linear", local);
      }
      return t >= next.t ? next.value : previous.value;
    }
  }
  return keys[keys.length - 1].value;
}

function animationsFromPose(pose) {
  const animations = {};
  for (const [id, clip] of Object.entries(pose.animations || {})) {
    animations[id] = {
      label: clip.label || id,
      description: clip.description || "",
      duration: clip.duration,
      loop: clip.loop !== false,
      update({ progress, set }) {
        for (const track of clip.tracks || []) {
          const value = sampleTrack(track, progress);
          if (value !== undefined) {
            set(track.param, value);
          }
        }
      }
    };
  }
  return animations;
}

/** Fetch a package source sidecar (source.json), compile its pose block (and
 * dynamic-import the escape hatch when declared) into a normalized step-module
 * definition. The ONLY pose loading path. */
export async function loadPoseModuleDefinition(poseUrl, { hatchUrl = "", cadPath = "" } = {}) {
  const response = await fetch(poseUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`pose sidecar fetch failed (${response.status}) for ${poseUrl}`);
  }
  const descriptor = await response.json();
  const poseBlock = descriptor && typeof descriptor.pose === "object" ? descriptor.pose : null;
  if (!poseBlock) {
    throw new Error(`pose payload at ${poseUrl} declares no pose block`);
  }
  let hatch = null;
  if (poseBlock.module) {
    // The scanner hands the viewer an explicit asset URL; path-style servers
    // (the snapshot loopback) can resolve the package-relative ref directly.
    const resolvedHatchUrl = hatchUrl || new URL(poseBlock.module, poseUrl).toString();
    hatch = await import(/* webpackIgnore: true */ /* @vite-ignore */ resolvedHatchUrl);
  }
  const raw = stepModuleFromPoseBlock(poseBlock, { hatch });
  return normalizeStepModuleDefinition(raw, { url: poseUrl, cadPath });
}

/** Compile a descriptor pose block (+ optional imported hatch namespace) into
 * the raw step-module shape normalizeStepModuleDefinition() consumes. */
export function stepModuleFromPoseBlock(poseBlock, { hatch = null } = {}) {
  const pose = poseBlock && typeof poseBlock === "object" ? poseBlock : {};
  const schemaVersion = Number(pose.schemaVersion || 0);
  if (schemaVersion !== POSE_SCHEMA_VERSION) {
    throw new Error(`Unsupported pose schemaVersion ${pose.schemaVersion ?? "unknown"}`);
  }
  const hatchModule = hatch && typeof hatch === "object" ? (hatch.default ?? hatch) : null;
  return {
    manifest: {
      schemaVersion: 1,
      parameters: pose.params || {},
      features: pose.features || {},
      animations: animationsFromPose(pose)
    },
    setup(ctx) {
      hatchModule?.setup?.(ctx);
    },
    update(ctx) {
      applyPose(pose, ctx);
      hatchModule?.update?.(ctx);
    },
    render(ctx) {
      hatchModule?.render?.(ctx);
    },
    dispose(ctx) {
      hatchModule?.dispose?.(ctx);
    }
  };
}
