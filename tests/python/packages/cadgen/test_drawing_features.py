"""What a drawing reads off a part's faces: holes, turned axes, turned diameters.

Every part is built here with build123d, so each expected number is the one it
was built with: a counterbored hole made ⌀6.6 through under a ⌀11 × 6.5 bore
reads exactly that, and a boss or a slot end -- convex, or half a cylinder --
reads as no hole at all.
"""

from __future__ import annotations

import math
import unittest


def _block():
    from build123d import Align, Box, BuildPart, CounterBoreHole, CounterSinkHole, Hole, Locations, Pos

    with BuildPart() as part:
        Box(80, 50, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(Pos(-25, 10, 12), Pos(-25, -10, 12)):
            CounterBoreHole(radius=3.3, counter_bore_radius=5.5, counter_bore_depth=6.5)
        with Locations(Pos(0, 0, 12)):
            CounterSinkHole(radius=3, counter_sink_radius=6, counter_sink_angle=90)
        with Locations(Pos(25, 10, 12), Pos(25, -10, 12)):
            Hole(radius=2, depth=5)
    return part.part


class HoleTests(unittest.TestCase):
    def test_every_hole_reads_as_its_callout_would(self) -> None:
        from cadgen._internal.drawing_features import holes

        found = holes(_block())
        by_kind: dict[tuple, list] = {}
        for hole in found:
            by_kind.setdefault(hole.signature(), []).append(hole)
        self.assertEqual(len(found), 5)
        self.assertEqual(len(by_kind), 3, "two counterbored, one countersunk, two blind")

        cbore = next(h for h in found if h.cbore)
        self.assertAlmostEqual(cbore.diameter, 6.6, places=6)
        self.assertTrue(cbore.thru)
        self.assertEqual(tuple(round(v, 6) for v in cbore.cbore), (11.0, 6.5))
        self.assertEqual(cbore.axis, (0.0, 0.0, -1.0), "into the material from the counterbored face")
        self.assertAlmostEqual(cbore.mouth[2], 12.0, places=6)

        csk = next(h for h in found if h.csk)
        self.assertAlmostEqual(csk.diameter, 6.0, places=6)
        self.assertEqual((round(csk.csk[0], 6), csk.csk[1]), (12.0, 90.0))

        blind = [h for h in found if not h.thru]
        self.assertEqual(len(blind), 2)
        for hole in blind:
            self.assertAlmostEqual(hole.diameter, 4.0, places=6)
            self.assertAlmostEqual(hole.depth, 5.0, places=6)
            self.assertAlmostEqual(hole.mouth[2], 12.0, places=6, msg="a blind hole opens where it is open")

    def test_a_boss_and_a_slot_are_not_holes(self) -> None:
        """A boss is a convex cylinder; a slot's ends are half cylinders."""
        from build123d import Align, Box, Cylinder, Pos, SlotCenterToCenter, extrude
        from cadgen._internal.drawing_features import holes

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        boss = Box(60, 40, 5, align=align) + Pos(0, 0, 5) * Cylinder(6, 10, align=align)
        self.assertEqual(holes(boss), [])
        slot = Box(60, 40, 5, align=align) - extrude(SlotCenterToCenter(20, 8), 5)
        self.assertEqual(holes(slot), [])

    def test_a_hole_broken_by_air_is_still_one_hole(self) -> None:
        """A clevis pin hole crosses the gap between the arms; a blind bore can break
        through a cross hole. Judged piece by piece, each read as two holes."""
        from build123d import Align, Box, Cylinder, Pos, Rot
        from cadgen._internal.drawing_features import holes

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        clevis = (Box(30, 30, 6, align=align) + Pos(0, 0, 26) * Box(30, 30, 6, align=align)
                  + Pos(-12, 0, 0) * Box(6, 30, 32, align=align)) - Cylinder(5, 40, align=align)
        found = holes(clevis)
        self.assertEqual(len(found), 1, "one pin hole through both arms")
        self.assertTrue(found[0].thru)

        crossed = (Box(40, 40, 30, align=align) - Pos(0, 0, 5) * Cylinder(3, 25, align=align)
                   - Pos(0, 0, 12) * Rot(0, 90, 0) * Cylinder(5, 60))
        blind = [h for h in holes(crossed) if round(h.diameter, 3) == 6]
        self.assertEqual(len(blind), 1, "the bore below the cross hole is the same bore")
        self.assertFalse(blind[0].thru)
        self.assertAlmostEqual(blind[0].depth, 25.0, places=6)

    def test_a_groove_inside_a_blind_bore_does_not_end_it(self) -> None:
        from build123d import Align, Box, Cylinder, Pos
        from cadgen._internal.drawing_features import holes

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = Box(40, 40, 30, align=align) - Pos(0, 0, 10) * Cylinder(5, 20, align=align) \
            - Pos(0, 0, 18) * Cylinder(6, 3, align=align)
        (hole,) = holes(part)
        self.assertAlmostEqual(hole.diameter, 10.0, places=6)
        self.assertAlmostEqual(hole.depth, 20.0, places=6)

    def test_a_ring_groove_or_a_pocket_round_a_standoff_is_not_a_hole(self) -> None:
        """Concave and full circle, but with material inside: nothing a drill makes."""
        from build123d import Align, Box, Cylinder, Pos
        from cadgen._internal.drawing_features import holes

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        plate = Box(80, 80, 10, align=align)
        groove = plate - Pos(0, 0, 7) * (Cylinder(20, 3, align=align) - Cylinder(15, 3, align=align))
        self.assertEqual(holes(groove), [])
        standoff = plate - Pos(0, 0, 5) * Cylinder(15, 5, align=align) + Pos(0, 0, 5) * Cylinder(5, 5, align=align)
        self.assertEqual(holes(standoff), [])

    def test_a_bore_opened_out_at_both_ends_says_so(self) -> None:
        from build123d import Align, Box, Cone, Cylinder, Pos
        from cadgen._internal.drawing_features import holes

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = (Box(40, 40, 12, align=align) - Cylinder(5, 12, align=align)
                - Pos(0, 0, 11) * Cone(5, 6, 1, align=align) - Cone(6, 5, 1, align=align))
        (hole,) = holes(part)
        self.assertTrue(hole.thru)
        self.assertEqual((round(hole.csk[0], 6), hole.csk[1]), (12.0, 90.0))
        self.assertEqual(hole.far_csk, hole.csk, "the same chamfer at the other end")

    def test_two_halves_of_one_bore_are_one_bore(self) -> None:
        """A STEP from some kernels splits a full cylinder into two faces."""
        from cadgen._internal.drawing_features import _full, _merge_split_faces, _Segment

        halves = [_Segment("cyl", 0.0, 10.0, 3.0, 3.0, True, math.pi), _Segment("cyl", 0.0, 10.0, 3.0, 3.0, True, math.pi)]
        merged = _merge_split_faces(halves)
        self.assertEqual(len(merged), 1)
        self.assertTrue(_full(merged[0]))
        self.assertFalse(_full(_merge_split_faces(halves[:1])[0]), "half a bore is a slot end")


class TurnedTests(unittest.TestCase):
    def _shaft(self):
        from build123d import Align, Cylinder, Pos, Rot

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        along_x = Rot(0, 90, 0)
        return (Pos(0, 0, 0) * along_x * Cylinder(10, 30, align=align)
                + Pos(30, 0, 0) * along_x * Cylinder(15, 40, align=align)
                + Pos(70, 0, 0) * along_x * Cylinder(10, 30, align=align))

    def test_a_stepped_shaft_has_one_axis_end_to_end(self) -> None:
        from cadgen._internal.drawing_features import axes

        found = axes(self._shaft())
        self.assertEqual(len(found), 1, "three steps on one line are one turned axis")
        xs = sorted((found[0].start[0], found[0].end[0]))
        self.assertAlmostEqual(xs[0], 0.0, places=6)
        self.assertAlmostEqual(xs[1], 100.0, places=6)
        self.assertAlmostEqual(found[0].radius, 15.0, places=6)

    def test_turned_diameters_are_the_outside_steps_not_the_bores(self) -> None:
        from build123d import Box, Cylinder
        from cadgen._internal.drawing_features import turned_diameters

        self.assertEqual(turned_diameters(self._shaft()), [20.0, 30.0])
        self.assertEqual(turned_diameters(Box(40, 40, 10) - Cylinder(5, 10)), [], "a bore is a hole, not a step")
