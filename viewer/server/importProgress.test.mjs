// Live WASM-import progress: the child's `[import-progress] {json}` stderr
// lines become the artifact-status GENERATING payload, in the exact shape the
// client's generating badge already renders (artifactProgress.js) — so a
// minutes-long vendor-STEP import shows a real components bar, not an
// indeterminate spinner (design/FEEDBACK.md item 20).
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createCadgenOps,
  parseImportProgressLine,
  wasmImportProgressState,
  wasmImportsInFlightState,
} from "./cadgenOps.mjs";
import { renderPackageDir } from "./scanner.mjs";

test("parseImportProgressLine: events map to the badge's progress shape", () => {
  const components = parseImportProgressLine(
    '[import-progress] {"phase":"components","detail":"c0ffee","done":3,"total":37}\n',
  );
  assert.equal(components.phase, "components");
  assert.equal(components.label, "Extract components");
  assert.equal(components.detail, "c0ffee");
  assert.equal(components.done, 3);
  assert.equal(components.total, 37);
  assert.equal(components.determinate, true);
  assert.equal(components.index, 4);
  assert.equal(components.count, 5);
  assert.ok(components.updatedAt > 0);

  // A phase with no denominator is honest about it: indeterminate.
  const parse = parseImportProgressLine('[import-progress] {"phase":"parse","detail":"a.step"}');
  assert.equal(parse.determinate, false);
  assert.equal(parse.total, null);
  assert.equal(parse.index, 1);
});

test("parseImportProgressLine: non-progress and malformed lines are not progress", () => {
  for (const line of [
    "warning: something else on stderr",
    "[import-progress] not-json",
    '[import-progress] {"detail":"phase missing"}',
    "",
  ]) {
    assert.equal(parseImportProgressLine(line), null, JSON.stringify(line));
  }
});

test("artifact status serves live import progress while an import is in flight", async (t) => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "import-progress-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const stepPath = path.join(root, "vendor.step");
  fs.writeFileSync(stepPath, "ISO-10303-21;\nfake\n");
  const packageDir = renderPackageDir(stepPath);

  const inFlight = wasmImportsInFlightState();
  const progress = wasmImportProgressState();
  inFlight.set(packageDir, Promise.resolve({ ok: true }));
  progress.set(packageDir, {
    runId: "wasm-import-test-1",
    record: parseImportProgressLine(
      '[import-progress] {"phase":"components","detail":"c1","done":5,"total":12}',
    ),
  });
  t.after(() => {
    inFlight.delete(packageDir);
    progress.delete(packageDir);
  });

  const ops = createCadgenOps(root);
  const status = await ops.artifactStatus(stepPath);
  assert.equal(status.state, "generating");
  assert.equal(status.runId, "wasm-import-test-1");
  assert.equal(status.progress.phase, "components");
  assert.equal(status.progress.done, 5);
  assert.equal(status.progress.total, 12);
  assert.equal(status.progress.determinate, true);

  // Before the first event arrives the import still reports generating —
  // runId present, progress honestly absent.
  progress.set(packageDir, { runId: "wasm-import-test-1", record: null });
  const early = await ops.artifactStatus(stepPath);
  assert.equal(early.state, "generating");
  assert.equal(early.runId, "wasm-import-test-1");
});
