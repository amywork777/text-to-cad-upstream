"""The user-level cadgen cache root and its tiers — ONE resolution rule.

Every user-level cache (the component store, the op-memo disk tier, the shared
mesh/tessellation cache) lives under a single root so one env knob relocates
everything and one command (``cadgen cache``) can reason about all of it:

1. ``$CADGEN_STORE_DIR`` when set — the explicit override, honored by BOTH
   languages and every tier.
2. The platform cache convention: ``$XDG_CACHE_HOME/cadgen`` on POSIX when
   set; ``%LOCALAPPDATA%\\cadgen`` on Windows when set. (Windows behavior is
   untested in CI — the repo has no Windows runner — so this stays trivially
   auditable: two env reads and a join.)
3. ``~/.cache/cadgen`` otherwise — the historical default, all platforms.

The JS mirror is ``cadgenCacheRootDir`` in
``packages/cadjs/src/lib/surf/tessellationCacheFs.mjs`` (and its deliberate
inline copy in ``viewer/server/tessCache.mjs``);
``tests/python/global/test_cache_root_sync.py`` pins the languages together.

Everything under the root is content-addressed and BEST-EFFORT: deleting any
entry — or the whole root — at any time costs a rebuild, never correctness. A
reader racing a deletion simply re-misses; a producer racing one re-publishes.
"""

from __future__ import annotations

import os
from pathlib import Path

# Mirror of TESSELLATION_VERSION in packages/cadjs/src/lib/surf/tessellate.js
# (sync-tested by tests/python/global/test_cache_root_sync.py). It salts every
# mesh-cache key as ``-t<version>-``; ``cadgen cache gc`` uses it to identify
# dead mesh generations by name.
MESH_TESSELLATION_VERSION = 1


def cache_root() -> Path:
    override = os.environ.get("CADGEN_STORE_DIR", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "cadgen"
    else:
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
        if xdg_cache_home:
            return Path(xdg_cache_home) / "cadgen"
    return Path.home() / ".cache" / "cadgen"


def components_dir() -> Path:
    return cache_root() / "components"


def opmemo_base_dir() -> Path:
    """The op-memo tier's base (one salt-named subdirectory per generation).

    ``CADGEN_OP_MEMO_DISK_DIR`` remains an op-memo-specific override of the
    base, kept for tests and pre-existing setups.
    """
    override = os.environ.get("CADGEN_OP_MEMO_DISK_DIR", "").strip()
    if override:
        return Path(override)
    return cache_root() / "opmemo"


def meshes_dir() -> Path:
    return cache_root() / "meshes"


def packages_dir() -> Path:
    """Render-package index: ``packages/<stepHash>-v<STEP_PACKAGE_VERSION>/``,
    one self-contained package per DOCUMENT (STEP/DXF bytes), whichever
    producer built it. Components inside a package hardlink into
    :func:`components_dir`, so relocation costs no duplication."""
    return cache_root() / "packages"


def locks_dir() -> Path:
    """Coordination scopes: locks and progress records keyed by the MODEL
    path (``cadgen.catalog.artifact_path_key``), not by output content — two
    runs building the same model must exclude each other even while the
    content hash they will produce is still unknown."""
    return cache_root() / "locks"


def records_dir() -> Path:
    """Per-model freshness records (step/dxf export records), keyed like
    locks. Bookkeeping, not artifacts: deleting one costs a rebuild check."""
    return cache_root() / "records"
