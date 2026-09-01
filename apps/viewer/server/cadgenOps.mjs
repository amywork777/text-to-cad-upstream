// Artifact operations for a STATIC visualization tool.
//
// The viewer's render path runs NO Python: it renders what exists — render
// packages and sibling .dxf files. Generation and export belong to running
// model scripts and the CLIs; the viewer neither runs generators nor writes
// artifact bytes itself. The one build-shaped thing it does is importing a
// raw FOREIGN .step, and that spawns `cadgen step compile` — importing a foreign
// document is that one verb applied to it — as a child process. cadgen is a
// SOFT dependency: absent, viewing
// is unaffected and imports fail with one actionable message
// (cadgenResolve.mjs).
//
// Status is the JS authority (artifactStatus.mjs). Build progress — a CLI
// build's OR our own import child's — is read from the build's progress
// record beside the package (schema: cadgen/coordination/record.py). For CLI
// builds of generated entries the read stays ADVISORY (the viewer takes no
// action, so the strict kernel-lock rules in cadgen/coordination/lock.py do
// not apply; a killed build's badge ages out of the freshness window). For
// the viewer's own import child, the same record is simply the child
// narrating its work — the in-flight map below, not the record, is what
// gates re-spawning.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { renderPackageDir } from "./scanner.mjs";
import { coordinationScope } from "./storePaths.mjs";
import {
  ARTIFACT_STATE,
  artifactStatus as computeArtifactStatus,
  ownsDxfPath,
  ownsStepPath,
  resolveArtifactVerdict,
} from "./artifactStatus.mjs";
import { cadgenUnavailableMessage, createCadgenResolver } from "./cadgenResolve.mjs";

const RAW_STEP_RE = /\.(step|stp)$/i;

// A locked package answers `contended` after this long instead of queueing
// the viewer's request behind an arbitrarily long peer build. The client
// treats contended as "generating" and attaches to the peer's progress.
const IMPORT_LOCK_TIMEOUT_SECONDS = 5;

// Kill an import child that has gone SILENT for this long — idleness, not wall
// clock (ports develop's 06bf1b3b/dbeea4f3). A real STEP compile legitimately
// runs for minutes, so a wall-clock cap would abort healthy builds; total
// silence on both pipes is the signal that the child is wedged rather than
// working. Without this the promise never settled, and because `importsInFlight`
// is only cleared in .finally(), one hung child pinned that package to
// "generating" for the life of the process. `<= 0` disables the watchdog.
const CADGEN_IDLE_TIMEOUT_SECONDS = Number(process.env.VIEWER_CADGEN_IDLE_TIMEOUT ?? 300);
const IDLE_POLL_MS = 250;

const CLI_BUILD_HINT =
  "The viewer is a static visualization tool and does not run generators. "
  + "Build this model by running its script: python <source>.";

// The viewer owns status for the entries whose render artifact it reads from
// disk.
export function ownsArtifactPath(filePath) {
  return ownsStepPath(filePath) || ownsDxfPath(filePath);
}

// --- build progress ----------------------------------------------------------
// Every cadgen build (a CLI run of a model script, a CLI `cadgen step compile`, or
// the viewer's own import child) writes `.<pathKey>.generation.progress.json`
// in the store's locks/ tier, keyed by the MODEL path (storePaths.mjs mirrors
// cadgen.catalog.coordination_scope). Its phase fields are flattened at the
// top level in exactly the shape the client's normalizeArtifactProgress
// reads, so one reader serves every producer. No runId filtering here — the
// viewer cannot know a child's runId before reading the record — so
// staleness is gated on outcome + the freshness window instead.
const PROGRESS_FRESHNESS_MS = 20_000;

export function buildProgressSnapshot(entryPath) {
  const scope = coordinationScope(entryPath);
  const recordPath = path.join(
    path.dirname(scope), `.${path.basename(scope)}.generation.progress.json`);
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
  if (!Number.isFinite(updatedAt) || Date.now() - updatedAt > PROGRESS_FRESHNESS_MS) {
    return null;
  }
  return {
    writing: true,
    busy: false,
    runId: typeof record.runId === "string" ? record.runId : null,
    progress: record,
  };
}

function isRawStepFile(candidate) {
  return RAW_STEP_RE.test(candidate) && fs.existsSync(candidate);
}

// One import per package dir at a time, per process: concurrent requests for
// the same entry attach to the in-flight child instead of spawning a second
// interpreter. Cross-process races are the kernel lock's job — a peer
// holding the package lock makes our child answer `contended`, which maps to
// "generating" downstream.
const importsInFlight = new Map();

// Test seam: suites read/stage in-flight state without spawning cadgen.
export function importsInFlightState() {
  return importsInFlight;
}

function parseResultLine(stdout) {
  for (const line of stdout.split("\n").reverse()) {
    const stripped = line.trim();
    if (stripped.startsWith("{")) {
      try {
        return JSON.parse(stripped);
      } catch {
        return null;
      }
    }
  }
  return null;
}

function runCadgenImport(resolver, candidate, { force = false } = {}) {
  const packageDir = renderPackageDir(candidate);
  const inFlight = importsInFlight.get(packageDir);
  if (inFlight) {
    return inFlight;
  }
  const promise = new Promise((resolve) => {
    const resolved = resolver.resolve();
    if (!resolved || !resolved.ok) {
      resolve({ ok: false, error: cadgenUnavailableMessage() });
      return;
    }
    const args = [
      ...resolved.prefixArgs,
      "step",
      // COMPILE, not build: importing a foreign STEP means making its render
      // package current in the shared store, which is exactly the cache action
      // — `step build` writes a NEW document and is not what an import is.
      "compile",
      candidate,
      "--lock-timeout",
      String(IMPORT_LOCK_TIMEOUT_SECONDS),
      // The result is machine-read: `step compile` prints human lines by
      // default and one JSON line (the CompileResult dataclass) under --json.
      "--json",
    ];
    if (force) {
      args.push("--force");
    }
    // The child inherits this process's environment verbatim — standard
    // Python knobs (PYTHONPATH for a worktree's cadgen sources, VIRTUAL_ENV,
    // etc.) flow through with no custom plumbing.
    const child = spawn(resolved.command, args, {
      // The STEP's own directory, NOT the served root: `cadgen step compile`
      // scans its cwd for CAD sources to resolve generated siblings, and a
      // large served root would pay a full recursive walk per import.
      cwd: path.dirname(candidate),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    // Every settle path goes through here so the watchdog can never outlive the
    // child. Promise resolution is idempotent, so the kill below racing the
    // `close` it provokes is harmless — the first answer wins.
    let idleTimer = null;
    const settle = (value) => {
      if (idleTimer !== null) {
        clearInterval(idleTimer);
        idleTimer = null;
      }
      resolve(value);
    };
    let lastActivity = Date.now();
    child.stdout.on("data", (chunk) => {
      lastActivity = Date.now();
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      // Output on EITHER pipe counts as liveness: `step compile` reports
      // progress on stderr and prints its JSON result only at the end.
      lastActivity = Date.now();
      stderr += chunk;
    });
    if (CADGEN_IDLE_TIMEOUT_SECONDS > 0) {
      const budgetMs = CADGEN_IDLE_TIMEOUT_SECONDS * 1000;
      idleTimer = setInterval(() => {
        const quietForMs = Date.now() - lastActivity;
        if (quietForMs <= budgetMs) {
          return;
        }
        child.kill("SIGKILL");
        settle({
          ok: false,
          error: `cadgen step compile went silent for ${(quietForMs / 1000).toFixed(1)}s `
            + "(no response and no output); killed",
        });
      }, IDLE_POLL_MS);
      // Never hold the event loop open on the watchdog alone.
      idleTimer.unref?.();
    }
    child.on("error", (error) => {
      // ENOENT here means the resolved command vanished (uninstalled while
      // the server ran). Drop the cache so the next request re-probes.
      resolver.invalidate();
      settle({ ok: false, error: `could not run cadgen step compile: ${error.message}` });
    });
    child.on("close", (code) => {
      const payload = parseResultLine(stdout);
      if (payload) {
        settle(payload);
        return;
      }
      settle({
        ok: false,
        error: (stderr || stdout || `cadgen step compile exited with code ${code}`).trim().slice(-500),
      });
    });
  }).finally(() => {
    importsInFlight.delete(packageDir);
  });
  importsInFlight.set(packageDir, promise);
  return promise;
}

export function createCadgenOps(rootDir, { cadgenProbeForTests = null } = {}) {
  const resolver = createCadgenResolver(rootDir, { probeForTests: cadgenProbeForTests });
  return {
    stepImportAvailable() {
      return resolver.available();
    },

    async artifactStatus(fileRef) {
      if (!ownsArtifactPath(fileRef)) {
        return { state: "ready" };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      const packageDir = renderPackageDir(candidate);
      let snapshot = buildProgressSnapshot(candidate);
      if (!snapshot && importsInFlight.has(packageDir)) {
        // Our child is starting up but has not published a record yet: show
        // an indeterminate generating badge rather than nothing.
        snapshot = { writing: true, busy: false, runId: null, progress: null };
      }
      const status = computeArtifactStatus(fileRef, rootDir, { snapshot });
      if (status.state !== ARTIFACT_STATE.NEEDS_BUILD) {
        return status;
      }
      // The ONLY buildable state the viewer supports is importing a raw
      // foreign STEP via `cadgen step compile`. Everything else renders what
      // exists or names the CLI.
      const verdict = resolveArtifactVerdict(fileRef, rootDir);
      if (verdict.rawStep && !verdict.generated) {
        // A foreign .step is simply importable. A GENERATED one is not routed
        // through this door — not because it looks different in the UI (it does
        // not), but because `cadgen step compile` refuses a document that is
        // stale relative to its script, and the viewer must never make
        // rendering depend on source code. Regeneration is the model script's
        // job and restores pose/mates/provenance whenever it runs.
        if (resolver.available()) {
          return { state: "needs-build", reason: status.reason, stepImport: true };
        }
        return {
          state: "error",
          error: `This STEP file has not been imported yet, and ${cadgenUnavailableMessage()}`,
        };
      }
      // No stale-render limbo exists under content keying: an edited file
      // resolves to a different key (needs-build above), and a resolved
      // package is by construction the render of exactly these bytes.
      return { state: "error", error: CLI_BUILD_HINT };
    },

    async buildArtifact(fileRef, { force = false } = {}) {
      if (!ownsArtifactPath(fileRef)) {
        return { ok: true, state: "ready" };
      }
      const candidate = path.isAbsolute(fileRef) ? fileRef : path.resolve(rootDir, fileRef);
      const verdict = resolveArtifactVerdict(fileRef, rootDir);
      if (isRawStepFile(candidate) && !verdict.generated) {
        const imported = await runCadgenImport(resolver, candidate, { force });
        if (imported.ok && imported.contended) {
          // A peer process holds the package lock and is building it. The
          // client treats this exactly like attaching to a CLI build.
          return { ok: true, state: "generating", contended: true };
        }
        if (imported.ok) {
          return { ok: true, state: "ready", stepImport: true, ...imported };
        }
        return {
          ok: false,
          state: "error",
          error: `STEP import failed: ${imported.error || "unknown error"}`,
        };
      }
      return { ok: false, state: "error", error: CLI_BUILD_HINT };
    },
  };
}
