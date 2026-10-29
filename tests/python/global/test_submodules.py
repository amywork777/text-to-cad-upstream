"""No submodule is checked out by a recursive clone of this repository.

An app pinned here as a submodule (``apps/t3code``) is another repository, fetched
only by someone who asks for it. An agent app that installs the plugin from ``main``
clones it with ``--recurse-submodules``: without ``update = none`` that clone fetches
the whole app, then recurses into the app's own gitlinks, and T3 Code's pinned tree
carries two with no ``.gitmodules`` entry, so the clone exits 128 and the install fails.
``update = none`` makes the clone skip it; ``git submodule update --init --checkout
<path>`` still fetches it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _sections(text: str) -> dict[str, dict[str, str]]:
    """``.gitmodules``' submodule sections, each its keys."""
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        header = re.match(r'^\s*\[submodule\s+"([^"]+)"\]\s*$', line)
        if header:
            current = sections.setdefault(header.group(1), {})
        elif current is not None and (entry := re.match(r"^\s*([A-Za-z]+)\s*=\s*(.*?)\s*$", line)):
            current[entry.group(1).lower()] = entry.group(2)
    return sections


class SubmodulesTest(unittest.TestCase):
    def test_a_recursive_clone_checks_out_no_submodule(self) -> None:
        gitmodules = REPO_ROOT / ".gitmodules"
        if not gitmodules.is_file():
            self.skipTest("no submodules")
        for name, keys in _sections(gitmodules.read_text(encoding="utf-8")).items():
            with self.subTest(submodule=name):
                self.assertEqual(keys.get("update"), "none", f"{name}: a recursive clone would check it out")


if __name__ == "__main__":
    unittest.main()
