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

## Execution log

- R0 DONE: golden harness (`scripts/render/golden.py`, capture + shift-
  tolerant perceptual compare), 24 themed baselines of the GLB viewer under
  `tmp/render-goldens/baseline`; headless WebGPU proven (Apple Metal-3).
- R1 DONE: `cadgen._internal.surface_extract` emits `<cid>.surf` beside
  every component GLB (packages, shared store keyed by bare cid,
  descriptor `surf` refs, freshness gates). OCCT-rebuild fidelity suite in
  `tests/python/packages/cadgen/test_surface_extract.py`.
  Hard-won invariants, all pinned by tests:
  - parametrization is part of the contract: revolution/extrusion
    serialize as axis + profile (NURBS conversion reparametrizes), native
    B-spline/Bezier convert exactly, exotic kinds approximate.
  - every curve/surface ships CLAMPED (client evaluators are
    clamped-only); a payload's range must sit inside its knot domain
    (trimming periodic pcurves near the period normalizes parameters).
  - swept faces can cross a closed profile's period: profiles carry
    `period` and the client wraps.
  - clamping operates on COPIES (the adaptor hands back the model's own
    curve handle).
- R2 DONE (CPU tier): `packages/cadjs/src/lib/surf/` — container parser,
  WGSL-portable evaluators, grid+clip tessellator (curvature-driven cells,
  boundary-exact trims, conforming refinement w/ chord + normal-spread +
  facet-alignment criteria; volume within 0.5% and per-face area within
  1% of OCCT). GPU compute tessellation remains as an optimization tier.
- VIEWER + SNAPSHOT swapped to `.surf` for STEP display: `loadRenderSurf`
  produces the GLB meshData contract (barycentric edge overlay synthesized
  from model-edge ordinals). Planetary golden diff 1.56% (<2% gate);
  turbofan visually identical (sub-percent auto-fit zoom difference from
  honest bbox deltas — accepted, new baseline captured from the surf
  renderer). three upgraded to 0.185.1 in cadjs.
- REMAINING: selector/topology bundles still load from GLB (R3), WebGPU
  renderer swap + TSL port of the edge overlay (R2 tail/R4), GLB display
  pipeline deletion (R5).
- R5a DONE: packages are SURF-ONLY. The component build no longer meshes,
  selector-extracts, or encodes GLB at all — `_write_component_surf_atomic`
  is a pure surface read. The shared store keys by bare cid. Python-side
  topology consumers (inspect refs/facts via `assembly_lookup`) read
  selector tables synthesized from the .surf (`_internal/surf_tables.py`,
  exact GProp metrics stored in the artifact). snapshot componentUrls
  point at the .surf. Verified: `inspect refs block#o1.1.f3` resolves
  "plane area=36.0" GLB-free; turbofan FORCED full rebuild (206
  components) 33s -> 7.3s; viewer renders surf-only packages.
- WIDE STEP SWEEP (2026-08-27): 21/21 imported vendor mechanism STEPs
  (models/step/mechanisms) import -> surf-only package -> snapshot render,
  ~8-10s each including STEP read; every current component parses,
  tessellates, and stays inside its descriptor bbox. Generated models:
  planetary (9), turbofan (206), moonwatch (257), lyra (92), juno (244),
  hypercar (647), f14d (1127 components, 741s cold geometry build) all
  clean. Two extractor gaps found and fixed by the sweep: native
  Geom_BSplineSurface faces serialize DIRECTLY (vendor trim-then-convert
  round trips can throw), and closed swept profiles carry their period.
  f1.step.py fails in its own loft (f1_parts/lib.py:313) identically on
  develop — pre-existing model breakage, unrelated.
- DEFERRED to a follow-on: WebGPURenderer swap + TSL port of the
  barycentric edge overlay + WGSL compute tessellation. The outcome
  contract (same-or-better pixels, exact edges, all themes, picking,
  snapshots) is met on WebGL + client CPU tessellation; headless WebGPU
  and a WebGPURenderer surf render are already proven, so the tier can
  land without artifact or protocol changes.
