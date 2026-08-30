// The viewer server's /__tess_cache/ routes: same store, same name rules, and
// the same TESB batch framing as the snapshot host. Framing is pinned against
// the AUTHORITATIVE codec in the vendored cadjs (tessellationCache.js is the
// format's home); the store lives under HOME, so every test redirects HOME
// into a sandbox.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createCadApp, POST_GUARD_HEADER } from "./httpApp.mjs";
import {
  readTessCacheBatch,
  tessCacheKeyFromRoutePath,
  tessellationCacheDir,
} from "./tessCache.mjs";
import {
  decodeTessellationCacheBatch,
} from "../packages/cadjs/src/lib/surf/tessellationCache.js";
import {
  readCachedTessellationBytes as cadjsRead,
  tessellationCacheDir as cadjsCacheDir,
  writeCachedTessellationBytes as cadjsWrite,
} from "../packages/cadjs/src/lib/surf/tessellationCacheFs.mjs";

const KEY = "c0ffee-t1-l1.500000e-3-a3.500000e-1";

function sandboxHome(t) {
  const home = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "tess-home-")));
  // The cache root resolves CADGEN_CACHE_DIR and XDG_CACHE_HOME before HOME;
  // clear both so the sandbox actually contains the store.
  const previous = {
    HOME: process.env.HOME,
    CADGEN_CACHE_DIR: process.env.CADGEN_CACHE_DIR,
    XDG_CACHE_HOME: process.env.XDG_CACHE_HOME,
  };
  process.env.HOME = home;
  delete process.env.CADGEN_CACHE_DIR;
  delete process.env.XDG_CACHE_HOME;
  t.after(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    fs.rmSync(home, { recursive: true, force: true });
  });
  return home;
}

async function startApp(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cad-tess-"));
  const app = createCadApp({ root, host: "127.0.0.1", port: 0, distDir: "" });
  const server = http.createServer((req, res) => {
    app.handle(req, res).then((handled) => {
      if (!handled) {
        res.writeHead(404);
        res.end();
      }
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => {
    server.close();
    fs.rmSync(root, { recursive: true, force: true });
  });
  return `http://127.0.0.1:${server.address().port}`;
}

const POST_HEADERS = { [POST_GUARD_HEADER]: "1" };

test("the inlined store IS the cadjs store: same dir, interoperable bytes", async (t) => {
  // server/tessCache.mjs carries an inline copy of tessellationCacheFs.mjs
  // because the bundled skill runtime has no cadjs tree. This is the drift
  // fence: same resolved directory, and entries written by either side read
  // back through the other.
  const home = sandboxHome(t);
  assert.equal(tessellationCacheDir(), cadjsCacheDir());
  assert.ok(tessellationCacheDir().startsWith(home));
  cadjsWrite(KEY, Buffer.from("FROM-CADJS"));
  const viaServer = await fetchThroughApp(t, KEY);
  assert.equal(viaServer, "FROM-CADJS");
  assert.equal(Buffer.from(cadjsRead(KEY)).toString(), "FROM-CADJS");
});

async function fetchThroughApp(t, key) {
  const base = await startApp(t);
  const response = await fetch(`${base}/__tess_cache/${key}.tess`);
  return response.status === 200 ? Buffer.from(await response.arrayBuffer()).toString() : null;
}

test("name validation refuses traversal and junk before touching disk", () => {
  assert.equal(tessCacheKeyFromRoutePath(`/__tess_cache/${KEY}.tess`), KEY);
  for (const name of ["../escape.tess", "sub/dir.tess", "%2e%2e%2fescape.tess", ".hidden.tess", "noext", "", "a b.tess"]) {
    assert.equal(tessCacheKeyFromRoutePath(`/__tess_cache/${name}`), null, name);
  }
});

test("GET/POST round trip through the live app, gates included", async (t) => {
  sandboxHome(t);
  const base = await startApp(t);
  const entryUrl = `${base}/__tess_cache/${KEY}.tess`;
  assert.equal((await fetch(entryUrl)).status, 404);
  // POST without the guard header is refused (same gate as every POST route).
  assert.equal((await fetch(entryUrl, { method: "POST", body: "ENTRY" })).status, 403);
  assert.equal(
    (await fetch(entryUrl, { method: "POST", body: "ENTRY", headers: POST_HEADERS })).status,
    204,
  );
  const hit = await fetch(entryUrl);
  assert.equal(hit.status, 200);
  assert.equal(Buffer.from(await hit.arrayBuffer()).toString(), "ENTRY");
  // Refused names 403 on both methods and write nothing.
  assert.equal((await fetch(`${base}/__tess_cache/..%2Fescape.tess`)).status, 403);
  assert.equal(
    (await fetch(`${base}/__tess_cache/..%2Fescape.tess`, { method: "POST", body: "x", headers: POST_HEADERS })).status,
    403,
  );
});

test("batch route speaks the cadjs TESB codec: hits, misses, refusals", async (t) => {
  const home = sandboxHome(t);
  const base = await startApp(t);
  fs.mkdirSync(path.join(home, ".cache", "cadgen", "meshes"), { recursive: true });
  fs.writeFileSync(path.join(home, ".cache", "cadgen", "meshes", `${KEY}.tess`), Buffer.from("AAA"));
  const response = await fetch(`${base}/__tess_cache/batch`, {
    method: "POST",
    headers: { ...POST_HEADERS, "content-type": "application/json" },
    body: JSON.stringify({ names: [`${KEY}.tess`, "missing.tess", "../evil.tess"] }),
  });
  assert.equal(response.status, 200);
  const entries = decodeTessellationCacheBatch(new Uint8Array(await response.arrayBuffer()));
  assert.ok(entries, "server framing must decode with the cadjs codec");
  assert.equal(entries.length, 3);
  assert.equal(Buffer.from(entries[0]).toString(), "AAA");
  assert.equal(entries[1], null);
  assert.equal(entries[2], null);
  // Malformed request bodies are a 400, not a container.
  const bad = await fetch(`${base}/__tess_cache/batch`, {
    method: "POST",
    headers: POST_HEADERS,
    body: "not json",
  });
  assert.equal(bad.status, 400);
});

test("CADGEN_MESH_CACHE=0 turns both directions off, batch included", async (t) => {
  const home = sandboxHome(t);
  process.env.CADGEN_MESH_CACHE = "0";
  t.after(() => {
    delete process.env.CADGEN_MESH_CACHE;
  });
  const base = await startApp(t);
  const entryUrl = `${base}/__tess_cache/${KEY}.tess`;
  // Writes accepted-and-dropped; reads miss.
  assert.equal((await fetch(entryUrl, { method: "POST", body: "X", headers: POST_HEADERS })).status, 204);
  assert.equal((await fetch(entryUrl)).status, 404);
  assert.equal(fs.existsSync(path.join(home, ".cache")), false);
  const batch = readTessCacheBatch(Buffer.from(JSON.stringify({ names: [`${KEY}.tess`] })));
  const entries = decodeTessellationCacheBatch(new Uint8Array(batch));
  assert.deepEqual(entries, [null]);
});
