"""``cadgen step snapshot`` — render a STEP/STP document or the model script behind one.

A thin declaration over :mod:`cadgen.cli.snapshot`: the only thing that distinguishes one
format's snapshot door from another's is which input kinds it accepts, so that is the only
thing stated here. Everything else — arguments, job schema, theme, the headless browser —
is shared by construction rather than by copies agreeing.

Mesh inputs are NOT this door's: ``.stl``, ``.3mf`` and ``.glb`` go through
``cadgen stl|3mf|glb snapshot``, which is where their `build` doors already live.
Handing one here is refused by name with the door that takes it.
"""

from __future__ import annotations

from collections.abc import Sequence

from cadgen.cli.snapshot import DOOR_KINDS, OPTION_NAMES, run

KINDS = DOOR_KINDS["step"]
# Re-exported so this command's declared adapter surface is readable from the
# command's own module, the way a generated command's parser is.
__all__ = ["KINDS", "OPTION_NAMES", "main"]


def main(argv: Sequence[str] | None = None, *, prog: str = "cadgen step snapshot") -> int:
    return run(argv, kinds=KINDS, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
