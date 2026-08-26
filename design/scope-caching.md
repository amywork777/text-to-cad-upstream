# Phase 5: Scope caching — execution plan

Status: planned, not started. Target branch: `claude/incremental-generation`
(off `release/0.5.0`). Companion doc: `design/incremental-generation.md`
(read its Phase 1–3 result sections and the moonwatch case study before
starting — they explain every convention this plan reuses and every dead end
you must not retry).

This document is written to be executed stage by stage by an agent with no
other context. Do the stages in order. Each stage ends with acceptance
criteria; do not start the next stage until they pass. If an acceptance
criterion cannot be met, stop and report rather than weakening the criterion.

## Goal

The op-level memo (`cadgen/_internal/op_memo.py`) verifies CONTENT: it re-runs
the model's Python and hashes each kernel op's input geometry. That reaches
FreeCAD-parity edits (~3s) on models whose ops are small and whose bytes are
stable, and it cannot on models like the moonwatch's chronograph movement,
where one subtree's bytes drift run-to-run (OCCT parallel-boolean
nondeterminism — measured: 29 of 191 parts byte-differ between two cache-OFF
builds) and where untouched-subtree verification itself costs minutes.

Scope caching adds the layer FreeCAD actually competes with: skip a whole
subtree by verifying its SOURCE (cheap, O(1)-ish) instead of its geometry.
Key = the set of first-party files a scope executed + their semantic hashes.
Value = the compound the scope returned, stored as canonical BREP bytes plus
a metadata sidecar. A caseback edit then re-hashes the movement's file list
in milliseconds, hits, and never runs its Python or its booleans at all.

Target numbers (measure at the end, S4): moonwatch single-parameter caseback
edit from ~120–175s to **5–15s**; no regression on turbofan (edit ~3s) or on
package-child assemblies (tom pattern).

## Environment

- Worktree: `/Users/jakefitzgerald/robots/text-to-cad-wt-050`, branch
  `claude/incremental-generation`. Commit each stage separately.
- Python: `/Users/jakefitzgerald/robots/text-to-cad/.venv/bin/python` with
  `PYTHONPATH=/Users/jakefitzgerald/robots/text-to-cad-wt-050/packages/cadgen/src`
  (the venv's installed cadgen points at the MAIN checkout; PYTHONPATH makes
  the worktree win — verify with `python -c "import cadgen; print(cadgen.__file__)"`).
- Tests: unit —
  `python -m unittest tests.python.packages.cadgen.<module>` from the
  worktree root (same PYTHONPATH); full suite —
  `PYTHON_BIN=<venv python> bash scripts/test/test-python.sh --keep-going`
  (it isolates `CADGEN_STORE_DIR` to a tempdir itself; your new cache must be
  covered by the same isolation — see S2).
- Measurements: always `CADGEN_WARM=0 CADGEN_COMPONENT_WORKERS=1`, run from
  the model's own directory, fresh process per data point. The host is often
  loaded; prefer `time.thread_time()` for attribution and treat wall-clock
  comparatively. Long runs (moonwatch ≈ 2–5 min per build) go in background
  tasks.
- Models used for validation:
  `models/step/assemblies/cutaway_turbofan_engine.step.py` (regression),
  `models/renders/moonwatch/` (the target; parent `moonwatch.step.py`
  composes children `case/dial/bracelet/movement.step.py` via a local
  `_load_entry()` helper; children import sibling helpers like `_mvt_base`
  which requires the model dir on `sys.path` — run from that directory).

## Hard rules (violating any of these is a bug)

1. **Correctness never depends on a cache hit.** Anything unkeyable,
   unserializable, or unverifiable falls through to plain execution, exactly
   like `op_memo`'s `_Unkeyable` path.
2. **Never alter, consume, or mutate caller arguments.** Generators and other
   one-shot iterables are unkeyable, full stop. (Materializing them to key
   them measurably changed op results — proven, do not retry.)
3. **Cache-state independence, not memo-off byte-identity**, is the
   determinism contract: output bytes must be identical across cold/warm/N-th
   runs. Validate it explicitly.
4. **No backwards compatibility.** Bump version salts, force regeneration,
   never write dual-format or migration code.
5. Use `cadgen._internal.atomic_replace.replace_atomic` for every file
   replace (a repo policy test enforces this; bare `os.replace` fails CI).
6. Do not retry the documented dead ends: op-result key stamping, memoized
   boolean deparallelization, live cached masters, deepcopy/BinTools
   round-trip isolation. The rationale for each is in
   `design/incremental-generation.md`.
7. Every new cache gets: a kill-switch env var defaulting ON, an in-process
   tier plus a disk tier under the store root, a version salt in its disk
   path, and stats counters.

## Known traps (all hit during Phases 1–3; each cost hours)

- `copy.copy()` on a build123d shape calls `__copy__`, which DEEP-COPIES the
  geometry (`BRepBuilderAPI_Copy`) before sharing the TShape back. Never use
  it in a hot path. Clone wrappers with
  `object.__new__(type(x))` + `__dict__.update` (see `op_memo._clone_wrapper`).
- `shape.wrapped = None` is assignable, but the property GETTER asserts —
  a geometry-free template must never have `.wrapped` read. Set/read
  `_wrapped` directly where needed.
- `BinTools.Write_s` with flags requires all five args:
  `(shape, stream, withTriangles, withNormals, BinTools_FormatVersion_CURRENT)`.
  Canonical serialization = flags `False, False` (matches cid hashing).
- build123d `Vector`/`Axis`/`Location` carry `.wrapped` (gp_Vec/gp_Ax1/
  TopLoc_Location). Type-check for a real TopoDS (`hasattr(wrapped, "TShape")`)
  before treating anything as a shape.
- Module eviction (`evict_first_party_modules`) drops model/first-party
  modules every generator run but never `cadgen.*` or site-packages — caches
  live in `cadgen.*` module state and survive; anything stored on model
  modules does not.
- The moonwatch children do `import _materials`-style sibling imports that
  only resolve while the model dir is on `sys.path` (running `python` with
  stdin/`-c` from that directory works; running a script file from elsewhere
  does not).
- A populated user-level cache satisfies builds that tests expect to observe.
  Any test touching the new cache must isolate its directory in `setUp`, and
  the suite-level isolation in `scripts/test/test-python.sh` must cover it.

---

## S0 — Nestable scoped closure capture

**Problem.** `cadgen/_internal/source_hash.py` provides
`record_first_party_execution()` (a `sys.addaudithook` on `exec` events +
`sys.modules` delta) but supports one active recording — the generator run's.
A child scope inside that run needs its own file set while the outer
recording keeps accumulating (the parent's closure must still include the
child's files).

**Build.**
- In `source_hash.py`, generalize the collector to a stack (module-level list
  of active collectors; the audit hook appends each executed first-party file
  to EVERY active collector). Keep the existing public API's behavior
  byte-for-byte for the single-recorder case.
- Add `record_scope() -> context manager` yielding a collector whose result
  is `(files: tuple[str], files_hash: str)` where `files_hash` uses the same
  semantic AST hashing (`_semantic_source_hash` / the stat-keyed memo) the
  package gate uses.
- Add `validate_scope(files, files_hash) -> bool`: re-hash the given file
  list now and compare — this is the lookup-side check, the same pattern as
  `generation.py`'s `_generated_child_is_stale` (recorded
  `sourceClosureFiles` + re-hash). A missing file → False.
- Non-Python inputs: extend the scope collector to also capture `open` audit
  events for paths under the scope's model directory (pass the directory into
  `record_scope(root_dir=...)`); record `(path, sha256 of content)` for files
  ≤ 32MB, and mark the scope **untrackable** if anything larger or unlinkable
  is read. Untrackable scopes are reported by the collector and must not be
  cached by callers.

**Acceptance.**
- New unit tests (new file `tests/python/packages/cadgen/test_scope_capture.py`):
  nested scopes attribute files correctly (outer sees union, inner sees only
  its own); `validate_scope` flips on a one-byte semantic edit and stays True
  on a comment-only edit (AST hashing is comment-insensitive); `open`-capture
  records a data file and invalidates when it changes; oversized read marks
  untrackable.
- Existing suite fully green (the audit hook is shared machinery — regressions
  here corrupt package freshness).

## S1 — Compound freeze/thaw with a metadata contract

**Problem.** A scope's value is a labeled build123d `Compound`. BinTools
serializes the shape graph but not the Python-side tree the packager
consumes: per-node labels and colors, `compound._occurrence_tree` (set by
`cadgen/instances.py`), assembly mates (they ride on the shape — grep
`assembly_mates` in `cadgen/` for the attribute names), joints if present.

**Build.** New module `cadgen/_internal/scope_freeze.py`:
- `freeze_compound(compound) -> ScopeBlob` where `ScopeBlob` holds canonical
  BREP bytes (flags `False, False`, location kept as-is — mirror
  `op_memo._write_brep`) and a JSON-able metadata tree: walk the wrapper
  tree in child order recording, per node: wrapper class name, label, color
  (as RGBA floats), plus the enumerated shape-riding extras. Enumerate the
  extras by READING the packager first: `component_package.py`'s compound
  walk (`_walk` / `_add_leaf`) and `step_export.py`'s XCAF labeling are the
  two consumers — capture exactly what they read, no more.
- `thaw_compound(blob) -> Compound`: read the BREP (structure comes back as
  one compound), walk the TopoDS tree in the same child order, wrap each node
  in its recorded class (reuse the ShapeType-mapping fallback from
  `component_package._build123d_shape_from_brep_bytes`), reapply metadata.
- Any attribute encountered during freeze that is not in the contract and not
  JSON-able → raise `Unfreezable` (callers skip caching, execution falls
  through). Log it once via stats so coverage gaps are visible.

**Acceptance.**
- Unit tests (`test_scope_freeze.py`): label/color/occurrence-tree/mates
  round-trip on a synthetic 3-part compound; `Unfreezable` on an exotic attr.
- **The load-bearing check** — package byte-identity: build
  `planetary_gear_assembly` and the moonwatch `case.step.py` compounds
  fresh, freeze+thaw them, run
  `component_package.build_package_from_compound` on both fresh and thawed
  (into temp dirs, holding the write lock — copy the harness from
  `tests/python/packages/cadgen/test_component_package.py`), and require
  identical component cid sets AND identical `assembly.json` occurrence
  names/transforms. If bytes differ only in the descriptor's provenance
  fields, exclude exactly those fields and document which.

## S2 — Child-entry scope cache + moonwatch migration

**Build.** New module `cadgen/compose.py` (public API):
- `child_entry(path) -> module-like` replacing the models' hand-rolled
  `_load_entry`: loads the child module (same importlib pattern the moonwatch
  uses, preserving its sys.path expectations) and wraps its `gen_step` so a
  call:
  1. computes lookup candidates from the in-process dict then the disk tier
     (`<store root>/scopes/v1-b123d<ver>/<keyhash>/…`), key =
     sha256(child path relative to model dir + args-key). Args normalize via
     the op layer's normalizer (`op_memo._normalize`); gen_step usually takes
     none.
  2. a candidate stores `(files, files_hash, blob)`; hit requires
     `validate_scope(files, files_hash)` — this is where source verification
     replaces geometry verification.
  3. on hit: return `thaw_compound(blob)`.
  4. on miss: run the real gen_step under `record_scope(root_dir=model_dir)`;
     if the scope is trackable and the result freezes, store
     (`replace_atomic`, version-salted path) and return the thawed canonical
     compound — the caller must receive the same reconstruction a future hit
     returns (cache-state independence; same rule as `op_memo`'s miss path).
  5. kill switch `CADGEN_SCOPE_CACHE=0`; stats via a `stats()` function
     mirroring `op_memo.stats()`.
- Disk tier lives under the same root as the other caches (default
  `~/.cache/cadgen`, `CADGEN_STORE_DIR` override) so the existing test-suite
  isolation covers it automatically — verify it does.
- Migrate `models/renders/moonwatch/moonwatch.step.py` from `_load_entry` to
  `cadgen.compose.child_entry` (also `movement.step.py`, which loads
  `movement_base` and `chrono_works` the same way).
- Update the skill's child-composition guidance
  (`skills/cad/references/step-generation.md`, the child-dependency section)
  to name `child_entry` as the composition seam. Keep it short.

**Acceptance.**
- Unit tests (`test_scope_cache.py`, with `CADGEN_STORE_DIR` isolated in
  setUp): miss→hit across two in-process calls; hit across two PROCESSES
  (disk tier); editing a child's helper file → miss; editing an unrelated
  sibling file → still hits; kill switch works; untrackable scope executes
  uncached.
- Moonwatch end-to-end (fresh processes, warm caches, background the long
  runs): cold build within 10% of current (~250s); no-change regen still
  ~0.5s; **caseback `_spec.py` edit ≤ 20s** — note `_spec.py` is imported by
  ALL children, so a `_spec` edit misses every scope; the caseback target
  edit for the 5–15s claim is one that touches only `_case`-side files. Report
  both numbers honestly. Byte-check: `assembly.json` + component files
  identical between a scope-hit build and a `CADGEN_SCOPE_CACHE=0` build of
  the same source state... if they differ, that is a FAILURE of S1's contract,
  not an acceptable drift.
- Viewer e2e: dev viewer config `cad-viewer-050` (port 3253, launch.json in
  the MAIN checkout) — load the moonwatch, confirm it renders, click a part,
  confirm the reference pane resolves, zero console errors.
- Full python suite green.

## S3 — `@cadgen.memo` for intra-entry scopes

**Build.** In `cadgen/compose.py`: decorator `memo(fn)` using the same
machinery, key = (module-relative qualname, args-key), value/validation
identical to S2. Document that decorated functions must return a shape/
compound (or a tuple of them — reuse `op_memo`'s seq handling) and must be
pure given their arguments and closure files.
- Apply it in the moonwatch as the reference example: `_mvt_base.build_base`
  and `_mvt_chrono.build_chrono` (check their signatures first; if they take
  shape arguments, those normalize via content digest — fine).
- One paragraph + example in the skill reference.

**Acceptance.**
- Unit tests: hit/miss on arg change; closure-file edit → miss.
- Moonwatch movement-internal edit (change a constant in `_mvt_chrono.py`):
  full rebuild of the chrono subtree only — measure and report; expect the
  base bridges (~the expensive drifting booleans) to be skipped, landing the
  edit well under 60s.
- Full suite green.

## S4 — Measurement, docs, wrap-up

- Re-run the moonwatch matrix (cold / no-change / `_case`-file edit /
  `_spec.py` edit / chrono-internal edit) and the turbofan edit loop, fresh
  processes, from clean caches. Present before/after against the numbers in
  `design/incremental-generation.md`'s moonwatch case study.
- Append a "Phase 5 results" section to `design/incremental-generation.md`
  (facts + measured numbers + any contract exclusions from S1), and mark this
  document's status line accordingly.
- Confirm all commits are on `claude/incremental-generation`, full suite
  green, viewer e2e passing. Do NOT push or open a PR — report and stop.

## Explicit non-goals

- No changes to `op_memo.py` (it is beneath this layer and its dead ends are
  documented — leave it alone).
- No attempt to make OCCT booleans deterministic.
- No cache GC (deferred repo-wide; note sizes in the S4 report).
- No package-children restructuring of the moonwatch (the helper preserves
  the in-process authoring pattern by design).
- No changes under `viewer/` or `packages/cadjs`.
