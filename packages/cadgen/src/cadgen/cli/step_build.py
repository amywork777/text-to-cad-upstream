"""``cadgen step build`` — a GENERATED CLI over :func:`cadgen.step.build`.

There is no parser here on purpose. Everything the command accepts is derived
from the verb function's signature by
:mod:`cadgen._internal.cli_from_function`, so a flag cannot drift from a
parameter: this module only names which function the command is
(design/format-doors.md).

This absorbs the retired ``cadgen import``: importing a foreign STEP is
``step.build`` applied to a foreign document — same gate, same locks, same
store package.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cadgen._internal.cli_from_function import generated_main, generated_parser

DEFAULT_PROG = "cadgen step build"
VERB = ("cadgen.step", "build")


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    return generated_parser(VERB, prog=prog)


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    return generated_main(VERB, argv, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
