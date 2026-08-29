"""The source sidecar: everything SOURCE-derived a generated model carries.

The render package (in the user-level store, keyed by the document's content
hash) is a pure function of the STEP file's bytes plus schema versions — the
cache engine's world, freely evictable. Everything derived from the Python
source instead lives in a sidecar FILE BESIDE THE MODEL,
``<name>.step.source.json``: generation provenance (source path/hash, the
runtime closure the no-op gate re-validates), the declarative pose block from
``@step(pose=...)`` (with the optional escape-hatch module source INLINED),
assembly mates (authored in Python, not representable in STEP), and the build
timestamp. It sits beside the model because it cannot be re-derived from the
STEP bytes: evicting the store must never lose pose or provenance.

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
from pathlib import Path
from typing import Any, Mapping

from cadgen._internal.atomic_replace import replace_atomic, temp_suffix

SOURCE_SIDECAR_SUFFIX = ".source.json"
SOURCE_SIDECAR_SCHEMA_VERSION = 2


def source_sidecar_path(step_path: Path | str) -> Path:
    """``<name>.step`` -> ``<name>.step.source.json``, beside the model."""
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


def remove_source_sidecar(step_path: Path | str) -> None:
    """Imports must never leave a stale generated-marker behind (e.g. a
    re-import over a model that used to be generated)."""
    source_sidecar_path(step_path).unlink(missing_ok=True)
