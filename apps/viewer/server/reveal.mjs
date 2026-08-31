// Reveal a file in the OS file manager (subprocess), for POST /__cad/reveal.
// Returns exactly one of {ok: true}, {unsupported: true} (no known file manager,
// or disabled by env) or {ok: false, error}.
//
// VIEWER_DISABLE_NATIVE_REVEAL=1 forces unsupported, so a headless CI run cannot
// pop a Finder window if something calls this by accident.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const TIMEOUT_MS = 10_000;

function run(args) {
  const result = spawnSync(args[0], args.slice(1), { encoding: "utf8", timeout: TIMEOUT_MS });
  if (result.error) {
    return { ok: false, error: `could not run ${args[0]}: ${result.error.message}` };
  }
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim().split("\n")[0];
    return { ok: false, error: detail || `${args[0]} exited ${result.status}` };
  }
  return { ok: true };
}

export function revealPath(target) {
  if (String(process.env.VIEWER_DISABLE_NATIVE_REVEAL || "").trim() === "1") {
    return { unsupported: true };
  }
  const resolved = path.resolve(String(target || ""));
  if (!fs.existsSync(resolved)) {
    return { ok: false, error: `no such file: ${resolved}` };
  }
  if (process.platform === "darwin") {
    return run(["open", "-R", resolved]);
  }
  if (process.platform === "win32") {
    // explorer returns nonzero even on success, so its exit code says nothing.
    try {
      spawn("explorer", [`/select,${resolved}`], { detached: true, stdio: "ignore" }).unref();
    } catch (error) {
      return { ok: false, error: `could not run explorer: ${error.message}` };
    }
    return { ok: true };
  }
  // Linux/BSD: no portable "reveal and select", so open the containing folder.
  const directory = fs.statSync(resolved).isDirectory() ? resolved : path.dirname(resolved);
  for (const opener of ["xdg-open", "gio", "nautilus"]) {
    const args = opener === "gio" ? [opener, "open", directory] : [opener, directory];
    const result = run(args);
    if (result.ok || !String(result.error || "").includes("could not run")) {
      return result;
    }
  }
  return { unsupported: true };
}
