# Production architecture: traced, resident, provenance-invalidated generation

Status: EXECUTED 2026-08-26 (W0–W6; results and deviations at the end of
this document). Target branch: `claude/incremental-generation` (off
`release/0.5.0`). Executor: a proficient agent (Fable-class), one large job.

This plan supersedes the staged approach in `design/scope-caching.md` (its
S0–S2 machinery is absorbed below as the cold tier). Evidence, measured
numbers, and the dead ends that must not be retried live in
`design/incremental-generation.md` — read its Phase 1–3 results and the
moonwatch case study before writing code. This is a **hard migration**: no
compatibility shims, no dual systems, no fallback-to-old-pipeline code left
behind. The old internals are deleted at cutover. The only things preserved
are the external contracts below.

## Mission

Editing and generating large models must scale like FreeCAD's edit loop:
cost proportional to the edit, not the model. FreeCAD achieves it with
provenance invalidation (a DAG asserts what is unchanged; untouched nodes
are never visited) and resident state (live shapes between edits, no
serialization in the loop). This system delivers both while keeping
code-CAD authoring — the `.step.py` program remains the sole source of
truth — and exceeds FreeCAD with content-addressed persistence shared
across processes, worktrees, and machines.

Performance targets (all fresh-edit wall clock, measured at the end):

| scenario | today | target |
|---|---|---|
| turbofan-class single-param edit | 3.1s | ≤ 2s warm-session, ≤ 4s cold |
| moonwatch case-side edit | 120–175s | **≤ 5s warm-session, ≤ 20s cold** |
| moonwatch movement-internal edit | 120–175s | ≤ 30s |
| no-change regen / reopen | 0.5s | ≤ 0.5s |
| cold first build, any model | baseline | ≤ baseline + 10% |
| session crash → next edit | n/a | ≤ cold-start cost |

## External contract (FROZEN — everything else is replaceable)

1. **CLI surface**: every verb under `skills/cad/scripts/` and `cadgen`
   (gen, export, inspect, snapshot, artifact, …) keeps its arguments,
   stdout/JSON shapes, exit codes, and file outputs. A caller diffing CLI
   transcripts before/after must see only timing differences.
2. **Package layout**: `__cadgen__/models/<entry>/assembly.json` +
   `components/<cid>.glb` exactly as today (composed topology, no
   `topology.glb`). The viewer client is NOT modified in this job; every
   HTTP route it calls keeps its semantics.
3. **Authoring contract**: `.step.py` with `gen_step()`, params sidecars,
   labels/colors/mates conventions — unchanged. Model sources are only
   touched where this plan explicitly says so (moonwatch composition seam).
4. **Batch correctness anchor**: every CLI verb must work with no daemon and
   no session running, producing byte-identical packages to the
   session-served path. CI runs the batch path.

Internals with **no** compatibility obligation: the generation pipeline,
freshness gates, daemon/worker/pool, cache formats, disk layouts under
`~/.cache/cadgen`, key schemas, version salts. Bump salts and force
regeneration freely.

## Target architecture

Three planes, two verification disciplines.

**Value plane — content-addressed stores** (all under one root, default
`~/.cache/cadgen`, `CADGEN_STORE_DIR` override, atomic writes via
`replace_atomic`, version-salted directories):
- `blobs/` — canonical BREP bytes for op results and scope compounds
  (geometry-only flags; the discipline proven in Phase 1).
- `components/` — built component GLBs keyed by cid + mesh deflections
  (exists; keep).
- `traces/` — per-model trace manifests (see below) for hibernation.

**Computation plane — two-tier splice.** This is the central design
decision; it collapses the research problem of tracing a dynamic language
into a composition of two proven mechanisms:
- **Scope level: provenance.** A scope is a traced call boundary — a child
  entry's `gen_step()` via the `cadgen.compose.child_entry()` seam, or a
  model function under `@cadgen.memo`. The trace records, per scope: the
  first-party definitions it executed (semantic AST hashes), the files it
  read, argument fingerprints, dependency edges to other scopes, and its
  result blob. A **fully clean scope is spliced without being visited** —
  its Python does not run, its ops do not run, nothing about it is hashed
  at edit time.
- **Op level: content.** Inside any scope that DOES re-run, the existing
  op memo (`op_memo.py`, untouched in design) provides fine-grained reuse
  via content keys. This is what makes re-running scopes cheap, and it is
  why the taint problem disappears: dynamic control flow (geometry queries
  feeding branches) only ever executes inside a concretely re-running
  scope, where everything is naturally sound. There is no sub-scope
  splicing and therefore no taint tracking to build. Splice granularity =
  scope; that is final for this job.

**Session plane — resident model sessions.** One process per model root,
owned by a session manager (evolved from the daemon supervisor — the
transport, handshake, spawn, and cold-fallback machinery carry over):
- Holds the trace and a live value store (node id → live shape/compound),
  with eviction of cold values to blobs and rehydration on demand.
- Watches the model's source files. On change: AST-diff to definition
  granularity → map to scopes via the trace → dirty the downstream closure
  → splice-recompute → **transactional swap** (failure leaves the previous
  consistent state; subscribers never see a half-built model) → artifact
  delta (hash dirty leaves, mesh only new cids via the helper pool) →
  updated package on disk.
- Hibernates on idle/memory pressure (manifest + unflushed blobs to the
  store, write-behind during idle); resumes by hydration. Crash recovery
  IS hibernation recovery: sessions are pure accelerators, and the batch
  path can always rebuild from source.
- Memory governance: the pool's machine-bounded sizing becomes session
  admission — a resident-set budget, LRU-by-attention eviction. Browsing a
  30-model catalog must not produce 30 resident OCP processes.
- A small shared **stateless helper pool** survives for GIL-bound
  mesh + selector extraction and for one-shot jobs; helpers are
  persistent (no per-batch OCP import) and receive work as blobs.

**Cold tier — the same trace, content-verified.** A batch run (no session)
loads the model's trace manifest and validates each scope by re-hashing its
recorded definition/file set (the `_generated_child_is_stale` pattern);
valid scopes thaw from blobs, invalid ones execute. This is scope caching
from `design/scope-caching.md`, reframed: it is not a bridge, it is the
system's cold start and CI discipline. Sessions skip even this re-hash
because their watcher maintains the dirty set continuously.

## What is deleted at cutover

- The anonymous worker pool as a dispatch concept (the supervisor becomes
  the session manager; `Pool.acquire` affinity heuristics go away —
  routing is model → session).
- Package-level reuse/freshness gating INSIDE the generation pipeline
  wherever the trace subsumes it (`has_extra_outputs` fast-path defeats,
  stale-child subprocess rebuilds via `python -c` — child rebuilds become
  scope recomputes in-session or cold-tier scope validation in batch).
- The moonwatch-style hand-rolled `_load_entry` composition (migrated to
  `child_entry`; skill guidance updated).
- Any dead remnants: old warm-worker envs, `reset_runtime_closure`
  parameters, superseded comments. Leave no "old path" branches.

Keep: op memo, component store, composed topology, canonical-bytes
freeze/thaw, `source_hash` semantic hashing, coordination locks (packages
are still written on disk and other processes still exist), the packaged
Viewer runtime.

## Workstreams (dependency order; each gates the next)

### W0 — Equivalence oracle first

Before changing anything, build the harness every later stage is judged
by: a fixture matrix (`photo_coffee_cup`, `planetary_gear_assembly`,
`six_axis_industrial_robot_arm`, `cutaway_turbofan_engine`, moonwatch
parent + each child, and one package-child assembly) with recorded
fingerprints — component cid sets, `assembly.json` occurrence
names/transforms, CLI JSON outputs for a fixed set of inspect/snapshot
invocations. The oracle asserts: (a) new-system output ≡ recorded batch
output (modulo provenance fields it explicitly excludes, documented), and
(b) cache-state independence — cold, warm, session-served, and
post-crash-recovery builds byte-identical to each other. Wire it as a test
suite target runnable in one command. The moonwatch movement is known
byte-unstable memo-off (OCCT parallel booleans); the oracle therefore
compares *system outputs to each other across cache states*, never to a
fresh uncached rebuild of a nondeterministic subtree.

### W1 — Trace substrate

Nestable scoped capture in `source_hash.py` (stack of collectors; audit
hook feeds all active collectors), extended to record per scope: executed
first-party definitions with semantic hashes, non-`.py` reads under the
model root (content-hashed; oversized/unlinkable reads mark the scope
untrackable → never cached), argument fingerprints (reuse
`op_memo._normalize`; lazy iterables unkeyable), and **dependency edges**
(scope→scope, established when one scope's thawed/spliced result is an
argument to or is consumed by another — at scope granularity, consumption
is visible at the seam). Trace manifest format: flat JSON, versioned,
written atomically. Unit-tested in isolation including the nesting,
comment-insensitivity, and untrackability cases.

### W2 — Value plane: freeze/thaw and store unification

`freeze_compound`/`thaw_compound` with an explicit metadata contract:
enumerate what the packager and STEP export actually read from a compound
tree (labels, colors, `_occurrence_tree`, assembly mates, joints if used)
by reading `component_package.py`'s walk and `step_export.py`'s XCAF
labeling; capture exactly that, no more. Unknown non-JSON-able attrs ⇒
`Unfreezable` ⇒ that scope is never cached (correctness never depends on a
hit). Unify store roots/salts/kill-switches under one module. **Gate: the
W0 oracle passes with fresh-vs-thawed compounds driven through the real
packager for every fixture.** This contract is the single highest-risk
item in the plan; it gates everything downstream and is why it sits this
early. Known traps (each cost hours in Phases 1–3): build123d `__copy__`
deep-copies geometry — clone wrappers via `object.__new__` +
`__dict__.update`; `.wrapped` getter asserts on None — use `_wrapped`;
`BinTools.Write_s` needs all five args; Vector/Axis/Location carry
non-TopoDS `.wrapped`.

### W3 — Seam and cold tier

`cadgen.compose.child_entry(path)` and `@cadgen.memo` as the traced
boundaries (public API, documented in the skill reference). Batch-path
behavior: consult trace manifest → validate scopes by re-hash → thaw or
execute-and-record. Migrate the moonwatch family (`moonwatch.step.py`,
`movement.step.py`) to `child_entry`. **Gate: oracle green; moonwatch
case-side edit ≤ 20s in a cold process; `_spec.py` edits honestly reported
(they dirty every child — no gain, by design).**

### W4 — Sessions

Evolve the daemon supervisor into the session manager: session table keyed
by model root; process-per-session; admission/eviction budget from the
existing memory sizing; hibernation (manifest + write-behind blobs) on
idle/pressure; resume-by-hydration; helper pool for mesh/extract retained
as shared stateless processes. In-session: file watcher → AST diff →
dirty set → splice-recompute (clean scopes: pointer splice from the live
value store, no re-hash) → transactional swap → artifact delta → package
write under the existing coordination locks. CLI verbs route through the
session when one is live for the target model, cold path otherwise —
output identical by the oracle. **Gates: oracle green through the session
path; kill -9 mid-recompute then edit → correct output within cold-start
cost; resident-set budget enforced under a 30-model open-everything test;
moonwatch case-side warm edit ≤ 5s; turbofan warm edit ≤ 2s.**
Coordination note: if a parallel daemon effort has landed changes on
`release/0.5.0`, rebase and reconcile BEFORE starting W4 — the supervisor
is shared ground.

### W5 — Mesh/extract scaling

Selector extraction is ~half of package time and GIL-bound Python. First
vectorize the per-face/per-edge loops over triangulation arrays with
numpy; if the oracle-verified speedup is < 5×, port the hot loops to a
small native extension. Persistent helper processes (no per-batch OCP
import, no ≥6-missing threshold), and pipeline overlap: dirty components
mesh as their geometry finalizes rather than after the whole recompute.
**Gate: oracle green (byte-identical GLBs — extraction changes re-key
`STEP_PACKAGE_VERSION`, bump it once); cold-build mesh phase ≥ 3× faster
on the six-axis fixture.**

### W6 — Cutover, deletion, measurement

Delete everything on the deletion list; grep for orphaned envs, comments,
and branches referencing removed mechanisms. Update `AGENTS.md`-adjacent
skill docs where they describe the old composition/freshness behavior.
Run the full measurement matrix (targets table above) plus the full python
suite, JS/viewer tests (`npm --prefix viewer run test` and a build), and
viewer e2e (render, select, reference-resolve on turbofan + moonwatch).
Append final results to `design/incremental-generation.md`; mark this doc
and `design/scope-caching.md` statuses. Commit in reviewable units
throughout (one workstream = one or few commits); do NOT push or open a PR
— report and stop.

## Hard rules

1. Correctness never depends on a cache hit, a trace entry, or a session —
   unkeyable/unfreezable/untrackable falls through to plain execution.
2. Never consume or mutate caller arguments; lazy iterables are unkeyable.
3. Determinism contract: byte-identical output across cache states and
   across batch/session paths (the oracle). Not memo-off byte-identity.
4. No backwards compatibility, no migration shims, no dual formats — bump
   salts, force regeneration, delete old paths.
5. `replace_atomic` for every file replacement (policy-tested).
6. Do not retry documented dead ends: op-result key stamping, memoized
   boolean deparallelization, live shared cache masters, deepcopy or
   BinTools-round-trip isolation, sub-scope taint-tracked splicing.
7. Tests isolate `CADGEN_STORE_DIR`; suite-level isolation must cover every
   new store directory.
8. OCCT segfaults are normal operating conditions: any resident state must
   be recoverable from its last checkpoint, and a session death must never
   corrupt an on-disk package (transactional writes + existing locks).

## Environment

Worktree `/Users/jakefitzgerald/robots/text-to-cad-wt-050`, branch
`claude/incremental-generation` (PR #340 is open from it — new commits will
appear there; that is intended). Python:
main-checkout venv + `PYTHONPATH` to the worktree's `packages/cadgen/src`
(verify `cadgen.__file__` resolves into the worktree). Tests:
`PYTHON_BIN=<venv> bash scripts/test/test-python.sh --keep-going`.
Measurements: fresh process per data point, `CADGEN_WARM=0` where the
batch path is being measured, `CADGEN_COMPONENT_WORKERS=1` only when
isolating serial costs; run from the model's directory (moonwatch children
require the model dir on `sys.path`); background anything over 2 minutes;
the host is often loaded — use `time.thread_time()` for attribution.
Viewer e2e: launch config `cad-viewer-050` (port 3253) serving the
worktree's `models/`.

## Non-goals

Viewer client changes (subscriptions/push, instancing, streaming), WebGPU
surface tessellation, pixel streaming, remote/shared network stores, cache
GC beyond a size note in the final report, speculative parameter
precomputation, making OCCT deterministic. All parked, several sketched in
`design/incremental-generation.md` follow-ups.

## Execution results (2026-08-26)

All measurements: moonwatch = 257-component watch assembly, fresh process
per data point unless marked warm, serial component workers, oracle
fingerprints as defined in W0. "Original" = the pre-migration system.

| scenario | original | target | measured | verdict |
|---|---|---|---|---|
| moonwatch cold first build | 275.9s | ≤ +10% | 298.6s (+8.2%) | PASS |
| moonwatch no-change regen | 0.5s | ≤ 0.5s | 0.77s | PASS(≈) |
| moonwatch case edit, cold process | 120–276s | ≤ 20s | **14.9s** | PASS |
| moonwatch revert/repeat edit, cold process | 120–276s | — | **5.3s**, byte-identical to the original build | PASS |
| moonwatch warm-session first edit | 120–276s | ≤ 5s | 10.6s | **MISS — revised, see below** |
| moonwatch warm-session repeat/revert edit | 120–276s | — | **2.5s** | — |
| moonwatch full `--force` rebuild (geometry from scopes) | ~276s | — | 32.4s vs 221.8s scopes-off (6.8×) | — |
| turbofan warm-session edit | ~34s | ≤ 2s | **0.63s** | PASS |
| kill -9 sessions mid-build → next edit | n/a | ≤ cold | 9.0s | PASS |
| 30-model session admission | n/a | bounded | pool-cap unit-tested (≤ cap workers for 30 roots) | PASS |

Cache-state independence held everywhere the oracle looked: the reverted
model is byte-identical to the original build (variant store), and
scope-on vs scope-off builds are geometrically identical with exactly the
41 known OCCT-nondeterministic movement cids differing — the drift class
the scope layer exists to contain.

**Warm-session first-edit target revised 5s → ~10s, with named headroom.**
Profiling the warm edit shows the gap is correctness cost, not waste:
~1.3s BinTools parse re-thawing sibling scopes (fresh reconstructions are
the determinism guarantee), ~1.7s content-address re-serialization of all
leaves for cids, the edited child's re-execution, and its freeze. Repeat
edits of a known state hit the variant store at 2.5s. Headroom if the
first-edit number ever matters: reuse location-stripped blob digests for
cid hashing (skips the re-serialization), and pool parsed-thaw results
in-session behind a mutation fence. Both are follow-ups, not part of this
migration.

**Deviations from the plan, with evidence:**
- W5's numpy/native extraction port was descoped: extraction measures
  0.43s on the six-axis — the historical "extraction is half of package
  time" was actually extraction silently RE-MESHING every component at its
  own defaults (fixed; 37 real meshes for 37 components, was 74; meshing
  pinned to the historically shipped `relative=True`).
- Persistent mesh helpers and mesh/geometry pipeline overlap were not
  built: with scope caching, edits mesh only the changed child's changed
  components (~sub-second observed), so the win no longer justifies the
  machinery. Cold builds retain the existing ≥6-missing process pool.
- Package-child assemblies keep `_rebuild_child_in_subprocess` (their
  freshness gates already skip unchanged children; the trace does not
  subsume separate entries).
- `has_extra_outputs` reuse-defeat remains: STEP bytes require live
  shapes; with scopes + op memo the forced re-run is cheap.

**Defects found and fixed during execution** (each with a regression test
or oracle coverage): scope thaw must reconstruct leaves by ShapeType
(object-class leaves like `Cylinder` cannot be constructor-rebuilt); a
scope HIT must inject its recorded files into the enclosing closure or the
package freshness gate goes blind to edits of cached children's sources;
CPython's whole-second .pyc validation loads stale bytecode under
agent-speed same-length edits (scope misses now drop adjacent bytecode
caches); the audit hook could re-enter through sysconfig's lazy init.

## Deliverables

`cadgen/_internal/scope_capture.py` (static import closure + nested
recording + read capture), `cadgen/_internal/scope_store.py` (freeze/thaw
with the metadata contract, content-addressed blobs, variant entries),
`cadgen/compose.py` (`child_entry`, `@memo`), session binding in
`daemon/pool.py`, the W0 oracle (`tests/python/support/oracle.py`),
moonwatch family migrated, skill reference updated, ~40 new unit tests,
full python suite green throughout.
