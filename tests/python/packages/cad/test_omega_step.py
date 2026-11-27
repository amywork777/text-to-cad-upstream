"""``cad gsl step``: a GSL model written as a faceted STEP solid, held to its field both ways and read back.

The writer and the fin repair are numpy and the kernel, tested wherever the kernel is. What meshes a model needs a
``gsl`` whose ``eval`` meshes; those tests skip by name where there is none.
"""

from __future__ import annotations

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.python.packages.cad.test_omega_mesh import MESHES, NEEDS_MESH, TETRA_FACES, TETRA_POINTS

HAS_KERNEL = importlib.util.find_spec("OCP") is not None
HAS_SIMPLIFY = importlib.util.find_spec("fast_simplification") is not None

BALL = "@scene(40)\nreturn length(p) - 8.0;\n"


@unittest.skipUnless(HAS_KERNEL, "needs the kernel (cad[build123d])")
class FacetedStepTest(unittest.TestCase):
    def test_a_closed_mesh_reads_back_as_one_valid_solid_of_its_volume(self) -> None:
        from cad._internal.step_readback import read_back
        from cad.omega._step import _write_faceted

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tetra.step"
            _write_faceted(TETRA_POINTS * 10.0, TETRA_FACES, "it's a tetra", path)
            self.assertIn("FACETED_BREP('its a tetra'", path.read_text())
            read = read_back(path)
        self.assertIsNotNone(read)
        valid, volume = read
        self.assertTrue(valid)
        self.assertAlmostEqual(1000.0 / 6.0, volume, places=3)


@unittest.skipUnless(HAS_KERNEL, "needs the kernel (cad[build123d])")
class AssembleTest(unittest.TestCase):
    def test_parts_are_copied_in_as_written_and_placed_where_asked(self) -> None:
        import build123d as bd

        from cad.gsl import assemble
        from cad.omega._step import _write_faceted

        with tempfile.TemporaryDirectory() as folder:
            here = Path(folder)
            bd.export_step(bd.Box(10, 10, 10), str(here / "block.step"))
            _write_faceted(TETRA_POINTS * 6.0, TETRA_FACES, "tetra", here / "tetra.step")
            parts = [(here / "block.step", "Block", (0, 0, 0)), (here / "tetra.step", "Lattice's tetra", (20, 0, 5)),
                     (here / "tetra.step", "Turned tetra", bd.Location((0, 30, 0), (0, 0, 90)))]
            out = assemble(here / "assembly.step", parts, name="Test assembly")
            text = out.read_text(encoding="latin-1")
            self.assertEqual(1, text.count("FACETED_BREP("))
            self.assertEqual(3, text.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE("))
            self.assertLess(out.stat().st_size, sum((here / name).stat().st_size for name in ("block.step", "tetra.step"))
                            + 5000)
            read = bd.import_step(str(out))
        # The file given twice is one part used twice, so both uses carry the part's first label.
        self.assertEqual(["Block", "Lattices_tetra", "Lattices_tetra"], sorted(child.label for child in read.children))
        block, *tetras = sorted(read.children, key=lambda child: -child.volume)
        self.assertAlmostEqual(1000.0, block.volume, places=3)
        self.assertEqual([36.0, 36.0], [round(tetra.volume, 3) for tetra in tetras])
        corners = sorted((round(box.min.X, 4), round(box.min.Y, 4), round(box.min.Z, 4))
                         for box in (tetra.bounding_box() for tetra in tetras))
        self.assertEqual([(-6.0, 30.0, 0.0), (20.0, 0.0, 5.0)], corners)

    def test_a_file_holding_an_assembly_is_refused(self) -> None:
        import build123d as bd

        from cad.gsl import assemble

        with tempfile.TemporaryDirectory() as folder:
            here = Path(folder)
            bd.export_step(bd.Compound(children=[bd.Box(1, 1, 1), bd.Sphere(1)]), str(here / "two.step"))
            with self.assertRaises(ValueError):
                assemble(here / "out.step", [(here / "two.step", "Two", (0, 0, 0))])


@unittest.skipUnless(HAS_SIMPLIFY, "needs fast_simplification (cad[omega])")
class ReducedTest(unittest.TestCase):
    def test_a_fin_a_reduction_leaves_goes_and_the_shell_is_manifold_again(self) -> None:
        from unittest import mock

        from cad.omega._check import measure
        from cad.omega._step import _reduced

        points = np.concatenate([TETRA_POINTS, [[1.0, 1.0, -1.0]]]).astype(np.float32)
        fin = np.concatenate([TETRA_FACES, [[1, 2, 4], [4, 2, 1]]])
        self.assertEqual(1, measure(points.astype(np.float64)[fin])["non_manifold_edges"])
        with mock.patch("fast_simplification.simplify", return_value=(points, fin)):
            vertices, faces = _reduced(TETRA_POINTS, TETRA_FACES, 0.5)
        shape = measure(vertices[faces])
        self.assertEqual((4, 4, 0, 0), (len(vertices), len(faces), shape["non_manifold_edges"], shape["open_edges"]))


@unittest.skipUnless(MESHES and HAS_KERNEL and HAS_SIMPLIFY, NEEDS_MESH)
class StepTest(unittest.TestCase):
    def test_a_ball_is_written_within_tolerance_and_as_few_faces_as_hold_it(self) -> None:
        from cad.gsl import step

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "ball.gsl"
            model.write_text(BALL)
            result = step(model, depth=6, tolerance=0.2)
            self.assertTrue(result.ok, result.findings)
            measured = result.measurements
            self.assertEqual(model.with_suffix(".step").resolve(), Path(measured["step"]).resolve())
            self.assertTrue(Path(measured["step"]).is_file())
        self.assertLessEqual(max(measured["field_at_step_mm"], measured["surface_to_step_mm"]), 0.2)
        self.assertLess(measured["faces"], measured["meshed_triangles"])
        self.assertAlmostEqual(4 / 3 * math.pi * 8.0 ** 3, measured["volume_mm3"], delta=0.03 * 2145.0)

    def test_with_no_depth_named_it_meshes_one_deeper_where_the_default_is_too_coarse(self) -> None:
        from unittest import mock

        from cad.gsl import step

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "ball.gsl"
            model.write_text(BALL)
            # The default is 9; at 5 a 16 mm ball is 0.07 mm off and at 6 0.02 mm, a test's worth of the same step.
            with mock.patch("cad.omega._mesh.DEFAULT_DEPTH", 5):
                result = step(model, tolerance=0.05)
        self.assertTrue(result.ok, result.findings)
        self.assertEqual(6, result.measurements["depth"])
        self.assertEqual(5, result.measurements["tried"][0]["depth"])
        self.assertGreater(result.measurements["tried"][0]["departure_mm"], 0.05)

    def test_a_tolerance_finer_than_the_mesh_writes_nothing_and_says_the_depth_to_raise(self) -> None:
        from cad.gsl import step

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "ball.gsl"
            model.write_text(BALL)
            result = step(model, depth=5, tolerance=1e-4)
            self.assertFalse(model.with_suffix(".step").exists())
        self.assertFalse(result.ok)
        self.assertEqual(["step_outside_tolerance"], [finding.code for finding in result.findings])
        self.assertIn("--depth 6", result.findings[0].hint)


if __name__ == "__main__":
    unittest.main()
