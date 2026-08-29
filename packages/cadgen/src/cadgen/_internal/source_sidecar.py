"""The source sidecar: everything SOURCE-derived a render package carries.

The descriptor (``assembly.json``) is a pure function of the STEP file's bytes
plus schema/extractor versions — the cache engine's world. Everything derived
from the Python source instead lives here, in ``<package>/source.json``:
generation provenance (source path/hash, the runtime closure the no-op gate
re-validates), the declarative pose block from ``@step(pose=...)``, assembly
mates (authored in Python, not representable in STEP), and the build
timestamp. Imports write NO sidecar — **the sidecar's existence is the
"generated" marker**, replacing the descriptor's old ``sourceKind`` field on
both freshness authorities (Python gates here, JS in
``viewer/server/artifactStatus.mjs``).

Write ordering matters: the sidecar is written BEFORE the descriptor, because
the descriptor's presence is the package's completeness signal (the same
rule component ``.surf`` files follow). Both writes happen under the package
write lock; readers are lock-blind and tolerate a missing sidecar (a package
without one simply classifies as imported).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from cadgen._internal.atomic_replace import replace_atomic, temp_suffix

SOURCE_SIDECAR_NAME = "source.json"
SOURCE_SIDECAR_SCHEMA_VERSION = 1


def source_sidecar_path(package_dir: Path | str) -> Path:
    return Path(package_dir) / SOURCE_SIDECAR_NAME


def package_is_generated(package_dir: Path | str) -> bool:
    """Whether this package was produced by a model script (vs an import)."""
    return source_sidecar_path(package_dir).is_file()


def read_source_sidecar(package_dir: Path | str) -> dict[str, Any] | None:
    try:
        payload = json.loads(source_sidecar_path(package_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_source_sidecar(package_dir: Path | str, payload: Mapping[str, Any]) -> None:
    package = Path(package_dir)
    package.mkdir(parents=True, exist_ok=True)
    target = source_sidecar_path(package)
    body = dict(payload)
    body.setdefault("schemaVersion", SOURCE_SIDECAR_SCHEMA_VERSION)
    temp = target.with_name(f".{target.name}{temp_suffix()}")
    temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    replace_atomic(temp, target)


def remove_source_sidecar(package_dir: Path | str) -> None:
    """Imports must never leave a stale generated-marker behind (e.g. a forced
    re-import over a package that used to be generated)."""
    source_sidecar_path(package_dir).unlink(missing_ok=True)
