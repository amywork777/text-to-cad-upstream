"""The generated-DXF output record: gen-side freshness for `.dxf.py` targets.

A drawing generator's product is the `.dxf` file itself (design/
standalone-viewer.md Phase A) — the viewer parses it directly, so there is no
drawing package any more. What remains under ``__cadgen__/models/<name>.dxf.py/``
is this one small record, which is what makes an unchanged source a no-op:

    dxf-export.json = {
      "kind": "dxf-export-record",
      "sourceClosureHash": ...,   # the SAME content digest gen_step uses
      "sourceClosureFiles": [...],# relative to the model folder
      "dxfPath": ...,             # the output this record verified (rel or abs)
      "dxfHash": ...,             # sha256 of that file's bytes
      "generatedAt": ...
    }

``dxf_output_current`` is BOTH freshness authorities: the CLI's no-op gate and
the retired render-side validator called it, so the two could never
disagree about staleness. Everything here is stdlib-only — the render side
imports this module into a process that must never load ezdxf/OCP.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cadgen._internal.atomic_replace import replace_atomic
from cadgen._internal.source_hash import closure_hash_matches
from cadgen.catalog import render_package_dir

DXF_EXPORT_RECORD_NAME = "dxf-export.json"
DXF_EXPORT_RECORD_KIND = "dxf-export-record"

# Everything the deleted drawing package used to leave behind. Cleared when a
# record is written so a pre-migration checkout converges on the new layout.
_LEGACY_PACKAGE_FILES = ("drawing.json", "geometry.json", "preview.glb")


def dxf_export_record_path(script_path: Path) -> Path:
    return Path(render_package_dir(Path(script_path))) / DXF_EXPORT_RECORD_NAME


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_dxf_path(script_path: Path, output_path: Path) -> str:
    """Store the sibling as a bare name and anything else absolute, so a moved
    model folder keeps verifying its own sibling."""
    resolved = output_path.expanduser().resolve()
    if resolved.parent == Path(script_path).resolve().parent:
        return resolved.name
    return str(resolved)


def _resolve_record_dxf_path(script_path: Path, recorded: str) -> Path:
    value = str(recorded or "")
    if not value:
        return Path()
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(script_path).resolve().parent / value


def record_dxf_output(script_path: Path, output_path: Path, *, source_closure) -> None:
    """Write the freshness record after a successful generate+write, and clear
    any legacy drawing-package payloads left in the record directory."""
    record_dir = dxf_export_record_path(script_path).parent
    record_dir.mkdir(parents=True, exist_ok=True)
    for name in _LEGACY_PACKAGE_FILES:
        try:
            (record_dir / name).unlink()
        except OSError:
            pass
    payload = {
        "kind": DXF_EXPORT_RECORD_KIND,
        "sourceClosureHash": source_closure.closure_hash,
        "sourceClosureFiles": list(source_closure.files),
        "dxfPath": _record_dxf_path(script_path, output_path),
        "dxfHash": _sha256_file(output_path),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target = dxf_export_record_path(script_path)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    replace_atomic(temporary, target)


def read_dxf_export_record(script_path: Path) -> dict | None:
    try:
        payload = json.loads(dxf_export_record_path(script_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != DXF_EXPORT_RECORD_KIND:
        return None
    return payload


def dxf_output_current(script_path: Path, output_path: Path | None = None) -> bool:
    """Whether the recorded output is still the CURRENT product of this source:
    the recorded closure still hashes unchanged AND the recorded file still
    hashes to the recorded digest. ``output_path`` narrows the question to a
    specific requested output (an ``-o`` target); by default the record's own
    output is checked."""
    script_path = Path(script_path)
    record = read_dxf_export_record(script_path)
    if record is None:
        return False
    closure_files = record.get("sourceClosureFiles")
    if not isinstance(closure_files, list) or not closure_files:
        return False
    if not closure_hash_matches(
        record.get("sourceClosureHash"), closure_files, base=script_path.resolve().parent
    ):
        return False
    recorded_output = _resolve_record_dxf_path(script_path, record.get("dxfPath"))
    if output_path is not None:
        requested = Path(output_path).expanduser().resolve()
        if requested != recorded_output:
            return False
    if not recorded_output.is_file():
        return False
    try:
        return _sha256_file(recorded_output) == str(record.get("dxfHash") or "")
    except OSError:
        return False
