"""The drill operation on the drill plate: holes hit at their exact centres, depths from the hole's kind and the
tool's point, every cycle expanded the way a controller runs it, shortest order, R planes, and its teaching errors
and findings."""

from __future__ import annotations

import math
import unittest

import numpy as np

from cadgen._internal.cam.ir import DWELL, FEED, PLUNGE, RAPID
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.job_errors import CamJobError
from cadgen._internal.cam.part import read_part
from cadgen._internal.cam.run import parse_operations, plan_setups
from cadgen._internal.cam.stock import build_stock
from tests.python.support.cam_fixtures import class_directory, quiet
from tests.python.support.cam_fixtures_drilling import PLATE, drill_job, drill_plate_step, hole_faces

#: WCS z = part z - 13 (stock-top-center, 1 mm of stock over the 12 mm plate).
TOP = -1.0
BOTTOM = -13.0


def tip(diameter: float, angle: float = 118.0) -> float:
    return diameter / 2 / math.tan(math.radians(angle / 2))


class DrillPlate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        with quiet():
            cls.step = drill_plate_step(class_directory(cls))
            cls.features = cam.features(cls.step)
            cls.part = read_part(cls.step)
        cls.f5 = hole_faces(cls.features, 5.0)
        cls.f6 = hole_faces(cls.features, 6.0)
        cls.f8 = hole_faces(cls.features, 8.0)
        cls.f68 = hole_faces(cls.features, 6.8)
        cls.f4 = hole_faces(cls.features, 4.0)
        cls.side = hole_faces(cls.features, 4.0, axis="+X")

    def plan(self, operations, **job):
        parsed = parse_job(drill_job(operations, **job))
        stock = build_stock(parsed.stock, self.part)
        setups, ops, _ = plan_setups(parsed, parse_operations(parsed), self.part, stock)
        return setups, ops

    def one(self, op, **job):
        setups, ops = self.plan([op], **job)
        path = setups[0].toolpath
        rng = next(o for o in path.ops if o.index == 0)
        return path, rng, ops[0]

    @staticmethod
    def cycles(path, rng):
        return [e for e in path.events if e.kind == "cycle" and rng.start <= e.at < rng.end]

    @staticmethod
    def bottoms(path, rng):
        """(x, y, lowest z) of every plunge run's end inside the op."""
        moves = path.moves[rng.start:rng.end]
        out = {}
        for m in moves[moves["kind"] == PLUNGE]:
            key = (round(float(m["x"]), 6), round(float(m["y"]), 6))
            out[key] = min(out.get(key, math.inf), float(m["z"]))
        return out

    # --- which holes, where, how deep ------------------------------------------------------------------------

    def test_all_holes_from_the_top_are_hit_at_their_exact_centres(self):
        path, rng, op = self.one({"op": "drill", "tool": "T4", "holes": "all"})
        found = sorted(self.bottoms(path, rng))
        expected = sorted([*PLATE["through5"], *PLATE["blind6"]["centers"], PLATE["blind8"]["center"],
                           PLATE["through68"], *PLATE["pocket"]["holes"]])
        self.assertEqual(len(expected), len(found))
        for (x, y), (ex, ey) in zip(found, expected):
            self.assertAlmostEqual(ex, x, places=6)
            self.assertAlmostEqual(ey, y, places=6)
        self.assertIn("1 matching hole along another axis", op.meta["note"])
        # Each moves only along Z under its R plane: no sideways feed anywhere.
        moves = path.moves[rng.start:rng.end]
        cuts = moves[(moves["kind"] == PLUNGE) | (moves["kind"] == FEED)]
        starts = path.positions()[rng.start:rng.end][(moves["kind"] == PLUNGE) | (moves["kind"] == FEED)]
        self.assertTrue(np.allclose(starts[:, :2], np.column_stack([cuts["x"], cuts["y"]])))

    def test_a_through_hole_goes_past_its_exit_by_the_breakthrough_plus_the_point(self):
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "faces": self.f5[:1]})
        (z,) = self.bottoms(path, rng).values()
        self.assertAlmostEqual(BOTTOM - 1.0 - tip(5.0), z, places=6)
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "faces": self.f5[:1], "breakthrough_mm": 2.5})
        (z,) = self.bottoms(path, rng).values()
        self.assertAlmostEqual(BOTTOM - 2.5 - tip(5.0), z, places=6)

    def test_a_blind_hole_with_a_drawn_point_drills_to_its_shoulder_else_to_its_tip(self):
        floor6 = TOP - PLATE["blind6"]["depth"]
        path, rng, _ = self.one({"op": "drill", "tool": "T2", "faces": self.f6})
        self.assertTrue(np.allclose(list(self.bottoms(path, rng).values()), [floor6 - tip(6.0)] * 2))
        path, rng, _ = self.one({"op": "drill", "tool": "T2", "faces": self.f6, "depth_to": "tip"})
        self.assertTrue(np.allclose(list(self.bottoms(path, rng).values()), floor6))
        floor8 = TOP - PLATE["blind8"]["depth"]
        path, rng, _ = self.one({"op": "drill", "tool": "T6", "faces": self.f8, "cycle": "bore"})
        self.assertAlmostEqual(floor8, list(self.bottoms(path, rng).values())[0], places=6)

    def test_a_tap_stops_a_pitch_short_of_a_blind_floor_and_leads_through_a_through_hole(self):
        path, rng, _ = self.one({"op": "drill", "tool": "T3", "faces": self.f6[:1]})
        self.assertAlmostEqual(TOP - 8.0 + 1.0, list(self.bottoms(path, rng).values())[0], places=6)
        path, rng, _ = self.one({"op": "drill", "tool": "T3", "faces": self.f5[:1]})
        self.assertAlmostEqual(BOTTOM - 1.0 - 3 * 1.0, list(self.bottoms(path, rng).values())[0], places=6)

    def test_a_spot_makes_a_cone_as_wide_as_the_hole(self):
        path, rng, op = self.one({"op": "drill", "tool": "T4", "faces": self.f5[:1] + self.f4[:1]})
        bottoms = self.bottoms(path, rng)
        self.assertAlmostEqual(TOP - 2.5, bottoms[PLATE["through5"][0]], places=6)        # 90°: depth = radius
        self.assertAlmostEqual(PLATE["pocket"]["floor_z"] - 13 - 2.0, bottoms[PLATE["pocket"]["holes"][0]],
                               places=6)
        self.assertEqual("spot", self.cycles(path, rng)[0].data["cycle"])

    def test_points_take_their_top_from_the_part_and_their_depth_from_the_job(self):
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "points": [[0, -15], [12, 0]], "depth_mm": 3})
        bottoms = self.bottoms(path, rng)
        self.assertAlmostEqual(TOP - 3.0, bottoms[(0.0, -15.0)], places=6)
        self.assertAlmostEqual(PLATE["pocket"]["floor_z"] - 13 - 3.0, bottoms[(12.0, 0.0)], places=6)
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "points": [[0, -15]], "depth_mm": 3, "top_z": -2,
                                 "depth_to": "shoulder"})
        self.assertAlmostEqual(-5.0 - tip(5.0), list(self.bottoms(path, rng).values())[0], places=6)

    def test_a_setup_from_the_side_drills_the_side_hole(self):
        setups = [{"id": "side", "orientation": "+X", "origin": "stock-top-center",
                   "operations": [{"op": "drill", "tool": "T7", "holes": "all"}]}]
        setups_out, ops = self.plan([], setups=setups)
        path = setups_out[0].toolpath
        rng = path.ops[0]
        (point,) = [setups_out[0].wcs.from_wcs([[k[0], k[1], z]])[0] for k, z in self.bottoms(path, rng).items()]
        side = PLATE["side"]
        self.assertAlmostEqual(side["y"], point[1], places=6)
        self.assertAlmostEqual(side["z"], point[2], places=6)
        self.assertAlmostEqual(30.0 - side["depth"], point[0], places=6)          # tip on the flat floor
        self.assertIn("10 matching holes along another axis", ops[0].meta["note"])

    # --- cycles --------------------------------------------------------------------------------------------

    def test_peck_comes_back_to_r_between_pecks_and_chipbreak_backs_off_a_little(self):
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "faces": self.f5[:1], "cycle": "peck", "peck_mm": 4})
        (cycle,) = self.cycles(path, rng)
        r_plane, bottom = cycle.data["r_plane"], cycle.data["z_bottom"]
        self.assertEqual(("peck", 4.0), (cycle.data["cycle"], cycle.data["peck_mm"]))
        moves = path.moves[cycle.at:cycle.data["end"]]
        depths = [float(m["z"]) for m in moves if m["kind"] == PLUNGE]
        self.assertEqual(depths, sorted(depths, reverse=True))
        self.assertTrue(np.allclose(np.diff([r_plane] + depths)[:-1], -4.0))
        self.assertAlmostEqual(bottom, depths[-1], places=5)
        rapids = [float(m["z"]) for m in moves if m["kind"] == RAPID]
        self.assertEqual(len(depths) - 1, sum(1 for z in rapids if abs(z - r_plane) < 1e-9) - 1)
        path, rng, _ = self.one({"op": "drill", "tool": "T1", "faces": self.f5[:1], "cycle": "chipbreak",
                                 "peck_mm": 3, "retract_mm": 0.3})
        (cycle,) = self.cycles(path, rng)
        moves = path.moves[cycle.at:cycle.data["end"]]
        rises = []
        for k in range(1, len(moves)):
            if moves[k]["kind"] == RAPID and moves[k - 1]["kind"] == PLUNGE and moves[k]["z"] > moves[k - 1]["z"] \
                    and moves[k]["z"] < cycle.data["r_plane"] - 1e-9:
                rises.append(float(moves[k]["z"] - moves[k - 1]["z"]))
        self.assertTrue(rises and np.allclose(rises, 0.3), rises)
        self.assertEqual((3.0, 0.3), (cycle.data["peck_mm"], cycle.data["retract_mm"]))

    def test_a_deep_hole_pecks_by_default(self):
        _, _, op = self.one({"op": "drill", "tool": "T7", "faces": self.f4[:1]})       # 8 deep, 2 diameters
        self.assertEqual("drill", op.meta["cycle"])
        _, _, op = self.one({"op": "drill", "tool": "T1", "faces": self.f5[:1]})       # 12 deep, 2.4 diameters
        self.assertEqual("drill", op.meta["cycle"])
        _, _, op = self.one({"op": "drill", "tool": "T7", "faces": self.f5[:1]})       # 12 deep: 3 diameters
        self.assertEqual("peck", op.meta["cycle"])

    def test_dwell_and_bore_modes(self):
        path, rng, _ = self.one({"op": "drill", "tool": "T2", "faces": self.f6[:1], "cycle": "dwell", "dwell_s": 0.8})
        (cycle,) = self.cycles(path, rng)
        self.assertEqual(("spot", 0.8), (cycle.data["cycle"], cycle.data["dwell_s"]))        # G82
        moves = path.moves[cycle.at:cycle.data["end"]]
        self.assertEqual([0.8], [float(m["p"]) for m in moves if m["kind"] == DWELL])
        for mode, ir_cycle, out_kind in (("feed", "bore", FEED), ("dwell", "bore_dwell", FEED),
                                         ("stop", "bore_stop", RAPID), ("fine", "fine_bore", RAPID)):
            with self.subTest(mode=mode):
                path, rng, _ = self.one({"op": "drill", "tool": "T6", "faces": self.f8, "cycle": "bore",
                                         "bore_mode": mode})
                (cycle,) = self.cycles(path, rng)
                self.assertEqual(ir_cycle, cycle.data["cycle"])
                moves = path.moves[cycle.at:cycle.data["end"]]
                k = int(np.argmin(moves["z"]))
                after = [m for m in moves[k + 1:] if m["kind"] != DWELL][0]
                self.assertEqual(out_kind, int(after["kind"]))
                spindle = [e.data.get("dir") for e in path.events
                           if e.kind == "spindle" and cycle.at < e.at <= cycle.data["end"]]
                self.assertEqual(["off", "cw"] if mode in ("stop", "fine") else [], spindle)
                if mode == "fine":
                    self.assertEqual(0.1, cycle.data["shift_mm"])
                if mode == "dwell":
                    self.assertEqual(0.5, cycle.data["dwell_s"])

    def test_a_tap_feeds_at_rpm_times_pitch_and_reverses_at_the_bottom(self):
        path, rng, op = self.one({"op": "drill", "tool": "T3", "faces": self.f5[:2]})
        (cycle,) = self.cycles(path, rng)
        self.assertEqual(op.feeds.rpm * 1.0, cycle.data["feed"])
        self.assertEqual(1.0, cycle.data["pitch_mm"])
        self.assertTrue(op.meta["no_gouge_check"])
        dirs = [e.data["dir"] for e in path.events if e.kind == "spindle" and rng.start <= e.at < rng.end]
        self.assertEqual(["cw", "ccw", "cw", "ccw", "cw"], dirs)
        moves = path.moves[cycle.at:cycle.data["end"]]
        cutting = moves[(moves["kind"] == PLUNGE) | (moves["kind"] == FEED)]
        self.assertTrue(np.allclose(cutting["feed"], op.feeds.rpm * 1.0))

    def test_a_left_hand_tap_runs_the_spindle_backwards_in(self):
        tools = [{"id": "T3", "type": "tap", "diameter_mm": 6, "pitch_mm": 1, "hand": "left"},
                 {"id": "T1", "type": "drill", "diameter_mm": 5}]
        setups, ops = self.plan([{"op": "drill", "tool": "T3", "faces": self.f5[:1]},
                                 {"op": "drill", "tool": "T1", "faces": self.f5[:1]}], tools=tools)
        path = setups[0].toolpath
        dirs = [e.data["dir"] for e in path.events if e.kind == "spindle"]
        self.assertEqual(["ccw", "cw", "ccw", "cw"], dirs)            # in, reverse out, restored; the drill cw
        (cycle,) = [e for e in path.events if e.kind == "cycle" and e.data["cycle"] == "tap"]
        self.assertTrue(cycle.data["left_hand"])
        self.assertEqual("M6x1 LH tap", ops[0].tool.plain)

    def test_holes_at_r_return_to_r_inside_a_pocket_and_to_the_initial_level_across_the_top(self):
        path, rng, op = self.one({"op": "drill", "tool": "T7", "holes": {"diameter_mm": 4}})
        (cycle,) = self.cycles(path, rng)
        self.assertEqual("r", cycle.data["retract"])
        self.assertAlmostEqual(PLATE["pocket"]["floor_z"] - 13 + 2.0, cycle.data["r_plane"])
        self.assertAlmostEqual(2.0, cycle.data["initial_z"])
        path, rng, op = self.one({"op": "drill", "tool": "T1", "faces": self.f5})
        (cycle,) = self.cycles(path, rng)
        self.assertEqual(("initial", 2.0, 2.0), (cycle.data["retract"], cycle.data["r_plane"], cycle.data["initial_z"]))
        # Pocket holes and top holes are separate cycles: different R planes.
        path, rng, op = self.one({"op": "drill", "tool": "T7", "faces": self.f4 + self.f5, "cycle": "drill"})
        groups = self.cycles(path, rng)
        self.assertGreaterEqual(len(groups), 2)
        for event in groups:
            self.assertEqual(1, len({(h[2]) for h in event.data["holes"]}))
        # Between cycles the tool climbs to the initial level before it moves across.
        for event in groups[1:]:
            before = path.positions()[event.at]
            self.assertAlmostEqual(2.0, before[2])

    def test_order_is_shorter_than_the_order_given(self):
        from cadgen._internal.cam.drilling import path_length

        faces = [self.f5[0], self.f5[3], self.f6[0], self.f5[1], self.f68[0], self.f5[2], self.f6[1]]
        lengths = {}
        for order in ("given", "shortest"):
            path, rng, op = self.one({"op": "drill", "tool": "T4", "faces": faces, "order": order})
            lengths[order] = path_length((0, 0), [h["at"] for h in op.meta["holes"]])
        self.assertLess(lengths["shortest"], lengths["given"] - 1.0)

    # --- findings ------------------------------------------------------------------------------------------

    def test_a_drill_off_the_hole_size_is_a_warning_and_a_tap_checks_its_thread(self):
        _, _, op = self.one({"op": "drill", "tool": "T1", "faces": self.f68})
        (found,) = op.meta["findings"]
        self.assertEqual(("drill", "warning", "hole_size"), (found["check"], found["severity"], found["type"]))
        self.assertIn("smaller than the Ø6.8", found["summary"])
        _, _, op = self.one({"op": "drill", "tool": "T2", "faces": self.f5[:1]})
        self.assertIn("oversize", op.meta["findings"][0]["summary"])
        _, _, op = self.one({"op": "drill", "tool": "T1", "faces": self.f5})
        self.assertNotIn("findings", op.meta)
        _, _, op = self.one({"op": "drill", "tool": "T3", "faces": self.f68})
        (found,) = op.meta["findings"]
        self.assertEqual("tap_thread", found["type"])
        self.assertIn("M8x1.25", found["summary"])
        tools = [{"id": "T3", "type": "tap", "diameter_mm": 6, "pitch_mm": 1.25}]
        _, _, op = self.one({"op": "drill", "tool": "T3", "faces": self.f5[:1]}, tools=tools)
        self.assertIn("pitch of 1 or 0.75", op.meta["findings"][0]["summary"])

    # --- teaching errors -----------------------------------------------------------------------------------

    def test_a_hole_along_another_axis_names_the_setup_that_reaches_it(self):
        with self.assertRaises(CamJobError) as caught:
            self.plan([{"op": "drill", "tool": "T7", "faces": self.side}])
        self.assertIn("along +X", str(caught.exception))
        self.assertIn("\"orientation\": \"+X\"", str(caught.exception))
        setups = [{"id": "top", "orientation": "+Z", "origin": "stock-top-center",
                   "operations": [{"op": "drill", "tool": "T7", "faces": self.side}]},
                  {"id": "right", "orientation": "+X", "origin": "stock-top-center",
                   "operations": [{"op": "drill", "tool": "T7", "holes": "all"}]}]
        with self.assertRaises(CamJobError) as caught:
            self.plan([], setups=setups)
        self.assertIn("drill it in setup 'right'", str(caught.exception))

    def test_faces_that_are_not_holes_and_filters_that_find_none_teach(self):
        plane = next(f["ref"] for f in self.features.floors if f["kind"] == "top")
        with self.assertRaises(CamJobError) as caught:
            self.plan([{"op": "drill", "tool": "T1", "faces": [plane]}])
        self.assertIn("not a hole wall", str(caught.exception))
        with self.assertRaises(CamJobError) as caught:
            self.plan([{"op": "drill", "tool": "T1", "holes": {"diameter_mm": 3}}])
        self.assertIn("no Ø3 ±0.05 hole", str(caught.exception))
        self.assertIn("Ø6.8 along +Z", str(caught.exception))

    def test_malformed_drill_ops_are_refused_before_planning(self):
        cases = {
            "names its holes one way": {"op": "drill", "tool": "T1", "holes": "all", "points": [[0, 0]]},
            "needs \"depth_mm\"": {"op": "drill", "tool": "T1", "points": [[0, 0]]},
            "a tap cycle cuts with a tap": {"op": "drill", "tool": "T1", "holes": "all", "cycle": "tap"},
            "peck_mm is for the peck and chipbreak": {"op": "drill", "tool": "T1", "holes": "all", "cycle": "drill",
                                                      "peck_mm": 2},
            "set \"speed\" (rpm) instead": {"op": "drill", "tool": "T3", "holes": "all", "feed": 300},
            "shift_mm is for": {"op": "drill", "tool": "T6", "holes": "all", "shift_mm": 0.2},
            "top_z is for holes given as points": {"op": "drill", "tool": "T1", "holes": "all", "top_z": 0},
            "unknown key 'pecks'": {"op": "drill", "tool": "T1", "holes": "all", "pecks": 2},
            "\"all\" or": {"op": "drill", "tool": "T1", "holes": "some"},
            "use one of drill, dwell, peck": {"op": "drill", "tool": "T1", "holes": "all", "cycle": "boring"},
        }
        for words, op in cases.items():
            with self.subTest(words=words):
                with self.assertRaises(CamJobError) as caught:
                    parse_operations(parse_job(drill_job([op])))
                self.assertIn(words, str(caught.exception))
        with self.assertRaises(CamJobError) as caught:
            parse_job(drill_job([], tools=[{"id": "T3", "type": "tap", "diameter_mm": 6, "pitch_mm": 1,
                                            "hand": "sinister"}]))
        self.assertIn("use one of right, left", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
