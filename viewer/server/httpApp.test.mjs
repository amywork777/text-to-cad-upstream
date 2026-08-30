// Live-listener tests of the /__cad contract: the two browser-borne gates
// (Host check, cross-site POST header), path containment, the Referer-relative
// asset route, download disposition, export/reveal env hooks, and the SPA.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createCadApp, hostIsAllowed } from "./httpApp.mjs";
import { renderPackageDir } from "./storePaths.mjs";

function write(root, rel, content = "") {
  const p = path.join(root, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}

async function startApp(t, { withDist = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cad-http-"));
  const previous = process.env.CADGEN_CACHE_DIR;
  process.env.CADGEN_CACHE_DIR = path.join(root, ".store");
  t.after(() => {
    if (previous === undefined) delete process.env.CADGEN_CACHE_DIR;
    else process.env.CADGEN_CACHE_DIR = previous;
  });
  let distDir = "";
  if (withDist) {
    distDir = fs.mkdtempSync(path.join(os.tmpdir(), "cad-dist-"));
    write(distDir, "index.html", "<html>viewer</html>");
    write(distDir, path.join("assets", "app.js"), "// app");
  }
  const app = createCadApp({ root, host: "127.0.0.1", port: 0, distDir });
  const server = http.createServer((req, res) => {
    app.handle(req, res).then((handled) => {
      if (!handled) {
        res.writeHead(404);
        res.end();
      }
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  t.after(() => {
    server.close();
    fs.rmSync(root, { recursive: true, force: true });
    if (distDir) {
      fs.rmSync(distDir, { recursive: true, force: true });
    }
  });
  const base = `http://127.0.0.1:${port}`;
  return { root, base, port };
}

test("host gate: a non-local Host header is refused, local ones pass", async (t) => {
  const { base, port } = await startApp(t);
  // fetch/undici refuses to override Host, so speak raw HTTP for the attack case.
  const evilStatus = await new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port, path: "/__cad/server", headers: { Host: "attacker.example" } },
      (res) => {
        res.resume();
        resolve(res.statusCode);
      },
    );
    req.on("error", reject);
    req.end();
  });
  assert.equal(evilStatus, 403);
  const ok = await fetch(`${base}/__cad/server`);
  assert.equal(ok.status, 200);
  // The NAME is compared, never the port; non-loopback binds skip the check.
  assert.equal(hostIsAllowed("localhost:9999", "127.0.0.1"), true);
  assert.equal(hostIsAllowed("[::1]:3245", "127.0.0.1"), true);
  assert.equal(hostIsAllowed("evil.example", "0.0.0.0"), true);
  assert.equal(hostIsAllowed("", "127.0.0.1"), true);
});

test("a POST without the x-cadgen-viewer header is refused and has no effect", async (t) => {
  const { base } = await startApp(t);
  const blocked = await fetch(`${base}/__cad/artifact?file=x.step`, { method: "POST" });
  assert.equal(blocked.status, 403);
  const body = await blocked.json();
  assert.match(body.error, /x-cadgen-viewer/);
  // The gate does not apply to reads.
  const read = await fetch(`${base}/__cad/catalog`);
  assert.equal(read.status, 200);
});

test("server info carries the fields the client reads", async (t) => {
  const { base, root } = await startApp(t);
  const info = await (await fetch(`${base}/__cad/server`)).json();
  assert.equal(info.app, "cad-viewer");
  assert.equal(info.backend, "local-fs");
  assert.equal(info.rootPath, fs.realpathSync.native ? path.resolve(root) : root);
  assert.equal(info.pid, process.pid);
  // Constant by design: the viewer is a static visualization tool and never
  // runs generators or exports.
  assert.equal(info.stepArtifactGenerationAvailable, false);
  assert.deepEqual(info.serverFeatures, ["path-directory"]);
});

test("asset containment: root serves, traversal and dot-paths never", async (t) => {
  const { base, root } = await startApp(t);
  const inside = write(root, "part.step", "ISO-10303-21;\n");
  const hidden = write(root, ".locks/part.step", "x");
  const outside = write(path.dirname(root), `${path.basename(root)}-sibling.step`, "x");
  t.after(() => fs.rmSync(outside, { force: true }));

  const ok = await fetch(`${base}/__cad/asset?file=${encodeURIComponent(inside)}`);
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("content-type"), "application/step");
  assert.equal(ok.headers.get("cache-control"), "no-store");

  for (const bad of [
    outside, // sibling name-prefix directory escape
    path.join(root, "..", path.basename(outside)), // traversal
    hidden, // dot-directory below the root
    `${root}/nope.step`, // missing
  ]) {
    const res = await fetch(`${base}/__cad/asset?file=${encodeURIComponent(bad)}`);
    assert.ok([403, 404].includes(res.status), `${bad} -> ${res.status}`);
  }
});

test("a malformed percent escape does not take the server down", async (t) => {
  const { base } = await startApp(t);
  const res = await fetch(`${base}/__cad/asset?file=%zz`);
  assert.ok([400, 404].includes(res.status));
  assert.equal((await fetch(`${base}/__cad/server`)).status, 200);
});

test("download sets the dual-form attachment disposition", async (t) => {
  const { base, root } = await startApp(t);
  const inside = write(root, "part.step", "ISO-10303-21;\n");
  const res = await fetch(`${base}/__cad/download?file=${encodeURIComponent(inside)}`);
  assert.equal(
    res.headers.get("content-disposition"),
    `attachment; filename="part.step"; filename*=UTF-8''part.step`,
  );
});

test("the store route serves package assets and stays contained", async (t) => {
  const { base, root } = await startApp(t);
  const stepPath = write(root, "a.step", "ISO-10303-21;\nstore-route\n");
  const packageDir = renderPackageDir(stepPath);
  fs.mkdirSync(path.join(packageDir, "components"), { recursive: true });
  fs.writeFileSync(path.join(packageDir, "assembly.json"), "{}");
  fs.writeFileSync(path.join(packageDir, "components", "c0.surf"), "SURFdata");
  const key = path.basename(packageDir);
  const ok = await fetch(`${base}/__cad/store?file=${encodeURIComponent(`${key}/components/c0.surf`)}`);
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), "SURFdata");
  // Traversal out of the packages tier and hidden names are refused.
  const escape = await fetch(`${base}/__cad/store?file=${encodeURIComponent("../../etc/hosts")}`);
  assert.equal(escape.status, 404);
  const hidden = await fetch(`${base}/__cad/store?file=${encodeURIComponent(".building-x/assembly.json")}`);
  assert.equal(hidden.status, 404);
});

test("reveal: disabled platform answers 501, a missing entry 404", async (t) => {
  const { base, root } = await startApp(t);
  process.env.VIEWER_DISABLE_NATIVE_REVEAL = "1";
  t.after(() => delete process.env.VIEWER_DISABLE_NATIVE_REVEAL);
  const inside = write(root, "part.step", "ISO-10303-21;\n");
  const headers = { "x-cadgen-viewer": "1" };
  const disabled = await fetch(`${base}/__cad/reveal?file=${encodeURIComponent(inside)}`, { method: "POST", headers });
  assert.equal(disabled.status, 501);
  const missing = await fetch(`${base}/__cad/reveal?file=${encodeURIComponent(path.join(root, "nope.step"))}`, {
    method: "POST",
    headers,
  });
  assert.equal(missing.status, 404);
});

test("the export route does not exist: the viewer is a static visualization tool", async (t) => {
  const { base, root } = await startApp(t);
  const inside = write(root, "part.step", "ISO-10303-21;\n");
  const headers = { "x-cadgen-viewer": "1" };
  const gone = await fetch(`${base}/__cad/export?file=${encodeURIComponent(inside)}&format=stl`, {
    method: "POST",
    headers,
  });
  assert.equal(gone.status, 405);
});

test("static dist serves the SPA with fallback, and 404s missing hashed assets", async (t) => {
  const { base } = await startApp(t, { withDist: true });
  assert.equal((await fetch(`${base}/`)).status, 200);
  assert.equal((await fetch(`${base}/Users/someone/models`)).status, 200); // SPA fallback
  assert.equal((await fetch(`${base}/assets/app.js`)).status, 200);
  assert.equal((await fetch(`${base}/assets/missing.js`)).status, 404);
});

test("artifact status for an unowned entry is ready without any python", async (t) => {
  const { base, root } = await startApp(t);
  const mesh = write(root, "benchy.stl", "solid benchy\nendsolid\n");
  const res = await fetch(`${base}/__cad/artifact?file=${encodeURIComponent(mesh)}`);
  const body = await res.json();
  assert.equal(body.state, "ready");
  assert.equal(typeof body.ref, "string");
  assert.ok(body.ref.includes("/__cad/asset?file="));
});
