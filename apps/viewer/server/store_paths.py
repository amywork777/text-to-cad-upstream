"""Store layout: the cache root, its tiers, and the keys that name things in it.

This is ONE module where the Node backend had two (``storePaths.mjs`` +
``packageContract.mjs``), and it is a deliberate local copy of helpers cadgen
also owns rather than an import of them.

WHY NOT ``from cadgen.catalog import render_package_dir``
--------------------------------------------------------
cadgen's own versions are stdlib-only and cost ~40ms to import, so the
temptation is real. But importing them makes cadgen a HARD dependency of
VIEWING, and the shipped contract is the opposite: with no cadgen the catalog
still lists, packages still render, components still stream, and only the
import path degrades. cadgen also drags a ~300MB kernel that someone who wants
to look at an ``.stl`` should never pay for. So: one local stdlib
implementation here, cadgen imported lazily and only on the compile path.

The duplication is policed BEHAVIOURALLY — ``tests_server/test_store_paths.py``
imports both cadgen's helpers and these and asserts equal outputs over a matrix
of environment states and paths. That is stronger than the grep-of-JS-source
tests it replaces, and it is not a tautology: the two implementations stay
genuinely independent.

ONE DELIBERATE BEHAVIOUR CHANGE FROM THE JS
-------------------------------------------
``artifact_path_key`` resolves with ``Path.expanduser().resolve()`` — cadgen's
semantics — where ``storePaths.mjs`` fell back to a purely lexical
``path.resolve`` when ``realpathSync`` threw. For an EXISTING file the two
agree. For a MISSING one under a symlinked ancestor they did not, so the viewer
and cadgen keyed the locks and records tiers differently for exactly the paths
that tier is about. Nothing pins the old key (``scanner.test.mjs`` only checks
the ``unbuilt-`` prefix and that the directory does not exist), and the catalog
diff is unaffected because a scanned file is readable by construction.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

__all__ = [
    "ARTIFACT_PATH_KEY_LENGTH",
    "CACHE_SCHEMA_VERSION",
    "PROVENANCE_RECORD_SUFFIX",
    "RECORDS_DIR_NAME",
    "SOURCE_SIDECAR_NAMES",
    "SOURCE_SIDECAR_SCHEMA_VERSION",
    "SOURCE_SIDECAR_SUFFIX",
    "artifact_file_hash",
    "artifact_path_key",
    "cadgen_cache_root_dir",
    "coordination_scope",
    "package_dir_for_hash",
    "render_package_dir",
    "source_provenance_record_path",
    "source_sidecar_path",
    "store_locks_dir",
    "store_packages_dir",
    "store_records_dir",
]

# --- the render contract --------------------------------------------------

# The ONE cache-scheme number. It salts every store package key
# (``<hash>-v<N>``), so a bump orphans old artifacts BY NAME and everything
# regenerates on demand. No artifact records a version inside itself: a package
# that resolves at all is current-scheme by construction.
CACHE_SCHEMA_VERSION = 17

# The source sidecar sits beside the model at ``<name>.step.json`` and carries
# the model's DECLARATIONS. APPENDED to the artifact's whole name, so
# ``part.step`` -> ``part.step.json``.
#
# Never test a path with ``endswith(SOURCE_SIDECAR_SUFFIX)`` alone — it is
# ``.json``, and serving every JSON file under a served root would hand out
# configs and secrets. Use SOURCE_SIDECAR_NAMES where a path is all you have.
SOURCE_SIDECAR_SUFFIX = ".json"
SOURCE_SIDECAR_NAMES = (".step.json", ".stp.json")
SOURCE_SIDECAR_SCHEMA_VERSION = 5

# The records tier, where a build's provenance actually lives. Evictable by
# design (``cadgen cache gc`` sweeps it): a missing record must degrade to
# "imported", never to an error.
RECORDS_DIR_NAME = "records"
PROVENANCE_RECORD_SUFFIX = ".source.json"
ARTIFACT_PATH_KEY_LENGTH = 24


# --- cache root -----------------------------------------------------------


def cadgen_cache_root_dir() -> str:
    """``CADGEN_CACHE_DIR``, else the platform convention, else ``~/.cache/cadgen``.

    Read from the environment on EVERY call, never memoised: the suites set
    these variables after the app is constructed and expect the next call to
    observe the change.

    Note the platform asymmetry is real — on Windows ``XDG_CACHE_HOME`` is
    never consulted, and on POSIX ``LOCALAPPDATA`` never is. And the
    ``CADGEN_CACHE_DIR`` override is used VERBATIM: it does not get ``/cadgen``
    appended the way the other two branches do.
    """
    override = os.environ.get("CADGEN_CACHE_DIR", "").strip()
    if override:
        return override
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return os.path.join(local_app_data, "cadgen")
    else:
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
        if xdg_cache_home:
            return os.path.join(xdg_cache_home, "cadgen")
    return os.path.join(os.path.expanduser("~"), ".cache", "cadgen")


def store_packages_dir() -> str:
    return os.path.join(cadgen_cache_root_dir(), "packages")


def store_locks_dir() -> str:
    return os.path.join(cadgen_cache_root_dir(), "locks")


def store_records_dir() -> str:
    return os.path.join(cadgen_cache_root_dir(), RECORDS_DIR_NAME)


# --- content hashing ------------------------------------------------------

# Memoised on (resolved path, mtime_ns, size). Status polls and catalog scans
# re-ask for the same file's hash constantly, and re-reading a multi-hundred-MB
# STEP per poll would put a full file read on the hot path. A stale hit needs an
# edit that preserves BOTH the nanosecond mtime and the byte size — not a real
# editor.
#
# Bounded, unlike the JS map: this process is long-lived and a large corpus
# would otherwise grow it without limit.
_HASH_MEMO: dict[str, tuple[int, int, str]] = {}
_HASH_MEMO_LIMIT = 4096
_HASH_MEMO_LOCK = threading.Lock()


def artifact_file_hash(file_path) -> str | None:
    """sha256 of the file's bytes, or ``None`` when it cannot be read.

    ``None`` is the "no package" answer, not an error: every caller turns it
    into a deterministic never-created path.
    """
    try:
        resolved = os.path.realpath(file_path)
        stat_result = os.stat(resolved)
    except (OSError, ValueError):
        return None
    key = (stat_result.st_mtime_ns, stat_result.st_size)
    with _HASH_MEMO_LOCK:
        cached = _HASH_MEMO.get(resolved)
    if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
        return cached[2]
    digest = hashlib.sha256()
    try:
        with open(resolved, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    hexdigest = digest.hexdigest()
    with _HASH_MEMO_LOCK:
        if len(_HASH_MEMO) >= _HASH_MEMO_LIMIT:
            _HASH_MEMO.clear()
        _HASH_MEMO[resolved] = (key[0], key[1], hexdigest)
    return hexdigest


# --- keys -----------------------------------------------------------------


def package_dir_for_hash(step_hash: str) -> str:
    return os.path.join(store_packages_dir(), f"{step_hash}-v{CACHE_SCHEMA_VERSION}")


def render_package_dir(file_path) -> str:
    """The store package for an artifact, resolved by CONTENT.

    Same bytes anywhere on disk resolve to the same package; different bytes to
    a different one. An unreadable or missing file resolves to
    ``packages/unbuilt-<pathKey>``, a deterministic path that is never created,
    so every existence-checking caller answers "no package" with no special
    case.
    """
    digest = artifact_file_hash(file_path)
    if digest is None:
        return os.path.join(store_packages_dir(), f"unbuilt-{artifact_path_key(file_path)}")
    return package_dir_for_hash(digest)


def artifact_path_key(file_path) -> str:
    """Model-PATH identity for the locks and records tiers.

    sha256 of the resolved path string, truncated to 24 hex chars. See the
    module docstring for why this resolves the way cadgen does rather than the
    way the JS did.
    """
    try:
        resolved = str(Path(str(file_path)).expanduser().resolve())
    except (OSError, ValueError, RuntimeError):
        resolved = os.path.abspath(str(file_path))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:ARTIFACT_PATH_KEY_LENGTH]


def coordination_scope(file_path) -> str:
    """``<cache>/locks/<pathKey>`` — a NAME, never created as a directory.

    The progress reader derives dot-named siblings from it.
    """
    return os.path.join(store_locks_dir(), artifact_path_key(file_path))


def source_provenance_record_path(file_path) -> str:
    """``<cache>/records/<pathKey>.source.json``.

    Path-keyed like the lock, because it is memory ABOUT a model rather than a
    product of one — two byte-identical documents share a package but never
    share provenance.
    """
    return os.path.join(store_records_dir(), f"{artifact_path_key(file_path)}{PROVENANCE_RECORD_SUFFIX}")


def source_sidecar_path(entry_path) -> str:
    """``part.step`` -> ``part.step.json``: the suffix is APPENDED to the whole name."""
    return f"{os.path.abspath(str(entry_path))}{SOURCE_SIDECAR_SUFFIX}"
