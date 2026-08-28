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
- Phase C shipped (da8da8d2 extractor twin, f19a6ce5 import twin, + wiring):
  - Extractor twin (viewer/server/import/surfExtractTwin.mjs) conformant with
    the native extractor over the full 11-blob corpus at <=1e-14 mm (incl.
    both periodic-crossing v14 traps and both gear involutes); harness =
    extractCli.mjs + compareSurf.mjs, wrapped as
    tests/python/packages/cadgen/test_surf_extractor_conformance.py.
  - Import twin (stepImport.mjs): XCAF walk, embedded-entryKind metadata read,
    adaptive mesh-resolution twin, package glue (salted cids, occurrence walk,
    descriptor). Verified DESCRIPTOR-IDENTICAL to a native import of the same
    STEP (ids, names, transforms, colors, tree, mesh block incl. hints, bbox,
    stats, key set) with every occurrence-paired component conformant; cids
    diverge by design. Pinned by test_wasm_import_parity.py; shared constants
    pinned by test_render_contract_sync.py (now covers the JS producer's blob
    pin too). Interop proven both ways: OCP reads WASM-written V4 blobs;
    inspect refs/measure (occurrence + face selectors, lazy topology build)
    work against a JS-built package.
  - Wiring (cadgenOps.mjs): raw STEPs route to the WASM import when render_ops
    is unavailable (VIEWER_WASM_IMPORT=1 forces, =0 disables); import runs as
    a child process (an emscripten abort must not kill the server), in-flight
    imports dedup by package dir and report `generating`; unimported STEPs
    report `needs-build` instead of an install hint, stale imports rebuild.
    E2E-pinned by standaloneMode.test.mjs: broken-Python server imports a raw
    vendor STEP end to end and renders/exports it.
  - Binding deviations from the plan, on record: worker THREAD became a child
    PROCESS (aborts observed taking the whole node process down);
    TDataStd_Name.Get and GetInstanceColor are unbound in the prebuilt kernel
    (workarounds + follow-ups in design/FEEDBACK.md #18-19); Quantity_Color is
    linear-RGB in WASM and converted to sRGB to match build123d output.
- Simplification pass (2026-08-28, user-directed), on top of the detached-
  outputs amendment:
  1. The unreachable monolith-GLB stratum is deleted (~950 lines): the file-
     gated validator, its manifest helpers, glb.py's duplicated readers, the
     dead part/assembly exporters, the topology.glb remnants, and the
     freshness-wrapper fallbacks.
  2. The OCP selector extractor (step_scene_selectors.py, 1,021 lines) is
     deleted; its one caller (the mid-write descriptor race window) is a
     bounded retry-read. Selector relevance now has exactly two
     implementations — the Python surf reader and its JS twin.
  3. The render package IS the scene cache: step_scene_cache.py is deleted,
     load_step_scene_cached reconstructs scenes from the package (brep blobs +
     descriptor + surf face colors), per-face colors ride the component build
     (STEP_PACKAGE_VERSION 15), and the imported-STEP build no longer parses
     the text STEP twice.
  4. Artifact status has ONE authority: viewer/server/artifactStatus.mjs (pure
     JS file reads). Python's render_ops keeps build/export plus one status
     primitive — `snapshot`, the flock view (idle|writing|busy) that Node
     cannot probe and that must never be re-inferred from pids/heartbeats.
     The freshness test suite lives with the authority
     (viewer/server/artifactStatus.test.mjs); Python suites that need a
     verdict ask through tests/python/support/js_status.py.
- Amendment (2026-08-28, user decision): the viewer is a STATIC VISUALIZATION
  TOOL and runs no Python, ever. Removed: the render_ops module and every
  viewer spawn of it (build, export, probe, the lock-snapshot primitive), the
  export routes/UI (server /__cad/export, StepExportDropdown, modelExport,
  clientMeshExport, the exportFormats/clientMeshExport capabilities — the
  CLIs own ALL exporting, implicits included), and viewer builds of generated
  entries (.step.py/.dxf.py without artifacts report "run scripts/gen", never
  needs-build — consistent with detached outputs). A CLI build in flight shows
  a generating badge ADVISORILY from its status record (fresh + non-terminal);
  the viewer never contends for the generation lock, so the lock.py
  no-liveness-inference rules are not violated — nothing acts on the badge.
  The WASM import of raw foreign STEPs remains the viewer's only build
  (VIEWER_WASM_IMPORT=0 disables). cadgen.coordination.snapshot() stays as
  the producer-side kernel read (contended builds, tests).
- Policy amendment (2026-08-28, user decision): generated outputs are DETACHED
  from their source code. The render-side validators (render_ops
  validate_step/dxf/implicit_freshness) no longer read source closures or the
  DXF output record — the viewer renders what exists and never rebuilds a
  generated entry because its code changed; regeneration is the agent's
  explicit act. Removed, not demoted: no advisory flag. Still checked
  render-side: package/sibling EXISTENCE, packageSchemaVersion, bakeHash, and
  the imported-file digest gate (a real .step on disk gets the stepHash gate
  even when its package was generator-built — file->render coherence is
  mechanism, not source currency). The CLI's no-op gates keep reading the
  recorded closures (skip-work direction only); the deliberate asymmetry is
  documented in render_ops, generation.py and viewer/docs/backend.md.
