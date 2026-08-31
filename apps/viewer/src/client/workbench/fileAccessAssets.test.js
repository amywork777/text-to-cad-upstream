import assert from "node:assert/strict";
import test from "node:test";

import {
  copyTargetsForFileAccessAsset,
  downloadUrlForFileAsset,
  fileAccessAssetsForEntry,
  openUrlForFileAsset
} from "./fileAccessAssets.js";

const viewerServerInfo = {
  rootPath: "/project/text-to-cad/models",
};

test("file access assets always include output filename", () => {
  const assets = fileAccessAssetsForEntry({
    file: "assemblies/robot-arm/robot-arm.step",
    sourceKind: "step",
  });

  assert.deepEqual(assets.output, {
    asset: "output",
    fileRef: "assemblies/robot-arm/robot-arm.step",
    filename: "robot-arm.step",
    label: "robot-arm.step",
    rootRelativePath: "assemblies/robot-arm/robot-arm.step",
  });
});

test("file access assets include generated artifact URLs when present", () => {
  const assets = fileAccessAssetsForEntry({
    file: "assemblies/robot-arm/robot-arm.step",
    url: "/models/assemblies/robot-arm/.robot-arm.step.glb?v=123",
  }, {
    viewerServerInfo,
  });

  assert.deepEqual(assets.artifact, {
    asset: "artifact",
    fileRef: "assemblies/robot-arm/robot-arm.step",
    filename: ".robot-arm.step.glb",
    label: ".robot-arm.step.glb",
    rootRelativePath: "assemblies/robot-arm/.robot-arm.step.glb",
  });
});

test("a Python-backed entry offers no source asset and keeps its on-disk output name", () => {
  // There is no same-stem `.py` beside a generated STEP -- model scripts live in `src/` --
  // and the viewer never presents an artifact under its generator's name anyway.
  const assets = fileAccessAssetsForEntry({
    file: "assemblies/robot-arm/robot-arm.step",
    sourceKind: "python",
  });

  assert.equal(assets.source, undefined);
  assert.equal(assets.output.filename, "robot-arm.step");
  assert.equal(assets.output.label, "robot-arm.step");
});

test("recorded generator provenance never becomes a file access asset", () => {
  // The sidecar still records where the artifact came from; that is machine-side
  // provenance for freshness gates, not a file the UI offers or names.
  const assets = fileAccessAssetsForEntry({
    file: "generated/robot.step",
    sourceKind: "python",
    source: {
      file: "generated/src/robot_module.py",
      sourcePath: "generated/src/robot_module.py",
    },
  });

  assert.equal(assets.source, undefined);
  assert.deepEqual(Object.keys(assets).sort(), ["artifact", "output"]);
  assert.equal(assets.output.filename, "robot.step");
});

test("a Python-backed URDF still names the URDF it is", () => {
  const assets = fileAccessAssetsForEntry({
    file: "robots/tom/tom.urdf",
    kind: "urdf",
    sourceKind: "python",
    source: {
      file: "robots/tom/src/tom.py",
      sourcePath: "robots/tom/src/tom.py",
    },
  });

  assert.equal(assets.source, undefined);
  assert.equal(assets.output.filename, "tom.urdf");
  assert.equal(assets.output.rootRelativePath, "robots/tom/tom.urdf");
});

test("file access download URLs target the requested asset", () => {
  assert.equal(
    downloadUrlForFileAsset("assemblies/robot arm.step", "artifact"),
    "/__cad/download?file=assemblies%2Frobot%20arm.step&asset=artifact"
  );
  assert.equal(
    downloadUrlForFileAsset("assemblies/robot arm.step", "output", "https://cad.example.test/viewer"),
    "https://cad.example.test/__cad/download?file=assemblies%2Frobot%20arm.step&asset=output"
  );
});

test("file access open URLs target the local reveal endpoint", () => {
  assert.equal(
    openUrlForFileAsset("assemblies/robot arm.step", "artifact"),
    "/__cad/reveal?file=assemblies%2Frobot%20arm.step&asset=artifact"
  );
  assert.equal(
    openUrlForFileAsset("assemblies/robot arm.step", "output", "http://127.0.0.1:4179/viewer"),
    "http://127.0.0.1:4179/__cad/reveal?file=assemblies%2Frobot%20arm.step&asset=output"
  );
});

test("file access copy targets include absolute and root-relative local paths", () => {
  const targets = copyTargetsForFileAccessAsset({
    rootRelativePath: "assemblies/robot-arm/robot-arm.step",
  }, {
    rootPath: "/project/text-to-cad/models",
  });

  assert.deepEqual(targets, {
    path: "/project/text-to-cad/models/assemblies/robot-arm/robot-arm.step",
    filename: "robot-arm.step",
    relativePath: "assemblies/robot-arm/robot-arm.step",
  });
});

test("copy targets resolve the asset's root-relative path against the served root", () => {
  // This used to resolve against a SECOND root (the repo root, one level above the
  // served directory), which is how a path outside the served root still got an
  // absolute form. There is one root now, so a relative path is relative to it.
  const targets = copyTargetsForFileAccessAsset({
    rootRelativePath: "cad/drawings/gasket_plate.dxf",
  }, viewerServerInfo);

  assert.deepEqual(targets, {
    path: "/project/text-to-cad/models/cad/drawings/gasket_plate.dxf",
    filename: "gasket_plate.dxf",
    relativePath: "cad/drawings/gasket_plate.dxf",
  });
});

test("copy targets take the filename the asset already carries", () => {
  // An artifact asset's display filename can differ from the basename of the path it
  // resolves to (a package artifact resolves to its own file), so the asset wins.
  const targets = copyTargetsForFileAccessAsset({
    filename: ".robot-arm.step.glb",
    rootRelativePath: "assemblies/robot-arm/.robot-arm.step.glb",
  }, viewerServerInfo);

  assert.equal(targets.filename, ".robot-arm.step.glb");
});

test("copy targets fall back to the path basename when the asset has no filename", () => {
  const targets = copyTargetsForFileAccessAsset({
    rootRelativePath: "cad/assemblies/robot-arm.step",
  }, viewerServerInfo);

  assert.equal(targets.filename, "robot-arm.step");
});
