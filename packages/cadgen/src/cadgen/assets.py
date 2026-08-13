"""Where cadgen's non-Python runtime assets live.

cadgen executes three kinds of thing it does not write in Python: Node builders (the DXF
and implicit render packages are baked by a JS child), a headless browser bundle (the
snapshot CLI drives it in a page), and the CAD Viewer's built SPA. All three ship inside
the distribution under ``cadgen/_runtime``; all three can be pointed elsewhere for
development.

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
    "viewer_dist_dir",
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

    ``CADGEN_NODE_BUILDERS_DIR`` names it directly. ``CADGEN_NODE_PACKAGES`` is the older
    knob and names a ``packages`` directory, so ``cadjs/bin`` is appended -- kept because
    it is documented and because vendored skill runtimes set it.
    """
    override = _env_dir("CADGEN_NODE_BUILDERS_DIR")
    if override:
        return override
    legacy = _env_dir("CADGEN_NODE_PACKAGES")
    if legacy:
        return legacy / "cadjs" / "bin"
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


def viewer_dist_dir(explicit: Path | str | None = None) -> Path:
    """Directory holding the built CAD Viewer SPA (``index.html`` + ``assets/``).

    Unlike the other two this is NOT committed to the repo -- it is a vite build output,
    produced into ``_runtime/viewer`` by the bundle step and shipped in the wheel. A
    source checkout that has never bundled has none, which is why the error names the two
    ways forward rather than just reporting a missing path.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    override = _env_dir("CADGEN_VIEWER_DIST")
    if override:
        return override
    packaged = _RUNTIME / "viewer"
    if (packaged / "index.html").is_file():
        return packaged
    raise AssetMissing(
        f"The CAD Viewer's built client is not present at {packaged}.\n"
        "In an installed cadgen this means a broken distribution. In a source checkout it\n"
        "has simply not been built yet -- either run the dev server:\n"
        "  npm --prefix viewer run dev -- --host 127.0.0.1\n"
        "or build the packaged client:\n"
        "  scripts/bundle/bundle.sh\n"
        "or point CADGEN_VIEWER_DIST / --dist at an existing viewer/dist."
    )
