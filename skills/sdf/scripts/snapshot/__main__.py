#!/usr/bin/env python3
"""Render a SDF description to an image.

A shim over the `cadgen` distribution named in this skill's requirements.txt. What is
local to this skill is the one line below: which input kinds it accepts. Everything else
about rendering — arguments, job schema, theme, display, the headless browser — is
``cadgen.cli.snapshot``, shared with every other skill that renders.

An SDF world may hold several models and their poses; the shared mesh path renders
the result, so there is nothing to generate and no generation lock to take.
"""

from __future__ import annotations

import sys

try:
    from cadgen.cli.snapshot import SKILL_KINDS, run
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)

KINDS = SKILL_KINDS["sdf"]


def main(argv: list[str] | None = None) -> int:
    return run(argv, kinds=KINDS, prog="scripts/snapshot")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
