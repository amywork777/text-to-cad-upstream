"""Composition seams for traced, cached model subtrees.

``child_entry(path)`` replaces the hand-rolled ``importlib`` loaders parent
entries use to compose sibling generators, and ``@memo`` marks expensive
model functions. Both are SCOPES (design/production-architecture.md): their
results are cached in the shared store keyed by source — the scope's static
import closure plus everything observed executing/reading during a miss —
so an edit that does not reach a scope's sources skips the scope's Python,
kernel work, and any nondeterminism wholesale. Validation is a semantic
re-hash of the recorded file list (stat-cached, milliseconds); a resident
session can install a cheaper validator that answers from its watcher.

Rules inherited from the op layer: a miss returns the same canonical
reconstruction a future hit would (cache-state independence); anything
unkeyable, untrackable, or unfreezable falls through to plain execution
(correctness never depends on a hit). Kill switch: ``CADGEN_SCOPE_CACHE=0``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path

from cadgen._internal import scope_capture, scope_store

_lock = threading.RLock()
_stats = {"hits": 0, "misses": 0, "unkeyable": 0, "unfreezable": 0,
          "untrackable": 0, "errors": 0}

# (resolved path, mtime_ns, size) -> loaded module. Keyed on stat so an
# edited child reloads even though this cache outlives the runner's
# first-party module eviction.
_MODULE_CACHE: dict[tuple[str, int, int], object] = {}

# Optional session-installed fast validator: files-unchanged answers from a
# watcher instead of re-hashing. Returning None means "don't know, re-hash".
_scope_validator = None


def set_scope_validator(validator) -> None:
    global _scope_validator
    _scope_validator = validator


def stats() -> dict:
    with _lock:
        return dict(_stats)


def _enabled() -> bool:
    return os.environ.get("CADGEN_SCOPE_CACHE", "1") != "0"


def _caller_dir() -> Path | None:
    frame = sys._getframe(2)
    file_name = frame.f_globals.get("__file__")
    return Path(file_name).resolve().parent if file_name else None


def _resolve_entry(path: Path | str, caller_dir: Path | None) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() and caller_dir is not None:
        candidate = caller_dir / candidate
    return candidate.resolve()


def _load_module(entry: Path):
    stat = entry.stat()
    key = (str(entry), stat.st_mtime_ns, stat.st_size)
    with _lock:
        cached = _MODULE_CACHE.get(key)
        if cached is not None:
            return cached
    root = str(entry.parent)
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        spec = importlib.util.spec_from_file_location(entry.stem, entry)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
    with _lock:
        _MODULE_CACHE[key] = module
    return module


def _args_key(args: tuple, kwargs: dict):
    from cadgen._internal.op_memo import _Unkeyable, _build_key

    try:
        return _build_key("scope", args, kwargs)
    except _Unkeyable:
        return None
    except Exception:
        return None


def _run_scope(scope_id: str, entry_file: Path, root: Path,
               call, args: tuple, kwargs: dict):
    """The shared hit/miss flow for both seam kinds."""
    if not _enabled():
        return call()

    args_key = _args_key(args, kwargs)
    if args_key is None and (args or kwargs):
        with _lock:
            _stats["unkeyable"] += 1
        return call()

    key = scope_store.scope_key(scope_id, args_key)

    entry = None
    if _scope_validator is not None:
        entry = _scope_validator(key, root)
    if entry is None:
        entry = scope_store.load_valid_scope_entry(key, base=root)
    if entry is not None:
        try:
            value = scope_store.thaw_value(entry["value"])
        except Exception:
            with _lock:
                _stats["errors"] += 1
        else:
            with _lock:
                _stats["hits"] += 1
            return value

    # A miss must execute against CURRENT sources: the process may hold stale
    # first-party modules (a helper edited since they were imported), so the
    # scope gets the same clean-module guarantee the generation runner gives a
    # full run. Existing references in the caller keep working; re-imports
    # inside this scope see fresh code.
    from cadgen._internal.source_hash import evict_first_party_modules

    evict_first_party_modules()
    # CPython validates .pyc files by (whole-second mtime, size): two
    # same-length edits inside one second load STALE BYTECODE on re-import —
    # exactly the cadence of an agent-driven edit loop. A miss is already a
    # rebuild, so drop the bytecode caches next to this scope's sources.
    import shutil

    pycache_parents = {Path(entry_file).resolve().parent}
    pycache_parents |= {
        f.parent for f in scope_capture.static_import_closure(Path(entry_file), root)
    }
    for parent in pycache_parents:
        shutil.rmtree(parent / "__pycache__", ignore_errors=True)
    # Belt and braces: the first-party classifier is environment-derived, so
    # also drop by location — any loaded module living under this scope's
    # root is definitionally this model's code and must re-import fresh.
    root_resolved = Path(root).resolve()
    for name, module in list(sys.modules.items()):
        file_name = getattr(module, "__file__", None)
        if not file_name:
            continue
        try:
            inside = Path(file_name).resolve().is_relative_to(root_resolved)
        except (OSError, ValueError):
            continue
        if inside:
            sys.modules.pop(name, None)
    with _lock:
        _MODULE_CACHE.clear()
    with scope_capture.scoped_recording(entry_file, root) as recording:
        result = call()
    with _lock:
        _stats["misses"] += 1

    closure = scope_capture.scope_closure(entry_file, recording)
    if closure is None:
        with _lock:
            _stats["untrackable"] += 1
        return result
    try:
        frozen = scope_store.freeze_value(result)
    except scope_store.Unfreezable:
        with _lock:
            _stats["unfreezable"] += 1
        return result
    except Exception:
        with _lock:
            _stats["errors"] += 1
        return result
    try:
        scope_store.save_scope_entry(
            key,
            closure_hash=closure.closure_hash,
            files=closure.files,
            frozen_value=frozen,
            scope_id=scope_id,
        )
        # The caller gets the same canonical reconstruction a future hit
        # returns: output must not depend on cache state.
        return scope_store.thaw_value(frozen)
    except Exception:
        with _lock:
            _stats["errors"] += 1
        return result


class ChildEntry:
    """A composed sibling generator. ``gen_step`` is the cached scope; every
    other attribute lazily proxies to the loaded module."""

    def __init__(self, entry: Path):
        self._entry = entry
        self._root = entry.parent

    def gen_step(self, *args, **kwargs):
        scope_id = self._entry.name
        return _run_scope(
            scope_id, self._entry, self._root,
            lambda: _load_module(self._entry).gen_step(*args, **kwargs),
            args, kwargs,
        )

    def __getattr__(self, name: str):
        return getattr(_load_module(self._entry), name)


def child_entry(path: Path | str) -> ChildEntry:
    """Load a sibling ``.step.py`` generator as a traced, cached scope.

    Relative paths resolve against the calling file's directory. The child's
    directory is guaranteed on ``sys.path`` while its module loads, so
    ``import _helpers``-style sibling imports work regardless of the process
    working directory."""
    entry = _resolve_entry(path, _caller_dir())
    if not entry.is_file():
        raise FileNotFoundError(f"child entry not found: {entry}")
    return ChildEntry(entry)


def memo(fn):
    """Cache an expensive model function as a traced scope. The function must
    be pure given its arguments and its source closure, and must return
    shapes/compounds (or JSON-able values)."""
    import functools

    file_name = fn.__globals__.get("__file__")
    entry_file = Path(file_name).resolve() if file_name else None

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if entry_file is None:
            return fn(*args, **kwargs)
        scope_id = f"{entry_file.name}::{fn.__qualname__}"
        return _run_scope(
            scope_id, entry_file, entry_file.parent,
            lambda: fn(*args, **kwargs), args, kwargs,
        )

    wrapper.__cadgen_memo__ = True
    return wrapper
