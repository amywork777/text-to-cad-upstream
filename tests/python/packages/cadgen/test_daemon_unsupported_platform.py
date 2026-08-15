"""What the daemon does where it cannot run: nothing, quietly, and builds stay cold.

The daemon speaks AF_UNIX, which CPython does not provide on Windows. That was harmless
while warm builds were opt-in -- a Windows user never set CADGEN_WARM, so the socket code
was never reached. Serving warm by default puts it on the path of `cadgen step gen`,
`dxf artifact`, and every viewer build, so the gap has to be handled rather than hit.

It cannot be handled by catching: `socket.AF_UNIX` raises AttributeError, while every
fallback in the client and its callers is keyed on OSError or on a None return, so the
exception escapes all of them and the command dies instead of building.

These tests simulate the platform rather than skipping off it, so the guard is verified
everywhere and cannot regress on the machines where it is impossible to reproduce.
"""

from __future__ import annotations

import contextlib
import io
import socket
import unittest
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages", "cadgen", "src")

from cadgen.cli import daemon_status  # noqa: E402
from cadgen.daemon import client  # noqa: E402


@contextlib.contextmanager
def without_af_unix():
    """Stand in for Windows, where the socket module has no AF_UNIX at all."""
    missing = object()
    original = getattr(socket, "AF_UNIX", missing)
    if original is not missing:
        delattr(socket, "AF_UNIX")
    try:
        yield
    finally:
        if original is not missing:
            socket.AF_UNIX = original


class DaemonSupportedTests(unittest.TestCase):
    def test_it_reports_unsupported_without_af_unix(self):
        with without_af_unix():
            self.assertFalse(client.daemon_supported())

    def test_it_reports_supported_where_af_unix_exists(self):
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("this platform genuinely has no AF_UNIX")
        self.assertTrue(client.daemon_supported())


class EveryEntryPointDegradesToCold(unittest.TestCase):
    """None is this module's "run it cold" answer; each caller already handles it."""

    def test_run_via_daemon_returns_none(self):
        with without_af_unix():
            self.assertIsNone(client.run_via_daemon("gen", ["part.step.py"], "/repo"))

    def test_invoke_returns_none(self):
        with without_af_unix():
            self.assertIsNone(client.invoke("cadgen.step_artifact_cli", ["x"], "/repo"))

    def test_status_returns_none(self):
        with without_af_unix():
            self.assertIsNone(client.status())

    def test_no_socket_is_opened_on_the_way_out(self):
        # The guard has to come before the connect, not around it: reaching socket() at
        # all is the failure, and a test that only asserts None would pass on a machine
        # that happens to have AF_UNIX.
        #
        # side_effect rather than a bare Mock so a regression fails HERE. A plain Mock
        # returns a Mock, whose .recv() is truthy forever, and the caller's read loop
        # never ends -- the guard coming back off turned this test into a hang instead
        # of a failure, which in CI is a ten-minute timeout with nothing to read.
        boom = AssertionError("the daemon was contacted on a platform that has no AF_UNIX")
        with without_af_unix(), mock.patch.object(
            client, "_connect_or_spawn", side_effect=boom
        ) as connect:
            self.assertIsNone(client.run_via_daemon("gen", ["part.step.py"], "/repo"))
            self.assertIsNone(client.invoke("cadgen.step_artifact_cli", ["x"], "/repo"))
        connect.assert_not_called()

    def test_the_gap_must_be_checked_rather_than_caught(self):
        # Why daemon_supported() exists at all. _connect_or_spawn's only recovery is
        # `except OSError`, and this is an AttributeError, so it sails past that handler
        # and every caller's None-keyed fallback with it.
        with without_af_unix():
            with self.assertRaises(AttributeError):
                client._connect_or_spawn(client.socket_path())


class StatusCommandTellsTheTruth(unittest.TestCase):
    def test_it_does_not_promise_a_daemon_that_cannot_start(self):
        # "One starts on the next build" would send a Windows user to wait for a warm
        # process that no build will ever produce.
        out = io.StringIO()
        with without_af_unix(), contextlib.redirect_stdout(out):
            self.assertEqual(0, daemon_status.main([]))
        text = out.getvalue()
        self.assertIn("does not run on this platform", text)
        self.assertNotIn("starts on the next build", text)

    def test_json_output_stays_a_payload(self):
        # --json is consumed by tooling; an unsupported platform is still "nothing warm",
        # not a different shape.
        out = io.StringIO()
        with without_af_unix(), contextlib.redirect_stdout(out):
            self.assertEqual(0, daemon_status.main(["--json"]))
        self.assertEqual("{}", out.getvalue().strip())


if __name__ == "__main__":
    unittest.main()
