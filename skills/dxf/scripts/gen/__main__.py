#!/usr/bin/env python3
"""Build DXF targets from their .dxf.py generators.

A shim over the `cadgen` distribution named in this skill's requirements.txt. The parser,
the behaviour and the output contract all live in ``cadgen.cli.dxf_gen``; this file exists so the
skill keeps a stable `scripts/gen` entrypoint, and so a missing install fails with an
instruction instead of a traceback.
"""

from __future__ import annotations

import sys

import os

# Drawing packages are content-addressed (drawing.json dxfHash) and must be
# byte-deterministic. ezdxf's object-section creation order depends on Python
# hash randomization, so pin the seed and re-run once before any ezdxf import.
#
# subprocess rather than os.execv: on Windows execv hands the argument vector to the C
# runtime, which re-joins it into a command line WITHOUT quoting, so an interpreter path
# containing a space -- C:\Program Files\Python311\python.exe, which is where the
# python.org all-users installer puts it -- arrives as two arguments and the child tries to
# run "Files\Python311\python.exe" as a script relative to the working directory. subprocess
# applies Windows quoting rules. Nothing is lost on POSIX either: os.execv never replaced the
# process on Windows, so the parent lingered there regardless, and the child's exit code is
# passed straight through here.
if os.environ.get("PYTHONHASHSEED") != "0":
    import subprocess

    os.environ["PYTHONHASHSEED"] = "0"
    raise SystemExit(subprocess.run([sys.executable, *sys.argv], check=False).returncode)

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

from cadgen.cli import dxf_gen as _cli


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
