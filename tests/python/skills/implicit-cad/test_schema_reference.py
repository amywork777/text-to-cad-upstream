from __future__ import annotations

import unittest

from tests.python.support.paths import repo_path

# The skill no longer vendors implicitjs, so there is no schema file under scripts/ to point
# at. SKILL.md names the helper module that declares the schema instead, and the definition
# it has to agree with now lives in cadjs and reaches users inside the cadgen wheel.
SCHEMA_DECLARATION = "scripts/lib/implicit-cad.mjs"
SCHEMA_SOURCE_OF_TRUTH = ("packages", "cadjs", "src", "lib", "implicitCad", "schema.js")
SCHEMA_MARKER = "implicit.js/0.1.0"


class ImplicitCadSchemaReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_root = repo_path("skills", "implicit-cad")

    def test_skill_md_names_the_schema_declaration(self) -> None:
        source = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(SCHEMA_DECLARATION, source)

    def test_schema_declaration_resolves(self) -> None:
        helper = self.skill_root / SCHEMA_DECLARATION
        self.assertTrue(helper.is_file(), f"{SCHEMA_DECLARATION} must resolve to a file")
        source = helper.read_text(encoding="utf-8")
        self.assertTrue(source.strip(), f"{SCHEMA_DECLARATION} must not be empty")
        self.assertIn(SCHEMA_MARKER, source)

    def test_schema_declaration_agrees_with_the_source_of_truth(self) -> None:
        schema = repo_path(*SCHEMA_SOURCE_OF_TRUTH)
        self.assertTrue(schema.is_file(), f"{'/'.join(SCHEMA_SOURCE_OF_TRUTH)} must resolve to a file")
        self.assertIn(SCHEMA_MARKER, schema.read_text(encoding="utf-8"))
