"""What ``stl.build`` / ``threemf.build`` / ``glb.build`` all are.

The three public mesh doors differ only in a format string, so their bodies
live here and the namespaces keep exactly the thin, fully-annotated signature
their CLIs are generated from. Anything richer in those modules would be a
second implementation to drift.

The engine is unchanged: :func:`cadgen.step_export_target.export_cad_target`
is the one entry, so a door and a model-script run cannot produce different
bytes (design/format-doors.md).
"""

from __future__ import annotations

from pathlib import Path

from cadgen.results import MeshExportFile, MeshExportResult


def mesh_build(
    fmt: str,
    target: Path,
    out: Path | None,
    *,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
    force: bool,
    verbose: bool,
) -> MeshExportResult:
    """One format door's ``build``, typed.

    ``out`` None means the model's DECLARATIONS — every declared variant of
    this format, or the sibling default when it declares none. An explicit
    ``out`` is one ad-hoc export at that path. Either way the shared ledger
    gates the write.
    """
    from cadgen.cli_logging import CliLogger
    from cadgen.step_export_target import export_cad_target

    payload = export_cad_target(
        Path(target).expanduser(),
        [(fmt, None if out is None else Path(out).expanduser())],
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
        force=force,
        verbose=verbose,
        logger=CliLogger(f"cadgen {fmt} build", verbose=verbose),
    )
    files = tuple(
        MeshExportFile(
            path=Path(str(entry["path"])),
            fmt=str(entry["format"]),
            skipped=bool(entry.get("skipped")),
            mesh_tolerance=entry.get("meshTolerance"),  # type: ignore[arg-type]
            mesh_angular_tolerance=entry.get("meshAngularTolerance"),  # type: ignore[arg-type]
        )
        for entry in payload["files"]  # type: ignore[union-attr]
    )
    return MeshExportResult(ok=bool(payload.get("ok", True)), files=files)
