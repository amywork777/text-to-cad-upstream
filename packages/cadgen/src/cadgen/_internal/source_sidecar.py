"""The source sidecar: everything SOURCE-derived a generated model carries.

The render package (in the user-level store, keyed by the document's content
hash) is a pure function of the STEP file's bytes plus schema versions — the
cache engine's world, freely evictable. The model's DECLARATIONS live in ONE
sidecar FILE BESIDE THE MODEL, ``<name>.step.json``: the KINEMATICS section
(typed mates with axes resolved to world numbers, couplings, pose presets),
the ANIMATION section (the .anim.js choreography text, COPIED — no path back
to the source tree ever appears in a generated file), the MESH EXPORTS section
(what the model's ``@stl``/``@glb``/``@threemf`` declarations resolved to, so
a bare mesh door reads DECLARATIONS from the document instead of importing
the model module), and assembly mates (authored in Python, not representable in
STEP). NOTHING source-derived-as-identity — no paths, hashes, closures, or
timestamps: a sidecar ships beside the artifact, and a generated file carries
no tie back to its source. Provenance lives in the RECORDS tier below. The
sidecar sits beside the model because declarations cannot be re-derived from
the STEP bytes: evicting the store must never lose kinematics. New capability
= new SECTION + schema bump, never a second sidecar file.

A sidecar exists ONLY when the model NEEDS one: a kinematics section, an
animation section, or declared mesh exports. A plain model — geometry and
nothing else — writes no sidecar at all; its provenance and freshness ride
the PROVENANCE RECORD in the evictable records tier (bottom of this module),
which every generated build writes and every gate falls back to. Eviction
costs one rebuild, never correctness. Imports write neither. One consequence
is accepted by design: the JS authority (``viewer/server/artifactStatus.mjs``)
reads only the sidecar file, so a plain generated model classifies as
imported in the Viewer.

Write ordering matters: the sidecar is written BEFORE the package lands at
its content key, so a resolvable package never races a missing sidecar.
Readers are lock-blind and tolerate a missing sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cadgen._internal.atomic_replace import replace_atomic, temp_suffix

# APPENDED to the artifact's whole name, so the pair sorts and reads together:
# `part.step` -> `part.step.json`. Never match a sidecar on this suffix alone —
# it is `.json`, which every unrelated JSON file also ends with. Construct the
# path from the artifact (:func:`source_sidecar_path`), or match the artifact
# suffix too (`.step.json` / `.stp.json`).
SOURCE_SIDECAR_SUFFIX = ".json"
# 5: provenance moved OUT of the sidecar (a generated file must carry no tie
#    to its source; the freshness gates read the records tier). 4 added the
#    meshExports section.
SOURCE_SIDECAR_SCHEMA_VERSION = 5

# What a sidecar may CONTAIN: declarations only. Anything source-derived-as-
# provenance (paths, hashes, closures, timestamps) belongs to the provenance
# record; a sidecar sits beside the artifact and ships with it.
_SIDECAR_SECTIONS = ("schemaVersion", "kinematics", "animation", "meshExports")


def source_sidecar_path(step_path: Path | str) -> Path:
    """``<name>.step`` -> ``<name>.step.json``, beside the model."""
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


# The sections that WARRANT a sidecar. Provenance alone does not: it also
# lives in the package descriptor, and a file per plain model is pure clutter.
_WARRANTING_SECTIONS = ("kinematics", "animation", "meshExports")


def sidecar_is_warranted(payload: Mapping[str, Any] | None) -> bool:
    """Whether this payload carries anything the model actually needs a
    sidecar FOR (kinematics, animation, or declared mesh exports)."""
    if not payload:
        return False
    return any(payload.get(section) for section in _WARRANTING_SECTIONS)


def write_source_sidecar(step_path: Path | str, payload: Mapping[str, Any]) -> None:
    """Write the sidecar — or, for a payload that warrants none, remove any
    stale one (a model that DROPPED its kinematics must lose the file).
    Only the FILE: the build's provenance record stays."""
    if not sidecar_is_warranted(payload):
        source_sidecar_path(step_path).unlink(missing_ok=True)
        return
    target = source_sidecar_path(step_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in payload.items() if k in _SIDECAR_SECTIONS}
    body["schemaVersion"] = SOURCE_SIDECAR_SCHEMA_VERSION
    # A rewrite that changes nothing but the timestamp is pure churn — for
    # committed sidecars (imported/ projects) it dirties git on every no-op.
    if read_source_sidecar(step_path) == body:
        return
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
    _provenance_record_path(step_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The provenance RECORD: the freshness gates' path-keyed memory of a build's
# source (kind, path, hash, closure). Every generated build writes one, in the
# evictable records tier — eviction costs one rebuild, never correctness. It
# exists so a PLAIN model (no sidecar warranted) still no-ops on rerun and is
# still refused by the doors when it drifts from its script.

_PROVENANCE_FIELDS = (
    "generatedAt",
    "schemaVersion",
    "sourceKind",
    "sourcePath",
    "sourceHash",
    "sourceClosureFiles",
    "sourceClosureHash",
    "annotationHash",
)


def _provenance_record_path(step_path: Path | str) -> Path:
    from cadgen.catalog import artifact_path_key
    from cadgen._internal.cache_paths import records_dir

    return records_dir() / f"{artifact_path_key(Path(step_path))}.source.json"


def write_source_provenance_record(step_path: Path | str, payload: Mapping[str, Any]) -> None:
    body = {key: payload[key] for key in _PROVENANCE_FIELDS if key in payload}
    body.setdefault("schemaVersion", SOURCE_SIDECAR_SCHEMA_VERSION)
    try:
        existing = json.loads(_provenance_record_path(step_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = None
    if isinstance(existing, dict):
        if {k: v for k, v in existing.items() if k != "generatedAt"} == {
            k: v for k, v in body.items() if k != "generatedAt"
        }:
            return
    target = _provenance_record_path(step_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}{temp_suffix()}")
    temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    replace_atomic(temp, target)


def read_source_provenance(step_path: Path | str) -> dict[str, Any] | None:
    """The document's source provenance, from the records tier — the ONE home
    of source-derived identity now that sidecars carry declarations only.
    Falls back to the sidecar for documents written by older schemas, else
    ``None`` (an import, or an evicted record: one rebuild re-records)."""
    try:
        payload = json.loads(_provenance_record_path(step_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict):
        return payload
    sidecar = read_source_sidecar(step_path)
    if sidecar is not None and sidecar.get("sourceKind"):
        return sidecar
    return None
