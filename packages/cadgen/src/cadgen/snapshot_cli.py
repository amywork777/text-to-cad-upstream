"""The snapshot CLI itself: arguments, job resolution, and the run loop.

Shared because six skills render. Each one is a declaration -- which input kinds it
accepts, and where its bundled browser runtime lives -- over this one implementation:

    run_snapshot_cli(argv, kinds=("step", "stp", "3mf", "glb", "stl"), runtime_dir=...)

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
import dataclasses
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
from cadgen.cli_progress import cli_progress_line
from cadgen.results import SnapshotResult
from cadgen._internal.cli_from_function import emit
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
    positive_integer,
    render_resolved_job_packet,
    render_snapshot,
    resolve_mesh_render_job,
    has_step_parameter_render_values,
    resolve_output_size,
    selection_filter_values,
    selection_value_list,
    resolve_snapshot_route_file,
    route_file,
    snapshot_timestamp,
    reject_animated_step_parameters,
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
    focus: list[str] | None = None
    hide: list[str] | None = None
    view_labels: bool = False
    debug: bool = False
    json: bool = False
    help: bool = False


# Bookkeeping, not options: `<name>_specified` records whether the user passed
# the flag at all, and `help` is argparse's own.
_NON_OPTION_FIELDS = frozenset({"help"})


def option_names() -> tuple[str, ...]:
    """The option surface every snapshot command carries, one name per flag.

    Snapshot is an ADAPTER in the format-doors schema (design/format-doors.md):
    its camera/theme/display surface is exactly what makes it underivable from a
    verb signature, so there is no generated parser to read the surface off.
    This is what the signature-sync policy test checks its declaration against
    instead — :class:`SnapshotOptions` is the surface, one field per flag.
    """
    return tuple(
        field.name
        for field in dataclasses.fields(SnapshotOptions)
        if field.name not in _NON_OPTION_FIELDS and not field.name.endswith("_specified")
    )






# What each kind can do, for generated help. A skill's --help then describes THAT skill
# rather than every format the shared implementation happens to carry -- the old single
# blob documented STEP parameters and robot joint poses to every reader regardless of
# which skill they were in.
KIND_BLURBS: dict[str, str] = {
    # `gen_step()` is retired; a model is a @step-decorated function in a .py.
    "step": "a STEP document, or the @step model script that builds one",
    "stp": "a STEP model",
    "glb": "a mesh, rendered shaded solid",
    "stl": "a mesh, rendered shaded solid",
    "3mf": "a mesh, rendered shaded solid",
    "dxf": "a drawing, rendered as its 3D flat pattern",
    "urdf": "a robot description, assembled from its link meshes",
    "srdf": "a robot description, assembled from its link meshes",
    "sdf": "a robot description, assembled from its link meshes",
}

KIND_MODES: dict[str, frozenset[str]] = {
    "step": frozenset(STEP_SUPPORTED_RENDER_MODES),
    "stp": frozenset(STEP_SUPPORTED_RENDER_MODES),
    "glb": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "stl": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "3mf": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "dxf": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "urdf": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "srdf": frozenset(MESH_SUPPORTED_RENDER_MODES),
    "sdf": frozenset(MESH_SUPPORTED_RENDER_MODES),
}

_MODE_BLURBS = {
    "view": "one still image per output (default)",
    "section": "cutaway sweep",
    "list": "part occurrence refs as JSON; writes no files",
}

_KIND_HELP_ORDER = ("step", "stp", "3mf", "glb", "stl", "dxf", "urdf", "srdf", "sdf")


def help_text(*, kinds: frozenset[str] | None = None, prog: str = "cadgen snapshot") -> str:
    """The help for THIS skill: only the inputs, modes and options it actually has."""
    enabled = frozenset(KIND_RESOLVERS) | {"python"} if kinds is None else kinds
    listed = [k for k in _KIND_HELP_ORDER if k in enabled]
    has_step = "step" in enabled
    modes = sorted({m for k in listed for m in KIND_MODES.get(k, frozenset())})
    sample = KIND_LABELS.get(listed[0], "model").split(" / ")[0] if listed else "model"

    lines = [
        "Usage:",
        # `prog` is already the whole command (`cadgen stl snapshot`), so it does
        # not take a `python` in front of it; the line used to print one, which
        # made the first thing a reader saw the one thing they could not run.
        f"  {prog} --input models/part{sample} --output /tmp/part.png",
        f"  {prog} --job render-job.json          # or --job - to read stdin",
        "",
        "Inputs",
    ]
    for kind in listed:
        lines.append(f"  {KIND_LABELS[kind]:<18}{KIND_BLURBS.get(kind, '')}")
    lines += [
        "",
        "Modes (--mode)",
        *[f"  {mode:<18}{_MODE_BLURBS[mode]}" for mode in modes if mode in _MODE_BLURBS],
        "",
        "Options",
        "  --input/-i PATH   the model to render",
        "  --output/-o PATH  a file path is written EXACTLY there (a relative one against the",
        "                    current directory) and is cleared first, so a failed render leaves",
        "                    no file at all; a directory gets a generated timestamped name",
        "                    inside it",
        "  --job PATH        one render job, an array of them, or { \"jobs\": [...] }; - reads stdin",
        "  --camera VALUE    a preset, an azimuth:elevation pair, or JSON with preset/position/target/up/zoom",
        "  --theme VALUE     see Theme below",
        *(["  --display VALUE   see Display below"] if has_step else []),
        "  --size-profile ID simple, diagnostic, labeled, assembly, presentation, contact-sheet",
        "  --width/--height  pixels, overriding the size profile",
        "  --json            print the render result as JSON on stdout",
    ]
    if has_step:
        lines += [
            "  --focus/--hide REF  selector refs such as #o1.2; repeat the flag or list several refs",
            "  --params JSON     pose parameter values (the model's @step(pose=...) block)",
            "  --view-labels     burn the camera/view label into the image",
            "  --debug           add a debug section to --json reporting how the artifact resolved",
        ]
    lines += [
        "",
        "Theme (--theme)  everything under the viewer's Theme tab, in one option.",
        "  A saved theme name, inline JSON theme settings, or a path to a theme JSON file.",
        f"  Default: {DEFAULT_RENDER_THEME_ID}. Projection is a theme trait (the workbench themes are",
        "  orthographic; the presentation stage themes are perspective).",
    ]
    if has_step:
        lines += [
            "",
            "Display (--display)  everything under the viewer's Display tab, in one option.",
            "  A mode name (solid, rendered, transparent, unshaded, wireframe, hidden_edges,",
            "  hidden_lines_removed), inline JSON display settings, or a JSON file path.",
            "  Edge styling and the exploded view live here, e.g.",
            '  {"mode":"rendered","exploded":{"amount":0.7},"edges":{"color":"#132232"}}.',
            "  Exploded is one 0..1 slider; the layout is automatic.",
        ]
    lines += [
        "",
        # This used to say every output was saved with a timestamp before the
        # extension. It has not been true since the declared path became the
        # written path, and it contradicted --output six lines above it.
        "The path you name is the path you get. Only a DIRECTORY output gets a",
        "generated name, timestamped, and the `saved snapshot:` line reports it.",
        "",
    ]
    return "\n".join(lines)


def parse_required_value(argv: Sequence[str], index: int, flag: str) -> str:
    try:
        value = argv[index + 1]
    except IndexError as exc:
        raise SnapshotError(f"{flag} requires a value") from exc
    if not value or value.startswith("--"):
        raise SnapshotError(f"{flag} requires a value")
    return value


def parse_required_values(argv: Sequence[str], index: int, flag: str) -> tuple[list[str], int]:
    values: list[str] = []
    cursor = index + 1
    while cursor < len(argv):
        value = argv[cursor]
        if value.startswith("--"):
            break
        if value:
            values.append(value)
        cursor += 1
    if not values:
        raise SnapshotError(f"{flag} requires at least one value")
    return values, cursor - index - 1


def parse_snapshot_args(argv: Sequence[str]) -> SnapshotOptions:
    if argv and argv[0] == "daemon":
        raise SnapshotError("snapshot daemon commands have been removed; use a batch --job snapshot instead")

    options = SnapshotOptions()
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"--help", "-h"}:
            options.help = True
        elif arg == "--json":
            options.json = True
        elif arg == "--no-daemon":
            raise SnapshotError("--no-daemon has been removed; snapshot no longer uses a daemon")
        elif arg == "--socket" or arg.startswith("--socket="):
            raise SnapshotError("--socket has been removed; snapshot no longer uses a daemon")
        elif arg == "--view-labels":
            options.view_labels = True
        elif arg == "--debug":
            options.debug = True
        elif arg == "--job":
            options.job = parse_required_value(argv, index, arg)
            index += 1
        elif arg.startswith("--job="):
            options.job = arg[len("--job=") :]
        elif arg in {"--input", "-i"}:
            # `-i` is advertised in the help beside `-o`, so it has to parse. It did not,
            # which made the documented spelling of the CLI's most-used flag an error.
            options.input = parse_required_value(argv, index, arg)
            index += 1
        elif arg.startswith("--input="):
            options.input = arg[len("--input=") :]
        elif arg in {"--output", "-o"}:
            options.output = parse_required_value(argv, index, arg)
            index += 1
        elif arg.startswith("--output="):
            options.output = arg[len("--output=") :]
        elif arg == "--mode":
            options.mode = parse_required_value(argv, index, arg)
            index += 1
        elif arg.startswith("--mode="):
            options.mode = arg[len("--mode=") :]
        elif arg == "--theme":
            options.theme = parse_required_value(argv, index, arg)
            options.theme_specified = True
            index += 1
        elif arg.startswith("--theme="):
            options.theme = arg[len("--theme=") :]
            options.theme_specified = True
        elif arg == "--display":
            options.display = parse_required_value(argv, index, arg)
            options.display_specified = True
            index += 1
        elif arg.startswith("--display="):
            options.display = arg[len("--display=") :]
            options.display_specified = True
        elif arg == "--params":
            options.params = parse_required_value(argv, index, arg)
            options.params_specified = True
            index += 1
        elif arg.startswith("--params="):
            options.params = arg[len("--params=") :]
            options.params_specified = True
        elif arg == "--params-path" or arg.startswith("--params-path="):
            raise SnapshotError(
                "--params-path is retired: pose data is declared on the model "
                "(@step(pose=cadgen.pose(...))) and read from the package descriptor; "
                "see skills/cad/references/kinematics.md"
            )
        elif arg == "--focus":
            values, consumed = parse_required_values(argv, index, arg)
            options.focus = [*(options.focus or []), *values]
            index += consumed
        elif arg.startswith("--focus="):
            value = arg[len("--focus=") :]
            if not value:
                raise SnapshotError("--focus requires at least one value")
            options.focus = [*(options.focus or []), value]
        elif arg == "--hide":
            values, consumed = parse_required_values(argv, index, arg)
            options.hide = [*(options.hide or []), *values]
            index += consumed
        elif arg.startswith("--hide="):
            value = arg[len("--hide=") :]
            if not value:
                raise SnapshotError("--hide requires at least one value")
            options.hide = [*(options.hide or []), value]
        elif arg == "--size-profile":
            options.size_profile = parse_required_value(argv, index, arg)
            index += 1
        elif arg.startswith("--size-profile="):
            options.size_profile = arg[len("--size-profile=") :]
        elif arg == "--camera":
            options.camera = parse_required_value(argv, index, arg)
            options.camera_specified = True
            index += 1
        elif arg.startswith("--camera="):
            options.camera = arg[len("--camera=") :]
            options.camera_specified = True
        elif arg == "--width":
            options.width = positive_integer(parse_required_value(argv, index, arg), arg)
            index += 1
        elif arg.startswith("--width="):
            options.width = positive_integer(arg[len("--width=") :], "--width")
        elif arg == "--height":
            options.height = positive_integer(parse_required_value(argv, index, arg), arg)
            index += 1
        elif arg.startswith("--height="):
            options.height = positive_integer(arg[len("--height=") :], "--height")
        else:
            raise SnapshotError(f"Unknown argument: {arg}")
        index += 1
    if options.focus and options.hide:
        raise SnapshotError("--focus and --hide cannot be used in the same snapshot command")
    return options








def parse_params_option(raw_params: object) -> dict[str, object]:
    # Already an object when it came from a `<format>.snapshot(params={...})`
    # call rather than argv; see the note above parse_camera_option.
    if is_plain_object(raw_params):
        return dict(raw_params)
    parsed = load_json_text(str(raw_params or ""), "--params")
    if not is_plain_object(parsed):
        raise SnapshotError("--params must be a STEP parameter JSON object")
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
        next_job["stepParameters"] = parse_params_option(options.params)
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
        raise SnapshotError("render requires --job, stdin JSON, or --input")
    if options.mode != "list" and not options.output:
        raise SnapshotError("render shortcut requires --output for non-list modes")

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
        job["stepParameters"] = parse_params_option(options.params)
    if options.debug:
        job["debug"] = True
    merge_focus_hide_options(job, options)
    return job




def input_kind(file_path: Path) -> str:
    # Compound suffixes first: `Path.suffix` sees only the last one, so `<name>.dxf.py`
    # would read as a STEP generator.
    name = file_path.name.lower()
    if name.endswith(".dxf.py"):
        return "dxf"
    suffix = file_path.suffix.lower()
    if suffix == ".step":
        return "step"
    if suffix == ".stp":
        return "stp"
    if suffix == ".dxf":
        return "dxf"
    if suffix == ".py":
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


def logical_step_path_for_python_source(source_path: Path) -> Path:
    # `<name>.step.py` -> `<name>.step` (strip only `.py`; the stem already ends in `.step`).
    name = source_path.name
    if name.endswith(".step.py"):
        return source_path.with_name(name[: -len(".py")])
    return source_path.with_suffix(".step")


def same_stem_python_generator_path(step_path: Path) -> Path | None:
    # The generator for `<name>.step` is `<name>.step.py` (append `.py` to the full step filename).
    candidate = step_path.with_name(step_path.name + ".py")
    try:
        return candidate if re.search(r"\bgen_step\s*\(", candidate.read_text(encoding="utf-8")) else None
    except OSError:
        return None


def resolve_input_path(raw_input: object, *, cwd: Path) -> Path:
    input_text = str(raw_input or "").strip()
    if not input_text:
        raise SnapshotError("render job is missing input")
    raw_path = Path(input_text)
    selected = raw_path.resolve() if raw_path.is_absolute() else (cwd / raw_path).resolve()
    if not selected.exists():
        if selected.suffix.lower() in {".step", ".stp"} and same_stem_python_generator_path(selected):
            return selected
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
        # A job input naming the .py generator must keep using the generator
        # entry even when a same-stem exported .step exists beside it.
        explicit_python=input_path.suffix.lower() == ".py",
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


def validate_occurrence_selector(selector: str, *, selector_index: lookup.SelectorIndex | None, source_label: str) -> None:
    if selector_index is None:
        return
    if selector not in selector_index.occurrence_by_id:
        raise SnapshotError(f"{source_label} references unknown part/subassembly occurrence selector: {selector}")


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
    validate_occurrence_selector(parsed.canonical, selector_index=selector_index, source_label=source_label)
    return [parsed.canonical]


def normalize_selection_filter_values(
    value: object,
    *,
    expected_cad_path: str,
    selector_index: lookup.SelectorIndex | None,
    source_label: str,
) -> list[str]:
    selectors: list[str] = []
    for raw_value in selection_value_list(value):
        selectors.extend(
            normalize_selection_selector(
                raw_value,
                selector_index=selector_index,
                source_label=source_label,
                expected_cad_path=expected_cad_path,
            )
        )
    return selectors


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
    if has_step_parameter_render_values(job.get("stepParameters")):
        raise SnapshotError(
            f"stepParameters require a STEP model; pose a {label} robot with jointValues"
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
        raise SnapshotError("render jobs use stepParameters; params is reserved for shortcut --params parsing")
    if "paramsPath" in job or "stepParametersPath" in job:
        raise SnapshotError(
            "parameter sidecar paths are retired: pose data is declared on the model "
            "(@step(pose=cadgen.pose(...))) and read from the package descriptor; "
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
    # The gate is on the AUTHORED kind, before `.py` collapses into `step`: a skill that
    # does not accept STEP should reject `part.step.py` as a STEP generator, not report a
    # confusing failure about the `.step` path it was rewritten to.
    if kinds is not None:
        reject_unsupported_kind(kind, input_path, kinds)
    if kind == "python":
        input_path = logical_step_path_for_python_source(input_path)
        root_path = input_path.parent.resolve()
        kind = "step"
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
    has_param_render = has_step_parameter_render_values(job.get("stepParameters"))
    reject_animated_step_parameters(job.get("stepParameters"))
    # Parameter values drive the model's declarative pose block (descriptor
    # `pose`, authored via @step(pose=...)). The retired sidecar-path key is
    # rejected upfront in job normalization with a teaching error.
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
        raise SnapshotError("stepParameters support only view mode; set display.mode for display-style changes")

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
        # evaluator (cadjs kinematicsModule).
        resolved["stepParameterUrl"] = asset_url_for_path(source_sidecar_path(source_path), root_path)
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
    if has_step_parameter_render_values(job.get("stepParameters")):
        raise SnapshotError(
            "stepParameters require a STEP model; a drawing is parameterized by its gen_dxf() source"
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


def generate_dxf_for_snapshot(source: Path, *, force: bool = False) -> Path:
    """Module-level indirection over the drawing generator.

    Deferred so importing this CLI does not drag ezdxf in for a skill that never
    renders a drawing, and module-level so it is one patchable seam. Returns the
    generated sibling `.dxf` path."""
    from cadgen._internal.generation import generate_dxf_targets

    generate_dxf_targets([str(source)], force=force)
    sibling = source.with_name(source.name[: -len(".py")])
    if not sibling.is_file():
        raise SnapshotError(f"gen did not write {sibling}")
    return sibling


def drawing_mesh_path(source: Path, *, force: bool = False) -> Path:
    """Mesh the drawing on demand and return a GLB path for the mesh renderer.

    A `.dxf.py` generator is made current first (the ordinary gen no-op gate);
    an imported `.dxf` is meshed as-is. The mesh is produced by the bundled
    dxf-mesh.mjs one-shot into the snapshot's temp space — nothing is cached,
    matching the viewer, which parses and meshes the `.dxf` client-side.
    """
    import subprocess
    import tempfile

    from cadgen._internal.node_runtime import cad_node_executable, node_builder_script

    if not source.name.lower().endswith((".dxf", ".py")):
        raise SnapshotError(
            f"snapshot input must be a .dxf file or a gen_dxf() Python source: {source}"
        )
    if not source.is_file():
        raise SnapshotError(f"snapshot input does not exist: {source}")
    dxf_path = source
    if source.name.lower().endswith(".py"):
        dxf_path = generate_dxf_for_snapshot(source, force=force)
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

# `python` is not a kind of its own: a `.py` input is a generator, and which kind it
# resolves to depends on the generator (a `.step.py` is a STEP entry). Enabling `step`
# therefore enables its generator, which is why the two are listed together here rather
# than a skill having to remember to name both.
KIND_ENABLES: dict[str, tuple[str, ...]] = {"step": ("step", "python")}


# What each kind is called in help and in errors, in the order a reader wants them.
KIND_LABELS: dict[str, str] = {
    "step": ".step / .step.py", "stp": ".stp", "python": ".step.py",
    "glb": ".glb", "stl": ".stl", "3mf": ".3mf",
    "dxf": ".dxf / .dxf.py",
    "urdf": ".urdf", "srdf": ".srdf", "sdf": ".sdf",
}


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
    where = f" Mesh inputs have their own door: `{door} --input <file> --output <path>`." if door else ""
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


def run_snapshot_cli(
    argv: Sequence[str],
    *,
    kinds: Sequence[str],
    runtime_dir: Path | None = None,
    prog: str = "cadgen snapshot",
    cwd: Path | None = None,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
    stdin: Any = sys.stdin,
) -> int:
    """Run one snapshot door's CLI. ``kinds`` is what that door accepts.

    The whole of a door's snapshot entrypoint is a call to this: everything else about
    rendering -- arguments, job schema, theme, display, the browser -- is identical across
    doors by construction rather than by several copies agreeing.

    Printing is `cli_from_function.emit`, the same serializer every generated
    `cadgen <format> <verb>` command prints through: one compact JSON line of the
    Result under `--json`, its human lines otherwise, and `{"ok":false,"error":...}`
    + exit 1 for a failure. Snapshot used to hand-roll all three.
    """
    try:
        options = parse_snapshot_args(argv)
        if options.help:
            stdout.write(help_text(kinds=enabled_kinds(kinds), prog=prog))
            return 0
    except SnapshotError as exc:
        # Argument errors precede the Result contract -- there is no result to
        # serialize -- so they stay a plain line on stderr.
        stderr.write(f"{exc}\n")
        return 1
    return emit(
        lambda: run_snapshot(
            options, kinds=kinds, runtime_dir=runtime_dir, cwd=cwd, stdin=stdin
        ),
        prog=prog,
        as_json=options.json,
        stdout=stdout,
        stderr=stderr,
    )

