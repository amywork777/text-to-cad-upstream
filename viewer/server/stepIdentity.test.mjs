// A cadgen-GENERATED .step must never be importable through the viewer:
// packages are gitignored, so generated files routinely arrive bare, and the
// import would overwrite/park a derived package that loses generated colors,
// the params sidecar, and provenance (the planetary-pilot regression).
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { cadgenStepIdentity } from "./stepIdentity.mjs";
import { createCadgenOps } from "./cadgenOps.mjs";
import { _setCadgenProbeForTests } from "./cadgenResolve.mjs";
import { STEP_PACKAGE_VERSION } from "./packageContract.mjs";

// The same property-graph shape export_build123d_step_file writes (verified
// against a real assembled planetary_gear_assembly.step trailer).
function generatedStepText(sourcePath = "colored.py") {
  return [
    "ISO-10303-21;",
    "HEADER;",
    "FILE_DESCRIPTION(('Open CASCADE Model'),'2;1');",
    "ENDSEC;",
    "DATA;",
    "#5=PRODUCT_DEFINITION('design','',#6,#7);",
    "#51=REPRESENTATION_CONTEXT('','');",
    "#100=DESCRIPTIVE_REPRESENTATION_ITEM('cadgen:generator','cadgen');",
    "#101=REPRESENTATION('cadgen:generator',(#100),#51);",
    "#102=PROPERTY_DEFINITION('cadgen metadata','cadgen:generator',#5);",
    "#103=PROPERTY_DEFINITION_REPRESENTATION(#102,#101);",
    `#104=DESCRIPTIVE_REPRESENTATION_ITEM('cadgen:sourcePath','${sourcePath}');`,
    `#105=REPRESENTATION('cadgen:sourcePath',(#104),#51);`,
    "#106=PROPERTY_DEFINITION('cadgen metadata','cadgen:sourcePath',#5);",
    "#107=PROPERTY_DEFINITION_REPRESENTATION(#106,#105);",
    "ENDSEC;",
    "END-ISO-10303-21;",
    "",
  ].join("\n");
}

const VENDOR_STEP_TEXT = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n";

function tempRoot(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "step-identity-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function write(root, rel, content) {
  const target = path.join(root, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
  return target;
}

test("cadgenStepIdentity: parses the generated trailer, null for vendor files", (t) => {
  const root = tempRoot(t);
  const generated = write(root, "gen.step", generatedStepText("models/colored.py"));
  assert.deepEqual(cadgenStepIdentity(generated), {
    generator: "cadgen",
    sourcePath: "models/colored.py",
  });
  const vendor = write(root, "vendor.step", VENDOR_STEP_TEXT);
  assert.equal(cadgenStepIdentity(vendor), null);
  // Metadata only counts when BOTH generator and sourcePath are present.
  const partial = write(root, "partial.step", generatedStepText().replace(/cadgen:sourcePath/g, "cadgen:other"));
  assert.equal(cadgenStepIdentity(partial), null);
});

test("bare generated .step: status names the script, build refuses (force included)", async (t) => {
  const root = tempRoot(t);
  write(root, "colored.step", generatedStepText("colored.py"));
  _setCadgenProbeForTests(() => ({ ok: true, command: "cadgen", prefixArgs: [] }));
  t.after(() => _setCadgenProbeForTests(null));
  const ops = createCadgenOps(root);

  const status = await ops.artifactStatus("colored.step");
  assert.equal(status.state, "error");
  assert.match(status.error, /python colored\.py/);
  assert.equal(status.stepImport, undefined);

  for (const force of [false, true]) {
    const build = await ops.buildArtifact("colored.step", { force });
    assert.equal(build.ok, false, `force=${force}`);
    assert.match(build.error, /python colored\.py/);
  }
});

test("generated .step over an accidentally-imported package: renders as-is, badged with the remedy", async (t) => {
  const root = tempRoot(t);
  const stepText = generatedStepText("colored.py");
  write(root, "colored.step", stepText);
  // A structurally-valid IMPORTED package (the accidental-import aftermath):
  // matching digest so plain freshness would call it READY+importable-rebuild.
  const crypto = await import("node:crypto");
  const stepHash = crypto.createHash("sha256").update(stepText).digest("hex");
  const packageRel = path.join("__cadgen__", "models", "colored.step");
  write(root, path.join(packageRel, "components", "c0.surf"), Buffer.from("SURF...."));
  write(root, path.join(packageRel, "assembly.json"), JSON.stringify({
    kind: "assembly-package",
    packageSchemaVersion: STEP_PACKAGE_VERSION,
    stepHash,
    components: { c0: { surf: "components/c0.surf" } },
  }));
  // Make the digest MISMATCH (needs-build territory) so the guard is what
  // decides, not ordinary freshness: append a trailing newline to the file.
  fs.appendFileSync(path.join(root, "colored.step"), "\n");

  _setCadgenProbeForTests(() => ({ ok: true, command: "cadgen", prefixArgs: [] }));
  t.after(() => _setCadgenProbeForTests(null));
  const ops = createCadgenOps(root);

  const status = await ops.artifactStatus("colored.step");
  assert.equal(status.state, "ready");
  assert.equal(status.stale, true);
  assert.match(status.staleReason, /python colored\.py/);

  const build = await ops.buildArtifact("colored.step", { force: true });
  assert.equal(build.ok, false);
  assert.match(build.error, /python colored\.py/);
});

test("vendor .step without metadata keeps the import offer", async (t) => {
  const root = tempRoot(t);
  write(root, "vendor.step", VENDOR_STEP_TEXT);
  _setCadgenProbeForTests(() => ({ ok: true, command: "cadgen", prefixArgs: [] }));
  t.after(() => _setCadgenProbeForTests(null));
  const ops = createCadgenOps(root);

  const status = await ops.artifactStatus("vendor.step");
  assert.equal(status.state, "needs-build");
  assert.equal(status.stepImport, true);
});
