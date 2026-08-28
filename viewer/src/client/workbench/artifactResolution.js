// The decision logic behind useArtifact, as pure functions.
//
// Extracted so it can be tested directly: the rules below are where the client decides
// whether to START a build or WATCH someone else's, and getting that wrong is expensive
// (a duplicate multi-minute OCP build) but invisible in a rendered component.

export const ARTIFACT_ACTION_READY = "ready";
export const ARTIFACT_ACTION_ERROR = "error";
export const ARTIFACT_ACTION_ATTACH = "attach";
export const ARTIFACT_ACTION_BUILD = "build";

/**
 * What the client should do about a status payload from `GET /__cad/artifact`.
 *
 * Only `needs-build` starts a build. `generating` means another process already holds
 * this model's lock — a `cad gen` in a terminal, another viewer tab — so we attach to
 * that run and watch it. POSTing there is what used to make the user wait out the peer's
 * build and then pay for a full duplicate rebuild.
 *
 * `blocked` is the server saying the artifact is stale AND its generator is occupied, so
 * a build would only queue behind the peer: attach rather than POST into a lock.
 */
export function artifactActionFor(status) {
  const state = String(status?.state || "ready");
  if (state === ARTIFACT_ACTION_READY) {
    return ARTIFACT_ACTION_READY;
  }
  if (state === ARTIFACT_ACTION_ERROR) {
    return ARTIFACT_ACTION_ERROR;
  }
  if (state === "generating" || status?.blocked) {
    return ARTIFACT_ACTION_ATTACH;
  }
  return ARTIFACT_ACTION_BUILD;
}

/**
 * The advisory flags a `ready` status may carry: `stale` (+`staleReason`) when a
 * degraded-mode package renders as-is although its source file changed, `busy` when
 * another process currently holds the model's generator. Neither changes what the
 * client DOES — the model renders — they are honest badges for the file sheet.
 * Returns null when there is nothing to surface, so `advisory` is falsy in the
 * overwhelmingly common case.
 */
export function artifactAdvisoryFor(status) {
  const stale = status?.stale === true;
  const busy = status?.busy === true;
  if (!stale && !busy) {
    return null;
  }
  return {
    stale,
    staleReason: String(status?.staleReason || "").trim(),
    busy,
    runId: status?.runId ? String(status.runId) : "",
  };
}

/**
 * Reconcile a freshly polled status against the run whose bar is currently on screen.
 *
 * Returns `{ runId, progress, handedOff }`. The server's ratio is monotonic only WITHIN a
 * run, so when one run hands off to another (one dies and another starts; a CLI run ends
 * and the viewer's own begins) the old position must be dropped rather than carried —
 * carrying it is what made the bar jump backwards.
 */
export function reconcileArtifactRun(shownRunId, status, progress) {
  const runId = status?.runId ? String(status.runId) : null;
  const handedOff = runId !== null && shownRunId !== null && runId !== shownRunId;
  return {
    runId: runId === null ? shownRunId : runId,
    progress: handedOff ? null : progress || null,
    handedOff,
  };
}
