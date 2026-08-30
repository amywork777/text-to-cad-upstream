"""``cadgen urdf snapshot`` — render URDF robot descriptions.

A thin declaration over :mod:`cadgen.cli.snapshot`: the only thing that distinguishes one
family's snapshot from another's is which input kinds it accepts, so that is the only thing
stated here. Everything else — arguments, job schema, theme, joint values, the headless
browser — is shared by construction rather than by copies agreeing.

New in the format-doors schema (design/format-doors.md): the renderer always
supported this input, but only the polymorphic ``cadgen snapshot`` could reach it,
so the urdf family had a validate verb and no way to look at the thing.
"""

from __future__ import annotations

from collections.abc import Sequence

from cadgen.cli.snapshot import DOOR_KINDS, OPTION_NAMES, run

KINDS = DOOR_KINDS["urdf"]
# Re-exported so this command's declared adapter surface is readable from the
# command's own module, the way a generated command's parser is.
__all__ = ["KINDS", "OPTION_NAMES", "main"]


def main(argv: Sequence[str] | None = None, *, prog: str = "cadgen urdf snapshot") -> int:
    return run(argv, kinds=KINDS, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
