#!/usr/bin/env python3
"""Render a URDF description to an image.

A shim over the `cadgen` distribution named in this skill's requirements.txt. What is
local to this skill is the one line below: which input kinds it accepts. Everything else
about rendering — arguments, job schema, theme, display, the headless browser — is
``cadgen.cli.snapshot``, shared with every other skill that renders.

A robot has no artifact to build: the browser parser resolves each link mesh against
the description's own URL, so there is nothing to generate and no generation lock to
take. Robots are authored in METRES against a millimetre CAD profile, so the resolver
defaults this input to the robot scene scale. Pose it with the job field
"jointValues" (joint name to degrees, defaulting to the rest pose).
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

KINDS = SKILL_KINDS["urdf"]


def main(argv: list[str] | None = None) -> int:
    return run(argv, kinds=KINDS, prog="scripts/snapshot")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
