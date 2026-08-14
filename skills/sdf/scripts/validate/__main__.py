#!/usr/bin/env python3
"""Validate SDF worlds and models.

A shim over the `cadgen` distribution named in this skill's requirements.txt. Structure, model/link/joint graph and mesh references are checked by
``cadgen.cli.sdf_validate``; ``--gz-check`` additionally shells out to ``gz sdf``.
This file exists so the skill keeps a stable `scripts/validate` entrypoint, and so a
missing install fails with an instruction instead of a traceback.
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

from cadgen.cli import sdf_validate as _cli


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
