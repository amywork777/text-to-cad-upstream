#!/usr/bin/env python3
"""Render a STEP or mesh to an image.

A shim over the `cadgen` distribution named in this skill's requirements.txt. The parser,
the behaviour and the output contract all live in ``cadgen.cli.step_snapshot``; this file exists so the
skill keeps a stable `scripts/snapshot` entrypoint, and so a missing install fails with an
instruction instead of a traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fail fast when the installed cadgen is not the one this skill was published against:
# every line below runs INSIDE that install, including the warm-daemon handoff.
try:
    from cadgen.cli import enforce_requirements_pin
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)

enforce_requirements_pin(Path(__file__).resolve().parents[2] / "requirements.txt")

# Warm-daemon handoff, BEFORE the cadgen import below -- that import is the multi-second
# OCP/build123d cost the daemon exists to avoid paying per invocation. The daemon sets
# CADGEN_DAEMON_CHILD in the process it serves from, so this cannot recurse.
import os

if os.environ.get("CADGEN_WARM") == "1" and not os.environ.get("CADGEN_DAEMON_CHILD"):
    try:
        from cadgen.daemon.client import run_via_daemon
    except ModuleNotFoundError:
        pass
    else:
        _warm_exit = run_via_daemon("snapshot", sys.argv[1:], os.getcwd())
        if _warm_exit is not None:
            raise SystemExit(_warm_exit)

from cadgen.cli import step_snapshot as _cli

# Re-exported so this entry still answers "which inputs does this skill accept" without a
# caller having to know which cadgen module backs it.
KINDS = _cli.KINDS


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
