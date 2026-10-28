"""A job with no setups planned from the part's features (``auto.py``): each feature cut by the operation a machinist
would pick, named for what it cuts, with tools proposed or taken from the job; what the top cannot reach left with a
warning; the completed job written beside the result, and planned again unchanged."""

from __future__ import annotations

import json
import unittest

from tests.python.support.cam_fixtures import class_directory, hole_block_step, needs_freecad, plate_step, quiet

MACHINE = {"post": "linuxcnc", "max_rpm": 24000}


def plan(step, job, **options):
    from cadgen import cam

    with quiet():
        return cam.plan(step, job=job, **options)


def names(result) -> list[str]:
    return [op["name"] for op in result.operations]


def not_cut(result) -> list[str]:
    return [f["summary"] for f in result.findings if f["type"] == "not_planned"]


class ToolChoice(unittest.TestCase):
    def test_the_cuts_the_shape_limits_choose_first_and_roomy_ones_take_their_tools(self):
        from cadgen._internal.cam.auto import _choose, _Cut

        cuts = [_Cut("face", 0, 12.0, roomy=True), _Cut("profile", 2, 13.3, roomy=True), _Cut("pocket", 1, 8.0),
                _Cut("profile", 3, 4.4)]
        sizes, used, unfit = _choose(cuts, None)
        self.assertEqual({0: 8.0, 1: 8.0, 2: 8.0, 3: 4.0}, sizes, "an 8 mm cuts all it fits; the slot takes a 4")
        self.assertEqual(([8.0, 4.0], []), (used, unfit))
        sizes, used, unfit = _choose(cuts, {10.0: 30.0})
        self.assertEqual(({0: 10.0, 1: 10.0}, [10.0]), (sizes, used))
        self.assertEqual([8.0, 4.4], [cut.largest for cut in unfit], "nothing the job has fits the pocket or the slot")


@needs_freecad
class Plate(unittest.TestCase):
    """A Ø22.2 bore, a 5.5 mm slot, a pocket and a blind Ø6 hole, from machine, material and stock alone."""

    @classmethod
    def setUpClass(cls):
        cls.directory = class_directory(cls)
        cls.step = plate_step(cls.directory)
        cls.job = {"machine": MACHINE, "material": "aluminum-6061", "stock": {"margin_mm": [2, 2, 1]}}
        cls.result = plan(cls.step, cls.job)

    def test_every_feature_is_cut_by_name_with_the_fewest_tools_proposed(self):
        self.assertEqual("ready", self.result.verdict["status"], self.result.findings)
        self.assertEqual(["Face the top", "Pocket 4 mm deep", "Bore Ø22.2", "Slot 5.5 x 17.5",
                          "Drill 1 hole Ø6 x 4 deep", "Cut the outline free"], names(self.result))
        self.assertEqual(["T1", "T1", "T1", "T2", "T3", "T1"], [op["tool"] for op in self.result.operations])
        self.assertEqual("Bore Ø22.2 (profile) with T1 8 mm flat", self.result.operations[2]["summary"].split(",")[0])
        (tools,) = [e for e in self.result.assumed if e["key"] == "tools"]
        self.assertEqual("8 mm flat, 4 mm flat, 6 mm drill", tools["value"])
        self.assertFalse([e for e in self.result.assumed if e["key"].startswith("T")], "one line for the tools")

    def test_the_completed_job_is_written_and_plans_again_unchanged(self):
        path = self.result.job_file
        self.assertEqual(self.directory / "plate.cam.json", path)
        text = path.read_text(encoding="utf-8")
        written = json.loads(text)
        self.assertEqual(names(self.result), [op["name"] for op in written["setups"][0]["operations"]])
        self.assertEqual((3, 16.0), (written["tools"][0]["flutes"], written["tools"][0]["flute_length_mm"]),
                         "a stub cutter, two diameters, three flutes in aluminium")
        again = plan(self.step, str(path), out_dir=self.directory / "again")
        self.assertEqual("ready", again.verdict["status"], again.findings)
        self.assertEqual([op["summary"] for op in self.result.operations], [op["summary"] for op in again.operations])
        self.assertIsNone(again.job_file)
        self.assertEqual(text, path.read_text(encoding="utf-8"))

    def test_the_jobs_own_tools_are_used_and_a_feature_none_fits_is_left_with_a_warning(self):
        tools = [{"id": "T1", "type": "flat", "diameter_mm": 6},
                 {"id": "T3", "type": "flat", "diameter_mm": 3, "flute_length_mm": 12},
                 {"id": "T2", "type": "drill", "diameter_mm": 6}]
        result = plan(self.step, dict(self.job, tools=tools), out_dir=self.directory / "own")
        self.assertEqual("ready", result.verdict["status"], result.findings)
        self.assertEqual(["T1", "T1", "T1", "T3", "T2", "T1"], [op["tool"] for op in result.operations])
        result = plan(self.step, dict(self.job, tools=[{"id": "T1", "type": "flat", "diameter_mm": 10}]),
                      out_dir=self.directory / "big")
        self.assertEqual(["Face the top", "Bore Ø22.2", "Cut the outline free"], names(result))
        self.assertEqual(["not cut: pocket 4 mm deep, which needs a flat end mill of 4.8 mm or less with 5 mm of "
                          "flutes",
                          "not cut: slot 5.5 x 17.5, which needs a flat end mill of 4.4 mm or less with 9.5 mm of "
                          "flutes"], sorted(not_cut(result)))

    def test_a_tool_whose_flutes_do_not_reach_the_cut_is_passed_over(self):
        tools = [{"id": "T1", "type": "flat", "diameter_mm": 6},
                 {"id": "T3", "type": "flat", "diameter_mm": 3, "flute_length_mm": 9},
                 {"id": "T2", "type": "drill", "diameter_mm": 6}]
        result = plan(self.step, dict(self.job, tools=tools), out_dir=self.directory / "short")
        self.assertEqual("ready", result.verdict["status"], result.findings)
        self.assertNotIn("Slot 5.5 x 17.5", names(result))
        self.assertIn("with 9.5 mm of flutes", " ".join(not_cut(result)))

    def test_a_tool_the_machine_slows_is_one_warning(self):
        result = plan(self.step, dict(self.job, machine={"post": "linuxcnc", "max_rpm": 5000}),
                      out_dir=self.directory / "slow")
        clamped = [f for f in result.findings if f["type"] == "clamped"]
        self.assertEqual(["T1", "T2", "T3"], sorted(f["summary"].split(" ")[0] for f in clamped))
        (first,) = [f for f in clamped if f["summary"].startswith("T1")]
        self.assertEqual(4, len(first["items"]), "face, pocket, bore and outline: one warning")


@needs_freecad
class HoleBlock(unittest.TestCase):
    def test_a_counterbore_is_profiled_and_what_the_top_cannot_reach_is_left_with_a_warning(self):
        step = hole_block_step(class_directory(type(self)))
        result = plan(step, {"machine": MACHINE, "material": "aluminum-6061", "stock": {"margin_mm": [2, 2, 1]}})
        self.assertEqual("ready", result.verdict["status"], result.findings)
        self.assertIn("Counterbore Ø9 x 4 deep", names(result))
        left = not_cut(result)
        self.assertTrue(any("Ø8 hole the top does not reach" in words for words in left), left)
        self.assertTrue(any("Ø5 hole the top does not reach" in words for words in left), left)
        self.assertIn("not cut: the floor at Z 4, under the part: it needs a setup from another side", left)
