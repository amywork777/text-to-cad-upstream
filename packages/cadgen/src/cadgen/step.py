"""The public ``step`` format namespace: the ``@step`` decorator and its verbs.

``@step`` DECLARES a model; ``step.build(...)`` OPERATES on one. They are the
same object — this module is callable (see
:mod:`cadgen._internal.format_namespace`) — so a format is one table row:
decorator, verbs, and generated CLI together (design/format-doors.md).

``cadgen step build`` is this module's ``build`` with a parser derived from its
signature, so the flags cannot drift from the function.

Import discipline: nothing here may pull in OCP/build123d at module scope. A
model script pays this import before its freshness gate runs, and the whole
point of the ~0.2s pre-gate budget is that a current model never wakes the CAD
kernel. Every heavy import lives inside a verb body.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cadgen._internal.format_namespace import callable_namespace
from cadgen._internal.snapshot_door import step_snapshot_verb
from cadgen.results import BuildResult, InspectResult

__all__ = ["build", "inspect", "snapshot"]

#: ``cadgen step snapshot``'s verb: render a STEP/STP document, or the model
#: script that builds one. Mesh inputs belong to their own doors
#: (``cadgen.stl.snapshot`` and friends).
snapshot = step_snapshot_verb("step")


def build(
    target: Path,
    *,
    force: bool = False,
    verbose: bool = False,
    lock_timeout: float = 0.0,
) -> BuildResult:
    """Make TARGET's derived state current; no-op when it already is.

    A model script runs its closure gate, runs the generator if stale, builds
    the store package, assembles and writes the .step document, and produces
    the model's declared @stl/@glb/@threemf exports. A foreign STEP/STP runs a
    content-hash gate and extracts a store package when one is absent; the
    document itself is never modified. Idempotent, so repeating it is free.

    target: model script (.py) or STEP/STP document to build.
    force: rebuild even when the freshness gate says the model is current.
    verbose: show detailed progress and timing on stderr.
    lock_timeout: give up after SECONDS when another run holds this model's
        generation lock, answering contended instead of building. 0 (the
        default) waits for the peer.
    """
    from cadgen.catalog import source_from_path
    from cadgen.step_artifact_cli import build_step_artifact

    path = Path(target).expanduser().resolve()
    suffix = path.suffix.lower()
    if suffix == ".py":
        if not path.is_file():
            raise FileNotFoundError(f"model script does not exist: {target}")
        source = source_from_path(path)
        if source is None:
            raise ValueError(
                f"{path.name} declares no CAD model — decorate one function with "
                "@step from cadgen"
            )
        if source.step_path is None:
            raise ValueError(
                f"{path.name} declares no @step model; `cadgen step build` builds "
                "STEP documents (a @dxf drawing builds with `cadgen dxf build`)"
            )
        step_path: Path = source.step_path
        source_path: Path | None = path
    elif suffix in {".step", ".stp"}:
        if not path.is_file():
            raise FileNotFoundError(f"STEP file does not exist: {target}")
        step_path, source_path = path, None
    else:
        raise ValueError(
            f"build target must be a model script (.py) or a STEP/STP document: {target}"
        )

    payload = build_step_artifact(
        repo_root=Path.cwd(),
        step=step_path,
        source_path=source_path,
        force=force,
        verbose=verbose,
        lock_timeout_s=lock_timeout,
    )
    return _build_result(payload)


INSPECTIONS = ("refs", "diff", "frame", "measure", "align", "interfere", "validate")


def inspect(
    target: Path,
    refs: "Sequence[str] | None" = None,
    *,
    inspection: str = "refs",
    against: Path | None = None,
    moving: str = "",
    onto: str = "",
    align_mode: str = "flush",
    offset: float = 0.0,
    axis: str = "",
    detail: bool = False,
    facts: bool = False,
    positioning: bool = False,
    planes: bool = False,
    topology: bool = False,
    plane_coordinate_tolerance: float = 1e-3,
    plane_min_area_ratio: float = 0.05,
    plane_limit: int = 12,
    tolerance: float | None = None,
    max_pairs: int | None = None,
    allow_open: bool = False,
    skip_self_intersection: bool = False,
) -> InspectResult:
    """Answer one geometry question about TARGET, without changing it.

    The parameters are a union across the inspections because the CLI's
    subcommands are: `cadgen step inspect <inspection>` is this function with
    the arguments that inspection reads, and the ones it does not read are
    ignored. Every inspection resolves refs the same way and builds the same
    package, so they are one verb with a mode rather than seven verbs.

    target: STEP/STP document, model script, or CAD entry target.
    refs: selector refs such as `#o1.2` or `#f9`. refs/interfere/validate read
        the whole list; measure reads the first two as from/to; frame reads the
        first as the occurrence to report.
    inspection: refs (default), diff, frame, measure, align, interfere, or
        validate.
    against: the right-hand document, for `diff`.
    moving: the selector being placed, for `align`.
    onto: the selector it is placed against, for `align`.
    align_mode: flush, center, or contact — how `align` relates the two.
    offset: extra distance along the axis, for `align`.
    axis: x, y or z. Inferred from the selectors when omitted.
    detail: include full geometry facts for each resolved face/edge ref.
    facts: include compact geometry facts for whole entries and selectors.
    positioning: include placement-ready frame, point, plane and axis facts.
    planes: include grouped major planar faces.
    topology: include full face/edge selector lists. Expensive on large models.
    plane_coordinate_tolerance: merge planar groups within this coordinate
        distance.
    plane_min_area_ratio: drop planar groups below this fraction of total
        planar area.
    plane_limit: maximum number of plane groups to report.
    tolerance: minimum overlap volume in mm3 that counts, for `interfere`.
    max_pairs: stop after this many interfering pairs, for `interfere`.
    allow_open: treat surface/shell geometry as intended, for `validate`.
    skip_self_intersection: skip the boolean self-intersection test, which
        dominates runtime on large assemblies, for `validate`.
    """
    # Every heavy import stays in the body: this module is on a model script's
    # pre-gate path (see the module docstring).
    from cadgen.cli.step_inspect import inspect as inspection_api

    if inspection not in INSPECTIONS:
        raise ValueError(
            f"unknown inspection {inspection!r}; expected one of: {', '.join(INSPECTIONS)}"
        )
    entry = str(target)
    selectors = [str(ref) for ref in (refs or [])]
    plane_options = {
        "planes": planes,
        "plane_coordinate_tolerance": float(plane_coordinate_tolerance),
        "plane_min_area_ratio": float(plane_min_area_ratio),
        "plane_limit": int(plane_limit),
    }
    try:
        if inspection == "refs":
            report = inspection_api.inspect_cad_refs(
                entry,
                # One ref per line is the shape the token parser is fed
                # everywhere else, including `--input-file`.
                "\n".join(selectors),
                detail=detail,
                include_topology=topology,
                facts=facts,
                positioning=positioning,
                **plane_options,
            )
        elif inspection == "diff":
            if against is None:
                raise ValueError("diff needs a second document: pass against=")
            report = inspection_api.diff_entry_targets(entry, str(against), **plane_options)
        elif inspection == "frame":
            report = inspection_api.inspect_target_frame(entry, selectors[0] if selectors else "")
        elif inspection == "measure":
            if len(selectors) < 2:
                raise ValueError("measure needs two refs: pass refs=[from, to]")
            report = inspection_api.measure_targets(
                entry, selectors[0], selectors[1], axis=axis or None
            )
        elif inspection == "align":
            report = inspection_api.align_targets(
                entry, moving, onto, mode=align_mode, offset=float(offset), axis=axis or None
            )
        elif inspection == "interfere":
            from cadgen import interference

            report = interference.inspect_interference(
                entry,
                refs=selectors,
                tolerance=(
                    interference.DEFAULT_TOLERANCE_MM3 if tolerance is None else tolerance
                ),
                max_pairs=max_pairs,
            )
        else:
            from cadgen import validity

            report = validity.inspect_validity(
                entry,
                refs=selectors,
                allow_open=allow_open,
                check_self_intersection=not skip_self_intersection,
            )
    except inspection_api.CadRefError as exc:
        # A ref that does not resolve is an ANSWER, not a crash: the report says
        # which token failed and why, and the CLI prints it like any other.
        report = {"ok": False, "errors": [inspection_api.cad_ref_error_payload(exc)]}
    return InspectResult(
        ok=bool(report.get("ok")), command=inspection, report=dict(report)
    )


def _build_result(payload: "dict[str, object]") -> BuildResult:
    """The build payload, typed. Paths in the payload are cwd-relative strings."""

    def path_of(key: str) -> Path | None:
        value = payload.get(key)
        return Path(str(value)).resolve() if value else None

    exports = payload.get("exports") or ()
    return BuildResult(
        ok=bool(payload.get("ok", True)),
        document=path_of("stepPath"),
        package=path_of("packagePath"),
        skipped=bool(payload.get("skipped")),
        exports=tuple(Path(str(item)).resolve() for item in exports),  # type: ignore[union-attr]
        contended=bool(payload.get("contended")),
    )


callable_namespace(__name__, "step")
