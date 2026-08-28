// The worker client's cache identity rule: only a content-addressed component
// surf (components/<cid>.surf) may key the shared tessellation cache — an
// arbitrary .surf path has no stable identity and caching it by name would
// collide across models.
import assert from "node:assert/strict";
import test from "node:test";

import { cidFromSurfUrl, loadSurfComponentInWorker } from "./surfWorkerClient.js";

test("cidFromSurfUrl accepts only components/<cid>.surf", () => {
  assert.equal(
    cidFromSurfUrl("/__cad/models/__cadgen__/models/x.step/components/abc123.surf"),
    "abc123",
  );
  assert.equal(cidFromSurfUrl("http://h/pkg/components/deadbeef.surf?v=1#frag"), "deadbeef");
  assert.equal(cidFromSurfUrl("/pkg/components/upper%2Bcase.surf"), "upper+case");
  assert.equal(cidFromSurfUrl("/pkg/other/abc.surf"), "", "non-components dir");
  assert.equal(cidFromSurfUrl("/components/abc.notsurf"), "", "wrong extension");
  assert.equal(cidFromSurfUrl("abc.surf"), "", "no components parent");
  assert.equal(cidFromSurfUrl(""), "");
});

test("loadSurfComponentInWorker returns null where Workers do not exist (node)", () => {
  assert.equal(loadSurfComponentInWorker("/pkg/components/abc.surf"), null);
});
