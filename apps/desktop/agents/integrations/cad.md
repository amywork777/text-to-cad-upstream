# CAD integration

Hardcore is the thread-first desktop shell for Text-to-CAD. It lives at `apps/desktop` inside
[earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) and runs on that
repository's canonical resources directly:

- `apps/viewer` — Jake's CAD Viewer (React client, stdlib-only Python server).
- `packages/cadgen` — the `cadgen` distribution: `@step` recipes, the warm build daemon, the
  content-addressed cache, and the `cadgen` inspection doors.
- `packages/cadgen-js` — the shared render runtime, bundled into the viewer client at build time.
- `skills/` — the agent skills, installed into Codex and Claude Code as the `cad@text-to-cad`
  plugin.

There is no vendored Text-to-CAD copy, no second viewer runtime, and no desktop-owned cache or
daemon. The desktop keeps its existing Electron shell, ACP sessions, Claude/Codex routing, and
design system; the CAD adapter under `src/main/host/cad/` is the only part that knows where the
canonical resources are.

## Locating the canonical tree

`src/main/host/cad/text-to-cad-layout.ts` resolves the tree once per call:

1. `HARDCORE_TEXT_TO_CAD_ROOT`, when set.
2. `Contents/Resources/text-to-cad` beside a packaged app.
3. The nearest ancestor of the app that carries `VERSION`, `packages/cadgen/pyproject.toml`,
   `skills/cad/SKILL.md`, and both plugin manifests — the monorepo root in a checkout.

A checkout uses `apps/viewer` (kind `repository`); a packaged bundle uses the cad-viewer skill's
materialized runtime at `skills/cad-viewer/scripts/viewer` (kind `bundle`), which is the same client
and server laid out the way Jake publishes them. Nothing is inferred from cache directories or
adjacent metadata files.

Run the setup and checks from `apps/desktop`:

```bash
pnpm cad:setup    # runtime + viewer client + provider plugins
pnpm cad:check    # report only
pnpm cad:test     # Jake's selected suites, the viewer launch smoke, and a generate/validate smoke
```

`tooling/scripts/setup-cad.mjs` builds `apps/viewer/dist` when it is missing (npm, from
`packages/cadgen-js` and `apps/viewer`), prepares the Python runtime, and registers the plugin.
The Python runtime is, in order: `CAD_DESKTOP_PYTHON`, a checkout's own `.venv` when it imports
cadgen from `packages/cadgen`, or a managed venv under the app's user data installed from
`packages/cadgen` with `tooling/cad-runtime-constraints.txt` as the dependency lock (editable in a
checkout). At runtime `HARDCORE_CAD_PYTHON` overrides the same choice.

Provider plugins are installed from a filtered, symlink-free staging copy under the runtime root
(`plugins/text-to-cad`): manifests, `skills/`, `LICENSE`, and `VERSION`, with the cad-viewer skill's
runtime materialized as `dist/` + `server/` only. Codex `plugin add` drops symlinks silently and both
provider caches copy whatever they are pointed at, so the develop-layout symlink and a repository
full of `node_modules` must never be the marketplace source. The desktop never launches that copy.

## Product model

The thread is the entry point. A user opens a project folder and can run many independent threads in
parallel. A thread may create or edit any relevant STEP, drawing, assembly, analysis, document, or
supporting file in that folder. The primary layout is:

```text
projects and threads | active conversation | artifacts and viewer
```

Artifact tabs belong to the selected thread. Opening an existing CAD file opens its canonical STEP
directly in the artifact area, served by the CAD Viewer for that thread's workspace. Advanced file
browsing remains the desktop's ordinary project-file UI.

## Canonical artifact lifecycle (cadgen 0.5)

The accepted on-disk STEP and its recorded SHA-256 are canonical model state. A plain `.py` recipe
that decorates one function with `@step` is the optional source that can rebuild it. `<name>.step.py`
is legacy: view-only until renamed by hand (cadgen 0.5 removed its migration codemod; see
`docs/migrating-0.4-to-0.5.md` at the repository root).

Every geometry-changing turn follows the same lifecycle:

1. Hash and back up the accepted STEP, its optional `.step.json` sidecar, and the linked recipe.
2. Let the selected agent edit files, or apply the user's explicit recipe edit in the source editor.
3. Run the recipe through the one v0.5 source door — `python <recipe>.py --json` — with cadgen's
   warm daemon and content-addressed cache on their defaults and never `--force`; cadgen's own
   freshness gate decides whether anything rebuilds.
4. Validate the resulting STEP independently with `cadgen step inspect refs` and
   `cadgen step inspect validate`.
5. Accept and reload only the validated on-disk artifact.
6. Restore the previous STEP, sidecar, and recipe after failure, interruption, or invalid geometry,
   and forget cadgen's records-tier entries for that artifact (`records/<key>.source.json` and
   `<key>.step-export.json`). cadgen's doors resolve a generated document through its export ledger,
   so after a restore they would otherwise validate the rejected output instead of the bytes on
   disk; without the records the STEP reads as an import and the next recipe run rebuilds once.
   In-flight recipe runs are terminated when the app exits so an orphaned build cannot overwrite the
   accepted STEP later.

Agents and in-app terminals see that runtime: the login-shell environment the desktop hands to its
workers carries the CAD interpreter's directory first on PATH (`withCadRuntimeOnPath`), so `python`,
`pip`, and `cadgen` resolve to the checkout venv in a repository or to the managed runtime in a packaged
app. Without it an agent following the CAD skill in a fresh project finds no cadgen and pip-installs its
own copy, which fails inside a network-less sandbox and duplicates the runtime the app already provisioned.

Opening, previewing, and restart recovery are read-only: they hash and inspect the STEP and never run
Python. A recipe edit alone never overwrites a newer STEP; only an explicit rebuild does, and its
output is accepted only after validation.

The recipe behind an accepted STEP is resolved, in order of trust, from the desktop's persisted
model catalog, from cadgen's own provenance record
(`<cache>/records/<sha256(resolved artifact path)[:24]>.source.json`, verified both ways against the
recipe's declared `out=`), and from the legacy `.step.py` sibling. A same-stem `.py` beside an
imported STEP is never assumed to own it. The `.step.json` sidecar carries declarations (kinematics,
animation, mesh exports) and is backed up and restored with the STEP; it is never source identity.

## Viewer ownership

Jake's viewer owns the viewport, topology tree, measurement, references, display controls, pose
controls, and per-file rendering. The desktop starts one server per workspace directory with
`python server/main.py --host 127.0.0.1 --json` from that directory, reads the launcher's
`{url, port, action}` line, and embeds `http://127.0.0.1:<port>/?file=<workspace-relative path>`.
The launcher owns ports and reuse: `action: "reused"` means another launch already serves that
directory at the same code, and the desktop tracks that port without owning a process to stop.
Health is `GET /__cad/server` with `rootPath` equal to the workspace.

The desktop does not script the viewer: there is no injected CSS or DOM, no reading of React
internals, and no polling of viewer state. Selections reach the chat through the viewer's own Copy
Reference and Copy Link actions; screenshots use Electron's webContents capture. When the accepted
STEP changes, the desktop reloads the page.

## Native feature-tree contract

Hardcore previously injected a source-backed feature tree and parameter sliders into the viewer's
DOM. That bridge was removed with the move into this repository; the last version is
`amywork777/hardcore@cb70246a40` (`src/core/features/cad/browser/cad-viewer-integration.ts`,
`cad-history-panel.tsx`, `cad-agent-panel.tsx`) and the desktop import commit preserves it in this
repository's history. What stays is the portable payload: the versioned `designHistory` descriptor
in `src/core/features/cad/api/cad-design-history-descriptor.ts`, its checked-in v1 fixture, and the
source parser in `cad-source-history.ts`.

The descriptor binds history to both `sourceHash` and `stepHash`, carries exact source spans,
numeric editability, sketch planes/transforms/dimensions when known, and exact cadgen/viewer selector
references. Feature IDs are deterministic but revision-local. To become a native viewer extension it
needs, in `apps/viewer`, a typed extension point that accepts this descriptor, renders it beside the
topology tree, and returns edit requests through a host callback; the desktop stays the owner of edit
authorization, source updates, rebuild, validation, rollback, and artifact acceptance, and the viewer
never writes source or accepts geometry on its own. Until then, recipes are edited in the desktop's
general source editor and rebuilt through the lifecycle above.

## Artifacts written by any agent

Nothing in the app knows which agent wrote a file, and a Codex or Claude
subagent writes into the same workspace as its parent. `CadTaskRunLifecycle`
therefore watches every conversation in the task: when an agent stops working,
`listCadArtifacts` (a host-side walk that skips runtime, cache, and dependency
folders) returns the model artifacts written since that turn started, and
`planCadArtifactReveal` decides what to do with the ones the catalog does not
already track. With no CAD tab open the first model (a STEP when there is one)
opens in the artifact pane; anything else is announced with an Open action so a
viewer the user is reviewing is never replaced mid-turn. Turns are recorded app-wide in
`cadTurnLedger`, not in the task view: a turn that ends while another project is on screen, or while a
pane change remounts the view, is revealed the next time its task is shown, scanning from the turn's real
start. Remote workspaces are
skipped because the viewer only serves local directories, and artifacts written
outside the workspace (a git worktree, a temp directory) stay invisible: the
viewer cannot serve them either.

## Acceptance gate

Before shipping a desktop build, verify the installed application rather than only a checkout:

1. Start Claude and Codex sessions and confirm the bundled skills are available automatically.
2. Open an existing STEP without regeneration and confirm its hash.
3. Generate a STEP from a plain `@step` recipe and open the accepted artifact.
4. Change a numeric dimension in the source editor, rebuild, validate, and reload it.
5. Produce an invalid edit and an interrupted run and confirm the last accepted artifact is restored.
6. Restart the app and confirm the same STEP hash and viewport artifact return without regeneration.
7. Run at least two CAD threads concurrently and confirm independent status, processes, and viewers.
8. Package the app and run the packaged CAD smoke (`scripts/release/verify-packaged-cad.ts`), which
   provisions the bundled runtime, builds two models in two roots, validates them, and serves each
   from its own viewer.
