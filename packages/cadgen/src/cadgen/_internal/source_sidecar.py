"""The source sidecar: everything SOURCE-derived a generated model carries.

The render package (in the user-level store, keyed by the document's content
hash) is a pure function of the STEP file's bytes plus schema versions — the
cache engine's world, freely evictable. Everything derived from the Python
source instead lives in ONE sidecar FILE BESIDE THE MODEL,
``<name>.step.cadgen.json``: generation provenance (source path/hash, the
runtime closure the no-op gate re-validates), the KINEMATICS section (typed
mates with axes resolved to world numbers, couplings, pose presets), the
ANIMATION section (the .anim.js choreography text, COPIED — no path back to
the source tree ever appears in a generated file), the MESH EXPORTS section
(what the model's ``@stl``/``@glb``/``@threemf`` declarations resolved to, so
a bare mesh door reads DECLARATIONS from the document instead of importing
the model module), assembly mates (authored in Python, not representable in
STEP), and the build timestamp. It sits beside the model because it cannot be
re-derived from the STEP bytes: evicting the store must never lose kinematics
or provenance. New capability = new SECTION + schema bump, never a second
sidecar file.

Imports write NO sidecar — **the sidecar's existence is the "generated"
marker**, on both freshness authorities (Python gates in
``cadgen._internal.generation``, JS in ``viewer/server/artifactStatus.mjs``).

Write ordering matters: the sidecar is written BEFORE the package lands at
its content key, so a resolvable package never races a missing sidecar.
Readers are lock-blind and tolerate a missing sidecar (a model without one
simply classifies as imported).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cadgen._internal.atomic_replace import replace_atomic, temp_suffix

SOURCE_SIDECAR_SUFFIX = ".cadgen.json"
# 4: the meshExports section (doors read declarations from the document).
SOURCE_SIDECAR_SCHEMA_VERSION = 4


def source_sidecar_path(step_path: Path | str) -> Path:
    """``<name>.step`` -> ``<name>.step.cadgen.json``, beside the model."""
    artifact = Path(step_path)
    return artifact.with_name(artifact.name + SOURCE_SIDECAR_SUFFIX)


def model_is_generated(step_path: Path | str) -> bool:
    """Whether this artifact was produced by a model script (vs an import)."""
    return source_sidecar_path(step_path).is_file()


def read_source_sidecar(step_path: Path | str) -> dict[str, Any] | None:
    try:
        payload = json.loads(source_sidecar_path(step_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_source_sidecar(step_path: Path | str, payload: Mapping[str, Any]) -> None:
    target = source_sidecar_path(step_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body.setdefault("schemaVersion", SOURCE_SIDECAR_SCHEMA_VERSION)
    temp = target.with_name(f".{target.name}{temp_suffix()}")
    temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    replace_atomic(temp, target)


@dataclass(frozen=True)
class SidecarMeshExport:
    """One ``meshExports`` entry, with ``out`` resolved beside the document.

    ``mesh_tolerance``/``mesh_angular_tolerance`` are the EFFECTIVE values the
    script run wrote at (declaration explicit, else the model's policy);
    ``None`` inherits the tessellator default. ``at`` is the bake point's
    ``{dof: value}``, or ``None`` for authored rest.
    """

    fmt: str
    path: Path
    mesh_tolerance: float | None = None
    mesh_angular_tolerance: float | None = None
    at: dict[str, float] | None = None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sidecar_mesh_exports(step_path: Path | str) -> tuple[SidecarMeshExport, ...]:
    """The document's declared mesh exports, from its sidecar.

    The mesh doors' one source of declarations: a document, not a script and
    not the Python registry (design/pose-animation-split.md, CLI/doors
    follow-on). An imported document has no sidecar and therefore no
    declarations — an empty tuple, which the door turns into a teaching error.
    """
    artifact = Path(step_path)
    payload = read_source_sidecar(artifact) or {}
    raw = payload.get("meshExports")
    if not isinstance(raw, list):
        return ()
    resolved: list[SidecarMeshExport] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        fmt = str(entry.get("fmt") or "").strip()
        out = str(entry.get("out") or "").strip()
        if not fmt or not out:
            continue
        at = entry.get("at")
        resolved.append(
            SidecarMeshExport(
                fmt=fmt,
                path=(artifact.parent / out).resolve(),
                mesh_tolerance=_optional_float(entry.get("meshTolerance")),
                mesh_angular_tolerance=_optional_float(entry.get("meshAngularTolerance")),
                at={str(k): float(v) for k, v in at.items()} if isinstance(at, Mapping) and at else None,
            )
        )
    return tuple(resolved)


def remove_source_sidecar(step_path: Path | str) -> None:
    """Imports must never leave a stale generated-marker behind (e.g. a
    re-import over a model that used to be generated)."""
    source_sidecar_path(step_path).unlink(missing_ok=True)
