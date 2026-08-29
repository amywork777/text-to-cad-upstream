# Backend

The CAD Viewer client never reads filesystem paths. It talks to HTTP routes under
`/__cad/*` and to catalog URLs, and a backend on the other side resolves those to
files. The viewer is a local-filesystem app, so there is exactly one backend.

That backend is **pure JS**: `viewer/server/`, dependency-free Node (>= 22). It owns
everything the viewer does — the catalog scan, path containment, asset serving, the
SPA, artifact status, the WASM STEP import, the native reveal dialog, the instance
registry. The viewer is a STATIC VISUALIZATION TOOL: it runs no Python, ever. It
renders artifacts that exist — render packages, sibling `.dxf` files — and the CAD
CLIs (`scripts/gen`, `scripts/export`) own generation and
export. The one build-shaped thing it does is Python-free by construction: importing
a raw foreign STEP through its bundled WASM kernel (below).

## Where it runs

Both modes run the same `createCadApp` handler, so a behaviour difference between
them is a bug:

- **Dev** (`npm run dev`) — Vite serves the client from source with HMR and mounts the
  handler as middleware in the same process. No child process, no proxy. Dev lives on
  Vite's canonical port (5173), is strict about it (taken port → pick another with
  `--port`), and never enters the instance registry: it is a hand-managed foreground
  process, so launch reuse must never hand it back, and restarting it to test server
  changes stays entirely in your hands.
- **Production** (`npm run build && npm run start`) — `node server/main.mjs` serves the
  built `dist/` and the API from one process. The cad-viewer skill ships the same files
  (built dist + this server) under its own `scripts/viewer/` and starts them the same
  way; cadgen ships no viewer at all.

## Launching (unconditional, Jupyter-style)

`main.mjs --root <dir>` always ends with the URL of a live, correct Viewer for that
directory. Order of operations:

1. **Reuse**: unless `--new` (or an explicit `--port`) is given, the launcher looks for
   a registry entry whose `realpath(root)` and viewer version match, identity-probed
   (`/__cad/server` must answer as the recorded pid). On a match it prints that URL
   with `action:"reused"` and exits 0. The key is never the port or the pid — keying
   reuse on the port was the old source-blind-reuse bug.
2. **Roll**: otherwise it binds the first free port from 3245 upward (binding IS the
   probe; a lost race just moves to the next candidate) and prints `action:"started"`.
3. **Strict `--port`**: an explicit port is a demand — taken means exit 1, naming the
   holder when the registry knows it. No reuse, no rolling.

The printed URL (and `--json`'s `{url,port,action}` line) is the whole contract; the
port is an output of launch. Iterating on server code from a checkout? `--new` is the
escape from reuse — a running instance keeps executing the code it started with.

Deliberately NOT adopted from the Jupyter model it parallels: **no auth token** (this
server executes nothing and serves read-only inside one root; the Host-header
rebinding guard and the preflight-forcing POST header cover the actual threat model),
and **no HTTP shutdown route** (`stop`'s identity-probed signal can never kill a
port-squatter, which is stronger than an authenticated endpoint).

## One root per instance

An instance serves ONE directory, given by `--root` at startup and defaulting to the
invoking directory. Requests never name a directory: there is no `?dir=` param, and
`?file=` is always resolved inside the served root. Anything resolving outside that
root is refused, unconditionally. Serving a second directory means launching again
with that root (reuse-or-start makes it idempotent); `node server/main.mjs list`
reports which root each running instance holds (and `stop --port <n>` ends one).

The root is resolved and checked once, in `LocalAssetBackend`'s constructor
(`server/backend.mjs`), so every later request is measured against a directory
already known to exist.

## Interface

`server/backend.mjs` holds `LocalAssetBackend` (root containment, catalog
absolutization, the guarded path resolvers); `server/scanner.mjs` holds the catalog
scan; `server/cadgenOps.mjs` holds the Python delegation:

```js
backend.resolveRoot()                     // the served root, resolved once
backend.readCatalog()                     // scan -> schema v4 entries
backend.assetPathForFileRef(fileRef)      // guarded path for bytes we will send
backend.containedPathForFileRef(fileRef)  // guarded path for bytes we will not
backend.catalogEntryForFileRef(catalog, fileRef)
ops.artifactStatus(fileRef)               // JS freshness verdict + advisory progress
ops.buildArtifact(fileRef, { force })     // WASM import of a raw STEP; else a CLI hint
```

`readCatalog()` scans the served root and returns schema v4 entries whose `file`
values are absolute paths plus `rootRelativeFile` values for URL navigation. Nothing
is written to `catalog.json` or any hidden catalog cache.

The two path resolvers differ by one question. `assetPathForFileRef` answers "may the
server send this file's contents", so it also applies the served-asset extension
filter, which excludes a `.step.py` generator. `containedPathForFileRef` applies the
root and hidden-path rules WITHOUT that filter, for callers that transfer no bytes —
`reveal` is the one that matters. Both throw on anything outside the root.

## Artifact status (JS-only), and where builds live

Artifact STATUS has exactly one authority: `server/artifactStatus.mjs`, pure file
reads in this process — package existence, schema version, payload files, the
no-bake gate, and the imported-file digest gate. Generated outputs are DETACHED
from their source code: the viewer never treats "the generator changed since this
artifact was built" as a reason to rebuild, and it does not rebuild generated
entries at all — a `.step.py` or `.dxf.py` with no artifact reports an error that
names the CLI (`python scripts/gen <source>`), not a build offer.

A CLI build in flight is shown ADVISORILY: the build's status record
(`.<name>.generation.progress.json`, written by cadgen's coordination layer) is
read for a `generating` badge with progress when it is fresh and non-terminal.
The viewer takes no action on that state — it never contends for the generation
lock — so the kernel-lock rules in `cadgen/coordination/lock.py` are not being
re-inferred here; a killed build's badge simply ages out within seconds.

Constants the JS authority mirrors from cadgen (the package schema version) are
pinned cross-language by `tests/python/global/test_render_contract_sync.py`.

`/__cad/server` reports `stepArtifactGenerationAvailable: false`, always: the
capability does not exist in the viewer by design.

## WASM STEP import (no Python)

A raw `.step`/`.stp` with no render package (or a stale one — the file changed after
import) is importable right here: `server/import/` holds a WASM OCCT pipeline
(opencascade.js — a viewer npm dependency in a checkout, and VENDORED into the
bundled cad-viewer skill runtime by `bundle-cad-viewer.sh`, so the import works
in every environment) that parses the STEP, walks its XCAF assembly, extracts
each component with the surf-extractor twin, and writes the SAME package format
cadgen writes. This is the viewer's ONLY build, and it is simply a capability
the viewer has: there is no configuration that disables it, and a missing
kernel is a broken install — the one failure path is a graceful error naming
the missing file (agents are routed to `cadgen import` as the alternative,
which is also the better importer where cadgen exists: native kernel, faster,
newer OCC, reads per-instance colors). It runs as a child process
(`import/importCli.mjs`) so a kernel abort can never take the server down.
Status for an importable STEP reports `needs-build` and the client's normal
build POST performs the import.

While an import runs, the child reports one `[import-progress] {json}` line per
phase on stderr; the server parses those into an in-memory record per in-flight
package dir and the status route serves it as the `generating` payload — the same
shape a CLI build's progress record takes, so the client's existing badge renders
it with no client changes. The `components` phase carries a real `done/total`
denominator (a bar); the other phases are honest indeterminate frames. The record
lives only as long as the child: no file is written, and a crashed import leaves
nothing to age out.

Both extractors and both package producers are deliberately duplicated code fenced by
tests: `tests/python/packages/cadgen/test_surf_extractor_conformance.py` (geometry,
per corpus blob), `test_wasm_import_parity.py` (descriptor + component parity against
a native import of the same file), and `tests/python/global/test_render_contract_sync.py`
(shared constants). Known limits: imports run at WASM speed (seconds for small files,
minutes for 100MB-class ones, once per file), and the kernel (OCCT ~7.6) trails OCP —
the BinTools blob format is pinned to V4 on both sides for that reason.

One workaround is measured rather than guessed at: label names ride a whole-document
XmlXCAF save into MEMFS (once per import, indexed and cached) because
`TDataStd_Name.Get` is unbound and every bound dump route needs the equally unbound
`std::ostream`. On 22–27 MB vendor STEPs the save costs 0.8–0.9 s against 20–30 s of
STEP parse+transfer — ~3–4% of the import, shrinking as files grow (the save scales
with the document, the parse with the file). Not worth optimizing short of the custom
kernel build below.

One limit is surfaced rather than silent: `GetInstanceColor` is unbound in this
opencascade.js build, so an instance whose color attachment only native OCCT's
instance resolution would find falls through to its prototype's color. The import
cannot know the missed color, but it CAN detect the risky shape of the problem —
some instances of a prototype resolved instance-level colors while siblings fell
through — and records a warning (`instanceColorWarnings` in `stepImport.mjs`) into
the descriptor's `importWarnings`, which the status route returns on every `ready`
answer and the build response echoes. Uniformly colored assemblies never warn. The
real fix is a custom opencascade.js build exposing the binding.

## Routes

- `GET /__cad/server`
- `GET /__cad/catalog`
- `GET /__cad/asset?file=...`
- `GET /__cad/download?file=...&asset=output|source`
- `GET /__cad/artifact?file=...` (status)
- `POST /__cad/artifact?file=...` (build; `&force=1` to rebuild)
- `POST /__cad/reveal?file=...&asset=output|source`
- `GET /__cad/<relative path>` — a sibling-of-Referer asset, resolved against the
  directory of the `file=` in the requesting page's Referer. This is how a URDF's
  mesh refs and a package's `../components/<hash>.surf` load, since those are written
  relative to the model rather than to the root. It is a second path surface and gets
  the same containment check as `/__cad/asset`.
- `GET /__tess_cache/<key>.tess`, `POST /__tess_cache/<key>.tess`,
  `POST /__tess_cache/batch` — the shared component-tessellation cache
  (`<cache root>/meshes`, the same store the export CLI and the snapshot host
  use; the entry codec, the key scheme — `<cid>-t<tessellator-version>-l<chord>-a<angle>` —
  and the TESB batch format live in cadjs `lib/surf/tessellationCache.js`). The client registers a provider at
  bootstrap, so component loads and viewport-LOD level re-tessellations are
  cache hits whenever ANY consumer — a snapshot, an export, a previous viewer
  session — tessellated the component before, and misses write back. Entries
  are opaque bytes living OUTSIDE every served root, so names are strictly
  validated (`server/tessCache.mjs`; its store I/O is an inline copy of cadjs's
  `tessellationCacheFs`, drift-fenced by test, because the bundled skill
  runtime ships no cadjs tree). `CADGEN_MESH_CACHE=0` disables both directions,
  and every cache failure degrades to plain in-page tessellation.

### Storage tiers, in one rule

`~/.cache/cadgen` (or `$CADGEN_STORE_DIR`, or the platform cache dir —
`$XDG_CACHE_HOME`/`%LOCALAPPDATA%`; one resolution rule in cadgen's
`_internal/cache_paths.py`, mirrored by `cadgenCacheRootDir` in the JS store
modules and sync-tested) holds everything CONTENT-ADDRESSED and DISPOSABLE:
the component store, the kernel-op memo, and this mesh cache. Deleting any of
it costs a rebuild, never correctness. The model's own folder holds everything
LOCATION-PAIRED and meaningful: the artifact and its `__cadgen__` package
(hardlinked into the store where possible, so the heavy bytes exist once).
Version bumps orphan whole cache generations by design; `cadgen cache info` /
`cadgen cache gc` are the only sweepers — nothing collects garbage
automatically.

`download` streams asset bytes. It serves OUTPUTS only — the artifacts the viewer may
have to regenerate — and never source code: a `.step.py` is not in the served-asset
extension set, so `asset=source` is not offered for download and the UI wires it only
to `reveal`.

`reveal` opens the asset in the platform file manager (`open -R` / `explorer /select,`
/ `xdg-open` on the containing folder) and answers 501 where no file manager is known
or when `VIEWER_DISABLE_NATIVE_REVEAL=1`. Because it transfers no bytes it resolves
through `containedPathForFileRef`, so a `.step.py` generator can be revealed even
though it is never streamed. `asset=output` resolves the catalog entry file itself;
`asset=source` resolves optional source code, such as a same-stem Python generator for
a Python-backed STEP file.

**Every POST must send `x-cadgen-viewer: 1`.** The value carries no meaning — a custom
header is what forces a browser to preflight a cross-origin request, and the backend
answers no CORS, so the preflight fails and a hostile page can never reach a route
that builds (and therefore executes a generator). A POST without it gets 403. GETs are
unaffected. A second gate refuses any Host header naming a non-local name
(DNS-rebinding defense). See the trust-model comment in `server/httpApp.mjs`.

**The viewer never touches the network.** Every byte it serves or reads is local.
When the bundled skill needed the WASM kernel, the alternative to vendoring it was
lazy fetch — download a pinned, hash-verified kernel on first import — and it was
consciously rejected: it would have added the viewer's first outbound request class
(plus fetch/integrity/untar machinery and an offline degradation path) purely to
save install bytes. Vendoring keeps the zero-network property absolute.
