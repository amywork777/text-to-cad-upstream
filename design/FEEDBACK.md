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

8. **FIXED — dev-mode backend no longer requires a built client.** The Vite dev proxy already marks its spawn (`VIEWER_AGENT_START_MODE=dev`); the backend now tolerates a missing dist under it (Vite serves the client from source), and the AssetMissing error no longer suggests running the dev server that is failing. Was: `vite
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

9. **FIXED — spans can no longer be orphaned at the artifact-job boundary** (`_run_artifact_jobs` supplies a default logger; verbosity alone decides printing), and a regression test asserts the export spans fire under `--verbose`. Also: metadata injection now takes an entity-count hint from the STEP writer's own model, replacing the full-file scan+rewrite — measured 1.23s → 21ms on a 121MB export. Was: The STEP-export spans
   existed but the call site dropped the logger (fixed on this branch);
   nothing guards new spans against the same fate. Easy win: a tests/policy
   check that `logger.timed` call sites are reachable with a logger, or a
   default logger at the artifact-job boundary.

## Standalone-viewer / DXF migration follow-ups (2026-08-27)

12. **Stale imported-DXF package directories linger.** Pre-migration, imported
    `.dxf` files got `__cadgen__/models/<name>.dxf/` drawing packages; nothing
    reads them now and nothing deletes them (only `.dxf.py` record writes clear
    legacy payloads in their own dir). Harmless clutter — a cleanup pass or a
    scanner-side GC note would tidy old checkouts.

13. **`skills/dxf` lost its `scripts/artifact` command by design** (an imported
    `.dxf` needs no build), and `cadgen dxf artifact` is gone from the CLI
    registry. Any external docs/automation invoking them must move to
    `scripts/gen` / direct rendering. Flagged here because the skill surface
    changed, not just internals.

14. **Dimensioned-drawing snapshots are now possible but not implemented.** The
    old pipeline could not snapshot a document profile at all (no preview.glb);
    the new one refuses with "no cut geometry". The client renders documents as
    2D line work — teaching `dxf-mesh.mjs`/snapshot a 2D line-render mode would
    close the gap the package era left.

15. **DXF sibling outputs are now repo-visible for generated drawings** (gen
    always writes `<name>.dxf`). Like the generated `.step` siblings, they are
    untracked build outputs today; decide whether fixtures should commit them
    (LFS) or a `.gitignore` convention should hide generated siblings.

16. **The `-o` export identity metadata embeds a path relative to the output**,
    so exporting the same drawing to two locations produces different bytes
    (sibling writes are byte-deterministic; renamed outputs differ only in the
    identity comment). Expected, but worth remembering when comparing exports.

17. **Degraded-mode advisory flags (`stale`, `busy`) have no client UI slot.**
    The artifact status API now reports honest staleness in no-cadgen mode
    (`stale` + `staleReason` on ready responses), matching the long-standing
    `busy` flag — but neither renders anywhere. A small badge in the file
    sheet's status section would surface both.

## WASM import follow-ups (2026-08-27)

18. **`XCAFDoc_ColorTool.GetInstanceColor` is unbound in the prebuilt
    opencascade.js**, so the import twin's shape-color fallback tries
    `GetColor(shape, type)` only (`stepImport.mjs`, `colorFromShape`). The
    label route covers instance colors on every corpus/parity fixture so far;
    if a vendor STEP surfaces wrong per-instance colors under WASM import,
    look here first (fix = custom ocjs build).

19. **Label names under WASM import ride an XmlXCAF save.** `TDataStd_Name.Get`
    is also unbound, so `stepImport.mjs` saves the XCAF doc to MEMFS as
    XmlXCAF once per import and regex-indexes `<TDataStd_Name>` by label
    entry. Correct on everything tested, but it serializes the whole document
    — avoidable cost on very large vendor files; a custom ocjs build exposing
    `Get` would delete the workaround.

20. **WASM import progress has no denominator surface.** The child process
    reports phase lines on stderr, but the status poll returns no `progress`
    for WASM imports, so the client shows an indeterminate spinner for what
    can be minutes on 100MB-class files. Wiring importCli's stderr phases into
    a progress record (the shape render_ops writes) would light up the
    existing bar.

21. **Python `round()` vs JS rounding at exact half-thousandths.** The
    adaptive-resolution twin rounds hints (and the >500mm scale-floor
    tolerance) with `Math.round(v*1000)/1000` where Python banker's-rounds; a
    value landing exactly on a .0005 boundary could differ by 0.001 and, for
    the scale floor only, flip a freshness comparison once. Vanishingly
    unlikely on real geometry; noted so a one-off "Python rebuilds a
    JS-imported package once" report has a suspect.

22. **Concurrent WASM imports are serialized in-process only.** `cadgenOps`
    keys in-flight imports by package dir, which covers one server; two viewer
    instances importing the same STEP concurrently rely on atomic per-file
    writes rather than the native generation lock. Both results are
    equivalent, so the race is benign — but it is not lock-coordinated with
    native builds.

## Static-viewer follow-ups (2026-08-28)

23. **The viewer lost every export affordance by design** (toolbar dropdown,
    context-menu export items, client-side STL/GLB/3MF serialization): the
    CLIs are the only exporters now. If users miss one-click "save an STL of
    what I'm looking at", the clean re-entry point is a CLI-parity export
    (see the tessellator-unification discussion) — not a viewer-side code
    path.

24. **Generated entries no longer auto-build on open.** A `.step.py`/`.dxf.py`
    with no artifact shows "run `python scripts/gen <source>`" instead of
    silently generating. Docs/skills that describe open-to-build behavior
    should be swept when next touched.

25. **The `generating` badge is now advisory** (status-record freshness window,
    20s): a SIGKILLed CLI build can show a lingering badge for up to that
    window, and a build phase silent for longer than it drops the badge until
    the next progress event. Cosmetic by construction — the viewer takes no
    action on the state.

26. **`cadgen.coordination.snapshot()` has no production caller** (the viewer
    no longer reads the lock; producers use their own paths). Kept as the
    kernel-truth read for contended-build reporting and the lock-state suite;
    if a future cleanup wants it gone, check test_generation_lock_state.py
    first.

## Unified-tessellation follow-ups (2026-08-28)

27. **Phase 5 (viewport LOD) is designed but not built.** Phases 0-4 of
    `design/unified-tessellation.md` shipped (one tessellator for render and
    export, OCCT meshes nothing); Phase 5 — zooming a component
    re-tessellates it at finer tolerance from its exact surfaces — was
    deliberately scoped out. The groundwork is in place: the component mesh
    cache is already keyed the way LOD needs
    (`~/.cache/cadgen/meshes/<cid>-l<chord>-a<angle>.tess`), though the
    viewer does not read it yet (only `bin/mesh-export.mjs` does). The open
    design questions are the re-tessellation trigger (zoom thresholds vs
    per-component screen-space error, plus debounce so orbiting does not
    thrash), cancellable/prioritized worker re-tessellation, and a swap-in
    path that does not drop frames on 2M-triangle models. This is the
    render-quality ceiling the unified architecture exists to reach.

