"""Studio's standard custom features (``cad.build123d.standard_features``): each made on a plate and
measured against the table its sizes come from, each refusal in its own words, and one inserted from the
Custom menu end to end, imported from its module as a project's own feature is from its file.
"""

from __future__ import annotations

import math
import shutil
import unittest

from tests.python.packages.cad.test_edit import project
from tests.python.packages.cad.test_edit import setUpModule as _engine_of_its_own


def setUpModule():
    _engine_of_its_own()


W, D, T = 80.0, 60.0, 6.0


def plate():
    import build123d as bd

    body = bd.Box(W, D, T)
    return body, body.faces().sort_by(bd.Axis.Z)[-1]


class Geometry(unittest.TestCase):
    def assertRemoved(self, before, after, volume, places=2):
        self.assertAlmostEqual(before.volume - after.volume, volume, places=places)

    def test_a_bolt_circle_cuts_each_hole_through(self):
        from cad.build123d.standard_features import bolt_circle

        body, top = plate()
        made = bolt_circle(body, top, diameter=40, count=6, hole=5)
        self.assertRemoved(body, made, 6 * math.pi * 2.5 ** 2 * T)

    def test_a_half_circle_spreads_its_holes_over_half_a_turn_end_to_end(self):
        import build123d as bd
        from cad.build123d.standard_features import bolt_circle

        body, top = plate()
        made = bolt_circle(body, top, diameter=40, count=3, hole=4, spread="half")
        self.assertRemoved(body, made, 3 * math.pi * 2 ** 2 * T)
        # Holes at 0, 90 and 180 degrees: the plate keeps its material at 270.
        self.assertTrue(made.is_inside(bd.Vector(0, -20, 0)))
        self.assertFalse(made.is_inside(bd.Vector(0, 20, 0)))

    def test_a_clearance_hole_is_iso_273_s_size_for_its_screw_and_fit(self):
        from cad.build123d.standard_features import ISO_273, clearance_hole

        body, top = plate()
        for size, fit, wanted in (("M3", "medium", 3.4), ("M4", "fine", 4.3), ("M8", "coarse", 10.0), ("M2.5", "medium", 2.9)):
            with self.subTest(size=size, fit=fit):
                self.assertEqual(ISO_273[size][fit], wanted)
                made = clearance_hole(body, top, size=size, fit=fit, x=10, y=-5)
                self.assertRemoved(body, made, math.pi * (wanted / 2) ** 2 * T)

    def test_an_insert_boss_stands_on_the_face_with_the_maker_s_hole_its_length_deep(self):
        from cad.build123d.standard_features import CNC_KITCHEN_INSERTS, heat_set_insert_boss

        body, top = plate()
        insert = CNC_KITCHEN_INSERTS["M3"]
        self.assertEqual((insert["length"], insert["hole"], insert["wall"]), (5.7, 4.0, 1.6))
        made = heat_set_insert_boss(body, top, size="M3", height=8)
        outer = insert["hole"] + 2 * insert["wall"]
        added = math.pi * (outer / 2) ** 2 * 8 - math.pi * (insert["hole"] / 2) ** 2 * insert["length"]
        self.assertAlmostEqual(made.volume - body.volume, added, places=2)
        self.assertAlmostEqual(made.bounding_box().max.Z, T / 2 + 8, places=4)

    def test_an_insert_boss_of_no_height_is_the_hole_alone_and_extra_depth_goes_deeper(self):
        from cad.build123d.standard_features import CNC_KITCHEN_INSERTS, heat_set_insert_boss

        body, top = plate()
        insert = CNC_KITCHEN_INSERTS["M2"]
        made = heat_set_insert_boss(body, top, size="M2", height=0, extra_depth=0.5)
        self.assertRemoved(body, made, math.pi * (insert["hole"] / 2) ** 2 * (insert["length"] + 0.5))

    def test_vent_slots_cut_each_slot_through(self):
        from cad.build123d.standard_features import vent_slots

        body, top = plate()
        made = vent_slots(body, top, length=20, width=3, count=6, pitch=6, rows=2, row_pitch=25)
        slot = 17 * 3 + math.pi * 1.5 ** 2
        self.assertRemoved(body, made, 12 * slot * T)

    def test_each_standard_size_has_its_source_s_numbers(self):
        from cad.build123d.standard_features import CNC_KITCHEN_INSERTS, ISO_273

        # ISO 273:1979 Table 1, fine / medium / coarse.
        self.assertEqual({size: tuple(each.values()) for size, each in ISO_273.items()},
                         {"M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1), "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8),
                          "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0), "M8": (8.4, 9.0, 10.0)})
        # CNC Kitchen standard inserts: length, hole D3, minimum wall W.
        self.assertEqual({size: tuple(each.values()) for size, each in CNC_KITCHEN_INSERTS.items()},
                         {"M2": (3.0, 3.2, 1.3), "M2.5": (4.0, 4.0, 1.6), "M3": (5.7, 4.0, 1.6), "M4": (8.1, 5.6, 2.1),
                          "M5": (9.5, 6.4, 2.6)})


class Refusals(unittest.TestCase):
    def refused(self, call, words, param):
        from cad.build123d import FeatureError

        with self.assertRaises(FeatureError) as raised:
            call()
        self.assertEqual((str(raised.exception), raised.exception.param), (words, param))

    def test_a_curved_face_is_refused(self):
        import build123d as bd
        from cad.build123d.standard_features import clearance_hole

        rod = bd.Cylinder(10, 20)
        side = rod.faces().filter_by(bd.GeomType.CYLINDER)[0]
        self.refused(lambda: clearance_hole(rod, side), "Clearance Hole: the face must be flat.", "face")

    def test_holes_that_would_overlap_on_their_circle_are_refused(self):
        from cad.build123d.standard_features import bolt_circle

        body, top = plate()
        self.refused(lambda: bolt_circle(body, top, diameter=10, count=12, hole=4),
                     "Bolt Circle: 12 holes of 4 overlap on a 10 circle.", "hole")

    def test_slots_off_the_face_are_refused(self):
        from cad.build123d.standard_features import vent_slots

        body, top = plate()
        self.refused(lambda: vent_slots(body, top, count=20, pitch=6), "Vent Slots: the slots run off the face.", "count")
        self.refused(lambda: vent_slots(body, top, length=3, width=3), "Vent Slots: a slot must be longer than it is wide.", "width")

    def test_a_hole_off_the_part_is_refused(self):
        from cad.build123d.standard_features import clearance_hole

        body, top = plate()
        self.refused(lambda: clearance_hole(body, top, x=200), "Clearance Hole: the hole misses the part.", "x")

    def test_a_size_outside_the_table_is_refused_by_its_choices(self):
        from cad.build123d import FeatureError
        from cad.build123d.standard_features import clearance_hole

        body, top = plate()
        with self.assertRaises(FeatureError):
            clearance_hole(body, top, size="M7")


PLATE = {
    "plate.py": """
        from build123d import Box
        from cad import model


        @model
        def plate():
            body = Box(80, 60, 6)
            return body
    """,
}

TOP = {"selector": "f6", "type": "plane", "center": [0.0, 0.0, 3.0], "size": W * D}


class FromTheCustomMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cad.edit import service as edit

        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def setUp(self):
        self.root = project(PLATE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.file = str(self.root / "plate.step")

    def test_every_project_offers_the_standard_features_after_its_own(self):
        state = self.service.state(self.file)
        self.assertTrue(state["ok"], state.get("error"))
        self.assertEqual([(each["name"], each["module"], each["file"], each.get("standard")) for each in state["customFeatures"]],
                         [("Bolt Circle", "cad.build123d.standard_features", None, True),
                          ("Vent Slots", "cad.build123d.standard_features", None, True),
                          ("Clearance Hole", "cad.build123d.standard_features", None, True),
                          ("Heat-set Insert Boss", "cad.build123d.standard_features", None, True)])

    def test_a_standard_feature_is_imported_from_its_module_and_reads_as_one_row(self):
        state = self.service.state(self.file)
        reply = self.service.change({"file": self.file, "files": state["files"], "command": {
            "command": "custom", "function": "cad.build123d.standard_features.clearance_hole",
            "inputs": {"size": "M4", "fit": "fine", "x": "12"}, "picks": {"face": [TOP]}}})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (self.root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("from cad.build123d.standard_features import clearance_hole\n", text)
        line = next(each.strip() for each in text.splitlines() if "clearance_hole(" in each and "import" not in each)
        self.assertTrue(line.startswith("body = clearance_hole(body, face=body.faces()"), line)
        self.assertIn("size='M4'", line)
        self.assertIn("fit='fine'", line)
        self.assertIn("x=12", line)
        row = next(row for row in reply["rows"] if (row.get("custom") or {}).get("name") == "Clearance Hole")
        self.assertEqual(row["custom"]["function"], "cad.build123d.standard_features.clearance_hole")
