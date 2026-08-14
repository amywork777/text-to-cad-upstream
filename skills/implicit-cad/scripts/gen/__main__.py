#!/usr/bin/env python3
"""Build implicit CAD targets.

A shim over the `cadgen` distribution named in this skill's requirements.txt. The parser,
the behaviour and the output contract all live in ``cadgen.cli.implicit_gen``; this file exists so the
skill keeps a stable `scripts/gen` entrypoint, and so a missing install fails with an
instruction instead of a traceback.
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

from cadgen.cli import implicit_gen as _cli


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
