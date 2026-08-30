"""Mesh export resolves the STORE render package before touching source.

The export fast path: a CURRENT model (canonical freshness gate, closure
included) exports straight from its store package — no generator run, no
extraction. A stale generated model rebuilds from source so exports can never
serve old geometry (the #308 class). An imported model missing its package
warms the SHARED store once via the import build, then every later export
reuses it. All requested formats come from ONE extraction and one Node
invocation per run.
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

    def _export(self, target: str, *flags: str) -> subprocess.CompletedProcess:
        code = "from cadgen.cli.step_export import main; raise SystemExit(main())"
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

        # CURRENT generated model: exports from the store package. No generator
        # run, no extraction — and one run serves every requested format.
        first = self._export("block.py", "--stl", "--glb", "--3mf")
        self.assertIn("reusing current render package", first.stderr)
        self.assertNotIn("run gen_step", first.stderr)
        self.assertNotIn("extract exact geometry", first.stderr)
        for suffix in (".stl", ".glb", ".3mf"):
            self.assertTrue(step_file.with_suffix(suffix).is_file(), suffix)
        stl_current = step_file.with_suffix(".stl").read_bytes()

        # STALE generated model: the closure gate must reject the package and
        # rebuild from source — exactly ONE extraction for all formats.
        _write_model(self.root, size=9.0)
        stale = self._export("block.py", "--stl", "--glb")
        self.assertNotIn("reusing current render package", stale.stderr)
        self.assertIn("run gen_step", stale.stderr)
        self.assertEqual(stale.stderr.count("extract exact geometry started"), 1)
        stl_stale = step_file.with_suffix(".stl").read_bytes()
        self.assertNotEqual(stl_current, stl_stale, "stale export must re-run the generator")

        # IMPORTED model with no package: the first export warms the shared
        # store via the import build; the second resolves it without building.
        imported = self.root / "imported_block.step"
        imported.write_bytes(step_file.read_bytes() + b"\n")
        before = self._package_dirs()
        warm = self._export("imported_block.step", "--glb")
        self.assertTrue(imported.with_suffix(".glb").is_file())
        after_first = self._package_dirs()
        self.assertEqual(len(after_first - before), 1, "one store package built by export")
        again = self._export("imported_block.step", "--stl")
        self.assertEqual(self._package_dirs(), after_first, "second export builds nothing")
        self.assertNotIn("extract exact geometry", again.stderr)
        del warm


if __name__ == "__main__":
    unittest.main()
