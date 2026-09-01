"""Every `python -m`-invokable cadgen CLI module must actually run when invoked.

A module that defines a top-level ``main()`` but has no ``__main__`` guard
exits 0 silently under ``python -m`` — the caller gets a success code and no
work (this shipped once: ``cadgen.cli.step_snapshot`` was documented as a
module entrypoint and did nothing). The guard is one line and easy to forget,
so it is policy-checked here rather than re-reviewed each time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI_DIR = ROOT / "packages" / "cadgen" / "src" / "cadgen" / "cli"

MAIN_DEF = re.compile(r"^def main\(", re.MULTILINE)
GUARD = re.compile(r"^if __name__ == \"__main__\":", re.MULTILINE)


class CliMainGuardTest(unittest.TestCase):
    def test_every_cli_module_with_a_main_has_the_module_guard(self) -> None:
        missing: list[str] = []
        checked = 0
        for path in sorted(CLI_DIR.rglob("*.py")):
            if path.name == "__main__.py":  # executed directly by -m on the package
                continue
            text = path.read_text(encoding="utf-8")
            if not MAIN_DEF.search(text):
                continue
            checked += 1
            # cli/__init__.py is dispatched through cli/__main__.py, which owns
            # the guard for the package form (`python -m cadgen.cli`).
            if path.name == "__init__.py":
                continue
            if not GUARD.search(text):
                missing.append(str(path.relative_to(ROOT)))
        self.assertGreater(checked, 5, "audit walked no CLI modules — wrong path?")
        self.assertEqual(
            missing,
            [],
            "CLI modules with a main() but no __main__ guard (silent no-op under "
            f"python -m): {missing}",
        )


if __name__ == "__main__":
    unittest.main()
