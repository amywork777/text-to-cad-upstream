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
    def test_every_routed_command_has_a_tool_the_daemon_knows(self):
        # A command mapped to a name the daemon does not import would fail at runtime
        # with nothing useful; this is the only place the two registries meet.
        from cadgen.daemon import server

        self.assertEqual(set(cli._DAEMON_TOOLS.values()), set(server._TOOL_IMPORTS))

    def test_the_served_set_is_step_and_dxf(self):
        # dxf joined once workers carried PYTHONHASHSEED=0: a served dxf build is
        # deterministic without the interpreter restart the cold path needs.
        self.assertEqual(
            set(cli._DAEMON_TOOLS),
            {"step gen", "step export", "step artifact", "step inspect", "step snapshot",
             "dxf gen", "dxf artifact"},
        )

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

    def test_no_handoff_when_explicitly_disabled(self):
        # Warm is the default now; CADGEN_WARM=0 is the opt-out.
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

    def test_an_unserved_command_is_never_routed_to_the_daemon(self):
        # implicit and the generic snapshot have no warm tool; routing them would import
        # the wrong module in the worker.
        for command in (["implicit", "gen", "x"], ["snapshot", "x"], ["viewer", "list"]):
            with self.subTest(command=command):
                with mock.patch.dict("os.environ", {"CADGEN_WARM": "1"}, clear=False), \
                        mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                        mock.patch.object(cli.importlib, "import_module") as imported:
                    imported.return_value.main.return_value = 0
                    cli.main(command)
                daemon.assert_not_called()

    def test_a_served_dxf_build_skips_the_hash_seed_rerun(self):
        # The worker already has a stable seed, so paying an interpreter restart on the
        # warm path would be pure waste.
        with mock.patch.dict("os.environ", {"CADGEN_WARM": "1", "PYTHONHASHSEED": ""}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=0) as daemon, \
                mock.patch("subprocess.run") as rerun:
            self.assertEqual(cli.main(["dxf", "gen", "x"]), 0)
        daemon.assert_called_once()
        rerun.assert_not_called()


class HashSeedRerun(unittest.TestCase):
    """The COLD re-run. Every case sets CADGEN_WARM=0: warm is the default now, and a
    served build gets its stable seed from the worker's environment instead, so without
    the opt-out these would route past the code they are about."""

    def test_a_dxf_build_reruns_when_the_seed_is_unset(self):
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_WARM": "0"}, clear=False), \
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
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_WARM": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(cli.importlib, "import_module"):
            run.return_value = mock.Mock(returncode=3)
            self.assertEqual(cli.main(["dxf", "gen", "part.dxf.py"]), 3)

    def test_no_rerun_once_the_seed_is_already_stable(self):
        # Otherwise the second pass would spawn again, forever.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "0", "CADGEN_WARM": "0"}, clear=False), \
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
                with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_WARM": "0"}, clear=False), \
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

        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_WARM": "0"}, clear=False), \
                mock.patch("subprocess.run", side_effect=capture), \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["dxf", "artifact", "x"])
        # The child inherits the environment, so it must be set before the spawn.
        self.assertEqual(recorded.get("seed"), "0")


if __name__ == "__main__":
    unittest.main()
