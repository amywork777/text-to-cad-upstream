"""The two gates that protect a loopback server from the browser.

A localhost CAD Viewer is reachable by any page the user has open, and `POST
/__cad/artifact` executes the target entry's generator. That puts this server in
Jupyter's threat class rather than TensorBoard's, so it needs Jupyter's two
browser-facing defenses:

* **Host validation** stops DNS rebinding, where an attacker domain re-resolves to
  127.0.0.1 so the browser treats us as same-origin and the page can READ responses.
* **A required custom header on POST** stops plain cross-site POSTs. Every param rides
  in the query string and no body is read, which is exactly what makes such a POST a
  no-preflight "simple request"; demanding one custom header forces a preflight that we
  never answer.

Neither gate covers the other's attack -- a cross-site POST carries an honest
`Host: 127.0.0.1:<port>` -- which is why both exist.

These start a real listener rather than mocking one: the behaviour under test is header
handling in BaseHTTPRequestHandler, which a mocked server would not exercise.
"""

from __future__ import annotations

import http.client
import json
import pathlib
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import server  # noqa: E402


class _LiveServer:
    """A real backend on an ephemeral loopback port, with a mocked asset backend so a
    route reaching business logic is observable without a model tree on disk."""

    def __init__(self) -> None:
        self.backend = mock.MagicMock()
        self.backend.read_catalog.return_value = {"entries": []}
        self.backend.resolve_root.return_value = {"dir": "/tmp", "rootPath": "/tmp", "rootName": "tmp"}
        self.backend.generate_export.return_value = {"ok": True, "path": "/tmp/x.step", "filename": "x.step", "format": "step"}

    def __enter__(self):
        self._prev = (server._Ctx.backend, server._Ctx.host, server._Ctx.port, server._Ctx.dist_root)
        server._Ctx.backend = self.backend
        server._Ctx.host = "127.0.0.1"
        server._Ctx.dist_root = ""
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
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

    def request(self, method: str, path: str, *, host: str | None = None, headers: dict | None = None):
        """`host=None` sends no Host header at all (an HTTP/1.0-style client)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            if host is None:
                conn.putrequest(method, path, skip_host=True)
                for key, value in (headers or {}).items():
                    conn.putheader(key, value)
                conn.endheaders()
            else:
                conn.request(method, path, headers={"Host": host, **(headers or {})})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()


GUARD = {server.POST_GUARD_HEADER: "1"}


class HostHeaderCheck(unittest.TestCase):
    """DNS-rebinding defense: a non-local Host name is refused on every method."""

    def test_non_local_host_is_refused_on_reads(self):
        with _LiveServer() as live:
            for path in ("/__cad/server", "/__cad/catalog?dir=/tmp"):
                with self.subTest(path=path):
                    status, body = live.request("GET", path, host="evil.example")
                    self.assertEqual(status, 403)
                    self.assertIn("DNS-rebinding", json.loads(body)["error"])

    def test_non_local_host_is_refused_on_post_before_the_header_gate(self):
        with _LiveServer() as live:
            status, body = live.request("POST", "/__cad/export?dir=/tmp&file=a", host="evil.example", headers=GUARD)
            self.assertEqual(status, 403)
            self.assertIn("DNS-rebinding", json.loads(body)["error"])
            live.backend.generate_export.assert_not_called()

    def test_local_host_names_are_allowed(self):
        with _LiveServer() as live:
            # localhost:12345 is a deliberate port mismatch: the check is name-only, so
            # odd-port instances and the vite dev proxy keep working.
            for host in (f"127.0.0.1:{live.port}", "localhost:12345", f"[::1]:{live.port}", "127.0.0.1"):
                with self.subTest(host=host):
                    status, _ = live.request("GET", "/__cad/server", host=host)
                    self.assertEqual(status, 200)

    def test_absent_host_header_is_allowed(self):
        with _LiveServer() as live:
            status, _ = live.request("GET", "/__cad/server", host=None)
            self.assertEqual(status, 200)

    def test_head_is_covered_by_the_same_check(self):
        with _LiveServer() as live:
            status, _ = live.request("HEAD", "/__cad/server", host="evil.example")
            self.assertEqual(status, 403)


class CrossSitePostGate(unittest.TestCase):
    """A POST without the custom header never reaches the route."""

    def test_post_without_the_header_is_refused_and_has_no_effect(self):
        with _LiveServer() as live:
            status, body = live.request("POST", "/__cad/export?dir=/tmp&file=a&format=step")
            self.assertEqual(status, 403)
            self.assertIn(server.POST_GUARD_HEADER, json.loads(body)["error"])
            # The status alone would not prove the export did not run.
            live.backend.generate_export.assert_not_called()

    def test_artifact_build_without_the_header_never_runs_the_generator(self):
        with _LiveServer() as live:
            status, _ = live.request("POST", "/__cad/artifact?dir=/tmp&file=a")
            self.assertEqual(status, 403)
            live.backend.resolve_artifact.assert_not_called()

    def test_post_with_the_header_reaches_the_route(self):
        with _LiveServer() as live:
            status, _ = live.request("POST", "/__cad/export?dir=/tmp&file=a&format=step", headers=GUARD)
            self.assertNotEqual(status, 403)
            live.backend.generate_export.assert_called_once()

    def test_the_gate_does_not_apply_to_reads(self):
        with _LiveServer() as live:
            status, _ = live.request("GET", "/__cad/server")
            self.assertEqual(status, 200)


class HostAllowancePredicate(unittest.TestCase):
    """`_host_is_allowed` directly, including the branch a real bind cannot reach in CI."""

    def test_loopback_bind_accepts_only_local_names(self):
        for host in ("127.0.0.1:3245", "localhost", "[::1]:3245", "LOCALHOST:80", ""):
            with self.subTest(host=host):
                self.assertTrue(server._host_is_allowed(host, "127.0.0.1"))
        for host in ("evil.example", "evil.example:3245", "attacker.localhost", "127.0.0.1.evil.com"):
            with self.subTest(host=host):
                self.assertFalse(server._host_is_allowed(host, "127.0.0.1"))

    def test_non_loopback_bind_skips_the_check(self):
        # The operator left the loopback trust model deliberately; main() warns on stderr.
        for bound in ("0.0.0.0", "192.168.1.10"):
            with self.subTest(bound=bound):
                self.assertTrue(server._host_is_allowed("evil.example", bound))

    def test_hostname_only_strips_ports_and_brackets(self):
        self.assertEqual(server._hostname_only("[::1]:3245"), "::1")
        self.assertEqual(server._hostname_only("127.0.0.1:3245"), "127.0.0.1")
        self.assertEqual(server._hostname_only("localhost"), "localhost")
        # A trailing non-numeric segment is part of the name, not a port.
        self.assertEqual(server._hostname_only("host:notaport"), "host:notaport")


if __name__ == "__main__":
    unittest.main()
