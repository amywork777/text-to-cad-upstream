"""Engine guards from review: plausible-wrong plans the engine must refuse, flag or get right (law 10), and keys it
must not accept and ignore (law 9). Each test is one fixed bug, on a small part built in a temporary directory."""

from __future__ import annotations

import unittest

from tests.python.support.cam_fixtures import class_directory, mill_job, quiet


def _twin_holes_step(directory):
    """40 x 40 x 30 with a Ø5 x 10 blind hole from the top and one from the bottom on the same axis: a 10 mm web."""
    from build123d import Align, Box, Cylinder, Pos, export_step

    base = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Box(40, 40, 30, align=base)
    part -= Pos(0, 0, 20) * Cylinder(2.5, 10, align=base)
    part -= Pos(0, 0, 0) * Cylinder(2.5, 10, align=base)
    path = directory / "twin.step"
    export_step(part, str(path))
    return path


def _slotted_hole_step(directory):
    """40 x 40 x 30 with a Ø5 through hole crossed by a slot (z 10..20) open front to back: one hole across air."""
    from build123d import Align, Box, Cylinder, Pos, export_step

    base = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Box(40, 40, 30, align=base)
    part -= Pos(0, 0, 10) * Box(12, 40, 10, align=base)
    part -= Cylinder(2.5, 30, align=base)
    path = directory / "slotted.step"
    export_step(part, str(path))
    return path


def _plate_with_hole_step(directory):
    from build123d import Align, Box, Cylinder, export_step

    base = (Align.CENTER, Align.CENTER, Align.MIN)
    path = directory / "holed.step"
    export_step(Box(40, 40, 10, align=base) - Cylinder(2.5, 10, align=base), str(path))
    return path


def _errors(result, check: str) -> list[dict]:
    return [f for f in result.findings if f["severity"] == "error" and f["check"] == check]


class CoaxialHoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = class_directory(cls)
        cls.twin = _twin_holes_step(cls.directory)

    def test_blind_holes_either_side_of_a_web_are_two_blind_holes(self):
        from cadgen import cam

        holes = cam.features(self.twin).holes
        self.assertEqual(2, len(holes))
        self.assertEqual(["+Z", "-Z"], sorted(h["axis_word"] for h in holes))
        for hole in holes:
            self.assertFalse(hole["through"])
            self.assertAlmostEqual(10.0, hole["depth_mm"], places=3)

    def test_a_hole_crossing_a_slot_is_still_one_through_hole(self):
        from cadgen import cam

        holes = cam.features(_slotted_hole_step(self.directory)).holes
        self.assertEqual(1, len(holes))
        self.assertTrue(holes[0]["through"])
        self.assertAlmostEqual(30.0, holes[0]["depth_mm"], places=3)
        self.assertEqual(2, len(holes[0]["faces"]))

    def test_a_tap_stops_in_its_blind_hole_and_one_driven_through_the_web_is_a_gouge(self):
        from cadgen import cam

        tap = [{"id": "T1", "type": "tap", "diameter_mm": 6, "pitch_mm": 1, "flute_length_mm": 40, "stickout_mm": 50}]
        with quiet():
            blind = cam.plan(self.twin, job=mill_job([{"op": "drill", "tool": "T1", "holes": "all"}], tools=tap),
                             out_dir=self.directory / "blind")
        self.assertTrue(blind.ok)
        self.assertEqual(1, blind.operations[0]["facts"]["hole_count"])
        # Stock top is z 31 (1 mm on top): the hole's floor is z 20, WCS -11; the tap stops a pitch above it.
        self.assertAlmostEqual(-10.0, blind.operations[0]["facts"]["bottom_z"], places=3)
        self.assertEqual([], _errors(blind, "gouge"))
        with quiet():
            deep = cam.plan(self.twin, job=mill_job([{"op": "drill", "tool": "T1", "points": [[0, 0]],
                                                      "depth_mm": 16, "top_z": -1}], tools=tap),
                            out_dir=self.directory / "deep")
        self.assertTrue(deep.ok)
        self.assertEqual("fix", deep.verdict["status"])
        self.assertTrue(_errors(deep, "gouge"))


class DrillBodyGouge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = class_directory(cls)
        cls.step = _plate_with_hole_step(cls.directory)

    def _plan(self, tool: dict, name: str):
        from cadgen import cam

        with quiet():
            return cam.plan(self.step, job=mill_job([{"op": "drill", "tool": "T1", "holes": "all"}],
                                                    tools=[{"id": "T1", **tool}]), out_dir=self.directory / name)

    def test_a_drill_bigger_than_its_hole_is_a_gouge(self):
        result = self._plan({"type": "drill", "diameter_mm": 8}, "big")
        self.assertEqual("fix", result.verdict["status"])
        gouges = _errors(result, "gouge")
        self.assertEqual(1, len(gouges))
        self.assertAlmostEqual(1.5, gouges[0]["items"][0]["depth_mm"], delta=0.05)

    def test_the_right_drill_is_not(self):
        result = self._plan({"type": "drill", "diameter_mm": 5}, "right")
        self.assertEqual([], _errors(result, "gouge"))


if __name__ == "__main__":
    unittest.main()
