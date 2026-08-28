// THE artifact-status authority: freshness verdicts computed here, in JS, from
// pure file reads — one implementation instead of the render_ops/degraded pair
// that had to be kept mirror-synced.
//
// What this module deliberately does NOT decide is "is a build in flight":
// that is kernel lock state (fcntl flock), which Node's stdlib cannot probe
// and which must never be re-inferred from pids, heartbeats, or age windows
// (see cadgen/coordination/lock.py for the measured failure modes of that
// design). The caller supplies a snapshot — from the one remaining Python
// status primitive (`render_ops snapshot`) when a runtime exists, or from the
// server's own in-flight WASM import map when it does not.
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
//
// Implicit models are NOT validated here: they render live from their own
// source in the client, so the viewer has no implicit artifact to be stale.
// Their baked packages exist for the CLI export/snapshot path only.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { renderPackageDir } from "./scanner.mjs";
import { STEP_PACKAGE_VERSION } from "./import/stepImport.mjs";

const STEP_PACKAGE_KIND = "assembly-package";
const STEP_DESCRIPTOR_NAME = "assembly.json";

const STEP_ENTRY_RE = /\.(step|stp)(\.py)?$/i;
const RAW_STEP_RE = /\.(step|stp)$/i;
const DXF_GENERATOR_RE = /\.dxf\.py$/i;

export const ARTIFACT_STATE = Object.freeze({
  READY: "ready",
  GENERATING: "generating",
  NEEDS_BUILD: "needs-build",
  ERROR: "error",
});

// Codes the client may build on (mirror of the retired BUILDABLE_ARTIFACT_CODES).
const BUILDABLE_CODES = new Set([
  "missing_glb", "missing_step_topology", "unsupported_step_topology",
  "missing_step_hash", "stale_step_artifact", "missing_source_path",
  "missing_dxf_output",
]);

function sha256File(filePath) {
  try {
    return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  } catch {
    return null;
  }
}

function readJson(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function schemaVersionMatches(descriptor, expected) {
  const recorded = descriptor.packageSchemaVersion;
  return typeof recorded === "number" && Number.isInteger(recorded) && recorded === expected;
}

function bakeHashMatches(descriptor, expected) {
  const recorded = descriptor.bakeHash ?? null;
  return (recorded ?? null) === (expected ?? null);
}

// --- ownership + source resolution (render_ops twins) ------------------------
export function ownsStepPath(filePath) {
  return STEP_ENTRY_RE.test(String(filePath || ""));
}

export function ownsDxfPath(filePath) {
  return DXF_GENERATOR_RE.test(String(filePath || ""));
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

function fileHasPythonGenerator(filePath, generatorName) {
  try {
    return new RegExp(`\\b${generatorName}\\s*\\(`).test(fs.readFileSync(filePath, "utf8"));
  } catch {
    return false;
  }
}

// resolve_step_source twin: the entry's package is keyed by the STEP path, and
// a same-stem `<name>.step.py` generator owns the entry even when the exported
// `<name>.step` sits beside it.
export function resolveStepSource(candidate) {
  if (candidate.toLowerCase().endsWith(".py")) {
    const stem = path.basename(candidate).slice(0, -".py".length);
    const stepBase = /\.(step|stp)$/i.test(stem) ? stem : `${stem}.step`;
    return { stepPath: path.join(path.dirname(candidate), stepBase), generated: true };
  }
  const generator = `${candidate}.py`;
  if (fs.existsSync(generator) && fileHasPythonGenerator(generator, "gen_step")) {
    return { stepPath: candidate, generated: true };
  }
  return { stepPath: candidate, generated: false };
}

// --- freshness verdicts ------------------------------------------------------
function validateStep(candidate) {
  const { stepPath, generated } = resolveStepSource(candidate);
  const packageDir = renderPackageDir(stepPath);
  if (!fs.existsSync(packageDir) || !fs.statSync(packageDir).isDirectory()) {
    return { ok: false, code: "missing_glb", packageDir };
  }
  const descriptor = readJson(path.join(packageDir, STEP_DESCRIPTOR_NAME));
  if (descriptor === null) {
    return { ok: false, code: "missing_step_topology", packageDir };
  }
  if (descriptor.kind !== STEP_PACKAGE_KIND || !schemaVersionMatches(descriptor, STEP_PACKAGE_VERSION)) {
    return { ok: false, code: "unsupported_step_topology", packageDir, descriptor };
  }
  const components = descriptor.components && typeof descriptor.components === "object"
    ? Object.values(descriptor.components)
    : [];
  if (!components.length) {
    return { ok: false, code: "missing_glb", packageDir, descriptor };
  }
  for (const component of components) {
    const surf = String(component?.surf || "");
    if (!surf || !fs.existsSync(path.join(packageDir, surf))) {
      return { ok: false, code: "missing_glb", packageDir, descriptor };
    }
  }
  // STEP bakes no settings; a descriptor claiming one came from another producer.
  if (!bakeHashMatches(descriptor, null)) {
    return { ok: false, code: "stale_step_artifact", packageDir, descriptor };
  }
  if (generated) {
    // Detached outputs: no source checks. A dangling entry cannot happen (the
    // catalog lists generated entries by their source file).
    return { ok: true, packageDir, descriptor };
  }
  // Imported file: the render is DERIVED from these bytes. Fails closed.
  const recorded = String(descriptor.stepHash || "").trim();
  if (fs.existsSync(stepPath)) {
    if (!recorded) {
      return { ok: false, code: "missing_step_hash", packageDir, descriptor };
    }
    const current = sha256File(stepPath);
    if (current && recorded !== current) {
      return { ok: false, code: "stale_step_artifact", digestMismatch: true, packageDir, descriptor };
    }
  }
  return { ok: true, packageDir, descriptor };
}

function validateDxf(candidate) {
  const packageDir = renderPackageDir(candidate);
  if (!fs.existsSync(candidate)) {
    return { ok: false, code: "missing_source_path", packageDir };
  }
  // The sibling .dxf IS what the client parses: its absence is the only
  // build-worthy state (source edits are the CLI no-op gate's business).
  const sibling = candidate.slice(0, -".py".length);
  if (!fs.existsSync(sibling)) {
    return { ok: false, code: "missing_dxf_output", packageDir };
  }
  return { ok: true, packageDir };
}

// --- the state machine --------------------------------------------------------
export function resolveArtifactVerdict(fileRef, rootDir) {
  const candidate = resolveCandidate(fileRef, rootDir);
  if (candidate === null) {
    return { error: `Artifact source not found: ${fileRef}` };
  }
  if (ownsDxfPath(candidate)) {
    return { format: "dxf", candidate, ...validateDxf(candidate) };
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
    // Import-time caveats ride the descriptor (e.g. the WASM kernel's
    // GetInstanceColor gap): honest, persistent, and shown on every open —
    // not just in the one build response the importer happened to see.
    const importWarnings = verdict.descriptor?.importWarnings;
    if (Array.isArray(importWarnings) && importWarnings.length) {
      status.warnings = importWarnings.map(String);
    }
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
