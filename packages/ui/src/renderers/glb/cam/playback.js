/**
 * A CAM result's routines on Preview's playbar (the renderer's own clips, `useGlbAnimation`): **Simulate**
 * plays the whole program, and a job with more than one setup adds **Simulate <setup>** for each. The
 * program's real time is played faster, the whole job in at most `SIMULATE_SECONDS` (one that is shorter
 * plays in real time), every clip at the same pace. A clip's moment is the program's time (`_CAM_T`).
 *
 * And what the scene's meshes are: the finished part, and the simulated stock, after the job or, where the
 * file stores it after each operation (`operation` in a stock node's extras), after the operation played.
 * Pure but for the visibility it sets.
 */

export const SIMULATE_SECONDS = 30;
const MIN_SECONDS = 2;

/** How fast the program plays (clip seconds per program second), and its span. */
export function camTimeline(job) {
  const end = Math.max(job?.durationS || 0, ...(job?.operations || []).map((op) => op.t1), 0);
  const seconds = Math.min(Math.max(end, MIN_SECONDS), SIMULATE_SECONDS);
  return { from: 0, to: end, pace: end > 0 ? seconds / end : 1 };
}

/**
 * The clips: `{ id, label, duration, play: { apply(elapsedSec), release() } }`, each moving `onMoment` to
 * `{ t, setup }` (the program's time, and the setup a setup's clip plays, null for Simulate) as it plays,
 * and to null when it lets go. None for a job with no time to play.
 */
export function camClips(job, onMoment) {
  const timeline = camTimeline(job);
  if (!(timeline.to > 0)) return [];
  const clip = (id, label, from, to, setup) => {
    const duration = Math.max((to - from) * timeline.pace, MIN_SECONDS);
    return {
      id, label, duration,
      play: {
        apply(elapsedSec) { onMoment({ t: from + Math.min(Math.max(elapsedSec / duration, 0), 1) * (to - from), setup }); },
        release() { onMoment(null); },
      },
    };
  };
  const clips = [clip("cam:simulate", "Simulate", timeline.from, timeline.to, null)];
  if (job.setups.length > 1) {
    for (const setup of job.setups) {
      if (!setup.operations.length) continue;
      const from = Math.min(...setup.operations.map((op) => op.t0));
      const to = Math.max(...setup.operations.map((op) => op.t1));
      if (to > from) clips.push(clip(`cam:setup:${setup.id}`, `Simulate ${setup.plain}`, from, to, setup.id));
    }
  }
  return clips;
}

/** Whether a mesh of the result is the stock: its extras say so, or its name does. */
function isStock(object) {
  const kind = String(object.userData?.kind || object.userData?.cam_kind || object.userData?.role || "").toLowerCase();
  if (kind) return kind === "stock";
  return /stock/i.test(`${object.userData?.name || ""} ${object.name || ""}`);
}

/** The result's meshes: the part's and the stock's, a stock with the operation it is after (`after`, null for the job's end). */
export function camSceneMeshes(root) {
  const part = [];
  const stock = [];
  root?.traverse?.((object) => {
    if (!object.isMesh || object.userData?.camDrawn) return;
    if (isStock(object)) {
      const after = Number(object.userData?.operation ?? object.userData?.after_operation);
      stock.push({ object, after: Number.isInteger(after) ? after : null });
    } else part.push(object);
  });
  return { part, stock };
}

/**
 * Shows the part and the stock as Display says. The stock shown is the job's end (a mesh with no
 * operation, else the last operation's); while a moment plays, the stock after the last operation that has
 * finished by then, where the file has one per operation. Returns whether anything changed.
 */
export function showCamMeshes(meshes, job, { part = true, stock = true, time = null } = {}) {
  let changed = false;
  const set = (object, visible) => {
    if (object.visible !== visible) { object.visible = visible; changed = true; }
  };
  for (const object of meshes.part) set(object, part);
  const staged = meshes.stock.filter((entry) => entry.after !== null).sort((a, b) => a.after - b.after);
  const final = meshes.stock.find((entry) => entry.after === null) || staged[staged.length - 1] || null;
  let current = final;
  if (time !== null && staged.length) {
    const done = new Set((job?.operations || []).filter((op) => op.t1 <= time).map((op) => op.index));
    current = null;
    for (const entry of staged) if (done.has(entry.after)) current = entry;
  }
  for (const entry of meshes.stock) set(entry.object, stock && entry === current);
  return changed;
}
