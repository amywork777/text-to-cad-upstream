"""What must happen BEFORE the heavy imports, at both front doors.

`cadgen <command>` dispatch hands off to the warm daemon before importing the
command's module (the daemon exists to avoid paying the multi-second
OCP/build123d import per invocation). Directly-run model scripts do the same
inside the @step/@dxf decorator (cadgen.authoring), which also owns the DXF
hash-seed re-exec: drawing packages are content-addressed and ezdxf's object
ordering depends on hash randomization, so a COLD @dxf run re-runs once with
PYTHONHASHSEED pinned — through subprocess, not os.execv (issue #245: execv
does not quote on Windows). The re-run's exit code must reach the caller or
every generator failure would read as a success.

Neither is testable by calling a command's `main()`; they are properties of
dispatch and of the decorator respectively.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import cadgen.cli as cli  # noqa: E402
from cadgen import authoring  # noqa: E402


class DaemonHandoff(unittest.TestCase):
    def test_every_routed_command_has_a_tool_the_daemon_knows(self):
        # A command mapped to a name the daemon does not import would fail at runtime
        # with nothing useful; this is the only place the two registries meet. "run"
        # is served without a cadgen.cli command: its front door is the @step/@dxf
        # decorator on a directly-executed model script.
        from cadgen.daemon import server

        self.assertEqual(set(cli._DAEMON_TOOLS.values()) | {"run"}, set(server._TOOL_IMPORTS))

    def test_the_served_set_is_the_non_generation_step_tools(self):
        # Generation has no CLI (library-first): model scripts dispatch themselves
        # via the decorator, so dispatch serves only the remaining STEP tools.
        self.assertEqual(
            set(cli._DAEMON_TOOLS),
            {"step export", "step build", "step inspect", "step snapshot"},
        )

    def test_a_step_command_hands_off_and_never_imports_the_module(self):
        with mock.patch.dict("os.environ", {"CADGEN_DAEMON": "1"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=7) as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            self.assertEqual(cli.main(["step", "export", "part.step"]), 7)
        daemon.assert_called_once()
        self.assertEqual(daemon.call_args.args[0], "export")
        self.assertEqual(daemon.call_args.args[1], ["part.step"])
        imported.assert_not_called()  # the whole point: no OCP import

    def test_a_daemon_that_declines_falls_through_to_the_module(self):
        with mock.patch.dict("os.environ", {"CADGEN_DAEMON": "1"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=None), \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            self.assertEqual(cli.main(["step", "export", "part.step"]), 0)
        imported.assert_called_once()

    def test_no_handoff_when_explicitly_disabled(self):
        # Warm is the default now; CADGEN_DAEMON=0 is the opt-out.
        with mock.patch.dict("os.environ", {"CADGEN_DAEMON": "0"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["step", "export", "x"])
        daemon.assert_not_called()

    def test_the_daemon_child_never_routes_back_to_itself(self):
        with mock.patch.dict(
            "os.environ", {"CADGEN_DAEMON": "1", "CADGEN_DAEMON_CHILD": "1"}, clear=False
        ), mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                mock.patch.object(cli.importlib, "import_module") as imported:
            imported.return_value.main.return_value = 0
            cli.main(["step", "export", "x"])
        daemon.assert_not_called()

    def test_an_unserved_command_is_never_routed_to_the_daemon(self):
        # The generic snapshot has no warm tool; routing it would import the wrong module
        # in the worker.
        for command in (["snapshot", "x"], ["doctor"]):
            with self.subTest(command=command):
                with mock.patch.dict("os.environ", {"CADGEN_DAEMON": "1"}, clear=False), \
                        mock.patch("cadgen.daemon.client.run_via_daemon") as daemon, \
                        mock.patch.object(cli.importlib, "import_module") as imported:
                    imported.return_value.main.return_value = 0
                    cli.main(command)
                daemon.assert_not_called()


def _defn(fmt: str) -> authoring.ModelDef:
    def fake():
        return None

    return authoring.ModelDef(
        func=fake,
        fmt=fmt,
        script_path=pathlib.Path("/tmp/preimport-model.py"),
        write=None,
        kind=None,
        mesh_tolerance=None,
        mesh_angular_tolerance=None,
    )


class HashSeedRerun(unittest.TestCase):
    """The COLD @dxf re-exec, now owned by the decorator's direct-run path.
    Every case sets CADGEN_DAEMON=0: a served build gets its stable seed from the
    worker's environment instead, so without the opt-out these would route past
    the code they are about."""

    def test_a_dxf_run_reruns_when_the_seed_is_unset(self):
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_DAEMON": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(sys, "argv", ["preimport-model.py"]):
            run.return_value = mock.Mock(returncode=0)
            self.assertEqual(authoring._run_from_main(_defn("dxf")), 0)
        run.assert_called_once()
        # Same interpreter, same script, so the second pass reaches the same model.
        self.assertEqual(run.call_args.args[0][0], sys.executable)
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONHASHSEED"], "0")
        # The re-run must not bounce to the daemon: cold was already decided.
        self.assertEqual(run.call_args.kwargs["env"]["CADGEN_DAEMON"], "0")

    def test_the_reruns_exit_code_reaches_the_caller(self):
        # Swallowing it would turn every failed generator into a success.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_DAEMON": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(sys, "argv", ["preimport-model.py"]):
            run.return_value = mock.Mock(returncode=3)
            self.assertEqual(authoring._run_from_main(_defn("dxf")), 3)

    def test_no_rerun_once_the_seed_is_already_stable(self):
        # Otherwise the second pass would spawn again, forever.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "0", "CADGEN_DAEMON": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(sys, "argv", ["preimport-model.py"]), \
                mock.patch("cadgen.cli._run_model.run_model_argv", return_value=0):
            self.assertEqual(authoring._run_from_main(_defn("dxf")), 0)
        run.assert_not_called()

    def test_step_models_never_rerun(self):
        # A STEP build has no ordering sensitivity; re-running it would cost a whole
        # interpreter start for nothing.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_DAEMON": "0"}, clear=False), \
                mock.patch("subprocess.run") as run, \
                mock.patch.object(sys, "argv", ["preimport-model.py"]), \
                mock.patch("cadgen.cli._run_model.run_model_argv", return_value=0):
            self.assertEqual(authoring._run_from_main(_defn("step")), 0)
        run.assert_not_called()

    def test_a_warm_dxf_run_skips_the_rerun(self):
        # The worker already has a stable seed, so paying an interpreter restart on
        # the warm path would be pure waste.
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "", "CADGEN_DAEMON": "1"}, clear=False), \
                mock.patch("cadgen.daemon.client.run_via_daemon", return_value=0) as daemon, \
                mock.patch("subprocess.run") as rerun, \
                mock.patch.object(sys, "argv", ["preimport-model.py"]):
            self.assertEqual(authoring._run_from_main(_defn("dxf")), 0)
        daemon.assert_called_once()
        self.assertEqual(daemon.call_args.args[0], "run")
        rerun.assert_not_called()


if __name__ == "__main__":
    unittest.main()
