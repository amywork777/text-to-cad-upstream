// Planetary gear escape hatch: the genuinely computational tail the
// declarative pose block cannot express (design: pose-framework) —
// a procedural THREE overlay (the planet-orbit guide ring) and the
// time-conditioned meshing-highlight pulse. Everything else about this model
// (kinematics, explode, styles, animations) is declarative on the decorator.
//
// Contract: the ctx here is the full legacy sidecar ctx; this module runs
// AFTER the declarative pass each frame.

const CARRIER_RATIO_FIXED_RING = 24 / (24 + 60);
let orbitGuide = null;

function createOrbitGuide(THREE) {
  const radius = 42;
  const points = [];
  for (let index = 0; index <= 144; index += 1) {
    const angle = (index / 144) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 4));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.55 });
  return new THREE.Line(geometry, material);
}

export default {
  setup({ THREE, modelGroup, cleanup }) {
    if (!THREE || !modelGroup) {
      return;
    }
    orbitGuide = createOrbitGuide(THREE);
    modelGroup.add(orbitGuide);
    cleanup(() => {
      modelGroup.remove(orbitGuide);
      orbitGuide.geometry?.dispose?.();
      orbitGuide.material?.dispose?.();
      orbitGuide = null;
    });
  },

  update({ params, effects, time }) {
    const drive = Number(params.drive) || 0;
    const carrierAngle = drive * CARRIER_RATIO_FIXED_RING;
    if (orbitGuide) {
      orbitGuide.visible = params.orbitGuides !== false;
      orbitGuide.rotation.z = (carrierAngle * Math.PI) / 180;
    }
    // The meshing highlight PULSES during playback (a window of each cycle);
    // the always-on case is declarative (see the highlightMeshing palettes).
    const pulsing = params.highlightMeshing === true &&
      time.playing && !(time.progress > 0.45 && time.progress < 0.6);
    if (pulsing) {
      effects.style("sun", { emissive: "", emissiveIntensity: 0 });
      effects.style(["planet1", "planet2", "planet3"], { emissive: "", emissiveIntensity: 0 });
    } else if (params.highlightMeshing === true) {
      effects.highlight(["sun", "planet1", "planet2", "planet3"], true);
    }
  }
};
