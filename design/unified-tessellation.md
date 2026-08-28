# Unified tessellation: one triangle producer for render and export

## End state

The cadjs surf tessellator is the ONLY thing in the product that turns exact
geometry into triangles. Every consumer — viewport, snapshots, CLI STL/GLB/3MF
exports — derives its mesh from the package's exact surfaces and curves at an
explicit tolerance, through one code path, with results shared via a
content-addressed mesh cache. OCCT meshes nothing: its remaining jobs are
generation itself and `.step` assembly (which never meshes).

Exports become strictly better than the OCCT meshes they replace:
**topologically watertight with boundary vertices lying exactly on the STEP
edge curves** — closer to the model than OCCT's own polygonization, not an
approximation of it. Byte-determinism falls out (one deterministic code path),
so any two producers of the same export agree byte-for-byte.

Fits the standing architecture decisions: exact geometry is the artifact and
polygons are regenerable views (design/surface-rendering.md); the viewer is a
static visualization tool and the CLIs own export (2026-08-28); duplicated
implementations are acceptable only when contract-fenced — this plan DELETES a
duplicated implementation (the OCCT export mesher) rather than fencing it.

## Why now and not earlier

Before the surf migration the client held baked triangles; exact geometry
existed only inside OCP, so exports had to mesh there. The prerequisites —
surf (exact surfaces in a JS-readable container), the client tessellator, the
cross-kernel conformance fences, CLI-owned exports — all landed in 2026. This
is the next rung of that ladder.

## Phase 0 — measure (speed gate only)

Benchmark the cadjs tessellator against OCCT `BRepMesh` at export-grade
deflections on the perf corpus (planetary, turbofan, moonwatch): wall time per
component and whole-model, triangle counts, aspect-ratio histograms. Record
results here. Quality needs no gate (Phase 1 makes boundaries better than
BRepMesh by construction); speed is go/no-go only if the JS path is
egregiously slower on moonwatch-class assemblies *after* accounting for the
Phase 3 cache (repeat exports are cache hits; the first export of a
just-rendered model at render tolerance is free).

## Phase 1 — watertight tessellation (shared-edge sampling)

Today each face samples its trim boundary from its own pcurve, so adjacent
faces agree only within `loopTolerance` (~0.5µm) — geometrically tight,
topologically unstitched. The surf already stores ONE exact 3D curve per edge
with both faces' ordinals attached, so:

- Sample each edge's exact 3D curve once per (edge, tolerance); both adjacent
  faces conform their trim loops to those shared points (matched through the
  pcurve's edge ordinal).
- Seams and degenerate edges keep their existing special handling.

Gates added to the conformance/tessellation suites:

- watertightness: within a solid, every boundary segment is shared by exactly
  two faces with identical vertices;
- boundary vertices lie on the exact edge curve (evaluate and compare);
- aspect-ratio histogram does not regress against the Phase 0 baseline.

The viewport inherits this automatically (its micro-cracks disappear).

## Phase 2 — colored JS exporters

Port per-face and per-occurrence materials into the cadjs GLB and 3MF writers
(today they are single-color; the retiring native GLB writer has per-face
material primitives). Migrate the color-fidelity tests currently pointed at
`export_native_glb_from_scene` to the JS writers as the new reference. STL is
colorless and unaffected.

## Phase 3 — packageMeshExport + the mesh cache

- `packages/cadjs/src/lib/export/packageMeshExport.js`: descriptor + component
  surfs in → tessellate at parameter tolerance → occurrence-transform-baked,
  mirroring-safe, colored mesh → STL/GLB/3MF bytes. (Absorbs what remains of
  the deleted viewer clientMeshExport logic.)
- Mesh cache tier, component-store pattern: `~/.cache/cadgen/meshes/`
  keyed `<cid>-l<lin>-a<ang>`, best-effort, `CADGEN_MESH_CACHE=0` to disable.
  Consumers: exports and snapshots now; the viewer later (Phase 5).
- Tolerance policy: exports default to the deflections recorded in the
  descriptor's mesh block (the export matches what renders showed, and is a
  cache hit); `--mesh-tolerance/--mesh-angular-tolerance` override for finer,
  paying tessellation only for uncached components.

## Phase 4 — CLI cutover and deletion

- `packages/cadjs/bin/mesh-export.mjs`, bundled like `dxf-mesh.mjs`;
  `step_export_target`'s STL/3MF/GLB arms dispatch to it (implicit exports are
  already JS; `.step` stays native blob assembly).
- Determinism test: exporting the same entry twice (and via snapshot's path)
  yields identical bytes.
- DELETE the OCCT meshing/export path: `export_native_glb_from_scene`,
  `_HierarchicalGlbWriter` and what remains of `glb.py`, `glb_mesh_payload.py`
  (numpy vectorization included), the 3MF mesh path. Their tests either moved
  in Phase 2 or die with the dead code.

## Phase 5 — viewport LOD

Render tolerance stops being a build-time constant: zooming a component
retessellates it at finer tolerance from its exact surface, backed by the same
mesh cache. This is the render-quality ceiling this architecture exists to
reach.

### Phase 5 design (2026-08-28, executed)

**Ladder, not a dial.** Three chord-tolerance levels — L0 `1.5e-3` (the
tessellator default; what every component loads at), L1 `5e-4`, L2 `1.5e-4`,
all relative to the component diagonal; `angleTolerance` stays `0.35`
everywhere (angular error is scale-free — zoom starves the chord criterion,
not the normal-spread one). Bounded levels keep the cache keyed exactly like
the disk tier (`<cid>-l<chord>-a<angle>`) and make hysteresis meaningful.

**Trigger: projected chord error, not zoom thresholds.** For a component with
bounding diagonal `D` (its tolerance unit) at distance `d` from the camera,
the worst on-screen silhouette error of level `l` is
`errorPx = l · D · pxPerUnit(d)` where `pxPerUnit` is
`viewportHeightPx / (2 · d · tan(fovY/2))` (perspective) or
`viewportHeightPx / visibleWorldHeight` (ortho). `d` is camera→bbox-center
minus the bounding radius, floored — zooming INSIDE a part demands its finest
level. Desired level = coarsest level with `errorPx ≤ 1.0`; upgrade only when
the current level's error exceeds `1.25 px`, downgrade only when the coarser
level would still sit under `0.6 px` — an enter/exit band so orbiting through
a boundary never thrashes.

**Scheduling.** Camera samples debounce 200 ms; then components are ranked by
projected error (worst first — nearest/largest on screen win) and ONE
retessellation runs at a time in the existing surf worker pool, cancellable
via AbortController when a newer camera sample changes the plan. Levels only
matter per unique component (cid), so an assembly of 200 occurrences of one
bolt pays one retessellation.

**Swap without hitches or picking drift.** A level's payload is the SAME
worker product the initial load produces — meshData AND selector bundle from
one tessellation — so selection ranges, faceRanges and edge overlays stay
mutually consistent by construction (face/edge ords are stable per surf; only
triangle counts change). The swap recomposes the package meshData (reference
composition, no baking) with a level-suffixed `sourceMeshKey`, so the scene
uploads the new component geometry, flips every occurrence of that cid at
once, and keeps drawing the old buffers until the new state commits.

**Memory.** Non-default-level payloads live in an LRU (default 8 entries)
beside the URL-keyed L0 cache; the displayed level is pinned, eviction falls
back to re-tessellating on demand. L0 payloads keep their existing lifetime
(they are the load path's cache).

**Seams.** `loadRenderSurfMeshData(url, { tessellation })` is the one place a
persistent tessellation cache (the `<cid>-l<chord>-a<angle>` disk tier the
snapshot pipeline shares) plugs in later; the implicit render path and
non-package meshes (STL/3MF) have no exact geometry and are out of scope.

**Placement.** Pure policy math and the level-keyed load layer live in cadjs
(`lib/surf/lodPolicy.js`, `lib/renderAssetClient.js`); the camera-driven
scheduler and React wiring live in the viewer
(`viewer/src/client/render/lodScheduler.js`, `useViewportLod`), keeping cadjs
non-React.

### Phase 5 execution log (2026-08-28, shipped)

Implemented exactly as designed above. Wiring: CadViewer exposes a
`sampleLodCamera()` imperative sampler (projection params, viewport height,
live distances to model-space points through the model group transform);
`onPerspectiveChange` — which already fires on every controls change — feeds
the scheduler; swaps re-compose through `useCadAssets`'
`applyComponentLodPayload` and announce themselves with a `cad:lod-level`
window event. Kill switch `window.__CAD_VIEWER_LOD__ = false`.

Measured on the cutaway turbofan (dev server, headless Chromium, 1400x1000):

- Time-to-first-render untouched: LOD does no work until a camera sample +
  200ms settle, and pre-zoom screenshots with LOD on/off are byte-identical.
- A hard zoom onto the nacelle produced 66 level swaps (every unique
  component to L1, the worst offenders on to L2) with LOD on and ZERO with
  the kill switch — the `cad:lod-level` trace is the functional evidence.
- Re-tessellation latency per component (node, inline path): the
  curved 6.6k-tri component is 89ms at L0, 154ms to L1 (12.2k tris),
  180ms to L2 (25.1k tris); NURBS-heavy components whose default
  tessellation is angle-bound barely densify (their chord criterion was
  never the binding one) and cost 33–84ms — exactly the selective
  densification the projected-error trigger is for.
- Suites: cadjs 1034 pass, viewer 401 pass (6 new policy tests, 3
  level-cache tests, 5 scheduler tests among them).

One scheduler defect was caught by its own test and fixed before landing: a
persistently failing level load would have busy-looped the drain
(fail -> finally -> re-plan -> same item); failures now park the (cid, level)
until the next camera sample.

## Decisions taken

- Shared-edge sampling is a committed work item, not a risk gate (user
  preference: exports as close to the STEP curves as possible).
- Export tolerance defaults to the descriptor's recorded deflections.
- The JS writers become the color-fidelity reference; the native exporter's
  byte-level output is not preserved.

## Execution log

- Phase 0 measured (2026-08-28). At production settings, per-triangle the JS
  tessellator is ~3.5x FASTER than BRepMesh (207k vs 58k tris/s on moonwatch);
  wall-clock gaps were entirely density (a flat 8-segment-per-pcurve floor).
  Baseline (pre-change): planetary 163ms/24.8k tris, turbofan 1.22s/170k,
  moonwatch 29.5s/6.11M, with a large sliver population. OCCT at descriptor
  deflections: 95ms/4.2k, 0.30s/23.9k, 3.85s/223k.
- Phase 1 shipped (same session): shared per-edge polylines (exact 3D curves,
  arc-fraction addressed, corner/seam-welded), face boundaries mapped through
  arclength correspondence with a loop-tolerance decimation of the chord-fine
  polyline (display overlays reuse the fine polyline, so drawn edges coincide
  with mesh boundaries), boundary vertices pinned through ONE evaluator
  (edgePointAt: exact-curve evaluation at interpolated parameters), a
  cross-face conformity pass that fan-splits to the union of boundary
  fractions (seam-side-aware mint cache, uv-guarded welds so periodic seam
  pairs never merge), and a post-conformity interior refinement of the minted
  fans. The 8-segment loop floor is adaptive (closed pcurves keep it).
  Gates in packages/cadjs/src/lib/surf/tessellateWatertight.test.js:
  bit-identical shared boundary vertices, every boundary segment covered by
  exactly two faces, boundary vertices on the exact curves. Volume/area
  invariants pass (mixed needed angleTolerance 0.45 -> 0.35).
  AFTER: planetary 167ms/6.4k tris (3.9x fewer, same speed), turbofan
  1.69s/146k, moonwatch 18.2s/2.2M — 38% faster than pre-change with 2.8x
  fewer triangles, watertight. cadjs 1009 + viewer 388 green.
- Phases 2+3 shipped (2026-08-27): `packages/cadjs/src/lib/export/
  packageMeshExport.js` — descriptor + component tessellations -> color-grouped
  primitives (priority: face > occurrence > component > surf partColor >
  `--default-color` > #d4d4d8), absolute occurrence transforms baked with true
  inverse-transpose normals (mirroring flips winding only), STL (single
  binary body), GLB (writeGlb export preset, one primitive+material per color,
  Y-up, mm->m — the retired native writer's conventions), and a colored 3MF
  writer (one basematerials group, per-object pid/pindex) on the shared
  zipStore, which now stamps the fixed DOS epoch so archives are
  byte-deterministic. `bin/mesh-export.mjs` wraps it with the component mesh
  cache (`~/.cache/cadgen/meshes/<cid>-l<chord>-a<angle>.tess`, best-effort,
  atomic, `CADGEN_MESH_CACHE=0` disables). Color-fidelity reference tests live
  in `packageMeshExport.test.js` + `meshExportCli.test.js` (16 tests: priority
  chain, per-face splits, mirroring, Y-up scale, format envelopes, cache
  losslessness, byte determinism).
- Phase 4 shipped (2026-08-27): `step_export_target`'s STL/3MF/GLB arms write
  the scene to a temporary render package (surf extraction, no meshing) and
  dispatch to the bundled `mesh-export.mjs` (registered in
  bundle-cadgen-runtime.sh); `.step` stays native blob assembly, and the #308
  generated-entry copy guard is untouched. `--mesh-tolerance` is now the
  tessellator's RELATIVE chord tolerance and `--mesh-angular-tolerance`
  radians (docs updated); the descriptor's OCCT-era absolute deflections are
  no longer consulted (divergence from the Phase 3 plan text, deliberate:
  render parity beats matching retired deflections). DELETED: `_internal/
  glb.py` (writer; `build_step_topology_index_manifest` moved to
  glb_topology.py), `glb_mesh_payload.py` (transform_normal_from_occ inlined
  into step_scene_geometry.py), `stl.py`, `threemf.py`, `mesh_step_scene`/
  `scene_export_shape` and the scene mesh-state fields, plus their test files
  (test_glb, test_glb_materials, test_glb_topology,
  test_glb_mesh_payload_vectorized, test_threemf). Python byte-determinism
  gate: test_step_export_target.test_mesh_exports_are_byte_deterministic.
