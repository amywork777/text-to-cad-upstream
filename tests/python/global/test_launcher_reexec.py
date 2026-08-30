"""A launcher that re-runs itself must survive an interpreter path with a space in it.

The retired skill launchers pinned ``PYTHONHASHSEED`` by re-running themselves, and the
re-run used ``os.execv``, which on Windows hands the argument vector to the C runtime; the
runtime re-joins it into a command line WITHOUT quoting, so the default all-users interpreter
path ``C:\\Program Files\\Python311\\python.exe`` arrived as two arguments and the child tried
to run ``Files\\Python311\\python.exe`` as a script (issue #245).

The launchers are gone (skills are instruction-only over the ``cadgen`` front door), and the
re-run itself now lives in ONE module, ``cadgen._internal.hash_seed``, shared by the two
callers that own a process to restart: ``cadgen.cli`` dispatch (``cadgen dxf build``) and the
``@dxf`` decorator's direct-run path. Anything that re-runs a command to pin the seed is in
scope, wherever it lives; add new re-runners to ``LAUNCHER_SOURCES`` explicitly.

The bug is Windows-only and CI is Linux, so the guard here is the policy: no re-runner uses
``os.execv``. ``subprocess`` quotes correctly on every platform, and on Windows
``os.execv`` never replaced the process anyway, so nothing was gained by it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# Named explicitly rather than globbed: a glob over cadgen would sweep in modules that
# legitimately exec other programs, and the skill shims a glob used to find are gone.
LAUNCHER_SOURCES = [
    REPO_ROOT / "packages/cadgen/src/cadgen/cli/__init__.py",
    REPO_ROOT / "packages/cadgen/src/cadgen/_internal/hash_seed.py",
    REPO_ROOT / "packages/cadgen/src/cadgen/authoring.py",
]


def launcher_sources() -> list[Path]:
    return [path for path in LAUNCHER_SOURCES if path.is_file()]


class LauncherReExecTest(unittest.TestCase):
    def test_there_are_launchers_to_check(self) -> None:
        self.assertEqual(
            len(launcher_sources()),
            len(LAUNCHER_SOURCES),
            "a named re-runner source is missing from the tree",
        )

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
        # success, which is worse than the crash it replaced. Only the source that actually
        # spawns the child is in scope: its callers hand the code straight up.
        re_runners = [
            path for path in launcher_sources()
            if "subprocess.run(" in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(re_runners, "no listed source performs the hash-seed re-run any more")
        for path in re_runners:
            source = path.read_text(encoding="utf-8")
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
