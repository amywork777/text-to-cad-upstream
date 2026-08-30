"""The public ``dxf`` format namespace: the ``@dxf`` decorator and its verbs.

``@dxf`` DECLARES a drawing; ``dxf.build(...)`` makes one current. They are the
same object — this module is callable (see
:mod:`cadgen._internal.format_namespace`) — so the drawing family is one table
row like every other format (design/format-doors.md).

``cadgen dxf build`` is this module's ``build`` with a parser derived from its
signature. It is a NEW verb: until now only the script door built a drawing, so
there was no way to ask for one by name.

Import discipline: nothing here may pull in ezdxf/OCP at module scope (see
:mod:`cadgen.step`).
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
) -> BuildResult:
    """Make TARGET's drawing current; no-op when it already is.

    Runs the closure gate, runs the generator if stale, and writes the ``.dxf``
    document plus its content-keyed record. The bytes are a function of the
    source alone: this build path pins PYTHONHASHSEED, because ezdxf's object
    ordering follows hash randomization and a drawing record is only meaningful
    if the same source writes the same file.

    target: @dxf model script (.py) to build.
    force: rebuild even when the record says the drawing is current.
    verbose: show detailed progress and timing on stderr.
    """
    from cadgen._internal.dxf_output import dxf_output_current
    from cadgen._internal.generation import _entry_spec_from_source, generate_dxf_targets
    from cadgen.catalog import source_from_path

    path = Path(target).expanduser().resolve()
    if path.suffix.lower() != ".py":
        raise ValueError(f"dxf build target must be a model script (.py): {target}")
    if not path.is_file():
        raise FileNotFoundError(f"model script does not exist: {target}")
    source = source_from_path(path)
    if source is None:
        raise ValueError(
            f"{path.name} declares no CAD model — decorate one function with @dxf from cadgen"
        )
    spec = _entry_spec_from_source(source)
    if spec.dxf_path is None:
        raise ValueError(
            f"{path.name} declares no @dxf drawing; `cadgen dxf build` builds DXF "
            "documents (a @step model builds with `cadgen step build`)"
        )
    document: Path = spec.dxf_path
    skipped = not force and dxf_output_current(path, document)
    generate_dxf_targets([str(path)], force=force, verbose=verbose)
    return BuildResult(
        ok=document.is_file(),
        document=document,
        # A drawing has no render package: the .dxf IS the product, and the
        # viewer parses it directly (design/standalone-viewer.md).
        package=None,
        skipped=skipped,
    )


callable_namespace(__name__, "dxf")
