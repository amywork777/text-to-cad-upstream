"""``cadgen snapshot`` — render any supported input, and the target every skill shim calls.

A skill's snapshot entrypoint has always been one call to :func:`cadgen.snapshot_cli.
run_snapshot_cli` with a declaration of which input kinds it accepts. That declaration now
lives here, keyed by skill, so the shim in the skill is a name rather than a copy of the
wiring — and ``cadgen snapshot`` with no restriction accepts every kind at once.

``runtime_dir`` is deliberately not passed: leaving it ``None`` lets ``cadgen.assets``
resolve the browser runtime, which finds the repo's live source in a dev checkout and the
packaged copy in an installed wheel. A skill pinning its own vendored path is exactly what
this reorganization removes.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from cadgen.snapshot_cli import run_snapshot_cli

# Which input kinds each skill's snapshot accepts. Unioned for the bare `cadgen snapshot`.
SKILL_KINDS: dict[str, tuple[str, ...]] = {
    "cad": ("step", "stp", "3mf", "glb", "stl"),
    "dxf": ("dxf",),
    "implicit-cad": ("implicit",),
    "urdf": ("urdf",),
    "srdf": ("srdf",),
    "sdf": ("sdf",),
}

ALL_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(kind for kinds in SKILL_KINDS.values() for kind in kinds)
)


def run(
    argv: Sequence[str] | None = None,
    *,
    kinds: Sequence[str] = ALL_KINDS,
    prog: str = "cadgen snapshot",
) -> int:
    """Render one input. Skill shims call this with their own ``kinds`` and ``prog``."""
    return run_snapshot_cli(
        list(sys.argv[1:] if argv is None else argv),
        kinds=kinds,
        runtime_dir=None,
        prog=prog,
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
