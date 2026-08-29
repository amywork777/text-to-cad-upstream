"""Shared cross-package component store.

Packages stay fully self-contained: every package's ``components/<cid>.surf``
is a real file (hardlinked from the store where possible). The store is a
best-effort cache — losing it costs a re-extraction, never correctness.

Layout: ``<cache root>/components/<cid>.surf`` plus ``<cid>.brep`` (the
exact-shape blob — design/step-document-architecture.md), with the root
resolved by :mod:`cadgen._internal.cache_paths` (``CADGEN_STORE_DIR``, then
the platform cache dir). The key is the BARE cid: both artifacts are exact
geometry with no mesh tolerances, and the cid is already salted by
``CACHE_SCHEMA_VERSION`` so extractor changes re-key the store wholesale.

``CADGEN_COMPONENT_STORE=0`` disables both directions.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cadgen._internal.atomic_replace import replace_atomic
from cadgen._internal.cache_paths import components_dir


def _enabled() -> bool:
    return os.environ.get("CADGEN_COMPONENT_STORE", "").strip() != "0"


def _store_dir() -> Path:
    path = components_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_path(cid: str, suffix: str = "surf") -> Path:
    return _store_dir() / f"{cid}.{suffix}"


def _link_or_copy(source: Path, dest: Path) -> None:
    dest.unlink(missing_ok=True)
    try:
        os.link(source, dest)
    except OSError:
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copyfile(source, tmp)
        replace_atomic(tmp, dest)


def fetch(cid: str, dest: Path) -> bool:
    """Materialize a stored component pair (``.surf`` + ``.brep``) at
    ``dest``'s directory. An entry missing either half is treated as absent
    so the caller rebuilds both. True on success."""
    if not _enabled():
        return False
    try:
        surf_source = _store_path(cid, "surf")
        brep_source = _store_path(cid, "brep")
        if not surf_source.exists() or not brep_source.exists():
            return False
        _link_or_copy(brep_source, dest.with_name(f"{cid}.brep"))
        _link_or_copy(surf_source, dest)
        return True
    except Exception:
        return False


def publish(src: Path, cid: str, *, overwrite: bool = False) -> None:
    """Record a locally built component pair in the store. Best-effort."""
    if not _enabled():
        return
    try:
        pairs = [(src, _store_path(cid, "surf"))]
        brep_src = src.with_name(f"{cid}.brep")
        if brep_src.exists():
            pairs.append((brep_src, _store_path(cid, "brep")))
        for source, target in pairs:
            if target.exists():
                if not overwrite:
                    continue
                target.unlink()
            _link_or_copy(source, target)
    except Exception:
        pass
