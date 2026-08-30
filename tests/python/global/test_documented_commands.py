"""Every `cadgen ...` command form a skill documents has to be a real command.

Skills are the product, and an agent runs what they say verbatim. A renamed or
retired command leaves the docs still confidently teaching it — that is how
`scripts/test/test-installed.sh` came to check four commands that no longer
existed, and how `cadgen step export` would have outlived its deletion.

So: extract the command forms out of the skills' own fenced code blocks and put
them through the real dispatcher's registry and the real parsers. Nothing is
executed — a smoke test may not build CAD — but a form that names a command that
is gone, or passes a flag that no longer exists, fails here
(design/format-doors.md, "executed docs").
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import re
import shlex
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path, repo_path

add_repo_path("packages/cadgen/src")

from cadgen import cli  # noqa: E402

SKILLS = Path(repo_path("skills"))

FENCE = re.compile(r"^\s*```")

# `[--force]` marks an optional flag in a documented form; `...` marks an
# elision. Neither is an argument, so one is unwrapped and the other ends the
# form (what follows a `...` is by definition not written out).
ELISION = "..."


def _command_forms(text: str) -> list[tuple[list[str], bool]]:
    """The `cadgen` argv forms inside this document's fenced code blocks.

    Each carries whether an elision cut it short: `cadgen step inspect ...` names
    a command but is not a complete invocation, so it is checked for existence
    and not put through the parser.
    """
    forms: list[tuple[list[str], bool]] = []
    in_fence = False
    pending = ""
    for raw in text.splitlines():
        if FENCE.match(raw):
            in_fence = not in_fence
            pending = ""
            continue
        if not in_fence:
            continue
        line = (pending + " " + raw.strip()).strip() if pending else raw.strip()
        pending = ""
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        if not line.startswith("cadgen "):
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue  # an unbalanced quote is prose, not a command form
        argv: list[str] = []
        elided = False
        for token in tokens[1:]:
            if token == ELISION:
                elided = True
                break
            argv.append(token.strip("[]"))
        if argv:
            forms.append((argv, elided))
    return forms


def _documented_forms() -> list[tuple[Path, list[str], bool]]:
    found: list[tuple[Path, list[str], bool]] = []
    for path in sorted(SKILLS.rglob("*.md")):
        for argv, elided in _command_forms(path.read_text(encoding="utf-8")):
            found.append((path.relative_to(SKILLS.parent), argv, elided))
    return found


def _split_command(argv: list[str]) -> tuple[str, list[str]] | None:
    """The registry entry this form dispatches to, exactly as `cli.main` picks it."""
    for width in (2, 1):
        name = " ".join(argv[:width])
        if name in cli._COMMANDS:  # noqa: SLF001 - the registry IS the thing under test
            return name, argv[width:]
    return None


def _parse(module, rest: list[str]) -> None:
    """Put the form through the command's real parser, or skip if it has none.

    Two parser shapes exist. A generated or argparse command answers with
    ``build_parser``; snapshot parses argv by hand and is reached through its own
    entry. A command that builds its parser inside ``main()`` has nothing to call
    without running it, so those forms are checked for existence only.
    """
    parser_builder = getattr(module, "build_parser", None)
    if parser_builder is not None:
        parser_builder().parse_args(rest)
        return
    if hasattr(module, "OPTION_NAMES"):
        from cadgen.snapshot_cli import parse_snapshot_args

        parse_snapshot_args(rest)


class DocumentedCommands(unittest.TestCase):
    def test_the_skills_document_command_forms_at_all(self):
        # A sweep that silently matched nothing would pass forever.
        self.assertGreater(len(_documented_forms()), 20)

    def test_every_documented_form_names_a_real_command(self):
        for source, argv, _elided in _documented_forms():
            with self.subTest(source=str(source), form=" ".join(argv)):
                self.assertIsNotNone(
                    _split_command(argv),
                    f"{source} documents `cadgen {' '.join(argv)}`, which no command answers",
                )

    def test_every_documented_form_parses(self):
        for source, argv, elided in _documented_forms():
            split = _split_command(argv)
            if split is None or elided:
                continue  # reported by the test above / not a complete invocation
            name, rest = split
            with self.subTest(source=str(source), form=" ".join(argv)):
                module = importlib.import_module(cli._COMMANDS[name][0])  # noqa: SLF001
                errors = io.StringIO()
                try:
                    with contextlib.redirect_stderr(errors):
                        _parse(module, rest)
                except SystemExit:  # argparse's usage error
                    self.fail(f"{source}: `cadgen {' '.join(argv)}` -> {errors.getvalue().strip()}")
                except argparse.ArgumentError as exc:
                    self.fail(f"{source}: `cadgen {' '.join(argv)}` -> {exc}")
                except Exception as exc:  # a hand-written parser's own error type
                    self.fail(f"{source}: `cadgen {' '.join(argv)}` -> {exc}")


if __name__ == "__main__":
    unittest.main()
