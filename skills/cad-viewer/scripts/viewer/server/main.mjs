#!/usr/bin/env node
// Single-port CAD Viewer server (pure JS, zero dependencies).
//
// Launching is UNCONDITIONAL, Jupyter-style: `main.mjs --root <dir>` always
// ends with the URL of a live, correct Viewer for that directory. If an
// identity-probed instance already serves realpath(root) at this viewer
// version, its URL is printed with action:"reused" and nothing is spawned
// (--new skips the lookup); otherwise the server binds the first free port
// from 3245 upward and prints action:"started". An EXPLICIT --port stays
// strict — it exits 1 when taken — because then the port was the ask.
// The printed URL (and the --json {url,port,action} line) is the contract;
// the port is an output of launch, never something the caller reasons about.
//
// Also the instance manager: `main.mjs list [--json]` shows every running
// Viewer (identity-probed, stale entries reaped) and `main.mjs stop --port <n>`
// / `--pid <n>` terminates one. These live here rather than in a separate tool
// because the registry the server writes is the only source of truth. Dev
// (`vite dev`) never registers: the registry is bundled instances only.
//
// A Viewer serves ONE directory, given by --root and defaulting to the invoking
// directory. The page is always the bare origin; `?file=` selects a file inside
// that root. To serve a second directory, just launch again with that root.
//
// cadgen is NOT required to start: without it the viewer serves packaged
// models read-only and importing a foreign STEP answers with an install hint
// (imports spawn `cadgen import`; see cadgenResolve.mjs).
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createCadApp, readViewerVersion } from "./httpApp.mjs";
import * as registry from "./registry.mjs";

export const DEFAULT_VIEWER_HOST = "127.0.0.1";
export const DEFAULT_VIEWER_PORT = 3245;
// How far past the default the launcher will roll looking for a free port
// before giving up. Far beyond any plausible number of live Viewers.
const PORT_ROLL_LIMIT = 100;

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_ROOT = path.resolve(SERVER_DIR, "..");

function parseArgs(argv) {
  const args = {
    host: DEFAULT_VIEWER_HOST,
    port: DEFAULT_VIEWER_PORT,
    // Explicit --port means "this port or fail"; the default means "any free
    // port from the base" and enables the reuse lookup + roll.
    portExplicit: false,
    root: "",
    dist: "",
    json: false,
    open: false,
    fresh: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--host") args.host = argv[++i] || args.host;
    else if (arg === "--port") {
      args.port = Number(argv[++i]) || args.port;
      args.portExplicit = true;
    } else if (arg === "--root") args.root = argv[++i] || "";
    else if (arg === "--dist") args.dist = argv[++i] || "";
    else if (arg === "--json") args.json = true;
    else if (arg === "--open") args.open = true;
    else if (arg === "--new") args.fresh = true;
    // Unknown args tolerated, matching the old launcher.
  }
  if (!(args.port > 0 && args.port <= 65535)) {
    args.port = DEFAULT_VIEWER_PORT;
    args.portExplicit = false;
  }
  return args;
}

function pathInside(candidate, container) {
  const relative = path.relative(container, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

// The directory this Viewer serves: --root, else where the USER invoked it
// (npm's INIT_CWD survives `npm --prefix viewer run start`), rejecting anything
// inside the viewer app itself so `npm start` never serves the source tree.
export function resolveDirectoryRoot({ root = "", env = process.env, cwd = process.cwd() } = {}) {
  if (root) {
    return path.resolve(cwd, root);
  }
  for (const candidate of [env.INIT_CWD, cwd]) {
    if (!candidate) {
      continue;
    }
    const resolved = path.resolve(candidate);
    if (resolved !== VIEWER_ROOT && !pathInside(resolved, VIEWER_ROOT)) {
      return resolved;
    }
  }
  return path.resolve(cwd);
}

function resolveDistDir(explicit) {
  const candidates = [
    String(explicit || "").trim(),
    String(process.env.CADGEN_VIEWER_DIST || "").trim(),
    path.join(VIEWER_ROOT, "dist"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (fs.existsSync(path.join(resolved, "index.html"))) {
      return resolved;
    }
  }
  return "";
}

// True when this process can BIND host:port — the same operation the server is
// about to perform, so the probe cannot disagree with reality (ports 3236a5c9
// from develop). This used to probe by CONNECTING, with only ECONNREFUSED
// counting as free; on Windows a connect to a closed port routinely fails some
// other way (Hyper-V/WSL port exclusions, loopback filtering, refusals arriving
// as timeouts), so free ports read as occupied and the launcher refused to
// start with a false "already in use". A definite EADDRINUSE (or EACCES,
// Windows's answer for its excluded ranges) keeps the friendly rerun-with-
// --port message; any OTHER failure counts as free, because this probe exists
// only for that message — the server's own bind stays authoritative and
// reports anything genuinely wrong.
function portIsFree(host, port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.unref();
    probe.once("error", (error) => {
      resolve(!(error.code === "EADDRINUSE" || error.code === "EACCES"));
    });
    probe.listen({ host, port, exclusive: true }, () => {
      probe.close(() => resolve(true));
    });
  });
}

async function openWhenReady(url, host, port, timeoutMs = 2000) {
  const probe = `http://${host}:${port}/__cad/server`;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const response = await fetch(probe, { signal: AbortSignal.timeout(250) });
      if (response.ok) {
        break;
      }
    } catch {
      // keep polling
    }
    if (Date.now() >= deadline) {
      process.stderr.write(`Viewer did not answer within ${timeoutMs / 1000}s; not opening a browser.\n`);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const { spawn } = await import("node:child_process");
  const opener = process.platform === "darwin" ? "open" : process.platform === "win32" ? "start" : "xdg-open";
  try {
    spawn(opener, [url], { detached: true, stdio: "ignore", shell: process.platform === "win32" }).unref();
  } catch (error) {
    process.stderr.write(`Could not open a browser: ${error.message}\n`);
  }
}

function realpathOr(candidate) {
  try {
    return fs.realpathSync(String(candidate || ""));
  } catch {
    return String(candidate || "");
  }
}

// The reuse key: realpath(root) × viewer version, over identity-probed entries
// only. Never port, never pid — keying on the port was the old source-blind
// reuse bug, and pid-liveness is the probe's job. Dev instances never register,
// so nothing here can hand back a Vite process.
async function findReusable(directory, viewerVersion) {
  const rootReal = realpathOr(directory);
  const live = await registry.liveEntries(); // probes pids, reaps stale files
  return (
    live.find(
      (entry) => realpathOr(entry.root) === rootReal && String(entry.version || "") === String(viewerVersion || ""),
    ) || null
  );
}

function formatAge(startedAt) {
  if (!startedAt) {
    return "";
  }
  const seconds = Math.max(0, Math.trunc(Date.now() / 1000 - startedAt));
  if (seconds >= 3600) {
    return `  up ${Math.trunc(seconds / 3600)}h${String(Math.trunc((seconds % 3600) / 60)).padStart(2, "0")}m`;
  }
  return `  up ${Math.trunc(seconds / 60)}m`;
}

function formatEntry(entry) {
  const url = `http://${entry.host || "127.0.0.1"}:${entry.port}/`;
  return (
    `  port ${entry.port}  pid ${entry.pid}  viewer ${entry.version || "?"}${formatAge(entry.startedAt)}\n` +
    `    ${url}\n` +
    `    serving  ${entry.root || "?"}\n` +
    `    code     ${entry.packageDir || "?"}`
  );
}

// `main.mjs list [--json]` — what CAD Viewers are running, and whose code answers
// each port. A viewer serves one directory fixed at startup, so instances differ
// both by what they serve and by WHICH CHECKOUT'S CODE holds the port.
export async function listCommand(argv) {
  const asJson = argv.includes("--json");
  const entries = await registry.liveEntries(); // also reaps anything that fails its identity probe
  if (asJson) {
    process.stdout.write(`${JSON.stringify(entries)}\n`);
    return 0;
  }
  if (!entries.length) {
    process.stdout.write("No CAD Viewer is running.\n");
    return 0;
  }
  process.stdout.write(`${entries.length} CAD Viewer${entries.length === 1 ? "" : "s"} running:\n`);
  for (const entry of entries) {
    process.stdout.write(`${formatEntry(entry)}\n`);
  }
  return 0;
}

const STOP_WAIT_MS = 3000;

// `main.mjs stop --port <n> | --pid <n>` — terminate a running CAD Viewer. Only
// ever signals a process the registry can still identify (liveEntries probes each
// recorded port and requires the answering pid to match the entry).
export async function stopCommand(argv) {
  let port = null;
  let pid = null;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--port") port = Number(argv[++i]);
    else if (argv[i] === "--pid") pid = Number(argv[++i]);
  }
  if (!port && !pid) {
    process.stderr.write("Specify which viewer to stop: --port <n> or --pid <n>.\n");
    return 2;
  }
  const entries = await registry.liveEntries();
  const described = port ? `port ${port}` : `pid ${pid}`;
  const target = port
    ? entries.find((entry) => entry.port === Math.trunc(port))
    : entries.find((entry) => entry.pid === Math.trunc(pid));
  if (!target) {
    process.stderr.write(`No running CAD Viewer for ${described}.\n`);
    return 1;
  }
  try {
    process.kill(target.pid, "SIGTERM");
  } catch (error) {
    process.stderr.write(`Could not stop pid ${target.pid}: ${error.message}\n`);
    return 1;
  }
  const deadline = Date.now() + STOP_WAIT_MS;
  while (Date.now() < deadline) {
    if (!(await registry.probe(target, 250))) {
      registry.unregister(target.pid);
      process.stdout.write(`Stopped CAD Viewer on port ${target.port} (pid ${target.pid}).\n`);
      return 0;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  process.stderr.write(`CAD Viewer pid ${target.pid} did not exit within ${STOP_WAIT_MS / 1000}s.\n`);
  return 1;
}

export async function main(argv = process.argv.slice(2)) {
  if (argv[0] === "list") {
    return listCommand(argv.slice(1));
  }
  if (argv[0] === "stop") {
    return stopCommand(argv.slice(1));
  }
  const args = parseArgs(argv);
  const directory = resolveDirectoryRoot({ root: args.root });
  if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) {
    // Booting a viewer whose root does not exist would answer every request with
    // a 404 that looks like a missing model rather than a missing root.
    process.stderr.write(`CAD Viewer root is not a directory: ${directory}\n`);
    return 1;
  }
  // Reuse before spawn: a live, identity-probed instance already serving this
  // realpath(root) at this viewer version IS the requested viewer. Explicit
  // --port opts out (you asked for a port, not a viewer), --new forces fresh.
  if (!args.fresh && !args.portExplicit) {
    const held = await findReusable(directory, readViewerVersion());
    if (held) {
      const url = `http://${held.host || DEFAULT_VIEWER_HOST}:${held.port}/`;
      process.stdout.write(`Reusing CAD Viewer at ${url} (serving ${held.root}, pid ${held.pid})\n`);
      process.stdout.write(`CAD Viewer URL: ${url}\n`);
      if (args.json) {
        process.stdout.write(`${JSON.stringify({ url, port: held.port, action: "reused" })}\n`);
      }
      if (args.open) {
        await openWhenReady(url, held.host || DEFAULT_VIEWER_HOST, held.port);
      }
      return 0;
    }
  }

  const distDir = resolveDistDir(args.dist);
  if (!distDir) {
    process.stderr.write(
      "No built CAD Viewer client found. Build one with `npm --prefix viewer run build` " +
        "or point --dist / CADGEN_VIEWER_DIST at a dist directory.\n",
    );
    return 1;
  }
  const { host } = args;
  let port = args.port;
  if (args.portExplicit) {
    // An explicit port is a demand, not a preference: refuse when taken, and
    // say who has it so the collision is diagnosable.
    if (!(await portIsFree(host, port))) {
      const holder = registry.findByPort(port);
      if (holder) {
        process.stderr.write(
          `Port ${port} on ${host} is already serving a CAD Viewer: pid ${holder.pid}, ` +
            `viewer ${holder.version || "?"}, from ${holder.packageDir || "?"}.\n` +
            `Stop it with \`node ${process.argv[1] || "server/main.mjs"} stop --port ${port}\`, ` +
            `or rerun without --port to take any free port.\n`,
        );
      } else {
        process.stderr.write(`Port ${port} on ${host} is already in use. Rerun without --port to take any free port.\n`);
      }
      return 1;
    }
  }

  // Bind BEFORE building the app, so the app (whose serverInfo reports the
  // port) always names the port actually taken. Rolling is done by BINDING,
  // not pre-probing: the bind is the only check that cannot disagree with
  // reality, and a lost race just moves to the next candidate. Explicit
  // --port gets a single attempt.
  const server = http.createServer();
  const lastCandidate = args.portExplicit ? port : port + PORT_ROLL_LIMIT;
  for (;;) {
    try {
      await new Promise((resolve, reject) => {
        const onError = (error) => reject(error);
        server.once("error", onError);
        server.listen({ port, host, exclusive: true }, () => {
          server.removeListener("error", onError);
          resolve(undefined);
        });
      });
      break;
    } catch (error) {
      const taken = error && (error.code === "EADDRINUSE" || error.code === "EACCES");
      if (!taken || args.portExplicit || port >= lastCandidate) {
        throw error;
      }
      port += 1;
    }
  }

  // Attach the handler in the same tick as the successful bind: no event-loop
  // turn runs between listen resolving and this line, so no request can be
  // dropped in the gap.
  const app = createCadApp({ root: directory, host, port, distDir });
  server.on("request", (req, res) => {
    app.handle(req, res).catch((error) => {
      if (!res.headersSent) {
        res.writeHead(500, { "content-type": "application/json; charset=utf-8" });
      }
      res.end(JSON.stringify({ error: String(error && error.message ? error.message : error) }));
    });
  });

  const url = `http://${host}:${port}/`;
  process.stdout.write(`Starting CAD Viewer at ${url} (serving ${directory})\n`);
  process.stdout.write(`CAD Viewer URL: ${url}\n`);
  if (args.json) {
    process.stdout.write(`${JSON.stringify({ url, port, action: "started" })}\n`);
  }

  // Announce this instance so `main.mjs list` can find it — after the bind,
  // so we never advertise a port we failed to take.
  registry.register({ host, port, root: directory, viewerVersion: app.serverInfo().viewerVersion });
  const shutdown = () => {
    registry.unregister();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 500).unref();
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", () => registry.unregister());

  if (args.open) {
    openWhenReady(url, host, port);
  }
  return new Promise(() => {});
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(
    (code) => {
      // The server path never resolves; list/stop do, and must not linger on a
      // stray keep-alive socket.
      if (typeof code === "number") {
        process.exit(code);
      }
    },
    (error) => {
      process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
      process.exit(1);
    },
  );
}
