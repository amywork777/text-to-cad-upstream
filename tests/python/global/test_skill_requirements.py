"""A skill that runs cadgen must say so, with the extras it actually reaches.

`requirements.txt` is not documentation: `scripts/release/pin-cadgen-requirements.sh`
rewrites it to `cadgen==<release>` at publish, and it is what an installed skill's
`pip install -r requirements.txt` resolves. A skill that imports cadgen without declaring
it installs nothing and fails at first use; one that renders without the `snapshot` extra
installs fine and then dies inside the headless browser with a playwright ImportError,
which reads as a rendering bug rather than a missing dependency.

Both stated as criteria rather than lists. implicit-cad shipped for months with no
manifest at all, and dxf gained a snapshot command without gaining the extra -- neither
was caught, because nothing derived the expectation from what the skill actually does.

Skills whose Python never touches cadgen (bambu-labs, gcode, step-parts) correctly have
no manifest, so "has Python" is not the trigger. Importing cadgen is.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS = sorted(p for p in (REPO_ROOT / "skills").iterdir() if p.is_dir())

# `cadgen`, `cadgen[snapshot]`, or either pinned -- the publish tree is the pinned form.
_CADGEN_LINE = re.compile(r"^cadgen(?:\[(?P<extras>[a-z0-9_,.-]+)\])?\s*(?:==\s*\S+)?\s*$")


def _declared(skill: Path) -> tuple[bool, set[str]]:
    """(declares cadgen, extras it asks for) from the skill's requirements.txt."""
    manifest = skill / "requirements.txt"
    if not manifest.is_file():
        return False, set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = _CADGEN_LINE.match(line.strip())
        if match:
            return True, set((match.group("extras") or "").split(",")) - {""}
    return False, set()


def _imports_cadgen(skill: Path) -> bool:
    return any(
        "cadgen" in path.read_text(encoding="utf-8")
        for path in skill.rglob("*.py")
        if "__pycache__" not in path.parts
    )


class SkillRequirements(unittest.TestCase):
    def test_skills_were_found(self) -> None:
        self.assertGreaterEqual(len(SKILLS), 8, "the skills/ glob found almost nothing")

    def test_every_skill_that_imports_cadgen_declares_it(self) -> None:
        missing = [s.name for s in SKILLS if _imports_cadgen(s) and not _declared(s)[0]]
        self.assertEqual(
            missing,
            [],
            "these skills import cadgen but do not name it in requirements.txt, so "
            "`pip install -r requirements.txt` installs nothing they need",
        )

    def test_every_rendering_skill_asks_for_the_snapshot_extra(self) -> None:
        """A `scripts/snapshot` shim reaches cadgen.cli.snapshot, which needs playwright.

        Playwright is an extra rather than a base dependency because it is a large install
        plus a browser download, so a skill that renders has to opt in explicitly.
        """
        for skill in SKILLS:
            if not (skill / "scripts" / "snapshot").is_dir():
                continue
            with self.subTest(skill=skill.name):
                declares, extras = _declared(skill)
                self.assertTrue(declares, f"{skill.name} renders but declares no cadgen")
                self.assertIn(
                    "snapshot",
                    extras,
                    f"{skill.name} has scripts/snapshot; it needs cadgen[snapshot] or its "
                    "renders die on a playwright ImportError",
                )

    def test_a_declared_extra_is_one_cadgen_actually_offers(self) -> None:
        """Guards the reverse typo: cadgen[snapshots] installs no extra and never warns."""
        pyproject = (REPO_ROOT / "packages" / "cadgen" / "pyproject.toml").read_text(encoding="utf-8")
        block = pyproject.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
        available = set(re.findall(r"^([a-z0-9_-]+)\s*=", block, re.M))
        self.assertIn("snapshot", available, "cadgen no longer defines a snapshot extra")
        for skill in SKILLS:
            extras = _declared(skill)[1]
            with self.subTest(skill=skill.name):
                self.assertTrue(
                    extras <= available,
                    f"{skill.name} asks for {sorted(extras - available)}, which cadgen does not define",
                )


if __name__ == "__main__":
    unittest.main()
