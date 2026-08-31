// THE artifact-status authority: freshness verdicts computed here, in JS, from
// pure file reads — one implementation instead of the render_ops/degraded pair
// that had to be kept mirror-synced.
//
// What this module deliberately does NOT decide is "is a build in flight":
// that is kernel lock state (fcntl flock), which Node's stdlib cannot probe
// and which must never be re-inferred from pids, heartbeats, or age windows
// (see cadgen/coordination/lock.py for the measured failure modes of that
// design). The caller supplies a snapshot read from the build's progress
// record beside the package — a CLI run's or the server's own `cadgen
// import` child's; one reader serves every producer (cadgenOps.mjs).
//
// Freshness semantics (mirrored constants are pinned by the render-contract
// sync test):
// - packages must exist, parse, declare the exact schema version, and have
//   every payload file on disk;
// - STEP bakes no settings, so a descriptor recording a bakeHash came from
//   another producer and is stale;
// - an IMPORTED file's digest must match the descriptor (file->render
//   coherence);
// - generated outputs are DETACHED from their source code: no source checks,
//   ever (the CLI's no-op gates own that direction).
import fs from "node:fs";
import path from "node:path";

import { renderPackageDir, sourceSidecarPath } from "./scanner.mjs";
import { sourceProvenanceRecordPath } from "./storePaths.mjs";

const STEP_PACKAGE_KIND = "assembly-package";
const STEP_DESCRIPTOR_NAME = "assembly.json";

// Artifacts only (design/library-first-generation.md): model scripts are not
// status subjects — python-backedness is descriptor provenance, not naming.
const STEP_ENTRY_RE = /\.(step|stp)$/i;
const RAW_STEP_RE = /\.(step|stp)$/i;

export const ARTIFACT_STATE = Object.freeze({
  READY: "ready",
  GENERATING: "generating",
  NEEDS_BUILD: "needs-build",
  ERROR: "error",
});

// Codes the client may build on (mirror of the retired BUILDABLE_ARTIFACT_CODES).
const BUILDABLE_CODES = new Set([
  "missing_glb", "missing_step_topology", "unsupported_step_topology",
  "missing_source_path", "missing_dxf_output",
]);

function readJson(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

// --- generated vs imported ---------------------------------------------------
/**
 * Was this document GENERATED (a declaration owns it) or IMPORTED (a foreign
 * file the viewer may offer to bring in)?
 *
 * The model-side sidecar used to answer this on its own, and stopped being able
 * to at schema 5: it now carries DECLARATIONS only, and is written only when the
 * model declares something (kinematics, animation, mesh exports). A plain
 * generated model has no sidecar, so sidecar-existence alone called every one of
 * them imported and offered a STEP-import button for a file whose real fix is
 * rerunning its script.
 *
 * The authority is the provenance RECORD, which every generated build writes:
 * <cache>/records/<sha256(abs artifact path)[:24]>.source.json. Present and
 * naming a sourceKind => generated; absent, unreadable, or empty => imported.
 *
 * That fallback is deliberate, not defensive sloppiness. The records tier is
 * evictable (`cadgen cache gc` sweeps it), so "no record" is a routine state, not
 * a fault: reading it must never raise. An evicted record costs one wrong badge
 * until the next build re-records it — the same rebuild an eviction always costs.
 */
function isGeneratedDocument(stepPath) {
  if (fs.existsSync(sourceSidecarPath(stepPath))) {
    return true;
  }
  const record = readJson(sourceProvenanceRecordPath(stepPath));
  return Boolean(record && String(record.sourceKind || "").trim());
}

// --- ownership + source resolution (render_ops twins) ------------------------
export function ownsStepPath(filePath) {
  return STEP_ENTRY_RE.test(String(filePath || ""));
}

export function ownsDxfPath() {
  // Generated-DXF entries were `.dxf.py` scripts; scripts are no longer
  // entries, and a plain `.dxf` renders directly with no artifact to manage.
  return false;
}

function resolveCandidate(fileRef, rootDir) {
  const normalized = String(fileRef || "").trim().replace(/\\/g, "/");
  if (!normalized) {
    return null;
  }
  const candidate = path.isAbsolute(normalized)
    ? path.resolve(normalized)
    : path.resolve(rootDir, normalized.replace(/^\/+/, ""));
  return fs.existsSync(candidate) ? candidate : null;
}

// --- freshness verdicts ------------------------------------------------------
function validateStep(stepPath) {
  // Generated-vs-imported comes from cadgen's own provenance bookkeeping (the
  // records tier, with the model-side sidecar as a fast yes), never from a
  // descriptor field: the store descriptor is a pure function of the STEP bytes.
  //
  // Decided BEFORE the package gates, and carried on every verdict including the
  // failures. The import path reads `rawStep && !generated` to decide whether to
  // offer "import this STEP", and the case where that decision matters most is
  // precisely a document with NO package — which used to return before this line
  // ran, leaving `generated` undefined and offering to import a model whose real
  // fix is rerunning its script.
  const generated = isGeneratedDocument(stepPath);
  const packageDir = renderPackageDir(stepPath);
  if (!fs.existsSync(packageDir) || !fs.statSync(packageDir).isDirectory()) {
    return { ok: false, code: "missing_glb", packageDir, generated };
  }
  const descriptor = readJson(path.join(packageDir, STEP_DESCRIPTOR_NAME));
  if (descriptor === null) {
    return { ok: false, code: "missing_step_topology", packageDir, generated };
  }
  if (descriptor.kind !== STEP_PACKAGE_KIND) {
    return { ok: false, code: "unsupported_step_topology", packageDir, descriptor, generated };
  }
  const components = descriptor.components && typeof descriptor.components === "object"
    ? Object.values(descriptor.components)
    : [];
  if (!components.length) {
    return { ok: false, code: "missing_glb", packageDir, descriptor, generated };
  }
  for (const component of components) {
    const surf = String(component?.surf || "");
    if (!surf || !fs.existsSync(path.join(packageDir, surf))) {
      return { ok: false, code: "missing_glb", packageDir, descriptor, generated };
    }
  }
  // Nothing else to gate: the package KEY is <sha256(document)>-v<schema>, so
  // a package that resolved at all has the right schema and belongs to exactly
  // these bytes — the old schema, bake, and per-poll digest gates all
  // collapsed into content keying (and the digest re-hash was the one
  // full-file read every status poll used to pay). Generated outputs are
  // detached: no source checks, ever.
  return { ok: true, packageDir, descriptor, generated };
}

// --- the state machine --------------------------------------------------------
export function resolveArtifactVerdict(fileRef, rootDir) {
  const candidate = resolveCandidate(fileRef, rootDir);
  if (candidate === null) {
    return { error: `Artifact source not found: ${fileRef}` };
  }
  if (ownsStepPath(candidate)) {
    const verdict = validateStep(candidate);
    return {
      format: "step",
      candidate,
      rawStep: RAW_STEP_RE.test(candidate),
      ...verdict,
    };
  }
  return { error: `No render-artifact format owns this entry: ${fileRef}` };
}

/**
 * The /__cad/artifact GET state machine. `snapshot` is the kernel lock view:
 * {writing, busy, runId, progress} — null when no view is available.
 */
export function artifactStatus(fileRef, rootDir, { snapshot = null } = {}) {
  const verdict = resolveArtifactVerdict(fileRef, rootDir);
  if (verdict.error) {
    return { state: ARTIFACT_STATE.ERROR, error: verdict.error };
  }
  if (snapshot?.writing) {
    const status = { state: ARTIFACT_STATE.GENERATING };
    if (snapshot.runId) {
      status.runId = snapshot.runId;
    }
    if (snapshot.progress != null) {
      status.progress = snapshot.progress;
    }
    return status;
  }
  if (verdict.ok) {
    const status = { state: ARTIFACT_STATE.READY };
    if (snapshot?.busy) {
      status.busy = true;
      if (snapshot.runId) {
        status.runId = snapshot.runId;
      }
      if (snapshot.progress != null) {
        status.progress = snapshot.progress;
      }
    }
    return status;
  }
  if (BUILDABLE_CODES.has(verdict.code)) {
    const status = { state: ARTIFACT_STATE.NEEDS_BUILD, reason: verdict.code };
    if (snapshot?.busy) {
      status.blocked = true;
    }
    return status;
  }
  return { state: ARTIFACT_STATE.ERROR, reason: verdict.code, error: verdict.code };
}
