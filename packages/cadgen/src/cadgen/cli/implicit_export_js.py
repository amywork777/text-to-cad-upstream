"""``cadgen implicit export`` — run the packaged implicit export builder under Node.

This one is Python only as a launcher: the exporter itself is JavaScript, because an
implicit model IS a JS module and evaluating it anywhere else would mean a second
implementation of the same semantics. So this resolves the builder and the interpreter
through :mod:`cadgen.assets`, then hands over.

argv, stdio and the exit code pass through untouched — a caller cannot tell this apart
from invoking node on the builder directly, which is what makes it a safe substitute for
the skill's old `export.mjs`.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

from cadgen._internal.node_runtime import cad_node_executable, node_builder_script

EXPORT_BUILDER = "implicit-export.mjs"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    completed = subprocess.run(
        [str(cad_node_executable()), str(node_builder_script(EXPORT_BUILDER)), *args],
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
