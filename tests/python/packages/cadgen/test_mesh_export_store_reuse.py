"""Mesh export resolves the STORE render package before touching source.

The export fast path, exercised through the `cadgen stl|3mf|glb build` doors: a
CURRENT model (canonical freshness gate, closure included) exports straight from
its store package — no generator run, no extraction. A stale generated model
rebuilds from source so exports can never serve old geometry (the #308 class),
in ONE extraction and writing nothing but its own format. An imported model
missing its package warms the SHARED store once via the same build
`cadgen step build` runs, then every later export reuses it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

REPO = Path(__file__).resolve().parents[4]
PYTHON = sys.executable


def _write_model(root: Path, size: float) -> Path:
    entry = root / "block.py"
    entry.write_text(textwrap.dedent(f"""\
        SIZE = {size}

        from cadgen import step
        @step
        def model():
            from build123d.topology import Solid
            block = Solid.make_box(SIZE, SIZE, SIZE)
            block.label = "block"
            return block
        """))
    return entry


class MeshExportStoreReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mesh-export-store-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.store = self.root / "store"
        self.env = dict(os.environ)
        self.env.update({
            "CADGEN_DAEMON": "0",
            "CADGEN_COMPONENT_WORKERS": "1",
            "CADGEN_CACHE_DIR": str(self.store),
            "PYTHONPATH": str(REPO / "packages/cadgen/src"),
        })

    def _run(self, argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PYTHON, *argv], cwd=str(cwd), env=self.env,
            capture_output=True, text=True, timeout=600,
        )

    def _export(self, fmt: str, target: str, *flags: str) -> subprocess.CompletedProcess:
        module = {"stl": "stl_build", "3mf": "threemf_build", "glb": "glb_build"}[fmt]
        code = f"from cadgen.cli.{module} import main; raise SystemExit(main())"
        proc = subprocess.run(
            [PYTHON, "-c", code, target, "--verbose", *flags],
            cwd=str(self.root), env=self.env, capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def _package_dirs(self) -> set[str]:
        packages = self.store / "packages"
        if not packages.is_dir():
            return set()
        return {p.name for p in packages.iterdir() if p.is_dir()}

    def test_generated_current_reuses_stale_rebuilds_and_imported_warms(self) -> None:
        entry = _write_model(self.root, size=6.0)
        build = self._run([entry.name], self.root)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        step_file = self.root / "block.step"
        self.assertTrue(step_file.is_file(), "model script writes its STEP")

        # CURRENT generated model: each door exports from the store package. No
        # generator run, no extraction.
        for fmt in ("stl", "glb", "3mf"):
            current = self._export(fmt, "block.py")
            self.assertIn("reusing current render package", current.stderr)
            self.assertNotIn("run gen_step", current.stderr)
            self.assertNotIn("extract exact geometry", current.stderr)
            self.assertTrue(step_file.with_suffix(f".{fmt}").is_file(), fmt)
        stl_current = step_file.with_suffix(".stl").read_bytes()

        # STALE generated model: the closure gate must reject the package and
        # rebuild from source — one extraction, and the door writes only its own
        # format (no .step, and the model stays stale for the next door).
        _write_model(self.root, size=9.0)
        step_before = step_file.read_bytes()
        stale = self._export("stl", "block.py")
        self.assertNotIn("reusing current render package", stale.stderr)
        self.assertIn("run gen_step", stale.stderr)
        self.assertEqual(stale.stderr.count("extract exact geometry started"), 1)
        self.assertEqual(step_before, step_file.read_bytes(), "a mesh door writes no .step")
        stl_stale = step_file.with_suffix(".stl").read_bytes()
        self.assertNotEqual(stl_current, stl_stale, "stale export must re-run the generator")

        # IMPORTED model with no package: the first export warms the shared
        # store via the same build `cadgen step build` runs; the second resolves
        # it without building.
        imported = self.root / "imported_block.step"
        imported.write_bytes(step_file.read_bytes() + b"\n")
        before = self._package_dirs()
        self._export("glb", "imported_block.step")
        self.assertTrue(imported.with_suffix(".glb").is_file())
        after_first = self._package_dirs()
        self.assertEqual(len(after_first - before), 1, "one store package built by export")
        again = self._export("stl", "imported_block.step")
        self.assertEqual(self._package_dirs(), after_first, "second export builds nothing")
        self.assertNotIn("extract exact geometry", again.stderr)


if __name__ == "__main__":
    unittest.main()
