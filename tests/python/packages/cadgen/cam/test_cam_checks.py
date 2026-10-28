"""The checks cadgen stands behind, on paths written by hand (no FreeCAD): a face the tool cannot see is refused
before planning, and a move into the part, a rapid through the stock or an operation that cuts nothing after."""

from __future__ import annotations

import unittest

from tests.python.support.cam_fixtures import BRIDGE, block_step, bridge_step, class_directory, mill_job

from cadgen._internal.cam import checks
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.toolpath import Moves


def moves(points, rapid, op=0):
    import numpy as np

    return Moves(points=np.asarray(points, dtype=float), rapid=np.asarray(rapid, dtype=bool),
                 op=np.full(len(points), op, dtype=np.int64), t=np.arange(len(points), dtype=float))


class Reach(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cadgen import cam
        from cadgen._internal.cam.part import read_part

        directory = class_directory(cls)
        cls.part = read_part(bridge_step(directory))
        cls.floors = {f["kind"]: f["ref"] for f in cam.features(cls.part.document).floors}

    def reach(self, op_raw, tool="T1"):
        job = parse_job(mill_job([op_raw]))
        (op,) = job.setups[0].operations
        faces = [self.part.face(ref) for ref in op.faces]
        top = float(self.part.bbox[1][2]) + 1.0
        return checks.reach(op, faces, {}, (self.part.vertices, self.part.triangles), self.part.face_of_triangle,
                            job.tools[tool], top, min(f.center_mm[2] for f in faces))

    def test_a_floor_partly_under_a_bridge_is_refused_with_how_much(self):
        (found,) = self.reach({"op": "pocket", "tool": "T1", "faces": [self.floors["floor"]]})
        self.assertEqual(("reach", "error", "unreachable"), (found["check"], found["severity"], found["type"]))
        import re

        share = BRIDGE["bar"] / BRIDGE["pocket"][0]                 # the bar is 8 mm of the pocket's 30
        said = float(re.search(r"(\d+)% of", found["summary"]).group(1)) / 100
        self.assertAlmostEqual(share, said, delta=0.03)
        x = found["items"][0]["at"][0]
        self.assertLessEqual(abs(x), BRIDGE["bar"] / 2)          # it points under the bar

    def test_the_top_is_in_reach_and_the_underside_does_not_face_the_tool(self):
        self.assertEqual([], self.reach({"op": "face", "tool": "T1", "faces": [self.floors["top"]]}))
        (found,) = self.reach({"op": "pocket", "tool": "T1", "faces": [self.floors["underside"]]})
        self.assertEqual("not_facing", found["type"])

    def test_a_cut_deeper_than_the_flutes(self):
        job = mill_job([{"op": "pocket", "tool": "T1", "faces": [self.floors["floor"]]}],
                       tools=[{"id": "T1", "type": "flat", "diameter_mm": 6, "flute_length_mm": 8}])
        (op,) = parse_job(job).setups[0].operations
        found = checks.reach(op, [], {}, (self.part.vertices, self.part.triangles), self.part.face_of_triangle,
                             parse_job(job).tools["T1"], 21.0, 8.0)
        self.assertEqual(["too_deep"], [f["type"] for f in found])
        self.assertIn("13.00 mm below the stock top, past T1's 8 mm of flutes", found[0]["summary"])


class Moves_(unittest.TestCase):
    """On the block (80 x 60 x 25, a pocket floor at z 17), in its own coordinates: the tool comes down -Z."""

    @classmethod
    def setUpClass(cls):
        import numpy as np

        from cadgen._internal.cam.part import read_part

        cls.part = read_part(block_step(class_directory(cls)))
        cls.mesh = (cls.part.vertices, cls.part.triangles)
        cls.job = parse_job(mill_job([{"op": "face", "tool": "T1"}, {"op": "drill", "tool": "T2",
                                                                     "faces": ["face 1"]}]))
        cls.stock = (np.array([-42.0, -32.0, 0.0]), np.array([42.0, 32.0, 26.0]))

    def check(self, path, op=0):
        operation = self.job.setups[0].operations[op]
        return checks.check_moves("top", path, [operation], self.job.tools, self.mesh, *self.stock, self.job.machine)

    def types(self, found):
        return sorted(f["type"] for f in found)

    def test_a_pass_over_the_top_and_down_into_the_pocket_is_clean(self):
        path = moves([[0, 0, 40], [0, 0, 28], [0, 0, 25.0], [30, 0, 25.0], [0, 0, 25], [0, 0, 17.0], [-15, 0, 17.0],
                      [-15, 0, 40]], [True, True, False, False, False, False, False, True])
        self.assertEqual([], self.check(path))

    def test_a_move_through_the_wall_is_a_gouge_where_it_happens(self):
        # Along y = -15, clear of the island at (14, 0), out through the pocket's wall at x = 25.
        path = moves([[0, -15, 40], [0, -15, 17.0], [30, -15, 17.0], [30, -15, 40]], [True, False, False, True])
        (found,) = self.check(path)
        self.assertEqual("gouge", found["type"])
        self.assertIn("8.00 mm into the part", found["summary"])          # 25 - 17 at the wall
        self.assertGreaterEqual(found["items"][0]["at"][0], 25.0 - 3.0)   # where the tool first meets the wall

    def test_a_drill_the_size_of_its_hole_down_the_hole_is_clean(self):
        x, y = -33.0, -23.0
        drill = self.job.tools["T2"]
        self.assertEqual(5.0, drill.diameter_mm)
        path = moves([[x, y, 40], [x, y, 28], [x, y, -1 - drill.tip_length_mm], [x, y, 40]], [True, True, False, True],
                     op=1)
        self.assertEqual([], self.check(path, op=1))
        off = moves([[x + 1, y, 40], [x + 1, y, 28], [x + 1, y, 10], [x + 1, y, 40]], [True, True, False, True], op=1)
        self.assertEqual(["gouge"], self.types(self.check(off, op=1)))

    def test_a_rapid_into_uncut_stock_but_not_a_retract_or_a_link_inside_a_cleared_pass(self):
        retract = moves([[0, 0, 40], [0, 0, 28], [0, 0, 25.0], [0, 0, 40]], [True, True, False, True])
        self.assertEqual([], self.check(retract))
        plunge = moves([[0, 0, 40], [0, 0, 20.0], [5, 0, 20.0]], [True, True, False])
        self.assertEqual(["rapid_into_stock"], self.types(self.check(plunge)))
        # Cut a pass at z 25.5 along y = 0 from x 0 to -15, then link back along it at that depth: already cut.
        link = moves([[0, 0, 40], [0, 0, 26.5], [0, 0, 25.5], [-15, 0, 25.5], [0, 0, 25.5], [0, 0, 40]],
                     [True, True, False, False, True, True])
        self.assertEqual([], self.check(link))
        # The same link 5 mm to the side runs through stock no pass has cut.
        aside = moves([[0, 0, 40], [0, 0, 26.5], [0, 0, 25.5], [-15, 0, 25.5], [-15, 5, 25.5], [-15, 5, 40]],
                      [True, True, False, False, True, True])
        (found,) = self.check(aside)
        self.assertEqual("rapid_into_stock", found["type"])
        self.assertIn("0.50 mm into stock not yet cut", found["summary"])

    def test_an_operation_with_no_cut_and_a_setup_past_the_travel(self):
        self.assertEqual(["empty_operation"], self.types(self.check(moves([[0, 0, 40], [5, 0, 40]], [True, True]))))
        wide = moves([[-200, 0, 40], [200, 0, 40], [200, 0, 26.0], [210, 0, 26.0]], [True, True, True, False])
        self.assertEqual(["travel"], self.types(self.check(wide)))


if __name__ == "__main__":
    unittest.main()
