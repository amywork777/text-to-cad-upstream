"""Guarded source reads and atomic numeric edits for the viewer feature tree."""

from __future__ import annotations

import ast
import hashlib
import os
import stat
import tempfile

from .source_features import parse_source_features


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def read_source_model(source_path: str) -> dict:
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    parsed = parse_source_features(source)
    return {
        "ok": parsed.get("ok") is True,
        "supported": True,
        "sourcePath": source_path,
        "source": source,
        "sourceHash": source_hash(source),
        "buildPartVar": parsed.get("buildPartVar"),
        "features": parsed.get("features", []),
        **({"error": parsed.get("error")} if parsed.get("error") else {}),
    }


def _validated_edits(source: str, edits) -> list[tuple[int, int, str]]:
    normalized = []
    for edit in edits if isinstance(edits, list) else []:
        if not isinstance(edit, dict):
            raise ValueError("Every source edit must be an object")
        start = edit.get("start")
        end = edit.get("end")
        replacement = str(edit.get("replacement", ""))
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(source):
            raise ValueError("Source edit span is invalid")
        expected = edit.get("expected")
        if expected is not None and source[start:end] != str(expected):
            raise ValueError("Source edit no longer matches the file on disk")
        normalized.append((start, end, replacement))
    normalized.sort(key=lambda item: item[0])
    for previous, current in zip(normalized, normalized[1:]):
        if previous[1] > current[0]:
            raise ValueError("Source edits overlap")
    return normalized


def _atomic_write(source_path: str, source: str) -> None:
    directory = os.path.dirname(source_path)
    mode = stat.S_IMODE(os.stat(source_path).st_mode)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(source_path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, source_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_source_model(source_path: str, payload: dict) -> dict:
    with open(source_path, encoding="utf-8") as handle:
        original = handle.read()
    expected_hash = str((payload or {}).get("expectedHash") or "")
    actual_hash = source_hash(original)
    if not expected_hash or expected_hash != actual_hash:
        raise ValueError("Source changed on disk; reload the feature tree before applying edits")

    if "source" in (payload or {}):
        updated = str(payload.get("source") or "")
    else:
        normalized = _validated_edits(original, payload.get("edits"))
        if not normalized:
            raise ValueError("No source edits were provided")
        updated = original
        for start, end, replacement in reversed(normalized):
            updated = updated[:start] + replacement + updated[end:]

    try:
        ast.parse(updated)
    except SyntaxError as exc:
        raise ValueError(f"Edited source is invalid: {exc.msg} (line {exc.lineno})") from exc
    parsed = parse_source_features(updated)
    if not parsed.get("ok"):
        raise ValueError(str(parsed.get("error") or "Edited source could not be parsed"))
    _atomic_write(source_path, updated)
    return read_source_model(source_path)
