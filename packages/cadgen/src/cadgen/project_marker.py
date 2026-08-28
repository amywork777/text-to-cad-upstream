"""The optional per-project output-routing marker: ``cadproject.toml``.

cadgen itself is UNOPINIONATED about layout: a decorated model with no
``write=`` writes ``<stem>.step`` beside its script. The ``cad-project`` skill
expresses its opinionated structure (``src/`` + capitalized format folders) by
scaffolding this marker instead of forcing a path into every decorator call::

    # cadproject.toml, at the project root
    [outputs]
    step = "STEP"
    dxf = "DXF"

The schema is deliberately minimal — output routing only. With a marker
present, a model in ``<root>/src/bracket.py`` writes to
``<root>/STEP/bracket.step`` by default; an explicit ``write=`` always wins
(resolved relative to the script's folder, absolute allowed).

stdlib only: this module is imported by the static metadata parser, which must
never pull OCP.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

MARKER_FILENAME = "cadproject.toml"

# How far above the script we look for the marker. Bounded so a stray marker in
# a home directory cannot silently re-route half a filesystem.
_MAX_ASCENT = 8


def find_project_marker(script_path: Path) -> Path | None:
    """The nearest ``cadproject.toml`` at or above the script's folder, if any."""
    folder = script_path.resolve().parent
    for _ in range(_MAX_ASCENT):
        candidate = folder / MARKER_FILENAME
        if candidate.is_file():
            return candidate
        if (folder / ".git").exists():
            return None
        if folder.parent == folder:
            return None
        folder = folder.parent
    return None


def _routing_for(marker_path: Path, fmt: str) -> str | None:
    try:
        with marker_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid {MARKER_FILENAME} at {marker_path}: {exc}") from exc
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return None
    route = outputs.get(fmt)
    if route is None:
        return None
    if not isinstance(route, str) or not route.strip() or "\\" in route or Path(route).is_absolute():
        raise ValueError(
            f"{marker_path}: outputs.{fmt} must be a relative POSIX folder path"
        )
    return route.strip()


def resolve_output_path(
    script_path: Path,
    *,
    fmt: str,
    explicit_write: str | None = None,
    stem: str | None = None,
) -> Path:
    """Where a decorated model's primary artifact goes.

    Precedence: explicit ``write=`` (relative to the script's folder) >
    marker routing (``<marker dir>/<route>/<stem>.<fmt>``) > the flexible
    default (``<stem>.<fmt>`` beside the script).
    """
    script = script_path.resolve()
    resolved_stem = stem or script.stem
    if explicit_write:
        target = Path(explicit_write)
        return (target if target.is_absolute() else script.parent / target).resolve()
    marker = find_project_marker(script)
    if marker is not None:
        route = _routing_for(marker, fmt)
        if route is not None:
            return (marker.parent / route / f"{resolved_stem}.{fmt}").resolve()
    return (script.parent / f"{resolved_stem}.{fmt}").resolve()
