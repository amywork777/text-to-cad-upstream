"""Constrained 2D sketches (``cadgen.sketch``): solved from their relations and dimensions, as
defined as a CAD tool says, and made into faces on their plane."""

from __future__ import annotations

import math
import unittest

import build123d as B

from cadgen.sketch import Sketch, SketchError


def plate(length=70.0, width=25.0, hole=8.0):
    s = Sketch("Sketch1", plane="Top")
    bottom, right, top, left = s.rectangle((0, 0), (60, 20))
    s.coincident(bottom.start, s.origin)
    s.length(bottom, length)
    s.length(left, width)
    circle = s.circle((30, 10), 3)
    s.diameter(circle, hole)
    s.horizontal_distance(bottom.start, circle.center, length / 2)
    s.vertical_distance(bottom.start, circle.center, width / 2)
    return s, bottom, right, top, left, circle


class Solving(unittest.TestCase):
    def test_a_dimensioned_plate_is_fully_defined_and_solved_where_its_sizes_put_it(self):
        s, bottom, right, top, left, circle = plate()
        self.assertEqual((s.status, s.dof), ("Fully defined", 0))
        self.assertAlmostEqual(top.end.x, 0.0, places=6)
        self.assertAlmostEqual(right.end.x, 70.0, places=6)
        self.assertAlmostEqual(right.end.y, 25.0, places=6)
        self.assertAlmostEqual(circle.radius, 4.0, places=6)
        self.assertAlmostEqual(circle.center.x, 35.0, places=6)

    def test_a_changed_size_moves_what_depends_on_it(self):
        s, *_, circle = plate(length=90.0)
        s.solve()
        self.assertAlmostEqual(circle.center.x, 45.0, places=6)

    def test_what_no_dimension_fixes_is_left_free_and_counted(self):
        s = Sketch()
        s.rectangle((0, 0), (10, 5))
        # A rectangle's lines held square still move, stretch and widen: four ways.
        self.assertEqual((s.status, s.dof), ("Under defined", 4))
        self.assertAlmostEqual(s.points[2].x, 10.0, places=6)

    def test_relations_that_cannot_all_hold_are_named(self):
        s = Sketch("Bad")
        bottom, right, top, left = s.rectangle((0, 0), (10, 5))
        s.length(bottom, 10)
        s.length(top, 12)
        with self.assertRaises(SketchError) as raised:
            s.solve()
        self.assertIn("can't all hold", str(raised.exception))

    def test_a_relation_that_adds_nothing_makes_the_sketch_over_defined(self):
        s = Sketch()
        bottom, right, top, left = s.rectangle((0, 0), (10, 5))
        s.coincident(bottom.start, s.origin)
        s.length(bottom, 10)
        s.length(left, 5)
        extra = s.length(top, 10)
        self.assertEqual(s.status, "Over defined")
        self.assertEqual(s.solve().redundant, [extra])

    def test_a_slot_of_tangent_arcs_solves_and_dimensions_like_a_cad_slot(self):
        s = Sketch("Slot")
        arc1, line1, arc2, line2 = s.slot((0, 0), (30, 0), 5)
        self.assertEqual((s.status, s.dof), ("Under defined", 5))
        s.fix(arc1.center)
        s.horizontal(arc1.center, arc2.center)
        s.distance(arc1.center, arc2.center, 40)
        s.radius(arc1, 6)
        self.assertEqual((s.status, s.dof), ("Fully defined", 0))
        self.assertAlmostEqual(s.face().area, 40 * 12 + math.pi * 36, places=6)

    def test_a_three_point_arc_bulges_toward_its_middle_point(self):
        s = Sketch()
        line = s.line((0, 0), (20, 0))
        s.three_point_arc(line.end, (10, 10), line.start)
        # Half a circle of radius 10 above the line.
        self.assertAlmostEqual(s.face().area, math.pi * 100 / 2, places=4)

    def test_a_polygon_is_its_lines_of_one_length_round_a_construction_circle(self):
        s = Sketch("Hex")
        *sides, circle = s.polygon((0, 0), (5, 0), 6)
        self.assertEqual((len(sides), circle.construction), (6, True))
        # Free to move, to grow and to turn: four ways.
        self.assertEqual((s.status, s.dof), ("Under defined", 4))
        s.coincident(circle.center, s.origin)
        s.diameter(circle, 20)
        s.horizontal(sides[1])
        self.assertEqual((s.status, s.dof), ("Fully defined", 0))
        # A regular hexagon 20 across its corners.
        self.assertAlmostEqual(s.face().area, 3 * math.sqrt(3) / 2 * 100, places=4)
        with self.assertRaises(SketchError):
            s.polygon((0, 0), (5, 0), 2)

    def test_a_linear_pattern_follows_its_spacing_and_a_circular_one_goes_round_its_center(self):
        s = Sketch("Holes")
        hole = s.circle((10, 0), 2)
        s.fix(hole.center)
        s.radius(hole, 2)
        row = s.linear_pattern([hole], 0, 8, 4)
        self.assertEqual((len(row), s.status), (3, "Fully defined"))
        self.assertEqual([round(copy.center.x, 6) for copy in row], [18, 26, 34])
        # Its spacing is a dimension: changed, the copies follow, each the hole's size.
        spacing = next(relation for relation in s.relations if relation.kind == "linear_pattern")
        spacing.value = 5
        s._changed()
        self.assertEqual(s.status, "Fully defined")
        self.assertEqual([(round(copy.center.x, 6), round(copy.radius, 6)) for copy in row], [(15, 2), (20, 2), (25, 2)])
        t = Sketch("Bolt circle")
        bolt = t.circle((20, 0), 3)
        t.radius(bolt, 3)
        t.horizontal_distance(t.origin, bolt.center, 20)
        t.vertical_distance(t.origin, bolt.center, 0)
        ring = t.circular_pattern([bolt], t.origin, 6)
        self.assertEqual((t.status, t.dof), ("Fully defined", 0))
        self.assertEqual([(round(copy.center.x, 6), round(copy.center.y, 6)) for copy in ring[:2]], [(10, round(20 * math.sin(math.pi / 3), 6)),
                                                                                                    (-10, round(20 * math.sin(math.pi / 3), 6))])
        with self.assertRaises(SketchError):
            t.circular_pattern([bolt], t.origin, 1)
        # A rectangle in a column: each copy a closed outline of its own.
        r = Sketch("Slots")
        column = r.linear_pattern(list(r.rectangle((0, 0), (4, 2))), 90, 5, 3)
        self.assertEqual((len(column), len(r.faces())), (8, 3))


class Faces(unittest.TestCase):
    def test_a_profile_with_a_hole_extrudes_along_its_plane(self):
        s, *_ = plate()
        solid = B.extrude(s.face(), amount=5)
        self.assertAlmostEqual(solid.volume, (70 * 25 - math.pi * 16) * 5, places=3)
        box = solid.bounding_box()
        self.assertAlmostEqual(box.min.Z, 0, places=6)
        self.assertAlmostEqual(box.max.Z, 5, places=6)

    def test_a_sketch_fillet_rounds_its_corner_in_the_face_and_its_dimensions_still_hold(self):
        s, bottom, right, top, left, circle = plate()
        s.fillet(bottom, right, 5)
        self.assertEqual(s.status, "Fully defined")
        self.assertAlmostEqual(right.end.x, 70.0, places=6)
        cut = 5 * 5 - math.pi * 25 / 4
        self.assertAlmostEqual(s.face().area, 70 * 25 - math.pi * 16 - cut, places=3)
        s.fillet(top, left, 30)
        with self.assertRaises(SketchError) as raised:
            s.face()
        self.assertIn("more than", str(raised.exception))

    def test_a_sketch_chamfer_cuts_its_corner_in_the_face_and_its_dimensions_still_hold(self):
        s, bottom, right, top, left, circle = plate()
        s.chamfer(bottom, right, 4)
        self.assertEqual(s.status, "Fully defined")
        self.assertAlmostEqual(right.end.x, 70.0, places=6)
        self.assertAlmostEqual(s.face().area, 70 * 25 - math.pi * 16 - 4 * 4 / 2, places=3)
        with self.assertRaises(SketchError) as cut:
            s.fillet(bottom, right, 2)
        self.assertIn("cut already", str(cut.exception))
        s.chamfer(top, left, 30)
        with self.assertRaises(SketchError) as raised:
            s.face()
        self.assertIn("distance of 30 is more than", str(raised.exception))

    def test_offset_entities_follow_what_they_are_offset_from(self):
        s, bottom, right, top, left, circle = plate()
        ring = s.circle(circle.center, 6)
        s.offset_entities(ring, circle, 2)
        made = [s.line((-1, -1), (71, -1))]
        made.append(s.line(made[0].end, (71, 26)))
        made.append(s.line(made[1].end, (-1, 26)))
        made.append(s.line(made[2].end, made[0].start))
        s.offset_entities(made, [bottom, right, top, left], 1)
        self.assertEqual((s.status, s.dof), ("Fully defined", 0))
        self.assertAlmostEqual(ring.radius, 6.0, places=6)
        bigger, *_ = plate(length=90.0)
        offset = [bigger.line((-1, -1), (71, -1))]
        offset.append(bigger.line(offset[0].end, (71, 26)))
        offset.append(bigger.line(offset[1].end, (-1, 26)))
        offset.append(bigger.line(offset[2].end, offset[0].start))
        bigger.offset_entities(offset, bigger.curves[:4], 1)
        bigger.solve()
        self.assertAlmostEqual(offset[1].start.x, 91.0, places=6)

    def test_front_and_right_sketches_face_their_planes(self):
        for plane, normal in (("Front", (0, -1, 0)), ("Right", (1, 0, 0)), ("Top", (0, 0, 1))):
            s = Sketch(plane=plane)
            s.rectangle((0, 0), (20, 10))
            self.assertEqual(tuple(round(c) for c in s.face().normal_at()), normal)

    def test_an_open_profile_says_where_it_is_open(self):
        s = Sketch("Open")
        s.polyline((0, 0), (10, 0), (10, 5))
        with self.assertRaises(SketchError) as raised:
            s.face()
        self.assertIn("is open at", str(raised.exception))

    def test_construction_geometry_is_no_part_of_the_profile(self):
        s = Sketch()
        s.center_rectangle((0, 0), (10, 5))
        self.assertAlmostEqual(s.face().area, 200, places=6)


class Splines(unittest.TestCase):
    """A spline passes through its points: a side of a profile, a loop of its own closed, or a path."""

    def test_a_spline_is_a_side_of_a_profile_or_closed_a_loop_of_its_own(self):
        s = Sketch("Sketch1", plane="Top")
        bottom = s.line((0, 0), (20, 0))
        side = s.spline(bottom.end, (25, 8), (10, 15), (0, 10))
        s.line(side.end, bottom.start)
        # Its points move it: four of them free, and the line's start.
        self.assertEqual((s.status, s.dof), ("Under defined", 10))
        # The spline bulges past its chord from (20, 0) to (0, 10): more than the triangle under it.
        self.assertGreater(s.face().area, 20 * 10 / 2 + 100)
        blob = Sketch("Sketch2", plane="Front")
        blob.spline((0, 0), (10, 5), (0, 10), (-10, 5), closed=True)
        self.assertAlmostEqual(blob.face().area, 160, delta=1)
        self.assertNotIn("start", blob.state()["curves"][0])
        with self.assertRaises(SketchError):
            blob.spline((0, 0), (1, 1), closed=True)

    def test_convert_brings_a_spline_edge_or_a_tilted_circle_in_as_a_spline_held_where_the_model_has_it(self):
        curve = B.Edge.make_spline([B.Vector(0, 0, 2), B.Vector(10, 6, 2), B.Vector(20, 0, 2)])
        s = Sketch("Sketch1", plane="Top")
        (spline,) = s.convert(curve)
        self.assertEqual((type(spline).__name__, s.status), ("Spline", "Fully defined"))
        self.assertEqual([(round(spline.start.x, 6), round(spline.end.x, 6))], [(0, 20)])
        # Through the edge where it falls on the plane: its middle at (10, 6) as the edge's is.
        middle = spline.points[len(spline.points) // 2]
        self.assertAlmostEqual(math.hypot(middle.x - 10, middle.y - 6), 0, places=1)
        # A circle tilted to the sketch comes in as the ellipse it falls as: a closed spline.
        tilted = B.Edge.make_circle(5, B.Plane(origin=(0, 0, 0), z_dir=(1, 0, 1)))
        (ellipse,) = Sketch("Sketch2", plane="Top").convert(tilted)
        self.assertTrue(ellipse.closed)
        widths = [point.x for point in ellipse.points]
        self.assertAlmostEqual(max(widths) - min(widths), 2 * 5 * math.cos(math.radians(45)), places=1)

    def test_a_path_runs_along_a_spline(self):
        s = Sketch("Path", plane="Front")
        s.spline((0, 0), (10, 5), (20, 0))
        path = s.path()
        self.assertGreater(path.length, 20)
        self.assertAlmostEqual(path.position_at(1).X, 20, places=6)


class Paths(unittest.TestCase):
    """A sketch as what a sweep runs along, a thin feature's wall and a rib."""

    def test_a_path_joins_its_curves_end_to_end_and_a_sweep_runs_a_profile_along_it(self):
        path = Sketch("Path1", plane="Front")
        up = path.line((0, 0), (0, 20))
        across = path.line((0, 20), (15, 20))
        path.coincident(up.end, across.start)
        wire = path.path()
        self.assertEqual((len(wire.edges()), wire.is_closed), (2, False))
        self.assertAlmostEqual(wire.length, 35.0, places=6)
        profile = Sketch("Profile1", plane="Top")
        profile.circle((0, 0), 2)
        # Mitred at its corner, as a CAD tool sweeps round one.
        self.assertAlmostEqual(B.sweep(profile.face(), path=wire, transition=B.Transition.RIGHT).volume, math.pi * 4 * 35, delta=1e-3)
        # Three curves at one point is not one chain.
        path.line((0, 20), (-10, 20))
        with self.assertRaisesRegex(SketchError, "meet at"):
            path.path()

    def test_a_thin_wall_goes_inside_outside_or_astride_an_outline_and_beside_an_open_line(self):
        box = Sketch("Box", plane="Top")
        box.rectangle((0, 0), (20, 10))
        areas = {side: sum(face.area for face in box.thin(1, side=side)) for side in ("inside", "outside", "mid")}
        self.assertAlmostEqual(areas["inside"], 20 * 10 - 18 * 8, places=6)
        self.assertAlmostEqual(areas["outside"], 22 * 12 - 20 * 10, places=6)
        self.assertAlmostEqual(areas["mid"], 21 * 11 - 19 * 9, places=6)
        line = Sketch("Wall", plane="Top")
        line.line((0, 0), (10, 0))
        # Astride an open line, square at its ends.
        self.assertAlmostEqual(sum(face.area for face in line.thin(2, side="mid")), 20.0, places=6)
        with self.assertRaisesRegex(SketchError, "thickness"):
            box.thin(0)

    def test_a_rib_grows_from_its_line_until_it_meets_the_body_the_way_it_is_turned(self):
        # A channel: a floor 5 thick between two walls; a rib's line across its top, 8 up.
        channel = B.Box(40, 20, 20) - B.Pos(0, 0, 5) * B.Box(30, 30, 20)
        rib = Sketch("Rib1", plane="Front")
        rib.line((-15, 8), (15, 8))
        grown = rib.rib(2, channel, flip=True)
        self.assertAlmostEqual(grown.volume, 30 * 2 * 13, places=3)
        self.assertAlmostEqual(grown.bounding_box().min.Z, -5, places=6)
        with self.assertRaisesRegex(SketchError, "Flip it"):
            rib.rib(2, channel)


class State(unittest.TestCase):
    def test_an_editor_reads_the_sketch_as_solved_with_where_each_line_of_it_is(self):
        s, *_ = plate()
        state = s.state()
        self.assertEqual((state["name"], state["plane"], state["status"], state["dof"]), ("Sketch1", "Top", "Fully defined", 0))
        self.assertEqual([curve["id"] for curve in state["curves"]], ["Line1", "Line2", "Line3", "Line4", "Circle1"])
        self.assertEqual([d["id"] for d in state["dimensions"]], ["D1", "D2", "D3", "D4", "D5"])
        self.assertTrue(all(d["file"].endswith("test_sketch.py") and d["line"] > 0 for d in state["dimensions"]))
        self.assertIn("Horizontal1", [r["id"] for r in state["relations"]])

    def test_its_closed_loops_come_as_outlines_to_shade_the_profile_a_feature_takes(self):
        s, *_ = plate()
        loops = s.state()["loops"]
        # The plate's outline and its hole: an even-odd fill shades the plate around the hole.
        self.assertEqual(len(loops), 2)
        corners = {tuple(point) for point in loops[1]}
        self.assertEqual(corners, {(0.0, 0.0), (70.0, 0.0), (70.0, 25.0), (0.0, 25.0)})
        for x, y in loops[0]:
            self.assertAlmostEqual(math.hypot(x - 35, y - 12.5), 4.0, places=5)
        open_sketch = Sketch("Open")
        open_sketch.polyline((0, 0), (10, 0), (10, 5))
        self.assertEqual(open_sketch.state()["loops"], [])


class Converting(unittest.TestCase):
    """Convert Entities and the depths an extrude ends at, from the model's own edges and faces."""

    def setUp(self):
        # A 30 x 20 x 4 plate, its corners rounded, a hole through it.
        rounded = B.fillet(B.Box(30, 20, 4).edges().filter_by(B.Axis.Z), radius=3)
        self.part = rounded - B.Pos(5, 0, 0) * B.Cylinder(2, 10)
        self.top = self.part.faces().sort_by(B.Axis.Z)[-1]

    def test_a_face_comes_in_whole_held_where_the_model_puts_it(self):
        s = Sketch("Sketch1", plane="Top")
        made = s.convert(self.top)
        self.assertEqual(sorted(type(curve).__name__ for curve in made), ["Arc"] * 4 + ["Circle"] + ["Line"] * 4)
        self.assertEqual(s.status, "Fully defined")
        # Projected onto the Top plane, 2 below the face: the same profile, its hole and all.
        self.assertAlmostEqual(s.face().area, self.top.area, places=6)
        self.assertEqual({r.kind for r in s.relations}, {"on_edge"})
        self.assertTrue(all(curve.get("converted") for curve in s.state()["curves"]))

    def test_what_cannot_come_in_flat_is_refused_and_edges_square_to_it_are_left_out(self):
        # The hole's rim seen edge on from the front falls as a line over itself (a circle tilted
        # less comes in as a spline, `Splines`).
        edge_on = Sketch("Sketch1", plane="Front")
        with self.assertRaisesRegex(SketchError, "folds onto itself on Sketch1"):
            edge_on.convert(self.top.edges().filter_by(B.GeomType.CIRCLE))
        upright = self.part.edges().filter_by(B.Axis.Z)
        with self.assertRaisesRegex(SketchError, "square to Sketch2"):
            Sketch("Sketch2", plane="Top").convert(upright)

    def test_an_extrude_ends_at_a_parallel_face_or_a_vertex_by_its_depth(self):
        s = Sketch("Sketch1", plane="Top", offset=-1)
        self.assertAlmostEqual(s.depth_to(self.top), 3.0)
        self.assertAlmostEqual(s.depth_to(self.part.vertices().sort_by(B.Axis.Z)[0]), -1.0)
        side = self.part.faces().filter_by(B.Plane.YZ)[0]
        with self.assertRaisesRegex(SketchError, "parallel"):
            s.depth_to(side)


if __name__ == "__main__":
    unittest.main()
