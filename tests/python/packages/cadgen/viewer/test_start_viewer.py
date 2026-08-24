"""Tests for the single-port CAD Viewer launcher (cadgen.viewer.start_viewer).

Cover the two branches (start when the port is free / error when it is occupied),
port selection, the URL shape, and the --json contract, with the port probe and
backend spawn stubbed so no network or child process is touched.

The launcher takes no directory: a page URL's path is the directory, so the
launcher only reports a URL for the cwd it happens to run in.
"""

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import start_viewer as sav  # noqa: E402


class _FakeChild:
    def __init__(self, code=0):
        self._code = code

    def wait(self):
        return self._code


@contextlib.contextmanager
def _run(argv, port_free=True, child_code=0, cad_backend_error=""):
    """Run main() with the port probe + backend spawn stubbed; yield
    (rc, out, err, calls)."""
    calls = {"spawn": []}

    def fake_spawn(host, port, dist_root="", root=""):
        calls["spawn"].append((host, port))
        calls.setdefault("dist", []).append(dist_root)
        calls.setdefault("root", []).append(root)
        return _FakeChild(child_code)

    out, err = io.StringIO(), io.StringIO()
    probe_effect = RuntimeError(cad_backend_error) if cad_backend_error else None
    with mock.patch.object(sav, "port_is_free", return_value=port_free), \
            mock.patch.object(sav, "spawn_backend", side_effect=fake_spawn), \
            mock.patch.object(sav.cadgen_bridge, "require_cadgen_runtime", side_effect=probe_effect), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = sav.main(argv)
    yield rc, out.getvalue(), err.getvalue(), calls


class ViewerUrlTest(unittest.TestCase):
    """The URL is the bare origin. The served directory is not in it.

    It used to be: the absolute directory WAS the URL path, like a file:// URL, so one
    instance could serve any folder. A viewer serves one root now, given by --root, so
    the path carries nothing and `?file=` selects within that root.
    """

    def test_the_url_is_the_bare_origin(self):
        self.assertEqual("http://127.0.0.1:3245/", sav.viewer_url("127.0.0.1", 3245))

    def test_the_url_does_not_depend_on_the_directory(self):
        # The old signature took a directory and spliced it in. Nothing about the served
        # root may reach the URL now -- the server already knows it.
        first = sav.viewer_url("127.0.0.1", 3245)
        with contextlib.chdir(pathlib.Path(__file__).parent):
            second = sav.viewer_url("127.0.0.1", 3245)
        self.assertEqual(first, second)

    def test_the_port_is_honoured(self):
        self.assertEqual("http://127.0.0.1:4321/", sav.viewer_url("127.0.0.1", 4321))


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_starts_when_port_free(self):
        with _run([], port_free=True) as (rc, out, err, calls):
            self.assertEqual(rc, 0)
            self.assertIn("CAD Viewer URL:", out)
            self.assertEqual(len(calls["spawn"]), 1)
            # default port is 3245
            self.assertEqual(calls["spawn"][0][1], sav.DEFAULT_VIEWER_PORT)

    def test_occupied_errors_without_rolling(self):
        with _run(["--port", "3245"], port_free=False) as (rc, out, err, calls):
            self.assertEqual(rc, 1)
            self.assertIn("3245", err)
            self.assertIn("--port", err)
            self.assertEqual(calls["spawn"], [])

    def test_dir_flag_is_gone(self):
        """The root flag is --root, not --dir; argparse must not adopt the old name."""
        parser_argv = ["--dir", self.directory]
        with _run(parser_argv, port_free=True) as (rc, _out, _err, calls):
            # parse_known_args ignores the unknown flag rather than adopting it as a root.
            self.assertEqual(rc, 0)
            self.assertEqual(len(calls["spawn"]), 1)

    def test_the_root_reaches_the_backend(self):
        # The backend does the containment checking, so a --root the child never receives
        # is a viewer serving the wrong directory with no sign anything is wrong.
        with _run(["--root", self.directory], port_free=True) as (rc, _out, _err, calls):
            self.assertEqual(rc, 0)
            self.assertEqual(calls["root"], [os.path.abspath(self.directory)])

    def test_a_root_that_is_not_a_directory_refuses_to_start(self):
        missing = os.path.join(self.directory, "no-such-directory")
        with _run(["--root", missing], port_free=True) as (rc, _out, err, calls):
            self.assertEqual(rc, 1)
            self.assertIn("not a directory", err)
            self.assertEqual(calls["spawn"], [])

    def test_custom_port_is_used(self):
        with _run(["--port", "4321"], port_free=True) as (rc, out, err, calls):
            self.assertEqual(rc, 0)
            self.assertEqual(calls["spawn"][0][1], 4321)

    def test_start_propagates_child_exit_code(self):
        with _run([], port_free=True, child_code=3) as (rc, out, err, calls):
            self.assertEqual(rc, 3)

    def test_invalid_cad_backend_refuses_to_start(self):
        with _run(
            [],
            port_free=True,
            cad_backend_error="No module named 'OCP'",
        ) as (rc, out, err, calls):
            self.assertEqual(rc, 1)
            self.assertEqual(calls["spawn"], [])
            self.assertNotIn("CAD Viewer URL:", out)
            self.assertIn("No module named 'OCP'", err)

    def test_json_output_start(self):
        with _run(["--json"], port_free=True) as (rc, out, err, calls):
            payload = json.loads([ln for ln in out.splitlines() if ln.startswith("{")][-1])
            self.assertEqual(payload["action"], "start")
            self.assertEqual(payload["port"], sav.DEFAULT_VIEWER_PORT)
            self.assertTrue(payload["url"].startswith("http://"))
            # The served directory is the server's, not the URL's: it appears neither as
            # the path (the old file://-style form) nor as a ?dir= query.
            self.assertNotIn("?dir=", payload["url"])
            self.assertNotIn(pathlib.Path.cwd().as_posix(), payload["url"])


class OpenBrowserFlagTest(unittest.TestCase):
    """`--open` is opt-in: agents start this viewer far more often than humans do, so the
    default inverts Jupyter's auto-open. Everything about it is best-effort -- the URL on
    stdout stays the real interface, and no browser problem may fail a start."""

    def test_default_never_opens_a_browser(self):
        with mock.patch.object(sav, "open_when_ready") as opener, \
                _run(["--port", "4321"]) as (rc, out, _err, _calls):
            self.assertEqual(rc, 0)
            opener.assert_not_called()
        self.assertIn("CAD Viewer URL:", out)

    def test_open_flag_opens_the_printed_url(self):
        with mock.patch.object(sav, "open_when_ready", return_value=True) as opener, \
                _run(["--port", "4321", "--open"]) as (rc, out, _err, _calls):
            self.assertEqual(rc, 0)
            opener.assert_called_once()
            opened_url = opener.call_args.args[0]
        # Exactly the URL the user was told about, not a reconstruction.
        self.assertIn(f"CAD Viewer URL: {opened_url}", out)

    def test_stdout_contract_is_unchanged_by_the_flag(self):
        """Agents parse these lines; --open may add stderr noise but not touch stdout."""
        with mock.patch.object(sav, "open_when_ready", return_value=True), \
                _run(["--port", "4321", "--open", "--json"]) as (_rc, with_open, _e, _c):
            pass
        with _run(["--port", "4321", "--json"]) as (_rc, without_open, _e, _c):
            pass
        self.assertEqual(with_open, without_open)


class OpenWhenReadyTest(unittest.TestCase):
    """The poll-then-open helper in isolation."""

    def test_opens_once_the_backend_answers(self):
        response = mock.MagicMock()
        response.status = 200
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=response), \
                mock.patch("webbrowser.open", return_value=True) as opener:
            self.assertTrue(sav.open_when_ready("http://127.0.0.1:4321/", "127.0.0.1", 4321))
        opener.assert_called_once_with("http://127.0.0.1:4321/")

    def test_timeout_warns_and_never_opens(self):
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")), \
                mock.patch("webbrowser.open") as opener, \
                contextlib.redirect_stderr(err):
            self.assertFalse(
                sav.open_when_ready("http://127.0.0.1:4321/", "127.0.0.1", 4321, timeout_s=0.25)
            )
        opener.assert_not_called()
        self.assertIn("did not answer", err.getvalue())

    def test_a_raising_browser_is_reported_not_propagated(self):
        response = mock.MagicMock()
        response.status = 200
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", return_value=response), \
                mock.patch("webbrowser.open", side_effect=RuntimeError("no display")), \
                contextlib.redirect_stderr(err):
            self.assertFalse(sav.open_when_ready("http://127.0.0.1:4321/", "127.0.0.1", 4321))
        self.assertIn("Could not open a browser", err.getvalue())


if __name__ == "__main__":
    unittest.main()
