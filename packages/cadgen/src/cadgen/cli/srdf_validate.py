from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


from cadgen.findings import ValidationResult
from cadgen.srdf_source import SrdfSource, parse_srdf_file
from cadgen.srdf_validation import (
    display_path,
    read_urdf_robot,
    resolve_paired_urdf,
    validate_srdf_against_urdf,
)

SRDF_SUFFIX = ".srdf"


DEFAULT_PROG = "scripts/validate"

def validate_srdf_targets(
    targets: Sequence[str],
    *,
    strict: bool = False,
    output_format: str = "text",
) -> int:
    target_paths = [_resolve_target_path(target) for target in targets]
    reports: list[dict[str, object]] = []
    failed = False
    for target_path in target_paths:
        report = _validate_target(target_path, strict=strict, output_format=output_format)
        reports.append(report)
        if not report["ok"]:
            failed = True
    if output_format == "json":
        print(json.dumps({"files": reports}, separators=(",", ":")))
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Validate explicit MoveIt2 SRDF targets against their paired URDF.",
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="Explicit .srdf file to validate.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat validation warnings as failures.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        dest="output_format",
        help="Output format: human-readable text (default) or a JSON findings document.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Narrate each target and its timing on stderr.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.verbose:
        # Narration goes to stderr; the findings document on stdout stays exactly the same
        # so `--verbose` never changes what a caller parses.
        for target in args.targets:
            print(f"[srdf] validating {target}", file=sys.stderr)
    return validate_srdf_targets(args.targets, strict=args.strict, output_format=args.output_format)


def _resolve_target_path(raw_target: object) -> Path:
    value = str(raw_target or "").strip()
    if not value:
        raise ValueError("srdf target must be a non-empty path")
    target_path = Path(value).expanduser()
    return target_path.resolve() if target_path.is_absolute() else (Path.cwd() / target_path).resolve()


def _validate_target(target_path: Path, *, strict: bool, output_format: str) -> dict[str, object]:
    display = display_path(target_path)
    text_mode = output_format == "text"
    if target_path.suffix.lower() != SRDF_SUFFIX:
        return _report_precheck_failure(display, "target must be a .srdf file", text_mode)
    if not target_path.is_file():
        return _report_precheck_failure(display, "file not found", text_mode)

    srdf_source, result = parse_srdf_file(target_path)
    urdf_path: Path | None = None
    if srdf_source is not None:
        urdf_path = resolve_paired_urdf(srdf_source.robot_name, srdf_dir=target_path.parent, result=result)
        if urdf_path is not None:
            urdf_robot = read_urdf_robot(urdf_path, result)
            if urdf_robot is not None:
                validate_srdf_against_urdf(srdf_source, urdf_robot=urdf_robot, result=result)

    result = result.deduplicated()
    ok = _report_findings(display, result, strict=strict, text_mode=text_mode)
    summary = ""
    if srdf_source is not None and urdf_path is not None:
        summary = _summary_line(display, srdf_source, urdf_path)
    if text_mode and ok and summary:
        print(summary)
    return {
        "path": display,
        "ok": ok,
        "summary": summary,
        "findings": [finding.to_dict() for finding in result.all_findings()],
    }


def _report_precheck_failure(display: str, message: str, text_mode: bool) -> dict[str, object]:
    if text_mode:
        print(f"FAIL {display}: {message}", file=sys.stderr)
    return {
        "path": display,
        "ok": False,
        "summary": "",
        "findings": [{"severity": "error", "code": "invalid_target", "message": message}],
    }


def _report_findings(display: str, result: ValidationResult, *, strict: bool, text_mode: bool) -> bool:
    if text_mode:
        for finding in result.all_findings():
            print(finding.format(), file=sys.stderr)
    blocking = len(result.errors) + (len(result.warnings) if strict else 0)
    if blocking:
        if text_mode:
            print(f"FAIL {display}: {blocking} blocking finding(s)", file=sys.stderr)
        return False
    return True


def _summary_line(display: str, srdf_source: SrdfSource, urdf_path: Path) -> str:
    return (
        f"OK {display}: robot {srdf_source.robot_name!r}, urdf {display_path(urdf_path)}, "
        f"{len(srdf_source.planning_groups)} groups, {len(srdf_source.end_effectors)} end effectors, "
        f"{len(srdf_source.group_states)} group states, "
        f"{len(srdf_source.disabled_collision_pairs)} disabled collision pairs, "
        f"{len(srdf_source.virtual_joints)} virtual joints"
    )


