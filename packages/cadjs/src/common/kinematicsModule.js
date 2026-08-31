// Sidecar -> viewer runtime for the mates half of the split
// (design/pose-animation-split.md). Replaces poseModule.js: the sidecar's
// KINEMATICS section (typed mates, resolved axes, couplings, presets) becomes
// a step-module definition — one number slider per DOF, an update pass that
// folds slider values through the shared FK evaluator into per-occurrence
// matrix effects. Pure data in, arithmetic out: no authored JS is involved on
// this path (choreography is the ANIMATION section, evaluated by
// animationRuntime.js, and never touches this module).

import {
  kinematicsAtRest,
  kinematicsDeltas,
  kinematicsDofs,
  kinematicsMates,
  kinematicsPoses
} from "./kinematicsRuntime.js";
import { normalizeStepModuleDefinition } from "./stepModule.js";

function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function stripHash(ref) {
  return String(ref || "").replace(/^#/, "");
}

// Column-major THREE.Matrix4 elements -> the row-major flat 16 the effects
// matrix spec takes.
function rowMajor16(matrix) {
  const e = matrix.elements;
  return [
    e[0], e[4], e[8], e[12],
    e[1], e[5], e[9], e[13],
    e[2], e[6], e[10], e[14],
    e[3], e[7], e[11], e[15]
  ];
}

export function stepModuleFromKinematics(block) {
  if (!isObject(block) || !kinematicsMates(block).length) {
    return null;
  }
  const dofs = kinematicsDofs(block);
  const parameters = {};
  for (const dof of dofs) {
    const limits = Array.isArray(dof.limits) ? dof.limits : [0, 1];
    parameters[dof.id] = {
      type: "number",
      label: dof.id,
      min: limits[0],
      max: limits[1],
      default: 0,
      unit: dof.kind === "revolute" ? "deg" : dof.kind === "coupling" ? "" : "mm"
    };
  }
  // Every mated occurrence becomes a feature keyed by the authored label. It
  // resolves by NAME (the stable form the instance tree carries) AND, when the
  // build resolved one, by the occurrence id the sidecar recorded beside the
  // label: id matching is what covers a SUBASSEMBLY, because a group is not a
  // rendered part and so has no leaf name of its own, while an id matches its
  // whole subtree by prefix. A mate on a group carries its parts either way.
  const features = {};
  for (const mate of kinematicsMates(block)) {
    for (const [ref, id] of [[mate.parent, mate.parentId], [mate.child, mate.childId]]) {
      const label = stripHash(ref);
      if (!label || features[label]) {
        continue;
      }
      const occurrenceId = stripHash(id);
      features[label] = occurrenceId
        ? { ref: `#${occurrenceId}`, names: [label] }
        : { names: [label] };
    }
  }
  return {
    manifest: {
      schemaVersion: 1,
      parameters,
      features,
      kinematics: block,
      poses: kinematicsPoses(block)
    },
    update(ctx) {
      const values = isObject(ctx?.params) ? ctx.params : {};
      if (kinematicsAtRest(block, values)) {
        return;
      }
      const deltas = kinematicsDeltas(ctx.THREE, block, values);
      for (const [ref, delta] of deltas.entries()) {
        ctx.effects.transform(stripHash(ref), { matrix: rowMajor16(delta) });
      }
    }
  };
}

/** Fetch the model's sidecar (<name>.step.cadgen.json) and compile its
 * kinematics section into a normalized step-module definition. Models with no
 * kinematics resolve to null (nothing to pose). The animation section is NOT
 * read here — the two systems stay independent end to end. */
export async function loadKinematicsModuleDefinition(sidecarUrl, { cadPath = "" } = {}) {
  const url = String(sidecarUrl || "").trim();
  if (!url) {
    return null;
  }
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load model sidecar: HTTP ${response.status}`);
  }
  const sidecar = await response.json();
  const raw = stepModuleFromKinematics(sidecar?.kinematics);
  if (!raw) {
    return null;
  }
  return normalizeStepModuleDefinition(raw, { url, cadPath });
}

/** Fetch the sidecar's ANIMATION section: the copied .anim.js text, or "". */
export async function loadAnimationSource(sidecarUrl) {
  const url = String(sidecarUrl || "").trim();
  if (!url) {
    return "";
  }
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load model sidecar: HTTP ${response.status}`);
  }
  const sidecar = await response.json();
  const clips = sidecar?.animation?.clips;
  return typeof clips === "string" ? clips : "";
}
