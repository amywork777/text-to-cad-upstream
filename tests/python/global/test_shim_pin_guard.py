"""Every skill shim that hands off to installed cadgen must check the pin first.

`enforce_requirements_pin` only protects the commands that call it, and the call is one
easily-forgotten line in a file that is otherwise copy-pasted. This test states the rule
by CRITERION rather than by a list of known shims, so a skill added later is covered the
day it lands instead of the day someone remembers.

The criterion is "imports cadgen", not "is a shim": three validate commands
(sdf/srdf/urdf) are self-contained stdlib and never run installed cadgen, so there is no
version to disagree about. Adding the guard there would give them a hard cadgen
dependency they do not have today.

Known and accepted gap: skills/implicit-cad/scripts/export.mjs is a Node shim that execs
`python -m cadgen.cli.implicit_export_js`, so it gets no guard.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIMS = sorted(REPO_ROOT.glob("skills/*/scripts/*/__main__.py"))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


class ShimPinGuard(unittest.TestCase):
    def test_shims_were_found(self) -> None:
        # A glob that silently matches nothing would make every test below vacuous.
        self.assertGreaterEqual(len(SHIMS), 13, "skill shim glob found almost nothing")

    def test_every_cadgen_shim_enforces_the_pin(self) -> None:
        missing = [
            _rel(shim)
            for shim in SHIMS
            if "from cadgen" in (text := shim.read_text(encoding="utf-8"))
            and "enforce_requirements_pin" not in text
        ]
        self.assertEqual(
            missing,
            [],
            "these shims run installed cadgen without checking the pin; add "
            "enforce_requirements_pin(Path(__file__).resolve().parents[2] / 'requirements.txt')",
        )

    def test_the_guard_runs_before_the_warm_daemon_handoff(self) -> None:
        """The daemon serves from the same install, so a mismatch must be caught first."""
        for shim in SHIMS:
            text = shim.read_text(encoding="utf-8")
            if "run_via_daemon" not in text:
                continue
            with self.subTest(shim=_rel(shim)):
                self.assertLess(
                    text.index("enforce_requirements_pin("),
                    text.index("run_via_daemon"),
                    "the pin check must precede the daemon handoff",
                )

    def test_the_guard_resolves_its_own_skill_requirements(self) -> None:
        """parents[2] from skills/<skill>/scripts/<tool>/__main__.py is skills/<skill>/."""
        for shim in SHIMS:
            text = shim.read_text(encoding="utf-8")
            if "enforce_requirements_pin" not in text:
                continue
            with self.subTest(shim=_rel(shim)):
                self.assertIn(
                    'enforce_requirements_pin(Path(__file__).resolve().parents[2] / "requirements.txt")',
                    text,
                )
                self.assertEqual(shim.resolve().parents[2], shim.resolve().parents[3] / shim.parts[-4])

    def test_a_guarded_shim_still_explains_a_missing_cadgen(self) -> None:
        """The guard import is now the FIRST cadgen import, so it owns the friendly error."""
        for shim in SHIMS:
            text = shim.read_text(encoding="utf-8")
            if "enforce_requirements_pin" not in text:
                continue
            with self.subTest(shim=_rel(shim)):
                self.assertIn("cadgen is not installed", text)
                self.assertLess(
                    text.index("cadgen is not installed"),
                    text.index("enforce_requirements_pin("),
                    "the ModuleNotFoundError handler must wrap the guard's own import",
                )


if __name__ == "__main__":
    unittest.main()
