// The launcher contract: launch is unconditional (roll + keyed reuse, --new
// escape), explicit --port stays strict, and the stdout lines agents parse.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const MAIN = path.join(path.dirname(fileURLToPath(import.meta.url)), "main.mjs");

function makeDist(t) {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "cad-dist-"));
  fs.writeFileSync(path.join(dist, "index.html"), "<html>viewer</html>");
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));
  return dist;
}

function makeRoot(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cad-root-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function launch(t, args, env = {}) {
  const child = spawn(process.execPath, [MAIN, ...args], {
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const out = { stdout: "", stderr: "" };
  child.stdout.on("data", (c) => (out.stdout += c));
  child.stderr.on("data", (c) => (out.stderr += c));
  t.after(() => child.kill());
  return { child, out };
}

function waitFor(predicate, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      if (predicate()) {
        resolve(undefined);
      } else if (Date.now() > deadline) {
        reject(new Error("timed out"));
      } else {
        setTimeout(tick, 50);
      }
    };
    tick();
  });
}

function jsonLine(out) {
  const line = out.stdout.split("\n").find((l) => l.startsWith("{"));
  assert.ok(line, `no JSON line in: ${out.stdout}`);
  return JSON.parse(line);
}

test("explicit --port: prints the URL contract, answers /__cad/server, and a second explicit start refuses", async (t) => {
  const dist = makeDist(t);
  const root = makeRoot(t);
  const port = 3200 + Math.floor(Math.random() * 40); // below the roll base, never collides with rolled instances
  const { out } = launch(t, ["--root", root, "--dist", dist, "--port", String(port), "--json"]);
  await waitFor(() => out.stdout.includes("CAD Viewer URL:"));
  assert.ok(out.stdout.includes(`Starting CAD Viewer at http://127.0.0.1:${port}/ (serving ${fs.realpathSync(root)})`)
    || out.stdout.includes(`Starting CAD Viewer at http://127.0.0.1:${port}/ (serving ${root})`));
  assert.deepEqual(jsonLine(out), { url: `http://127.0.0.1:${port}/`, port, action: "started" });

  const info = await (await fetch(`http://127.0.0.1:${port}/__cad/server`)).json();
  assert.equal(info.app, "cad-viewer");
  assert.equal(info.port, port, "serverInfo must name the port actually bound");

  // An explicit port is a demand: refuse when taken, never roll, never reuse.
  const second = launch(t, ["--root", root, "--dist", dist, "--port", String(port)]);
  const code = await new Promise((resolve) => second.child.on("exit", resolve));
  assert.equal(code, 1);
  assert.match(second.out.stderr, /already/);
});

test("default launch rolls to a free port; a second root rolls past the first", async (t) => {
  const dist = makeDist(t);
  const first = launch(t, ["--root", makeRoot(t), "--dist", dist, "--json"]);
  await waitFor(() => first.out.stdout.includes("CAD Viewer URL:"));
  const a = jsonLine(first.out);
  assert.equal(a.action, "started");
  assert.ok(a.port >= 3245, `rolled port ${a.port} must be >= the base`);

  // Different root, no reuse match -> must start its own instance on another port.
  const second = launch(t, ["--root", makeRoot(t), "--dist", dist, "--json"]);
  await waitFor(() => second.out.stdout.includes("CAD Viewer URL:"));
  const b = jsonLine(second.out);
  assert.equal(b.action, "started");
  assert.notEqual(b.port, a.port, "occupied candidate must be rolled past, not refused");
});

test("same root reuses the live instance; --new forces a fresh one", async (t) => {
  const dist = makeDist(t);
  const root = makeRoot(t);
  const first = launch(t, ["--root", root, "--dist", dist, "--json"]);
  await waitFor(() => first.out.stdout.includes("CAD Viewer URL:"));
  const a = jsonLine(first.out);

  // Reuse: same realpath(root) x version -> the existing URL, exit 0, no spawn.
  const again = launch(t, ["--root", root, "--json"]); // note: no --dist needed on reuse
  const code = await new Promise((resolve) => again.child.on("exit", resolve));
  assert.equal(code, 0);
  assert.deepEqual(jsonLine(again.out), { url: a.url, port: a.port, action: "reused" });
  assert.match(again.out.stdout, /Reusing CAD Viewer at /);

  // Reuse must also work through a symlinked spelling of the same root.
  const alias = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cad-alias-")), "link");
  fs.symlinkSync(root, alias);
  t.after(() => fs.rmSync(path.dirname(alias), { recursive: true, force: true }));
  const viaAlias = launch(t, ["--root", alias, "--json"]);
  const aliasCode = await new Promise((resolve) => viaAlias.child.on("exit", resolve));
  assert.equal(aliasCode, 0);
  assert.equal(jsonLine(viaAlias.out).action, "reused");

  // --new bypasses the lookup and starts a second instance on another port.
  const fresh = launch(t, ["--root", root, "--dist", dist, "--json", "--new"]);
  await waitFor(() => fresh.out.stdout.includes("CAD Viewer URL:"));
  const c = jsonLine(fresh.out);
  assert.equal(c.action, "started");
  assert.notEqual(c.port, a.port);
});

test("a missing root refuses before binding", async (t) => {
  const dist = makeDist(t);
  const { child, out } = launch(t, ["--root", "/nonexistent-root-xyz", "--dist", dist, "--port", "3999"]);
  const code = await new Promise((resolve) => child.on("exit", resolve));
  assert.equal(code, 1);
  assert.match(out.stderr, /root is not a directory/);
});
