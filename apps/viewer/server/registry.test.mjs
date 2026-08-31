// The instance registry: the writer side, and the identity-probed read side that
// `main.mjs list`/`stop` are built on.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import test from "node:test";

import { entryPath, findByPort, liveEntries, probe, register, unregister } from "./registry.mjs";

test("register writes a complete entry and unregister removes it", (t) => {
  const target = register({ host: "127.0.0.1", port: 39876, root: "/tmp/models", viewerVersion: "1.2.3" });
  if (!target) {
    t.skip("registry dir not writable here");
    return;
  }
  t.after(() => unregister());
  assert.equal(target, entryPath(process.pid));
  const entry = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.equal(entry.pid, process.pid);
  assert.equal(entry.host, "127.0.0.1");
  assert.equal(entry.port, 39876);
  assert.equal(entry.version, "1.2.3");
  assert.equal(entry.root, "/tmp/models");
  assert.equal(typeof entry.startedAt, "number");
  assert.ok(entry.packageDir);
  // No temp file left beside it.
  assert.ok(!fs.existsSync(`${target}.${process.pid}.tmp`));
  assert.equal(findByPort(39876).pid, process.pid);
  unregister();
  assert.ok(!fs.existsSync(target));
});

test("liveEntries keeps identity-probed entries and reaps the rest", async (t) => {
  // A tiny stand-in for /__cad/server that answers as THIS pid.
  const server = http.createServer((req, res) => {
    if (req.url === "/__cad/server") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ pid: process.pid }));
      return;
    }
    res.writeHead(404);
    res.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const port = server.address().port;

  const target = register({ host: "127.0.0.1", port, root: "/tmp/models", viewerVersion: "1.2.3" });
  if (!target) {
    t.skip("registry dir not writable here");
    return;
  }
  t.after(() => unregister());

  const live = await liveEntries();
  assert.ok(live.some((entry) => entry.pid === process.pid && entry.port === port));

  // A stale entry — a pid+port nothing answers for — fails its probe and is reaped.
  const stalePid = 999999;
  fs.writeFileSync(
    entryPath(stalePid),
    JSON.stringify({ pid: stalePid, host: "127.0.0.1", port: 1, startedAt: 0 }),
  );
  assert.equal(await probe({ pid: stalePid, host: "127.0.0.1", port: 1 }), false);
  await liveEntries();
  assert.ok(!fs.existsSync(entryPath(stalePid)), "stale entry must be reaped");
});

test("probe rejects a live port answering as a DIFFERENT pid", async (t) => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ pid: process.pid + 1 }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const port = server.address().port;
  // The registry names OUR pid, but the port answers as someone else: after a
  // hard kill another process may hold the port, and stop must not touch it.
  assert.equal(await probe({ pid: process.pid, host: "127.0.0.1", port }), false);
});
