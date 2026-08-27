from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from cadgen._internal.cli_locking import add_lock_timeout_argument
from cadgen.catalog import StepImportOptions
from cadgen.metadata import normalize_mesh_numeric




def generate_step_targets(*args, **kwargs):
    from cadgen.generation import generate_step_targets as generate

    return generate(*args, **kwargs)


def report_cli_error(*args, **kwargs):
    from cadgen._internal.cli_errors import report_cli_error as report

    return report(*args, **kwargs)


def _normalize_cli_numeric(value: object, *, field_name: str, parser: argparse.ArgumentParser) -> float | None:
    try:
        return normalize_mesh_numeric(value, field_name=field_name)
    except ValueError as exc:
        parser.error(str(exc))
    return None


def _add_gen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "targets",
        nargs="+",
        help="Explicit gen_step() Python generator source(s) to build.",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help=(
            "Where to write the STEP file (single target only; resolves from the "
            "command cwd). Default: each target's sibling <name>.step. scripts/gen "
            "ALWAYS writes the STEP file — it is the model's output artifact "
            "(assembled from the package's exact-shape blobs, not re-generated)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild render packages even when current artifacts match the source closure.",
    )
    parser.add_argument(
        "--mesh-tolerance",
        type=float,
        help="Positive mesh linear deflection for the render GLB/topology artifacts.",
    )
    parser.add_argument(
        "--mesh-angular-tolerance",
        type=float,
        help="Positive mesh angular deflection for the render GLB/topology artifacts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress and timing information.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print one JSON line per target on stdout reporting what happened to it "
            "(built, current, built by a concurrent run, or left to one) and where its "
            "package is. "
            "Human progress stays on stderr, so the two never interleave."
        ),
    )
    # The same flag, spelled and defaulted the same way, as every other artifact CLI --
    # scripts/gen is the one SKILL.md documents it on, and the one that did not accept it.
    add_lock_timeout_argument(parser)


def _validate_python_targets(targets: Sequence[str], *, parser: argparse.ArgumentParser) -> None:
    for target in targets:
        target_text = str(target)
        if "=" in target_text:
            parser.error(
                "SOURCE=OUTPUT pairs are no longer supported. Use -o/--output to "
                "name the STEP file, or scripts/export for STL/3MF/GLB files."
            )
        suffix = Path(target_text).suffix.lower()
        if suffix in {".step", ".stp"}:
            parser.error(
                f"scripts/gen builds gen_step() Python sources only: {target_text}. "
                "Imported STEP/STP files get render artifacts on demand (inspect, snapshot, "
                "CAD Viewer); use scripts/export for STL/3MF/GLB files from an imported STEP."
            )
        if suffix != ".py":
            parser.error(f"scripts/gen target must be a gen_step() Python source: {target_text}")


def _sibling_step_output(target: str) -> str:
    # foo.step.py -> foo.step; plain foo.py -> foo.step (the target's logical STEP).
    if target.lower().endswith(".step.py"):
        return target[: -len(".py")]
    # as_posix(), because this half of a SOURCE=OUTPUT pair is a logical path. str() on a
    # Path renders the NATIVE separator, so on Windows the two branches disagreed: the slice
    # above kept "parts/second.step" and this one produced "parts\second.step" for the same
    # shape of input. Windows accepts forward slashes, so one spelling serves both.
    return Path(target).with_suffix(".step").as_posix()


def _targets_with_step_outputs(
    targets: Sequence[str],
    output: str | None,
    *,
    parser: argparse.ArgumentParser,
) -> list[str]:
    """Pair every target with its STEP output (the CLI's contract: Python
    source in, STEP file out) as the SOURCE=OUTPUT targets that
    cadgen.generation already resolves per target."""
    if output is None:
        return [f"{target}={_sibling_step_output(target)}" for target in targets]
    if len(targets) != 1:
        parser.error("-o/--output requires exactly one target")
    return [f"{targets[0]}={output}"]


# The skill entrypoint's name, which is what `--help` must say when invoked that way.
# `cadgen <command>` passes its own name instead, so each front door names itself.
DEFAULT_PROG = "scripts/gen"


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Generate STEP files from gen_step() Python sources. Each run keeps "
            "the model's render package (the document of record) current and "
            "assembles the .step output from it; unchanged sources are a no-op. "
            "Use scripts/export for STL/3MF/GLB files."
        ),
    )
    _add_gen_arguments(parser)
    return parser


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = build_parser(prog)
    args = parser.parse_args(list(argv) if argv is not None else None)
    _validate_python_targets(args.targets, parser=parser)
    step_options = StepImportOptions(
        mesh_tolerance=_normalize_cli_numeric(
            args.mesh_tolerance,
            field_name="mesh_tolerance",
            parser=parser,
        ),
        mesh_angular_tolerance=_normalize_cli_numeric(
            args.mesh_angular_tolerance,
            field_name="mesh_angular_tolerance",
            parser=parser,
        ),
    )
    try:
        return generate_step_targets(
            _targets_with_step_outputs(args.targets, args.output, parser=parser),
            step_options=step_options,
            force=bool(args.force),
            verbose=bool(args.verbose),
            json_output=bool(args.json),
            lock_timeout_s=float(args.lock_timeout or 0.0),
        )
    except Exception as exc:  # noqa: BLE001 — the CLI boundary: report, do not traceback
        return report_cli_error(exc, tool="scripts/gen", verbose=bool(args.verbose))


if __name__ == "__main__":
    raise SystemExit(main())
