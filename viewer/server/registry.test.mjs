// The instance-registry file format is shared with cadgen's Python readers
// (cadgen/cli/viewer_registry.py) — these pin the writer's side of that contract.
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { entryPath, findByPort, register, unregister } from "./registry.mjs";

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
  assert.ok("publicUrl" in entry);
  assert.ok(entry.packageDir);
  // No temp file left beside it.
  assert.ok(!fs.existsSync(`${target}.${process.pid}.tmp`));
  assert.equal(findByPort(39876).pid, process.pid);
  unregister();
  assert.ok(!fs.existsSync(target));
});
