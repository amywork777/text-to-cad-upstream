#!/usr/bin/env node
/**
 * Mesh-export a render package: assembly.json + component surfs -> one
 * STL/GLB/3MF file (design/unified-tessellation.md Phase 3).
 *
 * This is the ONE mesh export path: components tessellate from their exact
 * surfaces through the same watertight tessellator the viewport uses, at the
 * same default tolerances, so an export IS what rendered. cadgen's
 * step_export_target dispatches its stl/3mf/glb arms here; `.step` stays
 * native blob assembly and never meshes.
 *
 * Contract:
 *   node mesh-export.mjs --package-dir <abs dir> --format stl|glb|3mf \
 *     --out <abs path> [--name N] [--chord-tolerance t] [--angle-tolerance t]
 *   stdout is exactly one JSON line: {"ok":true,"path":...,"triangleCount":...}
 *   or {"ok":false,"error":...}. No locks, no progress protocol — this writes
 *   only the file the caller named (plus best-effort cache entries).
 *
 * Component tessellations are cached under <cache root>/meshes/ (root:
 * CADGEN_CACHE_DIR, else the platform cache dir — see tessellationCacheFs.mjs)
 * keyed <cid>-t<tessellator-version>-l<chord>-a<angle> (tolerances in the
 * tessellator's diagonal-relative units), so repeat exports and
 * multi-occurrence assemblies pay tessellation once per unique component. The
 * cache is BEST-EFFORT: read/write failures fall through to tessellation,
 * writes are atomic (tmp + rename), and CADGEN_MESH_CACHE=0 disables it
 * entirely; `cadgen cache gc` sweeps orphaned generations.
 */

import fs from "node:fs";
import path from "node:path";

import { parseSurf } from "../src/lib/surf/container.js";
import { DEFAULT_OPTIONS, tessellateComponent } from "../src/lib/surf/tessellate.js";
import {
  decodeComponentTessellation,
  edgeClassesFromSurfIndex,
  encodeComponentTessellation,
  tessellationCacheKey,
} from "../src/lib/surf/tessellationCache.js";
import {
  readCachedTessellationBytes,
  writeCachedTessellationBytes,
} from "../src/lib/surf/tessellationCacheFs.mjs";
import {
  PACKAGE_MESH_EXPORT_FORMATS,
  buildPackageMeshPrimitives,
  packageMeshToFormat,
} from "../src/lib/export/packageMeshExport.js";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const next = argv[index + 1];
    if (next === undefined || next.startsWith("--")) {
      args[token.slice(2)] = "true";
    } else {
      args[token.slice(2)] = next;
      index += 1;
    }
  }
  return args;
}

function fail(message) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(message) })}\n`);
  process.exit(1);
}

function tessellationForComponent(packageDir, cid, entry, options) {
  const key = tessellationCacheKey(cid, options);
  const cached = decodeComponentTessellation(readCachedTessellationBytes(key));
  if (cached) {
    return { ...cached.component, partColor: cached.partColor };
  }
  const surfRel = String(entry?.surf || "");
  if (!surfRel) throw new Error(`component ${cid} has no surf payload`);
  const bytes = fs.readFileSync(path.join(packageDir, surfRel));
  const { index, floats } = parseSurf(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  );
  const component = tessellateComponent(index, floats, options);
  const partColor = Array.isArray(index.partColor) ? index.partColor : null;
  writeCachedTessellationBytes(
    key,
    encodeComponentTessellation(component, {
      partColor,
      edgeClasses: edgeClassesFromSurfIndex(index),
    }),
  );
  return { ...component, partColor };
}

const args = parseArgs(process.argv.slice(2));
const packageDir = String(args["package-dir"] || "");
const outPath = String(args.out || "");
const format = String(args.format || "").toLowerCase();
if (!packageDir || !path.isAbsolute(packageDir)) {
  fail("--package-dir must be an absolute render-package directory");
}
if (!outPath || !path.isAbsolute(outPath)) {
  fail("--out must be an absolute output path");
}
if (!PACKAGE_MESH_EXPORT_FORMATS.includes(format)) {
  fail(`--format must be one of ${PACKAGE_MESH_EXPORT_FORMATS.join(", ")}`);
}
const name = String(args.name || path.basename(outPath).replace(/\.[^.]+$/, "") || "model");
const options = { ...DEFAULT_OPTIONS };
if (args["chord-tolerance"] !== undefined) {
  options.chordTolerance = Number(args["chord-tolerance"]);
}
if (args["angle-tolerance"] !== undefined) {
  options.angleTolerance = Number(args["angle-tolerance"]);
}
if (!(options.chordTolerance > 0) || !(options.angleTolerance > 0)) {
  fail("tolerances must be positive numbers");
}
const defaultColor = args["default-color"] ? String(args["default-color"]) : null;
if (defaultColor !== null && !/^#[0-9a-fA-F]{6}$/.test(defaultColor)) {
  fail("--default-color must be #rrggbb");
}

try {
  const descriptor = JSON.parse(fs.readFileSync(path.join(packageDir, "assembly.json"), "utf8"));
  const componentEntries = descriptor.components || {};
  const used = new Set(
    (descriptor.occurrences || []).map((occurrence) => String(occurrence.component || "")),
  );
  const tessellations = new Map();
  for (const cid of used) {
    if (!componentEntries[cid]) throw new Error(`descriptor names unknown component ${cid}`);
    tessellations.set(cid, tessellationForComponent(packageDir, cid, componentEntries[cid], options));
  }
  const mesh = buildPackageMeshPrimitives(
    descriptor,
    tessellations,
    defaultColor ? { defaultColor: defaultColor.toLowerCase() } : {},
  );
  if (!mesh.triangleCount) throw new Error("package produced no triangles");
  const { body } = packageMeshToFormat(mesh, format, { name });
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const temp = `${outPath}.${process.pid}.tmp`;
  fs.writeFileSync(temp, body);
  fs.renameSync(temp, outPath);
  process.stdout.write(
    `${JSON.stringify({ ok: true, path: outPath, format, triangleCount: mesh.triangleCount })}\n`,
  );
} catch (error) {
  fail(error?.message || error);
}
