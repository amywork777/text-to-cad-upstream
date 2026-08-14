"""A launcher that re-runs itself must survive an interpreter path with a space in it.

``skills/dxf/scripts/{gen,artifact}`` pin ``PYTHONHASHSEED`` before importing ezdxf, because a
drawing package is content-addressed and ezdxf's object order depends on hash randomization. The
re-run used ``os.execv``, which on Windows hands the argument vector to the C runtime; the
runtime re-joins it into a command line WITHOUT quoting, so the default all-users interpreter
path ``C:\\Program Files\\Python311\\python.exe`` arrived as two arguments and the child tried to
run ``Files\\Python311\\python.exe`` as a script (issue #245).

The same re-run now also lives in ``cadgen.cli``'s dispatch, which owns the hash seed for
``cadgen dxf gen`` / ``dxf artifact`` -- and it was written with the execv form before this
test was widened to see it. Anything that re-runs a command to pin the seed is in scope,
wherever it lives.

The bug is Windows-only and CI is Linux, so the guard here is the policy: no re-runner uses
``os.execv``. ``subprocess`` quotes correctly on every platform, and on Windows
``os.execv`` never replaced the process anyway, so nothing was gained by it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
# cadgen's dispatcher re-runs for the same reason a launcher does, so it is held to the
# same rule. Named explicitly rather than globbed: a glob over cadgen would sweep in
# modules that legitimately exec other programs.
DISPATCH_SOURCE = REPO_ROOT / "packages/cadgen/src/cadgen/cli/__init__.py"


def launcher_sources() -> list[Path]:
    found = sorted(
        path
        for path in SKILLS_DIR.glob("*/scripts/*/__main__.py")
        if "__pycache__" not in path.parts
    )
    if DISPATCH_SOURCE.is_file():
        found.append(DISPATCH_SOURCE)
    return found


class LauncherReExecTest(unittest.TestCase):
    def test_there_are_launchers_to_check(self) -> None:
        self.assertGreater(len(launcher_sources()), 4, "the glob stopped finding launchers")

    def test_no_launcher_re_runs_itself_through_os_execv(self) -> None:
        # Comments are stripped first: a launcher is free to explain why it does NOT use execv.
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in launcher_sources()
            if re.search(
                r"\bos\.execv",
                re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8")),
            )
        ]
        self.assertEqual(
            [],
            offenders,
            "os.execv does not quote on Windows: an interpreter path containing a space "
            "arrives as two arguments. Re-run through subprocess and exit with its return code.",
        )

    def test_the_hash_seed_re_run_passes_the_exit_code_through(self) -> None:
        # A re-run that swallowed the child's status would turn every generator failure into a
        # success, which is worse than the crash it replaced.
        for path in launcher_sources():
            source = path.read_text(encoding="utf-8")
            if "PYTHONHASHSEED" not in source:
                continue
            with self.subTest(launcher=str(path.relative_to(REPO_ROOT))):
                # Two idioms, one property: a launcher raises SystemExit with the
                # child's code, a dispatcher returns it up to its own main().
                self.assertRegex(
                    source,
                    r"(?:SystemExit\(\s*subprocess\.run\(|return subprocess\.run\()",
                    "the re-run must pass the child's return code to its caller",
                )
                self.assertIn(
                    "sys.executable",
                    source,
                    "the re-run must use the same interpreter",
                )


if __name__ == "__main__":
    unittest.main()
