"""``cadgen dxf build`` — a GENERATED CLI over :func:`cadgen.dxf.build`.

There is no parser here on purpose; see :mod:`cadgen.cli.step_build`.

Dispatch used to re-run this command once with PYTHONHASHSEED pinned, because
ezdxf's emitted order followed string hashing and a drawing's bytes have to be a
function of its source. The DXF emitter engineers that instead
(:mod:`cadgen._internal.dxf_emit`), so this is an ordinary command again.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cadgen._internal.cli_from_function import generated_main, generated_parser

DEFAULT_PROG = "cadgen dxf build"
VERB = ("cadgen.dxf", "build")


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    return generated_parser(VERB, prog=prog)


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    return generated_main(VERB, argv, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
