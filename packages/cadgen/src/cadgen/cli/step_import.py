from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cadgen.metadata import normalize_mesh_numeric


def build_step_artifact(*args, **kwargs):
    from cadgen.step_artifact_cli import build_step_artifact as build

    return build(*args, **kwargs)


def _normalize_cli_numeric(value: object, *, field_name: str, parser: argparse.ArgumentParser) -> float | None:
    try:
        return normalize_mesh_numeric(value, field_name=field_name)
    except ValueError as exc:
        parser.error(str(exc))
    return None


def _add_artifact_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help="Imported STEP/STP file to build the render package for.",
    )
    parser.add_argument(
        "--kind",
        choices=("part", "assembly"),
        help="Override the inferred part/assembly kind.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when a current render package exists.",
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


# The skill entrypoint's name, which is what `--help` must say when invoked that way.
# `cadgen <command>` passes its own name instead, so each front door names itself.
DEFAULT_PROG = "cadgen import"


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Build the __cadgen__ render package for an IMPORTED STEP/STP file — the "
            "native twin of the CAD Viewer's WASM import. A generated model needs no "
            "import: run its @step model script directly (python <model>.py)."
        ),
    )
    _add_artifact_arguments(parser)
    return parser



def report_cli_error(*args, **kwargs):
    from cadgen._internal.cli_errors import report_cli_error as report

    return report(*args, **kwargs)

def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = build_parser(prog)
    args = parser.parse_args(list(argv) if argv is not None else None)
    target = str(args.target)
    suffix = Path(target).suffix.lower()
    if suffix == ".py":
        parser.error(
            f"{target} is a model script, not an import: run it directly "
            "(python <model>.py) to build its render package"
        )
    if suffix not in {".step", ".stp"}:
        parser.error(f"cadgen import target must be an imported STEP/STP file: {target}")
    step = target
    source_path = None
    mesh_tolerance = _normalize_cli_numeric(
        args.mesh_tolerance,
        field_name="mesh_tolerance",
        parser=parser,
    )
    mesh_angular_tolerance = _normalize_cli_numeric(
        args.mesh_angular_tolerance,
        field_name="mesh_angular_tolerance",
        parser=parser,
    )
    try:
        payload = build_step_artifact(
            repo_root=Path.cwd(),
            step=Path(step),
            source_path=Path(source_path) if source_path else None,
            kind=args.kind,
            force=bool(args.force),
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            verbose=bool(args.verbose),
        )
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:  # noqa: BLE001 — the CLI boundary: report, do not traceback
        return report_cli_error(exc, tool="cadgen import", verbose=bool(args.verbose))
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
