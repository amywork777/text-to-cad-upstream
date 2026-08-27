# Backend

The CAD Viewer client never reads filesystem paths. It talks to HTTP routes under
`/__cad/*` and to catalog URLs, and a backend on the other side resolves those to
files. The viewer is a local-filesystem app, so there is exactly one backend.

That backend is **pure JS**: `viewer/server/`, dependency-free Node (>= 22). It owns
everything filesystem- and HTTP-shaped — the catalog scan, path containment, asset
serving, the SPA, the native save/reveal dialogs, the instance registry. The one thing
it does not host is the CAD runtime: anything that needs cadgen (artifact freshness of
owned entries, builds, exports) is delegated to a stdlib-only Python one-shot,
`python -m cadgen.render_ops`, spawned per request. OCP never loads into the server
process, and Python is not required to START the viewer at all — without cadgen the
viewer serves packaged models read-only and builds answer with an install hint.

## Where it runs

Both modes run the same `createCadApp` handler, so a behaviour difference between
them is a bug:

- **Dev** (`npm run dev`) — Vite serves the client from source with HMR and mounts the
  handler as middleware in the same process. No child process, no proxy.
- **Production** (`npm run build && npm run start`) — `node server/main.mjs` serves the
  built `dist/` and the API from one process. An installed cadgen ships the same files
  at `cadgen/_runtime/viewer_server` and starts them via `cadgen viewer`.

## One root per instance

An instance serves ONE directory, given by `--root` at startup and defaulting to the
invoking directory. Requests never name a directory: there is no `?dir=` param, and
`?file=` is always resolved inside the served root. Anything resolving outside that
root is refused, unconditionally. Serving a second directory means starting a second
Viewer on another port; `cadgen viewer list` reports which root each running instance
holds.

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
ops.artifactStatus(fileRef)               // python render_ops status (or degraded)
ops.buildArtifact(fileRef, { force })     // python render_ops build
ops.generateExport(fileRef, format, out)  // python render_ops export
```

`readCatalog()` scans the served root and returns schema v4 entries whose `file`
values are absolute paths plus `rootRelativeFile` values for URL navigation. Nothing
is written to `catalog.json` or any hidden catalog cache.

The two path resolvers differ by one question. `assetPathForFileRef` answers "may the
server send this file's contents", so it also applies the served-asset extension
filter, which excludes a `.step.py` generator. `containedPathForFileRef` applies the
root and hidden-path rules WITHOUT that filter, for callers that transfer no bytes —
`reveal` is the one that matters. Both throw on anything outside the root.

## The CAD runtime

STEP/DXF/implicit freshness, builds, and exports go through
`python -m cadgen.render_ops <status|build|export>` — one JSON line per call, ~60 ms.
The op itself dispatches heavy work to cadgen's shared warm daemon pool, so a viewer
build and a terminal build reuse the same warm processes. The interpreter is
`VIEWER_CAD_PYTHON` when set (`cadgen viewer` sets it to the interpreter that launched
it), else the nearest `.venv/bin/python`, else `python3`. Freshness validators live in
cadgen (`cadgen/render_ops.py`) beside the producer's own gates, so the two
authorities cannot drift.

Startup never blocks on Python: availability is probed lazily and reported through
`stepArtifactGenerationAvailable` in `/__cad/server`.

## Routes

- `GET /__cad/server`
- `GET /__cad/catalog`
- `GET /__cad/asset?file=...`
- `GET /__cad/download?file=...&asset=output|source`
- `GET /__cad/artifact?file=...` (status)
- `POST /__cad/artifact?file=...` (build; `&force=1` to rebuild)
- `POST /__cad/export?file=...&format=...`
- `POST /__cad/reveal?file=...&asset=output|source`
- `GET /__cad/<relative path>` — a sibling-of-Referer asset, resolved against the
  directory of the `file=` in the requesting page's Referer. This is how a URDF's
  mesh refs and a package's `../components/<hash>.surf` load, since those are written
  relative to the model rather than to the root. It is a second path surface and gets
  the same containment check as `/__cad/asset`.

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
