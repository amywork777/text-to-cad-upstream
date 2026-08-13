#!/usr/bin/env python3
"""Build a DXF's drawing package.

A shim over the `cadgen` distribution named in this skill's requirements.txt. The parser,
the behaviour and the output contract all live in ``cadgen.cli.dxf_artifact``; this file exists so the
skill keeps a stable `scripts/artifact` entrypoint, and so a missing install fails with an
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

try:
    from cadgen.cli import dxf_artifact as _cli
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
