"""The running-instance registry behind `cadgen viewer list` / `cadgen viewer stop`.

One viewer serves any directory by URL, so instances never differ by what they serve --
they differ by which checkout's code answers a port, which is what this registry records
and what makes a port collision diagnosable instead of mysterious.

Two invariants matter more than the rest, and both are about NOT trusting a file:

* Liveness is an HTTP identity probe, never `os.kill(pid, 0)` -- that idiom terminates
  the target on Windows, and a recycled pid would make us trust a stranger.
* A stale entry naming a port that something else now holds must be reaped, never acted
  on. `stop` killing an unrelated process is the worst thing this code could do.

Every test isolates `registry_dir` into a tmp directory. Without that they would read the
developer's own running viewers and could reap -- or stop -- them.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.cli import viewer_list, viewer_stop  # noqa: E402
from cadgen.viewer import registry  # noqa: E402


class _IsolatedRegistry:
    """Point the registry at a throwaway directory for the duration of a test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tmp-viewer-registry-")
        self.path = os.path.join(self._tmp.name, "cadgen-viewer-info")
        self._patch = mock.patch.object(registry, "registry_dir", lambda: self.path)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()
        return False


class _FakeViewer:
    """A server that answers /__cad/server with a chosen pid, so identity can be faked."""

    def __init__(self, pid: int):
        self.reported_pid = pid

    def __enter__(self):
        reported_pid = self.reported_pid

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                body = json.dumps({"pid": reported_pid}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)
        return False


def _dead_pid() -> int:
    """A pid that has certainly exited (reaped, so it cannot be reused mid-test)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class EntryFile(unittest.TestCase):
    def test_register_writes_a_complete_entry_and_unregister_removes_it(self):
        with _IsolatedRegistry() as reg:
            path = registry.register("127.0.0.1", 3245)
            self.assertTrue(path and os.path.isfile(path))
            entry = json.loads(pathlib.Path(path).read_text())
            self.assertEqual(entry["pid"], os.getpid())
            self.assertEqual(entry["port"], 3245)
            self.assertEqual(entry["host"], "127.0.0.1")
            # The field the whole module exists for: whose code is this.
            self.assertTrue(entry["packageDir"].endswith(os.path.join("cadgen")))
            self.assertTrue(entry["version"])
            self.assertGreater(entry["startedAt"], 0)

            registry.unregister()
            self.assertFalse(os.path.exists(path))
            self.assertEqual(os.listdir(reg.path), [])

    def test_no_temp_file_is_left_behind(self):
        with _IsolatedRegistry() as reg:
            registry.register("127.0.0.1", 3245)
            self.assertEqual(
                [n for n in os.listdir(reg.path) if n.endswith(".tmp")],
                [],
                "atomic write leaked its temp file",
            )

    def test_registry_dir_is_private(self):
        with _IsolatedRegistry() as reg:
            registry.register("127.0.0.1", 3245)
            if hasattr(os, "getuid"):
                self.assertEqual(os.stat(reg.path).st_mode & 0o777, 0o700)

    def test_public_url_comes_from_the_environment(self):
        # Dev spawns the backend on an ephemeral port behind vite, so the URL a human
        # should open cannot be derived from host:port.
        with _IsolatedRegistry(), mock.patch.dict(
            os.environ, {"CADGEN_VIEWER_PUBLIC_URL": "http://127.0.0.1:5173/"}
        ):
            path = registry.register("127.0.0.1", 54321)
            self.assertEqual(json.loads(pathlib.Path(path).read_text())["publicUrl"], "http://127.0.0.1:5173/")

    def test_a_registry_that_cannot_be_written_does_not_raise(self):
        # Best-effort by contract: a viewer that cannot register must still serve.
        with _IsolatedRegistry(), mock.patch.object(registry, "_ensure_registry_dir", return_value=None):
            self.assertEqual(registry.register("127.0.0.1", 3245), "")


class Liveness(unittest.TestCase):
    def test_an_entry_whose_port_answers_with_a_matching_pid_is_live(self):
        with _IsolatedRegistry(), _FakeViewer(pid=4242) as viewer:
            entry = {"pid": 4242, "host": "127.0.0.1", "port": viewer.port}
            self.assertTrue(registry.probe(entry))
            self.assertEqual([e["port"] for e in registry.live_entries()], [])  # not on disk yet

    def test_a_dead_entry_is_reaped_from_the_listing(self):
        with _IsolatedRegistry() as reg:
            registry.register("127.0.0.1", 1, pid=_dead_pid())  # nothing listening on port 1
            self.assertEqual(len(os.listdir(reg.path)), 1)
            self.assertEqual(registry.live_entries(), [])
            self.assertEqual(os.listdir(reg.path), [], "stale entry was not reaped")

    def test_a_port_taken_over_by_a_stranger_is_not_trusted(self):
        # The dangerous case: the recorded viewer died and something ELSE now answers
        # that port. Matching only on port would make `stop` kill an innocent process.
        with _IsolatedRegistry() as reg, _FakeViewer(pid=999999) as viewer:
            registry.register("127.0.0.1", viewer.port, pid=_dead_pid())
            self.assertEqual(registry.live_entries(), [])
            self.assertEqual(os.listdir(reg.path), [])

    def test_corrupt_entries_are_ignored_and_reaped(self):
        with _IsolatedRegistry() as reg:
            os.makedirs(reg.path, mode=0o700, exist_ok=True)
            pathlib.Path(reg.path, "viewer-1.json").write_text("{not json")
            pathlib.Path(reg.path, "viewer-2.json").write_text('{"port": "nope"}')
            self.assertEqual(registry.live_entries(), [])

    def test_listing_is_oldest_first(self):
        with _IsolatedRegistry() as reg:
            os.makedirs(reg.path, mode=0o700, exist_ok=True)
            for pid, started in ((11, 200.0), (12, 100.0)):
                pathlib.Path(reg.path, f"viewer-{pid}.json").write_text(
                    json.dumps({"pid": pid, "port": 9000 + pid, "host": "127.0.0.1", "startedAt": started})
                )
            with mock.patch.object(registry, "probe", return_value=True):
                self.assertEqual([e["pid"] for e in registry.live_entries()], [12, 11])


class ListCommand(unittest.TestCase):
    def test_empty_registry_says_so(self):
        with _IsolatedRegistry(), mock.patch("sys.stdout") as out:
            self.assertEqual(viewer_list.main([]), 0)
        self.assertIn("No CAD Viewer is running", "".join(c.args[0] for c in out.write.call_args_list))

    def test_json_output_is_the_raw_entries(self):
        import io
        import contextlib

        with _IsolatedRegistry(), _FakeViewer(pid=os.getpid()) as viewer:
            registry.register("127.0.0.1", viewer.port)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(viewer_list.main(["--json"]), 0)
            entries = json.loads(buffer.getvalue())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["port"], viewer.port)
        self.assertEqual(entries[0]["pid"], os.getpid())

    def test_a_row_names_the_checkout(self):
        row = viewer_list.format_entry(
            {"port": 3245, "pid": 42, "version": "0.4.9", "packageDir": "/x/y/cadgen", "startedAt": time.time()}
        )
        self.assertIn("port 3245", row)
        self.assertIn("pid 42", row)
        self.assertIn("cadgen 0.4.9", row)
        self.assertIn("/x/y/cadgen", row)


class StopCommand(unittest.TestCase):
    def test_stop_requires_a_target(self):
        with _IsolatedRegistry():
            self.assertEqual(viewer_stop.main([]), 2)

    def test_stop_reports_when_nothing_matches(self):
        with _IsolatedRegistry():
            self.assertEqual(viewer_stop.main(["--port", "3245"]), 1)

    def test_stop_refuses_a_stale_entry_whose_port_a_stranger_holds(self):
        with _IsolatedRegistry(), _FakeViewer(pid=999999) as viewer, mock.patch("os.kill") as kill:
            registry.register("127.0.0.1", viewer.port, pid=_dead_pid())
            self.assertEqual(viewer_stop.main(["--port", str(viewer.port)]), 1)
        kill.assert_not_called()

    def test_stop_terminates_a_real_viewer_and_clears_its_entry(self):
        """End to end against a REAL backend, isolated by TMPDIR.

        registry_dir() sits under tempfile.gettempdir(), which honours TMPDIR, so the
        child writes into the same throwaway directory the parent is patched to read.
        """
        import socket

        with tempfile.TemporaryDirectory(prefix="tmp-viewer-stop-") as tmp:
            registry_path = os.path.join(tmp, "cadgen-viewer-info")
            with socket.socket() as probe:  # claim then release a free port
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]

            env = dict(os.environ, TMPDIR=tmp, VIEWER_CAD_BACKEND_VALIDATED="1")
            env["PYTHONPATH"] = str(pathlib.Path(registry.__file__).resolve().parents[2])
            child = subprocess.Popen(
                [sys.executable, "-m", "cadgen.viewer.server", "--port", str(port)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                with mock.patch.object(registry, "registry_dir", lambda: registry_path):
                    deadline = time.time() + 10
                    while time.time() < deadline and not registry.live_entries():
                        time.sleep(0.2)
                    self.assertEqual(
                        [e["port"] for e in registry.live_entries()], [port],
                        "the child viewer never registered itself",
                    )
                    self.assertEqual(viewer_stop.main(["--port", str(port)]), 0)
                    child.wait(timeout=5)
                    self.assertEqual(registry.live_entries(), [])
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)


class Dispatch(unittest.TestCase):
    """`viewer list` must beat one-word `viewer`, or the launcher eats "list"."""

    def test_two_word_commands_are_registered(self):
        from cadgen.cli import _COMMANDS

        self.assertEqual(_COMMANDS["viewer list"][0], "cadgen.cli.viewer_list")
        self.assertEqual(_COMMANDS["viewer stop"][0], "cadgen.cli.viewer_stop")
        self.assertEqual(_COMMANDS["viewer"][0], "cadgen.viewer.start_viewer")

    def test_dispatch_prefers_the_two_word_match(self):
        import cadgen.cli as cli

        # autospec matters: dispatch passes prog= only when the target's signature
        # accepts it, and a bare Mock has no signature to inspect.
        with mock.patch.object(viewer_list, "main", autospec=True, return_value=0) as listed, \
                mock.patch.object(registry, "live_entries", return_value=[]):
            cli.main(["viewer", "list"])
        listed.assert_called_once()
        self.assertEqual(listed.call_args.args[0], [])
        self.assertEqual(listed.call_args.kwargs.get("prog"), "cadgen viewer list")


if __name__ == "__main__":
    unittest.main()
