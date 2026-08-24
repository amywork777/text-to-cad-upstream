# Backend Storage

The CAD Viewer client never reads filesystem paths. It talks to HTTP routes under
`/__cad/*` and to catalog URLs, and a backend on the other side resolves those to
files. The viewer is a local-filesystem app, so there is exactly one backend.

That backend is **Python**: `cadgen.viewer`, shipped inside the `cadgen`
distribution. It used to be a JavaScript module under `viewer/src/server/`, which is
why this file once described a JS object shape; that module is gone, and so is the
second implementation it implied.

## Where it runs

Both modes serve the same backend, so a behaviour difference between them is a bug:

- **Dev** (`npm run dev`) — Vite serves the client from source with HMR and **spawns a
  Python child** (`python -m cadgen.viewer.server`), forwarding every `/__cad/*`
  request to it: method, headers, body, and streamed response. Vite does not
  implement any route itself.
- **Production** (`npm run build && npm run serve`) — the same Python module serves
  the built `dist/` and the API from one process. `npm run serve` is literally
  `python3 -m cadgen.viewer.server`.

## One root per instance

An instance serves ONE directory, given by `--root` at startup and defaulting to the
process cwd. Requests never name a directory: there is no `?dir=` param, and `?file=`
is always relative to the served root. Anything resolving outside that root is
refused, unconditionally. Serving a second directory means starting a second Viewer
on another port; `cadgen viewer list` reports which root each running instance holds.

The root is resolved and checked once, in `LocalAssetBackend.__init__`, so every
later request is measured against a directory already known to exist.

## Interface

`cadgen/viewer/backend.py` holds `LocalAssetBackend`. The shape the server uses:

```python
resolve_root()                                  # the served root, resolved once
read_catalog(file_ref="")                       # scan -> schema v4 entries
asset_path_for_file_ref(file_ref)               # guarded path for bytes we will send
contained_path_for_file_ref(file_ref)           # guarded path for bytes we will not
content_type_for_path(file_path)
catalog_entry_for_file_ref(catalog, file_ref)
artifact_status(file_ref, resolved_root, catalog)
resolve_artifact(file_ref, force, resolved_root, catalog)
generate_export(file_ref, fmt, resolved_root, catalog)
```

`read_catalog()` scans the served root, keeps the catalog as an in-memory object, and
returns schema v4 entries whose `file` values are absolute paths plus
`rootRelativeFile` values for URL navigation. Nothing is written to `catalog.json` or
any hidden catalog cache.

The two path resolvers differ by one question. `asset_path_for_file_ref` answers "may
the server send this file's contents", so it also applies the served-asset extension
filter, which excludes a `.step.py` generator. `contained_path_for_file_ref` applies
the root and hidden-path rules WITHOUT that filter, for callers that transfer no
bytes — `reveal` is the one that matters. Both raise on anything outside the root.

The `resolve_*` and `generate_*` methods take `resolved_root` because the server hands
them the value it already resolved, not because a request may choose one.

## The CAD runtime

STEP/DXF/implicit regeneration shells out to `cadgen`. OCP is deliberately kept OUT
of the long-lived server process, so a crash or a leak in a build cannot take the
viewer with it. Install cadgen into the Python the viewer uses:

```bash
pip install cadgen          # or, in this repo, the editable install from requirements-dev.txt
```

Before binding its port, the Viewer validates that its selected Python can import
`OCP`, `build123d`, and `cadgen.step_artifact_cli`. Startup fails rather than serving
a Viewer that cannot build a missing artifact. Set
`VIEWER_CAD_PYTHON=/absolute/path/to/python` when the CAD environment is not the
checkout's `.venv`.

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
  mesh refs and a package's `../components/<hash>.glb` load, since those are written
  relative to the model rather than to the root. It is a second path surface and gets
  the same containment check as `/__cad/asset`.

`download` streams asset bytes. It serves OUTPUTS only — the artifacts the viewer may
have to regenerate — and never source code: a `.step.py` is not in the served-asset
extension set, so `asset=source` is not offered for download and the UI wires it only
to `reveal`.

`reveal` opens the asset in the platform file manager (`open -R` / `explorer /select,`
/ `xdg-open` on the containing folder) and answers 501 where no file manager is known
or when `VIEWER_DISABLE_NATIVE_REVEAL=1`. Because it transfers no bytes it resolves
through `contained_path_for_file_ref`, so a `.step.py` generator can be revealed even
though it is never streamed. `asset=output` resolves the catalog entry file itself;
`asset=source` resolves optional source code, such as a same-stem Python generator for
a Python-backed STEP file.

**Every POST must send `x-cadgen-viewer: 1`.** The value carries no meaning — a custom
header is what forces a browser to preflight a cross-origin request, and the backend
answers no CORS, so the preflight fails and a hostile page can never reach a route
that builds (and therefore executes a generator). A POST without it gets 403. GETs are
unaffected. See the trust-model docstring in `cadgen/viewer/server.py`.
