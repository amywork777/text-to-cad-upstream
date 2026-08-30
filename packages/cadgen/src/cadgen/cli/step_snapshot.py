"""``cadgen step snapshot`` — render STEP, STP, 3MF, GLB and STL inputs.

A thin declaration over :mod:`cadgen.cli.snapshot`: the only thing that distinguishes one
skill's snapshot from another's is which input kinds it accepts, so that is the only thing
stated here. Everything else — arguments, job schema, theme, the headless browser — is
shared by construction rather than by copies agreeing.
"""

from __future__ import annotations

from collections.abc import Sequence

from cadgen.cli.snapshot import OPTION_NAMES, SKILL_KINDS, run

KINDS = SKILL_KINDS["cad"]
# Re-exported so this command's declared adapter surface is readable from the
# command's own module, the way a generated command's parser is.
__all__ = ["KINDS", "OPTION_NAMES", "main"]


def main(argv: Sequence[str] | None = None, *, prog: str = "cadgen step snapshot") -> int:
    return run(argv, kinds=KINDS, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
