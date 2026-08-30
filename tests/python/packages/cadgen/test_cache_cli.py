"""``cadgen cache`` info/gc: dead generations go, live-and-young stays.

The suite builds a synthetic cache root via CADGEN_STORE_DIR — the same knob
that governs every tier — so nothing here touches the developer's real cache.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen._internal.cache_paths import MESH_TESSELLATION_VERSION, cache_root  # noqa: E402
from cadgen.cli import cache as cache_cli  # noqa: E402

OLD = time.time() - 90 * 24 * 3600
FRESH = time.time()


def _touch(path: Path, mtime: float, data: bytes = b"x" * 64) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


class CacheCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cadgen-cache-cli-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {
            "CADGEN_STORE_DIR": str(self.root),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        salt_patch = mock.patch.object(cache_cli, "_opmemo_current_salt", return_value="v2-b123dX")
        salt_patch.start()
        self.addCleanup(salt_patch.stop)

        live_key = f"c0-t{MESH_TESSELLATION_VERSION}-l1.500000e-3-a3.500000e-1"
        self.mesh_live_fresh = _touch(self.root / "meshes" / f"{live_key}.tess", FRESH)
        self.mesh_live_old = _touch(self.root / "meshes" / f"old-t{MESH_TESSELLATION_VERSION}-l1.500000e-3-a3.500000e-1.tess", OLD)
        self.mesh_dead_version = _touch(self.root / "meshes" / "c1-t0-l1.500000e-3-a3.500000e-1.tess", FRESH)
        self.mesh_dead_legacy = _touch(self.root / "meshes" / "c2-l1.500000e-3-a3.500000e-1.tess", FRESH)
        self.op_dead = _touch(self.root / "opmemo" / "v1-b123dOLD" / "aa.brep", FRESH)
        self.op_live_fresh = _touch(self.root / "opmemo" / "v2-b123dX" / "bb.brep", FRESH)
        self.op_live_old = _touch(self.root / "opmemo" / "v2-b123dX" / "cc.brep", OLD)
        self.comp_fresh = _touch(self.root / "components" / "cidA.surf", FRESH)
        self.comp_old = _touch(self.root / "components" / "cidB.surf", OLD)

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cache_cli.main(argv)
        return code, buffer.getvalue()

    def test_store_dir_governs_the_root(self) -> None:
        self.assertEqual(cache_root(), self.root)

    def test_info_identifies_dead_generations(self) -> None:
        code, out = self._run(["info", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["root"], str(self.root))
        opmemo = next(tier for tier in payload["tiers"] if tier["name"] == "opmemo")
        dead = {gen["name"]: gen["dead"] for gen in opmemo["generations"]}
        self.assertEqual(dead, {"v1-b123dOLD": True, "v2-b123dX": False})
        meshes = next(tier for tier in payload["tiers"] if tier["name"] == "meshes")
        dead_bucket = next(gen for gen in meshes["generations"] if gen["dead"])
        self.assertEqual(dead_bucket["entries"], 2)  # -t0- and the unsalted legacy key

    def test_gc_dry_run_deletes_nothing(self) -> None:
        code, out = self._run(["gc", "--dry-run", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["dryRun"])
        for path in (self.mesh_dead_version, self.op_dead, self.comp_old):
            self.assertTrue(path.exists(), path)

    def test_gc_deletes_dead_generations_and_age_sweeps_live_tiers(self) -> None:
        code, _ = self._run(["gc"])
        self.assertEqual(code, 0)
        # Dead by name: gone regardless of age.
        self.assertFalse(self.mesh_dead_version.exists())
        self.assertFalse(self.mesh_dead_legacy.exists())
        self.assertFalse(self.op_dead.parent.exists())
        # Live but old: age-swept.
        self.assertFalse(self.mesh_live_old.exists())
        self.assertFalse(self.op_live_old.exists())
        self.assertFalse(self.comp_old.exists())
        # Live and young: NEVER touched without --all.
        self.assertTrue(self.mesh_live_fresh.exists())
        self.assertTrue(self.op_live_fresh.exists())
        self.assertTrue(self.comp_fresh.exists())

    def test_gc_all_wipes_current_generations_too(self) -> None:
        code, _ = self._run(["gc", "--all"])
        self.assertEqual(code, 0)
        for path in (self.mesh_live_fresh, self.op_live_fresh, self.comp_fresh):
            self.assertFalse(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
