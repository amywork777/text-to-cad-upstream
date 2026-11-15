"""SPIKE: a job that names ``"planner": "camlib"`` is planned, simulated and posted by camlib, and checked by cad's own
checks on the program camlib posted. Skipped where camlib is not installed (it has no release yet: build it from a
checkout of github.com/stevecad/camlib with a Rust toolchain)."""

from __future__ import annotations

import importlib.util
import unittest

from tests.python.support.cam_fixtures import (block_step, class_directory, features_of, floor_ref, mill_job,
                                               plate_step, quiet, result_json)

needs_camlib = unittest.skipUnless(importlib.util.find_spec("camlib"), "camlib is not installed")


def plan(step, job, out):
    import cad

    with quiet():
        return cad.step.plan(step, job={**job, "planner": "camlib"}, out=out)


@needs_camlib
class CamlibPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = class_directory(cls)
        cls.block = block_step(cls.dir)
        cls.plate = plate_step(cls.dir)

    def test_block_faced_pocketed_and_posted(self):
        features = features_of(self.block)
        job = mill_job([{"op": "face", "tool": "T1"},
                        {"op": "pocket", "tool": "T1", "faces": [floor_ref(features, 17.0)]},
                        {"op": "pocket", "tool": "T1", "faces": [floor_ref(features, 11.0)]}])
        result = plan(self.block, job, self.dir / "block")
        self.assertTrue(result.ok, [f.message for f in result.findings])
        self.assertEqual([], [f.message for f in result.findings])
        data = result_json(result)
        self.assertTrue(data["measurements"]["planner"].startswith("camlib "))
        self.assertIsNone(data["measurements"]["camlib"]["top"]["export_refused"])
        text = result.gcode[0].read_text(encoding="utf-8")
        self.assertIn("planned and posted by camlib", text)
        self.assertIn("G54", text)

    def test_drill_the_holes_size_is_released_as_a_warning(self):
        features = features_of(self.block)
        walls = [hole["faces"][0] for hole in features.holes]
        result = plan(self.block, mill_job([{"op": "drill", "tool": "T2", "faces": walls}]), self.dir / "drill")
        self.assertTrue(result.ok, [f.message for f in result.findings])
        self.assertEqual(["camlib_uncertain"], [f.code for f in result.findings])

    def test_plate_profiled_through_and_bored(self):
        features = features_of(self.plate)
        bore = [h["faces"][0] for h in features.holes if abs(h["diameter_mm"] - 22.2) < 1e-3]
        job = mill_job([{"op": "profile", "tool": "T1", "side": "inside", "through_mm": 0.5, "faces": bore},
                        {"op": "profile", "tool": "T1", "side": "outside", "through_mm": 0.5}],
                       stock={"margin_mm": [8, 8, 1]})
        result = plan(self.plate, job, self.dir / "plate")
        self.assertTrue(result.ok, [f.message for f in result.findings])
        self.assertEqual([], [f.message for f in result.findings])

    def test_a_post_camlib_does_not_ship_is_refused(self):
        features = features_of(self.block)
        job = mill_job([{"op": "pocket", "tool": "T1", "faces": [floor_ref(features, 17.0)]}],
                       machine={"post": "grbl", "max_rpm": 24000})
        result = plan(self.block, job, self.dir / "grbl")
        self.assertFalse(result.ok)
        self.assertIn("camlib posts linuxcnc here, not grbl", result.findings[0].message)


if __name__ == "__main__":
    unittest.main()
