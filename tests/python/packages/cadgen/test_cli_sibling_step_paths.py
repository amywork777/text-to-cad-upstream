"""`step gen` and `step artifact` must derive the same logical STEP path from one target.

Both commands turn a generator target into the STEP beside it, and the two halves of that
derivation used to disagree on Windows: the ".step.py" branch slices the string and keeps
whatever separator the caller typed, while the fallback built a Path and rendered it with
str(), which uses the NATIVE separator. So "parts/second.py" became "parts\\second.step"
while "parts/second.step.py" stayed "parts/second.step" -- one logical path spelled two
ways, which is enough to break a SOURCE=OUTPUT pair.

step_gen was fixed when the Windows runner went in. step_artifact holds the same helper and
was not, because nothing compared them. This does.
"""

from __future__ import annotations

import unittest
from pathlib import PureWindowsPath
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages", "cadgen", "src")

from cadgen.cli.step_artifact import _sibling_step_path  # noqa: E402
from cadgen.cli.step_gen import _sibling_step_output  # noqa: E402

TARGETS = [
    "part.step.py",
    "part.py",
    "parts/second.step.py",
    "parts/second.py",
    "deep/nested/dir/thing.py",
]


class BothCommandsAgree(unittest.TestCase):
    def test_they_derive_the_same_path_for_every_target_shape(self):
        for target in TARGETS:
            with self.subTest(target=target):
                self.assertEqual(_sibling_step_output(target), _sibling_step_path(target))

    def test_a_directory_target_keeps_forward_slashes(self):
        # The property that actually broke: a separator the caller did not type must not
        # appear, because the result is compared against the source half of the pair.
        for helper in (_sibling_step_output, _sibling_step_path):
            with self.subTest(helper=helper.__name__):
                self.assertEqual("parts/second.step", helper("parts/second.py"))
                self.assertEqual("parts/second.step", helper("parts/second.step.py"))

    def test_the_rendering_rule_the_fix_depends_on(self):
        # Why as_posix() and not str(), stated where it can be checked from any platform:
        # str() on a Windows path renders backslashes, as_posix() does not. PureWindowsPath
        # gives the Windows rendering without needing a Windows runner.
        windows_path = PureWindowsPath("parts/second.py").with_suffix(".step")
        self.assertEqual("parts\\second.step", str(windows_path))
        self.assertEqual("parts/second.step", windows_path.as_posix())

    def test_it_holds_with_windows_path_semantics(self):
        # The checks above compare the two helpers, which agree on POSIX whether or not the
        # fix is present -- str() and as_posix() render identically here, so they would only
        # catch a regression on the Windows runner. Swapping in PureWindowsPath gives each
        # helper Windows' rendering, so the property is enforced on every machine.
        for module, helper in (
            ("cadgen.cli.step_artifact.Path", _sibling_step_path),
            ("cadgen.cli.step_gen.Path", _sibling_step_output),
        ):
            with self.subTest(helper=helper.__name__):
                with mock.patch(module, PureWindowsPath):
                    self.assertEqual("parts/second.step", helper("parts/second.py"))
                    self.assertEqual("parts/second.step", helper("parts/second.step.py"))


if __name__ == "__main__":
    unittest.main()
