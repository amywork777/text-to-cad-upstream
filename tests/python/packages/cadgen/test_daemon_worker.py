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


class Allowlist(unittest.TestCase):
    def test_it_covers_every_producer_and_nothing_else(self):
        dispatch = worker._module_dispatch()
        self.assertEqual(
            set(dispatch),
            {
                "cadgen.dxf_export_target",
                "cadgen.implicit_artifact",
                "cadgen.implicit_export",
                "cadgen.step_artifact_cli",
                "cadgen.step_export_target",
            },
        )
        for name, entry in dispatch.items():
            with self.subTest(module=name):
                self.assertTrue(callable(entry))


if __name__ == "__main__":
    unittest.main()
