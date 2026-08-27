// The no-cadgen (standalone) contract, end to end against a live server whose
// Python is deliberately broken: built packages render (with honest staleness),
// unimported STEPs explain themselves, and mesh exports serialize in JS from
// the same surf geometry the viewport draws.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createCadApp } from "./httpApp.mjs";

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_ROOT = path.resolve(SERVER_DIR, "..");

function write(root, rel, content) {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  if (typeof content === "string") {
    fs.writeFileSync(p, content);
  } else {
    fs.writeFileSync(p, content);
  }
  return p;
}

function sha256(buffer) {
  return execFileSync("shasum", ["-a", "256"], { input: buffer }).toString().split(" ")[0];
}

// A REAL surf component: the cadjs sun-gear fixture (written by the actual
// Python extractor), so this test exercises the same parse+tessellate path the
// viewport uses rather than a hand-rolled container.
const SUN_GEAR_SURF = fs.readFileSync(
  path.join(VIEWER_ROOT, "packages/cadjs/src/lib/surf/fixtures/sun_gear.surf"),
);

async function startBrokenPythonApp(t, { root }) {
  process.env.VIEWER_CAD_PYTHON = "/usr/bin/false";
  t.after(() => delete process.env.VIEWER_CAD_PYTHON);
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

test("standalone mode: built packages render, edits show stale, unimported explains", async (t) => {
  // The WASM import is covered by its own test below; here it is disabled so
  // the kernel-less degraded contract (honest staleness, install hints) stays
  // testable on a checkout that has the kernel installed.
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
      stepHash: sha256(Buffer.from(stepBytes)),
      components: { c0: { surf: "components/c0.surf" } },
      occurrences: [
        { id: "o1", component: "c0", transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] },
        { id: "o2", component: "c0", transform: [1, 0, 0, 25, 0, 1, 0, 0, 0, 0, 1, 0] },
      ],
    }),
  );
  write(root, "never-imported.step", "ISO-10303-21;\nEND-ISO-10303-21;\n");

  const base = await startBrokenPythonApp(t, { root });

  // Built package: renders, degraded, not stale.
  let status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
  assert.equal(status.state, "ready");
  assert.equal(status.degraded, true);
  assert.equal(status.stale, undefined);

  // Edit the STEP: still renders, but honestly badged stale.
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

  // Client-side mesh export: serialize an STL in pure JS from the package's
  // surf geometry, through the same module the browser uses.
  const { buildEntryMeshExport } = await import(
    path.join(VIEWER_ROOT, "src/client/workbench/clientMeshExport.js")
  );
  const catalog = await (await fetch(`${base}/__cad/catalog`)).json();
  const entry = catalog.entries.find((e) => e.file.endsWith("widget.step"));
  assert.ok(entry, "catalog lists the packaged step");
  // The catalog's URLs are origin-relative (the browser resolves them against
  // the page); give node's fetch the same base.
  const rawFetch = globalThis.fetch;
  globalThis.fetch = (input, init) =>
    rawFetch(typeof input === "string" && input.startsWith("/") ? `${base}${input}` : input, init);
  t.after(() => {
    globalThis.fetch = rawFetch;
  });
  const result = await buildEntryMeshExport(entry, "stl");
  assert.equal(result.filename, "widget.stl");
  // Two sun-gear occurrences -> thousands of triangles; binary STL header + count.
  assert.ok(result.triangleCount >= 1000, `triangles: ${result.triangleCount}`);
  const body = Buffer.from(result.body);
  assert.equal(body.readUInt32LE(80), result.triangleCount);
});

// The full Python-less import flow against a REAL vendor-style STEP: status
// offers the build, the build runs the WASM import (parse -> XCAF walk ->
// extractor twin -> package), and the resulting package renders and exports
// through the same client modules the browser uses. Slow by nature (~15s:
// one-time kernel init + import); it IS the standalone e2e.
const IMPORT_FIXTURE = path.resolve(VIEWER_ROOT, "..", "models", "step", "parts", "cam_follower_roller.step");
const wasmKernelPresent = fs.existsSync(
  path.join(VIEWER_ROOT, "node_modules", "opencascade.js", "dist", "opencascade.full.wasm"),
);

test(
  "standalone mode: a raw STEP imports through the WASM kernel and renders",
  { skip: !wasmKernelPresent || !fs.existsSync(IMPORT_FIXTURE) },
  async (t) => {
    const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "cad-standalone-import-")));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const step = write(root, "roller.step", fs.readFileSync(IMPORT_FIXTURE));

    const base = await startBrokenPythonApp(t, { root });

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

    // The imported package now reports plain ready...
    status = await (await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(step)}`)).json();
    assert.equal(status.state, "ready");
    assert.equal(status.stale, undefined);

    // ...and renders/export-serializes through the standard client path.
    const { buildEntryMeshExport } = await import(
      path.join(VIEWER_ROOT, "src/client/workbench/clientMeshExport.js")
    );
    const catalog = await (await fetch(`${base}/__cad/catalog`)).json();
    const entry = catalog.entries.find((e) => e.file.endsWith("roller.step"));
    assert.ok(entry, "catalog lists the imported step");
    const rawFetch = globalThis.fetch;
    globalThis.fetch = (input, init) =>
      rawFetch(typeof input === "string" && input.startsWith("/") ? `${base}${input}` : input, init);
    t.after(() => {
      globalThis.fetch = rawFetch;
    });
    const exported = await buildEntryMeshExport(entry, "stl");
    assert.ok(exported.triangleCount >= 100, `triangles: ${exported.triangleCount}`);
    assert.equal(Buffer.from(exported.body).readUInt32LE(80), exported.triangleCount);
  },
);
