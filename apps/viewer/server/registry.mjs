// A best-effort registry of running CAD Viewers, so instances can be found and
// stopped (`main.mjs list` / `main.mjs stop` read this directory). Modelled on
// TensorBoard's .tensorboard-info: each live server drops a small JSON file in
// the system temp dir naming itself; liveness is an HTTP identity probe against
// /__cad/server requiring a matching pid, never a signal.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const REGISTRY_DIR_NAME = "cadgen-viewer-info";

export function registryDir() {
  return path.join(os.tmpdir(), REGISTRY_DIR_NAME);
}

function ensureRegistryDir() {
  // Create 0700; on a shared /tmp another user could pre-create the directory,
  // so an existing one is used only when we own it. Failing closed just means no
  // registry entry — it must never stop a viewer from starting.
  const dir = registryDir();
  try {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    if (typeof process.getuid === "function") {
      if (fs.statSync(dir).uid !== process.getuid()) {
        return null;
      }
    }
  } catch {
    return null;
  }
  return dir;
}

export function entryPath(pid) {
  return path.join(registryDir(), `viewer-${Math.trunc(pid)}.json`);
}

export function register({ host, port, root = "", viewerVersion = "" }) {
  const dir = ensureRegistryDir();
  if (!dir) {
    return "";
  }
  const pid = process.pid;
  const payload = {
    pid,
    host: String(host),
    port: Math.trunc(port),
    version: String(viewerVersion || ""),
    root: String(root || ""),
    packageDir: path.dirname(new URL(import.meta.url).pathname),
    startedAt: Date.now() / 1000,
  };
  const target = entryPath(pid);
  const temporary = `${target}.${pid}.tmp`;
  try {
    fs.writeFileSync(temporary, JSON.stringify(payload));
    fs.renameSync(temporary, target);
  } catch {
    try {
      fs.unlinkSync(temporary);
    } catch {
      // best-effort
    }
    return "";
  }
  return target;
}

export function unregister(pid = process.pid) {
  try {
    fs.unlinkSync(entryPath(pid));
  } catch {
    // best-effort
  }
}

function readEntries() {
  let names;
  try {
    names = fs.readdirSync(registryDir()).sort();
  } catch {
    return [];
  }
  const entries = [];
  for (const name of names) {
    if (!name.startsWith("viewer-") || !name.endsWith(".json")) {
      continue;
    }
    try {
      const entry = JSON.parse(fs.readFileSync(path.join(registryDir(), name), "utf8"));
      if (entry && Number.isInteger(entry.pid) && Number.isInteger(entry.port)) {
        entries.push(entry);
      }
    } catch {
      // skip corrupt entries
    }
  }
  return entries;
}

export function findByPort(port) {
  return readEntries().find((entry) => entry.port === Math.trunc(port)) || null;
}

const PROBE_TIMEOUT_MS = 500;

/** True when the recorded port answers /__cad/server AS the recorded pid.
 *
 * Never a signal: after a hard kill the port is free for anything else to take,
 * and acting on a stale file that names a stranger's port would be the worst
 * thing `stop` could do.
 */
export async function probe(entry, timeoutMs = PROBE_TIMEOUT_MS) {
  const host = String(entry.host || "127.0.0.1");
  try {
    const response = await fetch(`http://${host}:${entry.port}/__cad/server`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    return Boolean(payload) && payload.pid === entry.pid;
  } catch {
    return false;
  }
}

/** Every entry whose identity probe succeeds, oldest first. Stale files are deleted. */
export async function liveEntries({ reap = true } = {}) {
  const live = [];
  for (const entry of readEntries()) {
    if (await probe(entry)) {
      live.push(entry);
    } else if (reap) {
      unregister(entry.pid);
    }
  }
  live.sort((a, b) => (a.startedAt || 0) - (b.startedAt || 0));
  return live;
}
