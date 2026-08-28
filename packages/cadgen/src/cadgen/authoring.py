"""The library-first authoring surface: ``@step`` and ``@dxf``
(design/library-first-generation.md).

A CAD model is a plain Python script; the decorator is the entrypoint::

    from cadgen import build123d as bd
    from cadgen import step

    @step()                      # write= defaults to <stem>.step beside the
    def bracket(width: float = 10.0):    # script; pass write="..." to relocate
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

from cadgen.metadata import resolve_model_output_path

__all__ = ["step", "dxf", "ModelDef", "registered_model", "registered_models"]


@dataclass(frozen=True)
class ModelDef:
    """One registered model: the decorated function plus its durable options."""

    func: Callable[..., Any]
    fmt: str  # "step" | "dxf"
    script_path: Path
    write: str | None
    kind: str | None
    mesh_tolerance: float | None
    mesh_angular_tolerance: float | None

    @property
    def output_path(self) -> Path:
        return resolve_model_output_path(self.script_path, fmt=self.fmt, explicit_write=self.write)


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


def _decorator(
    fmt: str,
    *,
    write: str | None,
    kind: str | None,
    mesh_tolerance: float | None,
    mesh_angular_tolerance: float | None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if kind is not None and kind not in {"part", "assembly"}:
        raise ValueError(f"@{fmt} kind must be 'part' or 'assembly', got {kind!r}")

    def apply(func: Callable[..., Any]) -> Callable[..., Any]:
        _validate_signature(func, fmt=fmt)
        script_path = _script_path_of(func)
        lowered = script_path.name.lower()
        if lowered.endswith((".step.py", ".dxf.py")):
            raise _legacy_naming_error(script_path)
        defn = ModelDef(
            func=func,
            fmt=fmt,
            script_path=script_path,
            write=write,
            kind=kind,
            mesh_tolerance=mesh_tolerance,
            mesh_angular_tolerance=mesh_angular_tolerance,
        )
        _register(defn)
        func.__cadgen_model__ = defn  # type: ignore[attr-defined]
        if func.__module__ == "__main__":
            # Decoration-time execution: running the script builds the model.
            raise SystemExit(_run_from_main(defn))
        return func

    return apply


def step(
    func: Callable[..., Any] | None = None,
    *,
    write: str | None = None,
    kind: str | None = None,
    mesh_tolerance: float | None = None,
    mesh_angular_tolerance: float | None = None,
):
    """Declare a STEP model. Usable bare (``@step``) or configured (``@step(...)``)."""
    decorator = _decorator(
        "step",
        write=write,
        kind=kind,
        mesh_tolerance=mesh_tolerance,
        mesh_angular_tolerance=mesh_angular_tolerance,
    )
    return decorator(func) if func is not None else decorator


def dxf(
    func: Callable[..., Any] | None = None,
    *,
    write: str | None = None,
):
    """Declare a DXF drawing. Usable bare (``@dxf``) or configured (``@dxf(...)``)."""
    decorator = _decorator(
        "dxf", write=write, kind=None, mesh_tolerance=None, mesh_angular_tolerance=None
    )
    return decorator(func) if func is not None else decorator


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
    if os.environ.get("CADGEN_WARM") != "0" and not os.environ.get("CADGEN_DAEMON_CHILD"):
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

    # Drawing packages must be byte-deterministic and ezdxf's object ordering
    # depends on hash randomization. Warm workers always carry PYTHONHASHSEED=0;
    # a COLD @dxf run re-execs once to pin it (the same re-run the retired
    # `dxf gen` dispatch performed).
    if defn.fmt == "dxf" and os.environ.get("PYTHONHASHSEED") != "0":
        import subprocess

        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        env["CADGEN_WARM"] = "0"  # already decided cold; do not bounce to the daemon
        completed = subprocess.run(
            [sys.executable, str(defn.script_path), *argv], env=env, check=False
        )
        return int(completed.returncode)

    from cadgen.cli._run_model import run_model_argv

    return run_model_argv(
        [str(defn.script_path), *argv], prog=f"python {defn.script_path.name}"
    )
