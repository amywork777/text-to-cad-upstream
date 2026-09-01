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

**MAY DEPEND ON** — `cadgen-js` (the shared CAD render/runtime package,
vendored at `packages/cadgen-js` and imported via the `cadgen-js`
specifier) and its own npm dependencies. The backend spawns `cadgen step
build` for foreign STEP imports as a SOFT dependency: absent cadgen
(installable from PyPI), viewing still works.

**DEPENDED ON BY** — nothing. No code imports from this app, by law.

## The laws that bind the app

- **Ships alone**: this app works in isolation — the built client, the
  dependency-free Node server, and the vendored `packages/cadgen-js` are
  everything it needs; cadgen from PyPI is its only Python dependency, and
  a soft one. Nothing in the app — code or markdown — refers outside this
  directory: it ships unchanged, so an out-of-directory reference is
  broken the moment it leaves. `scripts/selfContained.test.mjs` is the
  fence.
- **Three-input law**: everything renders from the artifact file, its
  sidecar (`<name>.step.json`), and the cache. The viewer never reads
  source code and never rebuilds on source changes — generated outputs are
  detached, and a stale artifact stays stale until someone runs its script.
- **Kinematics/animation independence**: the Kinematics tab drives the sidecar's
  mate data through the shared FK runtime; the Animation tab evaluates the
  sidecar's copied `.anim.js` clips. They compose in the effect records and
  nowhere else.
- **Loud failure**: a missing entry, an unresolvable ref, or a failed
  compile surfaces as an alert — never a silently wrong scene.

## Launching

All commands run from this app's directory. Dev (Vite serves the client
from source with HMR; edits to `src/` and `packages/cadgen-js` show live):

```bash
npm run dev -- --host 127.0.0.1
# open http://127.0.0.1:5173/?file=<path relative to the served root>
```

Prod (the shipped bundle — build first, then the JS server):

```bash
npm run build
node server/main.mjs --root <absolute dir> --host 127.0.0.1 --json
```

The launcher is unconditional and prints the URL it serves: a live instance
already serving that realpath at this version is REUSED (`action:"reused"`);
otherwise it binds the first free port from 3245 upward. `--new` forces a
fresh instance (needed when testing server-code changes — a reused instance
runs the code it started with); an explicit `--port` is strict.
`main.mjs list` shows every running instance; `main.mjs stop --port <n>`
ends one. Do not stop instances you did not start. Dev lives on Vite's
port (5173, strict) and never enters the instance registry.

Reuse keys on realpath(root) × version, so an instance serving a
different directory — or the same directory from another copy of the app —
is never handed back by mistake.

## Behaviours worth knowing before concluding something is broken

- **The catalog scan skips dot-directories.** A buildable entry under
  `.review/` (or any dotted path) never appears, even with `--root`
  pointed straight at it.
- **Verify a link by loading the page**, never by curling `/__cad/asset` —
  that route serves raw files; generated entries render through a
  different route, so probing it 404s whether or not anything is wrong.
- **Vite's transform cache can outlive HMR and hard reloads.** If a source
  edit does not show up, restart the dev server and delete
  `node_modules/.vite`.
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

`npm run test` from this directory (node:test suites beside the code).
Headless UI verification uses Playwright with `--use-angle=metal` —
the default software WebGL renderer is not what users see.
