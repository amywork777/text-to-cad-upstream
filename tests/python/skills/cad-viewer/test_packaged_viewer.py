"""Static pins on the cad-viewer skill's packaged layout and documented command.

The LIVE boot smoke that once lived here is now `scripts/test/test-viewer-launch.sh`,
which launches the bundled runtime and reads the port off the `--json` line. What it
does NOT pin is the command and port the SKILL doc hands an agent. These tests keep
the documented launch line and the base port honest, so the doc cannot drift away
from the runtime it describes.
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
        self.assertTrue(
            (VIEWER_APP / "server" / "main.py").is_file(),
            "the Python entrypoint the SKILL documents must ship",
        )
        self.assertTrue(
            (VIEWER_APP / "server" / "collation.json").is_file(),
            "the collation table is RUNTIME data, not a fixture: without it the "
            "catalog sorts differently in production than in tests",
        )

    def test_package_json_still_carries_the_version(self):
        # npm starts nothing any more, but the file stays: the release workflow
        # refuses to publish without it, and its .version is what the launcher's
        # reuse key (realpath(root) x version) compares.
        self.assertTrue((VIEWER_APP / "package.json").is_file())
        package = json.loads((VIEWER_APP / "package.json").read_text(encoding="utf-8"))
        self.assertTrue(package.get("version"), "the runtime package.json must carry a version")

    def test_skill_md_documents_the_start_command_and_default_port(self):
        # The launcher has no directory flag: the cwd IS the served directory,
        # so the documented command cd's into the workspace first and names
        # main.py by absolute path.
        skill_md = (VIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/viewer/server/main.py --host 127.0.0.1 --json", skill_md)
        self.assertIn("cd /absolute/project/models", skill_md)
        self.assertNotIn("--root", skill_md, "the retired directory flag must not be documented")
        self.assertIn("3245", skill_md)

    def test_skill_md_no_longer_advertises_the_retired_npm_door(self):
        # `npm run start` was declared, shipped without its launcher, and stayed
        # broken for eighteen releases because nothing executed it. It is gone;
        # this keeps it gone.
        skill_md = (VIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("npm --prefix scripts/viewer run start", skill_md)
        self.assertNotIn("main.mjs", skill_md)

    def test_requirements_name_cadgen_as_the_import_path_dependency(self):
        # The Viewer server is stdlib-only Python; cadgen is named here because
        # this interpreter is the ONLY door the STEP-import path has to it.
        # Deliberately unvendored, and unpinned until release stamps it.
        requirements = (VIEWER_SKILL / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("cadgen", requirements)
        self.assertNotIn("cadgen[", requirements, "no extras: the Viewer never renders headlessly")


if __name__ == "__main__":
    unittest.main()
