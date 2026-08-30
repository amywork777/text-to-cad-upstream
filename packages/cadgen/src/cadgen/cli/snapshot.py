"""``cadgen snapshot`` — render any supported input, and the target every door calls.

A snapshot door's entrypoint has always been one call to :func:`cadgen.snapshot_cli.
run_snapshot_cli` with a declaration of which input kinds it accepts. That declaration
lives here, keyed by FORMAT, so a door module is a name rather than a copy of the
wiring — and ``cadgen snapshot`` with no restriction accepts every kind at once,
routing by suffix.

One format, one door (design/format-doors.md). ``cadgen step snapshot`` used to also
render ``.stl``/``.3mf``/``.glb``, which made the STEP door the door for four formats
and left the mesh formats with a `build` door and no `snapshot` door of their own. The
mesh arm moved to ``cadgen stl|3mf|glb snapshot`` verbatim; nothing about how a mesh
renders changed, only which command owns it.

``runtime_dir`` is deliberately not passed: leaving it ``None`` lets ``cadgen.assets``
resolve the browser runtime, which finds the repo's live source in a dev checkout and the
packaged copy in an installed wheel. A skill pinning its own vendored path is exactly what
this reorganization removes.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from cadgen.snapshot_cli import option_names, run_snapshot_cli

# Every snapshot command is an ADAPTER in the format-doors schema
# (design/format-doors.md): its option surface is too rich to derive from a verb
# signature, so it declares that surface instead and the signature-sync policy
# test checks the declaration. No door adds flags of its own — they differ
# only in which input kinds they accept — so there is one surface, here.
OPTION_NAMES: tuple[str, ...] = option_names()

# Which input kinds each format door's snapshot accepts. Unioned for the bare
# `cadgen snapshot`. `srdf` has no snapshot door of its own (an SRDF's geometry
# comes from the URDF beside it), but the polymorphic door still routes one.
DOOR_KINDS: dict[str, tuple[str, ...]] = {
    "step": ("step", "stp"),
    "stl": ("stl",),
    "3mf": ("3mf",),
    "glb": ("glb",),
    "dxf": ("dxf",),
    "urdf": ("urdf",),
    "srdf": ("srdf",),
    "sdf": ("sdf",),
}

ALL_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(kind for kinds in DOOR_KINDS.values() for kind in kinds)
)


def run(
    argv: Sequence[str] | None = None,
    *,
    kinds: Sequence[str] = ALL_KINDS,
    prog: str = "cadgen snapshot",
) -> int:
    """Render one input. Format doors call this with their own ``kinds`` and ``prog``."""
    return run_snapshot_cli(
        list(sys.argv[1:] if argv is None else argv),
        kinds=kinds,
        runtime_dir=None,
        prog=prog,
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
