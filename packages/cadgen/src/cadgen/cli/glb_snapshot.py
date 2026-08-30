"""``cadgen glb snapshot`` — render a GLB mesh.

A thin declaration over :mod:`cadgen.cli.snapshot`: the only thing that distinguishes one
format's snapshot door from another's is which input kinds it accepts, so that is the only
thing stated here. Everything else — arguments, job schema, theme, the headless browser —
is shared by construction rather than by copies agreeing.

The mesh half of ``cadgen step snapshot``, re-homed: GLB is a format with a door
(``cadgen glb build``), so its snapshot belongs behind the same door rather than
inside the STEP one. What a mesh can and cannot do is unchanged — it renders
shaded solid, and the STEP-only options (selection, display modes, exploded,
pose parameters, section mode) refuse it with the same errors.
"""

from __future__ import annotations

from collections.abc import Sequence

from cadgen.cli.snapshot import DOOR_KINDS, OPTION_NAMES, run

KINDS = DOOR_KINDS["glb"]
# Re-exported so this command's declared adapter surface is readable from the
# command's own module, the way a generated command's parser is.
__all__ = ["KINDS", "OPTION_NAMES", "main"]


def main(argv: Sequence[str] | None = None, *, prog: str = "cadgen glb snapshot") -> int:
    return run(argv, kinds=KINDS, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
