"""Where cadgen's non-Python runtime assets live.

cadgen executes two kinds of thing it does not write in Python: Node builders (the DXF
and implicit render packages are baked by a JS child) and a headless browser bundle (the
snapshot CLI drives it in a page). Both ship inside the distribution under
``cadgen/_runtime``; both can be pointed elsewhere for development. The CAD Viewer is NOT
one of them: it is a standalone app, distributed by the ``cad-viewer`` skill.

**Every resolver here is CALL-TIME.** Nothing at import time touches the filesystem or
looks for ``node``: ``pip install cadgen`` must succeed on a machine with no Node and no
browser, and the CAD Viewer's long-lived server must import light. A format that needs an
asset asks for it at the moment it needs it, and gets an actionable error if it is absent.

**Development beats the package, on purpose.** In this repo the builders resolve to the
live ``packages/cadjs/bin`` sources rather than the committed bundles, so editing builder
JS takes effect without a rebundle. An installed wheel has no such sources and falls
through to ``_runtime``.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "AssetMissing",
    "browser_runtime_dir",
    "node_builders_dir",
    "runtime_root",
]

# Data-only; deliberately no __init__.py, so this is a path lookup rather than an import.
_RUNTIME = Path(__file__).resolve().parent / "_runtime"


class AssetMissing(RuntimeError):
    """A runtime asset cadgen needs is not present in this installation."""


def runtime_root() -> Path:
    """The packaged ``_runtime`` directory. May not exist in a source checkout."""
    return _RUNTIME


def _env_dir(name: str) -> Path | None:
    value = str(os.environ.get(name) or "").strip()
    return Path(value).expanduser().resolve() if value else None


def _dev_builders_dir() -> Path | None:
    """``packages/cadjs/bin`` when cadgen is imported from a source checkout.

    Walks up from this module looking for a sibling ``cadjs/bin`` under a ``packages``
    directory -- true for ``packages/cadgen/src/cadgen/assets.py`` in this repo, and for a
    skill runtime that still vendors ``packages/cadgen`` beside ``packages/cadjs``. An
    installed wheel matches nothing here and falls through to the packaged copy.
    """
    for parent in Path(__file__).resolve().parents:
        if parent.name != "packages":
            continue
        candidate = parent / "cadjs" / "bin"
        if candidate.is_dir():
            return candidate
    return None


def node_builders_dir() -> Path:
    """Directory holding the esbuilt Node builders (``dxf-artifact.mjs`` and friends).

    ``CADGEN_NODE_BUILDERS_DIR`` names it directly. Otherwise a checkout's live
    ``packages/cadjs/bin`` wins over the packaged copy, so builder JS stays editable.
    """
    override = _env_dir("CADGEN_NODE_BUILDERS_DIR")
    if override:
        return override
    dev = _dev_builders_dir()
    if dev:
        return dev
    return _RUNTIME / "node"


def browser_runtime_dir(explicit: Path | str | None = None) -> Path:
    """Directory holding ``snapshot-render.js`` + ``render.html``.

    ``explicit`` is a caller-supplied directory (``run_snapshot_cli(runtime_dir=...)``),
    which a skill used to have to pass because the runtime was vendored beside it. It
    still wins when given; otherwise the packaged copy is used.
    """
    override = _env_dir("CADGEN_BROWSER_RUNTIME_DIR")
    if override:
        return override
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _RUNTIME / "browser"


