"""Shared cross-package component store.

Packages stay fully self-contained: every package's ``components/<cid>.surf``
is a real file (hardlinked from the store where possible). The store is a
best-effort cache — losing it costs a re-extraction, never correctness.

Layout: ``$CADGEN_STORE_DIR (default ~/.cache/cadgen)/components/<cid>.surf``.
The key is the BARE cid: a ``.surf`` is exact geometry with no mesh
tolerances (design/surface-rendering.md), and the cid is already salted by
``STEP_PACKAGE_VERSION`` so extractor changes re-key the store wholesale.

``CADGEN_COMPONENT_STORE=0`` disables both directions.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cadgen._internal.atomic_replace import replace_atomic


def _enabled() -> bool:
    return os.environ.get("CADGEN_COMPONENT_STORE", "").strip() != "0"


def _store_dir() -> Path:
    root = os.environ.get("CADGEN_STORE_DIR", "").strip()
    base = Path(root) if root else Path.home() / ".cache" / "cadgen"
    path = base / "components"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_path(cid: str) -> Path:
    return _store_dir() / f"{cid}.surf"


def _link_or_copy(source: Path, dest: Path) -> None:
    dest.unlink(missing_ok=True)
    try:
        os.link(source, dest)
    except OSError:
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copyfile(source, tmp)
        replace_atomic(tmp, dest)


def fetch(cid: str, dest: Path) -> bool:
    """Materialize a stored component ``.surf`` at ``dest``. True on success."""
    if not _enabled():
        return False
    try:
        source = _store_path(cid)
        if not source.exists():
            return False
        _link_or_copy(source, dest)
        return True
    except Exception:
        return False


def publish(src: Path, cid: str, *, overwrite: bool = False) -> None:
    """Record a locally extracted component in the store. Best-effort."""
    if not _enabled():
        return
    try:
        target = _store_path(cid)
        if target.exists():
            if not overwrite:
                return
            target.unlink()
        _link_or_copy(src, target)
    except Exception:
        pass
