// SURF tessellation (design/surface-rendering.md R2).
//
// Faces triangulate in UV space: trim loops are sampled adaptively from
// their exact pcurves, earcut triangulates the outer loop with holes
// (boundary-exact — no trim masks, no cracks along trims), then triangles
// refine by edge splitting wherever the 3D chord deviates from the true
// surface. Midpoints are cached per edge so refinement is crack-free.
// Every UV vertex introduced by refinement lies inside an earcut triangle
// and therefore inside the face, so no inside/outside testing is needed
// after the initial triangulation.
//
// Edge curves polyline the same way (adaptive chordal sampling of the
// exact 3D curve). All hot loops stay allocation-light and portable to
// WGSL compute later; the contract here is correctness first.

import { ShapeUtils, Vector2 } from "three";

import { evaluateCurve3, evaluatePCurve, evaluateSurface, evaluateSurfaceNormal } from "./evaluate.js";

const DEFAULT_OPTIONS = {
  // Max 3D distance between the surface and a triangle edge midpoint,
  // relative to the component diagonal.
  chordTolerance: 1.5e-3,
  // Pcurve sampling: max 3D deviation of a loop segment, same scale.
  loopTolerance: 5e-4,
  // Max normal spread across one triangle edge (radians). Bounds facet
  // tilt — chord criteria alone admit Schwarz-lantern triangles whose
  // vertices sit on the surface while the facet cuts across it.
  angleTolerance: 0.45,
  maxRefineDepth: 7,
  minLoopSegments: 8,
};

function sub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function length3(a) {
  return Math.hypot(a[0], a[1], a[2]);
}

// --- Loop sampling -----------------------------------------------------------

function sampleLoopPolygon(face, loop, floats, tolerance) {
  // points[i] -> points[i+1] lies on the model edge segmentOrds[i].
  const points = [];
  const segmentOrds = [];
  for (const pcurve of loop) {
    const forward = !pcurve.reversed;
    const segment = samplePCurveAdaptive(face, pcurve, floats, tolerance);
    if (!forward) segment.reverse();
    // Drop each segment's last point; the next pcurve supplies it.
    for (let i = 0; i < segment.length - 1; i += 1) {
      points.push(segment[i]);
      segmentOrds.push(pcurve.edgeOrd || 0);
    }
  }
  points.segmentOrds = segmentOrds;
  return points;
}

function samplePCurveAdaptive(face, pcurve, floats, tolerance) {
  const [t0, t1] = pcurve.range;
  const surface = face.surface;
  const initial = Math.max(2, DEFAULT_OPTIONS.minLoopSegments, pcurve.n ?? 2);
  const params = [];
  for (let i = 0; i <= initial; i += 1) params.push(t0 + ((t1 - t0) * i) / initial);

  const uvOf = (t) => evaluatePCurve(pcurve, floats, t);
  const xyzOf = (uv) => evaluateSurface(surface, floats, uv[0], uv[1]);

  // Refine parameter intervals until the 3D midpoint deviation is small.
  let depth = 0;
  while (depth < DEFAULT_OPTIONS.maxRefineDepth) {
    let split = false;
    const next = [params[0]];
    for (let i = 0; i + 1 < params.length; i += 1) {
      const a = params[i];
      const b = params[i + 1];
      const mid = (a + b) / 2;
      const pa = xyzOf(uvOf(a));
      const pb = xyzOf(uvOf(b));
      const pm = xyzOf(uvOf(mid));
      const chordMid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2];
      if (length3(sub(pm, chordMid)) > tolerance) {
        next.push(mid);
        split = true;
      }
      next.push(b);
    }
    params.length = 0;
    params.push(...next);
    if (!split) break;
    depth += 1;
  }
  return params.map(uvOf);
}

// --- Face triangulation ------------------------------------------------------

function polygonArea(points) {
  let area = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[(i + 1) % points.length];
    area += x0 * y1 - x1 * y0;
  }
  return area / 2;
}

// --- Grid triangulation ------------------------------------------------------

function gridStepsForDirection(face, floats, uvBox, chordLimit, direction) {
  const [u0, u1, v0, v1] = uvBox;
  const span = direction === 0 ? u1 - u0 : v1 - v0;
  if (span <= 0) return 1;
  const PROBES = 4;
  let worst = 0;
  for (let line = 0; line <= PROBES; line += 1) {
    const across =
      direction === 0
        ? v0 + ((v1 - v0) * line) / PROBES
        : u0 + ((u1 - u0) * line) / PROBES;
    for (let i = 0; i < PROBES; i += 1) {
      const t0 = (direction === 0 ? u0 : v0) + (span * i) / PROBES;
      const t1 = t0 + span / PROBES;
      const tm = (t0 + t1) / 2;
      const at = (t) =>
        direction === 0
          ? evaluateSurface(face.surface, floats, t, across)
          : evaluateSurface(face.surface, floats, across, t);
      const pa = at(t0);
      const pb = at(t1);
      const pm = at(tm);
      const chordMid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2];
      worst = Math.max(worst, length3(sub(pm, chordMid)));
    }
  }
  if (worst <= chordLimit) return 1;
  // Chord error scales ~h^2: required steps per probe interval.
  const perInterval = Math.sqrt(worst / chordLimit);
  return Math.min(256, Math.max(1, Math.ceil(PROBES * perInterval)));
}

function pointInLoopsEvenOdd(loops, u, v) {
  let inside = false;
  for (const points of loops) {
    for (let i = 0; i < points.length; i += 1) {
      const [x0, y0] = points[i];
      const [x1, y1] = points[(i + 1) % points.length];
      if (y0 > v !== y1 > v && u < ((x1 - x0) * (v - y0)) / (y1 - y0) + x0) {
        inside = !inside;
      }
    }
  }
  return inside;
}

// Sutherland–Hodgman against an axis-aligned rectangle.
function clipPolygonToCell(points, cu0, cu1, cv0, cv1) {
  let output = points;
  for (const [axis, bound, keepBelow] of [
    [0, cu0, false],
    [0, cu1, true],
    [1, cv0, false],
    [1, cv1, true],
  ]) {
    const input = output;
    output = [];
    for (let i = 0; i < input.length; i += 1) {
      const current = input[i];
      const previous = input[(i + input.length - 1) % input.length];
      const currentIn = keepBelow ? current[axis] <= bound : current[axis] >= bound;
      const previousIn = keepBelow ? previous[axis] <= bound : previous[axis] >= bound;
      if (currentIn !== previousIn) {
        const t = (bound - previous[axis]) / (current[axis] - previous[axis]);
        output.push([
          previous[0] + t * (current[0] - previous[0]),
          previous[1] + t * (current[1] - previous[1]),
        ]);
      }
      if (currentIn) output.push(current);
    }
    if (output.length < 3) return [];
  }
  return output;
}

function gridTriangulate(face, floats, loops, chordLimit) {
  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (const points of loops) {
    for (const [u, v] of points) {
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
  }
  if (!(maxU > minU) || !(maxV > minV)) return null;
  const uvBox = [minU, maxU, minV, maxV];
  const stepsU = gridStepsForDirection(face, floats, uvBox, chordLimit, 0);
  const stepsV = gridStepsForDirection(face, floats, uvBox, chordLimit, 1);
  const du = (maxU - minU) / stepsU;
  const dv = (maxV - minV) / stepsV;

  // Bucket loop segments by the cells their bounding boxes touch. The same
  // buckets serve two consumers: boundary-cell detection here, and model-
  // edge attribution of region-boundary mesh edges afterwards.
  const cellOf = (u, v) => [
    Math.min(stepsU - 1, Math.max(0, Math.floor((u - minU) / du))),
    Math.min(stepsV - 1, Math.max(0, Math.floor((v - minV) / dv))),
  ];
  const crossed = new Set();
  const segments = [];
  const segmentsByCell = new Map();
  for (const points of loops) {
    const ords = points.segmentOrds || [];
    for (let i = 0; i < points.length; i += 1) {
      const [x0, y0] = points[i];
      const [x1, y1] = points[(i + 1) % points.length];
      const segIndex = segments.length;
      segments.push([x0, y0, x1, y1, ords[i] || 0]);
      const [ca0, cb0] = cellOf(Math.min(x0, x1), Math.min(y0, y1));
      const [ca1, cb1] = cellOf(Math.max(x0, x1), Math.max(y0, y1));
      for (let cu = ca0; cu <= ca1; cu += 1) {
        for (let cv = cb0; cv <= cb1; cv += 1) {
          const key = cu * stepsV + cv;
          crossed.add(key);
          let list = segmentsByCell.get(key);
          if (!list) segmentsByCell.set(key, (list = []));
          list.push(segIndex);
        }
      }
    }
  }

  const uvVerts = [];
  const vertexIds = new Map();
  const vertexId = (u, v) => {
    const key = `${u}:${v}`;
    let id = vertexIds.get(key);
    if (id === undefined) {
      id = uvVerts.length;
      uvVerts.push([u, v]);
      vertexIds.set(key, id);
    }
    return id;
  };

  const triangles = [];
  const degenerateLimit = Math.abs((maxU - minU) * (maxV - minV)) * 1e-12 || 1e-30;
  // Canonical grid-line coordinates: adjacent cells MUST address their shared
  // border with bitwise-identical floats, or vertex dedup misses and every
  // cell border becomes an unmerged crack (visible as hairline banding).
  const gridU = [];
  const gridV = [];
  for (let iu = 0; iu <= stepsU; iu += 1) gridU.push(iu === stepsU ? maxU : minU + iu * du);
  for (let iv = 0; iv <= stepsV; iv += 1) gridV.push(iv === stepsV ? maxV : minV + iv * dv);
  for (let iu = 0; iu < stepsU; iu += 1) {
    for (let iv = 0; iv < stepsV; iv += 1) {
      const cu0 = gridU[iu];
      const cu1 = gridU[iu + 1];
      const cv0 = gridV[iv];
      const cv1 = gridV[iv + 1];
      if (!crossed.has(iu * stepsV + iv)) {
        // Uncrossed cell: uniformly inside or outside; test the center.
        if (!pointInLoopsEvenOdd(loops, (cu0 + cu1) / 2, (cv0 + cv1) / 2)) continue;
        const a = vertexId(cu0, cv0);
        const b = vertexId(cu1, cv0);
        const c = vertexId(cu1, cv1);
        const d = vertexId(cu0, cv1);
        triangles.push(a, b, c, a, c, d);
        continue;
      }
      // Boundary cell: clip every loop to the cell, then earcut the piece.
      const clipped = loops
        .map((points) => clipPolygonToCell(points, cu0, cu1, cv0, cv1))
        .filter((points) => points.length >= 3);
      if (!clipped.length) continue;
      let outerIndex = 0;
      let outerAbsArea = 0;
      for (let i = 0; i < clipped.length; i += 1) {
        const absArea = Math.abs(polygonArea(clipped[i]));
        if (absArea > outerAbsArea) {
          outerAbsArea = absArea;
          outerIndex = i;
        }
      }
      if (outerAbsArea <= degenerateLimit) continue;
      const contour = clipped[outerIndex].map(([x, y]) => new Vector2(x, y));
      const holes = clipped
        .filter((_, i) => i !== outerIndex)
        .map((points) => points.map(([x, y]) => new Vector2(x, y)));
      let cellFaces;
      try {
        cellFaces = ShapeUtils.triangulateShape(contour, holes);
      } catch {
        continue;
      }
      const localPoints = [...contour, ...holes.flat()];
      const localIds = localPoints.map(({ x, y }) => vertexId(x, y));
      for (const [a, b, c] of cellFaces) {
        const A = localPoints[a];
        const B = localPoints[b];
        const C = localPoints[c];
        const cross = (B.x - A.x) * (C.y - A.y) - (C.x - A.x) * (B.y - A.y);
        if (Math.abs(cross) / 2 > degenerateLimit) {
          triangles.push(localIds[a], localIds[b], localIds[c]);
        }
      }
    }
  }
  return {
    uvVerts,
    triangles,
    segmentIndex: { segments, segmentsByCell, cellOf, stepsV },
  };
}

function pointToSegmentDistanceSq(px, py, x0, y0, x1, y1) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const lengthSq = dx * dx + dy * dy;
  let t = lengthSq > 0 ? ((px - x0) * dx + (py - y0) * dy) / lengthSq : 0;
  t = Math.max(0, Math.min(1, t));
  const qx = x0 + t * dx;
  const qy = y0 + t * dy;
  return (px - qx) * (px - qx) + (py - qy) * (py - qy);
}

// Per-triangle model-edge ordinals for the barycentric edge overlay, in the
// GLB half-edge convention: side 0 = (v1,v2), side 1 = (v2,v0),
// side 2 = (v0,v1). A mesh edge belongs to a model edge when it appears in
// exactly one triangle (region boundary — interior edges are shared by two)
// and both endpoints lie on one sampled trim segment, whose ordinal it
// inherits. Clip intersections and refinement midpoints stay on their
// segment, so containment is exact up to float noise.
function attributeBoundaryEdges(triangles, uvVerts, segmentIndex, epsilon) {
  const counts = new Map();
  const keyOf = (a, b) => (a < b ? a * 0x100000000 + b : b * 0x100000000 + a);
  for (let t = 0; t < triangles.length; t += 3) {
    const [a, b, c] = [triangles[t], triangles[t + 1], triangles[t + 2]];
    for (const [p, q] of [[a, b], [b, c], [c, a]]) {
      const key = keyOf(p, q);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  const { segments, segmentsByCell, cellOf, stepsV } = segmentIndex;
  const epsilonSq = epsilon * epsilon;
  const ordCache = new Map();
  const ordOfMeshEdge = (p, q) => {
    const key = keyOf(p, q);
    if (counts.get(key) !== 1) return 0;
    let ord = ordCache.get(key);
    if (ord !== undefined) return ord;
    ord = 0;
    const [pu, pv] = uvVerts[p];
    const [qu, qv] = uvVerts[q];
    const [cu, cv] = cellOf((pu + qu) / 2, (pv + qv) / 2);
    const candidates = segmentsByCell.get(cu * stepsV + cv) || [];
    for (const segIdx of candidates) {
      const [x0, y0, x1, y1, segOrd] = segments[segIdx];
      if (!segOrd) continue;
      if (
        pointToSegmentDistanceSq(pu, pv, x0, y0, x1, y1) < epsilonSq &&
        pointToSegmentDistanceSq(qu, qv, x0, y0, x1, y1) < epsilonSq
      ) {
        ord = segOrd;
        break;
      }
    }
    ordCache.set(key, ord);
    return ord;
  };
  const sideOrds = new Uint32Array(triangles.length);
  for (let t = 0; t < triangles.length; t += 3) {
    const [a, b, c] = [triangles[t], triangles[t + 1], triangles[t + 2]];
    sideOrds[t] = ordOfMeshEdge(b, c);
    sideOrds[t + 1] = ordOfMeshEdge(c, a);
    sideOrds[t + 2] = ordOfMeshEdge(a, b);
  }
  return sideOrds;
}

export function tessellateFace(face, floats, scale, options = {}) {
  const { chordTolerance, loopTolerance, angleTolerance, maxRefineDepth } = {
    ...DEFAULT_OPTIONS,
    ...options,
  };
  // Tolerances scale by the FACE's own extent (min of face and component
  // scale): small curved features refine properly instead of inheriting a
  // large component's coarse budget.
  const roughLimit = loopTolerance * scale;
  const loops0 = face.loops
    .map((loop) => sampleLoopPolygon(face, loop, floats, roughLimit))
    .filter((points) => points.length >= 3);
  if (!loops0.length) return null;
  let faceScale = 0;
  {
    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (const points of loops0) {
      for (const [u, v] of points) {
        if (u < minU) minU = u;
        if (u > maxU) maxU = u;
        if (v < minV) minV = v;
        if (v > maxV) maxV = v;
      }
    }
    // Probe the 3D extent from UV box corners + center.
    const probes = [
      [minU, minV],
      [maxU, minV],
      [minU, maxV],
      [maxU, maxV],
      [(minU + maxU) / 2, (minV + maxV) / 2],
    ].map(([u, v]) => evaluateSurface(face.surface, floats, u, v));
    for (let i = 0; i < probes.length; i += 1) {
      for (let j = i + 1; j < probes.length; j += 1) {
        faceScale = Math.max(faceScale, length3(sub(probes[i], probes[j])));
      }
    }
  }
  const local = Math.max(Math.min(scale, faceScale * 4), 1e-9);
  const chordLimit = chordTolerance * local;
  const loopLimit = loopTolerance * local;

  const loops =
    loopLimit < roughLimit
      ? face.loops
          .map((loop) => sampleLoopPolygon(face, loop, floats, loopLimit))
          .filter((points) => points.length >= 3)
      : loops0;
  if (!loops.length) return null;

  // Base triangulation: a curvature-driven UV grid, with trim loops clipped
  // per cell. Interior cells emit two well-shaped triangles; boundary cells
  // triangulate their clipped polygon with earcut. This is boundary-exact
  // like a global earcut but never produces the long fans and caps that
  // made global earcut meshes fat on curved faces (Schwarz-lantern effect).
  const built = gridTriangulate(face, floats, loops, chordLimit);
  if (!built) return null;
  const { uvVerts, triangles: baseTriangles, segmentIndex } = built;
  let triangles = baseTriangles;
  if (!triangles.length) return null;

  // Crack-free refinement, two-phase per round so neighbours stay
  // conforming: (1) MARK edges — an edge splits when its 3D midpoint
  // chord error exceeds tolerance, and a triangle whose CENTROID deviates
  // from the surface (the earcut-sliver failure mode: short edges, curved
  // interior) marks its longest edge; (2) SUBDIVIDE every triangle by its
  // marked edges, materializing midpoints through a shared cache.
  const xyz = uvVerts.map(([u, v]) => evaluateSurface(face.surface, floats, u, v));
  const vertexNormal = ([u, v]) =>
    evaluateSurfaceNormal(face.surface, floats, u, v, face.uv, false);
  const nrm = uvVerts.map(vertexNormal);
  const angleCos = Math.cos(angleTolerance);
  const edgeKey = (a, b) => (a < b ? `${a}_${b}` : `${b}_${a}`);
  for (let depth = 0; depth < maxRefineDepth; depth += 1) {
    const marked = new Set();
    const chordChecked = new Map();
    const edgeChordBad = (a, b) => {
      const key = edgeKey(a, b);
      let bad = chordChecked.get(key);
      if (bad === undefined) {
        const mu = (uvVerts[a][0] + uvVerts[b][0]) / 2;
        const mv = (uvVerts[a][1] + uvVerts[b][1]) / 2;
        const surfaceMid = evaluateSurface(face.surface, floats, mu, mv);
        const chordMid = [
          (xyz[a][0] + xyz[b][0]) / 2,
          (xyz[a][1] + xyz[b][1]) / 2,
          (xyz[a][2] + xyz[b][2]) / 2,
        ];
        bad =
          length3(sub(surfaceMid, chordMid)) > chordLimit ||
          nrm[a][0] * nrm[b][0] + nrm[a][1] * nrm[b][1] + nrm[a][2] * nrm[b][2] < angleCos;
        chordChecked.set(key, bad);
      }
      return bad;
    };
    for (let t = 0; t < triangles.length; t += 3) {
      const a = triangles[t];
      const b = triangles[t + 1];
      const c = triangles[t + 2];
      let anyEdge = false;
      for (const [p, q] of [[a, b], [b, c], [c, a]]) {
        if (edgeChordBad(p, q)) {
          marked.add(edgeKey(p, q));
          anyEdge = true;
        }
      }
      if (anyEdge) continue;
      const cu = (uvVerts[a][0] + uvVerts[b][0] + uvVerts[c][0]) / 3;
      const cv = (uvVerts[a][1] + uvVerts[b][1] + uvVerts[c][1]) / 3;
      const surfaceCentroid = evaluateSurface(face.surface, floats, cu, cv);
      const flatCentroid = [
        (xyz[a][0] + xyz[b][0] + xyz[c][0]) / 3,
        (xyz[a][1] + xyz[b][1] + xyz[c][1]) / 3,
        (xyz[a][2] + xyz[b][2] + xyz[c][2]) / 3,
      ];
      // Cap detection: a triangle of near-collinear UV points bridges the
      // surface as a chord-vs-arc cap — its FACET normal swings away from
      // the surface normal even though every vertex (and its centroid, and
      // its edge midpoints) sits close to the surface.
      const e1 = sub(xyz[b], xyz[a]);
      const e2 = sub(xyz[c], xyz[a]);
      const facet = [
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
      ];
      const facetLength = length3(facet);
      const surfaceNormal = nrm[a];
      const misaligned =
        facetLength > 1e-30 &&
        Math.abs(
          (facet[0] * surfaceNormal[0] + facet[1] * surfaceNormal[1] + facet[2] * surfaceNormal[2]) /
            facetLength,
        ) < angleCos;
      if (misaligned || length3(sub(surfaceCentroid, flatCentroid)) > chordLimit) {
        let longest = [a, b];
        let longestSq = -1;
        for (const [p, q] of [[a, b], [b, c], [c, a]]) {
          const du = uvVerts[p][0] - uvVerts[q][0];
          const dv = uvVerts[p][1] - uvVerts[q][1];
          const sq = du * du + dv * dv;
          if (sq > longestSq) {
            longestSq = sq;
            longest = [p, q];
          }
        }
        marked.add(edgeKey(longest[0], longest[1]));
      }
    }
    if (!marked.size) break;

    const midCache = new Map();
    const midpointOf = (a, b) => {
      const key = edgeKey(a, b);
      if (!marked.has(key)) return -1;
      let midIndex = midCache.get(key);
      if (midIndex === undefined) {
        const mu = (uvVerts[a][0] + uvVerts[b][0]) / 2;
        const mv = (uvVerts[a][1] + uvVerts[b][1]) / 2;
        midIndex = uvVerts.length;
        uvVerts.push([mu, mv]);
        xyz.push(evaluateSurface(face.surface, floats, mu, mv));
        nrm.push(vertexNormal([mu, mv]));
        midCache.set(key, midIndex);
      }
      return midIndex;
    };

    const next = [];
    for (let t = 0; t < triangles.length; t += 3) {
      const a = triangles[t];
      const b = triangles[t + 1];
      const c = triangles[t + 2];
      const mab = midpointOf(a, b);
      const mbc = midpointOf(b, c);
      const mca = midpointOf(c, a);
      const splits = (mab >= 0) + (mbc >= 0) + (mca >= 0);
      if (splits === 0) {
        next.push(a, b, c);
        continue;
      }
      if (splits === 3) {
        next.push(a, mab, mca, mab, b, mbc, mca, mbc, c, mab, mbc, mca);
      } else if (splits === 2) {
        // Rotate so the un-split edge is (c, a).
        let [va, vb, vc, m1, m2] =
          mab >= 0 && mbc >= 0
            ? [a, b, c, mab, mbc]
            : mbc >= 0 && mca >= 0
              ? [b, c, a, mbc, mca]
              : [c, a, b, mca, mab];
        next.push(va, m1, m2, va, m2, vc, m1, vb, m2);
        void vb;
      } else {
        // Rotate so the split edge is (a, b).
        const [va, vb, vc, m] =
          mab >= 0 ? [a, b, c, mab] : mbc >= 0 ? [b, c, a, mbc] : [c, a, b, mca];
        next.push(va, m, vc, m, vb, vc);
      }
    }
    triangles = next;
  }

  const positions = new Float32Array(xyz.length * 3);
  const normals = new Float32Array(xyz.length * 3);
  const sign = face.reversed ? -1 : 1;
  for (let i = 0; i < xyz.length; i += 1) {
    positions.set(xyz[i], i * 3);
    normals[i * 3] = nrm[i][0] * sign;
    normals[i * 3 + 1] = nrm[i][1] * sign;
    normals[i * 3 + 2] = nrm[i][2] * sign;
  }
  const indices = face.reversed ? flipWinding(triangles) : Uint32Array.from(triangles);
  let spanU = 0;
  let spanV = 0;
  for (const [u, v] of uvVerts) {
    spanU = Math.max(spanU, Math.abs(u));
    spanV = Math.max(spanV, Math.abs(v));
  }
  const sideOrds = attributeBoundaryEdges(
    indices,
    uvVerts,
    segmentIndex,
    Math.max(spanU, spanV, 1) * 1e-7,
  );
  return {
    positions,
    normals,
    indices,
    sideOrds,
    uv: uvVerts,
  };
}

function flipWinding(triangles) {
  const flipped = new Uint32Array(triangles.length);
  for (let t = 0; t < triangles.length; t += 3) {
    flipped[t] = triangles[t];
    flipped[t + 1] = triangles[t + 2];
    flipped[t + 2] = triangles[t + 1];
  }
  return flipped;
}

// --- Edge polylines ----------------------------------------------------------

export function polylineEdge(curve, floats, scale, options = {}) {
  const { loopTolerance, maxRefineDepth } = { ...DEFAULT_OPTIONS, ...options };
  const tolerance = loopTolerance * scale;
  const [t0, t1] = curve.range;
  const params = [];
  const initial = Math.max(2, curve.n ?? 2, curve.kind === "line" ? 1 : 8);
  for (let i = 0; i <= initial; i += 1) params.push(t0 + ((t1 - t0) * i) / initial);
  let depth = 0;
  while (depth < maxRefineDepth) {
    let split = false;
    const next = [params[0]];
    for (let i = 0; i + 1 < params.length; i += 1) {
      const a = params[i];
      const b = params[i + 1];
      const mid = (a + b) / 2;
      const pa = evaluateCurve3(curve, floats, a);
      const pb = evaluateCurve3(curve, floats, b);
      const pm = evaluateCurve3(curve, floats, mid);
      const chordMid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2];
      if (length3(sub(pm, chordMid)) > tolerance) {
        next.push(mid);
        split = true;
      }
      next.push(b);
    }
    params.length = 0;
    params.push(...next);
    if (!split) break;
    depth += 1;
  }
  const polyline = new Float32Array(params.length * 3);
  for (let i = 0; i < params.length; i += 1) {
    polyline.set(evaluateCurve3(curve, floats, params[i]), i * 3);
  }
  return polyline;
}

// --- Component assembly ------------------------------------------------------

// Tessellate a full parsed SURF component. Returns merged buffers plus a
// per-vertex face ordinal channel (picking / selection tint) and per-class
// edge segment lists.
export function tessellateComponent(index, floats, options = {}) {
  // Component scale: bbox diagonal from a cheap pass over loop samples.
  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  const faceMeshes = [];
  let vertexTotal = 0;
  let indexTotal = 0;

  // First pass without scale to estimate bounds from loop polygons only.
  for (const face of index.faces) {
    for (const loop of face.loops) {
      for (const pcurve of loop) {
        for (const t of [pcurve.range[0], (pcurve.range[0] + pcurve.range[1]) / 2, pcurve.range[1]]) {
          const [u, v] = evaluatePCurve(pcurve, floats, t);
          const p = evaluateSurface(face.surface, floats, u, v);
          for (let d = 0; d < 3; d += 1) {
            if (p[d] < min[d]) min[d] = p[d];
            if (p[d] > max[d]) max[d] = p[d];
          }
        }
      }
    }
  }
  const scale = Math.max(length3(sub(max, min)), 1e-6);

  for (const face of index.faces) {
    const mesh = tessellateFace(face, floats, scale, options);
    if (!mesh) continue;
    faceMeshes.push({ ord: face.ord, color: face.color ?? null, mesh });
    vertexTotal += mesh.positions.length / 3;
    indexTotal += mesh.indices.length;
  }

  const positions = new Float32Array(vertexTotal * 3);
  const normals = new Float32Array(vertexTotal * 3);
  const faceOrds = new Float32Array(vertexTotal);
  const indices = new Uint32Array(indexTotal);
  const sideOrds = new Uint32Array(indexTotal);
  const faceRanges = [];
  let vertexOffset = 0;
  let indexOffset = 0;
  for (const { ord, color, mesh } of faceMeshes) {
    positions.set(mesh.positions, vertexOffset * 3);
    normals.set(mesh.normals, vertexOffset * 3);
    faceOrds.fill(ord, vertexOffset, vertexOffset + mesh.positions.length / 3);
    for (let i = 0; i < mesh.indices.length; i += 1) {
      indices[indexOffset + i] = mesh.indices[i] + vertexOffset;
    }
    if (mesh.sideOrds) sideOrds.set(mesh.sideOrds, indexOffset);
    faceRanges.push({ ord, color, indexStart: indexOffset, indexCount: mesh.indices.length });
    vertexOffset += mesh.positions.length / 3;
    indexOffset += mesh.indices.length;
  }

  // Bounds from the FINAL tessellated positions: the loop-sample estimate
  // above seeds tolerances but can clip extreme points, and camera auto-fit
  // is sensitive to the difference.
  min = [Infinity, Infinity, Infinity];
  max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let d = 0; d < 3; d += 1) {
      const value = positions[i + d];
      if (value < min[d]) min[d] = value;
      if (value > max[d]) max[d] = value;
    }
  }

  const edges = [];
  for (const edge of index.edges) {
    if (!edge.curve) continue;
    edges.push({
      ord: edge.ord,
      visibilityClass: edge.class,
      polyline: polylineEdge(edge.curve, floats, scale, options),
    });
  }

  return {
    positions,
    normals,
    faceOrds,
    indices,
    sideOrds,
    faceRanges,
    edges,
    bounds: { min, max },
    scale,
  };
}
