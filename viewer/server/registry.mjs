// A best-effort registry of running CAD Viewers, so instances can be found and
// stopped (`cadgen viewer list` / `stop` read this directory). Modelled on
// TensorBoard's .tensorboard-info: each live server drops a small JSON file in
// the system temp dir naming itself; liveness is an HTTP identity probe against
// /__cad/server requiring a matching pid, never a signal.
//
// The on-disk format is shared with cadgen's Python readers — change it there too.
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
    // The URL a human should open. In dev that is vite's port, not this server's,
    // so the spawning process passes it down rather than us guessing.
    publicUrl: process.env.CADGEN_VIEWER_PUBLIC_URL || "",
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

export function findByPort(port) {
  let names;
  try {
    names = fs.readdirSync(registryDir());
  } catch {
    return null;
  }
  for (const name of names) {
    if (!name.startsWith("viewer-") || !name.endsWith(".json")) {
      continue;
    }
    try {
      const entry = JSON.parse(fs.readFileSync(path.join(registryDir(), name), "utf8"));
      if (entry && entry.port === Math.trunc(port)) {
        return entry;
      }
    } catch {
      // skip corrupt entries
    }
  }
  return null;
}
