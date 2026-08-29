// Build progress for the artifact-status route: one reader
// (buildProgressSnapshot) serves every producer — a CLI model-script run, a
// CLI `cadgen import`, or the viewer's own import child — because they all
// write the same progress record beside the package, with the phase fields
// flattened in the exact shape the client's generating badge renders
// (artifactProgress.js).
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { buildProgressSnapshot, createCadgenOps, importsInFlightState } from "./cadgenOps.mjs";
import { _setCadgenProbeForTests } from "./cadgenResolve.mjs";
import { coordinationScope } from "./storePaths.mjs";
import { renderPackageDir } from "./scanner.mjs";

function tmpRoot(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-progress-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function writeRecord(scopePath, record) {
  fs.mkdirSync(path.dirname(scopePath), { recursive: true });
  fs.writeFileSync(
    path.join(path.dirname(scopePath), `.${path.basename(scopePath)}.generation.progress.json`),
    JSON.stringify(record),
  );
}

const RUNNING_RECORD = {
  schemaVersion: 1,
  runId: "run-1",
  outcome: null,
  updatedAt: Date.now(),
  phase: "components",
  label: "Meshing components",
  detail: "c0ffee",
  index: 3,
  count: 4,
  done: 3,
  total: 37,
  determinate: true,
};

test("a fresh in-flight record becomes a generating snapshot in badge shape", (t) => {
  const root = tmpRoot(t);
  const stepPath = path.join(root, "vendor.step");
  writeRecord(coordinationScope(stepPath), RUNNING_RECORD);
  const snapshot = buildProgressSnapshot(stepPath);
  assert.ok(snapshot);
  assert.equal(snapshot.writing, true);
  assert.equal(snapshot.runId, "run-1");
  // The record IS the progress payload: phase fields at the top level, which
  // is what normalizeArtifactProgress reads.
  assert.equal(snapshot.progress.phase, "components");
  assert.equal(snapshot.progress.label, "Meshing components");
  assert.equal(snapshot.progress.done, 3);
  assert.equal(snapshot.progress.total, 37);
  assert.equal(snapshot.progress.determinate, true);
});

test("finished and stale records report no progress", (t) => {
  const root = tmpRoot(t);
  const stepPath = path.join(root, "vendor.step");
  writeRecord(coordinationScope(stepPath), { ...RUNNING_RECORD, outcome: "ok" });
  assert.equal(buildProgressSnapshot(stepPath), null);
  writeRecord(coordinationScope(stepPath), { ...RUNNING_RECORD, updatedAt: Date.now() - 60_000 });
  assert.equal(buildProgressSnapshot(stepPath), null);
  assert.equal(buildProgressSnapshot(path.join(root, "absent.step")), null);
});

test("an in-flight import with no record yet still reports generating", async (t) => {
  _setCadgenProbeForTests(() => ({ ok: true, command: "cadgen", prefixArgs: [] }));
  t.after(() => _setCadgenProbeForTests(null));
  const root = tmpRoot(t);
  const step = path.join(root, "vendor.step");
  fs.writeFileSync(step, "ISO-10303-21;\nEND-ISO-10303-21;\n");
  const packageDir = renderPackageDir(step);
  // Stage an in-flight import (the child has not published a record yet).
  const inFlight = importsInFlightState();
  inFlight.set(packageDir, Promise.resolve({ ok: true }));
  t.after(() => inFlight.delete(packageDir));
  const ops = createCadgenOps(root);
  const status = await ops.artifactStatus(step);
  assert.equal(status.state, "generating");
  assert.equal(status.progress ?? null, null);
});
