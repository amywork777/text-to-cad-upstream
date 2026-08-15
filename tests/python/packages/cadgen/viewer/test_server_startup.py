"""Startup invariants for the runnable Python CAD Viewer backend."""

import contextlib
import io
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import server  # noqa: E402


class ServerStartupTest(unittest.TestCase):
    def test_invalid_cad_runtime_exits_before_binding(self):
        with \
                mock.patch.dict("os.environ", {"VIEWER_CAD_BACKEND_VALIDATED": ""}, clear=False), \
                mock.patch.object(
                    server.cadgen_bridge,
                    "require_cadgen_runtime",
                    side_effect=RuntimeError("No module named 'OCP'"),
                ), \
                mock.patch.object(server, "ThreadingHTTPServer") as http_server, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            rc = server.main(["--port", "4321"])

        self.assertEqual(rc, 1)
        self.assertIn("No module named 'OCP'", stderr.getvalue())
        http_server.assert_not_called()

    def test_valid_cad_runtime_binds_after_probe(self):
        # viewer_dist_dir is stubbed because the built client is a gitignored vite output
        # that only exists after a bundle. This test is about the probe-then-bind order, so
        # depending on a build step would make it fail on a fresh checkout and on the
        # Windows job, which runs the suites without bundling. Absence has its own
        # coverage below.
        with \
                mock.patch.dict("os.environ", {"VIEWER_CAD_BACKEND_VALIDATED": ""}, clear=False), \
                mock.patch.object(
                    server.cadgen_bridge,
                    "require_cadgen_runtime",
                    return_value={"ok": True},
                ) as require_runtime, \
                mock.patch.object(server, "viewer_dist_dir", return_value=pathlib.Path("dist")), \
                mock.patch.object(server, "ThreadingHTTPServer") as http_server, \
                contextlib.redirect_stdout(io.StringIO()):
            rc = server.main(["--port", "4321"])

        self.assertEqual(rc, 0)
        require_runtime.assert_called_once_with(os.getcwd())
        http_server.assert_called_once()
        http_server.return_value.serve_forever.assert_called_once_with()

    def test_a_missing_viewer_client_exits_before_binding(self):
        # The other half of the stub above. A checkout that has never bundled has no client,
        # and the server must say so and stop rather than serve 404s from a live port.
        from cadgen.assets import AssetMissing

        with \
                mock.patch.dict("os.environ", {"VIEWER_CAD_BACKEND_VALIDATED": ""}, clear=False), \
                mock.patch.object(
                    server.cadgen_bridge, "require_cadgen_runtime", return_value={"ok": True}
                ), \
                mock.patch.object(
                    server, "viewer_dist_dir", side_effect=AssetMissing("not built yet")
                ), \
                mock.patch.object(server, "ThreadingHTTPServer") as http_server, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            rc = server.main(["--port", "4321"])

        self.assertEqual(rc, 1)
        self.assertIn("not built yet", stderr.getvalue())
        http_server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
