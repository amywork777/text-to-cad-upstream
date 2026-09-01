"""Run unittest over an explicit list of test FILES, each under its dotted package path.

`python -m unittest tests/python/skills/cad/run/test_cli.py` does load the module by its
dotted path, but when that import fails it reports the failure under the LAST component
only -- `ERROR: test_cli (unittest.loader._FailedTest.test_cli)` -- so the three
`test_cli.py` files under different packages are indistinguishable in the summary, and
a SyntaxError in any one of them aborts the whole run before a single test executes.

This entrypoint imports each file under the dotted name of its path relative to --top
(what `-m unittest` does), and turns a failed import into ONE failing test named by
that full dotted path whose message carries the file and the traceback. It also refuses
a module that resolved to a DIFFERENT file than the one asked for (a sys.path shadow),
which `-m unittest` would run silently.

    python scripts/test/unittest_files.py --top <repo root> <test file>...

The loaded test set is identical to `python -m unittest <files>` run from --top.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
import unittest


def dotted_name(path: str, top: str) -> str:
    relative = os.path.relpath(os.path.abspath(path), top)
    if os.path.isabs(relative) or relative.startswith(os.pardir):
        raise SystemExit(f"unittest_files: {path} is not under --top {top}")
    stem, extension = os.path.splitext(relative)
    if extension != ".py":
        raise SystemExit(f"unittest_files: {path} is not a Python file")
    return stem.replace(os.sep, ".").replace("/", ".")


def _synthetic_test(name: str, body) -> unittest.TestCase:
    # A TestCase whose single method is NAMED by the dotted module path, so the
    # id printed in the summary reads `tests.python.skills.cad.run.test_cli`. This is
    # how unittest's own discovery reports a module it could not import.
    case_class = type("_FailedImport", (unittest.TestCase,), {name: body})
    return case_class(name)


def failed_import_test(name: str, path: str, exception_text: str) -> unittest.TestCase:
    message = f"Failed to import test module {name}\n  file: {path}\n{exception_text}"

    def test_failure(self):
        raise ImportError(message)

    return _synthetic_test(name, test_failure)


def skipped_module_test(name: str, reason: str) -> unittest.TestCase:
    def test_skipped(self):
        raise unittest.SkipTest(reason)

    return _synthetic_test(name, test_skipped)


def load_file(loader: unittest.TestLoader, path: str, top: str) -> unittest.TestSuite:
    name = dotted_name(path, top)
    try:
        module = importlib.import_module(name)
    except unittest.SkipTest as skip:
        return unittest.TestSuite([skipped_module_test(name, str(skip))])
    except BaseException as error:  # noqa: BLE001 - a SyntaxError must not abort the run
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        return unittest.TestSuite([failed_import_test(name, path, traceback.format_exc())])
    module_file = getattr(module, "__file__", None)
    if not module_file or os.path.realpath(module_file) != os.path.realpath(path):
        return unittest.TestSuite(
            [
                failed_import_test(
                    name,
                    path,
                    f"import resolved to a different file: {module_file!r} "
                    "(another sys.path entry shadows this test module)",
                )
            ]
        )
    return loader.loadTestsFromModule(module)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", required=True, help="directory the dotted module paths are relative to")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("files", nargs="+", metavar="TEST_FILE")
    args = parser.parse_args(argv)

    top = os.path.realpath(args.top)
    # `python -m unittest` runs with sys.path[0] == "" (the cwd); `python <script>`
    # puts the SCRIPT's directory there instead. Match -m so tests see the same path.
    sys.path[0] = ""

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(load_file(loader, path, top) for path in args.files)
    runner = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1,
        # unittest.main enables the default warning filter unless -W was given.
        warnings=None if sys.warnoptions else "default",
    )
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
