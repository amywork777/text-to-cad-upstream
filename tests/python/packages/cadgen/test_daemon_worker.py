"""The worker's `invoke` contract — what the CAD Viewer needs from the pool.

The viewer used to run its own warm-worker system for this, with its own tests. That
system is gone; one pool now serves both the CLI and the viewer, so a terminal build and
a viewer build reuse each other's warm processes. These are the cases from those tests
that were about the CONTRACT rather than the deleted plumbing:

* a build failure comes back as a payload the caller can render, never as a crash — the
  viewer shows `{ok: false, error}` in a card and must not see an exception instead
* the module allowlist is real, because `invoke` names a module over a socket

Everything else those tests covered now lives elsewhere: ping and shutdown in
test_daemon_pool, recycling and respawn in the pool's lifecycle cases, and warm==cold
output in test_warm_output_equivalence.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.daemon import worker  # noqa: E402


class InvokeContract(unittest.TestCase):
    def setUp(self) -> None:
        # _invoke parks the process in tempdir when it finishes, which is right for a
        # worker (it outlives the directories it builds in) and wrong for a test runner:
        # display_path is cwd-relative, so leaking the change makes unrelated suites
        # assert against a different path shape.
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        self.calls: list[tuple] = []

        def echo(args):
            self.calls.append(tuple(args))
            return {"ok": True, "args": list(args)}

        def boom(args):
            raise RuntimeError("kaboom")

        patcher = mock.patch.object(
            worker, "_DISPATCH", {"cadgen.step_artifact_cli": echo, "cadgen.dxf_export_target": boom}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_known_module_is_routed(self):
        result = worker._invoke({"module": "cadgen.step_artifact_cli", "args": ["--x", "1"]})
        self.assertEqual(result, {"ok": True, "args": ["--x", "1"]})
        self.assertEqual(self.calls, [("--x", "1")])

    def test_an_unknown_module_is_a_payload_not_an_import(self):
        result = worker._invoke({"module": "cadgen.nope"})
        self.assertFalse(result["ok"])
        self.assertIn("Unknown cadgen module", result["error"])

    def test_a_failing_build_comes_back_as_a_payload(self):
        # The viewer renders this in a card; an exception escaping here would instead
        # kill the worker and surface as a transport fault with no useful text.
        result = worker._invoke({"module": "cadgen.dxf_export_target"})
        self.assertFalse(result["ok"])
        self.assertIn("kaboom", result["error"])


class MissingWorkingDirectory(unittest.TestCase):
    """A request whose cwd is gone fails the REQUEST, not the worker.

    A worker parks in a tempdir between jobs, so a skipped chdir does not fall back
    to anything sane: the caller's relative paths -- which resolve against the
    process cwd, natively, like every other cadgen path argument -- would resolve
    under the parked tempdir. The job would then read nothing, or write an artifact
    somewhere the caller never looks, and report success. One clear error costs one
    request; the daemon and the worker keep going.
    """

    def setUp(self) -> None:
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        self.frames: list[dict] = []
        emit = mock.patch.object(worker, "_emit", self.frames.append)
        emit.start()
        self.addCleanup(emit.stop)
        # Nothing here should reach the module space; keep the eviction out of it.
        evict = mock.patch.object(worker, "_evict_first_party_modules", lambda: None)
        evict.start()
        self.addCleanup(evict.stop)

        self.ran: list[str] = []

        def main(argv):
            self.ran.append(os.getcwd())
            return 0

        tool_main = mock.patch.object(worker, "_tool_main", lambda tool: main)
        tool_main.start()
        self.addCleanup(tool_main.stop)

        self.live = tempfile.TemporaryDirectory()
        self.addCleanup(self.live.cleanup)
        deleted = tempfile.mkdtemp()
        os.rmdir(deleted)
        self.deleted = deleted

    def _stderr(self) -> str:
        return "".join(
            str(frame.get("data", "")) for frame in self.frames if frame.get("stream") == "stderr"
        )

    def test_a_deleted_cwd_fails_the_request_and_the_worker_serves_the_next_one(self):
        self.assertEqual(worker._run({"tool": "step-build", "argv": [], "cwd": self.deleted}), 1)
        self.assertIn(f"working directory does not exist: {self.deleted}", self._stderr())
        # The tool never ran: running it in the parked tempdir is the failure mode.
        self.assertEqual(self.ran, [])

        self.frames.clear()
        live = str(pathlib.Path(self.live.name).resolve())
        self.assertEqual(worker._run({"tool": "step-build", "argv": [], "cwd": live}), 0)
        self.assertEqual([str(pathlib.Path(seen).resolve()) for seen in self.ran], [live])
        self.assertEqual(self._stderr(), "")

    def test_a_deleted_invoke_repo_root_comes_back_as_a_payload(self):
        with mock.patch.object(worker, "_DISPATCH", {"cadgen.step_artifact_cli": lambda args: {"ok": True}}):
            result = worker._invoke(
                {"module": "cadgen.step_artifact_cli", "args": [], "repo_root": self.deleted}
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], f"working directory does not exist: {self.deleted}")
            # Same worker, next request, unaffected.
            self.assertEqual(
                worker._invoke(
                    {
                        "module": "cadgen.step_artifact_cli",
                        "args": [],
                        "repo_root": str(pathlib.Path(self.live.name).resolve()),
                    }
                ),
                {"ok": True},
            )


class Allowlist(unittest.TestCase):
    def test_it_covers_every_producer_and_nothing_else(self):
        dispatch = worker._module_dispatch()
        self.assertEqual(
            set(dispatch),
            {
                "cadgen.dxf_export_target",
                "cadgen.step_artifact_cli",
                "cadgen.step_export_target",
            },
        )
        import inspect

        for name, entry in dispatch.items():
            with self.subTest(module=name):
                self.assertTrue(callable(entry))
                # The worker calls run(argv) on every one.
                self.assertIn("argv", inspect.signature(entry).parameters)


if __name__ == "__main__":
    unittest.main()
