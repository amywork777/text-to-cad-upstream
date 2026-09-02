"""Run Jake's selected release/0.5 unittest modules against the bundled source."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


TEST_MODULES = (
    "tests.python.skills.cad.run.test_cli",
    "tests.python.skills.cad.import_cli.test_cli",
    "tests.python.skills.cad.inspect.test_cli",
    "tests.python.packages.cadgen.test_doctor",
    "tests.python.packages.cadgen.test_generated_step_fidelity",
    "tests.python.skills.cad.cadgen.test_step_targets",
    "tests.python.skills.cad.cadgen.test_semantic_closure_hash",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-root", required=True, type=Path)
    args = parser.parse_args()

    tests_root = args.tests_root.resolve()
    if not (tests_root / "tests/python/support/paths.py").is_file():
        parser.error(f"Jake test checkout is missing tests/python/support/paths.py: {tests_root}")
    if not (tests_root / "packages/cadgen/src/cadgen/authoring.py").is_file():
        parser.error(f"Jake test checkout does not contain the release/0.5 cadgen source: {tests_root}")

    sys.path.insert(0, str(tests_root))

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(module) for module in TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
