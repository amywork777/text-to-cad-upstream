// The choreography half of the split (design/pose-animation-split.md):
// evaluate the sidecar's animation section — the COPIED .anim.js text — and
// drive raw per-occurrence transforms. Total independence by construction:
// this module knows nothing of mates, DOFs, presets, or the Pose tab; it
// targets occurrences by label and pushes matrices/styles through the same
// effects records the viewer already composes.
//
// Contract (the .anim.js side):
//   export const clips = {
//     demo: { label?, duration, loop?, update(t, m) { ... } },
//   };
// `update` is called every frame with t in seconds and m, the model handle.
// EVERY frame starts from rest: update(t) rebuilds state from scratch, so it
// must be a pure function of t — scrub, loop, and seek are free, and there is
// no persistent state to mutate.
//
// Handle API — m.get(label) returns an occurrence handle:
//   .rotate(axisVec3, degrees, originVec3 = [0,0,0])
//   .translate(vec3)
//   .opacity(value 0..1)
//   .visible(bool)
// Successive transform calls PREMULTIPLY (later calls act in world space on
// the already-moved part): h.rotate(spin about own center) then
// h.rotate(orbit about the assembly origin) makes the spin ride the orbit.
// m.get() with an unknown label throws — a typo'd label must never silently
// animate nothing.

function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

const DEG_TO_RAD = Math.PI / 180;

// Compile the copied module text into live clips via a Blob import — the same
// sandboxing (page realm, no source-tree access) the pose hatch used.
export async function compileAnimationClips(moduleSource) {
  const text = String(moduleSource || "").trim();
  if (!text) {
    return {};
  }
  const blobUrl = URL.createObjectURL(new Blob([text], { type: "text/javascript" }));
  try {
    const module = await import(/* webpackIgnore: true */ /* @vite-ignore */ blobUrl);
    return normalizeAnimationClips(module?.clips);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

export function normalizeAnimationClips(rawClips) {
  const clips = {};
  for (const [id, raw] of Object.entries(isObject(rawClips) ? rawClips : {})) {
    if (!isObject(raw) || typeof raw.update !== "function") {
      continue;
    }
    const duration = Number(raw.duration);
    clips[String(id)] = {
      id: String(id),
      label: String(raw.label || id),
      duration: Number.isFinite(duration) && duration > 0 ? duration : 1,
      loop: raw.loop !== false,
      update: raw.update
    };
  }
  return clips;
}

// Index meshData parts by label for m.get(). Labels are occurrence names in
// the instance tree; every part whose name matches (or whose id sits inside a
// matching group occurrence) belongs to the handle.
function partIdsByLabel(meshData) {
  const byLabel = new Map();
  for (const part of meshData?.parts || []) {
    const label = String(part.label || part.name || "").trim();
    if (!label) {
      continue;
    }
    if (!byLabel.has(label)) {
      byLabel.set(label, []);
    }
    byLabel.get(label).push(String(part.id));
  }
  return byLabel;
}

// One frame's evaluation surface. Collects per-part effects; the caller
// applies them to display records exactly like pose/step-module effects.
export function createAnimationFrame(THREE, meshData) {
  const byLabel = partIdsByLabel(meshData);
  const matrices = new Map(); // partId -> THREE.Matrix4
  const styles = new Map(); // partId -> {opacity?, visible?}

  const handleFor = (label) => {
    const partIds = byLabel.get(label);
    if (!partIds || !partIds.length) {
      const known = [...byLabel.keys()].sort().join(", ") || "(none)";
      throw new Error(`animation: no occurrence labeled ${JSON.stringify(label)}; labels: ${known}`);
    }
    const applyMatrix = (matrix) => {
      for (const partId of partIds) {
        const current = matrices.get(partId);
        matrices.set(
          partId,
          current ? new THREE.Matrix4().multiplyMatrices(matrix, current) : matrix.clone()
        );
      }
    };
    const setStyle = (key, value) => {
      for (const partId of partIds) {
        const style = styles.get(partId) || {};
        style[key] = value;
        styles.set(partId, style);
      }
    };
    return {
      rotate(axis, degrees, origin = [0, 0, 0]) {
        const axisVec = new THREE.Vector3(axis[0], axis[1], axis[2]).normalize();
        const rotation = new THREE.Matrix4().makeRotationAxis(axisVec, (Number(degrees) || 0) * DEG_TO_RAD);
        const toOrigin = new THREE.Matrix4().makeTranslation(-origin[0], -origin[1], -origin[2]);
        const back = new THREE.Matrix4().makeTranslation(origin[0], origin[1], origin[2]);
        applyMatrix(new THREE.Matrix4().multiplyMatrices(back, new THREE.Matrix4().multiplyMatrices(rotation, toOrigin)));
        return this;
      },
      translate(vector) {
        applyMatrix(new THREE.Matrix4().makeTranslation(
          Number(vector[0]) || 0, Number(vector[1]) || 0, Number(vector[2]) || 0
        ));
        return this;
      },
      opacity(value) {
        setStyle("opacity", Math.max(0, Math.min(1, Number(value))));
        return this;
      },
      visible(value) {
        setStyle("visible", Boolean(value));
        return this;
      }
    };
  };

  const model = {
    get: handleFor,
    // Labels are enumerable so a clip can iterate without hardcoding.
    labels: () => [...byLabel.keys()].sort()
  };
  return { model, matrices, styles };
}

// Evaluate one clip at time t: a fresh frame each call (purity by
// construction). Returns {matrices, styles} keyed by part id.
export function evaluateAnimationClip(THREE, meshData, clip, t) {
  const frame = createAnimationFrame(THREE, meshData);
  const duration = clip.duration || 1;
  let localT = Math.max(0, Number(t) || 0);
  if (clip.loop !== false) {
    localT = localT % duration;
  } else {
    localT = Math.min(localT, duration);
  }
  clip.update(localT, frame.model);
  return { matrices: frame.matrices, styles: frame.styles };
}
