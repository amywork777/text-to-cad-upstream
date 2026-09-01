"""Snapshot below the options boundary: job resolution and the run loop.

There is no parser here any more. Snapshot used to be the schema's one ADAPTER
— a hand-written argv scanner plus a declared option surface a policy test
pinned — and that exception is retired: the verbs in
:mod:`cadgen._internal.snapshot_door` are MIRRORS, and their generated parsers
hand this module a :class:`SnapshotOptions` already built. What remains is
everything downstream of that:

    run_snapshot(options, kinds=("step", "stp"), runtime_dir=...)

It lives in cadgen rather than in the CAD skill because a skill may not import another
skill's code (AGENTS.md), and the robot resolver alone is needed by three skills at once.
The split against :mod:`cadgen.snapshot_core` is by ROLE, not by format: the core owns the
headless browser, the job/theme/display normalisation and output writing; this module owns
the command line and the per-kind resolution that decides what a given input even is.

Every input kind resolves here, and a skill enables a subset. An input the running skill
does not enable is rejected BY NAME with a pointer to the skill that owns it, so a `.urdf`
handed to the CAD skill is told where to go rather than failing on a missing resolver.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadgen.cad_ref_syntax as cad_ref_syntax
import cadgen.lookup as lookup
from cadgen.assets import browser_runtime_dir
from cadgen.catalog import render_package_dir
from cadgen.step_targets import ResolvedStepTarget, StepTopologyArtifact, StepTopologyArtifactError

from cadgen.cli_logging import CliLogger
from cadgen.coordination import PHASE_BROWSER, SNAPSHOT, ProgressReporter
# What a GROUP occurrence ref means is shared with `cadgen step inspect`
# (cadgen.occurrence_groups). Two commands answering "does this document have an o1.4"
# differently is a bug that reads as a data problem, and the near-miss hint is exactly
# the sort of text that drifts when it is written twice. Re-exported here because
# callers of this module have always reached for these names through it.
from cadgen.occurrence_groups import (
    OCCURRENCE_NEAR_MISS_LIMIT,
    UnknownOccurrenceSelector,
    occurrence_group_ids,
    occurrence_near_miss_hint,
    occurrence_sort_key,
)
from cadgen.occurrence_groups import (
    expand_occurrence_selector as _expand_occurrence_selector,
)
from cadgen.cli_progress import cli_progress_line
from cadgen.results import SnapshotResult
from cadgen.snapshot_core import (
    THEME_OPTION_KEYS,
    BatchSnapshotRenderer,
    COMPLEX_ASSEMBLY_LARGE_RENDER_HEIGHT,
    COMPLEX_ASSEMBLY_LARGE_RENDER_WIDTH,
    COMPLEX_ASSEMBLY_RENDER_HEIGHT,
    COMPLEX_ASSEMBLY_RENDER_WIDTH,
    CONTACT_SHEET_RENDER_HEIGHT,
    CONTACT_SHEET_RENDER_WIDTH,
    DEFAULT_RENDER_THEME_ID,
    DEFAULT_TIMEOUT_SECONDS,
    DIAGNOSTIC_RENDER_HEIGHT,
    DIAGNOSTIC_RENDER_WIDTH,
    DISPLAY_MODE_ALIASES,
    DISPLAY_OPTION_KEYS,
    MESH_INPUT_KINDS,
    MESH_SUPPORTED_RENDER_MODES,
    PRESENTATION_LARGE_RENDER_HEIGHT,
    PRESENTATION_LARGE_RENDER_WIDTH,
    PRESENTATION_RENDER_HEIGHT,
    PRESENTATION_RENDER_WIDTH,
    RENDER_BROWSER_STARTUP_TIMEOUT_MS,
    RouteFileError,
    RETIRED_JOB_KEYS,
    SELECTION_SHAPED_JOB_KEYS,
    SETTINGS_KEY_HOMES,
    SIMPLE_RENDER_HEIGHT,
    SIMPLE_RENDER_WIDTH,
    SIMPLE_SQUARE_RENDER_HEIGHT,
    SIMPLE_SQUARE_RENDER_WIDTH,
    SNAPSHOT_ORIGIN,
    SNAPSHOT_RENDER_URL,
    SNAPSHOT_ROUTE_GLOB,
    SUPPORTED_JOB_KEYS,
    SUPPORTED_OUTPUT_KEYS,
    SUPPORTED_RENDER_MODES,
    SnapshotError,
    TOPOLOGY_DISPLAY_MODES,
    WORKBENCH_RENDER_THEME_IDS,
    theme_id_for_job,
    asset_url_for_path,
    clear_render_output_targets,
    content_type_for_path,
    default_render_size,
    encode_path_param,
    explicit_size_profile,
    is_plain_object,
    load_theme_option,
    load_display_option,
    load_json_text,
    max_output_size,
    normalize_common_job,
    normalize_size_profile,
    normalize_snapshot_job_packet,
    parse_camera_option,
    path_is_inside_or_equal,
    render_resolved_job_packet,
    render_snapshot,
    resolve_mesh_render_job,
    has_kinematics_render_values,
    resolve_output_size,
    selection_filter_values,
    selection_value_list,
    resolve_snapshot_route_file,
    route_file,
    snapshot_timestamp,
    reject_animated_kinematics,
    validate_direct_settings_payload,
    validate_display_settings_values,
    with_snapshot_timeout,
    write_output_payload,
    write_render_outputs,
)


# SUPPORTED_RENDER_MODES is the union across every kind -- "is that a mode at all?" -- so
# each kind still has to name its own.
STEP_SUPPORTED_RENDER_MODES = {"view", "section", "list"}

# Imported lazily by ensure_render_job_step_artifact: only a STEP input needs it, and
# importing it eagerly would drag OCP into a robot or mesh snapshot that never builds
# anything. Kept module-level so tests can substitute it.
ensure_step_topology_artifact = None


@dataclass(slots=True)
class SnapshotOptions:
    """Every snapshot flag, as a field.

    ``slots=True`` so a typo'd assignment fails loudly. The parser mutates this
    object attribute by attribute, and on a plain dataclass
    ``options.size_profle = ...`` silently created a NEW attribute: the flag
    parsed, the run succeeded, and the setting was never applied. There is
    nothing left for a slot to hide behind.
    """

    job: str = ""
    input: str = ""
    output: str = ""
    mode: str = "view"
    theme: object = DEFAULT_RENDER_THEME_ID
    theme_specified: bool = False
    display: object = ""
    display_specified: bool = False
    camera: object = "iso"
    camera_specified: bool = False
    width: int | None = None
    height: int | None = None
    size_profile: str = ""
    params: object = None
    params_specified: bool = False
    joint_values: object = None
    joint_values_specified: bool = False
    focus: list[str] | None = None
    hide: list[str] | None = None
    view_labels: bool = False
    debug: bool = False


def parse_params_option(raw_params: object) -> dict[str, object] | str:
    """``--kinematics`` in job form: a values object, or a PRESET NAME.

    Already an object when it came from a ``<format>.snapshot(kinematics={...})``
    call rather than argv; see the note above parse_camera_option. From argv it
    is one string, and the two spellings are told apart by shape rather than by
    a second flag: text that opens with ``{`` is inline JSON, anything else is
    the name of a pose the model DECLARES. Resolving that name needs the
    kinematics declaration, which only the renderer has loaded, so the name
    travels through unresolved and the job's `kinematics` key carries either shape.
    """
    if is_plain_object(raw_params):
        return dict(raw_params)
    text = str(raw_params or "")
    if not text.lstrip().startswith("{"):
        return text
    parsed = load_json_text(text, "--kinematics")
    if not is_plain_object(parsed):
        raise SnapshotError("--kinematics must be a pose preset name or a JSON object")
    return parsed


def parse_joint_values_option(raw_joint_values: object) -> dict[str, object]:
    """``--joint-values`` in job form: ``{joint: degrees}``.

    A robot description declares no named poses — its articulation is the joint
    list in the file — so unlike ``--kinematics`` there is no preset spelling to
    tell apart, and anything that is not an object is an error.
    """
    if is_plain_object(raw_joint_values):
        return dict(raw_joint_values)
    parsed = load_json_text(str(raw_joint_values or ""), "--joint-values")
    if not is_plain_object(parsed):
        raise SnapshotError("--joint-values must be a {joint: degrees} JSON object")
    return parsed


def option_focus_hide_specified(options: SnapshotOptions) -> bool:
    return bool(options.focus or options.hide)


def merge_focus_hide_options(job: dict[str, object], options: SnapshotOptions) -> None:
    if not option_focus_hide_specified(options):
        return
    if options.focus and options.hide:
        raise SnapshotError("--focus and --hide cannot be used in the same snapshot command")
    selection = dict(job.get("selection") if is_plain_object(job.get("selection")) else {})
    if options.focus:
        selection["focus"] = list(options.focus)
    if options.hide:
        selection["hide"] = list(options.hide)
    job["selection"] = selection










def apply_option_overrides_to_job(job: object, options: SnapshotOptions, *, cwd: Path) -> object:
    if not is_plain_object(job):
        return job
    if not any(
        [
            options.view_labels,
            options.debug,
            options.size_profile,
            options.params_specified,
            options.joint_values_specified,
            options.display_specified,
            options.theme_specified,
            options.camera_specified,
            option_focus_hide_specified(options),
        ]
    ):
        return job
    next_job = copy.deepcopy(job)
    merge_focus_hide_options(next_job, options)
    if options.debug:
        next_job["debug"] = True
    if options.theme_specified:
        next_job["theme"] = load_theme_option(options.theme, cwd=cwd)
    if options.params_specified:
        next_job["kinematics"] = parse_params_option(options.params)
    if options.joint_values_specified:
        next_job["jointValues"] = parse_joint_values_option(options.joint_values)
    if options.display_specified:
        next_job["display"] = load_display_option(options.display, cwd=cwd)
    if options.camera_specified:
        next_job["camera"] = parse_camera_option(options.camera)
    render = dict(next_job.get("render") if is_plain_object(next_job.get("render")) else {})
    if options.view_labels:
        render["viewLabels"] = True
    if options.size_profile:
        render["sizeProfile"] = options.size_profile
    next_job["render"] = render
    return next_job


def apply_option_overrides_to_payload(payload: object, options: SnapshotOptions, *, cwd: Path) -> object:
    if isinstance(payload, list):
        return [apply_option_overrides_to_job(job, options, cwd=cwd) for job in payload]
    if is_plain_object(payload) and isinstance(payload.get("jobs"), list):
        next_payload = copy.deepcopy(payload)
        next_payload["jobs"] = [apply_option_overrides_to_job(job, options, cwd=cwd) for job in payload["jobs"]]
        return next_payload
    return apply_option_overrides_to_job(payload, options, cwd=cwd)


def load_job_from_options(
    options: SnapshotOptions,
    *,
    stdin: Any = sys.stdin,
    cwd: Path | None = None,
) -> object:
    resolved_cwd = (cwd or Path.cwd()).resolve()
    if options.job:
        if options.job == "-":
            text = stdin.read()
            source_label = "stdin"
        else:
            job_path = (resolved_cwd / options.job).resolve()
            text = job_path.read_text(encoding="utf-8")
            source_label = str(job_path)
        return apply_option_overrides_to_payload(load_json_text(text, source_label), options, cwd=resolved_cwd)

    if not stdin.isatty() and not options.input:
        text = stdin.read()
        if text.strip():
            return apply_option_overrides_to_payload(load_json_text(text, "stdin"), options, cwd=resolved_cwd)

    if not options.input:
        raise SnapshotError("render requires a TARGET, --job, or stdin JSON")
    if options.mode != "list" and not options.output:
        raise SnapshotError("render requires an OUT path for non-list modes: snapshot TARGET OUT")

    output: dict[str, object] = {
        "path": options.output,
        "camera": parse_camera_option(options.camera),
    }
    if options.width:
        output["width"] = options.width
    if options.height:
        output["height"] = options.height

    job: dict[str, object] = {
        "input": options.input,
        "mode": options.mode,
        "outputs": [] if options.mode == "list" else [output],
        "theme": load_theme_option(options.theme, cwd=resolved_cwd),
        "render": {"viewLabels": options.view_labels},
    }
    if options.size_profile:
        job["render"]["sizeProfile"] = options.size_profile
    if options.display_specified:
        job["display"] = load_display_option(options.display, cwd=resolved_cwd)
    if options.params_specified:
        job["kinematics"] = parse_params_option(options.params)
    if options.joint_values_specified:
        job["jointValues"] = parse_joint_values_option(options.joint_values)
    if options.debug:
        job["debug"] = True
    merge_focus_hide_options(job, options)
    return job




def input_kind(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".step":
        return "step"
    if suffix == ".stp":
        return "stp"
    if suffix == ".dxf":
        return "dxf"
    if suffix == ".py":
        # DOCUMENTS-ONLY: a model script is a program. The kind survives only so
        # the resolver can refuse it by naming the run.
        return "python"
    if suffix == ".glb":
        return "glb"
    if suffix == ".stl":
        return "stl"
    if suffix == ".3mf":
        return "3mf"
    if suffix in {".urdf", ".srdf", ".sdf"}:
        return suffix[1:]
    return ""


def resolve_input_path(raw_input: object, *, cwd: Path) -> Path:
    input_text = str(raw_input or "").strip()
    if not input_text:
        raise SnapshotError("render job is missing input")
    raw_path = Path(input_text)
    selected = raw_path.resolve() if raw_path.is_absolute() else (cwd / raw_path).resolve()
    if not selected.exists():
        raise SnapshotError(f"Render input does not exist: {input_text}")
    return selected






def reference_root_for_input(input_path: Path, cwd: Path) -> Path:
    return cwd if path_is_inside_or_equal(input_path, cwd) else input_path.parent


def cad_ref_for_step_path(repo_root: Path, step_path: Path) -> str:
    try:
        relative = step_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        relative = step_path.resolve().as_posix()
    suffix = step_path.suffix
    return relative[: -len(suffix)] if suffix else relative


def load_ensure_step_topology_artifact():
    global ensure_step_topology_artifact
    if ensure_step_topology_artifact is None:
        from cadgen.step_topology_artifact import ensure_step_topology_artifact as imported_ensure

        ensure_step_topology_artifact = imported_ensure
    return ensure_step_topology_artifact






def selector_value_requires_topology(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = cad_ref_syntax.parse_selector(text)
    return parsed is not None and parsed.selector_type != "opaque"


def selection_requires_selector_topology(job: Mapping[str, object]) -> bool:
    return any(selector_value_requires_topology(value) for value in selection_filter_values(job))


def ensure_render_job_step_artifact(
    job: Mapping[str, object],
    *,
    reference_root: Path,
    input_path: Path,
    step_path: Path,
    require_selector: bool = False,
    debug_info: dict[str, object] | None = None,
) -> StepTopologyArtifact:
    target = ResolvedStepTarget(
        cad_path=cad_ref_for_step_path(reference_root, step_path),
        kind="part",
        source_path=input_path,
        step_path=step_path,
    )
    try:
        ensure_artifact = load_ensure_step_topology_artifact()
        return ensure_artifact(
            target,
            require_selector=require_selector,
            debug=debug_info,
        )
    except StepTopologyArtifactError as exc:
        raise SnapshotError(str(exc)) from exc


def artifact_selector_index(artifact: StepTopologyArtifact | None) -> lookup.SelectorIndex | None:
    selector_bundle = artifact.selector_bundle if artifact is not None else None
    if selector_bundle is None:
        return None
    manifest = selector_bundle.manifest if isinstance(selector_bundle.manifest, dict) else None
    if manifest is None:
        return None
    buffers = selector_bundle.buffers if isinstance(selector_bundle.buffers, Mapping) else None
    index = lookup.build_selector_index(manifest, buffers=buffers)
    # The bundle is extracted from the COMPOSED compound, which has no instance tree, so it
    # describes even a 160-part assembly as one occurrence -- and `--focus`/`--hide` rejected
    # every ref `--mode list` had just handed out. See `cadgen.assembly_lookup`.
    from cadgen.assembly_lookup import index_with_assembly_occurrences

    return index_with_assembly_occurrences(index, artifact)


def expand_occurrence_selector(
    selector: str, *, selector_index: lookup.SelectorIndex | None, source_label: str
) -> list[str]:
    """The rendered occurrences a selection ref covers, as a snapshot error on failure."""
    try:
        return _expand_occurrence_selector(
            selector, selector_index=selector_index, source_label=source_label
        )
    except UnknownOccurrenceSelector as error:
        raise SnapshotError(str(error)) from error


def normalize_selection_selector(
    raw_value: str,
    *,
    selector_index: lookup.SelectorIndex | None,
    source_label: str,
    expected_cad_path: str = "",
) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    # A copied ref may carry a file prefix (`plate.step.py#o1.2`). Accept it when it names the
    # model being rendered, refuse it when it names another -- rendering a different file's ref
    # against this model would focus the wrong geometry and look like it worked.
    if "#" in text:
        prefix, _, remainder = text.partition("#")
        if prefix.strip():
            try:
                cad_ref_syntax.ensure_ref_file_matches(
                    prefix, expected_cad_path, source_label=f"{source_label} ref {text!r}"
                )
            except ValueError as error:
                raise SnapshotError(str(error)) from error
        text = remainder.strip()
        if not text:
            return []
    parsed = cad_ref_syntax.parse_selector(text)
    if parsed is None:
        return []
    if parsed.label:
        # Labels become numeric here, before any validation or job building, so everything
        # downstream -- including the JS render runtime -- only ever sees occurrence ids.
        from cadgen.label_refs import LabelResolutionError, resolve_label_selectors

        alias_map = getattr(selector_index, "label_aliases", None) if selector_index else None
        try:
            resolved = resolve_label_selectors([text], alias_map)
        except LabelResolutionError as error:
            raise SnapshotError(f"{source_label} {error}") from error
        parsed = cad_ref_syntax.parse_selector(resolved[0]) if resolved else None
        if parsed is None:
            return []
    if parsed.selector_type == "opaque":
        return [parsed.canonical]
    if parsed.selector_type != "occurrence":
        raise SnapshotError(
            f"{source_label} supports only part/subassembly occurrence refs; "
            f"got {parsed.selector_type} selector {text!r}"
        )
    # A GROUP ref expands to its subtree here — including a label that resolved to a group
    # id, which takes this same path, so labels and ids behave identically wherever the
    # label already exists.
    return expand_occurrence_selector(
        parsed.canonical, selector_index=selector_index, source_label=source_label
    )


def normalize_selection_filter_values(
    value: object,
    *,
    expected_cad_path: str,
    selector_index: lookup.SelectorIndex | None,
    source_label: str,
) -> list[str]:
    # Deduped, first-seen order. A group ref expands to its subtree, so naming a
    # subassembly AND one of its parts (or two overlapping groups) is an ordinary thing to
    # do and must not put the same occurrence in the job twice.
    selectors: dict[str, None] = {}
    for raw_value in selection_value_list(value):
        for selector in normalize_selection_selector(
            raw_value,
            selector_index=selector_index,
            source_label=source_label,
            expected_cad_path=expected_cad_path,
        ):
            selectors.setdefault(selector, None)
    return list(selectors)


def normalize_render_job_selection(
    job: Mapping[str, object],
    *,
    expected_cad_path: str,
    selector_index: lookup.SelectorIndex | None,
) -> dict[str, object] | None:
    selection = job.get("selection") if is_plain_object(job.get("selection")) else None
    if selection is None:
        return None
    if any(selection_value_list(selection.get(key)) for key in ("focus", "refs")) and selection_value_list(
        selection.get("hide")
    ):
        raise SnapshotError("selection.focus/refs and selection.hide cannot be used in the same snapshot job")
    normalized = dict(selection)
    for key in ("focus", "refs", "hide"):
        if key not in selection:
            continue
        normalized[key] = normalize_selection_filter_values(
            selection.get(key),
            expected_cad_path=expected_cad_path,
            selector_index=selector_index,
            source_label=f"selection.{key}",
        )
    return normalized






def resolve_robot_render_job(
    job: dict[str, object],
    *,
    kind: str,
    input_path: Path,
    root_path: Path,
    resolved_cwd: Path,
    timestamp: str | None,
    job_index: int = 0,
    job_count: int = 1,
    **_kind_context: object,
) -> dict[str, object]:
    """Resolve a robot description (`.urdf` / `.srdf` / `.sdf`).

    The browser assembles the robot: the parser resolves each link mesh against the
    description's own URL, so this hands over one asset URL and the pose, and the shared
    mesh backend renders the result. STEP-only options are rejected up front."""
    label = kind.upper()

    if selection_filter_values(job):
        raise SnapshotError(
            f"selection focus/hide/refs require STEP topology; {label} robots have no "
            "part/subassembly selectors"
        )
    if has_kinematics_render_values(job.get("kinematics")):
        raise SnapshotError(
            f"kinematics values require a STEP model; pose a {label} robot with jointValues"
        )

    mode = str(job.get("mode") or "view").strip().lower()
    if mode not in SUPPORTED_RENDER_MODES:
        raise SnapshotError(f"Unsupported render mode: {mode or '(missing)'}")
    if mode not in MESH_SUPPORTED_RENDER_MODES:
        supported = ", ".join(sorted(MESH_SUPPORTED_RENDER_MODES))
        raise SnapshotError(
            f"{mode} mode requires STEP topology; {label} robots support: {supported}"
        )

    display = job.get("display") if is_plain_object(job.get("display")) else {}
    raw_display_mode = re.sub(r"[\s-]+", "_", str(display.get("mode") or "").strip().lower())
    canonical_display_mode = DISPLAY_MODE_ALIASES.get(raw_display_mode, raw_display_mode)
    if canonical_display_mode and canonical_display_mode != "solid":
        raise SnapshotError(
            f"{canonical_display_mode} display mode is not supported for {label} robots; "
            "robots render shaded solid from their link meshes"
        )
    exploded = display.get("exploded") if is_plain_object(display.get("exploded")) else None
    if exploded is not None and exploded.get("enabled"):
        raise SnapshotError(
            f"exploded view requires STEP assembly occurrence structure; {label} robots "
            "cannot be exploded"
        )

    joint_values = job.get("jointValues")
    if joint_values is not None and not is_plain_object(joint_values):
        raise SnapshotError("jointValues must be an object of joint name to angle")
    if joint_values:
        for name, value in joint_values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SnapshotError(f"jointValues[{name}] must be a number (degrees)")

    # Link meshes are referenced relative to the description, so the served root has to
    # contain both. The description's own directory is the natural root and matches how the
    # viewer serves a robot from its model folder.
    asset_url = asset_url_for_path(input_path, root_path)
    resolved: dict[str, object] = {
        "rootPath": str(root_path),
        "inputPath": str(input_path),
        "inputUrl": asset_url,
        "kind": kind,
        "url": asset_url,
    }
    if kind == "srdf":
        # An SRDF carries semantics; its geometry comes from the URDF beside it.
        urdf_path = input_path.with_suffix(".urdf")
        if urdf_path.exists():
            resolved["urdfUrl"] = asset_url_for_path(urdf_path, root_path)
    if joint_values:
        resolved["jointValues"] = dict(joint_values)
    if bool(job.get("debug")):
        resolved["debug"] = {"robotSource": {"kind": kind}}

    # Robots are authored in METRES; the CAD profile assumes millimetres, and its floor,
    # grid and lighting radii are sized accordingly. Default the robot profile so a robot
    # frames like a robot without the caller having to know the unit convention.
    if not str(job.get("sceneScale") or job.get("scale") or "").strip():
        job = {**job, "sceneScale": "urdf"}

    normalized = normalize_common_job(
        job,
        mode=mode,
        resolved_cwd=resolved_cwd,
        timestamp=timestamp,
        job_index=job_index,
        job_count=job_count,
    )
    normalized["resolved"] = resolved
    return normalized


def resolve_render_job(
    raw_job: object,
    *,
    cwd: Path | None = None,
    timestamp: str | None = None,
    kinds: frozenset[str] | None = None,
    job_index: int = 0,
    job_count: int = 1,
) -> dict[str, object]:
    if not is_plain_object(raw_job):
        raise SnapshotError("render job must be an object")
    job = copy.deepcopy(raw_job)
    if "params" in job:
        raise SnapshotError("render jobs use kinematics; params is reserved for shortcut --kinematics parsing")
    # A key that WAS the schema is named, not aliased. Reading `stepParameters` as
    # `kinematics` would leave two spellings of one thing alive in every job file, and the
    # whole point of the rename is that the CLI flag, the sidecar section and the job
    # packet say the same word.
    for retired_key, guidance in RETIRED_JOB_KEYS.items():
        if retired_key in job:
            raise SnapshotError(guidance)
    if "paramsPath" in job or "stepParametersPath" in job:
        raise SnapshotError(
            "parameter sidecar paths are retired: kinematics is declared on the model "
            "(@step(kinematics={...})) and read from its sidecar; "
            "see skills/cad/references/kinematics.md"
        )
    forbidden_root_fields = [field for field in ("workspaceRoot", "rootDir") if field in job]
    if forbidden_root_fields:
        raise SnapshotError(
            "snapshot jobs no longer accept workspaceRoot or rootDir; pass a relative or absolute input path instead"
        )

    # Every other key must come from the closed job schema. Selection-shaped
    # near-misses get the exact fix spelled out; anything else is named with
    # the supported set so a typo fails here instead of rendering as if the
    # key were absent.
    unknown_keys = sorted(set(job) - SUPPORTED_JOB_KEYS)
    if unknown_keys:
        selection_shaped = [key for key in SELECTION_SHAPED_JOB_KEYS if key in unknown_keys]
        if selection_shaped:
            fields = ", ".join(f'"{key}": [...]' for key in selection_shaped)
            raise SnapshotError(
                f"render jobs take part selectors inside the selection object, not at top level; "
                f"move {fields} into \"selection\": {{...}}"
            )
        raise SnapshotError(
            f"unknown render job key(s): {', '.join(unknown_keys)}; "
            f"supported keys: {', '.join(sorted(SUPPORTED_JOB_KEYS))}"
        )

    resolved_cwd = (cwd or Path.cwd()).resolve()
    raw_input = str(job.get("input") or "").strip()
    if not raw_input:
        raise SnapshotError("render job is missing input")

    # A job's own `display` string gets the same treatment as the --display
    # flag: a mode name, an inline JSON object, or a path to a display JSON.
    # Without this it fell through to normalize_common_job, which accepts only
    # a plain object and silently substituted {"mode": "solid"} -- so
    # "wireframe", a file path, and an outright typo all rendered the default.
    raw_display = job.get("display")
    if isinstance(raw_display, str) and raw_display.strip():
        job["display"] = load_display_option(raw_display, cwd=resolved_cwd)

    # Closed-set display values are validated for the --display flag path in
    # load_display_option; a display object embedded in a full JSON job must get
    # the same guard, or a typo'd projection/mode silently renders the default.
    if is_plain_object(job.get("display")):
        validate_display_settings_values(job["display"], source_label="job display")

    input_path = resolve_input_path(raw_input, cwd=resolved_cwd)
    root_path = input_path.parent.resolve()
    reference_root = reference_root_for_input(input_path, resolved_cwd)
    kind = input_kind(input_path)
    source_path = input_path
    if kind == "python":
        # Scripts are RUN, never rendered: `python <script>` writes the
        # document, and snapshot renders the document.
        from cadgen._internal.doors import script_target_message

        raise SnapshotError(script_target_message(input_path))
    if kinds is not None:
        reject_unsupported_kind(kind, input_path, kinds)
    resolver = KIND_RESOLVERS.get(kind)
    if resolver is None:
        raise SnapshotError(
            f"snapshot cannot render {input_path.suffix or 'that file'} inputs: {input_path}"
        )
    return resolver(
        job,
        kind=kind,
        input_path=input_path,
        root_path=root_path,
        source_path=source_path,
        reference_root=reference_root,
        resolved_cwd=resolved_cwd,
        timestamp=timestamp,
        job_index=job_index,
        job_count=job_count,
    )


def resolve_step_render_job(
    job: dict[str, object],
    *,
    kind: str,
    input_path: Path,
    root_path: Path,
    source_path: Path,
    reference_root: Path,
    resolved_cwd: Path,
    timestamp: str | None,
    job_index: int = 0,
    job_count: int = 1,
    **_kind_context: object,
) -> dict[str, object]:
    has_param_render = has_kinematics_render_values(job.get("kinematics"))
    reject_animated_kinematics(job.get("kinematics"))
    # A render is a READ. A document whose sidecar closure no longer re-hashes
    # is refused by naming the run rather than rebuilt here — putting a build
    # inside a render is exactly the coupling documents-only inputs remove.
    from cadgen._internal.doors import require_current_document

    require_current_document(input_path)
    # Kinematics values drive the model's sidecar kinematics block. The retired
    # sidecar-path key is rejected upfront in job normalization.
    debug_enabled = bool(job.get("debug"))
    step_artifact_debug: dict[str, object] | None = {} if debug_enabled else None
    artifact = ensure_render_job_step_artifact(
        job,
        reference_root=reference_root,
        input_path=source_path,
        step_path=input_path,
        require_selector=selection_requires_selector_topology(job),
        debug_info=step_artifact_debug,
    )
    expected_cad_path = cad_ref_for_step_path(reference_root, input_path)
    normalized_selection = normalize_render_job_selection(
        job,
        expected_cad_path=expected_cad_path,
        selector_index=artifact_selector_index(artifact),
    )

    # The render package is content-keyed in the user-level store: the entry
    # file's bytes are hashed and looked up (cadgen.catalog.render_package_dir).
    package_dir = render_package_dir(source_path)
    if not package_dir.is_dir():
        raise SnapshotError(f"STEP/STP render input is missing its render package: {package_dir}")

    mode = str(job.get("mode") or "view").strip().lower()
    if mode not in SUPPORTED_RENDER_MODES:
        raise SnapshotError(f"Unsupported render mode: {mode or '(missing)'}")
    if mode not in STEP_SUPPORTED_RENDER_MODES:
        supported = ", ".join(sorted(STEP_SUPPORTED_RENDER_MODES))
        raise SnapshotError(
            f"{mode} mode is not supported for STEP inputs; STEP supports: {supported}"
        )
    if has_param_render and mode != "view":
        raise SnapshotError("kinematics values support only view mode; set display.mode for display-style changes")

    resolved: dict[str, object] = {
        "rootPath": str(root_path),
        "inputPath": str(input_path),
        "inputUrl": asset_url_for_path(input_path, root_path),
        "kind": kind,
        "packagePath": str(package_dir),
    }
    # Component-GLB package (the canonical render artifact for every STEP model): inline
    # the descriptor and pre-resolve one asset URL per unique component GLB so the renderer
    # fetches and composes them in world space.
    descriptor = json.loads((package_dir / "assembly.json").read_text())
    from cadgen.snapshot_core import asset_url_for_store_path

    component_urls = {
        cid: asset_url_for_store_path(package_dir / str(entry.get("surf", "")))
        for cid, entry in (descriptor.get("components") or {}).items()
    }
    resolved["package"] = {"descriptor": descriptor, "componentUrls": component_urls}
    from cadgen._internal.source_sidecar import read_source_sidecar, source_sidecar_path

    sidecar = read_source_sidecar(source_path) or {}
    kinematics_block = (
        sidecar.get("kinematics") if isinstance(sidecar.get("kinematics"), dict) else None
    )
    if kinematics_block:
        # Typed mates are the ONE articulation mechanism: the page fetches the
        # sidecar and folds --params DOF values through the shared FK
        # evaluator (cadgen-js kinematicsModule).
        resolved["stepParameterUrl"] = asset_url_for_path(source_sidecar_path(source_path), root_path)
        # A pose NAME is validated HERE, against the declaration the CLI just
        # loaded — a typo must fail as a clean CLI error, not as a stack trace
        # out of the browser runtime (which repeats this check as a backstop).
        preset = job.get("kinematics")
        if isinstance(preset, str) and preset.strip():
            poses = kinematics_block.get("poses")
            declared = sorted(poses) if isinstance(poses, dict) else []
            if preset.strip() not in declared:
                raise SnapshotError(
                    f"Unknown kinematics pose: {preset.strip()}. "
                    + (
                        f"This model declares: {', '.join(declared)}"
                        if declared
                        else "This model declares no poses; pass {dof: value} JSON instead"
                    )
                )
    elif has_param_render:
        raise SnapshotError(
            f"{input_path.name} declares no kinematics, so pose values have nothing to "
            "drive — declare kinematics= (typed mates) on the model's @step; "
            "see the cad skill's kinematics reference"
        )
    if debug_enabled:
        resolved["debug"] = {"stepArtifact": step_artifact_debug}

    if normalized_selection is not None:
        job["selection"] = normalized_selection

    normalized = normalize_common_job(
        job,
        mode=mode,
        resolved_cwd=resolved_cwd,
        timestamp=timestamp,
        job_index=job_index,
        job_count=job_count,
    )
    normalized["resolved"] = resolved
    return normalized


def resolve_drawing_render_job(
    job: dict[str, object],
    *,
    kind: str,
    input_path: Path,
    root_path: Path,
    resolved_cwd: Path,
    timestamp: str | None,
    job_index: int = 0,
    job_count: int = 1,
    **_kind_context: object,
) -> dict[str, object]:
    """Resolve a drawing input (`.dxf` or a `gen_dxf()` generator).

    A drawing has no geometry of its own to render: what the viewport shows is
    the 3D flat pattern. There is no drawing package any more (design/
    standalone-viewer.md Phase A) — a generator's product is its `.dxf` sibling
    (made current through the ordinary gen no-op gate) and the mesh is produced
    on demand by the bundled Node one-shot (bin/dxf-mesh.mjs: parseDxf ->
    buildDxfPreviewMeshData -> writeGlb) into a temp GLB the ordinary mesh path
    renders. Drawings carry no CAD topology, so the STEP-only options are
    rejected the way they are for every other non-STEP kind.
    """
    if selection_filter_values(job):
        raise SnapshotError(
            "selection focus/hide/refs require STEP topology; drawings have no "
            "part/subassembly selectors"
        )
    if has_kinematics_render_values(job.get("kinematics")):
        raise SnapshotError(
            "kinematics values require a STEP model; a drawing is parameterized by its gen_dxf() source"
        )

    mode = str(job.get("mode") or "view").strip().lower()
    if mode not in SUPPORTED_RENDER_MODES:
        raise SnapshotError(f"Unsupported render mode: {mode or '(missing)'}")
    if mode not in MESH_SUPPORTED_RENDER_MODES:
        supported = ", ".join(sorted(MESH_SUPPORTED_RENDER_MODES))
        raise SnapshotError(
            f"{mode} mode requires STEP topology; drawings support: {supported}"
        )

    display = job.get("display") if is_plain_object(job.get("display")) else {}
    raw_display_mode = re.sub(r"[\s-]+", "_", str(display.get("mode") or "").strip().lower())
    canonical_display_mode = DISPLAY_MODE_ALIASES.get(raw_display_mode, raw_display_mode)
    if canonical_display_mode and canonical_display_mode != "solid":
        raise SnapshotError(
            f"{canonical_display_mode} display mode is not supported for drawings; "
            "a drawing renders its flat pattern shaded solid"
        )
    exploded = display.get("exploded") if is_plain_object(display.get("exploded")) else None
    if exploded is not None and exploded.get("enabled"):
        raise SnapshotError(
            "exploded view requires STEP assembly occurrence structure; drawings cannot be exploded"
        )

    preview = drawing_mesh_path(input_path, force=bool(job.get("force")))
    # The mesh is a temp artifact beside nothing the caller serves, so serve it
    # from its own directory when it falls outside the cwd.
    serve_root = resolved_cwd if path_is_inside_or_equal(preview, resolved_cwd) else preview.parent
    return resolve_mesh_render_job(
        job,
        kind="glb",
        input_path=preview,
        root_path=serve_root,
        resolved_cwd=resolved_cwd,
        timestamp=timestamp,
        job_index=job_index,
        job_count=job_count,
    )


# The snapshot mesher: DXF text on stdin -> one GLB. Bundled into _runtime/node
# by bundle-cadgen-runtime.sh; the name is pinned by test_node_builder_bundles.
DXF_MESH_BUILDER = "dxf-mesh.mjs"


def drawing_mesh_path(source: Path, *, force: bool = False) -> Path:
    """Mesh the drawing on demand and return a GLB path for the mesh renderer.

    The `.dxf` is meshed as-is: a drawing has no derived state a door
    materializes, and a `@dxf` script is made current by running it. The mesh is
    produced by the bundled dxf-mesh.mjs one-shot into the snapshot's temp space
    — nothing is cached, matching the viewer, which parses and meshes the `.dxf`
    client-side.
    """
    import subprocess
    import tempfile

    from cadgen._internal.node_runtime import cad_node_executable, node_builder_script

    del force  # a .dxf is the product; there is nothing to regenerate here
    if not source.name.lower().endswith(".dxf"):
        raise SnapshotError(f"snapshot input must be a .dxf document: {source}")
    if not source.is_file():
        raise SnapshotError(f"snapshot input does not exist: {source}")
    dxf_path = source
    out_dir = Path(tempfile.mkdtemp(prefix="cadgen-dxf-snapshot-"))
    out_path = out_dir / f"{dxf_path.stem}.glb"
    proc = subprocess.run(
        [str(cad_node_executable()), str(node_builder_script(DXF_MESH_BUILDER)),
         "--out", str(out_path), "--name", dxf_path.stem],
        input=dxf_path.read_text(encoding="utf-8", errors="replace"),
        capture_output=True,
        text=True,
    )
    payload = {}
    for line in reversed(proc.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except ValueError:
                pass
            break
    if not payload.get("ok") or not out_path.is_file():
        detail = str(payload.get("error") or proc.stderr or f"exit {proc.returncode}").strip()
        raise SnapshotError(f"could not mesh {dxf_path.name}: {detail}")
    return out_path.resolve()


# Kind dispatch for render-job resolution. Every resolver takes the same
# signature (job plus the resolved input-kind context) and returns the common
# normalized job shape with a kind-specific ``resolved`` payload — adding a new
# input kind is one table entry, not another if-chain arm plus a copied tail.
KIND_RESOLVERS: dict[str, Callable[..., dict[str, object]]] = {
    "step": resolve_step_render_job,
    "stp": resolve_step_render_job,
    "glb": resolve_mesh_render_job,
    "stl": resolve_mesh_render_job,
    "3mf": resolve_mesh_render_job,
    "dxf": resolve_drawing_render_job,
    "urdf": resolve_robot_render_job,
    "srdf": resolve_robot_render_job,
    "sdf": resolve_robot_render_job,
}

# Every kind now resolves to itself: `.py` inputs are refused outright
# (documents-only), so there is no generator kind to expand into.
KIND_ENABLES: dict[str, tuple[str, ...]] = {}


# What each kind is called in errors, and the order a reader wants them listed
# in. Help is the verb signature's business now; this survives because a refusal
# still has to say what the door DOES take.
KIND_LABELS: dict[str, str] = {
    "step": ".step", "stp": ".stp",
    "glb": ".glb", "stl": ".stl", "3mf": ".3mf",
    "dxf": ".dxf",
    "urdf": ".urdf", "srdf": ".srdf", "sdf": ".sdf",
}

_KIND_HELP_ORDER = ("step", "stp", "3mf", "glb", "stl", "dxf", "urdf", "srdf", "sdf")


def enabled_kinds(kinds: Sequence[str]) -> frozenset[str]:
    """Expand a skill's declared kinds to the full set its resolvers accept."""
    resolved: set[str] = set()
    for kind in kinds:
        name = str(kind).strip().lower()
        if not name:
            continue
        if name not in KIND_RESOLVERS and name not in KIND_ENABLES:
            raise SnapshotError(f"unknown snapshot input kind: {kind!r}")
        resolved.update(KIND_ENABLES.get(name, (name,)))
    return frozenset(resolved)


# The cadgen command that owns each mesh format's snapshot. Named in the refusal
# because these moved: `cadgen step snapshot` rendered meshes until the door split,
# so a caller reaching the STEP door with a `.stl` is following instructions that
# were right, and "it accepts .step" alone does not tell them where it went. Safe
# to name, unlike a SKILL: every one of these ships in this same distribution.
MESH_SNAPSHOT_DOORS: dict[str, str] = {
    "stl": "cadgen stl snapshot",
    "3mf": "cadgen 3mf snapshot",
    "glb": "cadgen glb snapshot",
}


def reject_unsupported_kind(kind: str, input_path: Path, enabled: frozenset[str]) -> None:
    """Refuse an input this door does not render.

    A shared implementation makes every door CAPABLE of every format, so the gate is the
    only thing keeping `step snapshot` from quietly rendering a robot. It states what this
    door takes and stops there: naming another SKILL would assume that skill is installed,
    and skills ship independently. A sibling cadgen COMMAND is different — it is in the
    same distribution, so the mesh doors are named outright.
    """
    if kind in enabled:
        return
    label = KIND_LABELS.get(kind, f".{kind}") if kind else input_path.suffix or "that file"
    accepted = ", ".join(
        KIND_LABELS[name]
        for name in _KIND_HELP_ORDER
        if name in enabled and name in KIND_LABELS
    )
    door = MESH_SNAPSHOT_DOORS.get(kind)
    where = f" Mesh inputs have their own door: `{door} TARGET OUT`." if door else ""
    raise SnapshotError(
        f"snapshot does not render {label} inputs: {input_path}.{where} "
        f"It accepts: {accepted or '(nothing)'}."
    )


def resolve_render_job_packet(
    raw_payload: object,
    *,
    cwd: Path | None = None,
    kinds: frozenset[str] | None = None,
) -> dict[str, object]:
    single, jobs = normalize_snapshot_job_packet(raw_payload)
    # ONE timestamp for the whole packet: a multi-view run reads as one run, not
    # as N runs that happened to be close together. That is also why every
    # generated name in the packet needs a discriminator that covers the job as
    # well as the output (see generated_output_name).
    timestamp = snapshot_timestamp()
    return {
        "single": single,
        "jobs": [
            resolve_render_job(
                job,
                cwd=cwd,
                timestamp=timestamp,
                kinds=kinds,
                job_index=index,
                job_count=len(jobs),
            )
            for index, job in enumerate(jobs)
        ],
    }






















def snapshot_progress_label(packet: object) -> str:
    """The header the progress line commits: what this run is rendering."""
    jobs = packet.get("jobs") if isinstance(packet, dict) else None
    if not isinstance(jobs, list) or not jobs:
        return "snapshot"
    if len(jobs) == 1:
        return str(jobs[0].get("input") or "snapshot")
    return f"snapshot ({len(jobs)} jobs)"


async def run_snapshot_async(
    options: SnapshotOptions,
    *,
    kinds: Sequence[str],
    runtime_dir: Path | None = None,
    cwd: Path | None = None,
    stdin: Any = sys.stdin,
) -> SnapshotResult:
    """Render whatever ``options`` describes and report what was written.

    THE snapshot implementation: the CLI parses argv into ``options`` and prints
    what comes back, and the public ``<format>.snapshot()`` verbs build the same
    options object. Nothing here prints, so the two cannot report differently.
    """
    enabled = enabled_kinds(kinds)
    if options.display_specified and "step" not in enabled:
        # Display settings ARE STEP topology settings: mode, clip, exploded and edges all
        # need occurrences and CAD edges. Every other kind already rejected all four at
        # resolve time, so accepting the flag only meant erroring later or doing nothing
        # at all. renderJobContext gates job.display on the same condition.
        raise SnapshotError(
            "--display applies to STEP inputs only: its settings (mode, clip, exploded, "
            "edges) are CAD topology settings, and this door renders none"
        )
    raw_payload = load_job_from_options(options, stdin=stdin, cwd=cwd)
    # Clear the declared outputs FIRST -- before resolution, which is where a bad
    # input actually fails. The path a caller names is the path it gets, and that
    # is only safe to promise if a run that never renders leaves nothing behind for
    # the caller to read as though it had.
    clear_render_output_targets(
        normalize_snapshot_job_packet(raw_payload)[1], resolved_cwd=cwd or Path.cwd()
    )
    # Resolution is where a STEP or drawing package gets built, and on a cold model that is
    # the SLOWEST part of a snapshot -- longer than the render. It is deliberately NOT
    # wrapped in a phase of ours: that build reports its own phases through artifact_build,
    # and a second painter on the same terminal would both interleave with it and replace
    # its detail with the single word "resolving".
    packet = resolve_render_job_packet(raw_payload, cwd=cwd, kinds=enabled)
    logger = CliLogger("snapshot", verbose=False)
    with cli_progress_line(
        snapshot_progress_label(packet), logger=logger, fallback="Rendering..."
    ) as sink:
        progress = ProgressReporter(
            sinks=[sink] if sink is not None else (),
            phases=SNAPSHOT.phases,
            labels=SNAPSHOT.labels,
        )
        progress.phase(PHASE_BROWSER)
        result = await render_snapshot(
            packet, runtime_dir=browser_runtime_dir(runtime_dir), progress=progress
        )
        progress.finish()
    return result


def run_snapshot(
    options: SnapshotOptions,
    *,
    kinds: Sequence[str],
    runtime_dir: Path | None = None,
    cwd: Path | None = None,
    stdin: Any = sys.stdin,
) -> SnapshotResult:
    """:func:`run_snapshot_async` for a synchronous caller (the CLI, the verbs)."""
    return asyncio.run(
        run_snapshot_async(
            options, kinds=kinds, runtime_dir=runtime_dir, cwd=cwd, stdin=stdin
        )
    )
