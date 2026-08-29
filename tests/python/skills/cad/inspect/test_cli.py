"""The inspect front door: `cadgen step inspect` (the skill shims are gone)."""

from __future__ import annotations

import subprocess
import sys
import unittest


class InspectCliFrontDoorTests(unittest.TestCase):
    def test_front_door_help_names_the_cadgen_verb(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "cadgen.cli", "step", "inspect", "--help"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("usage: cadgen step inspect", result.stdout)

    def test_inspect_help_does_not_import_heavy_cad_modules(self) -> None:
        code = (
            "import sys; "
            "import cadgen.cli.step_inspect.cli; "
            "print('OCP.OCP' in sys.modules); "
            "print('cadgen._internal.step_scene' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertEqual(["False", "False"], result.stdout.strip().splitlines())

    def test_inspect_rejects_render_subcommand(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "cadgen.cli", "step", "inspect", "render", "--help"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
