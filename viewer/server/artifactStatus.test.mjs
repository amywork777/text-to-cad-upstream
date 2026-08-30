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
import { CACHE_SCHEMA_VERSION } from "./packageContract.mjs";
import { renderPackageDir } from "./storePaths.mjs";

function tempRoot(t, prefix) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  // Store-primary: packages resolve into the user-level store; isolate it
  // per-test exactly the way the Python runner does (CADGEN_CACHE_DIR).
  const previous = process.env.CADGEN_CACHE_DIR;
  process.env.CADGEN_CACHE_DIR = path.join(root, ".store");
  t.after(() => {
    if (previous === undefined) delete process.env.CADGEN_CACHE_DIR;
    else process.env.CADGEN_CACHE_DIR = previous;
  });
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
  components = ["c0"],
  withSurf = true,
} = {}) {
  // Unique per fixture name: content-keying would otherwise collide two
  // same-bytes fixtures into one store package.
  const stepBytes = `ISO-10303-21;\nfake step ${stepName}\n`;
  const stepPath = write(root, stepName, stepBytes);
  // Content-keyed store package for exactly the bytes just written.
  const packageDir = renderPackageDir(stepPath);
  const componentMap = {};
  for (const cid of components) {
    const rel = `components/${cid}.surf`;
    if (withSurf) {
      fs.mkdirSync(path.join(packageDir, "components"), { recursive: true });
      fs.writeFileSync(path.join(packageDir, rel), Buffer.from("SURF...."));
    }
    componentMap[cid] = { surf: rel };
  }
  const descriptor = { kind: "assembly-package", components: componentMap };
  if (generated) {
    // The MODEL-SIDE sidecar's existence is the generated marker; the store
    // descriptor is a pure function of the STEP bytes, no provenance at all.
    fs.writeFileSync(`${stepPath}.source.json`, JSON.stringify({ schemaVersion: 2, sourceKind: "python" }));
  }
  if (stepHash !== null) {
    descriptor.stepHash = stepHash === undefined ? sha256(stepBytes) : stepHash;
  }
  fs.mkdirSync(packageDir, { recursive: true });
  fs.writeFileSync(path.join(packageDir, "assembly.json"), JSON.stringify(descriptor));
  return stepPath;
}

test("imported STEP: fresh package is ready", (t) => {
  const root = tempRoot(t, "status-");
  const step = writeStepPackage(root, "imp.step");
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
});

test("imported STEP: the digest gate IS the content key — an edit unresolves the package", (t) => {
  const root = tempRoot(t, "status-");
  const step = writeStepPackage(root, "imp.step");
  assert.deepEqual(artifactStatus(step, root), { state: ARTIFACT_STATE.READY });
  // Edit the file: it hashes to a different key, so the package simply does
  // not resolve any more. No descriptor field is consulted, no re-hash gate
  // runs per poll — needs-build falls out of resolution itself.
  fs.appendFileSync(step, "\n");
  const status = artifactStatus(step, root);
  assert.equal(status.state, ARTIFACT_STATE.NEEDS_BUILD);
  assert.equal(status.reason, "missing_glb");
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

test("the schema gate lives in the package KEY, not the descriptor", (t) => {
  const root = tempRoot(t, "status-");
  // A bumped CACHE_SCHEMA_VERSION changes the -v<N> key salt, so an
  // old-generation package simply stops resolving: no descriptor field is
  // read to decide schema currency.
  const step = writeStepPackage(root, "imp.step");
  assert.equal(artifactStatus(step, root).state, ARTIFACT_STATE.READY);
  const packageDir = renderPackageDir(step);
  const oldGeneration = `${packageDir.slice(0, packageDir.lastIndexOf("-v"))}-v${CACHE_SCHEMA_VERSION - 1}`;
  fs.renameSync(packageDir, oldGeneration);
  const status = artifactStatus(step, root);
  assert.equal(status.state, ARTIFACT_STATE.NEEDS_BUILD);
  assert.equal(status.reason, "missing_glb");
});

test("missing payloads and package are buildable", (t) => {
  const root = tempRoot(t, "status-");
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
  const unbuilt = write(root, "unbuilt.step", "ISO-10303-21;\nno package\n");
  assert.deepEqual(artifactStatus(unbuilt, root, { snapshot: busy }), {
    state: ARTIFACT_STATE.NEEDS_BUILD, reason: "missing_glb", blocked: true,
  });
});

test("verdicts carry what the import path needs", (t) => {
  const root = tempRoot(t, "status-");
  const bare = write(root, "bare.step", "ISO-10303-21;\nbare\n");
  const verdict = resolveArtifactVerdict(bare, root);
  assert.equal(verdict.rawStep, true);
  assert.equal(verdict.generated, undefined);
  assert.equal(verdict.descriptor, undefined);
});
