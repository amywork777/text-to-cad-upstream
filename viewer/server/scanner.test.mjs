import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  isServedCadAsset,
  legacyParamsSidecarPath,
  renderPackageAssetDir,
  renderPackageDir,
  pathIsInside,
  scanCadDirectory,
  sortCatalogEntries,
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

test("a descriptor pose block is exposed as poseUrl (+ hatch); sidecars only teach", (t) => {
  const root = tmpRoot(t);
  write(root, "gripper.step", "ISO-10303-21;\n");
  write(root, path.join("__cadgen__", "models", "gripper.step", "assembly.json"), JSON.stringify({
    kind: "assembly-package",
    sourceKind: "python",
    pose: { schemaVersion: 1, params: { drive: { type: "number" } }, module: "components/ab12.pose.js" }
  }));
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "gripper.step");
  assert.ok(entry.poseUrl.includes("assembly.json"));
  assert.ok(entry.poseHatchUrl.includes("ab12.pose.js"));
  assert.equal(entry.legacyParamsSidecar, undefined);

  // The retired sidecar convention is detected only to TEACH, never loaded.
  write(root, "legacy.step", "ISO-10303-21;\n");
  write(root, "legacy.params.js", "export default {};\n");
  assert.equal(legacyParamsSidecarPath(path.join(root, "legacy.step")), path.join(root, "legacy.params.js"));
  const legacy = scanCadDirectory(root).entries.find((e) => e.file === "legacy.step");
  assert.equal(legacy.legacyParamsSidecar, true);
  assert.equal(legacy.poseUrl, undefined);
  assert.equal(legacy.moduleUrl, undefined);
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
  // Loose .js beside a model is never served any more (sidecars are retired);
  // pose escape hatches live INSIDE the package and ride the __cadgen__ rule.
  assert.equal(isServedCadAsset(sidecar), false);
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

// --- develop ports: symlink-following walk + alias-equality containment ---

test("the scan follows directory symlinks on purpose (ports b0f59af3)", (t) => {
  const root = tmpRoot(t);
  const outside = tmpRoot(t);
  write(outside, "shared/part.step", "ISO-10303-21;");
  fs.symlinkSync(path.join(outside, "shared"), path.join(root, "library"), "dir");
  const files = scanCadDirectory(root).entries.map((e) => e.file);
  assert.ok(
    files.some((f) => f.endsWith(path.join("library", "part.step"))),
    `symlinked model folder must catalog: ${JSON.stringify(files)}`,
  );
});

test("a symlink loop terminates instead of crashing the scan (ports 9bc6bd44)", (t) => {
  const root = tmpRoot(t);
  write(root, "model.step", "ISO-10303-21;");
  fs.symlinkSync(root, path.join(root, "loop"), "dir");
  const files = scanCadDirectory(root).entries.map((e) => e.file);
  assert.equal(files.filter((f) => f.endsWith("model.step")).length, 1);
});

test("broken symlinks are skipped, not fatal", (t) => {
  const root = tmpRoot(t);
  write(root, "model.step", "ISO-10303-21;");
  fs.symlinkSync(path.join(root, "does-not-exist"), path.join(root, "dangling"));
  assert.equal(scanCadDirectory(root).entries.length >= 1, true);
});

test("pathIsInside treats realpath as alias equality, never refusal", (t) => {
  const root = tmpRoot(t);
  write(root, "sub/part.step", "ISO-10303-21;");
  const alias = path.join(tmpRoot(t), "alias-root");
  fs.symlinkSync(root, alias, "dir");
  // Lexical containment under the symlinked root alias.
  assert.equal(pathIsInside(path.join(alias, "sub/part.step"), alias), true);
  // Alias equality: the RESOLVED file against the symlinked root, and vice versa.
  assert.equal(pathIsInside(path.join(root, "sub/part.step"), alias), true);
  assert.equal(pathIsInside(path.join(alias, "sub/part.step"), root), true);
  // Still refuses genuinely-outside paths both ways.
  assert.equal(pathIsInside(path.join(path.dirname(root), "elsewhere.step"), alias), false);
});
