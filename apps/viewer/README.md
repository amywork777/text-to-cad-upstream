# CAD Viewer

A local-filesystem CAD review app: a React client (`src/`) over a stdlib-only
Python backend (`server/`). One instance serves ONE directory,
fixed at start; the page is always the bare origin and `?file=` selects an
artifact inside that root. There is no hosted deployment — the `cad-viewer`
skill bundles the built client + server, and each release mirrors this app
into the standalone `earthtojake/cad-viewer` repo unchanged.

**PURPOSE** — the application: all UI, workflow, and session state for
reviewing CAD artifacts (catalog, tabs, selection, pose, animation,
measurements, themes).

**MAY DEPEND ON** — `cadgen-js` (the shared CAD render/runtime package,
vendored at `packages/cadgen-js` and imported via the `cadgen-js`
specifier) and its own npm dependencies, both of which are bundled into the
client AT BUILD TIME. The backend imports `cadgen` — an ordinary PyPI package —
to compile foreign STEP imports, and it is a SOFT dependency: nothing in
`server/` imports it at module scope, so absent cadgen viewing still works and
only imports answer with an install hint.

**DEPENDED ON BY** — nothing. No code imports from this app, by law.

## The laws that bind the app

- **Ships alone**: this app works in isolation — the built client, the
  stdlib-only Python server, and the vendored `packages/cadgen-js` are
  everything it needs; cadgen from PyPI is its only Python dependency, and
  a soft one. Nothing in the app — code or markdown — refers outside this
  directory: it ships unchanged, so an out-of-directory reference is
  broken the moment it leaves. `scripts/selfContained.test.mjs` and
  `tests_server/test_module_boundaries.py` are the fences.
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

Prod (the shipped bundle — build the client first, then run the server FROM
the directory to serve; there is no directory flag, the cwd IS the served
directory):

```bash
npm run build
cd <the directory to serve> && python <path to>/server/main.py --host 127.0.0.1 --json
```

`python` must be **3.11 or newer**: the server checks at startup and refuses
below that, naming the version it needs, rather than starting and then failing
on the first request. macOS still ships 3.9 as `python3`, so on a Mac
`VIEWER_PYTHON` usually has to name a newer one.

Viewing needs nothing but the standard library. STEP **import** needs cadgen,
which `requirements.txt` declares:

```bash
python -m pip install -r requirements.txt
```

That is a floor (`cadgen>=…`) rather than a pin, and it is real: the import path
calls cadgen's build entry point with a progress sink that older releases do not
accept. What the running server checks is the installed **signature**, not the
version — an editable checkout reports the last release's number whatever its
source contains — so a cadgen that is absent OR too old degrades identically:
`stepImportAvailable` is false, viewing is untouched, and the import is refused
with the command that fixes it. See `MINIMUM_CADGEN_VERSION` and
`cadgen_supports_progress_sink` in `server/compile_worker.py`.

Dev needs no build first — it spawns that same `server/main.py` on an ephemeral
port with `--api-only` and proxies `/__cad` and `/__tess_cache` to it, so there
is one implementation, not two, and Vite owns the client. Set `VIEWER_PYTHON`
to choose the interpreter, or `VIEWER_BACKEND_URL` to attach to one you started
yourself. Production does need the build, and refuses to start without it.

The launcher is unconditional and prints the URL it serves: a live instance
already serving that realpath with the same code on disk is REUSED
(`action:"reused"`); otherwise it binds the first free port from 3245 upward.
`--new` forces a fresh instance of the same code; an explicit `--port` is
strict. `main.py list` shows every running instance; `main.py stop --port <n>`
ends one. Do not stop instances you did not start. Dev lives on Vite's
port (5173, strict) and never enters the instance registry.

Reuse keys on realpath(served directory) × an identity token — the viewer
version salted with the newest mtime across `server/`'s `.py` files and the
built `dist/` (`identity_token` in `server/http_app.py`) — so an instance
serving a different directory, the same directory from another copy of the
app, or code that has since been edited, pulled, or rebuilt is never handed
back by mistake. In a published bundle the files never change after install,
so the token reduces to version-keyed reuse there. In a checkout, a server
that finds client sources (`src/`) beside the `dist/` it serves also warns
once on stderr when any source is newer than the build — detection only; it
keeps serving.

## Behaviours worth knowing before concluding something is broken

- **The catalog scan skips dot-directories.** A buildable entry under
  `.review/` (or any dotted path) never appears, even when the server is
  launched from inside it.
- **Verify a link by loading the page**, never by curling `/__cad/asset` —
  that route serves raw files; generated entries render through a
  different route, so probing it 404s whether or not anything is wrong.
- **Vite's transform cache can outlive HMR and hard reloads.** If a source
  edit does not show up, restart the dev server and delete
  `node_modules/.vite`.
- Never invoke the export routes from automation — they open native save-as
  dialogs.

## The shape of the app

```
server/     # stdlib-only Python backend: scanner.py (catalog),
            #   backend.py/http_app.py (routes), handler.py (sockets),
            #   artifact_status.py (freshness authority), store_paths.py
            #   (store layout, mirroring cadgen — equality-tested),
            #   compile_client/compile_worker.py (the cadgen import path),
            #   tess_cache.py, registry.py + main.py (the launcher)
tests_server/ # the backend's suite — unittest, NOT collected by `npm run test`
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

Two suites, one per language, both run from this directory:

```bash
npm run test                                   # client + app tooling (node:test, beside the code)
python -m unittest discover -s tests_server -t .   # the backend (stdlib unittest)
```

Neither covers the other, so running only one leaves half the app unchecked.
The backend suite's cadgen equality guard skips where cadgen is absent;
`VIEWER_REQUIRE_CADGEN_PARITY=1` turns that skip into a failure, for anywhere
cadgen is expected to be present.

Headless UI verification uses Playwright with `--use-angle=metal` —
the default software WebGL renderer is not what users see.
