"""Unit tests for the save-dialog env hooks and the cadgen subprocess bridge."""

import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import cadgen_bridge, save_dialog  # noqa: E402

_WORKTREE = pathlib.Path(__file__).resolve().parents[3]


class SaveDialogEnvHooks(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("VIEWER_SAVE_DIALOG_FORCE_PATH", "VIEWER_DISABLE_NATIVE_SAVE_DIALOG")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_forced_path(self):
        os.environ["VIEWER_SAVE_DIALOG_FORCE_PATH"] = "/tmp/out.stl"
        self.assertEqual(save_dialog.pick_save_destination(), {"path": "/tmp/out.stl"})

    def test_forced_cancel(self):
        os.environ["VIEWER_SAVE_DIALOG_FORCE_PATH"] = "__cancel__"
        self.assertEqual(save_dialog.pick_save_destination(), {"cancelled": True})

    def test_disabled_is_unsupported(self):
        os.environ["VIEWER_DISABLE_NATIVE_SAVE_DIALOG"] = "1"
        self.assertEqual(save_dialog.pick_save_destination(), {"unsupported": True})


class CadpyPythonpath(unittest.TestCase):
    def test_forwards_the_explicit_pythonpath_override(self):
        # cadgen is importable in-process and children are spawned with sys.executable, so
        # nothing is discovered any more -- but the explicit override must still reach the
        # child, which is how a caller points one at a different cadgen.
        with mock.patch.dict(os.environ, {"VIEWER_CAD_PYTHONPATH": "/tmp/other-cadgen/src"}):
            pp = cadgen_bridge.cadgen_pythonpath()
        self.assertIn("/tmp/other-cadgen/src", pp.split(os.pathsep))

    def test_cadgen_runtime_probe_checks_required_imports(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(cadgen_bridge.subprocess, "run", return_value=completed) as run:
            result = cadgen_bridge.probe_cadgen_runtime(str(_WORKTREE))
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-c"])
        self.assertIn("import OCP", command[2])
        self.assertIn("import build123d", command[2])
        self.assertIn("import cadgen.step_artifact_cli", command[2])

    def test_cadgen_runtime_probe_preserves_import_failure(self):
        completed = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="ModuleNotFoundError: No module named 'OCP'"
        )
        with mock.patch.object(cadgen_bridge.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "No module named 'OCP'"):
                cadgen_bridge.require_cadgen_runtime(str(_WORKTREE))


if __name__ == "__main__":
    unittest.main()
