"""Adaptive clearing on the block's stepped pocket: floors reached, walls and the island kept, helix entries, and the
engagement capped: the material cut per millimetre of path stays near the stepover, far from a full-width slot."""

from __future__ import annotations

import unittest

import numpy as np
import shapely

from cadgen._internal.cam.ir import ARC_CCW, ARC_CW, PLUNGE, RAPID
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.job_errors import CamJobError
from cadgen._internal.cam.part import read_part
from cadgen._internal.cam.run import parse_operations, plan_setups
from cadgen._internal.cam.stock import build_stock
from tests.python.support.cam_fixtures import BLOCK, block_step, class_directory, floor_ref, mill_job


class Adaptive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        cls.step = block_step(class_directory(cls))
        cls.features = cam.features(cls.step)
        cls.part = read_part(cls.step)
        cls.lower = floor_ref(cls.features, BLOCK["lower"]["floor_z"])
        cls.upper = floor_ref(cls.features, BLOCK["upper"]["floor_z"])
        cls.result = cls.plan([{"op": "adaptive", "tool": "T1", "faces": [cls.lower]}])

    @classmethod
    def plan(cls, operations):
        parsed = parse_job(mill_job(operations))
        stock = build_stock(parsed.stock, cls.part)
        setups, ops, _ = plan_setups(parsed, parse_operations(parsed), cls.part, stock)
        return setups[0], ops

    def test_it_reaches_both_floors_and_keeps_off_the_walls_and_the_island(self):
        plan, ops = self.result
        samples = plan.toolpath.sample(0.005, max_step_mm=0.25)
        cutting = samples.kind != RAPID
        cutting[0] = False
        points = samples.points[cutting]
        # WCS zero is the stock top, a millimetre over the part: the lower floor at -15, the upper at -9.
        self.assertAlmostEqual(-15.0, float(points[:, 2].min()), places=6)
        self.assertTrue(np.any(np.isclose(points[:, 2], -9.0) & (points[:, 0] > 18.0)), "the upper step is cleared")
        for z in np.unique(np.round(points[:, 2], 4)):
            group = points[np.isclose(points[:, 2], z, atol=1e-4)]
            material = plan.sections.at(float(z) + 1e-3)
            if material.is_empty:
                continue
            distance = shapely.distance(shapely.points(group[:, :2]), material)
            self.assertGreaterEqual(float(distance.min()), 3.0 - 0.02, f"at z {z}")
        meta = ops[0].meta
        self.assertEqual(meta["levels"], meta["entries"]["helix"])
        self.assertNotIn("plunges", meta)
        self.assertFalse(np.any(plan.toolpath.moves["kind"] == PLUNGE))
        self.assertEqual(0.9, meta["stepover_mm"])                     # 0.15 of the 6 mm tool
        self.assertEqual(6.0, meta["stepdown_mm"])                     # twice aluminium's half diameter
        self.assertEqual(8, len(meta["unreachable"]))
        self.assertEqual("lite", ops[0].operation.status)
        self.assertTrue(ops[0].operation.limits)

    def test_the_engagement_stays_near_the_stepover(self):
        plan, ops = self.result
        r, stepover = 3.0, ops[0].meta["stepover_mm"]
        moves = plan.toolpath.moves
        samples = plan.toolpath.sample(0.01, max_step_mm=0.5)
        # The deepest level, the lower step's own: cut from its helix outward.
        level = np.isclose(samples.points[:, 2], -15.0)
        arcs = level & np.isin(samples.kind, (ARC_CW, ARC_CCW))
        feeds = level & ~np.isin(samples.kind, (ARC_CW, ARC_CCW, RAPID))
        cleared = shapely.LineString(samples.points[arcs][:, :2]).buffer(r)
        rates = []
        points = samples.points
        index = np.nonzero(feeds)[0]
        # Walk the level's feed moves in runs of consecutive samples, about 3 mm of path each.
        runs = np.split(index, np.nonzero(np.diff(index) > 1)[0] + 1)
        for run in runs:
            for chunk in np.array_split(run, max(1, len(run) // 6)):
                if len(chunk) < 2:
                    continue
                path = shapely.LineString(points[np.r_[chunk[0] - 1, chunk]][:, :2])
                if path.length < 0.5:
                    continue
                swept = path.buffer(r)
                rates.append(swept.difference(cleared).area / path.length)
                cleared = cleared.union(swept)
        rates = np.asarray(rates)
        self.assertGreater(len(rates), 20)
        # A full-width slot would cut 6 mm² per mm. A ring of radius p growing outward by the stepover s cuts
        # s (p + r) / p per mm of its centre line: about 2 s on the first ring round the helix, nearer s further out.
        self.assertLess(float(rates.max()), 2.2 * stepover)
        self.assertLess(float(np.median(rates)), 1.4 * stepover)
        self.assertGreater(len(moves), 100)

    def test_a_stepover_past_half_the_diameter_is_refused(self):
        with self.assertRaises(CamJobError) as caught:
            parse_operations(parse_job(mill_job([{"op": "adaptive", "tool": "T1", "faces": [self.lower],
                                                  "stepover": 0.6}])))
        self.assertIn("keep it at most half the tool's diameter (3 mm)", str(caught.exception))
        with self.assertRaises(CamJobError) as caught:
            parse_operations(parse_job(mill_job([{"op": "adaptive", "tool": "T1"}])))
        self.assertIn("needs its floor faces", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
