"""Two things `cadgen <command>` must do BEFORE it imports the command's module.

Both used to live only in the skill launchers, which meant the console script was a
second-class front door for the same work:

* The warm daemon exists to avoid paying the multi-second OCP/build123d import per
  invocation. Handing off after that import would defeat it entirely -- and until this
  moved into dispatch, `cadgen step gen` never handed off at all and ran an order of
  magnitude slower than `scripts/gen` with no indication why.
* PYTHONHASHSEED is read once at interpreter start. A DXF build has to be
  byte-deterministic because drawing packages are content-addressed and ezdxf's object
  ordering depends on hash randomization, so the only way to guarantee it is to re-run.
  Through subprocess, not os.execv -- execv does not quote on Windows, which broke the dxf
  launcher for interpreter paths containing a space (issue #245). The re-run's exit code
  must reach the caller or every generator failure would read as a success.

Neither can be tested by calling a command's `main()`; both are properties of dispatch.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import cadgen.cli as cli  # noqa: E402


class DaemonHandoff(unittest.TestCase):
    def test_the_daemon_serves_exactly_the_step_commands(self):
        # The daemon's _TOOL_IMPORTS are all cadgen.cli.step_*; a dxf or implicit command
        # routed there would import the wrong module.
        from cadgen.daemon import server

        self.assertEqual(set(cli._DAEMON_TOOLS.values()), set(server._TOOL_IMPORTS))
        self.assertTrue(all(name.startswith("step ") for name in cli._DAEMON_TOOLS))

    def test_a_step_command_hands_off_and_never_imports_the_module(self):
        with mock.patch.dict("os.environ", {"CADGEN_WARM": "1"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=7) as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            self.assertEqual(cli.main(["step", "gen", "part.step.py"]), 7)
        daemon.assert_called_once()
        self.assertEqual(daemon.call_args.args[0], "gen")
        self.assertEqual(daemon.call_args.args[1], ["part.step.py"])
        imported.assert_not_called()  # the whole point: no OCP import

    def test_a_daemon_that_declines_falls_through_to_the_module(self):
        with mock.patch.dict("os.environ", {"CADGEN_WARM": "1"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=None), \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            self.assertEqual(cli.main(["step", "gen", "part.step.py"]), 0)
        imported.assert_called_once()

    def test_no_handoff_without_CADGEN_WARM(self):
        with mock.patch.dict("os.environ", {"CADGEN_WARM": "0"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["step", "gen", "x"])
        daemon.assert_not_called()

    def test_the_daemon_child_never_routes_back_to_itself(self):
        with mock.patch.dict(
            "os.environ", {"CADGEN_WARM": "1", "CADGEN_DAEMON_CHILD": "1"}, clear=False
        ), mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["step", "gen", "x"])
        daemon.assert_not_called()

    def test_a_non_step_command_is_never_routed_to_the_daemon(self):
        # PYTHONHASHSEED pinned so the dxf branch does not really re-exec the test runner
        # -- which is exactly what the first draft of this test did.
        with mock.patch.dict(
            "os.environ", {"CADGEN_WARM": "1", "PYTHONHASHSEED": "0"}, clear=False
        ), \
                mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["dxf", "gen", "x"])
        daemon.assert_not_called()


class HashSeedRerun(unittest.TestCase):
    def test_a_dxf_build_reruns_when_the_seed_is_unset(self):
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": ""}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            run.return_value = mock.Mock(returncode=0)
            imported.return_value.main.return_value = 0
            cli.main(["dxf", "gen", "part.dxf.py"])
        run.assert_called_once()
        # Same interpreter, same argv, so the second pass reaches the same command.
        self.assertEqual(run.call_args.args[0][0], sys.executable)
        self.assertNotIn("execv", str(run.call_args))

    def test_the_reruns_exit_code_reaches_the_caller(self):
        # Swallowing it would turn every failed generator into a success.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": ""}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(cli.importlib, "import_module"):
            run.return_value = mock.Mock(returncode=3)
            self.assertEqual(cli.main(["dxf", "gen", "part.dxf.py"]), 3)

    def test_no_rerun_once_the_seed_is_already_stable(self):
        # Otherwise the second pass would spawn again, forever.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["dxf", "gen", "part.dxf.py"])
        run.assert_not_called()

    def test_only_dxf_builds_rerun(self):
        # A STEP build has no ordering sensitivity, and re-running it would cost a whole
        # interpreter start on the daemon's hot path.
        for command in (["step", "gen", "x"], ["dxf", "snapshot", "x"], ["implicit", "gen", "x"]):
            with self.subTest(command=command):
                with mock.patch.dict("os.environ", {"PYTHONHASHSEED": ""}, clear=False), \
                        mock.patch("subprocess.run") as run, \
                        mock.patch.object(cli.importlib, "import_module") as imported:
                    imported.return_value.main.return_value = 0
                    cli.main(command)
                run.assert_not_called()

    def test_the_seed_is_set_before_the_child_starts(self):
        recorded = {}

        def capture(*args, **kwargs):
            recorded["seed"] = cli.os.environ.get("PYTHONHASHSEED")
            return mock.Mock(returncode=0)

        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": ""}, clear=False), \
                mock.patch("subprocess.run", side_effect=capture), \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["dxf", "artifact", "x"])
        # The child inherits the environment, so it must be set before the spawn.
        self.assertEqual(recorded.get("seed"), "0")


if __name__ == "__main__":
    unittest.main()
