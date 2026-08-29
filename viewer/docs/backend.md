# Backend

The CAD Viewer client never reads filesystem paths. It talks to HTTP routes under
`/__cad/*` and to catalog URLs, and a backend on the other side resolves those to
files. The viewer is a local-filesystem app, so there is exactly one backend.

That backend is **pure JS**: `viewer/server/`, dependency-free Node (>= 22). It owns
everything the viewer does — the catalog scan, path containment, asset serving, the
SPA, artifact status, the STEP import bridge, the native reveal dialog, the instance
registry. The viewer is a STATIC VISUALIZATION TOOL: its render path runs no Python.
It renders artifacts that exist — render packages, sibling `.dxf` files — and the
CLIs own generation and export. The one build-shaped thing it does is importing a
raw foreign STEP, which spawns `cadgen import` as a child process (below); cadgen
is a soft dependency, needed only for that.

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
ops.buildArtifact(fileRef, { force })     // spawns `cadgen import` for a raw STEP; else a CLI hint
```

`readCatalog()` scans the served root and returns schema v4 entries whose `file`
values are absolute paths plus `rootRelativeFile` values for URL navigation. Nothing
is written to `catalog.json` or any hidden catalog cache.

The two path resolvers differ by one question. `assetPathForFileRef` answers "may the
server send this file's contents", so it also applies the served-asset extension
filter, which excludes a model script. `containedPathForFileRef` applies the
root and hidden-path rules WITHOUT that filter, for callers that transfer no bytes —
`reveal` is the one that matters. Both throw on anything outside the root.

## Artifact status (JS-only), and where builds live

Artifact STATUS has exactly one authority: `server/artifactStatus.mjs`, pure file
reads in this process — package existence, schema version, payload files, the
no-bake gate, and the imported-file digest gate. Generated-vs-imported is decided
by the source sidecar's EXISTENCE (`<package>/source.json`, written only by
generation): the descriptor (`assembly.json`) is a pure function of the STEP
bytes and carries no provenance; everything source-derived — source path/hashes,
the pose block, assembly mates — rides the sidecar. Generated outputs are
DETACHED from their source code: the viewer never treats "the generator changed
since this artifact was built" as a reason to rebuild, and it does not rebuild
generated entries at all — a generated model with no artifact reports an error
that names the build (`python <model>.py`), not a build offer.

A CLI build in flight is shown ADVISORILY: the build's status record
(`.<name>.generation.progress.json`, written by cadgen's coordination layer) is
read for a `generating` badge with progress when it is fresh and non-terminal.
The viewer takes no action on that state — it never contends for the generation
lock — so the kernel-lock rules in `cadgen/coordination/lock.py` are not being
re-inferred here; a killed build's badge simply ages out within seconds.

Constants the JS authority mirrors from cadgen (the package schema version) are
pinned cross-language by `tests/python/global/test_render_contract_sync.py`.

`/__cad/server` reports `stepArtifactGenerationAvailable: false`, always: the
capability does not exist in the viewer by design. `stepImportAvailable` reports
whether a runnable cadgen was found (see the import section below); viewing is
unaffected either way.

## STEP import (via cadgen)

A raw `.step`/`.stp` with no render package (or a stale one — the file changed after
import) is importable right here: the server spawns `cadgen import <file>` — the
single import producer — as a child process, which parses the STEP natively and
writes the standard package. cadgen is a SOFT dependency, resolved at request time
by `server/cadgenResolve.mjs`: `$CADGEN_PYTHON` (spawned as
`<python> -m cadgen.cli import ...`), then a `cadgen` console script on PATH, then
`<served-root>/.venv` — deliberately no find-up discovery (it bound worktrees to
the wrong checkout's cadgen once before). The child inherits the server's
environment verbatim, so standard Python knobs (`PYTHONPATH` for a worktree's
cadgen sources, an activated venv) flow through unchanged. Without a resolvable
cadgen, status and build answer with one actionable message and viewing is
untouched; `/__cad/server` reports the probe as `stepImportAvailable`.

The child is spawned with `--lock-timeout 5` and cwd set to the STEP's own
directory. A `contended` answer (a peer process holds the package lock) maps to
`generating`, which the client already treats as "attach to the running build".
A bare `.step` with no package is simply importable, whatever produced it —
STEP files carry no cadgen metadata of any kind, so there is nothing to read
from the file beyond its geometry.

Progress needs no protocol of its own: `cadgen import` writes the standard build
progress record beside the package (phase fields flattened, the exact shape the
client badge renders), and the status route serves it through the same reader
used for CLI builds (`buildProgressSnapshot` in `cadgenOps.mjs`). One reader,
every producer.

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
meaningful: the artifact and its store package
(hardlinked into the store where possible, so the heavy bytes exist once).
Version bumps orphan whole cache generations by design; `cadgen cache info` /
`cadgen cache gc` are the only sweepers — nothing collects garbage
automatically.

`download` streams asset bytes. It serves OUTPUTS only — the artifacts the viewer may
have to regenerate — and never source code: a model script (`.py`) is not in the served-asset
extension set, so `asset=source` is not offered for download and the UI wires it only
to `reveal`.

`reveal` opens the asset in the platform file manager (`open -R` / `explorer /select,`
/ `xdg-open` on the containing folder) and answers 501 where no file manager is known
or when `VIEWER_DISABLE_NATIVE_REVEAL=1`. Because it transfers no bytes it resolves
through `containedPathForFileRef`, so a model script can be revealed even
though it is never streamed. `asset=output` resolves the catalog entry file itself;
`asset=source` resolves optional source code — the model script the source sidecar
names for a generated STEP file.

**Every POST must send `x-cadgen-viewer: 1`.** The value carries no meaning — a custom
header is what forces a browser to preflight a cross-origin request, and the backend
answers no CORS, so the preflight fails and a hostile page can never reach a route
that builds (and therefore executes a generator). A POST without it gets 403. GETs are
unaffected. A second gate refuses any Host header naming a non-local name
(DNS-rebinding defense). See the trust-model comment in `server/httpApp.mjs`.

**The viewer never touches the network.** Every byte it serves or reads is local;
the import spawns a local process, never a fetch.
