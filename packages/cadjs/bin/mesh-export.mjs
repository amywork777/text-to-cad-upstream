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
 *   node mesh-export.mjs --package-dir <abs dir> \
 *     --format stl|glb|3mf --out <abs path> [--chord-tolerance t] [--angle-tolerance t] \
 *     [--format F --out P [--chord-tolerance t] [--angle-tolerance t] ...] \
 *     [--name N]
 *   `--format`/`--out` repeat as ordered pairs. Tolerance flags AFTER a pair
 *   bind to that pair; tolerance flags BEFORE the first pair set the run
 *   defaults. Jobs group by their effective tolerance pair: the package is
 *   tessellated ONCE PER GROUP and each job serializes from its group's
 *   tessellation, so same-tolerance formats share one tessellation exactly as
 *   before. stdout is exactly one JSON line:
 *   {"ok":true,"files":[{"path":...,"format":...,"triangleCount":...},...]}
 *   or {"ok":false,"error":...}. No locks, no progress protocol — this writes
 *   only the files the caller named (plus best-effort cache entries).
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
  // Scalar flags are last-wins; `--format`/`--out` collect in CLI order and
  // zip into export pairs. Tolerance flags bind to the most recent pair, or
  // set the run defaults when they appear before any pair.
  const args = {};
  const formats = [];
  const outs = [];
  const pairTolerances = [];
  const defaults = { chord: undefined, angle: undefined };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const next = argv[index + 1];
    const value = next === undefined || next.startsWith("--") ? "true" : next;
    if (value !== "true") index += 1;
    if (token === "--format") {
      formats.push(value);
      pairTolerances.push({ chord: undefined, angle: undefined });
    } else if (token === "--out") {
      outs.push(value);
    } else if (token === "--chord-tolerance") {
      (pairTolerances.length ? pairTolerances[pairTolerances.length - 1] : defaults).chord = value;
    } else if (token === "--angle-tolerance") {
      (pairTolerances.length ? pairTolerances[pairTolerances.length - 1] : defaults).angle = value;
    } else if (token === "--pose-deltas") {
      // Per-pair export-at-pose deltas (JSON: {occurrenceId: flat-16 delta});
      // binds to the most recent --format/--out pair only — a pose is a
      // property of ONE declared output, never a run default.
      if (!pairTolerances.length) {
        throw new Error("--pose-deltas must follow a --format/--out pair");
      }
      pairTolerances[pairTolerances.length - 1].pose = value;
    } else {
      args[token.slice(2)] = value;
    }
  }
  return { args, formats, outs, pairTolerances, defaults };
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

const { args, formats, outs, pairTolerances, defaults } = parseArgs(process.argv.slice(2));
const packageDir = String(args["package-dir"] || "");
if (!packageDir || !path.isAbsolute(packageDir)) {
  fail("--package-dir must be an absolute render-package directory");
}
if (!formats.length || formats.length !== outs.length) {
  fail("--format and --out must be given as one or more ordered pairs");
}
const jobs = formats.map((rawFormat, index) => {
  const chord = pairTolerances[index].chord ?? defaults.chord;
  const angle = pairTolerances[index].angle ?? defaults.angle;
  const options = { ...DEFAULT_OPTIONS };
  if (chord !== undefined) options.chordTolerance = Number(chord);
  if (angle !== undefined) options.angleTolerance = Number(angle);
  let poseDeltas = null;
  if (pairTolerances[index].pose !== undefined) {
    poseDeltas = JSON.parse(String(pairTolerances[index].pose));
  }
  return {
    format: String(rawFormat).toLowerCase(),
    out: String(outs[index]),
    options,
    poseDeltas,
    // Tessellation-group identity: jobs sharing an effective pair share one
    // tessellation of the package (a pose only re-places occurrences, so it
    // shares its pair's tessellation and differs only at primitive build).
    groupKey: `${options.chordTolerance}:${options.angleTolerance}`,
    poseKey: poseDeltas ? JSON.stringify(poseDeltas) : "",
  };
});
for (const job of jobs) {
  if (!job.out || !path.isAbsolute(job.out)) {
    fail("--out must be an absolute output path");
  }
  if (!PACKAGE_MESH_EXPORT_FORMATS.includes(job.format)) {
    fail(`--format must be one of ${PACKAGE_MESH_EXPORT_FORMATS.join(", ")}`);
  }
  if (!(job.options.chordTolerance > 0) || !(job.options.angleTolerance > 0)) {
    fail("tolerances must be positive numbers");
  }
}
if (new Set(jobs.map((job) => job.out)).size !== jobs.length) {
  fail("--out paths must be distinct");
}
const name = String(args.name || path.basename(jobs[0].out).replace(/\.[^.]+$/, "") || "model");
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
  const groups = new Map();
  jobs.forEach((job, index) => {
    if (!groups.has(job.groupKey)) groups.set(job.groupKey, { options: job.options, members: [] });
    groups.get(job.groupKey).members.push({ job, index });
  });
  const files = [];
  for (const group of groups.values()) {
    const tessellations = new Map();
    for (const cid of used) {
      if (!componentEntries[cid]) throw new Error(`descriptor names unknown component ${cid}`);
      tessellations.set(
        cid,
        tessellationForComponent(packageDir, cid, componentEntries[cid], group.options),
      );
    }
    // Primitives are per (tolerance group x pose): unposed jobs share one
    // build, each distinct pose re-places the same tessellation.
    const meshByPose = new Map();
    for (const { job, index } of group.members) {
      let mesh = meshByPose.get(job.poseKey);
      if (!mesh) {
        mesh = buildPackageMeshPrimitives(descriptor, tessellations, {
          ...(defaultColor ? { defaultColor: defaultColor.toLowerCase() } : {}),
          ...(job.poseDeltas ? { poseDeltas: job.poseDeltas } : {}),
        });
        if (!mesh.triangleCount) throw new Error("package produced no triangles");
        meshByPose.set(job.poseKey, mesh);
      }
      const { body } = packageMeshToFormat(mesh, job.format, { name });
      fs.mkdirSync(path.dirname(job.out), { recursive: true });
      const temp = `${job.out}.${process.pid}.tmp`;
      fs.writeFileSync(temp, body);
      fs.renameSync(temp, job.out);
      files[index] = { path: job.out, format: job.format, triangleCount: mesh.triangleCount };
    }
  }
  process.stdout.write(`${JSON.stringify({ ok: true, files })}\n`);
} catch (error) {
  fail(error?.message || error);
}
