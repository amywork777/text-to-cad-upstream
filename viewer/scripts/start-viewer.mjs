#!/usr/bin/env node
// Thin shim: launch the CAD Viewer backend (cadgen.viewer) using the project's
// discovered venv Python, so `npm start` runs it without the caller knowing the venv
// path. Reuses the proven cadPythonExecutable/cadPythonEnv discovery from the STEP
// pipeline.
//
// The backend lives in cadgen now, not under viewer/, so this passes --dist to point it
// at THIS checkout's freshly built client rather than the copy inside the installed
// cadgen. That is the whole difference between iterating here and running the shipped
// viewer: same server, different client bundle.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cadPythonExecutable, cadPythonEnv } from "./cad-python.mjs";
import { resolveDirectoryRoot } from "./directoryRoot.mjs";

const viewerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(viewerRoot, "..");
const python = cadPythonExecutable(repoRoot);
const baseEnv = cadPythonEnv(repoRoot);

// The backend has no configured directory: a URL path IS the directory, and the bare
// origin falls back to the process cwd. So the child's cwd must be where the USER ran
// `npm start` (npm's INIT_CWD), not viewer/ — `npm --prefix` would otherwise make the
// default directory the viewer's own source tree.
const distRoot = path.join(viewerRoot, "dist");
const child = spawn(python, ["-m", "cadgen.viewer", "--dist", distRoot, ...process.argv.slice(2)], {
  cwd: resolveDirectoryRoot({ env: baseEnv, appRoot: viewerRoot }),
  env: baseEnv,
  stdio: "inherit",
});
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
child.on("error", (error) => {
  process.stderr.write(`Failed to start Python CAD Viewer launcher: ${error.message}\n`);
  process.exit(1);
});
