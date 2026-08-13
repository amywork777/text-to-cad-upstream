"""Which directories count as third-party when classifying a generator's source closure.

The classification decides what gets EVICTED from ``sys.modules`` before a build. Getting
it wrong for an installed package is not a near-miss: eviction forces a re-import, and a
C extension re-imported mid-process fails with an error that names something else
entirely (numpy reports a missing ``dtypes`` attribute). This was found by running the
CLI against a real wheel install whose dependencies came from a ``.pth`` line -- a
site-packages that belonged to no interpreter prefix, and so looked like model code.
"""

import sys
import unittest
from pathlib import Path

from cadgen._internal import source_hash


class InterpreterRoots(unittest.TestCase):
    def setUp(self):
        source_hash._interpreter_roots.cache_clear()
        source_hash._excluded_roots.cache_clear()
        source_hash.is_first_party_source_file.cache_clear()
        source_hash._MODULE_FILE_FIRST_PARTY.clear()
        self.addCleanup(source_hash._interpreter_roots.cache_clear)
        self.addCleanup(source_hash._excluded_roots.cache_clear)
        self.addCleanup(source_hash.is_first_party_source_file.cache_clear)
        self.addCleanup(source_hash._MODULE_FILE_FIRST_PARTY.clear)

    def test_a_site_packages_reached_by_pth_is_third_party(self):
        """Not every site-packages belongs to sys.prefix."""
        extra = Path("/tmp/some-other-venv/lib/python3.13/site-packages").resolve()
        sys.path.append(str(extra))
        self.addCleanup(sys.path.remove, str(extra))
        source_hash._interpreter_roots.cache_clear()
        source_hash._excluded_roots.cache_clear()
        source_hash.is_first_party_source_file.cache_clear()

        self.assertFalse(
            source_hash.is_first_party_source_file(extra / "numpy" / "__init__.py"),
            "a site-packages on sys.path must be third-party wherever it came from",
        )

    def test_dist_packages_counts_too(self):
        extra = Path("/tmp/debianish/lib/python3/dist-packages").resolve()
        sys.path.append(str(extra))
        self.addCleanup(sys.path.remove, str(extra))
        source_hash._interpreter_roots.cache_clear()
        source_hash._excluded_roots.cache_clear()
        source_hash.is_first_party_source_file.cache_clear()

        self.assertFalse(source_hash.is_first_party_source_file(extra / "pkg" / "mod.py"))

    def test_ordinary_model_code_is_still_first_party(self):
        """The point of the closure: a generator beside the model must NOT be excluded."""
        self.assertTrue(
            source_hash.is_first_party_source_file(Path("/tmp/models/widget.step.py").resolve())
        )

    def test_the_running_cadgen_is_never_first_party(self):
        self.assertFalse(
            source_hash.is_first_party_source_file(Path(source_hash.__file__).resolve())
        )


if __name__ == "__main__":
    unittest.main()
