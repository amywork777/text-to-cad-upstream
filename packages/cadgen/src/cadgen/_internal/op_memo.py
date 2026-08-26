"""Input-keyed memoization of build123d/OCCT kernel operations.

The incremental-generation design (design/incremental-generation.md) keeps the
deterministic full re-execution of model scripts and makes it cheap by caching
kernel operations on their INPUTS: an op call whose (operation, parameters,
input shapes) match a prior call returns the previously built shape instead of
re-running OCCT. Re-execution + op memoization recomputes exactly what a
dependency-graph system would: an edit re-runs only the ops whose inputs
changed, and everything downstream of them.

Scope and placement:

- Patches install at the TOPOLOGY layer (``Shape._bool_op``, ``Mixin3D``
  fillet/chamfer, ``Face``/``Solid``/``Wire`` factory classmethods) — pure
  shape-in/shape-out functions. The ``operations_*`` wrappers (``extrude()``,
  ``fillet()``…) mutate builder context and are deliberately NOT patched; their
  inner topology calls are the memo points.
- The cache lives in this module, which survives the generation runner's
  first-party module eviction (cadgen and site-packages are never evicted), so
  a warm daemon worker keeps its cache across requests.
- Keys hash input shapes by their BinTools BREP bytes: location-stripped bytes
  memoized per TShape, combined with the shape's location matrix. Fresh
  rebuilds of identical geometry serialize byte-identically (verified in the
  design doc's Phase 0 spike), so keys hit across full re-executions.
- Cache hits return a shallow copy of the stored build123d object: a fresh
  wrapper sharing the same immutable TShape. Callers must not mutate cached
  TShapes (the same discipline validity.py and interference.py already
  document); triangulation attachment is tolerated.

Kill switch: ``CADGEN_OP_MEMO=0``. Capacity: ``CADGEN_OP_MEMO_SIZE`` (entries,
default 4096). Stats: ``CADGEN_OP_MEMO_STATS=1`` logs a summary per process
exit and after each install.

Anything unkeyable — an argument type the normalizer does not understand, a
shape that fails to serialize — falls through to the original call, uncached.
Correctness never depends on a cache hit.
"""

from __future__ import annotations

import atexit
import hashlib
import io
import os
import struct
import sys
import threading
from collections import OrderedDict

from cadgen._internal.atomic_replace import replace_atomic

# Salt: bump _OP_MEMO_VERSION whenever keying or hit semantics change.
_OP_MEMO_VERSION = 1

_lock = threading.RLock()
_cache: OrderedDict[tuple, object] = OrderedDict()
_tshape_bytes_memo: dict[object, str] = {}
_stats = {"hits": 0, "misses": 0, "disk_hits": 0, "unkeyable": 0,
          "unstorable": 0, "evicted": 0, "errors": 0}
_installed = False


class _Unkeyable(Exception):
    """An argument cannot participate in a memo key; skip caching this call."""


def _enabled() -> bool:
    return os.environ.get("CADGEN_OP_MEMO", "1") != "0"


def _capacity() -> int:
    try:
        return max(64, int(os.environ.get("CADGEN_OP_MEMO_SIZE", "4096")))
    except ValueError:
        return 4096


def _tshape_digest(wrapped) -> str:
    """Location-stripped BREP digest of a TopoDS_Shape, memoized per TShape."""
    from OCP.BinTools import BinTools
    from OCP.TopLoc import TopLoc_Location

    tshape = wrapped.TShape()
    cached = _tshape_bytes_memo.get(tshape)
    if cached is not None:
        return cached
    stream = io.BytesIO()
    BinTools.Write_s(wrapped.Located(TopLoc_Location()), stream)
    digest = hashlib.sha256(stream.getvalue()).hexdigest()
    if len(_tshape_bytes_memo) > 4 * _capacity():
        _tshape_bytes_memo.clear()
    _tshape_bytes_memo[tshape] = digest
    return digest


def _location_key(wrapped) -> tuple:
    trsf = wrapped.Location().Transformation()
    values = []
    for row in (1, 2, 3):
        for col in (1, 2, 3, 4):
            values.append(struct.pack("<d", trsf.Value(row, col)))
    return (b"".join(values),)


def _shape_key(shape) -> tuple:
    wrapped = shape.wrapped
    if wrapped is None:
        raise _Unkeyable("shape with no wrapped TopoDS")
    # The full TopoDS_Shape triple: TShape (content-digested), Location, and
    # Orientation. Orientation must be explicit — a reversed shape shares its
    # TShape with the forward one, and aliasing them flips downstream geometry.
    return ("shape", _tshape_digest(wrapped), _location_key(wrapped),
            int(wrapped.Orientation()))


def _normalize(value) -> object:
    """Normalize one argument into a hashable, deterministic key component."""
    if value is None or isinstance(value, (bool, str, bytes)):
        return value
    if isinstance(value, float):
        return ("f", struct.pack("<d", value))
    if isinstance(value, int):
        return ("i", value)
    if isinstance(value, (tuple, list)):
        return ("seq", tuple(_normalize(v) for v in value))
    if isinstance(value, dict):
        return ("map", tuple(sorted((k, _normalize(v)) for k, v in value.items())))

    type_name = type(value).__name__

    # OCCT algo builder instances (Shape._bool_op's `operation` param): the
    # class fully identifies the operation as build123d constructs them.
    if type_name.startswith("BRepAlgoAPI"):
        return ("occ_op", type_name)

    # build123d geometry value types, normalized through their float tuples.
    module = type(value).__module__ or ""
    if module.startswith("build123d"):
        if hasattr(value, "wrapped") and getattr(value, "wrapped", None) is not None:
            try:
                return _shape_key(value)
            except _Unkeyable:
                raise
            except Exception as exc:  # serialization failure => uncacheable
                raise _Unkeyable(str(exc)) from exc
        to_tuple = getattr(value, "to_tuple", None)
        if callable(to_tuple):
            return (type_name, _normalize(to_tuple()))
        if type_name == "Axis":
            return (type_name, _normalize(value.position.to_tuple()),
                    _normalize(value.direction.to_tuple()))
        if type_name == "Plane":
            return (type_name, _normalize(value.origin.to_tuple()),
                    _normalize(value.x_dir.to_tuple()),
                    _normalize(value.z_dir.to_tuple()))
        if type_name == "Location":
            return (type_name, _normalize(tuple(value.to_tuple()[0])),
                    _normalize(tuple(value.to_tuple()[1])))
    if module.startswith("enum") or hasattr(value, "name") and isinstance(getattr(type(value), "__members__", None), dict):
        return ("enum", type_name, value.name)

    # One-shot iterables cannot be keyed without consuming them, and the memo
    # layer never alters or consumes what the caller passed.
    raise _Unkeyable(f"unkeyable argument type: {module}.{type_name}")


def _reject_lazy(value) -> None:
    """Refuse to key arguments that keying would have to consume.

    A generator (or other one-shot iterable) can only be keyed by
    materializing it, and handing the op a materialized copy measurably
    changes results for some ops — the memo layer must NEVER alter what the
    caller passed. Concrete types (shapes, build123d value types, str/bytes,
    tuples/lists/dicts, numbers) are keyable in place; everything else lazy
    raises _Unkeyable and the call passes through uncached, verbatim.
    """
    if value is None or isinstance(value, (str, bytes, bool, int, float,
                                           tuple, list, dict)):
        return
    if hasattr(value, "wrapped"):
        return
    if (type(value).__module__ or "").startswith("build123d"):
        return
    if hasattr(value, "__iter__"):
        raise _Unkeyable(f"lazy iterable argument: {type(value).__name__}")


def _build_key(op_name: str, args: tuple, kwargs: dict) -> tuple:
    """Build the memo key from the caller's arguments, never mutating or
    consuming them."""
    key_parts = []
    for arg in args:
        _reject_lazy(arg)
        key_parts.append(_normalize(arg))
    kw_parts = []
    for name, val in sorted(kwargs.items()):
        _reject_lazy(val)
        kw_parts.append((name, _normalize(val)))
    return (_OP_MEMO_VERSION, op_name, tuple(key_parts), tuple(kw_parts))


def _store(key: tuple, result: object) -> None:
    with _lock:
        _cache[key] = result
        _cache.move_to_end(key)
        capacity = _capacity()
        while len(_cache) > capacity:
            _cache.popitem(last=False)
    _disk_put(key, result)


def _lookup(key: tuple):
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    stored = _disk_get(key)
    if stored is not None:
        with _lock:
            _cache[key] = stored
            _cache.move_to_end(key)
        _stats["disk_hits"] += 1
    return stored


# --- persistent tier -------------------------------------------------------
#
# The canonical bytes ARE the durable representation, so persisting them gives
# a cold process (fresh daemon worker, CLI run, worktree, or a different model
# reusing the same part) the same skip a warm one gets. Keys are pure
# functions of op + inputs, content-addressed and salted, so the tier is
# shared safely across processes and checkouts; writes are atomic
# temp+rename, and any read problem falls back to executing the op.

def _disk_enabled() -> bool:
    return os.environ.get("CADGEN_OP_MEMO_DISK", "1") != "0"


def _disk_dir() -> str:
    # Resolved per call so tests (and long-lived workers) honor env changes;
    # the makedirs is a no-op syscall next to any kernel op.
    import build123d

    base = os.environ.get("CADGEN_OP_MEMO_DISK_DIR")
    if not base:
        store_root = os.environ.get("CADGEN_STORE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "cadgen")
        base = os.path.join(store_root, "opmemo")
    salt = f"v{_OP_MEMO_VERSION}-b123d{getattr(build123d, '__version__', 'unknown')}"
    path = os.path.join(base, salt)
    os.makedirs(path, exist_ok=True)
    return path


def _disk_path(key: tuple) -> str:
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
    return os.path.join(_disk_dir(), f"{digest}.brep")


def _disk_put(key: tuple, stored) -> None:
    if not _disk_enabled() or not isinstance(stored, _StoredShape):
        return
    try:
        import json

        cls = type(stored.template)
        header = json.dumps({"cls": f"{cls.__module__}.{cls.__qualname__}"})
        path = _disk_path(key)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(header.encode("utf-8") + b"\n" + stored.brep)
        replace_atomic(tmp, path)
    except Exception:
        _stats["errors"] += 1


def _resolve_shape_class(dotted: str):
    import importlib

    module_name, _, qualname = dotted.rpartition(".")
    if not module_name.startswith("build123d"):
        raise ValueError(f"refusing non-build123d class {dotted}")
    obj = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _disk_get(key: tuple):
    if not _disk_enabled():
        return None
    try:
        import json

        path = _disk_path(key)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            header, _, brep = fh.read().partition(b"\n")
        cls = _resolve_shape_class(json.loads(header.decode("utf-8"))["cls"])
        template = cls(_downcast(_read_brep(brep)))
        return _StoredShape(template, brep)
    except Exception:
        _stats["errors"] += 1
        return None


class _StoredShape:
    """A cached op result: canonical BREP bytes + a wrapper template.

    Cache correctness rests on CANONICAL RECONSTRUCTION. Cached shapes cannot
    be handed out live: downstream consumers mutate them (booleans and lofts
    bump input tolerances; meshing and bounding_box attach triangulation), so
    a live master is polluted by its own first use, and every isolation
    mechanism that preserves the live shape loses byte fidelity
    (BRepBuilderAPI_Copy re-serializes differently; BinTools write→read→write
    is not byte-stable for ~65% of real shapes).

    Instead, a cacheable result is serialized ONCE at op time (its canonical
    bytes), and EVERY consumer — the missing caller included — receives a
    fresh reconstruction read back from those bytes. All runs, cold or warm,
    therefore flow byte-identical shapes derived deterministically from the
    canonical bytes, which makes package output independent of cache state.
    Reconstructed inputs produce byte-identical downstream op results
    (validated empirically); a shape whose bytes fail to read back is simply
    not cached and the caller gets the original, exactly as un-memoized
    execution would.

    Relative to memo-OFF execution, canonicalization may change the exact
    bytes of some leaf components (geometrically identical). That is an
    accepted, versioned change: content addressing absorbs it as a one-time
    re-key, per the no-backwards-compatibility policy.
    """

    __slots__ = ("template", "brep")

    def __init__(self, template, brep: bytes):
        self.template = template
        self.brep = brep


def _write_brep(wrapped) -> bytes:
    """Canonical geometry-only serialization (no triangulation/normals —
    mirrors component_package._shape_brep_bytes), location kept as-is."""
    from OCP.BinTools import BinTools, BinTools_FormatVersion

    stream = io.BytesIO()
    BinTools.Write_s(
        wrapped,
        stream,
        False,  # theWithTriangles
        False,  # theWithNormals
        BinTools_FormatVersion.BinTools_FormatVersion_CURRENT,
    )
    return stream.getvalue()


def _read_brep(data: bytes):
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(data))
    if shape.IsNull():
        raise ValueError("BinTools read produced a null shape")
    return shape


def _downcast(wrapped):
    from build123d.topology import downcast

    return downcast(wrapped)


def _freeze_result(result):
    """Convert an op result into its stored form, verifying its bytes read
    back. Raises _Unkeyable when the result cannot be cached."""
    import copy

    if isinstance(result, (tuple, list)):
        return ("seq", type(result), tuple(_freeze_result(r) for r in result))
    if hasattr(result, "wrapped") and result.wrapped is not None:
        data = _write_brep(result.wrapped)
        template = copy.copy(result)
        # The template's wrapped is never handed out (thaw re-reads), but
        # pointing it at an isolated reconstruction rather than the live
        # result avoids pinning the caller's mutable TShape. This read also
        # proves the bytes are readable before anything is stored.
        template.wrapped = _downcast(_read_brep(data))
        return _StoredShape(template, data)
    if result is None or isinstance(result, (bool, int, float, str, bytes)):
        return result
    raise _Unkeyable(f"unstorable result type: {type(result).__name__}")


def _thaw_result(stored):
    """Produce a fresh, independent reconstruction of a stored result."""
    import copy

    if isinstance(stored, tuple) and stored and stored[0] == "seq":
        _, seq_type, items = stored
        return seq_type(_thaw_result(item) for item in items)
    if isinstance(stored, _StoredShape):
        clone = copy.copy(stored.template)
        clone.wrapped = _downcast(_read_brep(stored.brep))
        return clone
    return stored


def _result_digest(result) -> str:
    try:
        if isinstance(result, (tuple, list)):
            return "|".join(_result_digest(r) for r in result)
        if hasattr(result, "wrapped") and result.wrapped is not None:
            from OCP.BinTools import BinTools

            stream = io.BytesIO()
            BinTools.Write_s(result.wrapped, stream)
            return hashlib.sha256(stream.getvalue()).hexdigest()[:16]
    except Exception:
        return "<err>"
    return "<nonshape>"


def _trace(op_name: str, mode: str, key, result) -> None:
    path = os.environ.get("CADGEN_OP_MEMO_TRACE")
    if not path:
        return
    key_digest = hashlib.sha256(repr(key).encode()).hexdigest()[:12] if key else "-"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{op_name}\t{mode}\t{key_digest}\t{_result_digest(result)}\n")


def _memoized(op_name: str, fn, *, is_classmethod: bool):
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _enabled():
            result = fn(*args, **kwargs)
            if os.environ.get("CADGEN_OP_MEMO_TRACE"):
                try:
                    key_args = ((args[0].__name__,) + args[1:]) if is_classmethod else args
                    key = _build_key(op_name, key_args, kwargs)
                except Exception:
                    key = None
                _trace(op_name, "off", key, result)
            return result
        try:
            # For classmethods, `cls` identifies the constructed type and must
            # be part of the key but not hashed as a shape.
            key_args = ((args[0].__name__,) + args[1:]) if is_classmethod else args
            key = _build_key(op_name, key_args, kwargs)
        except _Unkeyable:
            _stats["unkeyable"] += 1
            return fn(*args, **kwargs)
        except Exception:
            _stats["errors"] += 1
            return fn(*args, **kwargs)

        cached = _lookup(key)
        if cached is not None:
            _stats["hits"] += 1
            clone = _thaw_result(cached)
            _trace(op_name, "hit", key, clone)
            return clone

        result = fn(*args, **kwargs)
        _stats["misses"] += 1
        try:
            stored = _freeze_result(result)
        except _Unkeyable:
            _stats["unstorable"] += 1
            _trace(op_name, "miss", key, result)
            return result
        except Exception:
            _stats["errors"] += 1
            _trace(op_name, "miss", key, result)
            return result
        _store(key, stored)
        # The caller gets the same canonical reconstruction a future hit
        # would: package output must not depend on cache state.
        canonical = _thaw_result(stored)
        _trace(op_name, "miss", key, canonical)
        return canonical

    wrapper.__op_memo__ = True
    return wrapper


# (class, attribute, op label). Instance methods and classmethods listed
# separately because classmethod rebinding differs.
_INSTANCE_TARGETS = (
    ("Shape", "_bool_op", "bool_op"),
    ("Mixin3D", "fillet", "fillet"),
    ("Mixin3D", "chamfer", "chamfer"),
    ("Mixin3D", "shell", "shell"),
    ("Mixin3D", "offset_3d", "offset_3d"),
    ("Mixin3D", "hollow", "hollow"),
)
_CLASSMETHOD_TARGETS = (
    ("Face", "make_surface", "face.make_surface"),
    ("Face", "make_surface_from_curves", "face.make_surface_from_curves"),
    ("Face", "make_surface_from_array_of_points", "face.make_surface_from_points"),
    ("Face", "make_bezier_surface", "face.make_bezier_surface"),
    ("Face", "revolve", "face.revolve"),
    ("Face", "sweep", "face.sweep"),
    ("Solid", "make_loft", "solid.make_loft"),
    ("Solid", "extrude", "solid.extrude"),
    ("Solid", "revolve", "solid.revolve"),
    ("Solid", "sweep", "solid.sweep"),
    ("Solid", "sweep_multi", "solid.sweep_multi"),
    ("Solid", "extrude_taper", "solid.extrude_taper"),
    ("Solid", "extrude_linear_with_rotation", "solid.extrude_rot"),
    ("Solid", "thicken", "solid.thicken"),
    ("Wire", "make_convex_hull", "wire.make_convex_hull"),
    ("Wire", "offset_2d", "wire.offset_2d"),
    ("Wire", "fillet_2d", "wire.fillet_2d"),
    ("Wire", "chamfer_2d", "wire.chamfer_2d"),
)


def install() -> bool:
    """Idempotently patch the build123d choke points. Returns installed-now."""
    global _installed
    with _lock:
        # Install even when CADGEN_OP_MEMO=0: the wrapper passes through when
        # disabled, and installing unconditionally keeps in-process toggling
        # (tests, validation runs) honest.
        if _installed:
            return False
        import inspect

        from build123d import topology

        for cls_name, attr, label in _INSTANCE_TARGETS:
            cls = getattr(topology, cls_name, None)
            fn = None if cls is None else inspect.getattr_static(cls, attr, None)
            if fn is None or getattr(fn, "__op_memo__", False):
                continue
            setattr(cls, attr, _memoized(label, fn, is_classmethod=False))

        for cls_name, attr, label in _CLASSMETHOD_TARGETS:
            cls = getattr(topology, cls_name, None)
            static = None if cls is None else inspect.getattr_static(cls, attr, None)
            if static is None or not isinstance(static, classmethod):
                continue
            fn = static.__func__
            if getattr(fn, "__op_memo__", False):
                continue
            setattr(cls, attr, classmethod(_memoized(label, fn, is_classmethod=True)))

        _installed = True
        if os.environ.get("CADGEN_OP_MEMO_STATS") == "1":
            atexit.register(_log_stats)
        return True


def stats() -> dict:
    with _lock:
        return dict(_stats, entries=len(_cache))


def clear() -> None:
    with _lock:
        _cache.clear()
        _tshape_bytes_memo.clear()


def _log_stats() -> None:
    print(f"[op_memo] {stats()}", file=sys.stderr)
