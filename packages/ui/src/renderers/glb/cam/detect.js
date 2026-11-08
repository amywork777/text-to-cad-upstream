/**
 * Whether a loaded GLB is a CAM result, and which kind. Its own small module, free of the CAM viewer, so GlbRenderer
 * can ask before that viewer's chunk is fetched.
 *
 * - **A plan** (text-to-cad 0.11's `cad <type> plan FILE --job JOB --out DIR`): the folder's `result.glb`, whose glTF
 *   asset `generator` is "cad plan". It is the picture only (the part, the stock, the toolpaths): its job is the
 *   `result.json` beside it, read through the workspace (`useCamView`).
 * - **An embedded job** (the 0.10 Studio line's `<stem>.cam.glb`, which a project may still hold): `generator:
 *   "cad cam"` in the extras of the scene or a node, and the whole job as `cam` (schema 1) in them.
 */

/** The glTF asset generator of a plan's `result.glb`. */
export const CAM_PLAN_GENERATOR = "cad plan";
/** The extras generator of a 0.10 `.cam.glb`. */
export const CAM_GENERATOR = "cad cam";
/** The file a plan writes its job into, beside its `result.glb`. */
export const CAM_PLAN_JSON = "result.json";

const plainObject = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

/** The `cam` extras an object of the scene carries, or null. */
export const camExtras = (object) => (plainObject(object?.userData?.cam) ? object.userData.cam : null);

/** Whether a scene carries a 0.10 job in its extras: `generator: "cad cam"` and `cam`. */
export function carriesCamJob(root) {
  let generator = false;
  let extras = false;
  root?.traverse?.((object) => {
    if (object?.userData?.generator === CAM_GENERATOR) generator = true;
    if (camExtras(object)) extras = true;
  });
  return generator && extras;
}

/** Whether a GLB document (core's `buildGlbDocumentFromBuffer`) is a 0.11 plan's `result.glb`: its asset says "cad plan". */
export function isCamPlan(document) {
  return document?.asset?.generator === CAM_PLAN_GENERATOR;
}

/** Which CAM result a GLB document is: "plan" (0.11, its job in `result.json`), "embedded" (0.10, its job in its extras), or null. */
export function camResultKind(document) {
  if (isCamPlan(document)) return "plan";
  return carriesCamJob(document?.scene) ? "embedded" : null;
}
