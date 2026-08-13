"""The implicit schema id is written in two places; they must agree.

`skills/implicit-cad/scripts/lib/implicit-cad.mjs` used to import the constant from a
vendored copy of the implicit runtime. Skills no longer vendor anything, so it declares the
id itself — which is correct for a skill that ships alone, and is exactly the kind of
duplication that drifts silently. cadjs remains the source of truth; this fails the moment
they disagree.

The previous arrangement broke without anyone noticing precisely because nothing tested it.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CADJS_SCHEMA = REPO_ROOT / "packages/cadjs/src/lib/implicitCad/schema.js"
SKILL_HELPER = REPO_ROOT / "skills/implicit-cad/scripts/lib/implicit-cad.mjs"


def _literal(path: Path, name: str) -> str:
    match = re.search(
        rf'^export const {re.escape(name)}\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M
    )
    if not match:
        raise AssertionError(f"{path.name} no longer declares {name} as a string literal")
    return match.group(1)


class ImplicitSchemaParity(unittest.TestCase):
    def test_the_skill_helper_matches_cadjs(self):
        self.assertEqual(
            _literal(CADJS_SCHEMA, "IMPLICIT_CAD_SCHEMA"),
            _literal(SKILL_HELPER, "SCHEMA"),
            "skills/implicit-cad's inlined schema id has drifted from cadjs's",
        )

    def test_the_skill_helper_reaches_into_no_repo_package(self):
        """The break this replaces: an import that only resolves in a source checkout."""
        text = SKILL_HELPER.read_text(encoding="utf-8")
        for offender in ("packages/implicitjs", "packages/cadjs", "../packages/"):
            self.assertNotIn(offender, text, f"{SKILL_HELPER.name} reaches into {offender}")


if __name__ == "__main__":
    unittest.main()
