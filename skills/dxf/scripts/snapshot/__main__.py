#!/usr/bin/env python3
"""Render a DXF to an image.

A shim over the `cadgen` distribution named in this skill's requirements.txt. The parser,
the behaviour and the output contract all live in ``cadgen.cli.dxf_snapshot``; this file exists so the
skill keeps a stable `scripts/snapshot` entrypoint, and so a missing install fails with an
instruction instead of a traceback.
"""

from __future__ import annotations

import sys

try:
    from cadgen.cli import dxf_snapshot as _cli
except ModuleNotFoundError:
    sys.stderr.write(
        "cadgen is not installed. From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)

# Re-exported so this entry still answers "which inputs does this skill accept" without a
# caller having to know which cadgen module backs it.
KINDS = _cli.KINDS


if __name__ == "__main__":
    raise SystemExit(_cli.main(sys.argv[1:]))
