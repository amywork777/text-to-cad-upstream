# Incremental generation: FreeCAD-class edit performance without a rearchitecture

Status: planned, not started. Target branch: `release/0.5.0`.

## The problem

Editing one parameter in a `.step.py` costs a full rebuild. FreeCAD, on the same
OCCT kernel, applies the equivalent edit near-instantly. The gap is not the
kernel — an individual boolean or fillet costs the same in both — it is how much
work surrounds the kernel per edit:

- FreeCAD holds a live document in a warm process. An edit marks one feature
  touched, recomputes that feature and its downstream dependents against
  in-memory `TopoDS_Shape`s, retessellates only what changed, and serializes
  nothing.
- We re-execute the entire model script from scratch on every generation.
  `run_script_generator` evicts all first-party modules and `exec_module`s the
  script fresh each run (`generation_runner.py:397-401`) — a hard guarantee for
  deterministic source-closure capture. Every boolean, fillet, and revolve
  re-runs in OCCT even for a one-line edit. The only cache is keyed on the
  *output* (sha256 of built BREP, `component_package.py:139-167`), which
  structurally cannot skip construction: a shape must be built before we can
  learn we didn't need to build it. The cache saves meshing/extraction/GLB
  writes for unchanged components, never kernel time.

## The insight that makes this cheap to fix

FreeCAD's dependency-DAG recompute and "re-run the whole script with memoized
kernel operations" are computationally equivalent. The Python logic in a model
script — loops, arithmetic, sketch profiles — is milliseconds; the cost is the
OCCT calls it triggers. Re-executing the entire script on every edit is fine
*if* unchanged OCCT operations return cached shapes instead of recomputing.
This is the Salsa / incremental-build-system pattern: recompute by re-execution
with memoized expensive pure calls. The recompute behavior that falls out is
identical to FreeCAD's touched-node propagation — a late fillet edit recomputes
one op; an early sketch edit cascades downstream, exactly as it does there.

So: **no persistent mutable document, no declarative feature tree, no change to
how models are authored.** The `.step.py`-as-program model stays. Deterministic
full re-execution stays (closure capture depends on it). What changes is that
kernel calls become memoized.

## Part 1 — Input-keyed operation memoization (the main build)

### Keying: a Merkle DAG over operations

Each memoized op's key = hash of `(op name, normalized parameters, input shape
keys)`. A shape's key is the key of the op that produced it — recursive and
cheap, so keys never require BREP serialization. Leaf inputs (dimensions,
imported files) hash trivially. Floats hash by bit pattern, not repr. Keys carry
a version salt, mirroring how `STEP_PACKAGE_VERSION`
(`_internal/package_freshness.py:41`) re-keys every cid when the extractor
changes: any change to the memo layer's semantics bumps the salt and re-keys
everything at once.

Key propagation: the key rides on the build123d `Shape` wrapper, with a
TShape→key registry for shapes that round-trip through raw OCCT.

### Interception: patch build123d, don't wrap it

There is no cadgen geometry layer — model scripts import build123d directly
(e.g. `models/step/assemblies/planetary_gear_assembly.step.py:3`) and must not
need rewriting. The memo layer installs by patching build123d's choke points at
worker startup: the boolean family (fuse/cut/intersect and the builder's `Mode`
combination path), `fillet`, `chamfer`, `extrude`, `revolve`, `loft`, `sweep`,
`offset`/`shell`. Pure transforms are keyed symbolically, not cached.

This works because daemon module eviction only drops *first-party* modules
(`source_hash.py:307-341`); site-packages (build123d, OCP) and `cadgen.*` are
never evicted, in both eviction sites (`generation_runner.py:397`,
`daemon/worker.py:115-117`). Patched build123d classes and a cache living in a
`cadgen.*` module persist across requests in a warm worker.

Fallback: a shape with no key (imported STEP, direct `OCP.*` construction in
model code) becomes an opaque leaf — serialize+hash once, memoized per TShape.
Everything downstream of it still memoizes.

### Storage: live shapes in worker memory

The cache is an in-worker LRU of live `TopoDS_Shape`s, bounded by count and
estimated size. Nothing on disk — on-disk shape persistence is a known trap
(BinTools round-trips are poisoned by some boolean/fillet-derived solids; see
Part 3 for the validated exception). Worker restart = cold first build, warm
thereafter — the same deal FreeCAD gives at document open, and Part 3 softens
even that.

### Mutation discipline

Cached shapes are returned with a fresh wrapper/location but shared TShape.
Some OCCT calls mutate shared TShapes (`bounding_box()` tessellates in place —
use `BRepBndLib.Add_s`). The codebase already guards this because mutation
"would break content-addressed component dedup" (`validity.py:23`,
`interference.py:74`); the memo layer adopts the same discipline and documents
which mutations (triangulation attachment) are tolerated on cached geometry.

### Guardrails

- `CADGEN_OP_MEMO=0` kill switch.
- Validation mode for tests: compute both memoized and fresh, assert identical
  package cids. Determinism suite: memo-on vs memo-off must produce
  byte-identical descriptors and component hashes.
- Source-closure hashing is unaffected: the `sys.addaudithook` capture
  (`source_hash.py:358-390`) records executed files regardless of whether
  kernel calls hit cache, because the script itself always re-executes.

### Daemon integration (coordinate with the daemon effort)

The daemon is a supervisor over a pool of warm workers (`daemon/pool.py`),
sized by memory/CPU and recycled after 200 jobs. A per-worker cache fragments
across the pool, so **dispatch needs entry-path affinity**: route repeat
requests for the same model to the same warm worker, falling back to any free
worker. Without affinity the memo hit rate craters; with it, worker recycling
(`DEFAULT_RECYCLE_AFTER`, `pool.py:36`) bounds cache memory for free.

Known inconsistency to reconcile in that effort: the `cadgen` CLI front door is
warm-by-default (`cadgen/cli/__init__.py:157`, opt-out `CADGEN_WARM=0`) while
all five skill shims are still opt-in (`skills/cad/scripts/*/__main__.py:33`,
`CADGEN_WARM=1`), and `daemon/__init__.py:1-7`'s docstring contradicts itself.

The writer/generator lock split (`generation_runner.py:555-568`) means a
concurrent build+export of one model each run `gen_step()` — duplicated work by
design. Memoization makes the duplication nearly free; no lock change needed.

## Part 2 — Shared content-addressed store

### What it is, and what it is not

0.5.0 deliberately rejects cross-package component sharing in favor of
self-contained, relocatable package dirs (`component_package.py:52-56`,
`:514-521`), and orphan pruning (`component_package.py:800-811`) would
garbage-collect a naively shared directory out from under other models. We keep
that decision and put sharing *behind* it, pnpm-style:

- **Render assets stay in the working directory.** Every package keeps its own
  `components/<cid>.glb`, fully materialized, exactly as today. Serving,
  scanning, orphan pruning, locking, and client ref resolution are unchanged.
- **The store is a build cache**: `~/.cache/cadgen/store/<cid>.glb` by default,
  overridable via `CADGEN_STORE_DIR` (for volume locality — a model dir on
  another filesystem can't hardlink to the boot-volume cache). Package entries
  materialize as **hardlinks into the store**, with copy fallback across
  volumes. A hardlink is an equal name for the same inode, so the package dir
  genuinely contains its assets; pruning unlinks the local name only.
- The litmus test that makes it a cache: `rm -rf` the store at any time and
  every existing package keeps rendering untouched — only the next
  cross-directory rebuild pays full price once. This matches how the branch
  already classifies `__cadgen__` (gitignored, "Rebuilt on demand; never
  committed", `.gitignore:11`).

### Why this shape

- Cross-directory and cross-worktree dedupe by content: the same vendor servo
  in five folders meshes once ever; a fresh worktree links instead of
  rebuilding. Directory identity is irrelevant because the key is the cid.
- No principled in-tree anchor exists: the viewer opens arbitrary folders and
  generation runs per-entry with no project-root concept, so an in-tree store
  is either per-model-folder (near-zero sharing) or needs fragile root
  discovery. In-tree placement is the `CADGEN_STORE_DIR` escape hatch, not the
  default.
- Store GC is refcount-free: LRU by link-count/atime, since every live package
  holds its own link.

## Part 3 — Op-key journal + validated BREP snapshots (cold start)

Persist the *keys*, not the shapes: an append-only journal mapping op-key →
resulting component cid. On a cold start with unchanged source, the journal
yields the final cids without running the kernel; if the store holds those
components, generation collapses to hardlinks + a manifest write.

Pair it with opportunistic BREP snapshots in the store: per-component BinTools
BREP written **only when a write-time round-trip validation passes** —
validated-on-write sidesteps the known BinTools poisoning on boolean-derived
solids (`component_package.py:326-329` documents the failure class) while
covering most shapes. Together these let even a cold process skip unchanged
geometry — something FreeCAD cannot do (it always pays full document load).

## Part 4 — Delete `topology.glb` as an artifact class

It is still deleted on every package rewrite (`component_package.py:795-798`)
and rebuilt lazily whole-model (`step_topology_artifact.py:306-341`; the code
comments a ~29.5s extraction at `:281`). The whole-model selector data is
redundant: it is derivable from the per-component `STEP_TOPOLOGY` tables plus
occurrence transforms in `assembly.json` — `assembly_lookup.py:20-23` already
notes each component GLB "carries that part's own complete topology". Compose
the whole-model view at read time (artifact route / inspect) instead of
materializing it. Removes a whole write-amplification path: less stored, less
invalidated, nothing to keep coherent.

Component GLBs themselves are the right architecture and stay: a browser
viewer needs GPU-ready triangles from somewhere, and
tessellate-once-persist-content-addressed beats WASM-OCCT-on-the-client and
re-mesh-per-view. GLB doubles as the carrier for selector topology, serving
rendering and semantic addressing from one artifact. With the monolithic GLB
already gone on this branch (`generation.py:559-565`) and topology.glb removed,
we are at one mesh artifact per unique geometry — the minimum.

## Part 5 — STEP export (`--write`)

`--write` semantics are intentional and stay: iterate visually on the
`.step.py`, export a real STEP once when done. On 0.5.0, one `gen --write`
invocation builds geometry once and shares the scene between the STEP job and
the package job (`generation.py:655-671`) — but three costs remain:

1. **The XCAF document is built twice** — once for the render scene
   (`step_export.py:387`) and again inside `export_build123d_step_file`
   (`step_export.py:411`), each walking the whole tree setting labels/colors.
   Fix: build once, pass the doc through. Pure waste reclaimed.
2. **Translation timing is invisible**: `write_xcaf_doc_step_file` has
   `logger.timed` spans (`step_export.py:341-350`) but the call site drops the
   logger (`generation.py:546-552`). One-line fix; do it in Phase 0 so the real
   translation cost is finally measured.
3. **`has_extra_outputs` defeats all four reuse gates** (`generation.py:483,
   490, 633, 640, 1238, 1258` via `generation_spec.py:184-189`), so
   `gen` → `gen --write` rebuilds everything. This needs no special fix: post-
   memoization the rebuild is cache hits. (Incidental: the docstring at
   `generation_spec.py:186` still says `--write-step`.)

Post-memoization, `--write` stops doubling anything: cost ≈ one XCAF build +
STEP translation + file write — the same floor FreeCAD pays at File → Export.
Optional, low priority: cache the finished STEP by source-closure hash so a
repeat `--write` with zero edits is a file copy. Per-component STEP-fragment
caching is not worth it (global entity numbering makes composition fiddly for a
small win).

## Part 6 — Residual `.moved()` cost

`cadgen/instances.py` (`compound_from_instances`) already solves the big case:
raw `TopoDS_Builder` placement sharing the prototype TShape, O(1) per instance,
with a packager fast path (`component_package.py:606-641`). What remains:
plain build123d `.moved()` is deepcopy-based, so each instance carries a
distinct TShape, misses the hash memo, and re-serializes its leaf BREPs
(`component_package.py:539-546`). Fix: memoize BREP serialization per source
TShape; prefer `compound_from_instances` in model guidance.

## Phase 0 results (measured 2026-08-25)

Measured on `release/0.5.0` with an in-process harness patching the choke
points above plus cadgen's phase functions. CPU-time attribution
(`time.thread_time`), because the host was under heavy external load; wall
numbers below are indicative only.

- **Coverage verdict: PASS, with one amendment.** The original choke list
  (booleans, fillet/chamfer, extrude/revolve/loft/sweep) captured only 2.6% of
  `cutaway_turbofan_engine`'s 36s generator run. Live-stack sampling found the
  missing 95%: `Face.make_surface` (OCCT n-sided surface filling), 907 calls,
  ~29s. **The choke set must include the `Face`/`Solid`/`Wire` factory
  classmethods**, not just the operations modules. With those added, coverage
  on the expensive model is **98.9%** of generator-run CPU.
- Cheap models have lower coverage but tiny absolute residuals:
  `planetary_gear_assembly` 48% of 0.58s; `six_axis_industrial_robot_arm` 65%
  of 1.11s. The residual is model-script Python, which re-execution keeps
  paying by design.
- **Cost split by model class:** mesh + selector extraction dominates small/mid
  models (six-axis: 4.6s mesh + 1.9s extract vs 1.1s generator); kernel ops
  dominate heavy ones (turbofan: 30s generator vs 3.7s package). So Phase 1
  (op memo) is the win on slow models, and the component cid cache + store
  already bound the rest.
- **STEP export is cheap:** `--write` on the turbofan adds 0.40s of
  translation+write and ~0.04s of XCAF doc build against a 35s generation.
  The historical "`--write` doubles generation" observation is fully explained
  by the reuse-gate rebuild, which memoization eliminates. The XCAF-once point
  fix is deprioritized (harmless, but worth ~1% here).
- **BREP hashing is negligible** (~0.02s per 206-component package), so
  input-hash keying costs nothing measurable.
- **Determinism spike: PASS.** Rebuilding identical geometry fresh (solid via
  sketch+extrude+fillet, wire, `Face.make_surface` output, boolean output)
  produces byte-identical location-stripped BinTools BREP in-process, so
  input-hash keys (opaque-leaf hashing of input shapes) will hit across
  re-executions. Full Merkle key propagation remains an optimization on top,
  not a correctness requirement.

## Phase 1 results (implemented 2026-08-25)

`cadgen/_internal/op_memo.py`, installed from `run_script_generator`; default
ON, `CADGEN_OP_MEMO=0` kill switch; tests in
`tests/python/packages/cadgen/test_op_memo.py`.

Measured on `cutaway_turbofan_engine` (206 components, in-process runs):
**36.0s → 4.2s warm (8.5×)**, 100% hit rate on repeats, ~6 unkeyable calls of
1112. Verified end-to-end in the CAD Viewer. Cross-model validation (coffee
cup, planetary gear, six-axis arm, spiral staircase, robotic hand): all
cache-state independent, no failures; their warm gains are smaller because
mesh+extract dominates them, as Phase 0 predicted.

What implementation forced us to learn:

1. **Never alter caller arguments.** Materializing a generator argument to
   key it changes some ops' results. Lazy iterables are unkeyable
   passthroughs; keys are built only from arguments that can be hashed in
   place. (Orientation must be an explicit key component: a reversed shape
   shares its TShape with the forward one.)
2. **Live cached masters cannot work.** Downstream consumers mutate their
   inputs: booleans and lofts bump input tolerances, meshing and
   `bounding_box()` attach triangulation — and model code makes *selection
   decisions* from tessellation-derived bboxes with hundredth-mm thresholds,
   so pollution is behavior-changing, not just byte-changing. A
   digest-self-check variant (evict-on-mutation) was correct but evicted
   exactly the expensive intermediates every run.
3. **Isolation mechanisms are byte-lossy.** `BRepBuilderAPI_Copy` (build123d
   `__deepcopy__`) re-serializes differently; BinTools write→read→write is
   not byte-stable for ~65% of real shapes.
4. **The scheme that works is canonical reconstruction**: serialize each
   cacheable result once at op time (geometry-only flags, mirroring cid
   hashing); hand every consumer — the missing caller included — a fresh
   reconstruction read back from those bytes. Reconstructed inputs produce
   byte-identical downstream op results (validated empirically at the op
   level and end-to-end). A result whose bytes fail to read back (the known
   BinTools poison class) is not cached and flows through untouched.

**Revised determinism invariant.** The original "memo-on/off byte-identity"
requirement is replaced by two invariants the implementation actually
guarantees and tests: (a) **cache-state independence** — package bytes are
identical across cold/warm/warm-N runs, which is what cid stability actually
requires; (b) **geometric equivalence with memo-off** — identical occurrence
names, transforms, and bounds. Canonicalization changes the exact BREP bytes
of most leaf components relative to memo-off execution (171 of 206 cids on
the turbofan re-key, geometry identical). Per the no-backwards-compatibility
policy this is absorbed as a one-time re-key: content addressing rebuilds
affected components on next generation; no compat shims, no dual formats.

Still open for Phase 1 polish: daemon pool entry-path affinity (the cache is
per-worker), and the ~15-20% unkeyable-call rate on fillet-heavy models
(generator edge-list arguments) if profiling shows it matters.

## Phasing

- **Phase 0 — measure (days).** Instrument the proposed choke points with
  per-op timing on `tom.step` and one or two mid-size models. Gates: what
  fraction of kernel time flows through build123d choke points (>90% expected;
  the gap identifies extra sites to wrap), and the per-phase split (script
  Python / OCCT / BREP hash / mesh+extract / package write / STEP translation —
  includes the logger pass-through fix from Part 5).
- **Phase 1 — op memoization (~2–3 weeks).** Part 1, including pool affinity.
- **Phase 2 — store + journal (~1–2 weeks).** Parts 2 and 3. Independent of
  Phase 1; either can land first.
- **Phase 3 — point fixes (days each, independent).** Parts 4, 5.1, 6.
- **Phase 4 — assembly children (integration with daemon work).** Stale
  children currently rebuild in fresh `python -c` subprocesses for closure
  capture (`generation.py:1018-1096`), bypassing every warm cache. Move child
  rebuilds in-daemon so they share the op cache, verifying per-request closure
  capture. Sequenced last; touches the daemon effort's territory.

## Expected wins (to be confirmed by Phase 0)

- Single-parameter edit, mid-to-large model: from full rebuild (~30s on
  `tom`-class assemblies, excluding import) to script re-exec (tens–hundreds of
  ms) + changed OCCT subtree (tens of ms–~1s) + mesh/extract one component
  (hundreds of ms–~2s) + incremental package write. **~1–3s, 10–30×**, scaling
  with model size.
- Small single-part models: 2–5× (little unchanged work to skip; meshing
  dominates).
- Inspect/snapshot after an edit: removes a whole-model extraction that today
  rivals a full generation (Part 4).
- `--write` at end of session: from ~2× build time to XCAF-once + translation.
- Fresh worktree / second directory using shared parts: mesh+extract replaced
  by hardlinks (Parts 2–3).

The new floor is per-component mesh + selector extraction — GIL-bound Python
(`component_package.py` notes it; workers amortize an OCP import each). If that
floor is what users feel after Phase 1, the follow-up is moving extraction
native — not before measuring.

## Risks

- **Choke-point coverage** below expectation (direct `OCP.*` in model code) —
  Phase 0 gates this; opaque-leaf fallback degrades gracefully.
- **Determinism**: memoization must return exactly what re-execution would
  produce. Version-salted keys, worker-lifetime scoping, and the memo-on/off
  byte-identity suite pin this.
- **TShape mutation** on cached shapes — discipline per Part 1; audit callers.
- **Pool fragmentation** without dispatch affinity — hit rate depends on it.
- **BinTools poisoning** — only validated-on-write snapshots are persisted;
  live-shape cache is unaffected by design.
- **Store on network filesystems** (SMB/NAS): hardlink support varies; copy
  fallback must be automatic and silent.

## Non-goals

- No persistent mutable document, no feature-tree format, no changes to model
  authoring or the `.step.py` contract.
- No weakening of deterministic full re-execution or audit-hook closure
  capture.
- No in-tree store by default; no committed `__cadgen__` content.
- No per-component STEP-fragment caching.
