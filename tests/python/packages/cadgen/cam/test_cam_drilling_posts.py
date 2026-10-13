"""Drill cycles posted: GRBL (no canned cycles) posts the expansion, a post with canned cycles posts G8x blocks, and
both read back (tests/python/support/gcode_reader.py) to the IR's own path. End to end: a pocket then the drilling
plans ready, the posted file and the GLB carry it."""

from __future__ import annotations

import json
import unittest

import numpy as np

from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.part import read_part
from cadgen._internal.cam.posts import get_post
from cadgen._internal.cam.posts.base import Post, Program
from cadgen._internal.cam.run import parse_operations, plan_setups
from cadgen._internal.cam.stock import build_stock
from tests.python.support import gcode_reader
from tests.python.support.cam_fixtures import class_directory, quiet, read_glb
from tests.python.support.cam_fixtures_drilling import PLATE, drill_job, drill_plate_step, hole_faces


class CannedPost(Post):
    """A Fanuc-style test post that emits every cycle the base's cycle_lines knows."""

    name = "canned-test"
    kinds = ("mill",)
    canned_cycles = frozenset({"drill", "spot", "peck", "chipbreak", "tap", "bore", "ream"})


def _same_path(test, text: str, program: Program, *, tolerance: float = 0.01) -> None:
    read = gcode_reader.read(text, start=program.toolpath.start)
    points, _ = gcode_reader.sample(read, 0.002, max_step=0.25)
    ir = program.toolpath.sample(0.002, max_step_mm=0.25).points[1:]
    for a, b in ((points, ir), (ir, points)):
        gaps = np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2), axis=1)
        test.assertLess(float(gaps.max()), tolerance)
    test.assertTrue(np.allclose(points[-1], program.toolpath.ends()[-1], atol=1e-3))


class Posted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        with quiet():
            cls.directory = class_directory(cls)
            cls.step = drill_plate_step(cls.directory)
            cls.features = cam.features(cls.step)
            cls.part = read_part(cls.step)
        f5, f6, f4 = (hole_faces(cls.features, d) for d in (5.0, 6.0, 4.0))
        cls.ops = [
            {"op": "drill", "tool": "T4", "faces": f5 + f4},                                   # spot (G81 here)
            {"op": "drill", "tool": "T1", "faces": f5, "cycle": "peck", "peck_mm": 3},        # G83
            {"op": "drill", "tool": "T7", "faces": f4, "cycle": "chipbreak", "peck_mm": 2},   # G73, G99 in the pocket
            {"op": "drill", "tool": "T2", "faces": f6, "cycle": "dwell", "dwell_s": 0.4},     # G82 P
            {"op": "drill", "tool": "T5", "faces": f6[:1], "depth_to": "tip"},               # G85
            {"op": "drill", "tool": "T3", "faces": f5[:2]},                                   # G84
        ]

    def program(self, post_name="grbl"):
        parsed = parse_job(drill_job(self.ops))
        stock = build_stock(parsed.stock, self.part)
        setups, _, _ = plan_setups(parsed, parse_operations(parsed), self.part, stock)
        plan = setups[0]
        return Program(setup=plan.setup, wcs=plan.wcs, toolpath=plan.toolpath, tools={t.id: t for t in parsed.tools},
                       machine=parsed.machine, version="TEST", part="drill_plate.step", tolerance_mm=0.01)

    def test_grbl_posts_every_cycle_expanded_and_it_reads_back_to_the_ir(self):
        program = self.program()
        text = get_post("grbl", "mill").render(program)
        for code in ("G81", "G82", "G83", "G73", "G84", "G85", "G98", "G99", "G80"):
            self.assertNotRegex(text, rf"\b{code}\b")
        self.assertIn("G4 P0.4", text)                                   # the dwell at the bottom
        lines = text.splitlines()
        reversal = [k for k, line in enumerate(lines) if line.endswith("M4")]
        self.assertEqual(2, len(reversal))                              # one per tapped hole
        for k in reversal:
            self.assertRegex(lines[k + 1], r"^G1 Z|^Z")                   # feeds out
            self.assertTrue(lines[k + 2].endswith("M3"))
        _same_path(self, text, program)

    def test_a_canned_post_posts_g8x_and_it_reads_back_to_the_same_path(self):
        program = self.program()
        text = CannedPost().render(program)
        read = gcode_reader.read(text, start=program.toolpath.start)
        # Spot (two cycles: the top holes and the pocket's), peck, chip-break, dwell, ream, tap.
        self.assertEqual(["G82", "G82", "G83", "G73", "G82", "G85", "G84"], read.cycles)
        self.assertIn("G98 G83", text)
        self.assertIn("G99 G73", text)                                  # the pocket holes return to R
        self.assertRegex(text, r"G99 G73 X\S+ Y\S+ Z-15\.202 R-3 Q2 F")
        self.assertEqual(text.count("G80"), sum(1 for e in program.toolpath.events if e.kind == "cycle"))
        self.assertNotIn("M4", text)                                     # G84 reverses the spindle itself
        _same_path(self, text, program)

    def test_plan_end_to_end_after_the_pocket_is_ready_and_writes_the_drilling(self):
        from cadgen._internal.cam.run import plan_job

        f4 = hole_faces(self.features, 4.0)
        floor = next(f["ref"] for f in self.features.floors if abs(f["z_mm"] - PLATE["pocket"]["floor_z"]) < 1e-6
                     and f["normal"] == "+Z")
        tools = drill_job([])["tools"] + [{"id": "T8", "type": "flat", "diameter_mm": 6, "flutes": 3,
                                           "flute_length_mm": 20, "stickout_mm": 30}]
        ops = [{"op": "face", "tool": "T8"}, {"op": "pocket", "tool": "T8", "faces": [floor]},
               {"op": "drill", "tool": "T4", "holes": "all"},
               {"op": "drill", "tool": "T7", "faces": f4, "cycle": "peck"},
               {"op": "drill", "tool": "T1", "holes": {"diameter_mm": 5}}]
        with quiet():
            result = plan_job(self.step, job=drill_job(ops, tools=tools), out_dir=self.directory)
        self.assertTrue(result.ok, result.findings)
        errors = [f for f in result.findings if f["severity"] == "error"]
        self.assertEqual([], errors)
        self.assertEqual("ready", result.verdict["status"])
        rows = [op for op in result.operations if op["op"] == "drill"]
        self.assertEqual(["Spot 10 holes with T4 6 mm spot drill", "Peck drill 2 holes with T7 4 mm drill",
                          "Drill 4 holes with T1 5 mm drill"], [row["summary"].rsplit(",", 1)[0] for row in rows])
        text = result.posts[0]["file"]
        posted = gcode_reader.read(open(text, encoding="utf-8").read(), start=(0, 0, 6.0))
        lowest = min(move.end[2] for move in posted.moves)
        self.assertAlmostEqual(-13.0 - 1.0 - 2.5 / np.tan(np.radians(59)), lowest, places=3)
        document, _ = read_glb(result.glb)
        cam = document["scenes"][document.get("scene", 0)]["extras"]["cam"]
        drills = [op for setup in cam["setups"] for op in setup["operations"] if op["op"] == "drill"]
        self.assertEqual(3, len(drills))
        self.assertTrue(all(op["time_s"] > 0 for op in drills))
        json.dumps(cam)


if __name__ == "__main__":
    unittest.main()
