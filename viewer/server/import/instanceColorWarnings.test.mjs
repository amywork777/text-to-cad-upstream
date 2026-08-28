// The honest slice of the GetInstanceColor gap (design/FEEDBACK.md item 18):
// when some instances of a prototype resolved their own color and siblings
// fell through to the prototype's, native OCCT might have colored the
// fall-throughs differently — the import must SAY so instead of silently
// rendering the shared color. Pure-tree tests (no kernel), plus the status
// surface: warnings persisted on the descriptor reach every ready status.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { instanceColorWarnings, STEP_PACKAGE_VERSION } from "./stepImport.mjs";
import { artifactStatus } from "../artifactStatus.mjs";

function leaf(prototypeKey, colorSource, name = prototypeKey) {
  return { prototypeKey, colorSource, name, sourceName: name, children: [] };
}

test("mixed instance/prototype color resolution on one prototype warns, once", () => {
  const roots = [{
    prototypeKey: null,
    children: [
      leaf("0:1:1:1", "instance", "Bolt"),
      leaf("0:1:1:1", "prototype", "Bolt"),
      leaf("0:1:1:1", null, "Bolt"),
      // A second, uniformly-colored prototype must not add noise.
      leaf("0:1:1:2", "prototype", "Washer"),
      leaf("0:1:1:2", "prototype", "Washer"),
    ],
  }];
  const warnings = instanceColorWarnings(roots);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /"Bolt"/);
  assert.match(warnings[0], /1 instance\(s\) carry/);
  assert.match(warnings[0], /2 resolved to the shared part color/);
  assert.match(warnings[0], /GetInstanceColor/);
});

test("uniform assemblies never warn", () => {
  for (const source of ["instance", "prototype", null]) {
    const roots = [{
      prototypeKey: null,
      children: [leaf("p", source), leaf("p", source), leaf("q", source)],
    }];
    assert.deepEqual(instanceColorWarnings(roots), [], `source=${source}`);
  }
});

test("descriptor importWarnings surface on every ready artifact status", (t) => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "import-warn-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const stepBytes = "ISO-10303-21;\nfake\n";
  fs.writeFileSync(path.join(root, "vendor.step"), stepBytes);
  const packageDir = path.join(root, "__cadgen__", "models", "vendor.step");
  fs.mkdirSync(path.join(packageDir, "components"), { recursive: true });
  fs.writeFileSync(path.join(packageDir, "components", "c0.surf"), "SURF....");
  fs.writeFileSync(path.join(packageDir, "assembly.json"), JSON.stringify({
    kind: "assembly-package",
    sourceKind: "step",
    packageSchemaVersion: STEP_PACKAGE_VERSION,
    stepHash: createHash("sha256").update(stepBytes).digest("hex"),
    components: { c0: { surf: "components/c0.surf" } },
    importWarnings: ["per-instance colors may be incomplete for \"Bolt\": ..."],
  }));
  const status = artifactStatus(path.join(root, "vendor.step"), root);
  assert.equal(status.state, "ready");
  assert.equal(status.warnings.length, 1);
  assert.match(status.warnings[0], /Bolt/);
});
