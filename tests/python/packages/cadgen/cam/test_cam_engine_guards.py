"""Engine guards from review: plausible-wrong plans the engine must refuse, flag or get right (law 10), and keys it
must not accept and ignore (law 9). Each test is one fixed bug, on a small part built in a temporary directory."""

from __future__ import annotations

import unittest

from tests.python.support.cam_fixtures import class_directory


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


if __name__ == "__main__":
    unittest.main()
