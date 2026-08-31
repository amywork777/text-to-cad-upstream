# CAD Viewer

A local-filesystem CAD review app: a React client (`src/`) over a
dependency-free Node backend (`server/`). One instance serves ONE directory,
fixed at start; the page is always the bare origin and `?file=` selects an
artifact inside that root. There is no hosted deployment — the `cad-viewer`
skill bundles the built client + server, and each release mirrors this app
into the standalone `earthtojake/cad-viewer` repo unchanged.

**PURPOSE** — the application: all UI, workflow, and session state for
reviewing CAD artifacts (catalog, tabs, selection, pose, animation,
measurements, themes).

**MAY DEPEND ON** — `cadgen-js` (source, via the `cadgen-js` specifier;
in the dev layout `packages/cadgen-js` here is a symlink to the canonical
package, dereferenced into a vendored copy when mirrored) and its own npm
dependencies. The backend spawns `cadgen step build` for foreign STEP
imports as a SOFT dependency: absent cadgen, viewing still works.

**DEPENDED ON BY** — nothing. No code imports from this app, by law.

## The laws that bind the app

- **Three-input law**: everything renders from the artifact file, its
  sidecar (`<name>.step.json`), and the cache. The viewer never reads
  source code and never rebuilds on source changes — generated outputs are
  detached, and a stale artifact stays stale until someone runs its script.
- **Kinematics/animation independence**: the Pose tab drives the sidecar's
  mate data through the shared FK runtime; the Animation tab evaluates the
  sidecar's copied `.anim.js` clips. They compose in the effect records and
  nowhere else.
- **Loud failure**: a missing entry, an unresolvable ref, or a failed
  compile surfaces as an alert — never a silently wrong scene.

## Launching

Dev (Vite serves the client from source with HMR; edits to `src/` and
`packages/cadgen-js` show live):

```bash
npm --prefix apps/viewer run dev -- --host 127.0.0.1
# open http://127.0.0.1:5173/?file=<path relative to the served root>
```

Prod (the shipped bundle — build first, then the JS server):

```bash
npm --prefix apps/viewer run build
node apps/viewer/server/main.mjs --root <absolute dir> --host 127.0.0.1 --json
```

The launcher is unconditional and prints the URL it serves: a live instance
already serving that realpath at this version is REUSED (`action:"reused"`);
otherwise it binds the first free port from 3245 upward. `--new` forces a
fresh instance (needed when testing server-code changes — a reused instance
runs the code it started with); an explicit `--port` is strict.
`main.mjs list` shows every running instance; `main.mjs stop --port <n>`
ends one. Do not stop instances you did not start. Dev lives on Vite's
port (5173, strict) and never enters the instance registry.

From a lightweight worktree (backend is pure JS; builds need a
cadgen-importable interpreter handed down):

```bash
CADGEN_PYTHON=<main>/.venv/bin/python \
PYTHONPATH=<worktree>/packages/cadgen/src \
node <worktree>/apps/viewer/server/main.mjs \
  --root <worktree>/models --dist <worktree>/apps/viewer/dist \
  --host 127.0.0.1 --json
```

Worktrees deliberately carry no `node_modules`; link them from the primary
checkout before building:

```bash
ln -s <main>/apps/viewer/node_modules apps/viewer/node_modules
mkdir -p packages/cadgen-js/node_modules
ln -s <main>/packages/cadgen-js/node_modules/three packages/cadgen-js/node_modules/three
ln -s <main>/apps/docs/node_modules/meshoptimizer  packages/cadgen-js/node_modules/meshoptimizer
npm --prefix apps/viewer run build
```

Reuse keys on realpath(root) × version, so another checkout's instance can
never be handed back for this worktree.

## Behaviours worth knowing before concluding something is broken

- **The catalog scan skips dot-directories.** A buildable entry under
  `.review/` (or any dotted path) never appears, even with `--root`
  pointed straight at it.
- **Verify a link by loading the page**, never by curling `/__cad/asset` —
  that route serves raw files; generated entries render through a
  different route, so probing it 404s whether or not anything is wrong.
- **Vite's transform cache can outlive HMR and hard reloads.** If a source
  edit does not show up, restart the dev server and delete
  `apps/viewer/node_modules/.vite`.
- Never invoke the export/reveal routes from automation — they open native
  save-as dialogs and Finder windows.

## The shape of the app

```
server/     # pure-Node backend: scanner (catalog), backend/httpApp
            #   (routes), artifactStatus (generated-vs-imported authority),
            #   packageContract.mjs (schema constants mirroring cadgen —
            #   sync-tested), tessCache, launcher (main.mjs)
src/client/ # React app: CadWorkspace (state root), CadViewer (scene +
            #   effects application), workbench/ (tabs, sections, session
            #   state, playback), render/ (viewport)
scripts/    # app tooling incl. e2e helpers and selfContained.test.mjs
            #   (the mirror's no-external-paths gate)
docs/       # subsystem docs; settings-ui.md is the CURATED design-system
            #   reference for all settings UI work — binding, read it
            #   before touching controls
dist/       # built client (gitignored)
```

## Testing

`npm --prefix apps/viewer run test` (node:test suites beside the code).
Headless UI verification uses Playwright with `--use-angle=metal` —
the default software WebGL renderer is not what users see.
