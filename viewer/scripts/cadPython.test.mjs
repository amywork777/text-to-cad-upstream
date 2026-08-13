// Which cadgen the viewer's Python backend is spawned against.
//
// The backend is `cadgen.viewer`, so this resolution decides which branch's code actually
// runs. The candidates walk UPWARD from this file, and a git worktree lives inside its
// parent checkout — so a candidate that matches further up binds the backend to a
// different branch, and the failure surfaces as an unrelated-looking ModuleNotFoundError
// at dev-server startup rather than as "you are running the wrong cadgen".

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { cadPythonEnv } from "./cad-python.mjs";

const SCRIPTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_ROOT = path.resolve(SCRIPTS_DIR, "..");
const REPO_ROOT = path.resolve(VIEWER_ROOT, "..");

function entries() {
  const env = cadPythonEnv();
  return String(env.PYTHONPATH || "")
    .split(path.delimiter)
    .filter(Boolean);
}

test("this checkout's own packages/cadgen/src leads PYTHONPATH", () => {
  const own = path.join(REPO_ROOT, "packages", "cadgen", "src");
  if (!fs.existsSync(own)) {
    return; // A packaged runtime has no repo packages/ dir; nothing to order.
  }
  assert.equal(
    entries()[0],
    own,
    "a cadgen found further up (e.g. the parent checkout of a worktree) must not win",
  );
});

test("every PYTHONPATH entry stays inside this checkout", () => {
  for (const entry of entries()) {
    assert.ok(
      path.resolve(entry).startsWith(REPO_ROOT + path.sep),
      `${entry} escapes ${REPO_ROOT} — the walk reached a parent checkout`,
    );
  }
});

test("the leading entry can actually import cadgen.viewer", () => {
  const own = path.join(REPO_ROOT, "packages", "cadgen", "src");
  if (!fs.existsSync(own)) {
    return;
  }
  // The whole point of the ordering: the backend module has to be there.
  assert.ok(
    fs.existsSync(path.join(entries()[0], "cadgen", "viewer", "server.py")),
    "the leading PYTHONPATH entry has no cadgen/viewer/server.py",
  );
});
