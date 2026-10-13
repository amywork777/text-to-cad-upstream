"""Engine guards from review: plausible-wrong plans the engine must refuse, flag or get right (law 10), and keys it
must not accept and ignore (law 9). Each test is one fixed bug, on a small part built in a temporary directory."""

from __future__ import annotations

import unittest
from pathlib import Path

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



class StaleOutputs(unittest.TestCase):
    """A plan never leaves the last run's GLB or G-code standing beside a refusal, a crash or a smaller job."""

    @classmethod
    def setUpClass(cls):
        from tests.python.support.cam_fixtures import plate_step

        cls.root = class_directory(cls)
        cls.step = plate_step(cls.root)

    def setUp(self):
        import shutil
        import tempfile

        self.out = Path(tempfile.mkdtemp(prefix="out-", dir=self.root))
        self.addCleanup(shutil.rmtree, self.out, True)

    def plan(self, job):
        from cadgen import cam

        with quiet():
            return cam.plan(self.step, job=job, out_dir=self.out)

    def names(self) -> list[str]:
        return sorted(path.name for path in self.out.iterdir())

    def test_a_refused_job_leaves_nothing_of_the_last_run(self):
        self.assertTrue(self.plan(mill_job([{"op": "face", "tool": "T1"}])).ok)
        self.assertEqual(["plate.cam.glb", "plate.top.nc"], self.names())
        bad = mill_job([{"op": "face", "tool": "T1"}])
        bad["tolerence_mm"] = 0.01
        self.assertFalse(self.plan(bad).ok)
        self.assertEqual([], self.names())

    def test_a_crash_leaves_nothing_of_the_last_run(self):
        from unittest import mock

        self.assertTrue(self.plan(mill_job([{"op": "face", "tool": "T1"}])).ok)
        with mock.patch("cadgen._internal.cam.part.read_part", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.plan(mill_job([{"op": "face", "tool": "T1"}]))
        self.assertEqual([], self.names())

    def test_a_setup_dropped_since_loses_its_file_and_only_cadgen_files_are_swept(self):
        both = mill_job([], setups=[{"id": "top", "orientation": "+Z", "operations": [{"op": "face", "tool": "T1"}]},
                                    {"id": "bottom", "orientation": "-Z", "operations": [{"op": "face", "tool": "T1"}]}])
        self.assertTrue(self.plan(both).ok)
        self.assertEqual(["plate.bottom.nc", "plate.cam.glb", "plate.top.nc"], self.names())
        (self.out / "plate.old.nc").write_text("(plate.step - setup old Top, 1 of 1)\n(Generated by cadgen 0.5 cam)\n")
        (self.out / "plate.notes.nc").write_text("(my own notes)\n")
        (self.out / "other.top.nc").write_text("(other.step - setup top Top, 1 of 1)\n(Generated by cadgen)\n")
        self.assertTrue(self.plan(mill_job([{"op": "face", "tool": "T1"}])).ok)
        self.assertEqual(["other.top.nc", "plate.cam.glb", "plate.notes.nc", "plate.top.nc"], self.names())

    def test_a_failed_rename_midway_leaves_none_of_the_new_set(self):
        import os
        from unittest import mock

        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(src, dst)

        with mock.patch("cadgen._internal.cam.run.os.replace", side_effect=flaky):
            with self.assertRaises(OSError):
                self.plan(mill_job([{"op": "face", "tool": "T1"}]))
        self.assertEqual(2, len(calls))
        self.assertEqual([], self.names())

    def test_a_post_that_splits_by_tool_writes_one_file_per_tool(self):
        from unittest import mock

        from cadgen._internal.cam import posts
        from tests.python.support.cam_fixtures import read_glb

        real_get = posts.get_post

        class Split:
            split_by_tool = True

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def render_tool_files(self, program):
                text = self._inner.render(program)
                return [("T1", "(T1)\n" + text), ("T3", "(T3)\n" + text)]

        tools = [{"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3, "flute_length_mm": 20, "stickout_mm": 30},
                 {"id": "T3", "type": "flat", "diameter_mm": 10, "flutes": 3, "flute_length_mm": 20, "stickout_mm": 30}]
        # A stub over a post with a tool changer, so the same job also posts as one file without it.
        job = mill_job([{"op": "face", "tool": "T3"}, {"op": "face", "tool": "T1"}], tools=tools,
                       machine={"kind": "mill", "post": "linuxcnc", "max_rpm": 24000})
        with mock.patch.object(posts, "get_post", lambda *a, **k: Split(real_get(*a, **k))):
            result = self.plan(job)
        self.assertTrue(result.ok)
        self.assertEqual(["plate.cam.glb", "plate.top.T1.ngc", "plate.top.T3.ngc"], self.names())
        self.assertEqual([("top", "T1", "plate.top.T1.ngc"), ("top", "T3", "plate.top.T3.ngc")],
                         [(p["setup"], p["tool"], Path(p["file"]).name) for p in result.posts])
        cam = read_glb(result.glb)[0]["scenes"][0]["extras"]["cam"]
        self.assertEqual(["T1", "T3"], [p["tool"] for p in cam["posts"]])
        self.assertEqual(["plate.top.T1.ngc", "plate.top.T3.ngc"], cam["setups"][0]["posts"])
        # Planned again with a post that does not split: the per-tool files go with the last run.
        self.assertTrue(self.plan(job).ok)
        self.assertEqual(["plate.cam.glb", "plate.top.ngc"], self.names())


class StockGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.python.support.cam_fixtures import plate_step

        cls.directory = class_directory(cls)
        cls.step = plate_step(cls.directory)

    def plan(self, document, job, name: str):
        from cadgen import cam

        with quiet():
            return cam.plan(document, job=job, out_dir=self.directory / name)

    def test_a_box_size_bigger_than_the_part_is_taken_and_a_smaller_one_refused(self):
        bigger = self.plan(self.step, mill_job([{"op": "face", "tool": "T1"}],
                                               stock={"kind": "box", "size_mm": [70, 50, 8]}), "bigger")
        self.assertTrue(bigger.ok)
        self.assertTrue(bigger.verdict)
        smaller = self.plan(self.step, mill_job([{"op": "face", "tool": "T1"}],
                                                stock={"kind": "box", "size_mm": [50, 50, 8]}), "smaller")
        self.assertFalse(smaller.ok)
        self.assertIn("smaller than the part", smaller.findings[0]["summary"])


if __name__ == "__main__":
    unittest.main()
