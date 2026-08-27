"""Shared content-addressed store for built component GLBs.

Packages stay fully self-contained: every package's ``components/<cid>.glb``
remains a real directory entry the viewer serves and orphan pruning manages.
The store is a cache TIER behind that layout, pnpm-style: when a package
needs a component the store already holds, it materializes as a hardlink
(same inode, zero copy; silent copy fallback across filesystems), skipping
the mesh + selector-extraction build entirely. Deleting the store never
breaks a package — the package's own links keep the bytes alive — which is
the property that makes this a cache and not an artifact location.

Store keys are ``<cid>-l<linear>-a<angular>``: the cid addresses geometry
(salted by STEP_PACKAGE_VERSION), but GLB bytes also depend on the mesh
deflections, which the cid deliberately does not capture.

Layout: ``$CADGEN_STORE_DIR (default ~/.cache/cadgen)/components/<key>.glb``.
``CADGEN_COMPONENT_STORE=0`` disables both directions. Writes are atomic
(hardlink, or temp+rename for copies); every failure degrades to building
locally, never to an error.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cadgen._internal.atomic_replace import replace_atomic


def _enabled() -> bool:
    return os.environ.get("CADGEN_COMPONENT_STORE", "1") != "0"


def _store_dir() -> Path:
    root = os.environ.get("CADGEN_STORE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "cadgen")
    path = Path(root) / "components"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_path(cid: str, linear_deflection: float, angular_deflection: float) -> Path:
    return _store_dir() / f"{cid}-l{linear_deflection:g}-a{angular_deflection:g}.glb"


def _surf_store_path(cid: str) -> Path:
    # Exact-surface artifact: pure geometry, no deflections in the key. This
    # is the final store shape (design/surface-rendering.md); the deflection-
    # keyed GLB beside it is the display path scheduled for deletion at R5.
    return _store_dir() / f"{cid}.surf"


def _link_or_copy(source: Path, dest: Path) -> None:
    dest.unlink(missing_ok=True)
    try:
        os.link(source, dest)
    except OSError:
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copyfile(source, tmp)
        replace_atomic(tmp, dest)


def fetch(cid: str, linear_deflection: float, angular_deflection: float,
          dest: Path) -> bool:
    """Materialize a stored component (GLB + sibling .surf) at ``dest``.
    True on success. A store entry missing either artifact is treated as
    absent so the caller rebuilds both."""
    if not _enabled():
        return False
    try:
        source = _store_path(cid, linear_deflection, angular_deflection)
        surf_source = _surf_store_path(cid)
        if not source.exists() or not surf_source.exists():
            return False
        _link_or_copy(source, dest)
        _link_or_copy(surf_source, dest.with_name(f"{cid}.surf"))
        return True
    except Exception:
        return False


def publish(src: Path, cid: str, linear_deflection: float,
            angular_deflection: float, *, overwrite: bool = False) -> None:
    """Record a locally built component (GLB + sibling .surf) in the store.
    Best-effort."""
    if not _enabled():
        return
    try:
        pairs = [(src, _store_path(cid, linear_deflection, angular_deflection))]
        surf_src = src.with_name(f"{cid}.surf")
        if surf_src.exists():
            pairs.append((surf_src, _surf_store_path(cid)))
        for source, target in pairs:
            if target.exists():
                if not overwrite:
                    continue
                target.unlink()
            _link_or_copy(source, target)
    except Exception:
        pass
