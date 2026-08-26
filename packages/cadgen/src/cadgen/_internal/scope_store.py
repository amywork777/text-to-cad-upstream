"""Scope value store: freeze/thaw of gen_step-style results + the on-disk
trace entries the cold tier validates (W2, design/production-architecture.md).

A frozen scope value is a JSON structure tree plus content-addressed BREP
blobs for leaf geometry. The tree captures EXACTLY what the two downstream
consumers read from a compound — the packager's walk and STEP export's XCAF
labeling (enumerated from source, see design doc W2):

    class, label, raw color (``_color`` — never the inheriting getter, which
    MUTATES the tree it reads), cad_material, assembly_mates, per-node
    location, anytree children, and ``_occurrence_tree`` (whose leaves hold
    live shapes + Locations and are re-pointed at thawed reconstructions).

Anything else non-JSON-able on a node makes the value Unfreezable: the scope
simply is not cached, and execution falls through (correctness never depends
on a hit).

Store layout (under the shared root, ``CADGEN_STORE_DIR`` override):

    blobs/<sha256>.brep                      content-addressed leaf geometry
    scopes/v<salt>/<scope_key>/<closure_hash>.json   one entry per variant

Lookup lists a scope's variants and validates each against the CURRENT
sources (``closure_hash_matches`` re-hashes the recorded file list); the
first match thaws. Editing back and forth between two source states
therefore alternates between two live variants instead of thrashing one.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

from cadgen._internal.atomic_replace import replace_atomic
from cadgen._internal.source_hash import closure_hash_matches

_SCOPE_STORE_VERSION = 1


class Unfreezable(Exception):
    """This value cannot be represented by the frozen contract."""


# ---------------------------------------------------------------------------
# store roots


def store_root() -> Path:
    root = os.environ.get("CADGEN_STORE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "cadgen")
    return Path(root)


def _blobs_dir() -> Path:
    path = store_root() / "blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scopes_dir() -> Path:
    import build123d

    salt = f"v{_SCOPE_STORE_VERSION}-b123d{getattr(build123d, '__version__', 'unknown')}"
    path = store_root() / "scopes" / salt
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# blobs


def _write_brep(wrapped) -> bytes:
    from OCP.BinTools import BinTools, BinTools_FormatVersion

    stream = io.BytesIO()
    BinTools.Write_s(
        wrapped, stream,
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
        raise Unfreezable("BREP blob read back null")
    return shape


def put_blob(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    path = _blobs_dir() / f"{digest}.brep"
    if not path.exists():
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        replace_atomic(tmp, path)
    return digest


def get_blob(digest: str) -> bytes:
    return (_blobs_dir() / f"{digest}.brep").read_bytes()


# ---------------------------------------------------------------------------
# freeze


_JSON_SCALARS = (str, int, float, bool, type(None))


def _freeze_color(node) -> list[float] | None:
    raw = getattr(node, "_color", None)
    if raw is None:
        return None
    try:
        return [float(v) for v in tuple(raw)]
    except (TypeError, ValueError) as exc:
        raise Unfreezable(f"color not tuple-like: {raw!r}") from exc


def _freeze_location_of(wrapped) -> list[float] | None:
    trsf = wrapped.Location().Transformation()
    values = [trsf.Value(r, c) for r in (1, 2, 3) for c in (1, 2, 3, 4)]
    identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    return None if values == identity else values


def _thaw_location(values: list[float]):
    from build123d import Location
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetValues(*values)
    return Location(TopLoc_Location(trsf))


def _json_safe(value, *, what: str):
    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, what=what) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v, what=what) for k, v in value.items()}
    raise Unfreezable(f"non-JSON {what}: {type(value).__name__}")


def _freeze_occurrence_tree(tree: dict) -> dict:
    node: dict = {
        "id": tree.get("id"),
        "name": tree.get("name"),
        "leaf": bool(tree.get("leaf")),
    }
    if tree.get("leaf"):
        shape = tree["shape"]
        node["blob"] = put_blob(_write_brep(shape.wrapped))
        node["class"] = type(shape).__name__
        node["label"] = getattr(shape, "label", "") or ""
        node["color"] = _freeze_color(shape)
        world = tree.get("world_loc")
        trsf = world.wrapped.Transformation()
        node["world"] = [trsf.Value(r, c) for r in (1, 2, 3) for c in (1, 2, 3, 4)]
    node["children"] = [_freeze_occurrence_tree(c) for c in tree.get("children") or []]
    return node


def freeze_value(value) -> dict:
    """Freeze a gen_step-style result: Shape/Compound, a dict envelope with a
    ``shape`` key, or a JSON scalar structure."""
    if isinstance(value, _JSON_SCALARS):
        return {"kind": "literal", "value": value}
    if isinstance(value, dict):
        if "shape" in value:
            rest = {k: _json_safe(v, what=f"envelope[{k}]")
                    for k, v in value.items() if k != "shape"}
            return {"kind": "envelope", "shape": freeze_value(value["shape"]),
                    "rest": rest}
        return {"kind": "literal", "value": _json_safe(value, what="dict")}
    if isinstance(value, (list, tuple)):
        if all(isinstance(v, _JSON_SCALARS) for v in value):
            return {"kind": "literal", "value": list(value)}
        return {"kind": "seq", "tuple": isinstance(value, tuple),
                "items": [freeze_value(v) for v in value]}

    wrapped = getattr(value, "wrapped", None)
    if wrapped is None or not hasattr(wrapped, "TShape"):
        raise Unfreezable(f"unsupported value type: {type(value).__name__}")

    node: dict = {
        "kind": "shape",
        "class": type(value).__name__,
        "label": getattr(value, "label", "") or "",
        "color": _freeze_color(value),
    }
    material = getattr(value, "cad_material", None)
    if material is not None:
        node["cadMaterial"] = _json_safe(material, what="cad_material")
    mates = getattr(value, "assembly_mates", None)
    if mates is not None:
        node["assemblyMates"] = _json_safe(mates, what="assembly_mates")

    children = list(getattr(value, "children", []) or [])
    occurrence_tree = getattr(value, "_occurrence_tree", None)
    if children:
        node["children"] = [freeze_value(child) for child in children]
        node["location"] = _freeze_location_of(wrapped)
    else:
        node["blob"] = put_blob(_write_brep(wrapped))
    if occurrence_tree is not None:
        node["occurrenceTree"] = _freeze_occurrence_tree(occurrence_tree)
    return node


# ---------------------------------------------------------------------------
# thaw


def _shape_class(name: str):
    import build123d

    cls = getattr(build123d, name, None)
    if cls is None or (cls.__module__ or "").partition(".")[0] != "build123d":
        raise Unfreezable(f"unknown shape class {name!r}")
    return cls


def _wrap_topo(class_name: str, topo):
    from build123d.topology import downcast

    return _shape_class(class_name)(downcast(topo))


def _thaw_occurrence_tree(node: dict) -> dict:
    tree: dict = {
        "id": node.get("id"),
        "name": node.get("name"),
        "leaf": bool(node.get("leaf")),
        "children": [_thaw_occurrence_tree(c) for c in node.get("children") or []],
    }
    if tree["leaf"]:
        shape = _wrap_topo(node["class"], _read_brep(get_blob(node["blob"])))
        shape.label = node.get("label") or ""
        if node.get("color") is not None:
            from build123d import Color

            shape.color = Color(*node["color"])
        tree["shape"] = shape
        tree["world_loc"] = _thaw_location(node["world"])
    return tree


def thaw_value(node: dict):
    kind = node.get("kind")
    if kind == "literal":
        return node.get("value")
    if kind == "envelope":
        result = dict(node.get("rest") or {})
        result["shape"] = thaw_value(node["shape"])
        return result
    if kind == "seq":
        items = [thaw_value(item) for item in node.get("items") or []]
        return tuple(items) if node.get("tuple") else items
    if kind != "shape":
        raise Unfreezable(f"unknown frozen kind {kind!r}")

    children_nodes = node.get("children")
    if children_nodes:
        from build123d import Compound

        cls = _shape_class(node["class"])
        if not (isinstance(cls, type) and issubclass(cls, Compound)):
            raise Unfreezable(f"non-Compound parent class {node['class']!r}")
        children = [thaw_value(child) for child in children_nodes]
        # Children carry their own locations already; construction reads each
        # child's wrapped as-is. The parent's OWN location is applied after.
        shape = cls(children=children, label=node.get("label") or "")
        if node.get("location") is not None:
            shape.location = _thaw_location(node["location"])
    else:
        shape = _wrap_topo(node["class"], _read_brep(get_blob(node["blob"])))
        shape.label = node.get("label") or ""

    if node.get("color") is not None:
        from build123d import Color

        shape._color = Color(*node["color"])
    else:
        shape._color = None
    if node.get("cadMaterial") is not None:
        shape.cad_material = node["cadMaterial"]
    if node.get("assemblyMates") is not None:
        shape.assembly_mates = node["assemblyMates"]
    if node.get("occurrenceTree") is not None:
        shape._occurrence_tree = _thaw_occurrence_tree(node["occurrenceTree"])
    return shape


# ---------------------------------------------------------------------------
# scope entries (the cold tier's trace records)


def scope_key(scope_id: str, args_key: object) -> str:
    return hashlib.sha256(repr((scope_id, args_key)).encode("utf-8")).hexdigest()


def save_scope_entry(
    key: str,
    *,
    closure_hash: str,
    files: tuple[str, ...],
    frozen_value: dict,
    scope_id: str,
) -> None:
    entry_dir = _scopes_dir() / key
    entry_dir.mkdir(parents=True, exist_ok=True)
    variant = hashlib.sha256(closure_hash.encode("utf-8")).hexdigest()[:24]
    path = entry_dir / f"{variant}.json"
    payload = {
        "version": _SCOPE_STORE_VERSION,
        "scopeId": scope_id,
        "closureHash": closure_hash,
        "files": list(files),
        "value": frozen_value,
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    replace_atomic(tmp, path)


def load_valid_scope_entry(key: str, *, base: Path) -> dict | None:
    """The first stored variant whose recorded closure still matches the
    CURRENT sources, or None. Validation cost is the semantic re-hash of the
    recorded file list (stat-cached)."""
    entry_dir = _scopes_dir() / key
    if not entry_dir.is_dir():
        return None
    for path in sorted(entry_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("version") != _SCOPE_STORE_VERSION:
            continue
        if closure_hash_matches(
            payload.get("closureHash"), payload.get("files") or [], base=base
        ):
            return payload
    return None
