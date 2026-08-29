// Artifact operations for a STATIC visualization tool.
//
// The viewer runs NO Python, ever. It renders what exists: render packages,
// sibling .dxf files, live implicit sources. Generation and export belong to
// running model scripts and the CLIs — the viewer neither runs generators
// nor writes new artifact bytes. The one build-shaped thing it still does is
// Python-free by construction: importing a raw foreign STEP through the WASM
// kernel (server/import/), which is how a .step becomes viewable at all on a
// machine with nothing else installed.
//
// Status is the JS authority (artifactStatus.mjs). "A CLI build is running"
// is shown ADVISORILY from the build's status record — the viewer takes no
// action on it (it never builds generated entries), so the strict kernel-lock
// rules in cadgen/coordination/lock.py do not apply to this read: a killed
// build's badge simply ages out of the freshness window.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { renderPackageDir } from "./scanner.mjs";
import {
  ARTIFACT_STATE,
  artifactStatus as computeArtifactStatus,
  ownsDxfPath,
  ownsStepPath,
  resolveArtifactVerdict,
} from "./artifactStatus.mjs";

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const IMPORT_CLI_PATH = path.join(SERVER_DIR, "import", "importCli.mjs");
const RAW_STEP_RE = /\.(step|stp)$/i;

const CLI_BUILD_HINT =
  "The viewer is a static visualization tool and does not run generators. "
  + "Build this model by running its script: python <source>.";

// The viewer owns status for the entries whose render artifact it reads from
// disk. Implicit models render LIVE from their own source, so they are not
// artifact-managed here at all (their baked packages exist for CLI exports).
export function ownsArtifactPath(filePath) {
  return ownsStepPath(filePath) || ownsDxfPath(filePath);
}

// --- advisory build progress -------------------------------------------------
// A CLI build writes `.<name>.generation.progress.json` beside the package
// (schema: cadgen/coordination/record.py; outcome is null while running).
// Fresh + running -> show a generating badge with its progress. This is UI
// decoration only; correctness never hangs on it — the viewer takes no build
// action for these entries, so a lingering or missing badge misleads nobody.
const ADVISORY_FRESHNESS_MS = 20_000;

function advisoryBuildProgress(packageDir) {
  const recordPath = path.join(
    path.dirname(packageDir), `.${path.basename(packageDir)}.generation.progress.json`);
  let record;
  try {
    record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
  } catch {
    return null;
  }
  if (!record || typeof record !== "object" || record.outcome != null) {
    return null;
  }
  const updatedAt = Number(record.updatedAt || 0);
  if (!Number.isFinite(updatedAt) || Date.now() - updatedAt > ADVISORY_FRESHNESS_MS) {
    return null;
  }
  return {
    writing: true,
    busy: false,
    runId: typeof record.runId === "string" ? record.runId : null,
    progress: record,
  };
}

// --- WASM STEP import ---------------------------------------------------------
// The import is simply a capability the viewer has: the kernel ships with the
// bundled skill and is an npm dependency everywhere else, so its ABSENCE is a
// broken install, not a configuration. One graceful failure path names the
// missing file. Tests exercise that path by injecting a probe (loader
// injection), not via a shipped env var.
let kernelProbeForTests = null;
export function _setKernelProbeForTests(probe) {
  kernelProbeForTests = probe;
}

function wasmKernelResolution() {
  if (kernelProbeForTests) {
    return kernelProbeForTests();
  }
  try {
    // Resolve the kernel the way the import worker will, so "available" and
    // "will actually load" agree.
    const kernelPath = path.join(
      SERVER_DIR, "..", "node_modules", "opencascade.js", "dist", "opencascade.full.wasm",
    );
    if (!fs.existsSync(IMPORT_CLI_PATH)) {
      return { ok: false, missing: IMPORT_CLI_PATH };
    }
    if (!fs.existsSync(kernelPath)) {
      return { ok: false, missing: kernelPath };
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, missing: String(error?.message || error) };
  }
}

function brokenKernelMessage(missing) {
  return (
    "the viewer's WASM import kernel is missing (broken install): expected "
    + `${missing}. Reinstall the cad-viewer skill (or npm install in a viewer `
    + "checkout), or import it with the CAD skill: cadgen import <file>."
  );
}

function isRawStepFile(candidate) {
  return RAW_STEP_RE.test(candidate) && fs.existsSync(candidate);
}

// One import per package dir at a time: the import runs as a child process (an
// emscripten abort must never take the server down with it), and concurrent
// requests for the same entry attach to the in-flight run instead of racing it.
const wasmImportsInFlight = new Map();

// --- live import progress ------------------------------------------------------
// The import child reports one `[import-progress] {json}` line per event on
// stderr (importCli.mjs). Parsed here into an in-memory record per in-flight
// package dir, served by the artifact-status route in the SAME shape a CLI
// build's progress record takes (phase/label/detail/done/total/determinate,
// see viewer/src/client/workbench/artifactProgress.js) — so the client's
// existing generating badge renders a real bar for the components phase, which
// is minutes on 100MB-class files, instead of an indeterminate spinner.
const wasmImportProgress = new Map();
const IMPORT_PROGRESS_PREFIX = "[import-progress] ";

// Phase order gives the badge its "2/5" ordinal; labels match the phase's
// actual work. `components` is the only phase with a real denominator.
const IMPORT_PHASES = ["parse", "analyze", "walk", "components", "finalize"];
const IMPORT_PHASE_LABELS = {
  parse: "Parse STEP",
  analyze: "Mesh resolution",
  walk: "Assembly walk",
  components: "Extract components",
  finalize: "Write descriptor",
};

export function parseImportProgressLine(line) {
  const stripped = line.trim();
  if (!stripped.startsWith(IMPORT_PROGRESS_PREFIX)) {
    return null;
  }
  let event;
  try {
    event = JSON.parse(stripped.slice(IMPORT_PROGRESS_PREFIX.length));
  } catch {
    return null;
  }
  const phase = String(event?.phase || "").trim();
  if (!phase) {
    return null;
  }
  const total = Number.isFinite(event.total) ? Math.max(0, Math.round(event.total)) : null;
  const done = Number.isFinite(event.done) ? Math.max(0, Math.round(event.done)) : 0;
  const ordinal = IMPORT_PHASES.indexOf(phase);
  return {
    phase,
    label: IMPORT_PHASE_LABELS[phase] || phase,
    detail: String(event.detail || "").trim(),
    index: ordinal >= 0 ? ordinal + 1 : 0,
    count: IMPORT_PHASES.length,
    done,
    total,
    determinate: total !== null && total > 0,
    updatedAt: Date.now(),
  };
}

// Test seams: let suites read (or stage) live import state without racing a
// real kernel run. Both return the internal maps on purpose.
export function wasmImportProgressState() {
  return wasmImportProgress;
}

export function wasmImportsInFlightState() {
  return wasmImportsInFlight;
}

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
    wasmImportProgress.set(packageDir, {
      runId: `wasm-import-${child.pid ?? "spawn"}-${Date.now()}`,
      record: null,
    });
    let stdout = "";
    let stderr = "";
    let stderrTail = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderrTail += chunk;
      const lines = stderrTail.split("\n");
      stderrTail = lines.pop() ?? "";
      for (const line of lines) {
        const record = parseImportProgressLine(line);
        if (record) {
          const entry = wasmImportProgress.get(packageDir);
          if (entry) {
            entry.record = record;
          }
        } else {
          stderr += `${line}\n`;
        }
      }
    });
    child.on("error", (error) => {
      resolve({ ok: false, error: `could not run the WASM STEP import: ${error.message}` });
    });
    child.on("close", (code) => {
      if (stderrTail && !parseImportProgressLine(stderrTail)) {
        stderr += `${stderrTail}\n`;
      }
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
    wasmImportProgress.delete(packageDir);
  });
  wasmImportsInFlight.set(packageDir, promise);
  return promise;
}

export function createCadgenOps(rootDir) {
  return {
    async artifactStatus(fileRef) {
      if (!ownsArtifactPath(fileRef)) {
        return { state: "ready" };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      const packageDir = renderPackageDir(candidate);
      let snapshot = advisoryBuildProgress(packageDir);
      if (!snapshot && wasmImportsInFlight.has(packageDir)) {
        const live = wasmImportProgress.get(packageDir);
        snapshot = {
          writing: true,
          busy: false,
          runId: live?.runId ?? null,
          progress: live?.record ?? null,
        };
      }
      const status = computeArtifactStatus(fileRef, rootDir, { snapshot });
      if (status.state !== ARTIFACT_STATE.NEEDS_BUILD) {
        return status;
      }
      // The ONLY buildable state the viewer supports is the WASM import of a
      // raw STEP. Everything else renders what exists or names the CLI.
      const verdict = resolveArtifactVerdict(fileRef, rootDir);
      if (verdict.rawStep && !verdict.generated) {
        const kernel = wasmKernelResolution();
        if (kernel.ok) {
          const importable = { state: "needs-build", reason: status.reason, wasmImport: true };
          if (verdict.digestMismatch) {
            importable.staleReason = "the STEP file changed after this package was imported";
          }
          return importable;
        }
        if (!verdict.descriptor) {
          return {
            state: "error",
            error: `This STEP file has not been imported yet, and ${brokenKernelMessage(kernel.missing)}`,
          };
        }
      }
      if (verdict.descriptor) {
        // A renderable package exists: render as-is, honestly badged when the
        // source file's digest disagrees.
        const asIs = { state: "ready", degraded: true };
        if (verdict.digestMismatch) {
          asIs.stale = true;
          asIs.staleReason = "the STEP file changed after this package was imported";
        }
        return asIs;
      }
      return { state: "error", error: CLI_BUILD_HINT };
    },

    async buildArtifact(fileRef, { force = false } = {}) {
      if (!ownsArtifactPath(fileRef)) {
        return { ok: true, state: "ready" };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      const verdict = resolveArtifactVerdict(fileRef, rootDir);
      if (isRawStepFile(candidate) && !verdict.generated) {
        const kernel = wasmKernelResolution();
        if (!kernel.ok) {
          return { ok: false, state: "error", error: `Cannot import: ${brokenKernelMessage(kernel.missing)}` };
        }
        const imported = await runWasmImport(candidate, { force });
        if (imported.ok) {
          return { ok: true, state: "ready", wasmImport: true, ...imported };
        }
        return {
          ok: false,
          state: "error",
          error: `WASM STEP import failed: ${imported.error || "unknown error"}`,
        };
      }
      return { ok: false, state: "error", error: CLI_BUILD_HINT };
    },
  };
}
