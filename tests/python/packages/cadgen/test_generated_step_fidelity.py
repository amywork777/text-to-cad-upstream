"""The assembled .step is the document: it must carry the model's colors, and
its embedded identity must protect it from being re-imported as a foreign file.

Regression suite for the planetary-pilot loss (2026-08-30): packages are
gitignored, so on a fresh checkout a generated model arrives as a bare .step.
Two defects compounded there:

* ``assemble_step_from_package`` read colors only from the COMPONENT entry,
  while generators author per-OCCURRENCE colors — every such model's .step was
  written colorless, so any import of it was colorless too;
* nothing consulted the file's embedded ``cadgen:`` identity metadata, so the
  bare file classified as importable and the import overwrote the package with
  ``sourceKind: "step"`` — dropping colors, the pose block, and provenance.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen import step_artifact_cli  # noqa: E402
from cadgen._internal.step_assemble import assemble_step_from_package  # noqa: E402
from cadgen.catalog import render_package_dir  # noqa: E402
from tests.python.support.cad_test_roots import IsolatedCadRoots  # noqa: E402

# Two occurrences of DISTINCT parts with per-occurrence colors and a pose
# block — the planetary pilot's shape of metadata, minimized.
COLORED_ASSEMBLY_GENERATOR = """from build123d import Box, Color, Compound, Location

from cadgen import pose, step


@step(kind="assembly", pose=pose(
    params={"drive": {"type": "number", "min": 0, "max": 360, "default": 0}},
))
def model():
    left = Box(10.0, 10.0, 10.0)
    left.label = "left"
    left.color = Color(1.0, 0.0, 0.0, 1.0)
    right = Box(6.0, 6.0, 6.0).moved(Location((20.0, 0.0, 0.0)))
    right.label = "right"
    right.color = Color(0.0, 0.0, 1.0, 1.0)
    return Compound(children=[left, right])
"""


class GeneratedStepFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._isolated_roots = IsolatedCadRoots(self, prefix="cadfid-")
        self._tempdir = self._isolated_roots.temporary_cad_directory(prefix="tmp-cadfid-")
        self.temp_root = Path(self._tempdir.name)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self._tempdir.cleanup()

    def _build_generated_package(self) -> tuple[Path, Path]:
        generator = self.temp_root / "colored.py"
        generator.write_text(COLORED_ASSEMBLY_GENERATOR)
        logical_step = self.temp_root / "colored.step"
        payload = step_artifact_cli.build_step_artifact(
            repo_root=Path.cwd(),
            step=logical_step,
            source_path=generator,
        )
        self.assertTrue(payload.get("ok"), payload)
        return generator, logical_step

    def _descriptor(self, step_path: Path) -> dict:
        return json.loads(
            (render_package_dir(step_path) / "assembly.json").read_text()
        )

    def test_generated_descriptor_records_occurrence_colors_and_pose(self) -> None:
        _, logical_step = self._build_generated_package()
        descriptor = self._descriptor(logical_step)
        occurrences = descriptor.get("occurrences") or []
        self.assertEqual(len(occurrences), 2)
        colored = [o for o in occurrences if isinstance(o.get("color"), list)]
        self.assertEqual(len(colored), 2, occurrences)
        block = descriptor.get("pose")
        self.assertIsInstance(block, dict)
        self.assertIn("drive", block["params"])
        self.assertNotIn("paramsPath", descriptor)
        self.assertEqual(descriptor.get("sourceKind"), "python")

    def test_assembled_step_carries_occurrence_colors(self) -> None:
        _, logical_step = self._build_generated_package()
        out = self.temp_root / "out" / "colored.step"
        out.parent.mkdir(parents=True, exist_ok=True)
        assemble_step_from_package(render_package_dir(logical_step), out)
        text = out.read_text(errors="ignore")
        self.assertIn(
            "COLOUR",
            text,
            "assembled STEP must carry the occurrence colors the descriptor records",
        )

    def test_import_refuses_generated_step_without_force(self) -> None:
        _, logical_step = self._build_generated_package()
        exported_dir = self.temp_root / "elsewhere"
        exported_dir.mkdir()
        exported = exported_dir / "colored.step"
        assemble_step_from_package(render_package_dir(logical_step), exported)

        with self.assertRaises(RuntimeError) as caught:
            step_artifact_cli.build_step_artifact(
                repo_root=Path.cwd(),
                step=exported,
            )
        message = str(caught.exception)
        self.assertIn("cadgen-GENERATED", message)
        self.assertIn("colored.py", message)
        self.assertIn("--force", message)

    def test_forced_import_of_generated_step_preserves_colors(self) -> None:
        # --force stays the deliberate override (e.g. recovering an artifact
        # whose source drifted) — and thanks to the colored assembly, even that
        # lossy path keeps the geometry colors.
        _, logical_step = self._build_generated_package()
        exported_dir = self.temp_root / "forced"
        exported_dir.mkdir()
        exported = exported_dir / "colored.step"
        assemble_step_from_package(render_package_dir(logical_step), exported)

        payload = step_artifact_cli.build_step_artifact(
            repo_root=Path.cwd(),
            step=exported,
            force=True,
        )
        self.assertTrue(payload.get("ok"), payload)
        descriptor = self._descriptor(exported)
        self.assertEqual(descriptor.get("sourceKind"), "step")
        occurrences = descriptor.get("occurrences") or []
        colored = [o for o in occurrences if isinstance(o.get("color"), list)]
        self.assertEqual(
            len(colored),
            len(occurrences),
            f"forced re-import must keep the STEP's colors: {occurrences}",
        )


if __name__ == "__main__":
    unittest.main()
