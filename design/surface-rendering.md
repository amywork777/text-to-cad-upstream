# Surface rendering: ship surfaces, tessellate on the GPU

Status: EXECUTING 2026-08-26. Branch: `claude/incremental-generation`.
Companions: `design/production-architecture.md` (the caching system this
completes), `design/incremental-generation.md` (evidence + dead ends).

## Mission

Delete the last geometry-scaled cost in the loop — display tessellation —
by shipping B-rep SURFACES (analytic params / NURBS nets + trim pcurves +
edge curves) and tessellating on the client GPU at screen-space precision.
The frozen contract is THE RENDERED OUTPUT AND ITS BEHAVIORS, nothing else:
themes (all presets), edge rendering incl. visibility classes, selection/
hover/tree-sync, exploded view, parameter animations, orthographic views,
snapshot/GIF tooling. No backwards compatibility below the pixels: the GLB
display pipeline (server and client) is deleted at cutover, no fallback
renderer, three.js version unpinned.

## Verification: the golden harness IS the contract (R0)

Screenshot matrix (fixtures x themes x views) of the CURRENT viewer,
perceptual diff (per-pixel threshold + RMS) against the new renderer, plus
an interaction checklist. Intentional improvements (exact curved edges,
true silhouettes) are human-reviewed diffs, never silent. Headless WebGPU
was proven before any renderer code: Apple Metal-3 adapter in headless
Chromium, triangle rendered and pixel-verified.

## Workstreams

- R0 golden harness + headless WebGPU proof (DONE: proof; harness first
  deliverable).
- R1 `.surf` extractor in cadgen: per-face surface (analytic | NURBS via
  GeomConvert), trim loop pcurves, 3D edge curves with PRECOMPUTED
  visibility classes (dihedral from adjacent surfaces), face/edge ordinals
  (subsumes STEP_TOPOLOGY), per-face color/material. GLB-style container:
  JSON index chunk + binary chunk. Content-addressed by the same cid;
  store key simplifies to bare cid (no deflections).
- R2 renderer core in `packages/surfjs` (standalone, own deps, cadjs
  re-exports — the implicitjs precedent): WebGPU device/canvas, camera
  shared with cadjs/common, tessellation of analytic surfaces then NURBS,
  trim-by-discard coverage masks, adaptive density by screen-space error,
  exact edge curves.
- R3 interaction: face/occurrence ID buffer picking, hover/selection
  tint, tree sync, measure overlays.
- R4 parity by checklist: themes/materials (cad_material, effects color
  multiplication), exploded view + parameter animations (occurrence
  transforms — untouched), orthographic, auto-fit, snapshots on the new
  renderer.
- R5 cutover: packages emit `.surf`, GLB display path deleted end to end
  (server emit, client fetch/parse, snapshot GLB runtime), goldens green,
  suites green.

## Hard rules

Correctness gates are the golden harness + existing suites. No dual
renderer. Mesh survives only in scripts/export (STL/3MF/GLB as export
formats) and on-demand inspect facts. All store/artifact conventions from
the production architecture apply (content addressing, atomic writes,
kill switches, version salts).
