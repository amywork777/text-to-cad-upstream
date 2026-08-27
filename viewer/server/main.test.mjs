// The launcher contract: the stdout lines agents parse, the refusal (never
// rollover) on an occupied port, and exit-code propagation.
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

test("prints the URL contract and answers /__cad/server; a second start refuses the port", async (t) => {
  const dist = makeDist(t);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cad-root-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const port = 3200 + Math.floor(Math.random() * 500);
  const { out } = launch(t, ["--root", root, "--dist", dist, "--port", String(port), "--json"]);
  await waitFor(() => out.stdout.includes("CAD Viewer URL:"));
  assert.ok(out.stdout.includes(`Starting CAD Viewer at http://127.0.0.1:${port}/ (serving ${fs.realpathSync(root)})`)
    || out.stdout.includes(`Starting CAD Viewer at http://127.0.0.1:${port}/ (serving ${root})`));
  const jsonLine = out.stdout.split("\n").find((line) => line.startsWith("{"));
  assert.deepEqual(JSON.parse(jsonLine), { url: `http://127.0.0.1:${port}/`, port, action: "start" });

  const info = await (await fetch(`http://127.0.0.1:${port}/__cad/server`)).json();
  assert.equal(info.app, "cad-viewer");

  // Occupied port: refuse with a --port hint, never roll to another port.
  const second = launch(t, ["--root", root, "--dist", dist, "--port", String(port)]);
  const code = await new Promise((resolve) => second.child.on("exit", resolve));
  assert.equal(code, 1);
  assert.match(second.out.stderr, /already|--port <n>/);
});

test("a missing root refuses before binding", async (t) => {
  const dist = makeDist(t);
  const { child, out } = launch(t, ["--root", "/nonexistent-root-xyz", "--dist", dist, "--port", "3999"]);
  const code = await new Promise((resolve) => child.on("exit", resolve));
  assert.equal(code, 1);
  assert.match(out.stderr, /root is not a directory/);
});
