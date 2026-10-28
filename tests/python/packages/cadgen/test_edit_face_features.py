"""Which feature made each face of a part (``cadgen.edit.face_features``): each reading of a part by
the edit service says, for every face by the number the viewer's references give it (``f12``), the
feature of the first traced step whose result has a face on the same surface that also overlaps it,
the very same B-rep face or one holding a point inside it (``faceFeatures``), and how many faces that
body has (``faceCount``); the rollback bar's body, which the viewer names no face on, says neither.

They drive the edit service end to end, as the viewer's server does, on ``test_edit_commands.py``'s
parts. The faces are numbered as the viewer numbers them (``faces_on_screen``): the part's document as
the engine makes it of its model, read back as the viewer's document is numbered. The surface keys are read on build123d's own faces (``SurfaceKeys``), and
the map itself on a body made here where OCCT is made to fail (``FaceMap``).
"""

from __future__ import annotations

import math
import os
import runpy
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.python.packages.cadgen import test_edit_commands as parts


def setUpModule():
    """An engine of this file's own (its folders, and a free port), started, which every process the
    edit service starts inherits: the rollback bar's body is handed to it (``tracer._bar_document``)."""
    from unittest import mock

    from tests.python.support import engine_daemon

    engine_daemon.isolate(unittest.addModuleCleanup)
    patch = mock.patch.dict(os.environ, {"CADGEN_ENGINE_PORT": "0"})
    patch.start()
    unittest.addModuleCleanup(patch.stop)
    # Running, as the engine's daemon the service is part of runs: the service's children never start one.
    from cadgen.engine import client

    with client.connect():
        pass

# PLATE placed at its end, as a part returned as ``Pos(...) * body`` is, and moved in place there.
PLACED = {"plate.py": parts.PLATE["plate.py"].replace("return plate", "return bd.Pos(0, 0, 10) * plate")}
MOVED = {"plate.py": parts.PLATE["plate.py"].replace(
    "            return plate", "            plate.move(bd.Location((0, 0, 10)))\n            return plate")}

# A loft from a square up to a circle: its sides are free-form (B-spline) surfaces, its ends flat.
FUNNEL = {
    "funnel.py": """
        from build123d import Circle, Plane, Rectangle, loft
        from cadgen import model


        @model
        def funnel():
            base = Rectangle(20, 20)
            top = Plane.XY.offset(15) * Circle(5)
            return loft([base, top])
    """,
}

# A plate with two tabs on it, their tops flush with each other, as bosses of one height are; and the
# same with a hole into the second tab's top, which leaves that face a new one, and the plate's top as
# the tabs left it.
TABS = {
    "tabs.py": """
        from build123d import Box, Pos
        from cadgen import model


        @model
        def tabs():
            plate = Box(100, 50, 10)
            plate += Pos(-30, 0, 8.5) * Box(10, 10, 7)
            plate += Pos(30, 0, 8.5) * Box(10, 10, 7)
            return plate
    """,
}
HOLED = {"tabs.py": TABS["tabs.py"].replace(
    "            return plate", "            plate -= Pos(30, 0, 10) * Cylinder(2, 4)\n            return plate").replace(
    "import Box, Pos", "import Box, Cylinder, Pos")}

# A plate whose top a later slot splits in two.
SLOTTED = {
    "slotted.py": """
        from build123d import Box, Pos
        from cadgen import model


        @model
        def slotted():
            plate = Box(100, 50, 10)
            plate -= Pos(0, 0, 5) * Box(10, 60, 4)
            return plate
    """,
}

def walled(length: float, width: float, wall: float) -> dict[str, str]:
    """An open tray with thin walls, as an enclosure is made: a block, and a cavity cut down into it
    from above. Its rim is a narrow frame round the cavity."""
    return {
        "tray.py": f"""
            from build123d import Box, Pos
            from cadgen import model


            @model
            def tray():
                body = Box({length}, {width}, 30)
                body -= Pos(0, 0, 1) * Box({length - 2 * wall}, {width - 2 * wall}, 30)
                return body
        """,
    }


# PLATE's top edges as the viewer reads them, for an Edge Blend on them.
HALF_LENGTH, HALF_WIDTH, TOP = 25.4, 12.7, 3.175
PLATE_TOP_EDGES = [parts.edge("e1", (0, -HALF_WIDTH, TOP), 50.8), parts.edge("e2", (0, HALF_WIDTH, TOP), 50.8),
                   parts.edge("e3", (-HALF_LENGTH, 0, TOP), 25.4), parts.edge("e4", (HALF_LENGTH, 0, TOP), 25.4)]


def faces_on_screen(script: Path) -> dict[int, object]:
    """A part's faces by the numbers the viewer's references give them (``face 12``, ``f12``): the
    part's document as the engine makes it of its model, built in this process (``daemon=False``:
    no engine runs) and written as its xbf, then read back by the scene adapter as the viewer's
    document is numbered (``step_open``)."""
    from cadgen._internal.step_open import open_scene
    from cadgen.engine import api
    from cadgen.engine.model import models_in

    folder = str(script.parent)
    sys.path.insert(0, folder)
    try:
        made = runpy.run_path(str(script), run_name=f"made_{script.stem}")
        model = models_in(made, script)[0]
        document = script.with_suffix(".xbf")
        api.export(model, document, daemon=False)
    finally:
        sys.path.remove(folder)
    (leaf,) = open_scene(document).leaves()
    return {face.ordinal: face.shape() for face in leaf.entities("face")}


def faces_of(shape) -> dict[int, object]:
    """A shape's faces by their numbers on it, as the viewer numbers a tree's faces (``entity_map``)."""
    from build123d import Face
    from OCP.TopoDS import TopoDS

    from cadgen._internal.entity_ordinals import entity_map

    found = entity_map(shape.wrapped, "face")
    return {number: Face(TopoDS.Face(found.FindKey(number))) for number in range(1, found.Extent() + 1)}


def kind(face) -> str:
    """``plane``, ``cylinder``, ``torus``, ``bspline``: a face's surface as build123d names it."""
    return face.geom_type.name.lower()


def is_round(face, radius: float) -> bool:
    return kind(face) == "cylinder" and math.isclose(face.radius, radius, rel_tol=1e-9)


class FaceFeatures(parts.Commands):
    def key(self, state: dict, feature_kind: str) -> str:
        return next(feature["key"] for feature in state["features"] if feature["kind"] == feature_kind)

    def test_credits_a_face_a_later_hole_cuts_through_to_the_block_that_made_it(self):
        from build123d import CenterOf

        root, file, state = self.open(parts.PLATE, "plate.step")
        plate, hole = self.key(state, "Boss-Extrude"), self.key(state, "Hole")
        faces = faces_on_screen(root / "plate.py")
        top = next(number for number, face in faces.items()
                   if kind(face) == "plane" and math.isclose(face.center(CenterOf.MASS).Z, TOP))
        wall = next(number for number, face in faces.items() if kind(face) == "cylinder")
        self.assertEqual(state["faceFeatures"][str(top)], plate)
        self.assertEqual(state["faceFeatures"][str(wall)], hole)
        # Every face is known, by the number the viewer gives it: the block's six, the hole's wall.
        self.assertEqual(state["faceFeatures"], {str(number): hole if number == wall else plate for number in faces})
        self.assertEqual(state["faceCount"], len(faces))
        # And that number is the one a command takes the face by, sent as a selector alone, as the edit tests send one: the top's edges.
        chamfered = self.command(file, state, "chamfer", [{"selector": f"f{top}"}], {"distance": ".02"})
        self.assertTrue(chamfered["ok"], chamfered.get("error"))
        line = next(line for line in (root / "plate.py").read_text(encoding="utf-8").splitlines() if "bd.chamfer(" in line)
        self.assertIn(".group_by(bd.Axis.Z)[-1]", line)
        self.assertEqual(chamfered["change"]["what"], "5 edges")

    def test_credits_a_fillets_round_face_to_the_fillet(self):
        root, file, state = self.open(parts.PLATE, "plate.step")
        made = self.command(file, state, "fillet", PLATE_TOP_EDGES, {"radius": ".05"})
        self.assertTrue(made["ok"], made.get("error"))
        plate, hole, fillet = self.key(made, "Boss-Extrude"), self.key(made, "Hole"), self.key(made, "Fillet")
        self.assertEqual(fillet, made["change"]["row"])
        faces = faces_on_screen(root / "plate.py")
        credited = made["faceFeatures"]
        rounds = [number for number, face in faces.items() if is_round(face, .05 * 25.4)]
        self.assertEqual(len(rounds), 4)
        self.assertEqual({credited[str(number)] for number in rounds}, {fillet})
        # The hole's wall stays the hole's, and the block's planes, trimmed by the rounds, the block's.
        (wall,) = [number for number, face in faces.items() if is_round(face, .1 * 25.4)]
        self.assertEqual(credited[str(wall)], hole)
        self.assertEqual({credited[str(number)] for number, face in faces.items() if kind(face) == "plane"}, {plate})
        self.assertEqual(len(credited), len(faces))

    def test_leaves_out_a_face_it_cannot_key(self):
        root, file, state = self.open(FUNNEL, "funnel.step")
        loft = next(feature["key"] for feature in state["features"] if "Loft" in feature["kind"])
        faces = faces_on_screen(root / "funnel.py")
        free = [number for number, face in faces.items() if kind(face) == "bspline"]
        self.assertTrue(free)
        for number in free:
            self.assertNotIn(str(number), state["faceFeatures"])
        # Its flat ends are known, and the loft made them.
        self.assertEqual(state["faceFeatures"], {str(number): loft for number, face in faces.items() if kind(face) == "plane"})
        self.assertEqual(state["faceCount"], len(faces))

    def test_has_no_map_for_an_assembly(self):
        root, file, state = self.open(parts.ASSEMBLY, "assemblies/stack.step")
        self.assertEqual([component["name"] for component in state["components"]], ["base", "pin"])
        self.assertEqual(state["faceFeatures"], {})

    def test_the_rollback_bars_body_has_no_map(self):
        from cadgen.engine import api

        root, file, state = self.open(parts.PLATE, "plate.step")
        hole = self.key(state, "Hole")
        rolled = self.service.change({"file": file, "files": state["files"], "bar": {"item": hole}})
        self.assertTrue(rolled["ok"], rolled.get("error"))
        bar = rolled["bar"]
        # The plate before its hole, the engine's document the viewer opens in the part's place; the viewer names
        # no face on it (`edit/faceChips.js`'s `shownFaces`), so the bar says no feature made any.
        summary = api.inspect(bar["document"]["id"], query="summary")["summary"]
        self.assertAlmostEqual(summary["volume"], (2 * 25.4) * (1 * 25.4) * (.25 * 25.4), places=3)
        self.assertNotIn("faceFeatures", bar)
        self.assertNotIn("faceCount", bar)
        # The part as a whole keeps its map, the hole's wall in it.
        self.assertIn(hole, state["faceFeatures"].values())

    def tab_features(self, state: dict) -> tuple[str, str, str]:
        """The plate's, the first tab's and the second tab's features, in the order the script makes them."""
        plate, first, second, *_ = [feature["key"] for feature in state["features"]]
        return plate, first, second

    def test_credits_flush_tabs_each_to_its_own_extrude(self):
        from build123d import CenterOf

        root, file, state = self.open(TABS, "tabs.step")
        plate, first, second = self.tab_features(state)
        faces = faces_on_screen(root / "tabs.py")

        def maker(face):
            # A tab's faces stand above the plate's top, at x = -30 or 30.
            centre = face.center(CenterOf.MASS)
            return plate if centre.Z <= 5 + 1e-9 else first if centre.X < 0 else second

        tops = {round(face.center(CenterOf.MASS).X): number for number, face in faces.items()
                if kind(face) == "plane" and math.isclose(face.center(CenterOf.MASS).Z, 12)}
        self.assertEqual(state["faceFeatures"][str(tops[30])], second)
        self.assertEqual(state["faceFeatures"][str(tops[-30])], first)
        # Their sides are flush too, and the plate's top runs round both: every face is its own feature's.
        self.assertEqual(state["faceFeatures"], {str(number): maker(face) for number, face in faces.items()})

    def test_a_plates_top_split_by_a_later_slot_stays_the_plates(self):
        from build123d import CenterOf

        root, file, state = self.open(SLOTTED, "slotted.step")
        plate = state["features"][0]["key"]
        faces = faces_on_screen(root / "slotted.py")
        halves = [number for number, face in faces.items() if kind(face) == "plane" and math.isclose(face.center(CenterOf.MASS).Z, 5)]
        self.assertEqual(len(halves), 2)
        self.assertEqual({state["faceFeatures"][str(number)] for number in halves}, {plate})

    def test_a_hole_through_a_tabs_top_keeps_the_tabs_credit(self):
        from build123d import CenterOf

        root, file, state = self.open(HOLED, "tabs.step")
        plate, first, second = self.tab_features(state)
        hole = self.key(state, "Hole")
        faces = faces_on_screen(root / "tabs.py")
        credited = state["faceFeatures"]

        def at(z, x=None):
            return next(number for number, face in faces.items() if kind(face) == "plane"
                        and math.isclose(face.center(CenterOf.MASS).Z, z, abs_tol=1e-9)
                        and (x is None or math.isclose(face.center(CenterOf.MASS).X, x, abs_tol=1e-6)))

        # The second tab's top, a new face round the hole, is still that tab's; the first's is the first's.
        self.assertEqual(credited[str(at(12, 30))], second)
        self.assertEqual(credited[str(at(12, -30))], first)
        # The plate's top as the tabs left it, which the hole does not touch, is still the plate's.
        self.assertEqual(credited[str(at(5))], plate)
        # The hole's floor and wall are the hole's.
        self.assertEqual(credited[str(at(8))], hole)
        (wall,) = [number for number, face in faces.items() if kind(face) == "cylinder"]
        self.assertEqual(credited[str(wall)], hole)

    def test_a_thin_walled_trays_rim_is_the_extrudes(self):
        from build123d import CenterOf

        for length, width, wall in ((100, 60, 1), (80, 50, 2.5)):
            with self.subTest(f"{length} x {width}, {wall} mm walls"):
                root, file, state = self.open(walled(length, width, wall), "tray.step")
                block, cavity = self.key(state, "Boss-Extrude"), self.key(state, "Cut-Extrude")
                faces = faces_on_screen(root / "tray.py")
                (rim,) = [number for number, face in faces.items()
                          if kind(face) == "plane" and math.isclose(face.center(CenterOf.MASS).Z, 15)]
                self.assertTrue(math.isclose(faces[rim].area, length * width - (length - 2 * wall) * (width - 2 * wall)))
                self.assertEqual(state["faceFeatures"].get(str(rim)), block)
                # Every face is known: the block's outside and its rim, the cavity's walls and floor.
                inside = {number for number, face in faces.items()
                          if abs(face.center(CenterOf.MASS).X) < length / 2 - wall / 2 and abs(face.center(CenterOf.MASS).Y) < width / 2 - wall / 2
                          and face.center(CenterOf.MASS).Z > -15 + 1e-9 and number != rim}
                self.assertEqual(state["faceFeatures"], {str(number): cavity if number in inside else block for number in faces})

    def test_a_body_placed_at_its_end_keeps_the_features_that_made_its_faces(self):
        for name, files in (("placed", PLACED), ("moved in place", MOVED)):
            with self.subTest(name):
                root, file, state = self.open(files, "plate.step")
                plate, hole = self.key(state, "Boss-Extrude"), self.key(state, "Hole")
                faces = faces_on_screen(root / "plate.py")
                (wall,) = [number for number, face in faces.items() if kind(face) == "cylinder"]
                self.assertEqual(state["faceFeatures"], {str(number): hole if number == wall else plate for number in faces})


class FaceMap(unittest.TestCase):
    """``face_features`` itself, in the tracer's process: on a body and the steps that made it, made here."""

    def test_a_face_occt_cannot_read_has_no_name_and_the_rest_keep_theirs(self):
        from build123d import Box

        from cadgen.edit import face_features as faces

        box = Box(10, 20, 30)
        steps, row_of, features = [{"index": 0, "result": box}], {0: "box.py:7"}, [{"key": "box.py:7"}]
        self.assertEqual(faces.face_features(box, steps, row_of, features), {str(number): "box.py:7" for number in range(1, 7)})
        # OCCT throws on the third face it is asked about, as it does on a face it cannot read.
        maker, asked = faces._maker, []

        def failing(face, *rest):
            asked.append(face)
            if len(asked) == 3:
                raise RuntimeError("Standard_Failure")
            return maker(face, *rest)

        with mock.patch.object(faces, "_maker", failing):
            self.assertEqual(faces.face_features(box, steps, row_of, features), {str(number): "box.py:7" for number in (1, 2, 4, 5, 6)})


class SurfaceKeys(unittest.TestCase):
    """``surface_key``: the surface a face lies on, as one key, whichever way the face faces."""

    def test_a_plane_is_one_surface_whichever_way_its_face_faces(self):
        from build123d import Axis, Box, Face, Pos

        from cadgen.edit.face_features import surface_key

        box = Box(10, 20, 30)
        top = box.faces().sort_by(Axis.Z)[-1]
        front = box.faces().sort_by(Axis.Y)[0]
        flipped = Face(top.wrapped.Reversed())
        self.assertIsNotNone(surface_key(top, size=10))
        self.assertEqual(surface_key(flipped, size=10), surface_key(top, size=10))
        self.assertEqual(surface_key(Face(front.wrapped.Reversed()), size=10), surface_key(front, size=10))
        # Another box's top on the same plane is that plane; its bottom, the plane below, is not.
        other = Pos(40, 0, 0) * Box(5, 5, 30)
        self.assertEqual(surface_key(other.faces().sort_by(Axis.Z)[-1], size=10), surface_key(top, size=10))
        self.assertNotEqual(surface_key(box.faces().sort_by(Axis.Z)[0], size=10), surface_key(top, size=10))

    def test_a_cylinder_is_its_axis_line_and_radius(self):
        from build123d import Cylinder, Pos, Rot

        from cadgen.edit.face_features import surface_key

        def wall(shape):
            return next(face for face in shape.faces() if face.geom_type.name == "CYLINDER")

        up = wall(Cylinder(2, 10))
        # The same axis line turned end over end, or slid along itself, is the same cylinder.
        self.assertEqual(surface_key(wall(Rot(180, 0, 0) * Cylinder(2, 10)), size=10), surface_key(up, size=10))
        self.assertEqual(surface_key(wall(Pos(0, 0, 7) * Cylinder(2, 4)), size=10), surface_key(up, size=10))
        self.assertNotEqual(surface_key(wall(Pos(1, 0, 0) * Cylinder(2, 10)), size=10), surface_key(up, size=10))
        self.assertNotEqual(surface_key(wall(Cylinder(3, 10)), size=10), surface_key(up, size=10))

    def test_a_cone_a_sphere_and_a_torus_are_their_own_surfaces_turned_end_over_end(self):
        from build123d import Cone, Pos, Rot, Sphere, Torus

        from cadgen.edit.face_features import surface_key

        def curved(shape):
            (face,) = [face for face in shape.faces() if face.geom_type.name in ("CONE", "SPHERE", "TORUS")]
            return surface_key(face, size=20)

        for name, made, turned, other in (
            # A cone narrowing up, and the cone widening up turned over: one surface through one apex.
            ("cone", Cone(5, 2, 10), Rot(180, 0, 0) * Cone(2, 5, 10), Cone(5, 1, 10)),
            ("sphere", Sphere(3), Rot(30, 40, 0) * Sphere(3), Pos(0, 0, 1) * Sphere(3)),
            ("torus", Torus(10, 2), Rot(180, 0, 0) * Torus(10, 2), Torus(10, 3)),
        ):
            with self.subTest(name):
                self.assertIsNotNone(curved(made))
                self.assertEqual(curved(turned), curved(made))
                self.assertNotEqual(curved(other), curved(made))

    def test_a_part_in_inches_keys_as_the_same_part_in_millimetres(self):
        from build123d import Box, Cylinder, Pos

        from cadgen.edit.face_features import surface_key

        def part(scale):
            return Box(2 * scale, 1 * scale, .25 * scale) - Pos(.5 * scale, .1 * scale, 0) * Cylinder(.1 * scale, .25 * scale)

        inches, millimetres = part(1), part(25.4)
        keys = [surface_key(face, size=inches.bounding_box().diagonal) for face in inches.faces()]
        self.assertEqual([surface_key(face, size=millimetres.bounding_box().diagonal) for face in millimetres.faces()], keys)
        self.assertNotIn(None, keys)

    def test_a_free_form_face_has_no_key(self):
        from build123d import Circle, Plane, Rectangle, loft

        from cadgen.edit.face_features import surface_key

        funnel = loft([Rectangle(20, 20), Plane.XY.offset(15) * Circle(5)])
        free = [face for face in funnel.faces() if face.geom_type.name == "BSPLINE"]
        self.assertTrue(free)
        self.assertEqual({surface_key(face, size=30) for face in free}, {None})


if __name__ == "__main__":
    unittest.main()
