#!/usr/bin/env node
// Conformance harness entry: run the WASM extractor twin over a .brep blob.
//
//   node extractCli.mjs --brep <in.brep> --out <out.surf>
//
// One JSON line on stdout: {"ok":true,"path":...,"faces":N,"edges":N} or
// {"ok":false,"error":...}. Used by the cross-implementation conformance suite
// (tests/python/packages/cadgen/test_surf_extractor_conformance.py) and for
// hand-debugging a single corpus blob.
import fs from "node:fs";
import path from "node:path";

import { loadKernel } from "./ocKernel.mjs";
import { extractSurfaceComponent, shapeFromBrepBuffer } from "./surfExtractTwin.mjs";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token.startsWith("--")) {
      args[token.slice(2)] = argv[index + 1];
      index += 1;
    }
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
if (!args.brep || !args.out) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: "usage: --brep <in> --out <out.surf>" })}\n`);
  process.exit(2);
}

try {
  const oc = await loadKernel();
  const shape = shapeFromBrepBuffer(oc, fs.readFileSync(args.brep));
  const surf = extractSurfaceComponent(oc, shape);
  fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
  fs.writeFileSync(args.out, surf);
  const jsonLength = surf.readUInt32LE(8);
  const index = JSON.parse(surf.subarray(12, 12 + jsonLength).toString("utf8"));
  process.stdout.write(
    `${JSON.stringify({ ok: true, path: path.resolve(args.out), faces: index.counts.faces, edges: index.counts.edges })}\n`,
  );
  process.exit(0);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.message || error) })}\n`);
  process.exit(1);
}
