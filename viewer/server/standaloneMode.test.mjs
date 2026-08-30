// The static-viewer contract, end to end against a live server. The viewer's
// render path runs no Python: built packages render (with honest staleness)
// and generated entries without artifacts name the CLI. Importing a raw
// foreign STEP — the viewer's only build — spawns `cadgen step build`; without a
// runnable cadgen it degrades to one actionable message and viewing is
// unaffected.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createCadApp } from "./httpApp.mjs";
import { _setCadgenProbeForTests } from "./cadgenResolve.mjs";
import { renderPackageDir } from "./storePaths.mjs";

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_ROOT = path.resolve(SERVER_DIR, "..");

function write(root, rel, content) {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}

function sha256(buffer) {
  return execFileSync("shasum", ["-a", "256"], { input: buffer }).toString().split(" ")[0];
}

// A REAL surf component: the cadjs sun-gear fixture (written by the actual
// Python extractor), so this test exercises the same asset path the viewport
// loads rather than a hand-rolled container.
const SUN_GEAR_SURF = fs.readFileSync(
  path.join(VIEWER_ROOT, "packages/cadjs/src/lib/surf/fixtures/sun_gear.surf"),
);

async function startApp(t, { root }) {
  const app = createCadApp({ root, host: "127.0.0.1", port: 0 });
  const server = http.createServer((req, res) => {
    app.handle(req, res).then((handled) => {
      if (!handled) {
        res.writeHead(404);
        res.end();
      }
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  return `http://127.0.0.1:${server.address().port}`;
}

test("static viewer: packages render, edits badge stale, no cadgen degrades cleanly", async (t) => {
  // The real import is covered by the e2e below; here the resolver is
  // INJECTED as absent so the no-cadgen contract stays testable on a checkout
  // where cadgen is installed.
  _setCadgenProbeForTests(() => null);
  t.after(() => _setCadgenProbeForTests(null));
  // realpath'd: macOS tmpdirs are symlinks (/var -> /private/var), and package
  // asset URLs are repo-relative — a root on one side of the symlink with
  // packages resolved on the other mangles them (the documented reason
  // renderPackageAssetDir exists).
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-standalone-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const previousStore = process.env.CADGEN_CACHE_DIR;
  process.env.CADGEN_CACHE_DIR = path.join(root, ".store");
  t.after(() => {
    if (previousStore === undefined) delete process.env.CADGEN_CACHE_DIR;
    else process.env.CADGEN_CACHE_DIR = previousStore;
  });

  const stepBytes = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n";
  const step = write(root, "widget.step", stepBytes);
  const packageDir = renderPackageDir(step);
  fs.mkdirSync(path.join(packageDir, "components"), { recursive: true });
  fs.writeFileSync(path.join(packageDir, "components", "c0.surf"), SUN_GEAR_SURF);
  fs.writeFileSync(
    path.join(packageDir, "assembly.json"),
    JSON.stringify({
      kind: "assembly-package",
      stepHash: sha256(Buffer.from(stepBytes)),
      components: { c0: { surf: "components/c0.surf" } },
      occurrences: [
        { id: "o1", component: "c0", transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] },
        { id: "o2", component: "c0", transform: [1, 0, 0, 25, 0, 1, 0, 0, 0, 0, 1, 0] },
      ],
    }),
  );
  write(root, "never-imported.step", "ISO-10303-21;\nEND-ISO-10303-21;\n");
  write(root, "unbuilt.py", "from cadgen import step\n@step\ndef model():\n    return None\n");

  const base = await startApp(t, { root });

  // The server never claims a generation capability, and with no runnable
  // cadgen it does not claim the import capability either.
  const info = await (await fetch(`${base}/__cad/server`)).json();
  assert.equal(info.stepArtifactGenerationAvailable, false);
  assert.equal(info.stepImportAvailable, false);

  // Built package: renders, not stale.
  let status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "ready");
  assert.equal(status.stale, undefined);

  // Edit the STEP: the content key changes, so the old package is simply
  // unreachable — with no cadgen the answer is the actionable import error.
  fs.appendFileSync(step, "\n");
  status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "error");
  assert.match(String(status.error || ""), /has not been imported yet/);
  // Restore the original bytes: the package resolves again, nothing rebuilt.
  fs.writeFileSync(step, stepBytes);
  status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "ready");

  // Never-imported foreign STEP with no cadgen: one specific, actionable
  // explanation that names the fix, not a generic hint.
  status = await (
    await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(path.join(root, "never-imported.step"))}`)
  ).json();
  assert.equal(status.state, "error");
  assert.match(String(status.error || ""), /has not been imported yet/);
  assert.match(String(status.error || ""), /requires cadgen/);
  assert.match(String(status.error || ""), /CADGEN_PYTHON/);
  assert.match(String(status.error || ""), /Viewing existing models does not need cadgen/);

  // A model script is not the viewer's business at all (artifacts-only
  // catalog): status and build both answer as a no-op — nothing to manage.
  const generatorRef = path.join(root, "unbuilt.py");
  status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(generatorRef)}`)).json();
  assert.equal(status.state, "ready");
  const scriptPost = await (
    await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(generatorRef)}`, {
      method: "POST",
      headers: { "x-cadgen-viewer": "1" },
    })
  ).json();
  assert.equal(scriptPost.ok, true);

  // A build POST on a raw STEP with no cadgen refuses with the same
  // actionable message (the probe is injected above).
  const refused = await (
    await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(path.join(root, "never-imported.step"))}`, {
      method: "POST",
      headers: { "x-cadgen-viewer": "1" },
    })
  ).json();
  assert.equal(refused.ok, false);
  assert.match(String(refused.error || ""), /requires cadgen/);

  // The render data itself serves: catalog lists the entry and its component
  // surf streams — everything the viewport needs, no Python anywhere.
  const catalog = await (await fetch(`${base}/__cad/catalog`)).json();
  const entry = catalog.entries.find((e) => e.file.endsWith("widget.step"));
  assert.ok(entry, "catalog lists the packaged step");
  const surfUrl = `${base}/__cad/store?file=${encodeURIComponent(
    `${path.basename(packageDir)}/components/c0.surf`,
  )}`;
  const surf = await fetch(surfUrl);
  assert.equal(surf.status, 200);
  const payload = Buffer.from(await surf.arrayBuffer());
  assert.equal(payload.subarray(0, 4).toString("utf8"), "SURF");
});

// The full import flow against a REAL vendor-style STEP: status offers the
// build, the build spawns `cadgen step build` (cold interpreter — the e2e must
// not depend on a warm daemon), and the resulting package renders. Skips
// cleanly where no project cadgen exists (the mirrored cad-viewer repo runs
// this suite standalone).
const IMPORT_FIXTURE = path.resolve(VIEWER_ROOT, "..", "models", "step", "parts", "cam_follower_roller.step");
const REPO_PYTHON = process.platform === "win32"
  ? path.resolve(VIEWER_ROOT, "..", ".venv", "Scripts", "python.exe")
  : path.resolve(VIEWER_ROOT, "..", ".venv", "bin", "python");
const cadgenPresent = fs.existsSync(REPO_PYTHON);

test(
  "static viewer: a raw STEP imports through cadgen and renders",
  { skip: !cadgenPresent || !fs.existsSync(IMPORT_FIXTURE) },
  async (t) => {
    process.env.CADGEN_PYTHON = REPO_PYTHON;
    process.env.CADGEN_DAEMON = "0"; // hermetic: no daemon spawned by a test
    t.after(() => {
      delete process.env.CADGEN_PYTHON;
      delete process.env.CADGEN_DAEMON;
    });
    const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-standalone-import-")));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const previousStore = process.env.CADGEN_CACHE_DIR;
    process.env.CADGEN_CACHE_DIR = path.join(root, ".store");
    t.after(() => {
      if (previousStore === undefined) delete process.env.CADGEN_CACHE_DIR;
      else process.env.CADGEN_CACHE_DIR = previousStore;
    });
    // A bare STEP is a bare STEP: files carry no cadgen metadata, so any
    // .step without a package is simply importable, whatever produced it.
    const step = write(root, "roller.step", fs.readFileSync(IMPORT_FIXTURE));

    const base = await startApp(t, { root });

    // With a resolvable cadgen the server claims the import capability.
    const info = await (await fetch(`${base}/__cad/server`)).json();
    assert.equal(info.stepImportAvailable, true);

    // Unimported + importable: the server offers a build instead of an excuse.
    let status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
    assert.equal(status.state, "needs-build");
    assert.equal(status.stepImport, true);

    // POST the build: `cadgen step build` runs in a child process and the entry
    // settles ready with a real package on disk.
    const build = await (
      await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`, {
        method: "POST",
        headers: { "x-cadgen-viewer": "1" },
      })
    ).json();
    assert.equal(build.ok, true, `build failed: ${build.error || ""}`);
    assert.equal(build.state, "ready");
    assert.equal(build.stepImport, true);
    const descriptorPath = path.join(renderPackageDir(step), "assembly.json");
    const descriptor = JSON.parse(fs.readFileSync(descriptorPath, "utf8"));
    assert.equal(descriptor.kind, "assembly-package");
    // Imports write NO source sidecar — its absence IS the "imported" marker;
    // the descriptor itself carries no provenance kind at all.
    assert.equal(descriptor.sourceKind, undefined);
    assert.equal(
      fs.existsSync(`${step}.cadgen.json`),
      false,
      "an imported package must not carry a source sidecar",
    );
    assert.ok(Object.keys(descriptor.components).length >= 1);
    assert.equal(
      descriptor.stepHash,
      sha256(fs.readFileSync(step)),
      "descriptor records the imported file's hash",
    );

    // The imported package now reports plain ready, and its render data serves.
    status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
    assert.equal(status.state, "ready");
    assert.equal(status.stale, undefined);
    const surfRel = String(Object.values(descriptor.components)[0].surf);
    const surf = await fetch(`${base}/__cad/store?file=${encodeURIComponent(
      `${path.basename(renderPackageDir(step))}/${surfRel}`,
    )}`);
    assert.equal(surf.status, 200);
    assert.equal(Buffer.from(await surf.arrayBuffer()).subarray(0, 4).toString("utf8"), "SURF");
  },
);
