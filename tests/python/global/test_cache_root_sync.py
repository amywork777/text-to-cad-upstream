"""The user-level cache root is a CROSS-LANGUAGE contract.

Python (cadgen/_internal/cache_paths.py) and JS (cadgenCacheRootDir in
packages/cadjs/src/lib/surf/tessellationCacheFs.mjs, inlined again in
viewer/server/tessCache.mjs) must resolve the SAME directory from the same
environment, or the "one cache warms every consumer" property silently
splits into per-language stores. Same spirit as test_render_contract_sync:
a one-sided change fails here before it can ship.

Also pins the mesh-cache key's tessellator-version salt across languages:
TESSELLATION_VERSION (tessellate.js) == MESH_TESSELLATION_VERSION
(cache_paths.py), and the inline viewer-server copy of the root resolver
against the cadjs original.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from cadgen._internal import cache_paths

ROOT = Path(__file__).resolve().parents[3]
CADJS_FS = ROOT / "packages" / "cadjs" / "src" / "lib" / "surf" / "tessellationCacheFs.mjs"
VIEWER_COPY = ROOT / "viewer" / "server" / "tessCache.mjs"
TESSELLATE_JS = ROOT / "packages" / "cadjs" / "src" / "lib" / "surf" / "tessellate.js"


def _node_resolve_root(env_overrides: dict[str, str]) -> str:
    from cadgen._internal.node_runtime import cad_node_executable

    env = {k: v for k, v in os.environ.items() if k not in {"CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"}}
    env.update(env_overrides)
    module_url = CADJS_FS.resolve().as_uri()
    script = f"import({module_url!r}).then(m => process.stdout.write(m.cadgenCacheRootDir()))"
    result = subprocess.run(
        [str(cad_node_executable()), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


class CacheRootSyncTest(unittest.TestCase):
    def _python_root(self, env_overrides: dict[str, str]) -> str:
        cleared = {"CADGEN_CACHE_DIR": "", "XDG_CACHE_HOME": "", **env_overrides}
        with mock.patch.dict(os.environ, cleared):
            return str(cache_paths.cache_root())

    def test_root_resolution_matches_between_python_and_js(self) -> None:
        cases = [
            {"CADGEN_CACHE_DIR": "/tmp/cadgen-sync-store"},
            # CADGEN_CACHE_DIR wins over the platform convention.
            {"CADGEN_CACHE_DIR": "/tmp/cadgen-sync-store", "XDG_CACHE_HOME": "/tmp/xdg"},
        ]
        if os.name != "nt":
            cases.append({"XDG_CACHE_HOME": "/tmp/cadgen-sync-xdg"})
            cases.append({"HOME": "/tmp/cadgen-sync-home"})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    self._python_root(overrides),
                    _node_resolve_root(overrides),
                    f"cache root diverged between Python and JS for {overrides}",
                )

    def test_viewer_server_inline_copy_matches_cadjs_resolver(self) -> None:
        # The viewer server carries a deliberate inline copy (the bundled
        # skill runtime has no cadjs tree). Pin the copied resolver's BODY,
        # not just its behavior somewhere: the three decision reads must
        # appear in both files.
        for needle in ("CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"):
            for path in (CADJS_FS, VIEWER_COPY):
                self.assertIn(needle, path.read_text(), f"{needle} missing from {path.name}")

    def test_tessellator_version_matches_between_python_and_js(self) -> None:
        match = re.search(r"^export const TESSELLATION_VERSION = (\d+);", TESSELLATE_JS.read_text(), re.MULTILINE)
        assert match, "TESSELLATION_VERSION not found in tessellate.js"
        self.assertEqual(
            int(match.group(1)),
            cache_paths.MESH_TESSELLATION_VERSION,
            "the mesh-cache tessellator-version salt diverged between languages — "
            "bump TESSELLATION_VERSION (tessellate.js) and MESH_TESSELLATION_VERSION "
            "(cache_paths.py) together",
        )

    def test_key_scheme_carries_the_version_salt(self) -> None:
        # Policy: the key must salt the algorithm version. Grep-level pin so a
        # JS-side refactor cannot drop it without failing a Python-side gate.
        cache_js = (ROOT / "packages" / "cadjs" / "src" / "lib" / "surf" / "tessellationCache.js").read_text()
        self.assertIn("-t${TESSELLATION_VERSION}-", cache_js)


if __name__ == "__main__":
    unittest.main()
