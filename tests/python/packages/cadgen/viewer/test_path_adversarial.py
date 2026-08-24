"""Path containment, attacked the way this tool category actually gets broken.

Every localhost file-serving tool ships this bug class, repeatedly, in code shaped like
`backend.asset_path_for_file_ref` + `scanner.path_is_inside`:

* Jupyter (GHSA-5789-5fc7-67v3): a prefix-only boundary check plus a normalizer that kept
  `..` let users read directories SIBLING to the root -- the `/root` vs `/root-evil` shape.
* MLflow: a 2024-2026 run of traversal/LFI issues from URI parsing that missed `..`.
* Gradio (CVE-2023-51449): create a subdirectory via the upload endpoint, then `../` out
  of it -- proof that WRITE routes are part of this surface, not just reads.

A viewer instance serves ONE root, fixed at startup, so the guarantee is the strong form:
nothing may escape that root, on any request. It did not always read that way. The root
used to arrive per-request, which meant a request that named no root was checked against
nothing at all -- see `RootIsPinnedAtStartup` below, which is the regression test for
exactly that. These tests exist so the guarantee cannot go quiet again.
"""

from __future__ import annotations

import http.client
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.viewer import backend as backend_mod  # noqa: E402
from cadgen.viewer import scanner, server  # noqa: E402


class _Tree:
    """base/{root,root-evil,outside}: a served root, a sibling sharing its name as a
    string prefix, and an unrelated directory holding the thing an attacker wants.

    Fixtures are .step, not .txt: `is_served_cad_asset` filters by extension BEFORE the
    backend consults containment, so a .txt probe 404s for the wrong reason and every
    denial below would pass vacuously. `test_the_root_itself_still_serves` is the
    control that catches exactly that mistake."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tmp-viewer-adversarial-")
        self.base = pathlib.Path(self._tmp.name).resolve()
        self.root = self.base / "root"
        (self.root / ".hidden").mkdir(parents=True)
        (self.base / "root-evil").mkdir()
        (self.base / "outside").mkdir()
        (self.root / "ok.step").write_text("public")
        (self.root / ".dotfile.step").write_text("DOTFILE-SECRET")
        (self.root / ".hidden" / "secret.step").write_text("HIDDEN-SECRET")
        (self.base / "root-evil" / "stolen.step").write_text("SIBLING-SECRET")
        (self.base / "outside" / "secret.step").write_text("OUTSIDE-SECRET")
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class _LiveServer:
    """Real handler over the REAL LocalAssetBackend -- the containment logic is the
    subject here, so mocking the backend would test nothing."""

    def __init__(self, root: str = ""):
        # The served root, as `cadgen viewer --root` fixes it at startup.
        self._root = str(root or "")

    def __enter__(self):
        self._prev = (
            server._Ctx.backend,
            server._Ctx.host,
            server._Ctx.port,
            server._Ctx.dist_root,
            server._Ctx.directory_root,
        )
        server._Ctx.backend = backend_mod.LocalAssetBackend(self._root)
        server._Ctx.host = "127.0.0.1"
        server._Ctx.dist_root = ""
        server._Ctx.directory_root = self._root
        class _QuietServer(ThreadingHTTPServer):
            # Closing a keep-alive connection mid-request is normal here and would
            # otherwise print a traceback per request, drowning real failures.
            def handle_error(self, request, client_address):
                pass

        self.httpd = _QuietServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        server._Ctx.port = self.port
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)
        (
            server._Ctx.backend,
            server._Ctx.host,
            server._Ctx.port,
            server._Ctx.dist_root,
            server._Ctx.directory_root,
        ) = self._prev
        return False

    def get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()


SECRETS = (b"SIBLING-SECRET", b"OUTSIDE-SECRET", b"HIDDEN-SECRET", b"DOTFILE-SECRET")


class ContainmentPrimitives(unittest.TestCase):
    """`path_is_inside` at the unit level, including the exact Jupyter CVE shape."""

    def test_sibling_sharing_a_name_prefix_is_outside(self):
        # The bug a naive `candidate.startswith(root)` produces, and the one that
        # actually shipped in jupyter_server.
        self.assertFalse(scanner.path_is_inside("/tmp/x/root-evil/stolen.step", "/tmp/x/root"))
        self.assertFalse(scanner.path_is_inside("/tmp/x/rootevil", "/tmp/x/root"))

    def test_genuine_descendants_are_inside(self):
        self.assertTrue(scanner.path_is_inside("/tmp/x/root/a/b.txt", "/tmp/x/root"))
        self.assertTrue(scanner.path_is_inside("/tmp/x/root", "/tmp/x/root"))

    def test_parent_and_traversal_are_outside(self):
        self.assertFalse(scanner.path_is_inside("/tmp/x", "/tmp/x/root"))
        self.assertFalse(scanner.path_is_inside("/tmp/x/root/../outside/s.txt", "/tmp/x/root"))

    def test_relative_helper_rejects_escapes_but_allows_inner_dotdot(self):
        self.assertTrue(scanner.relative_path_stays_inside_root(""))
        self.assertTrue(scanner.relative_path_stays_inside_root("a/b.txt"))
        self.assertFalse(scanner.relative_path_stays_inside_root(".."))
        self.assertFalse(scanner.relative_path_stays_inside_root(".." + os.sep + "x"))
        self.assertFalse(scanner.relative_path_stays_inside_root(os.path.abspath("/etc/passwd.step")))


class AssetRouteEscapes(unittest.TestCase):
    """GET /__cad/asset must never return bytes from outside the SERVED root.

    Note what is absent from every request below: a `dir=` param. There used to be one,
    and containment was computed as `resolved_root or (resolve_root(root_dir) if root_dir
    else None)` and applied under `if active:` -- so a request that simply omitted it was
    checked against nothing. Every test here passed while that hole was open, because
    every test supplied `dir=`. The root is fixed at startup now, so there is no way to
    ask for a request without one.
    """

    def _assert_denied(self, live, tree, file_ref, why):
        status, body = live.get(
            f"/__cad/asset?file={file_ref}"
        )
        with self.subTest(file_ref=file_ref):
            self.assertNotEqual(status, 200, why)
            for secret in SECRETS:
                self.assertNotIn(secret, body, f"{why}: leaked {secret!r}")

    def test_the_root_itself_still_serves(self):
        # A containment test that denies everything proves nothing.
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            status, body = live.get(f"/__cad/asset?file={tree.root / 'ok.step'}")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"public")

    def test_traversal_out_of_the_root_is_denied(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            for file_ref, why in [
                (f"{tree.root}/../outside/secret.step", "raw ../ escape"),
                (f"{tree.root}%2F..%2Foutside%2Fsecret.step", "percent-encoded ../ escape"),
                (f"{tree.root}/..%2foutside%2fsecret.step", "mixed encoding"),
                (f"{tree.root}/..\\outside\\secret.step", "backslash separators"),
                (str(tree.base / "outside" / "secret.step"), "absolute path outside the root"),
            ]:
                self._assert_denied(live, tree, file_ref, why)

    def test_sibling_prefix_directory_is_denied(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            self._assert_denied(
                live, tree, str(tree.base / "root-evil" / "stolen.step"),
                "sibling sharing the root's name prefix (the jupyter_server CVE shape)",
            )

    def test_dot_paths_under_the_root_are_never_served(self):
        # Mirrors Jupyter's allow_hidden=False: dotfiles are invisible even inside root.
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            self._assert_denied(live, tree, str(tree.root / ".dotfile.step"), "dotfile under the root")
            self._assert_denied(
                live, tree, str(tree.root / ".hidden" / "secret.step"), "file in a dot-directory"
            )

    def test_malformed_percent_escapes_do_not_leak(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            self._assert_denied(live, tree, "%2e%2e%2foutside%2fsecret.step", "encoded bare ..")
            self._assert_denied(live, tree, "%zz", "malformed escape")


class LegacyRefererRouteEscapes(unittest.TestCase):
    """GET /__cad/<rel> resolves relative to the Referer's file, so it is a second,
    less obvious path surface -- the one most likely to be forgotten."""

    def test_traversal_in_the_relative_path_is_denied(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            for rel in ("../outside/secret.step", "..%2Foutside%2Fsecret.step", "../../etc/passwd.step"):
                with self.subTest(rel=rel):
                    status, body = live.get(f"/__cad/{rel}")
                    self.assertNotEqual(status, 200)
                    for secret in SECRETS:
                        self.assertNotIn(secret, body)


class SymlinkPolicy(unittest.TestCase):
    """Documents -- rather than changes -- what a symlink out of the root does.

    Jupyter deliberately follows such links (it is the sanctioned escape from its rigid
    root). We have never stated a policy. This test pins today's behaviour so a change
    is a decision rather than an accident; if it starts failing, decide on purpose.
    """

    def test_symlink_pointing_outside_the_root(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            link = tree.root / "escape.step"
            try:
                link.symlink_to(tree.base / "outside" / "secret.step")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")
            status, body = live.get(f"/__cad/asset?file={link}")
            # CURRENT BEHAVIOUR: the link resolves inside the root by name, so it serves.
            # Same posture as Jupyter. Recorded, not endorsed.
            self.assertEqual(status, 200)
            self.assertEqual(body, b"OUTSIDE-SECRET")


class WriteSideParameters(unittest.TestCase):
    """Gradio's CVE came through an upload route, so the write side gets the same look.

    /__cad/export takes `format` from the caller. It must select from a known set, never
    become part of a path.
    """

    def test_export_format_is_not_a_path(self):
        with _Tree() as tree, _LiveServer(root=str(tree.root)) as live:
            conn = http.client.HTTPConnection("127.0.0.1", live.port, timeout=5)
            try:
                conn.request(
                    "POST",
                    f"/__cad/export?file={tree.root / 'ok.step'}"
                    "&format=../../outside/pwned",
                    headers={server.POST_GUARD_HEADER: "1"},
                )
                status = conn.getresponse().status
            finally:
                conn.close()
            self.assertNotEqual(status, 200)
            # Nothing may be created anywhere in the tree from a traversal-shaped format.
            written = [p for p in tree.base.rglob("*pwned*")]
            self.assertEqual(written, [], f"export wrote {written} from a path-shaped format")


if __name__ == "__main__":
    unittest.main()

