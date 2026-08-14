#!/usr/bin/env python3
"""Render a SRDF description to an image.

A shim over the `cadgen` distribution named in this skill's requirements.txt. What is
local to this skill is the one line below: which input kinds it accepts. Everything else
about rendering — arguments, job schema, theme, display, the headless browser — is
``cadgen.cli.snapshot``, shared with every other skill that renders.

An SRDF names group states over a robot it references rather than carrying geometry,
so rendering resolves that robot first and then applies the selected state.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fail fast when the installed cadgen is not the one this skill was published against:
# everything below this line runs INSIDE that install.
try:
    from cadgen.cli import enforce_requirements_pin
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)

enforce_requirements_pin(Path(__file__).resolve().parents[2] / "requirements.txt")

from cadgen.cli.snapshot import SKILL_KINDS, run

KINDS = SKILL_KINDS["srdf"]


def main(argv: list[str] | None = None) -> int:
    return run(argv, kinds=KINDS, prog="scripts/snapshot")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
