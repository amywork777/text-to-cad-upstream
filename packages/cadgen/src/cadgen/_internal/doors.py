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

The doors that DO rebuild -- the in-memory scene doors (``inspect validate``,
``inspect interfere``) and the Viewer's export ABI, which need the generator's
scene rather than a render package -- announce it through
:func:`announce_rebuild` the moment they decide to, on stderr, with the
freshness authority's own reason. That one line is what separates "this door
runs Python when the document is stale" from a fifteen-minute silence a user
cannot attribute to anything.

Stdlib-light: these run before any CAD import, on the ``--help`` path and on a
model script's pre-gate path.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ScriptTargetError",
    "StaleDocumentError",
    "announce_rebuild",
    "document_staleness",
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
    from cadgen._internal.source_sidecar import read_source_provenance

    sidecar = read_source_provenance(document) or {}
    if str(sidecar.get("sourceKind") or "").strip().lower() != "python":
        return None
    recorded = str(sidecar.get("sourcePath") or "").strip()
    if not recorded:
        return None
    candidate = (Path(document).parent / recorded).resolve()
    return candidate if candidate.is_file() else None


def document_staleness(document: Path) -> str | None:
    """Why ``document`` is stale relative to its source, or ``None`` when it is not.

    THE freshness authority for a document at a door: the no-op gate
    (:func:`require_current_document`) and the rebuilding doors' notice
    (:func:`announce_rebuild`) both read it, so they cannot disagree about
    what stale means or why.

    The verdict is the SIDECAR's recorded closure -- the generator's Python
    import reach -- re-hashed exactly as the build's own no-op gate does. An
    imported document (no sidecar) and a ``cadgen step build`` document
    (``sourceKind: "step"``) have no Python source and are never stale here;
    nor is a generated document whose record carries no closure to check
    against (not a licence to rebuild, and not evidence of staleness either).

    The REASON names what the authority can actually see. The record holds one
    aggregate digest, not per-file digests, so a changed closure is attributed
    by modification time: the closure files written after the document was.
    When none is newer (a file touched back, a clock skew) the reason says the
    digest differs and how many files it covers -- true, if less pointed.
    """
    from cadgen._internal.source_hash import closure_hash_matches
    from cadgen._internal.source_sidecar import read_source_provenance

    document = Path(document)
    script = document_source_script(document)
    if script is None:
        return None
    if not document.is_file():
        return "no document on disk"
    sidecar = read_source_provenance(document) or {}
    recorded_hash = str(sidecar.get("sourceClosureHash") or "").strip()
    recorded_files = sidecar.get("sourceClosureFiles")
    if not recorded_hash or not isinstance(recorded_files, list) or not recorded_files:
        return None
    if closure_hash_matches(recorded_hash, recorded_files, base=script.parent):
        return None
    return _closure_change_reason(document, recorded_files, base=script.parent)


def _closure_change_reason(document: Path, recorded_files: list, *, base: Path) -> str:
    try:
        document_mtime = document.stat().st_mtime
    except OSError:
        document_mtime = None
    missing: list[str] = []
    newer: list[str] = []
    for relative in recorded_files:
        rel = str(relative or "").strip()
        if not rel:
            continue
        candidate = Path(rel)
        resolved = candidate if candidate.is_absolute() else base / candidate
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            missing.append(rel)
            continue
        if document_mtime is not None and mtime > document_mtime:
            newer.append(rel)
    if missing:
        return f"closure file missing: {_listed(missing)}"
    if newer:
        return f"{_listed(newer)} changed after the document was written"
    return (
        f"the source closure hash differs from the recorded one "
        f"({len(recorded_files)} file(s) re-hashed)"
    )


def _listed(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    rest = len(names) - limit
    return f"{shown} and {rest} more" if rest > 0 else shown


def require_current_document(document: Path) -> None:
    """Refuse to operate on a document that is stale relative to its source.

    The gate is :func:`document_staleness`; this turns its reason into the
    teaching error every no-op door raises.
    """
    document = Path(document)
    reason = document_staleness(document)
    if reason is None:
        return
    script = document_source_script(document)
    raise StaleDocumentError(
        f"{_display(document)} is stale relative to its source ({reason}) — "
        f"run python {_display(script) if script is not None else '<script>'}"
    )


def announce_rebuild(
    door: str, document: Path | str, *, reason: str, source: Path | str, verb: str
) -> None:
    """The ONE line a rebuilding door prints, on stderr, when it decides to rebuild.

    ``<door>: <document> is stale (<reason>); rebuilding from <source> before <verb>``

    Printed at the decision, before the generator runs, so the wait that follows
    is attributed. Every door that can rebuild routes here; there is no second
    wording. Written to the CURRENT ``sys.stderr`` so a warm worker's redirect
    carries it to the client like the rest of the narration.
    """
    import sys

    print(
        f"{door}: {_display(Path(document))} is stale ({reason}); "
        f"rebuilding from {_display(Path(source))} before {verb}",
        file=sys.stderr,
        flush=True,
    )
