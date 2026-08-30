// The viewer half of the mates FK evaluator (design/pose-animation-split.md).
//
// The sidecar's kinematics block is pure data: typed mates over one resolved
// axis each (world-at-rest numbers, baked by the build), linear couplings, and
// named pose presets. This module folds DOF values through the mate tree into
// one delta matrix per mated occurrence subtree — no solver, no flips, and the
// same math the Python exporter runs, so a slider position and an exported
// pose agree to the bit.
//
// Semantics: THE ARTIFACT AS WRITTEN is q=0. A mate's motion is displacement
// about its axis from the written placement, expressed in world-at-rest
// space; a parent's delta carries its whole instance subtree. For occurrence
// rest transform R and accumulated delta D, the rendered transform is D * R —
// exactly the viewer's effectMatrix-premultiplies-baseTransform composition,
// so a mate delta IS an effect matrix.

function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

const DEG_TO_RAD = Math.PI / 180;

export function kinematicsMates(block) {
  return isObject(block) && Array.isArray(block.mates) ? block.mates : [];
}

// Every controllable DOF, in declaration order: mate DOFs first (cylindrical
// contributes "<name>.turn" and "<name>.travel"), then coupling DOFs. Each
// entry carries what a slider needs: id, kind, limits [lo, hi], default.
export function kinematicsDofs(block) {
  const dofs = [];
  for (const mate of kinematicsMates(block)) {
    const name = String(mate.name || "");
    if (!name) {
      continue;
    }
    if (mate.kind === "fastened") {
      continue;
    }
    const limits = isObject(mate.limits) ? mate.limits : {};
    if (mate.kind === "cylindrical") {
      for (const sub of ["turn", "travel"]) {
        dofs.push({
          id: `${name}.${sub}`,
          kind: sub === "turn" ? "revolute" : "slider",
          limits: Array.isArray(limits[sub]) ? limits[sub] : null
        });
      }
    } else {
      dofs.push({
        id: name,
        kind: String(mate.kind || ""),
        limits: Array.isArray(limits.value) ? limits.value : null
      });
    }
  }
  for (const coupling of (isObject(block) && Array.isArray(block.couplings) ? block.couplings : [])) {
    const name = String(coupling.name || "");
    if (name) {
      dofs.push({
        id: name,
        kind: "coupling",
        limits: Array.isArray(coupling.limits) ? coupling.limits : [0, 1]
      });
    }
  }
  return dofs;
}

export function kinematicsPoses(block) {
  return isObject(block) && isObject(block.poses) ? block.poses : {};
}

// Effective per-mate-DOF values: explicit value else 0 (ZERO IS THE ARTIFACT
// AS WRITTEN), plus every coupling's ratio * its value. Additive gearing is
// the whole coupling semantics — data in, arithmetic out, same in both
// runtimes.
export function effectiveDofValues(block, rawValues) {
  const values = isObject(rawValues) ? rawValues : {};
  const effective = {};
  for (const dof of kinematicsDofs(block)) {
    if (dof.kind === "coupling") {
      continue;
    }
    const raw = values[dof.id];
    effective[dof.id] = Number.isFinite(Number(raw)) && raw !== null && raw !== undefined && raw !== ""
      ? Number(raw)
      : 0;
  }
  for (const coupling of (isObject(block) && Array.isArray(block.couplings) ? block.couplings : [])) {
    const raw = values[String(coupling.name || "")];
    const amount = Number.isFinite(Number(raw)) && raw !== null && raw !== undefined && raw !== "" ? Number(raw) : 0;
    if (!amount || !isObject(coupling.gears)) {
      continue;
    }
    for (const [dof, ratio] of Object.entries(coupling.gears)) {
      effective[dof] = (Number(effective[dof]) || 0) + (Number(ratio) || 0) * amount;
    }
  }
  return effective;
}

function axisNumbers(mate) {
  const axis = isObject(mate.axis) ? mate.axis : {};
  const origin = Array.isArray(axis.origin) ? axis.origin.map(Number) : null;
  const dir = Array.isArray(axis.dir) ? axis.dir.map(Number) : null;
  if (!origin || !dir || origin.length !== 3 || dir.length !== 3) {
    // An unresolved ref should never reach a written sidecar; refuse rather
    // than render a wrong pose.
    throw new Error(`kinematics mate ${mate.name}: axis is not resolved to numbers`);
  }
  const length = Math.hypot(dir[0], dir[1], dir[2]) || 1;
  return { origin, dir: dir.map((v) => v / length) };
}

// D(axis, q) for one mate in world-at-rest space.
function mateMotionMatrix(THREE, mate, effective) {
  if (mate.kind === "fastened") {
    return new THREE.Matrix4();
  }
  const { origin, dir } = axisNumbers(mate);
  const axisVec = new THREE.Vector3(dir[0], dir[1], dir[2]);
  const originVec = new THREE.Vector3(origin[0], origin[1], origin[2]);
  const motion = new THREE.Matrix4();
  const rotate = (angleDeg) => {
    if (!angleDeg) {
      return;
    }
    const rotation = new THREE.Matrix4().makeRotationAxis(axisVec, angleDeg * DEG_TO_RAD);
    const toOrigin = new THREE.Matrix4().makeTranslation(-originVec.x, -originVec.y, -originVec.z);
    const back = new THREE.Matrix4().makeTranslation(originVec.x, originVec.y, originVec.z);
    motion.premultiply(toOrigin).premultiply(rotation).premultiply(back);
  };
  const translate = (distance) => {
    if (!distance) {
      return;
    }
    motion.premultiply(new THREE.Matrix4().makeTranslation(
      axisVec.x * distance, axisVec.y * distance, axisVec.z * distance
    ));
  };
  if (mate.kind === "revolute") {
    rotate(Number(effective[mate.name]) || 0);
  } else if (mate.kind === "slider") {
    translate(Number(effective[mate.name]) || 0);
  } else if (mate.kind === "cylindrical") {
    rotate(Number(effective[`${mate.name}.turn`]) || 0);
    translate(Number(effective[`${mate.name}.travel`]) || 0);
  }
  return motion;
}

// Topological order over the declared parent/child refs: parents before
// children, declaration order otherwise. The authoring layer guarantees the
// graph is a tree, so this always terminates.
function matesInTreeOrder(mates) {
  const byChild = new Map(mates.map((mate) => [mate.child, mate]));
  const ordered = [];
  const placed = new Set();
  const place = (mate) => {
    if (placed.has(mate.child)) {
      return;
    }
    const parentMate = byChild.get(mate.parent);
    if (parentMate && !placed.has(parentMate.child)) {
      place(parentMate);
    }
    placed.add(mate.child);
    ordered.push(mate);
  };
  for (const mate of mates) {
    place(mate);
  }
  return ordered;
}

// The evaluator: DOF values -> one delta Matrix4 per mated child ref
// ("#label" as declared). Apply each delta as the effect matrix of every part
// in that occurrence's subtree; a deeper mate's own children get their own
// (composed) delta.
export function kinematicsDeltas(THREE, block, rawValues) {
  const effective = effectiveDofValues(block, rawValues);
  const deltas = new Map();
  for (const mate of matesInTreeOrder(kinematicsMates(block))) {
    const parentDelta = deltas.get(mate.parent);
    const motion = mateMotionMatrix(THREE, mate, effective);
    const delta = parentDelta ? new THREE.Matrix4().multiplyMatrices(parentDelta, motion) : motion;
    deltas.set(mate.child, delta);
  }
  return deltas;
}

// True when every DOF sits at 0 — lets the viewer skip the effects pass
// entirely (and IS the "artifact as written is q=0" law).
export function kinematicsAtRest(block, rawValues) {
  const effective = effectiveDofValues(block, rawValues);
  const epsilon = 1e-9;
  for (const dof of kinematicsDofs(block)) {
    if (dof.kind === "coupling") {
      continue;
    }
    if (Math.abs(Number(effective[dof.id]) || 0) > epsilon) {
      return false;
    }
  }
  return true;
}
