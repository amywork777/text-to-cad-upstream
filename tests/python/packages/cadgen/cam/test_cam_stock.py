"""The heightfield stock simulator against analytic volumes, rapids into stock, and the check registry."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import numpy as np

from cadgen._internal.cam.ir import ToolpathBuilder
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.stock import build_stock, create_stock_sim
from cadgen._internal.cam.wcs import build_wcs

JOB = {
    "machine": {"kind": "mill"}, "material": "aluminum-6061", "stock": {"kind": "box", "margin_mm": [0, 0, 0]},
    "tools": [{"id": "T1", "type": "flat", "diameter_mm": 6}, {"id": "T2", "type": "ball", "diameter_mm": 6}],
    "setups": [{"id": "top", "operations": [{"op": "face", "tool": "T1"}]},
               {"id": "under", "orientation": "-Z", "operations": [{"op": "face", "tool": "T1"}]}],
}


def fake_part(low, high):
    corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
    return SimpleNamespace(bbox=(np.asarray(low, float), np.asarray(high, float)), vertices=corners,
                           document=None)


class Heightfield(unittest.TestCase):
    def setUp(self):
        self.job = parse_job(JOB)
        self.part = fake_part((-20, -20, 0), (20, 20, 10))
        self.stock = build_stock(self.job.stock, self.part)
        self.tools = {t.id: t for t in self.job.tools}

    def sim(self, cell=0.1):
        sim, adapted = create_stock_sim("mill", self.stock, self.part, cell_mm=cell, tolerance_mm=0.01)
        self.assertEqual([], adapted)
        return sim

    def slot(self, setup_index=0, tool="T1", depth=5.0, rapid_down_to=1.0):
        setup = self.job.setups[setup_index]
        wcs = build_wcs(setup, stock_points=self.stock.vertices, part_points=self.part.vertices)
        b = ToolpathBuilder((-15, 0, 5))
        b.begin_op(index=0, setup=setup.id, op="slot", plain="Slot", tool=tool)
        b.rapid(z=rapid_down_to)
        b.feed(z=-depth, f=300)
        b.feed(x=15, f=600)
        b.rapid(z=5)
        b.end_op()
        return b.build(), wcs

    def test_a_flat_slot_removes_its_analytic_volume(self):
        sim = self.sim()
        start = sim.volume()
        self.assertAlmostEqual(40 * 40 * 10, start, delta=1.0)
        path, wcs = self.slot()
        report = sim.cut(path, self.tools, wcs)
        expected = (30 * 6 + math.pi * 9) * 5
        self.assertAlmostEqual(expected, start - sim.volume(), delta=0.015 * expected)
        self.assertAlmostEqual(expected, report.removed_mm3_by_op[0], delta=0.015 * expected)
        self.assertAlmostEqual(5.0, report.depth_by_op[0]["depth_mm"], places=6)
        self.assertEqual([], report.rapid_hits)

    def test_a_ball_slot_and_a_cut_from_below(self):
        sim = self.sim()
        path, wcs = self.slot(tool="T2", depth=3.0)
        start = sim.volume()
        sim.cut(path, self.tools, wcs)
        # A 3 mm ball 3 mm deep: a half-cylinder groove with quarter-sphere ends... a half cylinder plus a sphere half.
        expected = 30 * math.pi * 9 / 2 + (4 / 3) * math.pi * 27 / 2
        self.assertAlmostEqual(expected, start - sim.volume(), delta=0.02 * expected)
        under, wcs = self.slot(setup_index=1, depth=2.0)
        before = sim.volume()
        sim.cut(under, self.tools, wcs)
        self.assertAlmostEqual((30 * 6 + math.pi * 9) * 2, before - sim.volume(), delta=0.02 * (30 * 6 + math.pi * 9) * 2)
        self.assertTrue(sim.cut_from_below)

    def test_a_rapid_down_into_the_stock_is_a_hit(self):
        sim = self.sim(cell=0.25)
        path, wcs = self.slot(rapid_down_to=-2.0)
        report = sim.cut(path, self.tools, wcs)
        self.assertEqual(1, len(report.rapid_hits))
        self.assertAlmostEqual(2.0, report.rapid_hits[0]["depth_mm"], places=6)

    def test_the_mesh_is_the_stock(self):
        sim = self.sim(cell=0.5)
        vertices, triangles = sim.mesh()
        self.assertGreater(len(triangles), 100)
        self.assertAlmostEqual(10.0, float(vertices[:, 2].max()))


class Registries(unittest.TestCase):
    def test_every_check_in_the_spec_is_registered_and_unbuilt_ones_are_skipped(self):
        from cadgen._internal.cam.checks import CHECK_NAMES, REGISTRY, available, run_checks

        self.assertEqual(("gouge", "holder_collision", "reach", "rapid_into_stock", "travel", "corner_radius",
                          "material_left", "fixture", "limits", "machine", "empty_operation", "through_stock_bottom",
                          "long_stickout", "full_slot", "prepared_hole", "unused_tool"), CHECK_NAMES)
        ctx = SimpleNamespace(job=parse_job(JOB), part=None, stock=None, sim=None, sim_reports={}, setups=[], ops=[],
                              tolerance_mm=0.01)
        findings, ran, skipped = run_checks(ctx)
        self.assertEqual(["unused_tool"], [f["type"] for f in findings])     # no operation runs the job's tools
        self.assertEqual([entry.name for entry in REGISTRY if not available(entry)], skipped)
        self.assertIn("holder_collision", ran)
        self.assertIn("reach", ran)

    def test_the_operation_registry_teaches_what_is_planned(self):
        from cadgen._internal.cam.job_errors import CamJobError
        from cadgen._internal.cam.operations import OPERATION_NAMES, REGISTRY, available, get_operation

        self.assertEqual(28, len(OPERATION_NAMES))
        missing = [name for name in OPERATION_NAMES if not available(name)]
        if missing:
            with self.assertRaises(CamJobError) as caught:
                get_operation(missing[0])
            self.assertIn(f"'{missing[0]}' is planned but not in this cadgen yet", str(caught.exception))
        for name in OPERATION_NAMES:
            if available(name):
                with self.subTest(op=name):
                    op = get_operation(name)
                    entry = REGISTRY[name]
                    self.assertEqual((entry.name, entry.plain, entry.family, entry.machines, entry.status),
                                     (op.name, op.plain, op.family, op.machines, op.status))
                    self.assertEqual(op.status == "lite", bool(op.limits))

    def test_every_sim_and_post_is_registered(self):
        from cadgen._internal.cam import posts
        from cadgen._internal.cam.stock import SIM_REGISTRY

        self.assertEqual({"mill", "mill4", "mill5", "lathe", "laser", "plasma", "waterjet", "router", "wire_edm"},
                         set(SIM_REGISTRY))
        self.assertEqual(("grbl", "linuxcnc", "fanuc", "haas", "mach3", "marlin", "plasma", "waterjet", "wire_edm"),
                         posts.POST_NAMES)
        for kind in SIM_REGISTRY:
            self.assertIn(posts.DEFAULT_POST[kind], posts.POST_NAMES)
            self.assertIn(kind, posts.REGISTRY[posts.DEFAULT_POST[kind]].kinds)


class FitLadder(unittest.TestCase):
    def test_a_big_stock_coarsens_its_grid_and_says_so(self):
        from cadgen._internal.cam import fit

        job = parse_job(JOB)
        small = build_stock(job.stock, fake_part((0, 0, 0), (40, 40, 10)))
        self.assertEqual((0.75, []), fit.stock_cell(small, job.tools, fit.Budget()))
        big = build_stock(job.stock, fake_part((0, 0, 0), (3000, 2000, 10)))
        cell, steps = fit.stock_cell(big, job.tools, fit.Budget())
        self.assertLessEqual(3000 * 2000 / cell ** 2, fit.Budget().max_cells)
        self.assertEqual("stock_grid", steps[0]["step"])
        self.assertIn("->", steps[0]["words"])

    def test_the_display_chord_grows_then_thins(self):
        from cadgen._internal.cam import fit

        chord, stride, steps = fit.display_chord(lambda c: 10, 0.01, fit.Budget())
        self.assertEqual((0.02, 1, []), (chord, stride, steps))
        chord, stride, steps = fit.display_chord(lambda c: 5_000_000, 0.01, fit.Budget(max_glb_segments=1_000_000))
        self.assertEqual(1.0, chord)
        self.assertEqual(5, stride)
        self.assertEqual(["display", "display"], [s["step"] for s in steps])


if __name__ == "__main__":
    unittest.main()
