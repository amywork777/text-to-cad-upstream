"""POST /__cad/reveal — "show this file in Finder".

The client has called this route and viewer/docs/backend.md has documented it since the
0.4.0 client landed, but no backend ever implemented it here: the only implementation
lives on an unmerged branch. The menu item was live (it shows whenever the backend
reports `local-fs`) and answered 405, surfacing an error in the UI.

Nothing here spawns a real file manager: the OS call is mocked, and the module also
honours VIEWER_DISABLE_NATIVE_REVEAL=1 so an accidental call in CI cannot pop a window.
"""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import backend as backend_mod  # noqa: E402
from cadgen.viewer import reveal, server  # noqa: E402


class _LiveServer:
    def __enter__(self):
        self._prev = (server._Ctx.backend, server._Ctx.host, server._Ctx.port, server._Ctx.dist_root)
        server._Ctx.backend = backend_mod.LocalAssetBackend()
        server._Ctx.host = "127.0.0.1"
        server._Ctx.dist_root = ""

        class _Quiet(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass

        self.httpd = _Quiet(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        server._Ctx.port = self.port
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)
        server._Ctx.backend, server._Ctx.host, server._Ctx.port, server._Ctx.dist_root = self._prev
        return False

    def post(self, path: str, *, guard: bool = True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, headers={server.POST_GUARD_HEADER: "1"} if guard else {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()


class _Tree:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tmp-viewer-reveal-")
        self.root = pathlib.Path(self._tmp.name).resolve()
        (self.root / "widget.step").write_text("solid")
        (self.root.parent / "outside.step").write_text("secret")
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class RevealRoute(unittest.TestCase):
    def test_revealing_an_entry_calls_the_file_manager_with_that_path(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path", return_value={"ok": True}) as revealer:
            target = tree.root / "widget.step"
            status, body = live.post(f"/__cad/reveal?dir={tree.root}&file={target}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        revealer.assert_called_once()
        self.assertEqual(os.path.realpath(revealer.call_args.args[0]), os.path.realpath(str(target)))

    def test_a_missing_entry_is_404_and_reveals_nothing(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path") as revealer:
            status, _ = live.post(f"/__cad/reveal?dir={tree.root}&file={tree.root / 'nope.step'}")
        self.assertEqual(status, 404)
        revealer.assert_not_called()

    def test_a_path_outside_the_root_is_refused(self):
        # Reveal resolves through the same containment as every other asset route.
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path") as revealer:
            status, _ = live.post(
                f"/__cad/reveal?dir={tree.root}&file={tree.root.parent / 'outside.step'}"
            )
        self.assertNotEqual(status, 200)
        revealer.assert_not_called()

    def test_the_cross_site_gate_applies(self):
        # It spawns a process, so this matters more here than on any other route.
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path") as revealer:
            status, _ = live.post(
                f"/__cad/reveal?dir={tree.root}&file={tree.root / 'widget.step'}", guard=False
            )
        self.assertEqual(status, 403)
        revealer.assert_not_called()

    def test_an_unsupported_platform_reports_501(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path", return_value={"unsupported": True}):
            status, body = live.post(f"/__cad/reveal?dir={tree.root}&file={tree.root / 'widget.step'}")
        self.assertEqual(status, 501)
        self.assertFalse(json.loads(body)["ok"])

    def test_a_failing_file_manager_reports_500_with_its_message(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path", return_value={"ok": False, "error": "boom"}):
            status, body = live.post(f"/__cad/reveal?dir={tree.root}&file={tree.root / 'widget.step'}")
        self.assertEqual(status, 500)
        self.assertIn("boom", json.loads(body)["error"])


class GeneratorSources(unittest.TestCase):
    """A `.step.py` generator must be revealable even though it is not a served asset.

    `asset_path_for_file_ref` asks `is_served_cad_asset`, which excludes `.py` -- correct
    for "may the server stream these bytes", wrong for "may the file manager show this
    file". Reveal therefore uses `contained_path_for_file_ref`, which keeps the root and
    hidden-path rules and drops the extension filter. The first draft of this route used
    the streaming resolver and 404'd on every Python-backed entry.
    """

    def test_a_step_py_generator_can_be_revealed(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path", return_value={"ok": True}) as revealer:
            generator = tree.root / "widget.step.py"
            generator.write_text("# generator")
            status, _ = live.post(f"/__cad/reveal?dir={tree.root}&file={generator}")
        self.assertEqual(status, 200)
        revealer.assert_called_once()

    def test_containment_still_applies_to_non_asset_files(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path") as revealer:
            outside = tree.root.parent / "outside.step.py"
            outside.write_text("# not yours")
            status, _ = live.post(f"/__cad/reveal?dir={tree.root}&file={outside}")
        self.assertNotEqual(status, 200)
        revealer.assert_not_called()

    def test_hidden_files_are_still_refused(self):
        with _Tree() as tree, _LiveServer() as live, \
                mock.patch.object(reveal, "reveal_path") as revealer:
            hidden = tree.root / ".secret.step.py"
            hidden.write_text("# hidden")
            status, _ = live.post(f"/__cad/reveal?dir={tree.root}&file={hidden}")
        self.assertNotEqual(status, 200)
        revealer.assert_not_called()


class RevealPath(unittest.TestCase):
    """The OS dispatch itself, with the subprocess mocked."""

    def test_disabled_by_environment(self):
        with mock.patch.dict(os.environ, {"VIEWER_DISABLE_NATIVE_REVEAL": "1"}):
            self.assertEqual(reveal.reveal_path(__file__), {"unsupported": True})

    def test_a_missing_path_is_reported_without_spawning(self):
        with mock.patch.object(reveal, "_spawn") as spawn:
            result = reveal.reveal_path("/definitely/not/here.step")
        self.assertFalse(result["ok"])
        spawn.assert_not_called()

    # Each branch is exercised with the PLATFORM simulated rather than the host detected.
    # Gating on the host meant only one of the three was ever checked, and never the one
    # that matters most: the Windows branch does not go through _spawn at all, so a fault
    # in it was invisible on every runner this project has.

    def test_macos_selects_the_file(self):
        with mock.patch.object(reveal.sys, "platform", "darwin"), \
                mock.patch.object(reveal.os, "name", "posix"), \
                mock.patch.object(reveal, "_spawn", return_value={"ok": True}) as spawn:
            self.assertTrue(reveal.reveal_path(__file__)["ok"])
        # -R is what makes Finder select the file rather than open it.
        self.assertEqual(spawn.call_args.args[0][:2], ["open", "-R"])

    def test_windows_selects_the_file_through_explorer(self):
        # Popen, not _spawn: explorer exits nonzero even when it worked, so its exit code
        # carries no information and waiting on it would report a failure that did not
        # happen. The comma in "/select,<path>" is explorer's own syntax, not a typo.
        with mock.patch.object(reveal.sys, "platform", "win32"), \
                mock.patch.object(reveal.os, "name", "nt"), \
                mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertTrue(reveal.reveal_path(__file__)["ok"])
        argv = popen.call_args.args[0]
        self.assertEqual("explorer", argv[0])
        self.assertTrue(argv[1].startswith("/select,"), argv[1])
        self.assertIn("test_reveal.py", argv[1])

    def test_windows_reports_a_missing_explorer_rather_than_raising(self):
        with mock.patch.object(reveal.sys, "platform", "win32"), \
                mock.patch.object(reveal.os, "name", "nt"), \
                mock.patch.object(reveal.subprocess, "Popen", side_effect=OSError("nope")):
            result = reveal.reveal_path(__file__)
        self.assertFalse(result["ok"])
        self.assertIn("explorer", result["error"])

    def test_linux_opens_the_containing_folder(self):
        # No portable "reveal and select" on Linux, so the folder is opened instead —
        # the directory, never the file, which is the part worth pinning.
        with mock.patch.object(reveal.sys, "platform", "linux"), \
                mock.patch.object(reveal.os, "name", "posix"), \
                mock.patch.object(reveal, "_spawn", return_value={"ok": True}) as spawn:
            self.assertTrue(reveal.reveal_path(__file__)["ok"])
        argv = spawn.call_args.args[0]
        self.assertEqual("xdg-open", argv[0])
        self.assertEqual(str(pathlib.Path(__file__).parent), argv[-1])

    def test_linux_falls_through_to_the_next_opener(self):
        # xdg-open is absent on plenty of desktops; the chain is the point.
        attempts = []

        def spawn(argv):
            attempts.append(argv[0])
            if argv[0] == "xdg-open":
                return {"ok": False, "error": "could not run xdg-open"}
            return {"ok": True}

        with mock.patch.object(reveal.sys, "platform", "linux"), \
                mock.patch.object(reveal.os, "name", "posix"), \
                mock.patch.object(reveal, "_spawn", side_effect=spawn):
            self.assertTrue(reveal.reveal_path(__file__)["ok"])
        self.assertEqual(["xdg-open", "gio"], attempts)

    def test_a_nonzero_exit_becomes_an_error(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="no such thing\n")
            self.assertEqual(reveal._spawn(["open", "-R", "/x"]), {"ok": False, "error": "no such thing"})


if __name__ == "__main__":
    unittest.main()
