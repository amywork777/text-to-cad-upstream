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

from pathlib import Path

from cadgen._internal.format_namespace import callable_namespace
from cadgen.results import BuildResult

__all__ = ["build"]


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
