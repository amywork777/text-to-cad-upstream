# Standalone Viewer: STEP without cadgen

## End state

The viewer is a standalone JavaScript app (Node >= 22, npm-installable, no Python
anywhere) that renders EVERY STEP file — generated or foreign — plus DXF, meshes,
robots, and implicits, with full selection refs, classified edges, and themes. cadgen
remains the authoring/generation tool; when present, everything runs native-speed
exactly as today. Nothing in any existing pipeline gets slower. No backwards
compatibility; viewer and CLI functionality is maintained.

## Architecture rules (the performance guarantees)

1. The render path never touches a kernel. All rendering stays on the surf pipeline
   (exact surfaces -> worker tessellation) — measured 10x faster than kernel meshing.
2. Generation stays 100% native. build123d/OCP, in-process extraction, warm daemon,
   op memo, component store — untouched code paths.
3. WASM runs only where the alternative is "impossible", never where a native path
   exists: importing a foreign STEP on a machine with no Python. When cadgen exists,
   its native importer always wins.
4. One package format, two producers, contract-tested: byte divergence allowed,
   semantic divergence fenced by CI (see Testing).

## Phase 0 — contract hardening

- Pin `BinTools_FormatVersion` on cadgen component-blob writes + a read-back test, so
  blobs stay readable by WASM OCCT (~7.6) across future OCP upgrades.
- Conformance corpus: committed `.brep` fixtures (LFS, `models/conformance/`)
  covering every extractor branch — each analytic kind, revolution/extrusion,
  in-domain native B-spline, periodic-crossing NURBS (the v14 case), seam-crossing
  faces, approx fallback, degenerate slivers.
- Version-sync tripwire (CI, always): `SURF_VERSION` / `STEP_PACKAGE_VERSION` must
  match across the Python and JS sources; a one-sided bump fails CI.

## Phase A — DXF migration to the direct-render model

Same contract as STEP: `gen` ALWAYS writes the `.dxf` sibling of a `.dxf.py` (`-o`
renames; unchanged source no-ops via the existing closure record). The viewer parses
`.dxf` files directly — the parser (`parseDxf.js`) and fold/preview mesher are
already JavaScript and move client-side. The drawing package is DELETED, not
migrated: `drawing.json`, `geometry.json`, `preview.glb`, its schema version, bake
hashes, validator row, and the imported-DXF "needs-build" state all go. Imported
`.dxf` files render natively like STL/GLB — zero build step; DXF is standalone from
day one. Hard migration.

## Phase B — standalone polish

- Client-side STL/GLB/3MF export from rendered geometry (JS writers exist in cadjs).
- Honest staleness badge in no-cadgen mode (sha256 vs `stepHash` — pure JS).
- Clean "not yet imported" state for packageless STEPs (Phase C's entry point).

After A+B the viewer is fully standalone for everything the pipeline ever produced.

## Phase C — WASM import of foreign STEPs

For raw STEP files that never met the pipeline, on Python-less machines:

- `opencascade.js` (prebuilt full build; viewer npm dependency ONLY — excluded from
  the cadgen wheel), lazy-loaded in a worker thread, active only when the cadgen
  probe fails (`VIEWER_WASM_IMPORT=1` override for testing).
- Pipeline: WASM parse (upstream OCCT, no code of ours) -> assembly-walk twin
  (~200 lines JS) -> extractor twin (the ~1,000-line port, built kind-by-kind
  against the conformance harness) -> package-glue twin (cids, descriptor) ->
  standard package -> existing render path.
- Output is the SAME package format cadgen writes: cross-consumable both directions
  (Python CLIs resolve refs against JS-built packages — face-order parity proven in
  the POC, design/opencascade-js-render-poc.md), first-producer-wins with no double
  builds, byte divergence harmless by design.
- Known limit, documented: standalone imports run at WASM speed (~4s small, minutes
  for 100MB-class files), one time per file, with progress.

## Testing regime (the condition on the duplicated code)

- Version-sync tripwire (above).
- Cross-implementation conformance suite (Python-orchestrated; Python holds OCCT
  ground truth): per corpus blob, three-way checks — surface kinds exactly equal;
  UV-grid evaluation of both surf outputs within tolerance of each other AND of
  native OCCT; trim samples match; edge classification exactly equal; selector
  tables aligned. JS-extracted surf must also pass the existing tessellator
  invariants (volume <0.5%, per-face area <1%).
- Interop: OCP reads WASM-written blobs; `inspect` resolves `#o1.fN` against
  JS-built packages; pinned BinTools format with read-back test.
- E2E: standalone server (no VIEWER_CAD_PYTHON) importing raw fixture STEPs ->
  format-sweep render assertions; vendor-corpus screenshot comparison of JS-imported
  vs Python-imported packages of identical files.
- DXF: client-parse unit tests against pre-deletion package outputs as goldens;
  fold-preview parity; gen-writes-sibling CLI tests mirroring the STEP ones.
- Performance non-regression: the kernel version PAIR is pinned in CI (conformance
  reruns on either upgrade); existing timing-sensitive suites run untouched.

## Deferred (considered, on record)

- WASM-for-generation (replatform to JS authoring): rejected on performance — every
  measured axis regresses (edits 3.1s -> 6-15s, cold builds -> minutes, 4GB heap
  ceiling).
- Custom WASM build at OCCT 7.9: deferred unless the vendor sweep shows the 7.6
  reader mishandling files that matter.

## Execution log

- Branch `claude/standalone-viewer` off `claude/incremental-generation`.
- Phase 0 shipped (adb07db5): pinned BinTools_FormatVersion_VERSION_4 blob
  writes, SURF_VERSION/blob-format tripwire test, 11-blob conformance corpus
  under models/conformance (LFS).
- Phase A shipped (python a7322620, client 52b9ac8c + test/doc reconciliation):
  gen always writes the .dxf sibling (byte-deterministic; ezdxf volatile-
  metadata pin moved into the sibling write); freshness = the output record
  (cadgen/_internal/dxf_output.py), read by BOTH the CLI no-op gate and
  render_ops.validate_dxf_freshness; the drawing package, its Node bake, the
  dxf_artifact CLIs and the skills/dxf artifact command are deleted; exports go
  through cadgen.dxf_export_target; snapshots mesh on demand via
  bin/dxf-mesh.mjs (same reference-thickness Z-up GLB contract). Client: DXF is
  a mesh-loadable format parsed+meshed from the file itself; dxfDataIsDocument
  (apparatus counters in parseDxf) is the profile predicate; documents render
  as 2D line work (the overlay is exempt from the scene sync's clear).
  Verified: e2e sweep 7/7 with DXF coverage equal to the pre-migration
  baseline; cold needs-build auto-generates through the viewer; document +
  cut-layout + imported paths all render.
- Phase B shipped: client-side STL/GLB/3MF export (viewer/src/client/workbench/
  clientMeshExport.js — package surf geometry composed with baked occurrence
  transforms, mirroring-safe winding; used automatically when generation is
  unavailable); honest staleness in degraded mode (stepHash vs file bytes, pure
  JS); a specific "has not been imported yet" state for packageless foreign
  STEPs; silent-interpreter runs now classify as unavailable (no stdout = no
  runtime). Pinned end to end by viewer/server/standaloneMode.test.mjs against
  a live server with a broken Python: degraded ready, stale badge, import
  explanation, and a real STL serialized in JS from the sun-gear surf fixture.
