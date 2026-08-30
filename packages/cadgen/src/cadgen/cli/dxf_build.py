"""``cadgen dxf build`` — a GENERATED CLI over :func:`cadgen.dxf.build`.

There is no parser here on purpose; see :mod:`cadgen.cli.step_build`.

Dispatch re-runs this command once with PYTHONHASHSEED pinned when it is not
already (``cadgen.cli._HASH_SEED_COMMANDS``), because a drawing's bytes must be
a function of its source alone. That happens before this module is imported —
the seed is read at interpreter start, so nothing here could fix it.
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
