// Resolving a runnable cadgen for the viewer's ONE Python-shaped need:
// importing a foreign STEP. Viewing never touches this — the render path is
// pure JS over packages on disk — so cadgen is a SOFT dependency: absent, the
// viewer still views everything and imports fail with one actionable message.
//
// Resolution order, deliberately WITHOUT find-up discovery (the deleted
// cad-python.mjs documented the trap: find-up `.venv` binds a git worktree to
// its PARENT checkout's cadgen, importing with the wrong version):
//   1. $CADGEN_PYTHON        -> spawn `<it> -m cadgen.cli <verb> ...`
//   2. `cadgen` on PATH          -> pip's console script, the common install
//   3. <servedRoot>/.venv        -> the project-local environment, if any
//
// The probe runs `<candidate> --help` once and caches the winner — the
// dumbest possible check: exit 0 proves a runnable cadgen CLI, with no
// cadgen-specific exit-code lore. Anything deeper (pin mismatches, broken
// installs) is the spawned import's problem to REPORT, not the probe's to
// predict. `invalidate()` drops the cache so a spawn-time ENOENT (cadgen
// uninstalled while the server ran) re-probes on the next request instead of
// failing forever.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PROBE_TIMEOUT_MS = 15_000;

// Test seam: suites inject a fake resolution (through the full app) instead
// of probing for a real cadgen. Module-level on purpose — createCadApp offers
// no options plumbing, and tests exercise the whole HTTP surface.
let probeOverrideForTests = null;
export function _setCadgenProbeForTests(probe) {
  probeOverrideForTests = probe;
}

function candidateCommands(rootDir) {
  const candidates = [];
  const override = String(process.env.CADGEN_PYTHON || "").trim();
  if (override) {
    candidates.push({ command: override, prefixArgs: ["-m", "cadgen.cli"], source: "CADGEN_PYTHON" });
  }
  candidates.push({ command: "cadgen", prefixArgs: [], source: "PATH" });
  const venvPython = process.platform === "win32"
    ? path.join(rootDir, ".venv", "Scripts", "python.exe")
    : path.join(rootDir, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    candidates.push({ command: venvPython, prefixArgs: ["-m", "cadgen.cli"], source: ".venv" });
  }
  return candidates;
}

function probe(candidate) {
  try {
    const result = spawnSync(candidate.command, [...candidate.prefixArgs, "--help"], {
      timeout: PROBE_TIMEOUT_MS,
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (result.error) {
      return false;
    }
    return result.status === 0;
  } catch {
    return false;
  }
}

export function cadgenUnavailableMessage() {
  return (
    "importing a STEP file requires cadgen, which the viewer could not find. "
    + "Install it (pip install cadgen, or the cad skill's requirements.txt) "
    + "or point CADGEN_PYTHON at a Python with cadgen installed. "
    + "Viewing existing models does not need cadgen."
  );
}

export function createCadgenResolver(rootDir, { probeForTests = null } = {}) {
  let cached; // undefined = not probed; null = unavailable; object = resolved
  return {
    resolve() {
      if (probeOverrideForTests) {
        return probeOverrideForTests();
      }
      if (probeForTests) {
        return probeForTests();
      }
      if (cached !== undefined) {
        return cached;
      }
      for (const candidate of candidateCommands(rootDir)) {
        if (probe(candidate)) {
          cached = { ok: true, ...candidate };
          return cached;
        }
      }
      cached = null;
      return cached;
    },
    available() {
      const resolved = this.resolve();
      return Boolean(resolved && resolved.ok);
    },
    invalidate() {
      cached = undefined;
    },
  };
}
