"""The reveal surface: ``POST /__cad/reveal`` and the opener beneath it.

EVERY test here runs with ``VIEWER_DISABLE_NATIVE_REVEAL=1``. Reveal opens a
Finder window on the developer's desktop, so the only branches exercised live
are the disabled one and the refusals that answer BEFORE any opener runs. The
platform branches are pinned by inspecting the command that WOULD be spawned,
never by spawning it — the same discipline the Node suite used, which also only
covered 501 and 404.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server import handler as handler_module  # noqa: E402
from server import reveal as reveal_module  # noqa: E402
from server.http_app import create_cad_app  # noqa: E402

GUARD = {"x-cadgen-viewer": "1"}


class RevealServer(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VIEWER_DISABLE_NATIVE_REVEAL"] = "1"
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "models")
        os.makedirs(os.path.join(self.root, ".hidden"))
        Path(self.root, "part.step").write_text("ISO-10303-21;\n", encoding="utf-8")
        Path(self.root, "model.py").write_text("# a generator\n", encoding="utf-8")
        Path(self.root, ".dotfile.step").write_text("hidden\n", encoding="utf-8")
        Path(self.root, ".hidden", "secret.step").write_text("hidden\n", encoding="utf-8")
        self.outside = os.path.join(self._tmp.name, "outside")
        os.makedirs(self.outside)
        Path(self.outside, "secret.step").write_text("outside\n", encoding="utf-8")

        self.app = create_cad_app(root=self.root, host="127.0.0.1", port=0)
        self.server = handler_module.serve(self.app, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.app.port = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self._teardown)

    def _teardown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def post_reveal(self, file_ref: str, headers=GUARD):
        url = f"http://127.0.0.1:{self.port}/__cad/reveal?file={urllib.parse.quote(file_ref)}"
        request = urllib.request.Request(url, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - loopback
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            return error.code, json.loads(body) if body else None

    def test_disabled_reveal_answers_501(self) -> None:
        status, payload = self.post_reveal(os.path.join(self.root, "part.step"))
        self.assertEqual(status, 501)
        self.assertEqual(payload, {"ok": False, "error": "Revealing files is not supported here"})

    def test_a_missing_entry_answers_404(self) -> None:
        status, payload = self.post_reveal(os.path.join(self.root, "nope.step"))
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"ok": False, "error": "Not found"})

    def test_a_model_script_resolves_here_and_nowhere_else(self) -> None:
        # No served-extension filter on this route: reveal sends no bytes, so a
        # .py resolves (and then hits the disabled 501) where /__cad/asset 404s.
        status, _ = self.post_reveal(os.path.join(self.root, "model.py"))
        self.assertEqual(status, 501, "a .py must RESOLVE for reveal")

        asset = f"http://127.0.0.1:{self.port}/__cad/asset?file={urllib.parse.quote(os.path.join(self.root, 'model.py'))}"
        try:
            with urllib.request.urlopen(asset, timeout=5) as response:  # noqa: S310
                self.fail(f"a .py must never stream, got {response.status}")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)

    def test_a_path_outside_the_root_answers_403(self) -> None:
        status, payload = self.post_reveal(os.path.join(self.outside, "secret.step"))
        self.assertEqual(status, 403)
        self.assertEqual(payload, {"error": "Forbidden"})

    def test_hidden_targets_answer_404(self) -> None:
        for ref in (
            os.path.join(self.root, ".dotfile.step"),
            os.path.join(self.root, ".hidden", "secret.step"),
        ):
            with self.subTest(ref=ref):
                status, payload = self.post_reveal(ref)
                self.assertEqual(status, 404)
                self.assertEqual(payload, {"ok": False, "error": "Not found"})

    def test_a_relative_ref_answers_404(self) -> None:
        # Reveal takes ABSOLUTE refs only, matching asset/download.
        status, _ = self.post_reveal("part.step")
        self.assertEqual(status, 404)

    def test_a_null_byte_answers_400_with_the_post_error_shape(self) -> None:
        status, payload = self.post_reveal(os.path.join(self.root, "part.step") + "\x00.png")
        self.assertEqual(status, 400)
        self.assertEqual(payload, {"ok": False, "error": "File path contains an invalid null byte"})

    def test_reveal_is_behind_the_post_guard(self) -> None:
        status, payload = self.post_reveal(os.path.join(self.root, "part.step"), headers={})
        self.assertEqual(status, 403)
        self.assertIn("x-cadgen-viewer", payload["error"])

    def test_the_asset_query_parameter_is_ignored(self) -> None:
        # The client appends &asset=artifact|output. Reveal always targets the
        # entry itself; the asset=source branch was deliberately deleted.
        url = (
            f"http://127.0.0.1:{self.port}/__cad/reveal"
            f"?file={urllib.parse.quote(os.path.join(self.root, 'part.step'))}&asset=source"
        )
        request = urllib.request.Request(url, method="POST", headers=GUARD)
        try:
            urllib.request.urlopen(request, timeout=5)  # noqa: S310
            self.fail("expected 501")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 501, "asset= must not change the outcome")


class RevealOpener(unittest.TestCase):
    """The opener itself, with every spawn mocked. Nothing is launched."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = os.path.join(self._tmp.name, "a file.step")
        Path(self.target).write_text("x", encoding="utf-8")
        os.environ.pop("VIEWER_DISABLE_NATIVE_REVEAL", None)
        self.addCleanup(lambda: os.environ.__setitem__("VIEWER_DISABLE_NATIVE_REVEAL", "1"))

    def test_the_env_kill_switch_wins_before_anything_else(self) -> None:
        os.environ["VIEWER_DISABLE_NATIVE_REVEAL"] = "1"
        with mock.patch.object(reveal_module.subprocess, "run") as run:
            self.assertEqual(reveal_module.reveal_path("/nonexistent"), {"unsupported": True})
        run.assert_not_called()

    def test_a_missing_target_reports_structurally(self) -> None:
        result = reveal_module.reveal_path(os.path.join(self._tmp.name, "gone.step"))
        self.assertFalse(result["ok"])
        self.assertIn("no such file:", result["error"])

    @unittest.skipUnless(sys.platform == "darwin", "darwin opener")
    def test_darwin_spawns_open_dash_r_as_an_argument_vector(self) -> None:
        with mock.patch.object(reveal_module.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertEqual(reveal_module.reveal_path(self.target), {"ok": True})
        args = run.call_args[0][0]
        # A vector, never a string: a filename with shell metacharacters is an
        # ordinary filename, not an injection.
        self.assertEqual(args, ["open", "-R", self.target])
        self.assertIsInstance(args, list)
        self.assertIs(run.call_args.kwargs.get("shell", False), False)

    def test_a_nonzero_exit_becomes_the_first_stderr_line(self) -> None:
        with mock.patch.object(reveal_module.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "boom\nsecond line\n")
            result = reveal_module.reveal_path(self.target)
        self.assertEqual(result, {"ok": False, "error": "boom"})

    def test_a_timeout_is_caught_into_the_failure_shape(self) -> None:
        # subprocess RAISES where Node's spawnSync set result.error. Letting
        # TimeoutExpired escape would surface as a 500 where Node produced a
        # structured {ok:false,error}.
        with mock.patch.object(reveal_module.subprocess, "run") as run:
            run.side_effect = subprocess.TimeoutExpired(["open"], 10)
            result = reveal_module.reveal_path(self.target)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    def test_a_missing_opener_is_caught_into_the_failure_shape(self) -> None:
        with mock.patch.object(reveal_module.subprocess, "run") as run:
            run.side_effect = FileNotFoundError("No such file or directory: 'open'")
            result = reveal_module.reveal_path(self.target)
        self.assertFalse(result["ok"])
        self.assertIn("could not run", result["error"])

    def test_linux_tries_each_opener_and_gives_up_as_unsupported(self) -> None:
        attempted = []

        def fake_run(args, **kwargs):  # noqa: ARG001
            attempted.append(args)
            raise FileNotFoundError(f"no {args[0]}")

        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(
            reveal_module.subprocess, "run", side_effect=fake_run
        ):
            result = reveal_module.reveal_path(self.target)
        self.assertEqual(result, {"unsupported": True})
        self.assertEqual([a[0] for a in attempted], ["xdg-open", "gio", "nautilus"])
        # gio takes a subcommand; the others take the directory directly, and
        # all three open the CONTAINING folder since there is no portable
        # "reveal and select".
        self.assertEqual(attempted[1], ["gio", "open", self._tmp.name])
        self.assertEqual(attempted[0], ["xdg-open", self._tmp.name])

    def test_linux_stops_at_the_first_opener_that_actually_ran(self) -> None:
        def fake_run(args, **kwargs):  # noqa: ARG001
            if args[0] == "xdg-open":
                raise FileNotFoundError("no xdg-open")
            return subprocess.CompletedProcess(args, 1, "", "gio: permission denied\n")

        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(
            reveal_module.subprocess, "run", side_effect=fake_run
        ):
            result = reveal_module.reveal_path(self.target)
        # A real failure from an opener that EXISTS is the answer; only
        # "could not run" means keep looking.
        self.assertEqual(result, {"ok": False, "error": "gio: permission denied"})


if __name__ == "__main__":
    unittest.main()
