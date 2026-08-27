// The server's single Python touchpoint: `python -m cadgen.render_ops`, a
// stdlib-only one-shot answering artifact status / build / export / probe as
// one JSON line. Everything OCP-shaped stays behind it (the op itself dispatches
// heavy work to the shared warm daemon pool); this process never hosts Python.
//
// Without a working cadgen the viewer still serves: status degrades to a pure
// filesystem check and builds/exports answer with an install hint.
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { renderPackageDir } from "./scanner.mjs";

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

// Degraded status when no Python runtime is reachable: a package whose descriptor
// exists renders as-is (a possibly-stale render beats nothing when nothing could
// rebuild it anyway); anything else is an error naming the install.
function degradedStatus(fileRef, rootDir) {
  const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
  try {
    // A generated drawing's product is its sibling .dxf; when it exists the
    // viewer parses it directly, cadgen or no cadgen.
    if (/\.dxf\.py$/i.test(candidate)) {
      if (fs.existsSync(candidate.slice(0, -3))) {
        return { state: "ready", degraded: true };
      }
      return { state: "error", error: CADGEN_UNAVAILABLE_HINT };
    }
    const packageDir = renderPackageDir(candidate);
    const assemblyPath = path.join(packageDir, "assembly.json");
    if (fs.existsSync(assemblyPath)) {
      // Honest staleness for an imported STEP: the descriptor records the hash
      // of the file it was built from — pure hashing, no Python needed. The
      // package still renders (a possibly-stale render beats nothing when
      // nothing could rebuild it), but the client can say so.
      const status = { state: "ready", degraded: true };
      try {
        const descriptor = JSON.parse(fs.readFileSync(assemblyPath, "utf8"));
        const recorded = String(descriptor?.stepHash || "");
        if (recorded && /\.(step|stp)$/i.test(candidate) && fs.existsSync(candidate)) {
          const digest = crypto.createHash("sha256").update(fs.readFileSync(candidate)).digest("hex");
          if (digest !== recorded) {
            status.stale = true;
            status.staleReason = "the STEP file changed after this package was imported";
          }
        }
      } catch {
        // Descriptor unreadable enough to hash-check: render as-is.
      }
      return status;
    }
    if (fs.existsSync(path.join(packageDir, "implicit.json"))) {
      return { state: "ready", degraded: true };
    }
    if (/\.(step|stp)$/i.test(candidate)) {
      return {
        state: "error",
        error:
          "This STEP file has not been imported yet. Importing needs the cadgen "
          + "Python package (pip install cadgen); once imported, it renders here "
          + "with no Python required.",
      };
    }
  } catch {
    // fall through to the error below
  }
  return { state: "error", error: CADGEN_UNAVAILABLE_HINT };
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
      const result = await runRenderOps(rootDir, ["status", "--file", fileRef, "--root", rootDir]);
      if (result.unavailable) {
        return degradedStatus(fileRef, rootDir);
      }
      return result;
    },

    async buildArtifact(fileRef, { force = false } = {}) {
      if (!ownsArtifactPath(fileRef)) {
        return { ok: true, state: "ready" };
      }
      const args = ["build", "--file", fileRef, "--root", rootDir];
      if (force) {
        args.push("--force");
      }
      const result = await runRenderOps(rootDir, args);
      if (result.unavailable) {
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
