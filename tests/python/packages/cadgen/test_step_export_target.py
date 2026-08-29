from __future__ import annotations

import json
import shutil
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen import render as cad_render  # noqa: E402
from cadgen import step_export_target  # noqa: E402
from tests.python.support.cad_test_roots import IsolatedCadRoots  # noqa: E402

# A tiny generated model: model() returns a single labeled solid.
BOX_GENERATOR = """from build123d import Box


from cadgen import step
@step
def model():
    return Box(10.0, 10.0, 10.0)
"""

# Magic bytes we can assert on; STL (binary) and 3MF (zip) just get a non-empty check.
FORMAT_MAGIC = {
    "glb": b"glTF",
    "step": b"ISO-10303-21",
    "stl": None,
    "3mf": None,
}
FORMATS = ("step", "stl", "3mf", "glb")


class StepExportTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._isolated_roots = IsolatedCadRoots(self, prefix="cadexp-")
        self._tempdir = self._isolated_roots.temporary_cad_directory(prefix="tmp-cadexp-")
        self.temp_root = Path(self._tempdir.name)
        self.out_dir = self.temp_root / "out"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self._tempdir.cleanup()

    def _run(self, args: list[str]) -> tuple[int, dict]:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = step_export_target.main(args)
        json_lines = [line for line in buffer.getvalue().splitlines() if line.strip().startswith("{")]
        payload = json.loads(json_lines[-1]) if json_lines else {}
        return code, payload

    def _assert_export_file(self, out_path: Path, fmt: str) -> None:
        self.assertTrue(out_path.is_file(), f"{fmt} output missing")
        data = out_path.read_bytes()
        self.assertGreater(len(data), 0, f"{fmt} output is empty")
        magic = FORMAT_MAGIC[fmt]
        if magic is not None:
            self.assertTrue(data.startswith(magic), f"{fmt} wrong magic: {data[:16]!r}")

    def _write_box_generator(self) -> Path:
        generator = self.temp_root / "box.py"
        generator.write_text(BOX_GENERATOR)
        return generator

    def test_export_generated_step_py_all_formats(self) -> None:
        generator = self._write_box_generator()
        logical_step = self.temp_root / "box.step"
        for fmt in FORMATS:
            out = self.out_dir / f"box.{fmt}"
            code, payload = self._run([
                "--repo-root", str(Path.cwd()),
                "--step", str(logical_step),
                "--source-path", str(generator),
                "--format", fmt,
                "--out", str(out),
            ])
            self.assertEqual(code, 0, f"{fmt}: {payload}")
            self.assertTrue(payload.get("ok"), f"{fmt}: {payload}")
            self.assertEqual(payload.get("format"), fmt)
            self._assert_export_file(out, fmt)
        # The generated export writes only the requested files; no STEP is left beside the source.
        self.assertFalse((self.temp_root / "box.step").exists())

    def test_export_imported_step_all_formats(self) -> None:
        # Materialize a real STEP from the generator, then export from that on-disk file.
        generator = self._write_box_generator()
        imported_step = self.temp_root / "imported.step"
        code, payload = self._run([
            "--repo-root", str(Path.cwd()),
            "--step", str(self.temp_root / "box.step"),
            "--source-path", str(generator),
            "--format", "step",
            "--out", str(imported_step),
        ])
        self.assertEqual(code, 0, payload)
        self.assertTrue(imported_step.is_file())

        for fmt in FORMATS:
            out = self.out_dir / f"imported.{fmt}"
            code, payload = self._run([
                "--repo-root", str(Path.cwd()),
                "--step", str(imported_step),
                "--format", fmt,
                "--out", str(out),
            ])
            self.assertEqual(code, 0, f"{fmt}: {payload}")
            self.assertTrue(payload.get("ok"), f"{fmt}: {payload}")
            self._assert_export_file(out, fmt)

    def test_missing_imported_step_reports_error(self) -> None:
        code, payload = self._run([
            "--repo-root", str(Path.cwd()),
            "--step", str(self.temp_root / "does_not_exist.step"),
            "--format", "stl",
            "--out", str(self.out_dir / "missing.stl"),
        ])
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertIn("error", payload)

    def test_export_cad_target_rejects_step_format(self) -> None:
        # The Viewer's Save-dialog path (main(), tested above) still exports STEP; the CAD
        # CAD workflow does not — the model script itself owns .step files.
        generator = self._write_box_generator()
        with self.assertRaises(ValueError) as cm:
            step_export_target.export_cad_target(generator, [("step", None)])
        self.assertIn("Unsupported export format: step", str(cm.exception))

    def test_export_cad_target_writes_mesh_formats(self) -> None:
        generator = self._write_box_generator()
        payload = step_export_target.export_cad_target(
            generator,
            [(fmt, None) for fmt in step_export_target.MESH_EXPORT_FORMATS],
        )
        self.assertTrue(payload["ok"])
        for entry in payload["files"]:
            self._assert_export_file(Path(entry["path"]), entry["format"])
        # Mesh exports never leave a .step behind.
        self.assertFalse((self.temp_root / "box.step").exists())

    def test_mesh_exports_are_byte_deterministic(self) -> None:
        # design/unified-tessellation.md Phase 4: one deterministic code path,
        # so exporting the same model twice yields identical bytes per format.
        generator = self._write_box_generator()
        digests: dict[str, bytes] = {}
        for round_index in range(2):
            payload = step_export_target.export_cad_target(
                generator,
                [
                    (fmt, f"round{round_index}.{fmt}")
                    for fmt in step_export_target.MESH_EXPORT_FORMATS
                ],
            )
            self.assertTrue(payload["ok"])
            for entry in payload["files"]:
                data = Path(entry["path"]).read_bytes()
                if round_index == 0:
                    digests[entry["format"]] = data
                else:
                    self.assertEqual(
                        digests[entry["format"]],
                        data,
                        f"{entry['format']} export must be byte-identical across runs",
                    )

    def test_invalid_format_rejected(self) -> None:
        generator = self._write_box_generator()
        with self.assertRaises(SystemExit):
            self._run([
                "--repo-root", str(Path.cwd()),
                "--step", str(self.temp_root / "box.step"),
                "--source-path", str(generator),
                "--format", "iges",
                "--out", str(self.out_dir / "box.iges"),
            ])


if __name__ == "__main__":
    unittest.main()
