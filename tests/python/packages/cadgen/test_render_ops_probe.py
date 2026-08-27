"""The CAD-runtime probe: what `render_ops probe` (the JS server's availability
check) validates, and that a failure's detail survives to the caller."""

import unittest
from unittest import mock

from cadgen import render_ops


class ProbeTest(unittest.TestCase):
    def test_probe_checks_required_imports(self):
        with mock.patch.object(render_ops.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            result = render_ops.probe_cadgen_runtime("")
        command = run.call_args[0][0]
        self.assertIn("import OCP", command[2])
        self.assertIn("import build123d", command[2])
        self.assertIn("import cadgen.step_artifact_cli", command[2])
        self.assertTrue(result["ok"])

    def test_probe_preserves_import_failure(self):
        with mock.patch.object(render_ops.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'OCP'"
            )
            result = render_ops.probe_cadgen_runtime("")
        self.assertFalse(result["ok"])
        self.assertIn("No module named 'OCP'", result["error"])


if __name__ == "__main__":
    unittest.main()
