import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  isServedCadAsset,
  isStepSidecarPath,
  renderPackageAssetDir,
  renderPackageDir,
  scanCadDirectory,
  sortCatalogEntries,
  stepSidecarPath,
} from "./scanner.mjs";

function tmpRoot(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cad-scan-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function write(root, rel, content = "") {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}

test("the catalog is artifacts-only: scripts never list", (t) => {
  // Library-first: a model with no artifact does not appear until its script
  // has been run; artifact->source is descriptor provenance, not filenames.
  const root = tmpRoot(t);
  write(root, "widget.py", "from cadgen import step\n@step\ndef model():\n    return None\n");
  write(root, "outline.py", "from cadgen import dxf\n@dxf\ndef drawing():\n    return None\n");
  const files = scanCadDirectory(root).entries.map((e) => e.file);
  assert.deepEqual(files, []);
  // Once artifacts exist, THEY are the entries.
  write(root, "outline.dxf", "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n");
  const built = scanCadDirectory(root).entries.map((e) => e.file);
  assert.deepEqual(built, ["outline.dxf"]);
});

test("a generated model keys its package by the STEP file it outputs", (t) => {
  const root = tmpRoot(t);
  const py = write(root, "widget.step.py", "def gen_step(): ...\n");
  assert.equal(
    renderPackageDir(py),
    path.join(fs.realpathSync(root), "__cadgen__", "models", "widget.step"),
  );
});

test("the asset dir is unresolved while the lock dir is resolved", (t) => {
  // Two derivations of one directory, deliberately: the lock sentinel must be
  // realpath'd so two paths reaching one package exclude each other; an asset URL
  // must NOT be, or a macOS /var -> /private/var realpath escapes the scan root.
  const root = tmpRoot(t);
  const src = write(root, "gyroid.implicit.js", "// model\n");
  write(root, path.join("__cadgen__", "models", "gyroid.implicit.js", "implicit.json"), "{}");
  const assetDir = renderPackageAssetDir(src);
  assert.ok(assetDir.startsWith(path.resolve(root) + path.sep));
  assert.equal(renderPackageDir(src), fs.realpathSync(assetDir));
});

test("a written drawing lists as its own .dxf entry", (t) => {
  const root = tmpRoot(t);
  write(root, "outline.py", "from cadgen import dxf\n@dxf\ndef drawing(): ...\n");
  // The script never lists; the .dxf the run writes is the entry the client parses.
  write(root, "outline.dxf", "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n");
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "outline.dxf");
  assert.ok(entry.url.includes("outline.dxf?v="));
  assert.ok(entry.hash.length === 64);
  assert.equal(entry.relations, undefined);
});

test("an implicit model publishes its baked mesh as the glb relation", (t) => {
  const root = tmpRoot(t);
  write(root, "gyroid.implicit.js", "// model\n");
  write(
    root,
    path.join("__cadgen__", "models", "gyroid.implicit.js", "implicit.json"),
    JSON.stringify({ kind: "implicit-package", glb: "model.glb" }),
  );
  write(root, path.join("__cadgen__", "models", "gyroid.implicit.js", "model.glb"), "glbdata!");
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "gyroid.implicit.js");
  assert.equal(entry.kind, "implicit");
  assert.equal(entry.relations.glb.file, "__cadgen__/models/gyroid.implicit.js/model.glb");
  assert.equal(entry.relations.glb.bytes, 8);
});

test("an unbuilt implicit model publishes no mesh", (t) => {
  const root = tmpRoot(t);
  write(root, "gyroid.implicit.js", "// model\n");
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "gyroid.implicit.js");
  assert.equal(entry.relations, undefined);
});

test("a step sidecar is exposed as moduleUrl and recognized only beside its STEP", (t) => {
  const root = tmpRoot(t);
  const step = write(root, "gripper.step", "ISO-10303-21;\n");
  write(root, "gripper.step.js", "export default {};\n");
  assert.equal(stepSidecarPath(step), `${step}.js`);
  assert.ok(isStepSidecarPath(path.join(root, "gripper.step.js")));
  assert.ok(!isStepSidecarPath(path.join(root, "orphan.step.js")));
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "gripper.step");
  assert.ok(entry.moduleUrl.includes("gripper.step.js"));
});

test("the served-asset gate: hidden never, __cadgen__ always, stray js never", (t) => {
  const root = tmpRoot(t);
  const hidden = write(root, ".secret.step", "x");
  const packaged = write(root, path.join("__cadgen__", "models", "a.step", "assembly.json"), "{}");
  const stray = write(root, "random.js", "x");
  const sidecar = write(root, "part.step.js", "x");
  write(root, "part.step", "ISO-10303-21;\n");
  assert.equal(isServedCadAsset(hidden), false);
  assert.equal(isServedCadAsset(packaged), true);
  assert.equal(isServedCadAsset(stray), false);
  assert.equal(isServedCadAsset(sidecar), true);
});

test("catalog order is natural: numeric runs compare as integers", () => {
  const sorted = sortCatalogEntries([{ file: "v2.10.step" }, { file: "v2.9.step" }, { file: "v10.1.step" }]);
  assert.deepEqual(sorted.map((e) => e.file), ["v2.9.step", "v2.10.step", "v10.1.step"]);
});

test("srdf pairs with the same-directory urdf whose robot name matches", (t) => {
  const root = tmpRoot(t);
  write(root, "arm.urdf", '<?xml version="1.0"?>\n<robot name="arm"><link name="a"/></robot>\n');
  write(root, "arm.srdf", '<robot name="arm"><group name="g"/></robot>\n');
  write(root, "other.urdf", '<robot name="other"><link name="b"/></robot>\n');
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "arm.srdf");
  assert.equal(entry.relations.urdf.file, "arm.urdf");
});
