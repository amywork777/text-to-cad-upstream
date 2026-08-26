# Interface feedback log (CLI / viewer)

Issues, redundancies, and easy wins in the existing interfaces, observed
while executing `design/production-architecture.md`. Append-only; each item
notes where it was hit. None of these are fixed by that plan unless the
entry says so.

## CLI

1. **FIXED — `inspect refs` accepts fused entry#ref targets.**
   `refs planetary_gear_assembly.step.py#o1.2` fails with "Invalid STEP/CAD
   entry target", while `refs planetary_gear_assembly.step.py '#o1.2'`
   works. The fused form is exactly what the viewer's "Copy
   `model#o1.6`" button hands users. Easy win: split on the first `#` in
   the target argument, or error with a hint showing the split form.

2. **FIXED — `--json` accepted (no-op) on every inspect subcommand.** `inspect refs` prints JSON by
   default and has no `--json` flag; `gen` has `--json`. Attempting
   `refs ... --json` errors. Easy win: accept (and ignore) `--json` where
   output is already JSON, or add it uniformly.

3. **FIXED — `python -m cadgen.cli.step_inspect` works** (was a package without `__main__`); so
   `python -m cadgen.cli.step_inspect` fails; other verbs are modules.
   Trivial win: add `__main__.py` shims uniformly.

4. **FIXED — warm-by-default everywhere.** All five skill shims now match the `cadgen` front door (`CADGEN_WARM=0` is the single opt-out); daemon docstring unified. Was: `cadgen <verb>`
   is warm-by-default (`CADGEN_WARM=0` opts out) while all five
   `skills/cad/scripts/*` shims are opt-in (`CADGEN_WARM=1`), and
   `daemon/__init__.py`'s docstring says both. One default, one doc.
   (The session manager in the production plan will force this decision.)

5. **FIXED — stale flag name in docs**: `generation_spec.py`'s
   `_spec_requests_extra_outputs` docstring says `--write-step`; the flag
   is `--write`.

6. **FIXED — `--write` now has a closure-keyed reuse fast path.** Repeat exports of unchanged source print "step export is current; reusing" and cost ~0.01s; exporting the same state to a NEW path copies the verified file (~0.02s) instead of rebuilding; records are variant-shaped (per closure) and stored with model-relative keys (package portability). Fixing this also surfaced a real pre-existing defect: the recorded source closure was based on `step_path.parent`, so an explicit `--write <path>` re-based every recorded relpath at the OUTPUT location — the same source hashed differently depending on where its export was written, silently defeating closure-keyed freshness for explicit-output builds. Closure capture and validation now base on the generator's folder. Was: Export always re-runs
   the generator even when the sidecar and package are current (by design —
   STEP bytes need live shapes — and now cheap with the op cache), but the
   CLI could say "step is current; reusing" when the source closure matches
   a previously exported file's recorded hash. Cheap UX win, optional.

7. **Model child imports depend on CWD being on `sys.path`.**
   `import _materials`-style sibling imports in children resolve when the
   CLI runs from the model dir (stdin/`-c` puts `''` on sys.path) and break
   when a script file drives the same load from elsewhere. Fixed
   structurally by `cadgen.compose.child_entry` (production plan W3), which
   owns the child's import context.

## Viewer

8. **Dev server hard-requires a built client to exist somewhere.** `vite
   dev` spawns the Python backend, which fails startup validation when
   `packages/cadgen/src/cadgen/_runtime/viewer` is absent — in a worktree
   the error suggests running the dev server *that is already being run*.
   Easy win: skip the dist check when launched by the dev proxy
   (`CADGEN_VIEWER_DIST` env is the workaround today).

## Pipeline defects found during the migration (fixed on this branch)

10. **Selector extraction silently re-meshed every component at its own
    defaults.** `build_component_glb_from_shape` meshed at the requested
    deflections with `relative=False`, then `extract_selectors_from_scene`
    (called without options) re-meshed at `relative=True` defaults — doubling
    OCCT meshing on every build AND shipping GLB triangles that ignored the
    deflections the caller passed. Fixed by handing extraction the build's
    exact mesh options (37 real meshes for 37 components, was 74);
    `STEP_PACKAGE_VERSION` bumped for the byte change. Lesson for interfaces:
    functions that "ensure meshing" as a side effect of an unrelated default
    argument make tolerance overrides unverifiable — extraction should have
    required explicit options from day one.

11. **`record_first_party_execution` audit hook could re-enter through
    sysconfig's lazy init** and crash with a confusing AttributeError when
    the first capture in a process happened outside the generation runner.
    Fixed by pre-warming the exclusion roots before any capture window.

## Measurement/diagnostics

9. **`--verbose` timing spans are easy to orphan.** The STEP-export spans
   existed but the call site dropped the logger (fixed on this branch);
   nothing guards new spans against the same fate. Easy win: a tests/policy
   check that `logger.timed` call sites are reachable with a logger, or a
   default logger at the artifact-job boundary.
