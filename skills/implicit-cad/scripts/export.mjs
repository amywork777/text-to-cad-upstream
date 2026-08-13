#!/usr/bin/env node
// Export an implicit model. A shim over the `cadgen` distribution named in this skill's
// requirements.txt: cadgen owns the exporter (it is JavaScript, because an implicit model
// IS a JS module) and resolves it out of its own packaged runtime.
//
// argv, stdio and the exit code pass through untouched, so this is indistinguishable from
// running the exporter directly.
import { spawnSync } from "node:child_process";

const python = process.env.CADGEN_PYTHON || process.env.CAD_PYTHON || "python3";
const completed = spawnSync(
  python,
  ["-m", "cadgen.cli.implicit_export_js", ...process.argv.slice(2)],
  { cwd: process.cwd(), stdio: "inherit" },
);

if (completed.error) {
  process.stderr.write(
    `Could not run ${python}: ${completed.error.message}\n` +
      "cadgen must be installed for the implicit exporter. From the skill directory run:\n" +
      "  python -m pip install -r requirements.txt\n",
  );
  process.exit(3);
}

process.exitCode = completed.status ?? 1;
