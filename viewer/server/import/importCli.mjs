#!/usr/bin/env node
// WASM STEP import entry: convert a foreign STEP file into a standard render
// package without Python.
//
//   node importCli.mjs --step <file.step> --package-dir <dir> [--force]
//
// One JSON line on stdout: {"ok":true,...build stats} or {"ok":false,"error"}.
// Used by the import worker, the interop/e2e suites, and hand-debugging.
import { loadKernel } from "./ocKernel.mjs";
import { buildPackageFromStep } from "./stepImport.mjs";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      continue;
    }
    const key = token.slice(2);
    if (key === "force") {
      args.force = true;
    } else {
      args[key] = argv[index + 1];
      index += 1;
    }
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
if (!args.step || !args["package-dir"]) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: "usage: --step <file.step> --package-dir <dir> [--force]" })}\n`);
  process.exit(2);
}

try {
  const oc = await loadKernel();
  const result = buildPackageFromStep(oc, args.step, args["package-dir"], {
    force: Boolean(args.force),
    onProgress: ({ phase, detail }) => {
      process.stderr.write(`[import] ${phase}: ${detail ?? ""}\n`);
    },
  });
  process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
  process.exit(0);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.message || error) })}\n`);
  process.exit(1);
}
