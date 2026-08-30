"""The library-first authoring surface: ``@step`` and ``@dxf``
(design/library-first-generation.md).

A CAD model is a plain Python script; the decorator is the entrypoint::

    from cadgen import build123d as bd
    from cadgen import step

    @step()                      # out= defaults to <stem>.step beside the
    def bracket(width: float = 10.0):    # script; pass out="..." to relocate
        return bd.Box(width, 10, 10)

Semantics (settled in the design doc):

- **Decoration-time execution.** When the defining module is ``__main__``,
  decoration runs the full existing pipeline right here — freshness gate,
  locks/progress, incremental package build, ``.step`` assembly — via the warm
  daemon when available, in-process otherwise. Everything the model needs must
  therefore be defined ABOVE the decorated function.
- **Import never builds.** Importing a model module only registers.
- **Transparent callable.** Calling the decorated function returns the shape
  (or drawing) and nothing else — composition imports the module and calls it.
- **One model per file.** Entry identity (refs, packages, closures) is keyed
  by the source file everywhere in the pipeline, so a file defines exactly one
  ``@step`` or ``@dxf`` model. (Supersedes the design doc's "multiple steps
  build in file order" sketch; recorded in its execution log.)
- **A direct run ends the process** (``SystemExit`` with the pipeline's exit
  code) whether it dispatched warm or ran in-process — the two paths must not
  disagree about whether trailing module code executes.

Per-run flags ride ``sys.argv``: ``--force``, ``--verbose``, ``--json``,
``-o/--output``, ``--mesh-tolerance``, ``--mesh-angular-tolerance``,
``--lock-timeout``. Durable configuration lives in the decorator call.

This module must import light (no OCP): the whole point is that a model
script's body costs ~0.2s before the gate and the warm handoff run.
"""

from __future__ import annotations

import inspect
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cadgen.kinematics import (
    KinematicsDef,
    normalize_bake_pose,
    normalize_kinematics,
)
from cadgen.metadata import (
    MeshExportDecl,
    renamed_write_kwarg_message,
    resolve_model_output_path,
)

__all__ = [
    "step",
    "dxf",
    "stl",
    "glb",
    "threemf",
    "ModelDef",
    "registered_model",
    "registered_models",
]


@dataclass(frozen=True)
class ModelDef:
    """One registered model: the decorated function plus its durable options."""

    func: Callable[..., Any]
    fmt: str  # "step" | "dxf"
    script_path: Path
    out: str | None
    kind: str | None
    mesh_tolerance: float | None
    mesh_angular_tolerance: float | None
    # Typed mates (kinematics= dict, validated at decoration); axis refs
    # resolve at build and the block lands in the model's sidecar. STEP only.
    kinematics: KinematicsDef | None = None
    # pose= bake selector resolved to {dof: value}: the artifact is WRITTEN at
    # this configuration (and is therefore its own q=0). None = authored rest.
    bake_pose: dict[str, float] | None = None
    # Script-relative path of the .anim.js choreography module; its TEXT is
    # copied into the sidecar at build (never a path in generated files).
    animation: str | None = None
    # Declared mesh serializations (@stl/@glb/@threemf). STEP models only.
    mesh_exports: tuple[MeshExportDecl, ...] = ()

    @property
    def output_path(self) -> Path:
        return resolve_model_output_path(self.script_path, fmt=self.fmt, explicit_out=self.out)


# Keyed by resolved script path. One model per file is a hard rule (see module
# docstring), so the value is a single ModelDef, not a list.
_REGISTRY: dict[Path, ModelDef] = {}


def registered_model(script_path: Path) -> ModelDef | None:
    return _REGISTRY.get(Path(script_path).resolve())


def registered_models() -> dict[Path, ModelDef]:
    return dict(_REGISTRY)


def _legacy_naming_error(script_path: Path) -> RuntimeError:
    from cadgen._internal.legacy_generators import legacy_naming_message

    return RuntimeError(legacy_naming_message(script_path))


def _script_path_of(func: Callable[..., Any]) -> Path:
    source = inspect.getsourcefile(func) or func.__code__.co_filename
    return Path(source).resolve()


def _validate_signature(func: Callable[..., Any], *, fmt: str) -> None:
    signature = inspect.signature(func)
    for parameter in signature.parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise TypeError(
                f"@{fmt} model {func.__name__}() must not accept variadic arguments"
            )
        if parameter.default is parameter.empty:
            raise TypeError(
                f"@{fmt} model {func.__name__}() parameters must all have defaults — "
                "the pipeline calls it with no arguments"
            )


def _register(defn: ModelDef) -> None:
    existing = _REGISTRY.get(defn.script_path)
    if existing is not None and existing.func.__qualname__ != defn.func.__qualname__:
        raise RuntimeError(
            f"{defn.script_path.name} defines more than one CAD model "
            f"({existing.func.__name__} and {defn.func.__name__}); a model file "
            "defines exactly one @step or @dxf entry — split it into two files"
        )
    _REGISTRY[defn.script_path] = defn


def _reject_renamed_kwargs(deco_name: str, kwargs: dict[str, Any]) -> None:
    """``write=`` is gone (hard cutover). Name its replacement rather than
    letting a stale model script die on a bare TypeError."""
    if "write" in kwargs:
        raise TypeError(renamed_write_kwarg_message(deco_name, kwargs["write"]))
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"@{deco_name} got an unexpected keyword argument: {unexpected}")


def _normalize_animation(animation: object, *, fmt: str) -> str | None:
    if animation is None:
        return None
    text = str(animation).strip()
    if not text.lower().endswith(".js"):
        raise ValueError(
            f"@{fmt} animation must name a .js module beside the script "
            f"(e.g. animation='arm.anim.js'), got {animation!r}"
        )
    return text


def _decorator(
    fmt: str,
    *,
    out: str | None,
    kind: str | None,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
    kinematics: object = None,
    pose: object = None,
    animation: object = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if kind is not None and kind not in {"part", "assembly"}:
        raise ValueError(f"@{fmt} kind must be 'part' or 'assembly', got {kind!r}")
    kinematics_def = (
        normalize_kinematics(kinematics, where=f"@{fmt}") if kinematics is not None else None
    )
    bake_pose = normalize_bake_pose(pose, kinematics_def, where=f"@{fmt}")
    animation_path = _normalize_animation(animation, fmt=fmt)

    def apply(func: Callable[..., Any]) -> Callable[..., Any]:
        _validate_signature(func, fmt=fmt)
        script_path = _script_path_of(func)
        lowered = script_path.name.lower()
        if lowered.endswith((".step.py", ".dxf.py")):
            raise _legacy_naming_error(script_path)
        pending = tuple(getattr(func, "__cadgen_pending_mesh_exports__", ()))
        if pending and fmt != "step":
            names = ", ".join(f"@{_MESH_FMT_DECORATOR[d.fmt]}" for d in pending)
            raise TypeError(
                f"{script_path.name} stacks {names} on a @{fmt} drawing; "
                "STL/3MF/GLB derive from a @step model's geometry"
            )
        if pending:
            try:
                delattr(func, "__cadgen_pending_mesh_exports__")
            except AttributeError:
                pass
        defn = ModelDef(
            func=func,
            fmt=fmt,
            script_path=script_path,
            out=out,
            kind=kind,
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            kinematics=kinematics_def,
            bake_pose=bake_pose,
            animation=animation_path,
            mesh_exports=pending,
        )
        _register(defn)
        func.__cadgen_model__ = defn  # type: ignore[attr-defined]
        if func.__module__ == "__main__":
            # Decoration-time execution: running the script builds the model.
            # A mesh decorator stacked ABOVE @step has not run yet in THIS
            # process — that is fine: the pipeline re-imports the module under
            # a loader name (never __main__), where every decorator applies
            # before the runner reads the registry.
            raise SystemExit(_run_from_main(defn))
        return func

    return apply


def step(
    func: Callable[..., Any] | None = None,
    *,
    out: str | None = None,
    kind: str | None = None,
    mesh_tolerance: float | None = None,
    mesh_angular_tolerance: float | None = None,
    kinematics: object = None,
    pose: object = None,
    animation: str | None = None,
    **renamed: Any,
):
    """Declare a STEP model. Usable bare (``@step``) or configured (``@step(...)``).

    ``kinematics=`` takes the typed-mates dict (see ``cadgen.kinematics``);
    ``pose=`` names the configuration to BAKE the artifact at (preset name or
    ``{dof: value}``; the written artifact is its own q=0); ``animation=``
    names a ``.js`` choreography module beside the script whose text is copied
    into the sidecar. STEP is the only format with animation — mesh exports
    are static bakes.
    """
    _reject_renamed_kwargs("step", renamed)
    decorator = _decorator(
        "step",
        out=out,
        kind=kind,
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
        kinematics=kinematics,
        pose=pose,
        animation=animation,
    )
    return decorator(func) if func is not None else decorator


def dxf(
    func: Callable[..., Any] | None = None,
    *,
    out: str | None = None,
    **renamed: Any,
):
    """Declare a DXF drawing. Usable bare (``@dxf``) or configured (``@dxf(...)``)."""
    for retired in ("kinematics", "pose", "animation"):
        if retired in renamed:
            raise TypeError(
                f"@dxf takes no {retired}=: a drawing is 2D geometry — kinematics "
                "and pose baking live on @step and the mesh decorators, and "
                "animation is @step-only"
            )
    _reject_renamed_kwargs("dxf", renamed)
    decorator = _decorator(
        "dxf", out=out, kind=None, mesh_tolerance=None, mesh_angular_tolerance=None
    )
    return decorator(func) if func is not None else decorator


_MESH_FMT_DECORATOR = {"stl": "stl", "glb": "glb", "3mf": "threemf"}


def _validate_variant(existing, decl: MeshExportDecl, deco_name: str) -> None:
    """Variants of one format are allowed; ambiguous duplicates are not: two
    bare declarations collide at the sibling default, two identical out=
    targets collide outright."""
    if decl.out is None:
        if any(d.fmt == decl.fmt and d.out is None for d in existing):
            raise TypeError(
                f"bare @{deco_name} is declared more than once; at most one "
                "declaration per format may omit out= (the sibling default)"
            )
    elif any(d.fmt == decl.fmt and d.out == decl.out for d in existing):
        raise TypeError(f"@{deco_name} is declared twice for the same target {decl.out!r}")


def _mesh_export_decorator(deco_name: str, fmt: str):
    """Factory for ``@stl``/``@glb``/``@threemf``: metadata-attachers, never
    wrappers. Below ``@step`` they park a pending declaration on the raw
    function; above it they extend the registered model. Both routes converge
    in the loader import, so stacking order is behavior-neutral."""
    from dataclasses import replace as _replace

    suffix = f".{fmt}"

    def decorator_factory(
        func: Callable[..., Any] | None = None,
        *,
        out: str | None = None,
        mesh_tolerance: float | None = None,
        mesh_angular_tolerance: float | None = None,
        kinematics: object = None,
        pose: object = None,
        **renamed: Any,
    ):
        if "animation" in renamed:
            raise TypeError(
                f"@{deco_name} takes no animation=: mesh exports are static "
                "bakes with no sidecar — animation is a STEP-x-viewer concern "
                "and lives on @step only"
            )
        _reject_renamed_kwargs(deco_name, renamed)
        if out is not None and not str(out).lower().endswith(suffix):
            raise ValueError(f"@{deco_name} out= must end with '{suffix}': {out!r}")
        kinematics_def = (
            normalize_kinematics(kinematics, where=f"@{deco_name}")
            if kinematics is not None
            else None
        )
        decl = MeshExportDecl(
            fmt=fmt,
            out=out,
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
            kinematics=kinematics_def,
            bake_pose=normalize_bake_pose(pose, kinematics_def, where=f"@{deco_name}"),
        )

        def attach(target: Callable[..., Any]) -> Callable[..., Any]:
            existing_model: ModelDef | None = getattr(target, "__cadgen_model__", None)
            if existing_model is not None:
                # Above @step: extend the registered model in place.
                if existing_model.fmt != "step":
                    raise TypeError(
                        f"@{deco_name} declares a mesh export of a @step model; "
                        f"{existing_model.script_path.name} is a @{existing_model.fmt} drawing"
                    )
                _validate_variant(existing_model.mesh_exports, decl, deco_name)
                updated = _replace(
                    existing_model, mesh_exports=(*existing_model.mesh_exports, decl)
                )
                _REGISTRY[updated.script_path] = updated
                target.__cadgen_model__ = updated  # type: ignore[attr-defined]
                return target
            # Below @step: park a pending declaration for @step to consume.
            pending = list(getattr(target, "__cadgen_pending_mesh_exports__", ()))
            _validate_variant(pending, decl, deco_name)
            pending.append(decl)
            target.__cadgen_pending_mesh_exports__ = tuple(pending)  # type: ignore[attr-defined]
            return target

        return attach(func) if func is not None else attach

    decorator_factory.__name__ = deco_name
    return decorator_factory


stl = _mesh_export_decorator("stl", "stl")
glb = _mesh_export_decorator("glb", "glb")
threemf = _mesh_export_decorator("threemf", "3mf")


def _maybe_hint_eager_imports(defn: ModelDef) -> None:
    if os.environ.get("CADGEN_DAEMON_CHILD"):
        return
    if "OCP" in sys.modules or "build123d" in sys.modules:
        print(
            f"hint: {defn.script_path.name} imported the CAD kernel at module top; "
            "use `from cadgen import build123d as bd` so re-runs skip the ~2.5s "
            "import when the model is current (see the cad skill docs)",
            file=sys.stderr,
        )


def _run_from_main(defn: ModelDef) -> int:
    """Run the pipeline for a directly-executed model script and return its exit code."""
    argv = sys.argv[1:]
    _maybe_hint_eager_imports(defn)

    # Warm handoff BEFORE any heavy import, mirroring the retired CLI shims.
    # The daemon worker re-imports this module under a loader name (never
    # __main__), so the decorator over there only registers and the runner
    # calls the function — the documented double-import semantics.
    if os.environ.get("CADGEN_DAEMON") != "0" and not os.environ.get("CADGEN_DAEMON_CHILD"):
        try:
            from cadgen.daemon.client import run_via_daemon
        except ModuleNotFoundError:
            warm_exit: int | None = None
        else:
            warm_exit = run_via_daemon(
                "run",
                [str(defn.script_path), *argv],
                os.getcwd(),
                prog=f"python {defn.script_path.name}",
            )
        if warm_exit is not None:
            return warm_exit

    # A cold @dxf run used to re-exec itself here with PYTHONHASHSEED=0, because
    # ezdxf's emitted order depended on string hashing. The engine's emitter makes
    # DXF bytes a function of the drawing's geometry instead
    # (cadgen._internal.dxf_emit), so a cold run needs no interpreter restart and
    # @dxf reaches the pipeline by exactly the route @step does.
    from cadgen.cli._run_model import run_model_argv

    return run_model_argv(
        [str(defn.script_path), *argv], prog=f"python {defn.script_path.name}"
    )
