# cadgen unification — one self-contained distribution

Working plan for an executor session. **Delete this file in the final phase** — the repo
does not keep planning documents on `develop`/`main` (standing policy in this repo).

- Base your work on **latest `origin/develop`**. PR #224 (branch
  `claude/cadgen-self-contained`) is **prior art, not a dependency** — see §0.1 for what
  to reuse from it and what it got wrong relative to this plan. The plan must execute
  cleanly whether or not #224 ever merges.
- Read `AGENTS.md` and `CONTRIBUTING.md` before starting. Branch from `develop`, PR to
  `develop`, one PR per phase (A → B → C → D), full gate run per phase.
- When a step here conflicts with the tree you find, trust the tree, keep the *intent*,
  and note the divergence in §8 (Execution log).

## 0. Goal

Make `cadgen` (already on PyPI, version-stamped from the repo `VERSION`) the one
installable distribution containing the whole CAD runtime:

- the Python artifact runtime it already has (STEP/DXF/implicit build, coordination,
  locks, freshness, snapshot CLI, catalog/inspection),
- the JavaScript it executes: the esbuilt Node builders and the headless browser render
  runtime,
- the CAD Viewer: its Python backend (today `viewer/server_py`) and its built SPA
  (`viewer/dist`), with a launcher.

Consumers, all first-class:

1. **This repo's skills** — become thin CLI shims + docs; no vendored code.
2. **Anyone running `pip install cadgen`** — the Python API, the CLIs, and
   `cadgen viewer`. This is also the viewer's ONLY distribution channel: the
   `earthtojake/cad-viewer` mirror repo and its sync machinery are **retired** (user
   decision 2026-08-12 — the mirror was added days earlier and predates the
   mega-package; with the wheel carrying the built SPA and the backend, a second synced
   channel is pure upkeep).

Explicit user decisions already made (do not relitigate):

- One mega-package now; splitting into `cadgen-core`/`cadgen-viewer` is a possible later
  step, not this one.
- Keep Node for the DXF and implicit builders. Do **not** port the DXF mesher to Python:
  the viewer re-meshes DXF live in the browser (interactive sheet-metal folding —
  thickness/bend/K-factor in `CadViewer.js` via `buildDxfPreviewMeshData`), so JS at
  build time is what keeps it ONE implementation. Same logic for implicit (GLSL is the
  source language). Snapshot stays a Playwright-driven browser. Revisiting implicit and
  snapshot is a separate follow-up the user asked to defer.
- `cadjs` and `implicitjs` stay unpublished repo-internal JS source packages (build
  inputs). Nothing installs them; their built outputs ship inside the cadgen wheel.
- The `earthtojake/cad-viewer` mirror repo + sync are retired (2026-08-12). Added in
  0.4.6, superseded by wheel distribution; archiving the GitHub repo is a user step.

### 0.1 Prior art: PR #224 (`claude/cadgen-self-contained`) — reuse judgment

That branch was written before the mega-package decision, so it targets the OLD
per-skill layout. Treat it as a parts bin:

**Reuse (cherry-pick or re-derive during Phase A — all four are proven working there):**

1. `tests/python/packages/cadgen/test_step_needs_no_node.py` — the STEP tripwire test
   (see invariant 1 for its demoted status: accidental-coupling guard, not a rule).
2. The export-CLI-as-builder pieces: `packages/cadjs/bin/implicit-export.mjs` (thin
   wrapper `import "implicitjs/cli/export"`), the `"./cli/export"` entry in implicitjs's
   exports map, and `"./scripts/export.mjs"` added to implicitjs's `sideEffects` — the
   wrapper bundles to a 20-byte shebang without that last one, silently.
3. The emitted-no-code bundler guard (in that branch's `node_builders.sh`): strips the
   shebang, fails if nothing remains. A raw size floor is wrong — one legitimate builder
   is 370 bytes.
4. `implicit_export.py` switched from walking to `implicitjs/scripts/export.mjs` to
   resolving a builder named `implicit-export.mjs` — keep that shape, but route it
   through `cadgen.assets` (§2.2) rather than #224's `node_builder_script()`.

**Superseded (do NOT replicate):**

- Emitting the export bundle to `skills/implicit-cad/scripts/packages/cadjs/bin/` and
  the matching `bundle-implicit-cad.sh` edits — Phase A emits to `cadgen/_runtime/node/`
  and Phase C deletes that whole script.
- Its early removal of implicit-cad's vendored implicitjs — subsumed by Phase C's
  blanket un-vendoring; from develop, just do it once in Phase C.

**If #224 happens to merge first:** nothing conflicts — Phase A relocates the bundle
destination, Phase C deletes the per-skill copies it committed.

## 1. Non-negotiable invariants (hold at the end of EVERY phase)

1. **Runtime resolution is call-time only.** No import-time code may resolve the node
   binary or touch `_runtime` assets — `pip install cadgen` must work with no Node
   present, and the long-lived viewer server must import light. Node ≥ 20 is otherwise a
   first-class, documented runtime dependency of the distribution (user decision
   2026-08-12): a *deliberate* design that routes more of the pipeline through Node is
   allowed.

   STEP happens to need no Node today. That is a preserved property, **not a design
   constraint**: land `tests/python/packages/cadgen/test_step_needs_no_node.py`
   (§0.1 item 1) as a tripwire against *accidental* coupling — one stray call in the
   shared generation path would break STEP in Node-less environments silently — and
   delete or amend the test in the same PR as any deliberate change, with a note.
2. **Skill CLI contracts are frozen**: argv, stdout/stderr split, exit codes, env
   knobs (`CADGEN_WARM`, `CADGEN_STRICT_LOCKS`, `PYTHONHASHSEED` re-exec in dxf, …) for
   every entry under `skills/*/scripts/`. The suites under `tests/python/skills/**` are
   the pin — they must keep passing **unmodified** except for import-path mechanics.
   One new failure mode is allowed: cadgen not installed → clear actionable error
   (previously an ImportError traceback).
3. **Viewer contract is frozen**: URL scheme (absolute dir as path + `?file=` relative),
   `/__cad/*` endpoints, default port 3245 with strict-port semantics, the launcher's
   stdout lines including the JSON `{"url",...,"action":"start"}` line, `VIEWER_*` env
   vars, artifact regeneration with progress + locks, catalog behavior (dot-dirs
   skipped). Pinned by the moved server tests + viewer JS tests + e2e sweeps.
4. **One `VERSION`**; `scripts/release/sync-version.mjs` stamps derived metadata; the
   PyPI upload happens **before** the publish-tree trim and the `main` push
   (release.yml ordering fixed in PR #223 — keep it).
5. **Publish tree rules**: no symlinks on `main` (`check-builds.sh`), gitignored paths
   never reach `main`, and after Phase C skills carry no generated runtime at all.
6. **Coordination is untouched**: fcntl generation lock, the run-id sentinel handshake
   that Node children verify before writing, NDJSON progress over the pipe, dual
   freshness authorities, content digests. Drawing packages are content-addressed —
   goldens in `tests/python/skills/dxf` must stay byte-identical.
7. **`cadgen.viewer` server modules import without OCP** (the long-lived server never
   drags OCP/build123d/ezdxf in at import; today's `server_py/artifact.py` discipline).
   `test_coordination_is_stdlib_only.py` and the moved server tests pin it.
8. **The wheel is the viewer's only distribution channel.** The
   `earthtojake/cad-viewer` mirror and its sync machinery are retired in Phase B — no
   second copy of the viewer exists to drift or to keep self-contained. `viewer/`
   becomes an ordinary internal app directory of this repo: the self-containment fence
   (`viewer/scripts/selfContained.test.mjs`) and its AGENTS.md rule existed solely for
   verbatim mirroring and are deleted with it. (The viewer's *runtime* contract is
   invariant 3; this one is about distribution.)

## 2. Target state

### 2.1 The wheel

```
cadgen/                          # packages/cadgen/src/cadgen (unchanged home)
  <existing modules>             # step_artifact, dxf_artifact, implicit_artifact,
                                 # implicit_export, step_export_target, snapshot_cli,
                                 # catalog, generation, coordination/, _internal/, ...
  cli/                           # NEW: argparse definitions moved from skill scripts,
    step_gen.py …                # one module per command, byte-compatible parsers
  daemon/                        # NEW: moved from skills/cad/scripts/cadgen_daemon
  viewer/                        # NEW: moved from viewer/server_py (same filenames:
    server.py backend.py artifact.py scanner.py worker.py worker_client.py
    cadgen_bridge.py start_viewer.py paths.py urls.py encoding.py content_types.py
    natural_sort.py save_dialog.py server_info.py __init__.py __main__.py)
  assets.py                      # NEW: runtime-asset resolver (§2.2)
  _runtime/                      # NEW: data-only (no __init__), shipped via package-data
    node/                        # esbuilt self-contained builders — COMMITTED on develop
      dxf-artifact.mjs implicit-artifact.mjs implicit-export.mjs
      implicitClosureHooks.mjs meshWorkerEntry.js package.json THIRD_PARTY_LICENSES.txt
    browser/                     # snapshot runtime — COMMITTED on develop
      snapshot-render.js render.html
    viewer/                      # built SPA — GITIGNORED on develop, built at bundle
      index.html assets/** THIRD_PARTY_LICENSES.txt
    moveit2/                     # copy of viewer/moveit2_server (best-effort; §3.5)
```

Console scripts (pyproject `[project.scripts]`, today only `cadgen-step-artifact`):
keep it; add `cadgen = cadgen.cli:main` with nested subcommands mirroring the skill
CLIs — `step {gen,artifact,export,inspect}`, `dxf {gen,artifact}`,
`implicit {gen,export}`, `snapshot` (generic, all kinds), `viewer`, `daemon`,
`moveit2`. All existing `python -m cadgen.<module>` entries keep working.
`python -m cadgen.viewer` == the launcher (today's `server_py.start_viewer` behavior).

Wheel size, measured: `viewer/dist` is **~16 MB, 12 MB of which is sourcemaps**; the
Node + browser bundles add ~2–3 MB, so the wheel lands ≈18–20 MB with maps, ~7 MB
without. PyPI's per-file cap is 100 MB — not a concern. Default: keep the maps
(installed-runtime debuggability is an existing deliberate decision); stripping them
from the wheel only is an acceptable follow-up if weight ever matters.

### 2.2 Asset resolution — `cadgen/assets.py`

One module, three resolvers, all **call-time only** (invariant 1):

| asset | order |
|---|---|
| Node builders dir | `CADGEN_NODE_BUILDERS_DIR` → legacy `CADGEN_NODE_PACKAGES` (means `<dir>/cadjs/bin`) → **dev source walk** (today's `parents[4]` logic, so an editable install in this repo runs live `packages/cadjs/bin` sources with the resolve hook) → packaged `_runtime/node` |
| Browser snapshot runtime | `CADGEN_BROWSER_RUNTIME_DIR` → explicit `runtime_dir=` arg (kept on `run_snapshot_cli`) → packaged `_runtime/browser` |
| Viewer dist | `--dist` flag → `CADGEN_VIEWER_DIST` → packaged `_runtime/viewer`; if absent (dev checkout, not yet bundled) fail with: use `npm --prefix viewer run dev`, or run `scripts/bundle/bundle.sh` |

Dev-source-first for builders is deliberate: builder JS stays live-editable in the repo.
Keep `node_resolve_register.mjs`/`node_resolve_hooks.mjs` — the dev source path still
needs them; they're tiny and already package-data. `cad_node_executable()` (env → PATH,
call-time, `NodeUnavailable` with actionable message) is unchanged.

### 2.3 Dependencies and extras

- Core deps unchanged: `build123d`, `cadquery-ocp`, `ezdxf`, `shapely`.
- NEW extra `snapshot`: `playwright`. (Extras gate *dependencies*, not files — the JS
  ships to everyone; it's small.)
- Node ≥ 20 is a documented **runtime** requirement of the distribution; today only the
  DXF/implicit builds exercise it (invariant 1: resolved at call time, never import).
- Snapshot additionally needs a browser: document `python -m playwright install chromium`
  in the SKILL.md Setup of snapshot-capable skills and in cadgen's README.

Skill `requirements.txt` (source of truth on develop) becomes **unpinned distribution
names**; `scripts/release/pin-cadgen-requirements.sh` pins them at publish:

| skill | requirements.txt (develop) |
|---|---|
| cad, urdf, srdf, sdf | `cadgen[snapshot]` |
| implicit-cad | `cadgen[snapshot]` (it has scripts/snapshot) |
| dxf | `cadgen[snapshot]` (drop the redundant `ezdxf`/`shapely` lines — core deps) |
| cad-viewer | `cadgen` |
| gcode, bambu-labs, sendcutsend, step-parts | untouched (no cadgen) |

Update the pin script: match `^cadgen(\[[a-z0-9_,-]+\])?$` → `cadgen\1==$VERSION`.
`viewer/requirements.txt` is deleted in Phase B — it existed for the packaged skill
runtime and the retired mirror; the dev backend comes from `requirements-dev.txt`'s
editable install (version == `VERSION`), which also satisfies the skills' unpinned
lines, so `pip install -r skills/*/requirements.txt` is a no-op locally — that's the
point.

### 2.4 What is committed where

| artifact | develop | built by | main / wheel |
|---|---|---|---|
| `_runtime/node/*` | committed (replaces per-skill copies) | `scripts/bundle/skills/bundle-cadgen-runtime.sh` (new; freshness-checked by `bundle.sh --check`) | shipped |
| `_runtime/browser/*` | committed (replaces 6 per-skill copies) | same | shipped |
| `_runtime/viewer/**` | **gitignored** | same script, `--viewer` stage (vite build) — runs in CI test job and in the publish job (both already run `bundle.sh --clean` before the wheel is built) | shipped; publish asserts presence |
| `_runtime/moveit2/**` | committed (small copy step) | same | shipped |

### 2.5 Repo layout after Phase C

- `skills/<skill>/scripts/` = thin shims only (a few files each). **No `packages/`, no
  `snapshot/runtime/`, no sys.path juggling.** `skills/cad-viewer/scripts/viewer`
  symlink and the generated 280-file runtime are gone.
- `viewer/` = the JS client app only: `src/`, `vite.config.mjs`, `scripts/*.mjs`
  launchers, `moveit2_server/`, docs. `server_py/` has moved into cadgen.
- Deleted: `scripts/bundle/lib/vendor.sh`, `lib/node_builders.sh` (folded into the new
  bundler), `lib/snapshot_runtime.sh`, `scripts/bundle/skills/bundle-{cad,dxf,implicit-cad,
  sdf,srdf,urdf,cad-viewer}.sh`, `scripts/dev/skills/setup-*-skill-symlink.sh` entries
  for vendored paths. `bundle-skill.sh --all` dispatches to the one cadgen-runtime
  bundler (keep the wrapper API: `--check`, `--clean`, `--print-outputs`).
- `main` drops another ~500 files (vendored cadgen ×6, snapshot runtimes ×6, cad-viewer
  runtime, builder copies): from 967 → roughly **420**.

### 2.6 External consumer story (put a short version in cadgen's README)

```bash
pip install "cadgen[snapshot]"        # python -m playwright install chromium for snapshots
cadgen step gen model.step.py         # STEP: currently needs no Node
cadgen dxf gen drawing.dxf.py         # needs node>=20 on PATH (or CADGEN_NODE)
cadgen implicit export model.implicit.js --stl
cadgen snapshot model.step.py --out shot.png
cadgen viewer --host 127.0.0.1        # serves the bundled SPA; URL path names the dir
```

Public surface = the CLIs above + the modules skills import (`cadgen.generation`,
`cadgen.snapshot_cli`, `cadgen.implicit_export`, `cadgen.catalog`, `cadgen.coordination`).
`_internal` stays internal — the viewer's `_internal` imports become intra-package.

## 3. Current → target map

### 3.1 JS runtime (sources unchanged; bundled outputs move)

| today (develop) | target |
|---|---|
| `skills/{cad,dxf}/scripts/packages/cadjs/bin/dxf-artifact.mjs` | `cadgen/_runtime/node/dxf-artifact.mjs` (one copy) |
| `skills/implicit-cad/scripts/packages/cadjs/bin/{implicit-artifact,implicitClosureHooks}.mjs, meshWorkerEntry.js` | `cadgen/_runtime/node/` |
| implicit **export**: runs UNBUNDLED from the vendored `…/packages/implicitjs/scripts/export.mjs` (the whole reason implicit-cad vendors implicitjs) | `cadgen/_runtime/node/implicit-export.mjs` — Phase A creates the wrapper + metadata (§0.1 item 2) and bundles it |
| `skills/*/scripts/snapshot/runtime/{snapshot-render.js,render.html}` (×6) | `cadgen/_runtime/browser/` (one copy) |
| `viewer/dist/**` (built at publish into the cad-viewer skill runtime) | `cadgen/_runtime/viewer/**` (built at bundle) |

Builder entry list for the new bundler:
`packages/cadjs/bin/{dxf-artifact,implicit-artifact,implicit-export,implicitClosureHooks}.mjs`
(the last created in Phase A) and `packages/implicitjs/src/lib/implicitCad/meshWorkerEntry.js`.
Keep the pinned-esbuild + lockfile-pinned three/meshoptimizer mechanics from
`node_builders.sh`; add the emitted-no-code guard (§0.1 item 3); switch
`--legal-comments` from `none` to `eof` and emit a `THIRD_PARTY_LICENSES.txt`
(MIT notices for three/meshoptimizer/gifenc).

### 3.2 Viewer backend move

`git mv viewer/server_py/<mod>.py packages/cadgen/src/cadgen/viewer/<mod>.py` for the 16
modules listed in §2.1. Then:

- Rewrite imports `server_py.` → `cadgen.viewer.` (the `sys.path.insert` +
  try/except dual-import blocks at the top of `server.py`/`start_viewer.py` die —
  the package is importable normally now).
- `cadgen/viewer/__main__.py` = today's `start_viewer` main. Add `--dist DIR` flag
  (resolution §2.2). Keep every stdout line and the JSON line identical.
- `cadgen_bridge.py`: default worker/cold interpreter becomes `sys.executable`
  (`VIEWER_CAD_PYTHON` still wins); the `cadgen_pythonpath` find-up machinery can go —
  cadgen is importable in-process. Keep the startup probe (OCP/build123d/cadgen
  importable) and its exact error text.
- Tests: `git mv viewer/server_py/tests tests/python/packages/cadgen/viewer` and update
  `scripts/test/test-python.sh` (the "CAD Viewer backend Python tests" block: start dir
  and `PYTHONPATH` → `packages/cadgen/src`). The cross-process lock/SIGKILL test and the
  no-OCP-at-import property must survive the move.
- `viewer/scripts/start-viewer.mjs` (the in-repo prod-path launcher): spawn
  `python -m cadgen.viewer --dist "$appRoot/dist" …` instead of `-m server_py.start_viewer`.
  The backend comes from the interpreter's installed cadgen (dev: the editable install
  via `requirements-dev.txt` / `cad-python.mjs`'s find-up of `packages/cadgen/src`);
  the existing startup probe (cadgen/OCP importable, actionable error text) is the
  missing-install failure mode. Delete the `viewer/packages/cadgen` symlink and
  `viewer/requirements.txt` — nothing consumes them once the runtime copy and the
  mirror are gone. `viewer/package.json` `"serve"` → `python3 -m cadgen.viewer.server`.

### 3.3 Skill CLI shims

Move each parser module into `cadgen/cli/` **verbatim** (parser definitions unchanged):

| skill script | cadgen.cli module |
|---|---|
| `skills/cad/scripts/gen/cli.py` | `cadgen/cli/step_gen.py` |
| `skills/cad/scripts/{artifact,export,inspect,snapshot}` | `cadgen/cli/step_{artifact,export,inspect,snapshot}.py` (inspect includes `inspect_refs`) |
| `skills/dxf/scripts/{gen,artifact,snapshot}` | `cadgen/cli/dxf_*.py` |
| `skills/implicit-cad/scripts/{gen,snapshot}` | `cadgen/cli/implicit_*.py` |
| `skills/{urdf,srdf,sdf}/scripts/snapshot` — **verified the only cadgen importers in those skills** (discover with `git grep -l 'from cadgen\|import cadgen' skills \| grep -v '/packages/'` — note: a `skills/*/scripts` pathspec silently returns nothing) | snapshot shims only. Their `urdf`/`srdf`/`sdf` generators and `validate` commands are skill-local Python with **no cadgen dependency and stay in the skill** — the thin-shim rule applies to cadgen-backed commands, not to all skill code |
| `skills/implicit-cad/scripts/export.mjs` (Node shim; today spawns the vendored implicitjs CLI) | becomes a passthrough onto `python -m cadgen.cli.implicit_export_js`, a ~10-line module that execs node on the packaged `implicit-export.mjs` with argv untouched — argv/stdio/exit codes preserved exactly |
| `skills/cad/scripts/cadgen_daemon/` | `cadgen/daemon/` (env contract `CADGEN_WARM`/`CADGEN_DAEMON_CHILD` unchanged; staleness keying moves from watched source trees to `cadgen.__version__` + shim-dir mtimes — preserve restart semantics) |

Shim template (replaces each `__main__.py`; the cad shims keep their warm-daemon
pre-hook, dxf keeps its `PYTHONHASHSEED` re-exec, **before** the cadgen import):

```python
#!/usr/bin/env python3
"""Thin shim over the cadgen distribution. Contract pinned by tests/python/skills/<skill>."""
import sys

try:
    from cadgen.cli import step_gen as _cli
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n")
    raise SystemExit(3)

if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
```

Version guard: if the sibling `requirements.txt` pins `cadgen…==X` (published copies do)
and `cadgen.__version__ != X`, hard-error naming both versions and the pip fix;
unpinned (develop) skips the check. Stdlib-only, no new deps.

Snapshot shims: keep passing their `kinds` and `prog`; pass `runtime_dir=None` so the
packaged browser runtime resolves (§2.2).

### 3.4 Deletions (Phase C unless noted)

Vendored trees `skills/*/scripts/packages/**`; `skills/*/scripts/snapshot/runtime/`;
`skills/cad-viewer/scripts/viewer` symlink + its bundler (Phase B); the mirror
machinery — `scripts/viewer/sync-cad-viewer-repo.sh`,
`.github/workflows/sync-cad-viewer.yml`, the `sync-cad-viewer` release.yml job,
`viewer/scripts/selfContained.test.mjs`, `viewer/requirements.txt`, the
`viewer/packages/cadgen` symlink (all Phase B); `vendor.sh`,
`snapshot_runtime.sh`, per-skill bundle scripts; per-skill symlink setup scripts;
`sync-version.mjs` entries for deleted paths (viewer/packages/*, skill copies);
`check-builds.sh` keeps its no-symlink sweep over `skills/` but its outputs list shrinks
to the cadgen runtime dirs. `requirements-dev.txt` comment block about generated
editable packages. This plan file (Phase D).

### 3.5 Not moving

`packages/cadjs`, `packages/implicitjs` (JS sources; still symlinked into `viewer/packages/`
for vite dev/build; `viewer/packages/cadgen` goes away, see §3.2). `viewer/src` + vite config +
e2e scripts. `viewer/moveit2_server` stays the source of truth in `viewer/` (nothing needs
it); the wheel carries a copy under `_runtime/moveit2` and `cadgen moveit2
setup|check|serve` passes through to its shell scripts with
`MOVEIT2_SERVER_REPO_ROOT` defaulting to cwd — best-effort parity with today's packaged
`npm run moveit2:*`. `models/`, `docs/`, release workflows (beyond §5).

## 4. Phases

Each phase: own branch, own PR to `develop`, gates green before the next starts.
B and C both depend on A but **not on each other** — either order (A→B→C or A→C→B) is
fine. Run `scripts/dev/setup-symlinks.sh` after any bundle script run — bundling
materializes dev symlinks (known footgun).

**Global policy tests encode the OLD doctrine and must be updated deliberately, in the
phase that breaks them, never weakened silently** (all under `tests/python/global/`):
`test_skill_self_containment.py` (rewrite in Phase C to the new rule: no cross-skill or
repo-module imports; cadgen comes from the pinned distribution),
`test_node_builder_bundles.py` (pins per-skill builder bundles AND `node_package_root()`
behavior — replace across Phases A/C with a resolution-order unit test + the
wheel-contents check), `test_pin_cadgen_requirements.py` (update with the Phase C regex
change), `test_release_version_paths.py` (touched wherever `sync-version.mjs` entries
change). `test_cli_stream_contract.py` spawns `skills/cad/scripts/gen` and must keep
passing **unmodified** — it is the shim-compatibility gate, not an obstacle.

### Phase A — consolidate the JS runtime into the wheel

0. Land the reuse items from §0.1 against develop: the STEP-no-Node test; the
   `implicit-export.mjs` wrapper in `packages/cadjs/bin` + implicitjs exports-map entry
   `"./cli/export"` + `"./scripts/export.mjs"` in its `sideEffects`; and switch
   `implicit_export.py` off the `IMPLICIT_EXPORT_CLI` path walk onto builder-name
   resolution. Verify the test both passes and still FAILS when a
   `cad_node_executable()` call is injected into `generate_step_targets`.
1. Add `scripts/bundle/skills/bundle-cadgen-runtime.sh` (fold `node_builders.sh` +
   `snapshot_runtime.sh` mechanics): stages `--node` (builders → `_runtime/node`),
   `--browser` (snapshot runtime → `_runtime/browser`), `--viewer` (vite build →
   `_runtime/viewer`, used by CI/publish), `--moveit2` (copy). Register in
   `bundle-skill.sh`; `--print-outputs` lists the committed dirs (node, browser,
   moveit2); `--check` verifies those always and viewer-dist only when present or when
   `CADGEN_REQUIRE_VIEWER_DIST=1` (set by CI/publish).
2. `.gitignore`: `packages/cadgen/src/cadgen/_runtime/viewer/`.
3. `cadgen/assets.py` with the §2.2 resolution; rewrite `node_builder_script()` and
   `run_snapshot_cli`'s runtime default to use it (keep legacy walk as the dev-source
   step). `pyproject.toml`: package-data `cadgen = ["py.typed", "_runtime/**"]` —
   **verify with the wheel-contents check**: `**` handling in setuptools package-data
   has version quirks; if nested files (e.g. `_runtime/viewer/assets/*`) are missing
   from the wheel, fall back to `include-package-data = true` + a `MANIFEST.in` with
   `graft src/cadgen/_runtime`, or enumerate per-directory globs.
4. Add `_runtime` to `vendor.sh` excludes (transitional: vendored skill copies must not
   duplicate it; the per-skill builder/runtime copies still exist until Phase C).
5. Licensing: `--legal-comments=eof` + `THIRD_PARTY_LICENSES.txt` in `_runtime/node`.
6. `scripts/release/check-wheel-contents.sh`: build the wheel, `unzip -l`, assert the
   §2.1 required paths. Wire into release.yml beside the existing cadgen build step
   (which already runs before the trim) and into test.yml after the bundle step.

Gates: `bundle.sh --check` and `setup-symlinks.sh --check` clean; full
`scripts/test/test.sh` (PYTHON_BIN=repo venv); STEP-no-Node test; a DXF gen + implicit
export smoke in a temp dir; wheel-contents check passes locally (`CADGEN_REQUIRE_VIEWER_DIST=1`
after a full bundle).

### Phase B — viewer into cadgen

Steps in §3.2, plus: rewrite `skills/cad-viewer/SKILL.md` (launch = `cadgen viewer …`,
same URL/JSON contract), delete the `scripts/viewer` symlink + `bundle-cad-viewer.sh`
(its vite-build stage already moved to the Phase A bundler; the viewer-packages
materialization dies with it), drop the `skills/cad-viewer/scripts/viewer` path from
every outputs list. Mirror retirement (invariant 8): delete
`scripts/viewer/sync-cad-viewer-repo.sh`, `.github/workflows/sync-cad-viewer.yml`, and
the `sync-cad-viewer` job in `release.yml` (remove it from `tag-release.needs`); delete
`viewer/scripts/selfContained.test.mjs` and the viewer-self-containment rule/sections
in AGENTS.md and CONTRIBUTING — including AGENTS' release-flow paragraph naming the
Sync workflow and CONTRIBUTING's "Mirroring the CAD Viewer repo" section; delete
`viewer/requirements.txt` and the `viewer/packages/cadgen` symlink. Do **not** delete
`scripts/dev/skills/setup-cad-viewer-skill-symlink.sh` wholesale: it also manages
`viewer/packages/{cadjs,implicitjs}`, which survive as vite build inputs — it just
loses the `viewer/packages/cadgen` and `skills/cad-viewer/scripts/viewer` links. Rewrite `viewer/README.md`: install =
`pip install cadgen && cadgen viewer`; in-repo loops stay `npm --prefix viewer run dev`
(HMR) and `npm --prefix viewer run start` (prod path against a local build).
**USER STEPS** (flag, don't do unprompted): archive the `earthtojake/cad-viewer` GitHub
repo — or push a final pointer README — and delete the now-unused
`CAD_VIEWER_SYNC_TOKEN` secret. Update `viewer/docs/backend.md` paths.

Gates: full suite; viewer JS tests; e2e: `npm --prefix viewer run dev` sweep
(`scripts/e2e-format-sweep.mjs`) AND prod path `bundle … --viewer` then
`python -m cadgen.viewer --port <n>` → open a fixture, curl `/__cad/catalog`;
installed-wheel viewer smoke: after a full bundle, build the wheel, install it into a
scratch venv (`--system-site-packages` over the repo venv), and from an empty directory
run `cadgen viewer --port <n>` → curl the catalog and the page.
The packaged-runtime `npm run start` bug (missing `scripts/`) disappears with the
runtime — note it as fixed-by-deletion.

### Phase C — skills stop vendoring

Per skill (cad, dxf, implicit-cad, urdf, srdf, sdf): §3.3 moves + shims, §3.4 deletions,
requirements per §2.3, SKILL.md gains a Setup section (`python -m pip install -r
requirements.txt`, plus `python -m playwright install chromium` where snapshot-capable,
plus "Node ≥ 20 on PATH" for dxf/implicit-cad). Update `test-python.sh` skill paths
(vendored src → `packages/cadgen/src`), `pin-cadgen-requirements.sh` regex (§2.3),
`check-builds.sh`, `setup-symlinks.sh`. Rewrite the AGENTS.md skill-self-containment
rule to: skills must not import other skills or repo modules; shared runtime comes from
the pinned `cadgen` distribution named in each skill's `requirements.txt`; skill scripts
must fail with the install hint when it is missing. Update CONTRIBUTING's layout/bundle
sections to match.

Gates: full suite; per-skill CLI smoke in a temp dir (gen/artifact/export/snapshot as
applicable); **installed-mode smoke** (`scripts/test/test-installed.sh`, new): build the
wheel, create a venv with `--system-site-packages` over the repo venv (OCP reuse),
`pip install dist/*.whl --no-deps`, then from an empty cwd with the repo hidden run
`cadgen step gen`, `cadgen dxf gen`, `cadgen implicit export`, `cadgen viewer --port` +
curl. Wire it into test.yml after the bundle step.

### Phase D — release hardening + docs + cleanup

Extras in pyproject (`[snapshot]`); viewer-dist license file; release rehearsal
(`gh workflow run release.yml -f bump=none -f base_branch=<branch> -f
target_branch=build-test`) — then verify the build-test tree: skills thin, no vendored
copies, no symlinks, README/AGENTS/CONTRIBUTING consistent; wheel-contents green in the
rehearsal log. Delete the legacy source-walk in `assets.py`? **No** — keep it (dev
path). Delete this plan file. Update the user's memory notes if the session has them.
Real release only on explicit user approval (they pick the bump).

Rollback: each phase is one PR; revert the merge commit. No data migrations anywhere —
artifact formats and digests are unchanged (invariant 6).

## 5. CI / release deltas (summary)

- `test.yml`: unchanged triggers; after its bundle step add wheel-contents +
  installed-mode smoke (Phase A/C). Wheel steps need `python -m pip install build`
  first (the CI env does not carry it).
- `release.yml`: cadgen build/upload already precedes trim (#223) — add
  `check-wheel-contents.sh` (with `CADGEN_REQUIRE_VIEWER_DIST=1`) right before the
  upload. `PUBLISH_TREE_REMOVED_ROOTS` unchanged.
- `pin-cadgen-requirements.sh`: add the bare-`cadgen[extra]` pin rule (§2.3).
- `sync-version.mjs`: drop entries for deleted copies; nothing new to stamp
  (`_runtime` carries no versions; the viewer dist inherits its stamp from
  `viewer/package.json` at build).
- `release.yml`: delete the `sync-cad-viewer` job and its edge in `tag-release.needs`
  (Phase B). Deploy Docs is untouched.
- `check-builds.sh`: outputs shrink; keep the symlink sweep.

## 6. Footguns (read before touching anything)

1. `bundle.sh`/`bundle-skill.sh` **materialize dev symlinks** — always finish with
   `scripts/dev/setup-symlinks.sh` and clear `viewer/node_modules/.vite` before dev-server
   work.
2. esbuild **silently tree-shakes side-effect-only imports** (the 20-byte-bundle
   incident: a `sideEffects` list that omits the entry file, exit code 0, file exists,
   every check passes) and **silently externalizes unresolvable dynamic imports**. The
   emitted-no-code guard (Phase A, §0.1 item 3) exists for the first. Grep bundles for
   bare `from"…"` specifiers after changes.
3. JS test runners need **Node 22** (Node 24 breaks the `--experimental-default-type`
   flag; CI uses 22).
4. Publish `git add -A` honours `.gitignore` — a gitignored path can never reach `main`,
   but **setuptools does not read .gitignore**: gitignored `_runtime/viewer` still lands
   in the wheel when present on disk. That asymmetry is load-bearing; don't "fix" it.
5. Codex plugin installs **silently drop symlinks** — nothing under `skills/` on `main`
   may be one (check-builds enforces).
6. Python for tests: `PYTHON_BIN=<repo>/.venv/bin/python` (worktrees have no venv; OCP
   lives there).
7. The viewer catalog **skips dot-directories**; don't stage e2e fixtures under `.foo/`.
8. Ports are strict (3245 default) — pass `--port <free>` in every e2e; never reuse a
   running viewer from another checkout.
9. When moving `server_py`, preserve the **lazy-import discipline** in `artifact.py`
   (no OCP at import) and the stderr/stdout fd arrangement in the worker (C-level stdout
   is redirected to stderr on purpose).
10. `git -C <path>` everything, or `cd` per command — the Bash tool's cwd persists and a
    stale cwd in the main checkout has already produced one bad mega-commit this effort.

## 7. Out of scope / follow-ups

- Splitting the mega-package (`cadgen-viewer` etc.) — later, user-initiated.
- Revisiting implicit + snapshot architecture — user deferred.
- Publishing `cadjs`/`implicitjs` to npm; PyPI'ing the moveit2 server.
- The docs site keeps building from repo source (`packages/cadjs` via tsconfig paths) —
  untouched by this plan.

## 8. Execution log (append per phase)

| date | phase | PR | result / divergences |
|---|---|---|---|
