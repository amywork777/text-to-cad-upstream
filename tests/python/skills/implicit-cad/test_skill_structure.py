from __future__ import annotations

import unittest

from tests.python.support.paths import repo_path

# The skill is instruction-only over the `cadgen` front door; the ONE thing it still
# ships is the authoring helper library (a tool, not a shim).
EXPECTED_SCRIPT_ENTRIES = ("lib/implicit-cad.mjs",)
FORBIDDEN_SCRIPT_ENTRIES = ("gen", "export.mjs", "snapshot")


class ImplicitCadSkillStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_root = repo_path("skills", "implicit-cad")

    def test_skill_md_exists_with_required_frontmatter(self) -> None:
        source = (self.skill_root / "SKILL.md").read_text(encoding="utf-8")
        head = source.split("---", 2)
        self.assertEqual(3, len(head), "SKILL.md must open with YAML frontmatter")
        self.assertIn("name: implicit-cad", head[1])
        self.assertRegex(head[1], r"description:\s*\S", "description frontmatter must be non-empty")

    def test_agents_openai_yaml_exists(self) -> None:
        agent_file = self.skill_root / "agents" / "openai.yaml"
        self.assertTrue(agent_file.is_file(), "agents/openai.yaml must exist")
        self.assertGreater(agent_file.read_text(encoding="utf-8").strip(), "")

    def test_expected_script_entry_points_exist(self) -> None:
        for rel in EXPECTED_SCRIPT_ENTRIES:
            with self.subTest(entry=rel):
                self.assertTrue(
                    (self.skill_root / "scripts" / rel).exists(),
                    f"scripts/{rel} must exist",
                )

    def test_no_shim_entry_points_return(self) -> None:
        # The per-verb shims were deleted (cadgen implicit gen/export/snapshot are the
        # invocations); a reappearing shim means the deletion regressed.
        for rel in FORBIDDEN_SCRIPT_ENTRIES:
            with self.subTest(entry=rel):
                self.assertFalse(
                    (self.skill_root / "scripts" / rel).exists(),
                    f"scripts/{rel} is a deleted shim and must not return",
                )
