// The static-viewer contract, end to end against a live server. The viewer
// runs no Python at all: built packages render (with honest staleness),
// generated entries without artifacts name the CLI, and a raw foreign STEP
// imports through the WASM kernel — the viewer's only build.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createCadApp } from "./httpApp.mjs";
import { STEP_PACKAGE_VERSION } from "./import/stepImport.mjs";

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

test("static viewer: packages render, edits badge stale, generators name the CLI", async (t) => {
  // The WASM import is covered by its own test below; disabled here so the
  // kernel-less contract stays testable on a checkout that has the kernel.
  process.env.VIEWER_WASM_IMPORT = "0";
  t.after(() => delete process.env.VIEWER_WASM_IMPORT);
  // realpath'd: macOS tmpdirs are symlinks (/var -> /private/var), and package
  // asset URLs are repo-relative — a root on one side of the symlink with
  // packages resolved on the other mangles them (the documented reason
  // renderPackageAssetDir exists).
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-standalone-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  const stepBytes = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n";
  const step = write(root, "widget.step", stepBytes);
  write(root, path.join("__cadgen__", "models", "widget.step", "components", "c0.surf"), SUN_GEAR_SURF);
  write(
    root,
    path.join("__cadgen__", "models", "widget.step", "assembly.json"),
    JSON.stringify({
      kind: "assembly-package",
      packageSchemaVersion: STEP_PACKAGE_VERSION,
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

  // The server never claims a generation capability.
  const info = await (await fetch(`${base}/__cad/server`)).json();
  assert.equal(info.stepArtifactGenerationAvailable, false);

  // Built package: renders, not stale.
  let status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "ready");
  assert.equal(status.stale, undefined);

  // Edit the STEP: still renders, but honestly badged stale (nothing here can
  // re-import it with the kernel disabled).
  fs.appendFileSync(step, "\n");
  status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "ready");
  assert.equal(status.stale, true);
  assert.match(String(status.staleReason || ""), /changed after/);

  // Never-imported foreign STEP: a specific explanation, not a generic hint.
  status = await (
    await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(path.join(root, "never-imported.step"))}`)
  ).json();
  assert.equal(status.state, "error");
  assert.match(String(status.error || ""), /has not been imported yet/);

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

  // A build POST on an artifact the viewer cannot build refuses with the
  // run-the-script hint (the WASM kernel is disabled above).
  const refused = await (
    await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(path.join(root, "never-imported.step"))}`, {
      method: "POST",
      headers: { "x-cadgen-viewer": "1" },
    })
  ).json();
  assert.equal(refused.ok, false);
  assert.match(String(refused.error || ""), /python <source>/);

  // The render data itself serves: catalog lists the entry and its component
  // surf streams — everything the viewport needs, no Python anywhere.
  const catalog = await (await fetch(`${base}/__cad/catalog`)).json();
  const entry = catalog.entries.find((e) => e.file.endsWith("widget.step"));
  assert.ok(entry, "catalog lists the packaged step");
  const surfUrl = `${base}/__cad/asset?file=${encodeURIComponent(
    path.join(root, "__cadgen__", "models", "widget.step", "components", "c0.surf"),
  )}`;
  const surf = await fetch(surfUrl);
  assert.equal(surf.status, 200);
  const payload = Buffer.from(await surf.arrayBuffer());
  assert.equal(payload.subarray(0, 4).toString("utf8"), "SURF");
});

// The full Python-less import flow against a REAL vendor-style STEP: status
// offers the build, the build runs the WASM import (parse -> XCAF walk ->
// extractor twin -> package), and the resulting package renders. Slow by
// nature (~5s: one-time kernel init + import); it IS the standalone e2e.
const IMPORT_FIXTURE = path.resolve(VIEWER_ROOT, "..", "models", "step", "parts", "cam_follower_roller.step");
const wasmKernelPresent = fs.existsSync(
  path.join(VIEWER_ROOT, "node_modules", "opencascade.js", "dist", "opencascade.full.wasm"),
);

test(
  "static viewer: a raw STEP imports through the WASM kernel and renders",
  { skip: !wasmKernelPresent || !fs.existsSync(IMPORT_FIXTURE) },
  async (t) => {
    const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-standalone-import-")));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const step = write(root, "roller.step", fs.readFileSync(IMPORT_FIXTURE));

    const base = await startApp(t, { root });

    // Unimported + importable: the server offers a build instead of an excuse.
    let status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
    assert.equal(status.state, "needs-build");
    assert.equal(status.wasmImport, true);

    // POST the build: the WASM import runs in a child process and the entry
    // settles ready with a real package on disk.
    const build = await (
      await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`, {
        method: "POST",
        headers: { "x-cadgen-viewer": "1" },
      })
    ).json();
    assert.equal(build.ok, true, `build failed: ${build.error || ""}`);
    assert.equal(build.state, "ready");
    assert.equal(build.wasmImport, true);
    const descriptorPath = path.join(root, "__cadgen__", "models", "roller.step", "assembly.json");
    const descriptor = JSON.parse(fs.readFileSync(descriptorPath, "utf8"));
    assert.equal(descriptor.kind, "assembly-package");
    assert.equal(descriptor.sourceKind, "step");
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
    const surf = await fetch(`${base}/__cad/asset?file=${encodeURIComponent(
      path.join(root, "__cadgen__", "models", "roller.step", surfRel),
    )}`);
    assert.equal(surf.status, 200);
    assert.equal(Buffer.from(await surf.arrayBuffer()).subarray(0, 4).toString("utf8"), "SURF");
  },
);
