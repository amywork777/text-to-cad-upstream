#!/usr/bin/env node
// Cross-implementation surf comparison: the conformance suite's geometric half.
//
//   node compareSurf.mjs --a <native.surf> --b <twin.surf>
//
// Loads both containers and compares them with ONE evaluator (the cadjs client
// evaluator — the code that actually renders): structure must match exactly
// (counts, ordinals, kinds, classification, loop shape), geometry must match
// within tolerance (surfaces sampled on a UV grid inside each face, pcurves
// and 3D curves sampled along their ranges, metrics compared relatively).
// Prints one JSON line: {"ok":true,...stats} or {"ok":false,"problems":[...]}.
import fs from "node:fs";

import { parseSurf, floatSpan } from "../../packages/cadjs/src/lib/surf/container.js";
import {
  evaluateSurface,
  evaluatePCurve,
  evaluateCurve3,
} from "../../packages/cadjs/src/lib/surf/evaluate.js";

const GRID = 7;
const CURVE_SAMPLES = 9;
const POINT_TOLERANCE_MM = 2e-3;
const METRIC_REL_TOLERANCE = 1e-4;
const DIHEDRAL_TOLERANCE_DEG = 0.75;

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index].startsWith("--")) {
      args[argv[index].slice(2)] = argv[index + 1];
      index += 1;
    }
  }
  return args;
}

function load(pathname) {
  const buffer = fs.readFileSync(pathname);
  return parseSurf(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
}

function relClose(a, b, tolerance = METRIC_REL_TOLERANCE) {
  if (a == null || b == null) {
    return a == null && b == null;
  }
  const scale = Math.max(Math.abs(a), Math.abs(b), 1e-9);
  return Math.abs(a - b) / scale <= tolerance;
}

function pointDelta(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

const problems = [];
const stats = { faces: 0, surfacePointMax: 0, pcurvePointMax: 0, curvePointMax: 0 };

function problem(text) {
  if (problems.length < 40) {
    problems.push(text);
  }
}

const args = parseArgs(process.argv.slice(2));
const a = load(args.a);
const b = load(args.b);

// --- structure ---
if (a.index.counts.faces !== b.index.counts.faces || a.index.counts.edges !== b.index.counts.edges) {
  problem(`counts differ: a=${JSON.stringify(a.index.counts)} b=${JSON.stringify(b.index.counts)}`);
}
const shapesA = a.index.shapes.map((s) => `${s.ord}:${s.kind}`).join(",");
const shapesB = b.index.shapes.map((s) => `${s.ord}:${s.kind}`).join(",");
if (shapesA !== shapesB) {
  problem(`shape decomposition differs: a=[${shapesA}] b=[${shapesB}]`);
}

const faceCount = Math.min(a.index.faces.length, b.index.faces.length);
for (let i = 0; i < faceCount; i += 1) {
  const fa = a.index.faces[i];
  const fb = b.index.faces[i];
  const tag = `face ${fa.ord}`;
  if (fa.ord !== fb.ord || fa.surfaceType !== fb.surfaceType || fa.reversed !== fb.reversed || fa.shape !== fb.shape) {
    problem(`${tag}: identity differs (${fa.ord}/${fa.surfaceType}/${fa.reversed}/${fa.shape} vs ${fb.ord}/${fb.surfaceType}/${fb.reversed}/${fb.shape})`);
    continue;
  }
  if (!relClose(fa.area, fb.area)) {
    problem(`${tag}: area ${fa.area} vs ${fb.area}`);
  }
  if (fa.loops.length !== fb.loops.length) {
    problem(`${tag}: loop count ${fa.loops.length} vs ${fb.loops.length}`);
  } else {
    for (let l = 0; l < fa.loops.length; l += 1) {
      const ea = fa.loops[l].map((p) => `${p.edgeOrd}${p.reversed ? "r" : ""}`).join(">");
      const eb = fb.loops[l].map((p) => `${p.edgeOrd}${p.reversed ? "r" : ""}`).join(">");
      if (ea !== eb) {
        problem(`${tag} loop ${l}: edge sequence ${ea} vs ${eb}`);
      }
    }
  }
  // Surface geometry: sample both on the SAME uv grid (face a's uv box —
  // the two must agree on parametrization, which is the contract).
  const [u0a, u1a, v0a, v1a] = fa.uv;
  const [u0b, u1b, v0b, v1b] = fb.uv;
  if (!relClose(u0a, u0b, 1e-6) || !relClose(u1a, u1b, 1e-6) || !relClose(v0a, v0b, 1e-6) || !relClose(v1a, v1b, 1e-6)) {
    problem(`${tag}: uv box differs ${JSON.stringify(fa.uv)} vs ${JSON.stringify(fb.uv)}`);
  }
  let faceMax = 0;
  for (let gu = 0; gu <= GRID; gu += 1) {
    for (let gv = 0; gv <= GRID; gv += 1) {
      const u = u0a + ((u1a - u0a) * gu) / GRID;
      const v = v0a + ((v1a - v0a) * gv) / GRID;
      const pa = evaluateSurface(fa.surface, a.floats, u, v);
      const pb = evaluateSurface(fb.surface, b.floats, u, v);
      if (!pa || !pb) {
        problem(`${tag}: surface evaluation failed at (${u}, ${v})`);
        gu = GRID + 1;
        break;
      }
      faceMax = Math.max(faceMax, pointDelta(pa, pb));
    }
  }
  if (faceMax > POINT_TOLERANCE_MM) {
    problem(`${tag} (${fa.surfaceType}): surface deviation ${faceMax.toFixed(6)}mm`);
  }
  stats.surfacePointMax = Math.max(stats.surfacePointMax, faceMax);
  // Pcurves: sample each loop pcurve over its range in both containers.
  for (let l = 0; l < Math.min(fa.loops.length, fb.loops.length); l += 1) {
    for (let e = 0; e < Math.min(fa.loops[l].length, fb.loops[l].length); e += 1) {
      const pa = fa.loops[l][e];
      const pb = fb.loops[l][e];
      let maxDelta = 0;
      for (let siter = 0; siter <= CURVE_SAMPLES; siter += 1) {
        const ta = pa.range[0] + ((pa.range[1] - pa.range[0]) * siter) / CURVE_SAMPLES;
        const tb = pb.range[0] + ((pb.range[1] - pb.range[0]) * siter) / CURVE_SAMPLES;
        const uva = evaluatePCurve(pa, a.floats, ta);
        const uvb = evaluatePCurve(pb, b.floats, tb);
        if (!uva || !uvb) {
          problem(`${tag} loop ${l} pcurve ${e}: evaluation failed`);
          break;
        }
        // Compare in 3D THROUGH the surface: pcurve parametrizations may
        // legitimately differ (arc-length vs angle), the trim they cut must not.
        const p3a = evaluateSurface(fa.surface, a.floats, uva[0], uva[1]);
        const p3b = evaluateSurface(fb.surface, b.floats, uvb[0], uvb[1]);
        if (p3a && p3b) {
          maxDelta = Math.max(maxDelta, pointDelta(p3a, p3b));
        }
      }
      if (maxDelta > POINT_TOLERANCE_MM) {
        problem(`${tag} loop ${l} pcurve ${e}: trim deviation ${maxDelta.toFixed(6)}mm`);
      }
      stats.pcurvePointMax = Math.max(stats.pcurvePointMax, maxDelta);
    }
  }
  stats.faces += 1;
}

// --- edges ---
const edgeCount = Math.min(a.index.edges.length, b.index.edges.length);
for (let i = 0; i < edgeCount; i += 1) {
  const ea = a.index.edges[i];
  const eb = b.index.edges[i];
  const tag = `edge ${ea.ord}`;
  if (ea.ord !== eb.ord || ea.class !== eb.class || ea.continuity !== eb.continuity
      || ea.flags !== eb.flags || ea.adjacentFaceCount !== eb.adjacentFaceCount
      || ea.curveType !== eb.curveType || ea.shape !== eb.shape) {
    problem(`${tag}: classification differs `
      + `(${ea.class}/${ea.continuity}/${ea.flags}/${ea.adjacentFaceCount}/${ea.curveType}`
      + ` vs ${eb.class}/${eb.continuity}/${eb.flags}/${eb.adjacentFaceCount}/${eb.curveType})`);
    continue;
  }
  if (JSON.stringify(ea.faceOrds) !== JSON.stringify(eb.faceOrds)) {
    problem(`${tag}: faceOrds ${JSON.stringify(ea.faceOrds)} vs ${JSON.stringify(eb.faceOrds)}`);
  }
  if (!relClose(ea.length, eb.length)) {
    problem(`${tag}: length ${ea.length} vs ${eb.length}`);
  }
  if (ea.dihedralDeg != null && eb.dihedralDeg != null
      && Math.abs(ea.dihedralDeg - eb.dihedralDeg) > DIHEDRAL_TOLERANCE_DEG) {
    problem(`${tag}: dihedral ${ea.dihedralDeg} vs ${eb.dihedralDeg}`);
  }
  if ((ea.curve == null) !== (eb.curve == null)) {
    problem(`${tag}: 3d curve presence differs`);
    continue;
  }
  if (ea.curve && eb.curve) {
    let maxDelta = 0;
    for (let siter = 0; siter <= CURVE_SAMPLES; siter += 1) {
      const ta = ea.curve.range[0] + ((ea.curve.range[1] - ea.curve.range[0]) * siter) / CURVE_SAMPLES;
      const tb = eb.curve.range[0] + ((eb.curve.range[1] - eb.curve.range[0]) * siter) / CURVE_SAMPLES;
      const pa = evaluateCurve3(ea.curve, a.floats, ta);
      const pb = evaluateCurve3(eb.curve, b.floats, tb);
      if (!pa || !pb) {
        problem(`${tag}: 3d curve evaluation failed`);
        break;
      }
      maxDelta = Math.max(maxDelta, pointDelta(pa, pb));
    }
    if (maxDelta > POINT_TOLERANCE_MM) {
      problem(`${tag} (${ea.curveType}): 3d curve deviation ${maxDelta.toFixed(6)}mm`);
    }
    stats.curvePointMax = Math.max(stats.curvePointMax, maxDelta);
  }
}

process.stdout.write(`${JSON.stringify(problems.length ? { ok: false, problems, stats } : { ok: true, ...stats })}\n`);
process.exit(problems.length ? 1 : 0);
