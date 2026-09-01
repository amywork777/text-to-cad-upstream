import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  isServedCadAsset,
  renderPackageDir,
  pathIsInside,
  scanCadDirectory,
  sortCatalogEntries,
} from "./scanner.mjs";
import { packageDirForHash, storePackagesDir } from "./storePaths.mjs";

function tmpRoot(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cad-scan-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  // Store-primary: isolate the user-level store per test.
  const previous = process.env.CADGEN_CACHE_DIR;
  process.env.CADGEN_CACHE_DIR = path.join(dir, ".store");
  t.after(() => {
    if (previous === undefined) delete process.env.CADGEN_CACHE_DIR;
    else process.env.CADGEN_CACHE_DIR = previous;
  });
  return dir;
}

// A store package for exactly the bytes at stepPath.
function writeStorePackage(stepPath, descriptor) {
  const dir = renderPackageDir(stepPath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "assembly.json"), JSON.stringify(descriptor));
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

test("a package resolves by the document's CONTENT hash in the store", (t) => {
  const root = tmpRoot(t);
  const src = write(root, "gyroid.step", "ISO-10303-21;\ncontent A\n");
  const dir = renderPackageDir(src);
  assert.ok(pathIsInside(dir, storePackagesDir()));
  // Same bytes elsewhere -> the SAME package; different bytes -> a different one.
  const twin = write(root, "copy.step", "ISO-10303-21;\ncontent A\n");
  assert.equal(renderPackageDir(twin), dir);
  const other = write(root, "other.step", "ISO-10303-21;\ncontent B\n");
  assert.notEqual(renderPackageDir(other), dir);
  // A missing file resolves to a deterministic never-created path.
  const unbuilt = renderPackageDir(path.join(root, "nope.step"));
  assert.ok(pathIsInside(unbuilt, storePackagesDir()));
  assert.ok(path.basename(unbuilt).startsWith("unbuilt-"));
  assert.equal(fs.existsSync(unbuilt), false);
  assert.ok(typeof packageDirForHash === "function");
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

test("a .implicit.js file is not a catalog entry at all", (t) => {
  const root = tmpRoot(t);
  write(root, "gyroid.implicit.js", "// model\n");
  write(root, "outline.dxf", "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n");
  const entries = scanCadDirectory(root).entries;
  assert.equal(entries.find((e) => e.file === "gyroid.implicit.js"), undefined);
  // The scan still works around it rather than stopping at it.
  assert.ok(entries.find((e) => e.file === "outline.dxf"));
});

test("a sidecar kinematics section is exposed as poseUrl; sidecars only teach", (t) => {
  const root = tmpRoot(t);
  const stepPath = write(root, "gripper.step", "ISO-10303-21;\ngripper\n");
  // The store descriptor is STEP-pure; kinematics (and all source-derived
  // state) rides the MODEL-SIDE sidecar. The catalog asks only whether that
  // sidecar EXISTS, so it can hand the client its URL -- never what produced
  // the document.
  writeStorePackage(stepPath, { kind: "assembly-package" });
  write(root, "gripper.step.json", JSON.stringify({
    schemaVersion: 4,
    kinematics: { mates: [{ name: "jaw", kind: "slider", parent: "#body", child: "#jaw",
      axis: { origin: [0, 0, 0], dir: [1, 0, 0] }, limits: { value: [0, 40] } }] },
    animation: { clips: "export const clips = {};\n" }
  }));
  const entry = scanCadDirectory(root).entries.find((e) => e.file === "gripper.step");
  assert.equal(entry.sourceKind, undefined, "the catalog publishes no provenance kind");
  assert.equal(entry.source, undefined, "the catalog never names a generator script");
  assert.ok(entry.poseUrl.includes(".step.json"));
  assert.ok(entry.sourceUrl.includes(".step.json"));
  assert.equal(entry.poseHatchUrl, undefined);

  // A re-emitted document (`cadgen step build`) has a sidecar with no Python
  // behind it, and its declarations reach the client exactly the same way. The
  // catalog used to withhold sourceUrl from these, so a re-emitted assembly's
  // mates never loaded — the classification was not just noise, it was wrong.
  const reemittedPath = write(root, "hinge.step", "ISO-10303-21;\nhinge\n");
  writeStorePackage(reemittedPath, { kind: "assembly-package" });
  write(root, "hinge.step.json", JSON.stringify({
    schemaVersion: 4,
    sourceKind: "step",
    kinematics: { mates: [{ name: "pin", kind: "revolute", parent: "#a", child: "#b",
      axis: { origin: [0, 0, 0], dir: [0, 0, 1] }, limits: { value: [0, 90] } }] }
  }));
  const reemitted = scanCadDirectory(root).entries.find((e) => e.file === "hinge.step");
  assert.ok(reemitted.sourceUrl.includes(".step.json"));
  assert.ok(reemitted.poseUrl.includes(".step.json"));
  assert.equal(reemitted.sourceKind, undefined);

  // A loose .params.js beside a model is inert bytes: never loaded, never
  // even remarked on (the retired-sidecar teaching path is gone).
  write(root, "legacy.step", "ISO-10303-21;\n");
  write(root, "legacy.params.js", "export default {};\n");
  const legacy = scanCadDirectory(root).entries.find((e) => e.file === "legacy.step");
  assert.equal(legacy.legacyParamsSidecar, undefined);
  assert.equal(legacy.poseUrl, undefined);
  assert.equal(legacy.moduleUrl, undefined);
});

test("the served-asset gate: hidden never, source sidecars yes, stray js never", (t) => {
  const root = tmpRoot(t);
  const hidden = write(root, ".secret.step", "x");
  const sourceSidecar = write(root, "part.step.json", "{}");
  const stray = write(root, "random.js", "x");
  const sidecar = write(root, "part.step.js", "x");
  write(root, "part.step", "ISO-10303-21;\n");
  assert.equal(isServedCadAsset(hidden), false);
  assert.equal(isServedCadAsset(sourceSidecar), true);
  assert.equal(isServedCadAsset(stray), false);
  // Loose .js beside a model is never served (the .params.js mechanism is
  // retired); the pose escape hatch rides INLINE in the source sidecar.
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
