// The artifact-status authority's contract (ported from the retired Python
// validator suite when freshness moved to this single JS implementation):
// ready / needs-build / generating / error, schema and bake gates, the
// imported-file digest gate, and the detached-outputs policy for everything
// generated.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  ARTIFACT_STATE,
  artifactStatus,
  resolveArtifactVerdict,
} from "./artifactStatus.mjs";
import { STEP_PACKAGE_VERSION } from "./packageContract.mjs";

function tempRoot(t, prefix) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function write(root, rel, content) {
  const target = path.join(root, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
  return target;
}

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

// A package the validator considers current, with knobs for each gate.
function writeStepPackage(root, stepName, {
  generated = false,
  stepHash,
  schemaVersion = STEP_PACKAGE_VERSION,
  bakeHash,
  components = ["c0"],
  withSurf = true,
} = {}) {
  const stepBytes = "ISO-10303-21;\nfake step\n";
  const stepPath = write(root, stepName, stepBytes);
  const packageRel = path.join("__cadgen__", "models", stepName);
  const componentMap = {};
  for (const cid of components) {
    const rel = `components/${cid}.surf`;
    if (withSurf) {
      write(root, path.join(packageRel, rel), Buffer.from("SURF...."));
    }
    componentMap[cid] = { surf: rel };
  }
  const descriptor = { kind: "assembly-package", components: componentMap };
  if (generated) {
    // The source sidecar's EXISTENCE is the generated marker; the descriptor
    // itself is a pure function of the STEP bytes and carries no provenance.
    write(root, path.join(packageRel, "source.json"), JSON.stringify({ schemaVersion: 1, sourceKind: "python" }));
  }
  if (schemaVersion !== null) {
    descriptor.packageSchemaVersion = schemaVersion;
  }
  if (stepHash !== null) {
    descriptor.stepHash = stepHash === undefined ? sha256(stepBytes) : stepHash;
  }
  if (bakeHash !== undefined) {
    descriptor.bakeHash = bakeHash;
  }
  write(root, path.join(packageRel, "assembly.json"), JSON.stringify(descriptor));
  return stepPath;
}

test("imported STEP: fresh package is ready", (t) => {
  const root = tempRoot(t, "status-");
  const step = writeStepPackage(root, "imp.step");
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
});

test("imported STEP: digest gate fails closed (stale, blank, and absent hashes)", (t) => {
  const root = tempRoot(t, "status-");
  for (const [stepHash, reason] of [
    ["deadbeef", "stale_step_artifact"],
    ["", "missing_step_hash"],
    [null, "missing_step_hash"],
  ]) {
    const sub = fs.mkdtempSync(path.join(root, "case-"));
    const step = writeStepPackage(sub, "imp.step", { stepHash });
    const status = artifactStatus(step, sub);
    assert.equal(status.state, ARTIFACT_STATE.NEEDS_BUILD, `hash=${stepHash}`);
    assert.equal(status.reason, reason);
  }
});

test("generated entries are detached: no source checks, ever", (t) => {
  const root = tempRoot(t, "status-");
  // Python-backedness is the SOURCE SIDECAR's existence, never a sibling
  // filename: no stepHash recorded, source edited after the build — all READY.
  const step = writeStepPackage(root, "widget.step", { generated: true, stepHash: null });
  const generator = write(root, "widget.py", "from cadgen import step\n@step\ndef model():\n    return 1\n");
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
  fs.writeFileSync(generator, "from cadgen import step\n@step\ndef model():\n    return 999\n");
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
});

test("provenance owns the digest gate: a python-backed .step skips it", (t) => {
  const root = tempRoot(t, "status-");
  const step = writeStepPackage(root, "widget.step", { generated: true, stepHash: "recorded-at-export" });
  // The exported file's bytes do not match the recorded hash, but the source
  // SIDECAR says python-backed -> detached -> ready. No sibling script is
  // consulted (none exists here).
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
});

test("schema gate: strict equality, missing/old/stringified all unsupported (and buildable)", (t) => {
  const root = tempRoot(t, "status-");
  for (const schemaVersion of [null, STEP_PACKAGE_VERSION - 1, String(STEP_PACKAGE_VERSION)]) {
    const sub = fs.mkdtempSync(path.join(root, "case-"));
    const step = writeStepPackage(sub, "imp.step", { schemaVersion });
    const status = artifactStatus(step, sub);
    assert.equal(status.state, ARTIFACT_STATE.NEEDS_BUILD, `schema=${schemaVersion}`);
    assert.equal(status.reason, "unsupported_step_topology");
  }
});

test("STEP bakes nothing, so a recorded bake is stale; missing payloads and package are buildable", (t) => {
  const root = tempRoot(t, "status-");
  const baked = writeStepPackage(root, "baked.step", { bakeHash: "any-recorded-bake" });
  assert.equal(artifactStatus(baked, root).reason, "stale_step_artifact");
  const missingSurf = writeStepPackage(root, "gone.step", { withSurf: false });
  assert.equal(artifactStatus(missingSurf, root).reason, "missing_glb");
  const bare = write(root, "bare.step", "ISO-10303-21;\n");
  const status = artifactStatus(bare, root);
  assert.equal(status.state, ARTIFACT_STATE.NEEDS_BUILD);
  assert.equal(status.reason, "missing_glb");
});

test("drawing scripts are not status subjects (artifacts-only)", (t) => {
  const root = tempRoot(t, "status-");
  // Scripts are never catalog entries; a .dxf renders directly with no
  // artifact to manage, so status owns neither form.
  const generator = write(root, "outline.py", "from cadgen import dxf\n@dxf\ndef drawing():\n    return None\n");
  assert.equal(artifactStatus(generator, root).state, ARTIFACT_STATE.ERROR);
  const drawing = write(root, "outline.dxf", "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n");
  assert.equal(artifactStatus(drawing, root).state, ARTIFACT_STATE.ERROR);
});

test("the lock snapshot decides generating/busy/blocked; freshness decides the rest", (t) => {
  const root = tempRoot(t, "status-");
  const step = writeStepPackage(root, "imp.step");
  const writing = { writing: true, busy: false, runId: "run-1", progress: { ratio: 0.5 } };
  assert.deepEqual(artifactStatus(step, root, { snapshot: writing }), {
    state: ARTIFACT_STATE.GENERATING, runId: "run-1", progress: { ratio: 0.5 },
  });
  const busy = { writing: false, busy: true, runId: "run-2", progress: null };
  assert.deepEqual(artifactStatus(step, root, { snapshot: busy }), {
    state: ARTIFACT_STATE.READY, busy: true, runId: "run-2",
  });
  const stale = writeStepPackage(root, "stale.step", { stepHash: "deadbeef" });
  assert.deepEqual(artifactStatus(stale, root, { snapshot: busy }), {
    state: ARTIFACT_STATE.NEEDS_BUILD, reason: "stale_step_artifact", blocked: true,
  });
});

test("verdicts carry what the degraded path needs", (t) => {
  const root = tempRoot(t, "status-");
  const stale = writeStepPackage(root, "stale.step", { stepHash: "deadbeef" });
  const verdict = resolveArtifactVerdict(stale, root);
  assert.equal(verdict.rawStep, true);
  assert.equal(verdict.digestMismatch, true);
  assert.ok(verdict.descriptor);
});
