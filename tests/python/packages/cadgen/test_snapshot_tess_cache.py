"""The snapshot host's side of the shared component-tessellation cache.

The page and the export CLI share ONE on-disk store (~/.cache/cadgen/meshes;
codec in packages/cadjs/src/lib/surf/tessellationCache.js). Python never
decodes entries — it stores and serves opaque bytes — so what these tests pin
is the transport contract: name validation (the cache lives OUTSIDE any model
root, so a bad name must be refused, never resolved), the CADGEN_MESH_CACHE=0
bypass, atomic best-effort writes, and read-your-write round-trips.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen.snapshot_core import (  # noqa: E402
    TESS_CACHE_ROUTE_PREFIX,
    SnapshotAssetServer,
    read_tessellation_cache_entry,
    tessellation_cache_dir,
    tessellation_cache_file,
    write_tessellation_cache_entry,
)


class TessellationCacheRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="tess-cache-")
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Path.home() reads HOME on POSIX; guard the assumption this suite rests on.
        self.assertEqual(Path.home(), self.home)

    def route(self, name: str) -> str:
        return f"{TESS_CACHE_ROUTE_PREFIX}{name}"

    def test_round_trip_and_atomic_layout(self) -> None:
        pathname = self.route("c0ffee-l1.500000e-3-a3.500000e-1.tess")
        self.assertIsNone(read_tessellation_cache_entry(pathname))
        self.assertTrue(write_tessellation_cache_entry(pathname, b"TESS-bytes"))
        self.assertEqual(read_tessellation_cache_entry(pathname), b"TESS-bytes")
        entries = sorted(p.name for p in tessellation_cache_dir().iterdir())
        self.assertEqual(entries, ["c0ffee-l1.500000e-3-a3.500000e-1.tess"], "no tmp files left behind")

    def test_bad_names_are_refused_not_resolved(self) -> None:
        for name in (
            "../escape.tess",
            "sub/dir.tess",
            "..%2Fescape.tess",  # unquoted to ../escape.tess
            ".hidden.tess",
            "noext",
            "",
            "a b.tess",
        ):
            self.assertIsNone(tessellation_cache_file(self.route(name)), name)
            self.assertFalse(write_tessellation_cache_entry(self.route(name), b"x"), name)
            self.assertIsNone(read_tessellation_cache_entry(self.route(name)), name)
        self.assertEqual(list(self.home.rglob("*.tess")), [], "nothing may be written for a refused name")

    def test_cache_disabled_env_bypasses_both_directions(self) -> None:
        pathname = self.route("c0-l1.000000e-3-a3.500000e-1.tess")
        with mock.patch.dict(os.environ, {"CADGEN_MESH_CACHE": "0"}):
            # Writes are accepted (the page must not error) but dropped.
            self.assertTrue(write_tessellation_cache_entry(pathname, b"dropped"))
            self.assertIsNone(read_tessellation_cache_entry(pathname))
        self.assertFalse((tessellation_cache_dir()).exists())
        # Re-enabled: the entry was really never written.
        self.assertIsNone(read_tessellation_cache_entry(pathname))

    def test_empty_body_is_accepted_and_dropped(self) -> None:
        pathname = self.route("c0-l1.000000e-3-a3.500000e-1.tess")
        self.assertTrue(write_tessellation_cache_entry(pathname, None))
        self.assertTrue(write_tessellation_cache_entry(pathname, b""))
        self.assertIsNone(read_tessellation_cache_entry(pathname))


class SnapshotAssetServerTests(unittest.TestCase):
    """The loopback bulk-bytes server: same containment as the CDP route,
    CORS for the intercepted page origin, and the tess-cache round trip."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="asset-server-")
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.home / "modelroot"
        self.root.mkdir()
        (self.root / "inside.step").write_bytes(b"ISO-10303-21;")
        (self.home / "outside.secret").write_bytes(b"nope")
        self.active_root: Path | None = self.root
        self.server = SnapshotAssetServer(lambda: self.active_root)
        self.addCleanup(self.server.close)

    def request(self, method: str, path: str, body: bytes | None = None):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"{self.server.base_url}{path}", data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def test_render_asset_containment(self) -> None:
        status, body, headers = self.request("GET", "/__render_asset/inside.step")
        self.assertEqual((status, body), (200, b"ISO-10303-21;"))
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertEqual(headers.get("cache-control"), "no-store")
        status, _, _ = self.request("GET", "/__render_asset/%2e%2e/outside.secret")
        self.assertIn(status, (403, 404), "traversal must never serve bytes")
        self.active_root = None
        status, _, _ = self.request("GET", "/__render_asset/inside.step")
        self.assertEqual(status, 404)

    def test_tess_cache_round_trip_and_preflight(self) -> None:
        name = "cafe01-l1.500000e-3-a3.500000e-1.tess"
        status, _, _ = self.request("GET", f"{TESS_CACHE_ROUTE_PREFIX}{name}")
        self.assertEqual(status, 404)
        status, _, _ = self.request("POST", f"{TESS_CACHE_ROUTE_PREFIX}{name}", b"TESSbytes")
        self.assertEqual(status, 204)
        status, body, _ = self.request("GET", f"{TESS_CACHE_ROUTE_PREFIX}{name}")
        self.assertEqual((status, body), (200, b"TESSbytes"))
        status, _, _ = self.request("POST", f"{TESS_CACHE_ROUTE_PREFIX}%2e%2e/escape.tess", b"x")
        self.assertEqual(status, 403)
        status, _, headers = self.request("OPTIONS", f"{TESS_CACHE_ROUTE_PREFIX}{name}")
        self.assertEqual(status, 204)
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))

    def test_unknown_paths_404(self) -> None:
        for method, path in (("GET", "/anything"), ("POST", "/__render_asset/inside.step")):
            status, _, _ = self.request(method, path)
            self.assertEqual(status, 404, f"{method} {path}")


if __name__ == "__main__":
    unittest.main()
