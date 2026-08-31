"""Static pins on the cad-viewer skill's packaged layout and documented command.

The LIVE boot smoke that once lived here is now `scripts/test/test-viewer-launch.sh`,
which launches the bundled runtime and reads the port off the `--json` line. What it
does NOT pin is the command and port the SKILL doc hands an agent: it invokes
`node .../server/main.mjs` directly. These tests keep the documented npm door and the
base port honest, so the doc cannot drift away from the runtime it describes.
"""

from __future__ import annotations

import json
import unittest

from tests.python.support.paths import repo_path

VIEWER_SKILL = repo_path("skills", "cad-viewer")
VIEWER_APP = VIEWER_SKILL / "scripts" / "viewer"


class PackagedViewerLayoutTests(unittest.TestCase):
    """The static contract: what must exist for the documented start command to work."""

    def test_the_vendored_viewer_runtime_is_present(self):
        self.assertTrue(VIEWER_APP.is_dir(), "skills/cad-viewer/scripts/viewer must resolve")
        self.assertTrue((VIEWER_APP / "package.json").is_file())
        self.assertTrue(
            (VIEWER_APP / "server" / "main.mjs").is_file(),
            "the Node entrypoint behind `npm run start` must ship",
        )

    def test_package_json_defines_the_start_command(self):
        package = json.loads((VIEWER_APP / "package.json").read_text(encoding="utf-8"))
        self.assertIn("start", package.get("scripts", {}))

    def test_skill_md_documents_the_start_command_and_default_port(self):
        skill_md = (VIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("npm --prefix scripts/viewer run start", skill_md)
        self.assertIn("3245", skill_md)

    def test_requirements_name_cadgen_as_the_soft_dependency(self):
        # Viewing is pure Node; cadgen is named here only so the STEP import path
        # (which spawns it) works. It is deliberately unvendored and unpinned.
        requirements = (VIEWER_SKILL / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("cadgen", requirements)


if __name__ == "__main__":
    unittest.main()
