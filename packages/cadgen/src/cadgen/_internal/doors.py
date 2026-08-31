"""What every CLI door does before it touches a document.

DOCUMENTS-ONLY CLI INPUTS (design/pose-animation-split.md, CLI/doors
follow-on). A model script is a PROGRAM: ``python model.py`` is the one source
door, and running it writes the document, its sidecar and its declared exports.
Every command therefore takes the DOCUMENT — a ``.step``/``.stp``/``.stl``/
``.dxf`` file — and refuses a ``.py`` by naming the run.

Staleness is a NO-OP GATE, never an auto-rebuild: a door handed a document
whose sidecar closure no longer re-hashes says so and names ``python
<sourcePath>``. Silently regenerating from a CLI would put a build inside a
render, which is exactly the coupling the split exists to remove. A document
with no sidecar is IMPORTED and has no staleness concept at all.

Stdlib-light: these run before any CAD import, on the ``--help`` path and on a
model script's pre-gate path.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ScriptTargetError",
    "StaleDocumentError",
    "document_target",
    "require_current_document",
    "script_target_message",
]


class ScriptTargetError(ValueError):
    """A CLI door was handed a model script instead of a document."""


class StaleDocumentError(ValueError):
    """A document's sidecar closure no longer matches its source."""


def _display(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except (OSError, ValueError):
        return str(path)


def script_target_message(script: Path | str) -> str:
    """The one teaching error at every door that used to accept a ``.py``."""
    return (
        f"a model script is a program — run it: python {_display(Path(script))} "
        "(building writes the document, sidecar, and declared exports); "
        "this command takes the document"
    )


def document_target(target: Path | str, *, suffixes: tuple[str, ...]) -> Path:
    """Resolve TARGET as a document, or raise the teaching error.

    ``suffixes`` is the door's own accepted set (``.step``/``.stp`` for STEP,
    ``.stl`` for the STL door, ...). A ``.py`` is refused by naming the run; any
    other suffix is refused by naming what the door takes.
    """
    path = Path(target).expanduser()
    suffix = path.suffix.lower()
    if suffix == ".py":
        raise ScriptTargetError(script_target_message(path))
    if suffix not in suffixes:
        accepted = "/".join(suffixes)
        raise ValueError(f"this command takes a {accepted} document: {target}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"document does not exist: {target}")
    return resolved


def document_source_script(document: Path) -> Path | None:
    """The model script a generated document's sidecar records, or ``None``.

    ``sourcePath`` is stored RELATIVE to the document, so the pair relocates
    together; a document whose recorded script has since moved away resolves to
    ``None`` and is treated as having nothing to be stale against.
    """
    from cadgen._internal.source_sidecar import read_source_sidecar

    sidecar = read_source_sidecar(document) or {}
    if str(sidecar.get("sourceKind") or "").strip().lower() != "python":
        return None
    recorded = str(sidecar.get("sourcePath") or "").strip()
    if not recorded:
        return None
    candidate = (Path(document).parent / recorded).resolve()
    return candidate if candidate.is_file() else None


def require_current_document(document: Path) -> None:
    """Refuse to operate on a document that is stale relative to its source.

    The gate reads the SIDECAR's recorded closure — the generator's Python
    import reach — and re-hashes it exactly as the build's own no-op gate does.
    An imported document (no sidecar) and a ``cadgen step build`` document
    (``sourceKind: "step"``) have no Python source and are never stale here.
    """
    from cadgen._internal.source_hash import closure_hash_matches
    from cadgen._internal.source_sidecar import read_source_sidecar

    document = Path(document)
    script = document_source_script(document)
    if script is None:
        return
    sidecar = read_source_sidecar(document) or {}
    recorded_hash = str(sidecar.get("sourceClosureHash") or "").strip()
    recorded_files = sidecar.get("sourceClosureFiles")
    if not recorded_hash or not isinstance(recorded_files, list) or not recorded_files:
        # Nothing recorded to check against: not a licence to rebuild, and not
        # evidence of staleness either.
        return
    if closure_hash_matches(recorded_hash, recorded_files, base=script.parent):
        return
    raise StaleDocumentError(
        f"{_display(document)} is stale relative to its source — "
        f"run python {_display(script)}"
    )
