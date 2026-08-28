// The server's single Python touchpoint: `python -m cadgen.render_ops`, a
// stdlib-only one-shot answering artifact status / build / export / probe as
// one JSON line. Everything OCP-shaped stays behind it (the op itself dispatches
// heavy work to the shared warm daemon pool); this process never hosts Python.
//
// Without a working cadgen the viewer still serves: status degrades to a pure
// filesystem check and builds/exports answer with an install hint — except for
// raw STEP files, which the WASM import (server/import/) converts into a
// standard render package with no Python at all.
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { renderPackageDir } from "./scanner.mjs";
import {
  ARTIFACT_STATE,
  artifactStatus as computeArtifactStatus,
  resolveArtifactVerdict,
} from "./artifactStatus.mjs";

const STEP_ENTRY_RE = /\.(step|stp)(\.py)?$/i;
// Generated drawings only: an imported .dxf renders natively (the client
// parses the file itself), so it needs no build and is not owned.
const DXF_ENTRY_RE = /\.dxf\.py$/i;
const IMPLICIT_SUFFIXES = [".implicit.js", ".implicit.mjs"];

export function ownsArtifactPath(filePath) {
  const value = String(filePath || "");
  const lowered = value.toLowerCase();
  return (
    STEP_ENTRY_RE.test(value) ||
    DXF_ENTRY_RE.test(value) ||
    IMPLICIT_SUFFIXES.some((suffix) => lowered.endsWith(suffix))
  );
}

// --- interpreter discovery -------------------------------------------------
function firstExistingFile(paths) {
  return paths.find((candidate) => {
    try {
      return fs.statSync(candidate).isFile();
    } catch {
      return false;
    }
  }) || "";
}

function findUp(startDir, relativePath) {
  let current = path.resolve(startDir);
  for (;;) {
    const candidate = path.join(current, relativePath);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const next = path.dirname(current);
    if (next === current) {
      return "";
    }
    current = next;
  }
}

export function cadPythonExecutable(rootDir = "") {
  // VIEWER_CAD_PYTHON wins outright: `cadgen viewer` sets it to the interpreter
  // that launched the viewer, so a pip-installed cadgen finds itself.
  const configured = String(process.env.VIEWER_CAD_PYTHON || process.env.CAD_PYTHON || "").trim();
  if (configured) {
    return configured;
  }
  const resolvedRoot = path.resolve(rootDir || process.cwd());
  const venvPython = path.join(".venv", "bin", "python");
  return (
    firstExistingFile([
      path.join(resolvedRoot, venvPython),
      path.join(process.cwd(), venvPython),
      findUp(resolvedRoot, venvPython),
    ]) || "python3"
  );
}

export function cadPythonEnv() {
  const entries = [];
  for (const configured of [process.env.VIEWER_CAD_PYTHONPATH, process.env.CAD_PYTHONPATH]) {
    const value = String(configured || "").trim();
    if (value) {
      entries.push(value);
    }
  }
  const existing = String(process.env.PYTHONPATH || "").trim();
  if (existing) {
    entries.push(existing);
  }
  return {
    ...process.env,
    ...(entries.length ? { PYTHONPATH: entries.join(path.delimiter) } : {}),
  };
}

// --- the one-shot ------------------------------------------------------------
function runRenderOps(rootDir, args, { timeoutMs = 0 } = {}) {
  return new Promise((resolve) => {
    const python = cadPythonExecutable(rootDir);
    const child = spawn(python, ["-m", "cadgen.render_ops", ...args], {
      cwd: rootDir,
      env: cadPythonEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timer = null;
    if (timeoutMs > 0) {
      timer = setTimeout(() => child.kill(), timeoutMs);
    }
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      if (timer) clearTimeout(timer);
      resolve({ ok: false, unavailable: true, error: `could not run ${python}: ${error.message}` });
    });
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      for (const line of stdout.split("\n").reverse()) {
        const stripped = line.trim();
        if (stripped.startsWith("{")) {
          try {
            resolve(JSON.parse(stripped));
            return;
          } catch {
            break;
          }
        }
      }
      const message = (stderr || stdout || `cadgen.render_ops exited with code ${code}`).trim();
      // "No CAD runtime here" is a supported degraded mode, not a request
      // failure. That includes an interpreter that produced NO stdout at all:
      // a real render_ops run always prints one JSON line, so silence means
      // the interpreter never reached Python (missing binary, shim, sandbox).
      const unavailable =
        /No module named|ModuleNotFoundError|could not run/.test(message) ||
        !stdout.trim();
      resolve({ ok: false, unavailable, error: message });
    });
  });
}

const CADGEN_UNAVAILABLE_HINT =
  "CAD generation requires the cadgen Python package (pip install cadgen); the viewer is serving read-only.";

// --- WASM STEP import (Python-less fallback) ---------------------------------
const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const IMPORT_CLI_PATH = path.join(SERVER_DIR, "import", "importCli.mjs");
const RAW_STEP_RE = /\.(step|stp)$/i;

// VIEWER_WASM_IMPORT=1 forces the WASM path even when cadgen answers (tests,
// side-by-side comparison); =0 disables it outright (and lets tests exercise
// the kernel-less degraded messages on a checkout that has the kernel).
// Read per call, not at module load, so tests can flip it.
function wasmImportForced() {
  return String(process.env.VIEWER_WASM_IMPORT || "").trim() === "1";
}

export function wasmImportAvailable() {
  if (String(process.env.VIEWER_WASM_IMPORT || "").trim() === "0") {
    return false;
  }
  try {
    // The kernel is a viewer npm dependency; resolve it the way the import
    // worker will, so "available" and "will actually load" agree.
    const kernelPath = path.join(
      SERVER_DIR, "..", "node_modules", "opencascade.js", "dist", "opencascade.full.wasm",
    );
    return fs.existsSync(IMPORT_CLI_PATH) && fs.existsSync(kernelPath);
  } catch {
    return false;
  }
}

function isRawStepFile(candidate) {
  return RAW_STEP_RE.test(candidate) && fs.existsSync(candidate);
}

// One import per package dir at a time: the WASM import runs as a child process
// (an emscripten abort must never take the server down with it), and concurrent
// requests for the same entry attach to the in-flight run instead of racing it.
const wasmImportsInFlight = new Map();

function runWasmImport(candidate, { force = false } = {}) {
  const packageDir = renderPackageDir(candidate);
  const inFlight = wasmImportsInFlight.get(packageDir);
  if (inFlight) {
    return inFlight;
  }
  const promise = new Promise((resolve) => {
    const args = [IMPORT_CLI_PATH, "--step", candidate, "--package-dir", packageDir];
    if (force) {
      args.push("--force");
    }
    const child = spawn(process.execPath, args, {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      resolve({ ok: false, error: `could not run the WASM STEP import: ${error.message}` });
    });
    child.on("close", (code) => {
      for (const line of stdout.split("\n").reverse()) {
        const stripped = line.trim();
        if (stripped.startsWith("{")) {
          try {
            resolve(JSON.parse(stripped));
            return;
          } catch {
            break;
          }
        }
      }
      resolve({
        ok: false,
        error: (stderr || stdout || `WASM STEP import exited with code ${code}`).trim().slice(-500),
      });
    });
  }).finally(() => {
    wasmImportsInFlight.delete(packageDir);
  });
  wasmImportsInFlight.set(packageDir, promise);
  return promise;
}

export function createCadgenOps(rootDir) {
  let probePromise = null;
  return {
    // Lazily probed and cached: startup never blocks on Python. `/__cad/server`
    // reports the cached answer (optimistically true until the probe lands).
    probe() {
      if (!probePromise) {
        probePromise = runRenderOps(rootDir, ["probe"], { timeoutMs: 60_000 }).then((result) => {
          if (result.unavailable) {
            return { ok: false, error: result.error };
          }
          return result;
        });
      }
      return probePromise;
    },

    async artifactStatus(fileRef) {
      if (!ownsArtifactPath(fileRef)) {
        return { state: "ready" };
      }
      // Freshness is decided HERE (viewer/server/artifactStatus.mjs) — the one
      // authority. Python contributes only the kernel lock snapshot (flock is
      // not probeable from Node, and liveness must never be re-inferred from
      // pids or heartbeats — see cadgen/coordination/lock.py).
      const snapshotResult = await runRenderOps(
        rootDir, ["snapshot", "--file", fileRef, "--root", rootDir], { timeoutMs: 30_000 });
      const pythonAvailable = !snapshotResult.unavailable;
      let snapshot = null;
      if (pythonAvailable && snapshotResult.ok !== false) {
        snapshot = {
          writing: snapshotResult.state === "writing",
          busy: snapshotResult.state === "busy",
          runId: snapshotResult.runId || null,
          progress: snapshotResult.progress ?? null,
        };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      if (!pythonAvailable && wasmImportsInFlight.has(renderPackageDir(candidate))) {
        snapshot = { writing: true, busy: false, runId: null, progress: null };
      }
      const status = computeArtifactStatus(fileRef, rootDir, { snapshot });
      if (!pythonAvailable && status.state === ARTIFACT_STATE.READY) {
        // Nothing here can rebuild; the client can say the render is served as-is.
        status.degraded = true;
      }
      if (pythonAvailable || status.state !== ARTIFACT_STATE.NEEDS_BUILD) {
        return status;
      }
      // No Python: a buildable verdict must degrade honestly. A raw STEP still
      // imports through the WASM kernel; anything else renders what exists or
      // names the install.
      const verdict = resolveArtifactVerdict(fileRef, rootDir);
      if (verdict.rawStep && wasmImportAvailable()) {
        const degraded = { state: "needs-build", reason: status.reason, degraded: true, wasmImport: true };
        if (verdict.digestMismatch) {
          degraded.staleReason = "the STEP file changed after this package was imported";
        }
        return degraded;
      }
      if (verdict.descriptor || (verdict.format === "dxf" && verdict.code !== "missing_dxf_output" && verdict.code !== "missing_source_path")) {
        // A renderable package exists and nothing here can rebuild it: render
        // as-is, honestly badged when the source file's digest disagrees.
        const degraded = { state: "ready", degraded: true };
        if (verdict.digestMismatch) {
          degraded.stale = true;
          degraded.staleReason = "the STEP file changed after this package was imported";
        }
        return degraded;
      }
      if (verdict.rawStep) {
        return {
          state: "error",
          error:
            "This STEP file has not been imported yet. Importing needs the cadgen "
            + "Python package (pip install cadgen); once imported, it renders here "
            + "with no Python required.",
        };
      }
      return { state: "error", error: CADGEN_UNAVAILABLE_HINT };
    },

    async buildArtifact(fileRef, { force = false } = {}) {
      if (!ownsArtifactPath(fileRef)) {
        return { ok: true, state: "ready" };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      const wasmEligible = isRawStepFile(candidate) && wasmImportAvailable();
      const importViaWasm = async () => {
        const imported = await runWasmImport(candidate, { force });
        if (imported.ok) {
          return { ok: true, state: "ready", degraded: true, wasmImport: true, ...imported };
        }
        return {
          ok: false,
          state: "error",
          error: `WASM STEP import failed: ${imported.error || "unknown error"}`,
        };
      };
      if (wasmEligible && wasmImportForced()) {
        return importViaWasm();
      }
      const args = ["build", "--file", fileRef, "--root", rootDir];
      if (force) {
        args.push("--force");
      }
      const result = await runRenderOps(rootDir, args);
      if (result.unavailable) {
        // No Python here. A raw STEP still imports — at WASM speed, once —
        // through the bundled kernel; everything else needs cadgen.
        if (wasmEligible) {
          return importViaWasm();
        }
        return { ok: false, state: "error", error: CADGEN_UNAVAILABLE_HINT };
      }
      return result;
    },

    async generateExport(fileRef, format, outPath) {
      const result = await runRenderOps(rootDir, [
        "export", "--file", fileRef, "--root", rootDir, "--format", format, "--out", outPath,
      ]);
      if (result.unavailable) {
        return { ok: false, error: CADGEN_UNAVAILABLE_HINT };
      }
      return result;
    },
  };
}
