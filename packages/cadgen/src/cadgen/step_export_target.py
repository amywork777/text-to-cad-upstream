"""Export one CAD model to standalone STEP/STL/3MF/GLB files.

Two callers share this module, and they offer different formats:

* The CAD Viewer's "Export model" backend — one format to an arbitrary ``--out``
  destination picked from a native Save dialog, via ``main()``/
  :func:`export_model_to_path`. Offers every :data:`FORMAT_SUFFIX` format, STEP included,
  because "Download STEP" is a Viewer menu item.
* The CAD skill workflow (``cadgen step export``) — one or more formats per run, via
  :func:`export_cad_target`. Mesh formats only (:data:`MESH_EXPORT_FORMATS`); a model's
  ``.step`` file is written by the model script (``python <model>.py``) instead.

Both accept an imported ``.step``/``.stp`` or a generated ``gen_step()`` Python source;
exports can never be stale: a model either passes the canonical freshness gate (closure
included) and exports from its store render package, or it rebuilds from source.

Mesh formats tessellate from a render package — the STORE package when the model is
current (the fast path: no generator run, no STEP load, no extraction), else a one-shot
temporary package extracted from the freshly built scene. Geometry is extracted at most
once per run and one Node invocation serializes every requested format from one
tessellation, so all formats come from identical geometry. The module writes no
beside-source artifacts; the one cache effect is that an imported model missing its
package warms the SHARED store via the ``cadgen import`` build.

Emits a single final JSON line on stdout: ``{"ok": true, "path": ..., "filename": ...}``
or ``{"ok": false, "error": ...}`` (the Node spawner parses the last stdout JSON line).
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import replace
from pathlib import Path

from cadgen.catalog import source_from_path
from cadgen.cli_logging import CliLogger
from cadgen._internal.generation import (
    EntrySpec,
    _entry_spec_from_source,
    run_script_generator,
)
from cadgen.metadata import normalize_mesh_numeric
from cadgen.step_artifact_cli import _build_entry_spec, _cad_ref_for_step, infer_entry_kind
from cadgen.step_export import export_build123d_step_file
from cadgen._internal.step_scene import (
    LoadedStepScene,
    load_step_scene,
)

# Logical format name -> conventional file suffix (informational; the caller owns `--out`).
FORMAT_SUFFIX = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "glb": ".glb"}

# Formats :func:`export_cad_target` (`cadgen step export`) offers. STEP is
# deliberately absent: a generated model writes its `.step` through
# its model script run, and an imported model's STEP is
# already the file on disk. The Viewer's Save-dialog export still offers STEP.
MESH_EXPORT_FORMATS = ("stl", "3mf", "glb")


def _apply_mesh_overrides(
    spec: EntrySpec,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
) -> EntrySpec:
    if mesh_tolerance is None and mesh_angular_tolerance is None:
        return spec
    return replace(
        spec,
        mesh_tolerance=mesh_tolerance if mesh_tolerance is not None else spec.mesh_tolerance,
        mesh_angular_tolerance=(
            mesh_angular_tolerance
            if mesh_angular_tolerance is not None
            else spec.mesh_angular_tolerance
        ),
        mesh_tolerance_explicit=mesh_tolerance is not None or spec.mesh_tolerance_explicit,
        mesh_angular_tolerance_explicit=(
            mesh_angular_tolerance is not None or spec.mesh_angular_tolerance_explicit
        ),
    )


def _resolve_spec_and_scene(
    repo_root: Path,
    step_path: Path | None,
    source_path: Path | None,
    *,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
    logger: CliLogger,
) -> tuple[EntrySpec, LoadedStepScene]:
    """Build the entry spec + an in-memory scene for the model.

    Generated model (``--source-path`` given): run ``gen_step()`` in-process to build the
    scene — generated models keep no on-disk STEP. Imported model: load the existing STEP
    and classify it via :func:`cadgen.step_artifact_cli.infer_entry_kind`.
    """
    if source_path is not None:
        source = source_from_path(source_path)
        if source is None:
            raise RuntimeError(f"Python generator is not a gen_step() CAD source: {source_path}")
        spec = _entry_spec_from_source(source)
        if spec.step_path is None:
            raise RuntimeError(f"Generator defines no STEP output: {source_path}")
        # Align the logical STEP path/name when the caller passed an explicit --step that the
        # generator does not itself resolve to (mirrors cadgen.step_artifact_cli).
        if step_path is not None and spec.step_path.resolve() != step_path.resolve():
            spec = replace(
                spec,
                cad_ref=_cad_ref_for_step(repo_root, step_path),
                display_name=step_path.stem,
                step_path=step_path,
            )
        spec = _apply_mesh_overrides(spec, mesh_tolerance, mesh_angular_tolerance)
        # An export runs the generator but writes the render package NOTHING -- its output
        # is a STEP/STL/3MF/GLB file somewhere else entirely. Claiming the writer lock here
        # made a fully-current model report `generating` with an empty bar for the whole
        # length of the export.
        scene = run_script_generator(
            spec,
            "gen_step",
            logger=logger,
            force=True,
            lock_intent="generate",
        )
        if scene is None:
            raise RuntimeError(f"Generator did not produce a STEP scene: {spec.source_ref}")
        return spec, scene

    if step_path is None:
        raise ValueError("step_path is required for imported STEP/STP models")
    if not step_path.is_file():
        raise FileNotFoundError(f"STEP file does not exist: {step_path}")
    with logger.timed(f"load STEP {step_path.name}"):
        scene = load_step_scene(step_path)
    spec = _build_entry_spec(
        repo_root,
        step_path,
        scene,
        kind=infer_entry_kind(step_path, scene),
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
    )
    return spec, scene


def _display_name_for(path: Path) -> str:
    try:
        return path.name
    except Exception:  # noqa: BLE001 - a message must never be the thing that fails
        return str(path)


# The bundled Node mesh exporter (packages/cadjs/bin/mesh-export.mjs).
MESH_EXPORT_BUILDER = "mesh-export.mjs"


def _color_hex(color) -> str | None:
    """RGBA floats (0..1) -> #rrggbb, or None when there is no usable color."""
    try:
        red, green, blue = (max(0, min(255, round(float(c) * 255))) for c in tuple(color)[:3])
    except (TypeError, ValueError):
        return None
    return f"#{red:02x}{green:02x}{blue:02x}"


def _build_export_package_from_scene(
    spec: EntrySpec,
    scene: LoadedStepScene,
    package_dir: Path,
    *,
    logger: CliLogger,
) -> None:
    """Extract the scene's exact geometry into ``package_dir`` (surf extraction
    only — no OCCT meshing). Run at most ONCE per export run: every requested
    format tessellates from this one package."""
    from cadgen.coordination.lock import exclusive
    from cadgen.coordination.paths import write_lock_path
    from cadgen._internal.component_package import build_package_from_compound

    compound = getattr(scene, "source_compound", None)
    if compound is None:
        from cadgen._internal.step_scene_mesh import scene_to_build123d_compound

        compound = scene_to_build123d_compound(scene)

    package_dir.mkdir(parents=True, exist_ok=True)
    with logger.timed("extract exact geometry"):
        # The write lock is formally required at the package mutation
        # boundary; on a private temp dir it is uncontended by construction.
        with exclusive(write_lock_path(package_dir)):
            build_package_from_compound(
                compound,
                package_dir=package_dir,
                root_name=spec.step_path.stem,
                single_component=spec.kind != "assembly",
                force=True,
            )


def _run_mesh_exporter(
    package_dir: Path,
    jobs: "list[tuple[str, Path]]",
    *,
    name: str,
    default_color: str | None,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
    logger: CliLogger,
) -> None:
    """STL/3MF/GLB through the ONE tessellation path (design/unified-tessellation.md).

    One Node invocation serves every requested format: the bundled exporter
    tessellates each component's exact surfaces once — the same watertight
    tessellator the viewport uses — then serializes per format. Boundary
    vertices lie on the exact STEP edge curves, colors carry per
    face/occurrence/part, and the bytes are deterministic. Tolerance overrides
    are the tessellator's units — chord tolerance RELATIVE to each component's
    bounding diagonal, angular tolerance in radians — not the retired OCCT
    absolute deflections.
    """
    import subprocess

    from cadgen._internal.node_runtime import cad_node_executable, node_builder_script

    argv = [
        str(cad_node_executable()),
        str(node_builder_script(MESH_EXPORT_BUILDER)),
        "--package-dir", str(package_dir),
        "--name", name,
    ]
    for fmt, out in jobs:
        argv += ["--format", fmt, "--out", str(out)]
    if mesh_tolerance is not None:
        argv += ["--chord-tolerance", repr(float(mesh_tolerance))]
    if mesh_angular_tolerance is not None:
        argv += ["--angle-tolerance", repr(float(mesh_angular_tolerance))]
    if default_color is not None:
        argv += ["--default-color", default_color]
    label = "+".join(fmt for fmt, _ in jobs)
    with logger.timed(f"tessellate + write {label}"):
        proc = subprocess.run(argv, capture_output=True, text=True)
    payload: dict = {}
    for line in reversed(proc.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except ValueError:
                pass
            break
    missing = [out for _, out in jobs if not out.is_file()]
    if not payload.get("ok") or missing:
        detail = str(payload.get("error") or proc.stderr or f"exit {proc.returncode}").strip()
        raise RuntimeError(f"mesh export failed for {label}: {detail}")


def _current_store_package(spec: EntrySpec) -> Path | None:
    """The store render package for a CURRENT model, or None.

    This is the export fast path: when the canonical freshness gate — the same
    one `python <model>.py` and the artifact CLI use, closure included — says
    the model is current, its store package holds exactly the surf geometry the
    mesh exporter consumes, and extraction is pure waste. A stale or unbuilt
    model returns None and the caller builds from source, so exports can never
    serve stale geometry (the #308 class)."""
    from cadgen.catalog import render_package_dir
    from cadgen.step_artifact_cli import _current_artifact_for_spec

    if spec.entry_path is None:
        return None
    if _current_artifact_for_spec(spec) is None:
        return None
    return render_package_dir(spec.entry_path)


def _ensure_imported_store_package(
    repo_root: Path,
    step_path: Path,
    *,
    logger: CliLogger,
) -> Path:
    """The store render package for an imported STEP, built if missing.

    An imported file's package is keyed by its content hash, so it can never be
    stale — only absent. On a miss this warms the SHARED store through the same
    build (and locks) `cadgen import` uses; nothing export-specific is stored,
    and every later export, view, or snapshot of these bytes reuses it."""
    from cadgen.catalog import render_package_dir
    from cadgen.step_artifact_cli import build_step_artifact

    package_dir = render_package_dir(step_path)
    if not (package_dir / "assembly.json").is_file():
        build_step_artifact(repo_root=repo_root, step=step_path, logger=logger)
        package_dir = render_package_dir(step_path)
    if not (package_dir / "assembly.json").is_file():
        raise RuntimeError(f"no render package for {step_path.name} after import build")
    return package_dir


def _export_scene(
    fmt: str,
    spec: EntrySpec,
    scene: LoadedStepScene,
    out: Path,
    *,
    mesh_tolerance: float | None = None,
    mesh_angular_tolerance: float | None = None,
    logger: CliLogger,
) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "step":
        # gen_step writes no STEP, so serialize the generator's in-memory compound; an
        # imported source already has a text STEP on disk, so copy it to the destination.
        source_compound = getattr(scene, "source_compound", None)
        if source_compound is not None:
            export_build123d_step_file(source_compound, out)
            return out
        if spec.step_path is not None and spec.step_path.is_file():
            # Only an IMPORTED source may be copied. A generated entry's step_path is its own
            # previous output, so copying it here rewrites <name>.step with the geometry the
            # last run produced while the caller reports outcome:built -- the failure in #308,
            # where an edited generator kept exporting the old part and validate, snapshot and
            # the Viewer all inherited it without a single error. A generated entry reaches
            # this line only when the scene arrived without source_compound (loaded from cache
            # rather than run), and the answer to that is to say so, not to copy.
            if spec.source == "generated":
                raise RuntimeError(
                    f"{spec.source_ref}: refusing to export a generated model from its own "
                    f"{_display_name_for(spec.step_path)} -- the scene carries no generator "
                    "output to serialize, so the file on disk is the PREVIOUS build. Rerun "
                    "with a fresh generation (run `cadgen cache gc` if this "
                    "persists) rather than trusting this export."
                )
            if spec.step_path.resolve() != out.resolve():
                shutil.copyfile(spec.step_path, out)
            return out
        raise RuntimeError("No STEP geometry available to export")

    raise ValueError(f"Unsupported export format: {fmt}")


def _resolve_mesh_package(
    repo_root: Path,
    step_path: Path | None,
    source_path: Path | None,
    *,
    logger: CliLogger,
) -> tuple[EntrySpec, Path | None, LoadedStepScene | None]:
    """Resolve what a mesh export tessellates from: ``(spec, package_dir, scene)``.

    A CURRENT model resolves to its store render package — no generator run, no
    STEP load, no extraction; the package already holds the exact surf geometry
    the exporter consumes. An imported model can only miss (content-hash keying
    cannot go stale), and a miss builds the shared store package via the
    ``cadgen import`` path. Only a STALE generated model still pays for source:
    its generator runs in-memory and the scene comes back for a one-shot
    temporary package (``package_dir`` None)."""
    if source_path is not None:
        source = source_from_path(source_path)
        if source is None:
            raise RuntimeError(f"Python generator is not a gen_step() CAD source: {source_path}")
        spec = _entry_spec_from_source(source)
        if spec.step_path is None:
            raise RuntimeError(f"Generator defines no STEP output: {source_path}")
        if step_path is not None and spec.step_path.resolve() != step_path.resolve():
            spec = replace(
                spec,
                cad_ref=_cad_ref_for_step(repo_root, step_path),
                display_name=step_path.stem,
                step_path=step_path,
            )
        package_dir = _current_store_package(spec)
        if package_dir is not None:
            logger.debug(f"reusing current render package: {package_dir.name}")
            return spec, package_dir, None
        # See _resolve_spec_and_scene on lock_intent: an export must not claim
        # the writer lock, or a fully-current model reports `generating`.
        scene = run_script_generator(
            spec,
            "gen_step",
            logger=logger,
            force=True,
            lock_intent="generate",
        )
        if scene is None:
            raise RuntimeError(f"Generator did not produce a STEP scene: {spec.source_ref}")
        return spec, None, scene

    if step_path is None:
        raise ValueError("step_path is required for imported STEP/STP models")
    if not step_path.is_file():
        raise FileNotFoundError(f"STEP file does not exist: {step_path}")
    from cadgen.step_artifact_cli import _relative_to_base

    spec = EntrySpec(
        source_ref=_relative_to_base(repo_root, step_path),
        cad_ref=_cad_ref_for_step(repo_root, step_path),
        kind="part",
        source_path=step_path,
        display_name=step_path.stem,
        source="imported",
        step_path=step_path,
    )
    package_dir = _ensure_imported_store_package(repo_root, step_path, logger=logger)
    return spec, package_dir, None


def _export_mesh_jobs(
    spec: EntrySpec,
    package_dir: Path | None,
    scene: LoadedStepScene | None,
    jobs: "list[tuple[str, Path]]",
    *,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
    logger: CliLogger,
) -> None:
    """Export every requested mesh format from ONE package: the store package
    when the model resolved current, else a one-shot temp package extracted
    from the scene. OCCT meshes nothing on either path (the GLB is Y-up glTF
    for external tools, matching the retired native writer's convention)."""
    for out in {out for _, out in jobs}:
        out.parent.mkdir(parents=True, exist_ok=True)
    name = spec.step_path.stem
    default_color = _color_hex(spec.color)
    if package_dir is not None:
        _run_mesh_exporter(
            package_dir,
            jobs,
            name=name,
            default_color=default_color,
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            logger=logger,
        )
        return
    import tempfile

    if scene is None:
        raise RuntimeError(f"no render package and no scene to extract for {name}")
    with tempfile.TemporaryDirectory(prefix="cadgen-mesh-export-") as tmp:
        temp_package = Path(tmp) / "package"
        _build_export_package_from_scene(spec, scene, temp_package, logger=logger)
        _run_mesh_exporter(
            temp_package,
            jobs,
            name=name,
            default_color=default_color,
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            logger=logger,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cadgen.step_export_target",
        description="Export one CAD model to STEP/3MF/STL/GLB at an explicit destination path.",
    )
    parser.add_argument("--repo-root", required=True, help="Repository/workspace root for relative metadata.")
    parser.add_argument("--step", required=True, help="Logical STEP path (generated) or on-disk STEP/STP (imported).")
    parser.add_argument("--source-path", help="Python gen_step() generator (.step.py) for a generated model.")
    parser.add_argument("--format", required=True, choices=tuple(FORMAT_SUFFIX), help="Output format.")
    parser.add_argument("--out", required=True, help="Destination file path for the exported model.")
    parser.add_argument(
        "--mesh-tolerance",
        type=float,
        help="Chord tolerance RELATIVE to each component's bounding diagonal (default 1.5e-3).",
    )
    parser.add_argument(
        "--mesh-angular-tolerance",
        type=float,
        help="Max normal spread across a triangle edge, radians (default 0.35).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed timing on stderr.")
    return parser


def export_model_to_path(
    *,
    repo_root: Path,
    step: Path,
    fmt: str,
    out: Path,
    source_path: Path | None = None,
    mesh_tolerance: float | None = None,
    mesh_angular_tolerance: float | None = None,
    logger: CliLogger | None = None,
) -> dict[str, object]:
    """Export one CAD model to STEP/STL/3MF/GLB at ``out`` and RETURN
    {ok, path, filename, format}. Single source of truth, callable in-process by a
    warm-OCCT worker AND wrapped by main(); it RAISES on error so callers map their
    own protocol (the CLI shell keeps the {ok:false,error} JSON envelope)."""
    if logger is None:
        logger = CliLogger("step-export", verbose=False)
    repo_root = Path(repo_root).expanduser().resolve()
    step_path = Path(step).expanduser().resolve()
    source_path = Path(source_path).expanduser().resolve() if source_path else None
    out = Path(out).expanduser().resolve()
    mesh_tolerance = normalize_mesh_numeric(mesh_tolerance, field_name="mesh_tolerance")
    mesh_angular_tolerance = normalize_mesh_numeric(mesh_angular_tolerance, field_name="mesh_angular_tolerance")
    if fmt in MESH_EXPORT_FORMATS:
        spec, package_dir, scene = _resolve_mesh_package(
            repo_root, step_path, source_path, logger=logger
        )
        _export_mesh_jobs(
            spec,
            package_dir,
            scene,
            [(fmt, out)],
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            logger=logger,
        )
        return {"ok": True, "path": str(out), "filename": out.name, "format": fmt}
    spec, scene = _resolve_spec_and_scene(
        repo_root,
        step_path,
        source_path,
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
        logger=logger,
    )
    written = _export_scene(
        fmt,
        spec,
        scene,
        out,
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
        logger=logger,
    )
    return {"ok": True, "path": str(written), "filename": written.name, "format": fmt}


def _is_step_suffix(path: Path) -> bool:
    return path.suffix.lower() in {".step", ".stp"}


def _resolve_export_output(
    fmt: str,
    raw: str | Path | None,
    *,
    logical_step: Path,
) -> Path:
    """Resolve one requested mesh export output. ``None`` means the default sibling path
    (``<name>.<ext>`` beside the logical STEP); a relative path resolves beside the
    logical STEP, matching the historical sidecar-path semantics."""
    if raw is None:
        return logical_step.with_suffix(FORMAT_SUFFIX[fmt]).resolve()
    out = Path(raw).expanduser()
    if not out.is_absolute():
        out = logical_step.parent / out
    out = out.resolve()
    if out.suffix.lower() != FORMAT_SUFFIX[fmt]:
        raise ValueError(f"--{fmt} output must end with {FORMAT_SUFFIX[fmt]}: {raw}")
    return out


def export_cad_target(
    target: str | Path,
    outputs: "list[tuple[str, str | Path | None]]",
    *,
    repo_root: Path | None = None,
    mesh_tolerance: float | None = None,
    mesh_angular_tolerance: float | None = None,
    verbose: bool = False,
    logger: CliLogger | None = None,
) -> dict[str, object]:
    """Export one CAD model — an imported ``.step``/``.stp`` or a generated Python
    ``gen_step()`` source — to one or more of :data:`MESH_EXPORT_FORMATS` in a single run.

    A CURRENT model exports straight from its store render package — no generator run,
    no STEP load, no extraction. Geometry is extracted at most ONCE per run in every
    case, and one Node invocation serializes all requested formats from one
    tessellation, so every format comes from identical geometry. ``outputs`` pairs a
    format name with an explicit output path or ``None`` for the default sibling path.
    Writes no ``.step`` and no beside-source artifacts; an imported model missing its
    render package warms the SHARED store through the ``cadgen import`` build (content
    keyed — the same package every later view or export of those bytes reuses)."""
    if logger is None:
        logger = CliLogger("cadgen step export", verbose=verbose)
    if not outputs:
        raise ValueError("No export formats requested")
    for fmt, _ in outputs:
        if fmt not in MESH_EXPORT_FORMATS:
            raise ValueError(
                f"Unsupported export format: {fmt}. "
                f"Supported formats: {', '.join(MESH_EXPORT_FORMATS)}."
            )
    repo_root = Path(repo_root).expanduser().resolve() if repo_root else Path.cwd()
    target_path = Path(target).expanduser().resolve()
    mesh_tolerance = normalize_mesh_numeric(mesh_tolerance, field_name="mesh_tolerance")
    mesh_angular_tolerance = normalize_mesh_numeric(
        mesh_angular_tolerance, field_name="mesh_angular_tolerance"
    )

    if _is_step_suffix(target_path):
        step_path: Path | None = target_path
        source_path: Path | None = None
    elif target_path.suffix.lower() == ".py":
        step_path = None
        source_path = target_path
    else:
        raise ValueError(
            f"Export target must be a .step/.stp file or a gen_step() Python source: {target}"
        )

    spec, package_dir, scene = _resolve_mesh_package(
        repo_root,
        step_path,
        source_path,
        logger=logger,
    )

    resolved: list[tuple[str, Path]] = []
    seen: dict[Path, str] = {}
    for fmt, raw in outputs:
        out = _resolve_export_output(fmt, raw, logical_step=spec.step_path)
        if out in seen:
            raise ValueError(f"--{seen[out]} and --{fmt} resolve to the same output path: {out}")
        seen[out] = fmt
        resolved.append((fmt, out))

    _export_mesh_jobs(
        spec,
        package_dir,
        scene,
        resolved,
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
        logger=logger,
    )
    files = [{"format": fmt, "path": str(out)} for fmt, out in resolved]
    logger.total()
    return {"ok": True, "files": files}


def run_cli_payload(argv: list[str] | None = None) -> dict[str, object]:
    """Parse CLI ``argv`` and run :func:`export_model_to_path`, RETURNING its
    ``{ok:true,...}`` payload (no printing). RAISES on error — callers own the error
    envelope. The in-process primitive shared by ``main()`` and the CAD Viewer's warm
    worker."""
    args = build_parser().parse_args(argv)
    logger = CliLogger("step-export", verbose=bool(args.verbose))
    payload = export_model_to_path(
        repo_root=Path(args.repo_root),
        step=Path(args.step),
        fmt=args.format,
        out=Path(args.out),
        source_path=Path(args.source_path) if args.source_path else None,
        mesh_tolerance=args.mesh_tolerance,
        mesh_angular_tolerance=args.mesh_angular_tolerance,
        logger=logger,
    )
    logger.total()
    return payload


def main(argv: list[str] | None = None) -> int:
    try:
        payload = run_cli_payload(argv)
    except Exception as exc:  # noqa: BLE001 — surface a clean JSON error to the CLI caller.
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
