"""Posts: the GRBL golden on one small IR, its G-code read back to the IR's own path, arc fitting, the registry."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np

from cadgen._internal.cam.ir import ToolpathBuilder
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.posts import get_post
from cadgen._internal.cam.posts.base import Program, fit_arcs
from cadgen._internal.cam.wcs import build_wcs
from tests.python.support import gcode_reader

GOLDEN = Path(__file__).with_name("golden") / "grbl.nc"

JOB = {
    "machine": {"kind": "mill", "post": "grbl"}, "material": "aluminum-6061",
    "stock": {"kind": "box", "margin_mm": 1},
    "tools": [{"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3}, {"id": "T2", "type": "drill", "diameter_mm": 5}],
    "setups": [{"id": "top", "operations": [{"op": "face", "tool": "T1"}]}],
}


def small_program() -> Program:
    """Every kind of move and event on a 40 x 30 plate: a rounded square, a helix, a dwell, a tool change and a
    drill cycle (expanded, since GRBL has none)."""
    job = parse_job(JOB)
    setup = job.setups[0]
    corners = np.array([[-20, -15, -1], [20, 15, 0]], dtype=float)
    wcs = build_wcs(setup, stock_points=corners, part_points=corners)
    b = ToolpathBuilder((0, 0, 5))
    b.event("setup", id="top", wcs="G54", plain="Top")
    b.begin_op(index=0, setup="top", op="pocket", plain="Pocket", tool="T1")
    b.event("tool", tool="T1", number=1)
    b.event("spindle", rpm=13260, dir="cw")
    b.event("coolant", mode="flood")
    b.rapid(x=10, y=0)
    b.rapid(z=1)
    b.feed(z=0, f=600)
    b.arc(10, 0, -1, centre=(5, 0, 0), clockwise=False, f=1200)        # a helical full turn
    # A rounded square as short lines: the post fits arcs to its corners.
    for k in range(0, 91, 5):
        a = math.radians(k)
        b.feed(x=5 + 5 * math.cos(a), y=5 * math.sin(a), z=-1, f=1990)
    b.feed(x=-5, y=5, f=1990)
    b.dwell(0.5)
    b.rapid(z=5)
    b.end_op()
    b.begin_op(index=1, setup="top", op="drill", plain="Drill", tool="T2")
    b.event("tool", tool="T2", number=2)
    b.event("spindle", rpm=7640, dir="cw")
    handle = b.begin_cycle(cycle="peck", holes=[[-10, 5, 0], [10, 5, 0]], z_bottom=-6.0, r_plane=1.0,
                           retract="initial", initial_z=5.0, peck_mm=3.0, feed=300.0)
    for x in (-10, 10):
        b.rapid(x=x, y=5)
        b.rapid(z=1)
        b.feed(z=-3, f=300)
        b.rapid(z=1)
        b.rapid(z=-2.5)
        b.feed(z=-6, f=300)
        b.rapid(z=5)
    b.end_cycle(handle)
    b.end_op()
    b.event("coolant", mode="off")
    path = b.build()
    return Program(setup=setup, wcs=wcs, toolpath=path, tools={t.id: t for t in job.tools}, machine=job.machine,
                   version="TEST", part="plate.step", material="aluminium 6061", tolerance_mm=0.01)


class Grbl(unittest.TestCase):
    def setUp(self):
        self.program = small_program()
        self.text = get_post("grbl", "mill").render(self.program)

    def test_the_golden(self):
        if not GOLDEN.exists():  # pragma: no cover - writes the golden the first time only
            GOLDEN.write_text(self.text, encoding="utf-8")
        self.assertEqual(GOLDEN.read_text(encoding="utf-8"), self.text)

    def test_it_opens_with_the_safety_block_and_is_deterministic(self):
        head = self.text.splitlines()[:5]
        self.assertIn("NOT proven on a machine", head[1])
        self.assertIn("Air-cut", head[2])
        self.assertIn("work offset G54", head[3])
        self.assertEqual(self.text, get_post("grbl", "mill").render(small_program()))
        self.assertNotIn("M6", self.text)
        self.assertIn("M0", self.text)                 # the manual tool change
        self.assertNotIn("G83", self.text)             # GRBL posts the cycle expanded

    def test_the_gcode_reads_back_to_the_ir_path(self):
        read = gcode_reader.read(self.text, start=self.program.toolpath.start)
        points, _ = gcode_reader.sample(read, 0.002, max_step=0.05)
        ir = self.program.toolpath.sample(0.002, max_step_mm=0.05).points[1:]
        # Every posted point lies on the IR's path, and every IR point on the posted path, within the tolerance.
        for a, b in ((points, ir), (ir, points)):
            gaps = np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2), axis=1)
            self.assertLess(float(gaps.max()), 0.035)
        self.assertTrue(any(m.kind in ("arc_cw", "arc_ccw") for m in read.moves))
        self.assertIn("M8", read.coolant)
        self.assertTrue(np.allclose(points[-1], self.program.toolpath.ends()[-1]))


class ArcFitting(unittest.TestCase):
    def test_a_sampled_circle_fits_to_an_arc_and_a_zigzag_stays_lines(self):
        angles = np.linspace(0, math.pi, 40)
        arc = np.column_stack([10 * np.cos(angles), 10 * np.sin(angles), np.zeros(40)])
        pieces = fit_arcs(arc, 0.01)
        self.assertEqual(["arc"], [p[0] for p in pieces])
        self.assertAlmostEqual(0.0, pieces[0][2][0], places=6)
        self.assertFalse(pieces[0][3])                  # counter-clockwise
        zigzag = np.array([[0, 0, 0], [1, 1, 0], [2, 0, 0], [3, 1, 0], [4, 0, 0]], dtype=float)
        self.assertEqual(["line"] * 4, [p[0] for p in fit_arcs(zigzag, 0.01)])


class Registry(unittest.TestCase):
    def test_a_planned_post_teaches(self):
        from cadgen._internal.cam.job_errors import CamJobError
        from cadgen._internal.cam.posts import POST_NAMES, available

        missing = [name for name in POST_NAMES if not available(name)]
        if missing:
            from cadgen._internal.cam.posts import REGISTRY

            name = missing[0]
            with self.assertRaises(CamJobError) as caught:
                get_post(name, REGISTRY[name].kinds[0])
            self.assertIn("is planned but not in this cadgen yet", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
