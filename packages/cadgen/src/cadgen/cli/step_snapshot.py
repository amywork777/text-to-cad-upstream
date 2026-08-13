"""``cadgen step snapshot`` — render STEP, STP, 3MF, GLB and STL inputs.

A thin declaration over :mod:`cadgen.cli.snapshot`: the only thing that distinguishes one
skill's snapshot from another's is which input kinds it accepts, so that is the only thing
stated here. Everything else — arguments, job schema, theme, the headless browser — is
shared by construction rather than by copies agreeing.
"""

from __future__ import annotations

from collections.abc import Sequence

from cadgen.cli.snapshot import SKILL_KINDS, run

KINDS = SKILL_KINDS["cad"]


def main(argv: Sequence[str] | None = None, *, prog: str = "scripts/snapshot") -> int:
    return run(argv, kinds=KINDS, prog=prog)
