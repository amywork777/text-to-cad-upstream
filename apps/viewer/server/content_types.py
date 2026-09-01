"""The two hand-written content-type maps.

Do NOT replace these with ``mimetypes``: the three.js GLB/WASM loaders and the
browser's ES-module loader are strict, so the bytes must match what the client
has always been served. ``mimetypes`` is also platform-dependent — it reads the
system's mime.types — which would make the wire format vary by machine.
"""

from __future__ import annotations

import posixpath

__all__ = ["content_type_for_static_asset", "content_type_for_path", "extension_of"]

# Static dist/SPA assets. Unknown extension -> "" and the caller sets NO
# content-type header at all (not octet-stream).
_STATIC_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}

# CAD assets (/__cad/asset, /__cad/store). Unknown -> octet-stream.
_ASSET_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".wasm": "application/wasm",
    ".glb": "model/gltf-binary",
    ".stl": "model/stl",
    ".3mf": "model/3mf",
    ".step": "application/step",
    ".stp": "application/step",
    ".dxf": "application/dxf",
    ".py": "text/plain; charset=utf-8",
    ".urdf": "application/xml; charset=utf-8",
    ".srdf": "application/xml; charset=utf-8",
    ".sdf": "application/xml; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def extension_of(file_path) -> str:
    """``path.extname(...).toLowerCase()``.

    Node's semantics, which ``os.path.splitext`` does not share for leading-dot
    names: ``extname(".step")`` is ``""`` while ``splitext`` answers ``".step"``.
    """
    name = posixpath.basename(str(file_path or "").replace("\\", "/"))
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    return name[dot:].lower()


def content_type_for_static_asset(file_path) -> str:
    return _STATIC_CONTENT_TYPES.get(extension_of(file_path), "")


def content_type_for_path(file_path) -> str:
    return _ASSET_CONTENT_TYPES.get(extension_of(file_path), "application/octet-stream")
