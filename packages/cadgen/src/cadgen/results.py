"""What the public verb functions return: the JSON line protocol, typed.

Every ``build`` / ``validate`` verb answers with one of these frozen
dataclasses rather than a loose dict, so the library call and the generated CLI
carry the SAME shape — ``--json`` is just ``dataclasses.asdict`` of the value
the library already returned (design/format-doors.md).

Stdlib only, on purpose: importing a result type must never pull in the CAD
kernel, because the public namespaces (``cadgen.step``, ``cadgen.stl``, ...)
import this at module scope and must stay inside the ~0.2s pre-gate budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "BuildResult",
    "MeshExportFile",
    "MeshExportResult",
    "ValidationIssue",
    "ValidationResult",
]


def _display(path: Path | None) -> str:
    """Cwd-relative where that is meaningful, else absolute. Messages only."""
    if path is None:
        return "-"
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except (OSError, ValueError):
        return str(path)


@dataclass(frozen=True)
class BuildResult:
    """The outcome of making one document's derived state current."""

    ok: bool
    #: The ``.step``/``.dxf`` document — this build's OUTPUT for a model script,
    #: its INPUT for a foreign document. ``None`` when the run claimed none.
    document: Path | None
    #: The store package directory holding the built geometry.
    package: Path | None
    #: True when the freshness gate said the derived state was already current.
    skipped: bool
    #: Declared artifacts produced (or healed) by THIS run. Outputs the ledger
    #: already found current are not listed: the field answers "what did this
    #: run write", not "what does the model declare".
    exports: tuple[Path, ...] = ()
    #: A peer process held this model's lock and the caller asked not to wait.
    #: Nothing went wrong (``ok`` stays true) and nothing was built here.
    contended: bool = False

    def human_lines(self) -> list[str]:
        if self.contended:
            return [f"contended {_display(self.package)} (another run is building it)"]
        head = "current" if self.skipped else "built"
        lines = [f"{head} {_display(self.document or self.package)}"]
        lines += [f"wrote {path.suffix.lstrip('.').upper()}: {_display(path)}" for path in self.exports]
        return lines


@dataclass(frozen=True)
class MeshExportFile:
    """One mesh output of a format door, and the tolerances it was written at."""

    path: Path
    fmt: str
    #: True when the mesh-export ledger already had this document at this
    #: tolerance pair, so nothing was re-tessellated.
    skipped: bool
    #: The EFFECTIVE pair (run-level arg > declaration > @step model policy >
    #: tessellator default, which is ``None``).
    mesh_tolerance: float | None = None
    mesh_angular_tolerance: float | None = None


@dataclass(frozen=True)
class MeshExportResult:
    """The outcome of one format door's ``build``."""

    ok: bool
    files: tuple[MeshExportFile, ...] = ()

    def human_lines(self) -> list[str]:
        return [
            f"{'current' if entry.skipped else 'wrote'} {entry.fmt.upper()}: {_display(entry.path)}"
            for entry in self.files
        ]


@dataclass(frozen=True)
class ValidationIssue:
    """One conformance finding against a robot description."""

    severity: str  # "error" | "warning"
    message: str
    #: The offending element or reference, when the checker knows it.
    element: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of one ``validate`` verb."""

    ok: bool
    path: Path
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def human_lines(self) -> list[str]:
        lines = [
            f"{issue.severity}: {issue.message}"
            + (f" [{issue.element}]" if issue.element else "")
            for issue in self.issues
        ]
        lines.append(f"{'OK' if self.ok else 'FAILED'} {_display(self.path)}")
        return lines
