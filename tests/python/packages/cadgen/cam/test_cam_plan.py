"""``cadgen cam plan`` end to end, through the FreeCAD installed here: the block planned, posted and drawn; a face
under a bridge refused with no G-code; a setup turned over; GRBL's program split by tool; a failure that leaves the
earlier files as they were."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from tests.python.support.cam_fixtures import (BLOCK, block_step, bridge_step, class_directory, floor_ref, glb_cam,
                                               mill_job, needs_freecad, quiet, read_glb)


#: Tools long enough to profile the block's 26 mm, stock top to bottom.
LONG_FLUTES = [{"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3, "flute_length_mm": 30, "stickout_mm": 40},
               {"id": "T2", "type": "drill", "diameter_mm": 5, "flute_length_mm": 50, "stickout_mm": 60}]


def plan(step: Path, job: dict, **options):
    from cadgen import cam

    with quiet():
        return cam.plan(step, job=job, **options)


def z_words(text: str) -> list[float]:
    return [float(z) for z in re.findall(r"\bZ(-?\d+(?:\.\d+)?)", text)]


@needs_freecad
class Block(unittest.TestCase):
    """Face, pocket (around the island), adaptive (the lower step), profile and drill: one LinuxCNC program."""

    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        cls.step = block_step(class_directory(cls))
        features = cam.features(cls.step)
        holes = [hole["faces"][0] for hole in features.holes]
        cls.job = mill_job(tools=LONG_FLUTES, operations=[
            {"op": "face", "tool": "T1"},
            {"op": "pocket", "tool": "T1", "faces": [floor_ref(features, 17.0)]},
            {"op": "adaptive", "tool": "T1", "faces": [floor_ref(features, 11.0)]},
            {"op": "profile", "tool": "T1", "through_mm": 0.5},
            {"op": "drill", "tool": "T2", "faces": holes},
        ])
        cls.result = plan(cls.step, cls.job)
        cls.cam = glb_cam(cls.result.glb) if cls.result.glb else None

    def test_it_is_ready_to_cut_and_posts_one_program(self):
        self.assertTrue(self.result.ok, self.result.findings)
        self.assertEqual("ready", self.result.verdict["status"], self.result.findings)
        (post,) = self.result.posts
        self.assertEqual(("top", "linuxcnc", None), (post["setup"], post["post"], post["tool"]))
        self.assertEqual("block.top.ngc", Path(post["file"]).name)
        self.assertTrue(self.cam["planner"].startswith("freecad 1."))

    def test_the_program_is_in_work_coordinates_and_cuts_at_real_feeds(self):
        text = Path(self.result.posts[0]["file"]).read_text(encoding="utf-8")
        depth = BLOCK["size"][2]
        zs = z_words(text)
        self.assertAlmostEqual(-(depth + 1.0 + 0.5), min(z for z in zs if z > -(depth + 3)), places=3)  # profile
        self.assertGreater(max(zs), 0.0)                                       # clearance above the stock top
        self.assertIn("G54", text)
        speeds = {float(s) for s in re.findall(r"\bS(\d+(?:\.\d+)?)", text)}
        self.assertTrue(speeds and all(s > 1000 for s in speeds), speeds)
        feeds = {float(f) for f in re.findall(r"\bF(\d+(?:\.\d+)?)", text)}
        self.assertTrue(feeds and min(feeds) > 10, feeds)                      # never FreeCAD's 0 mm/min
        self.assertIn("T2", text)                                             # the tool change to the drill

    def test_each_operation_is_drawn_and_timed_in_order(self):
        ops = self.cam["setups"][0]["operations"]
        self.assertEqual(["face", "pocket", "adaptive", "profile", "drill"], [op["op"] for op in ops])
        times = [(op["t0"], op["t1"]) for op in ops]
        self.assertTrue(all(t0 < t1 for t0, t1 in times), times)
        self.assertTrue(all(a[1] <= b[0] + 1e-6 for a, b in zip(times, times[1:])), times)
        document, blob = read_glb(self.result.glb)
        kinds = {node["extras"].get("kind") for node in document["nodes"] if "extras" in node}
        self.assertTrue({"part", "stock", "feed", "rapid"} <= kinds, kinds)

    def test_the_drill_goes_through_by_its_point_and_the_break_through(self):
        drill = self.job["tools"][1]
        import math

        tip = drill["diameter_mm"] / 2 / math.tan(math.radians(59))
        expected = -(BLOCK["size"][2] + 1.0) - 1.0 - tip
        text = Path(self.result.posts[0]["file"]).read_text(encoding="utf-8")
        self.assertIn(round(expected, 3), [round(z, 3) for z in z_words(text)])


@needs_freecad
class Bridge(unittest.TestCase):
    """A floor a quarter under a bar: refused before FreeCAD plans it, and the earlier program goes."""

    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        cls.directory = class_directory(cls)
        cls.step = bridge_step(cls.directory)
        cls.floors = {f["kind"]: f["ref"] for f in cam.features(cls.step).floors}

    def test_a_ready_plan_then_one_that_is_not_leaves_no_program(self):
        first = plan(self.step, mill_job([{"op": "face", "tool": "T1"}]))
        self.assertEqual("ready", first.verdict["status"], first.findings)
        program = Path(first.posts[0]["file"])
        self.assertTrue(program.is_file())
        second = plan(self.step, mill_job([{"op": "face", "tool": "T1"},
                                           {"op": "pocket", "tool": "T1", "faces": [self.floors["floor"]]}]))
        self.assertTrue(second.ok)
        self.assertEqual("fix", second.verdict["status"])
        self.assertEqual((), second.posts)
        self.assertFalse(program.exists())                 # no "ready" program beside a plan that is not
        (error,) = [f for f in second.findings if f["severity"] == "error"]
        self.assertEqual(("reach", "unreachable"), (error["check"], error["type"]))
        cam = glb_cam(second.glb)
        self.assertEqual("fix", cam["verdict"]["status"])
        self.assertIn("G-code not written", cam["verdict"]["gcode"])

    def test_the_bottom_turned_over_is_faced_from_its_own_side(self):
        result = plan(self.step, mill_job([], setups=[
            {"id": "bottom", "orientation": "-Z", "operations": [{"op": "face", "tool": "T1"}]}]))
        self.assertEqual("ready", result.verdict["status"], result.findings)
        (op,) = result.operations
        self.assertEqual([self.floors["bottom"]], op["faces"])
        setup = glb_cam(result.glb)["setups"][0]
        self.assertEqual([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]], setup["matrix"])
        self.assertEqual(0.0, setup["origin_part_mm"][2])  # the work zero is the stock's face toward the tool


@needs_freecad
class Grbl(unittest.TestCase):
    def test_a_setup_with_two_tools_posts_one_file_per_tool(self):
        from cadgen import cam

        directory = class_directory(type(self))
        step = block_step(directory)
        holes = [hole["faces"][0] for hole in cam.features(step).holes]
        job = mill_job([{"op": "face", "tool": "T1"}, {"op": "drill", "tool": "T2", "faces": holes}],
                       machine={"kind": "router", "post": "grbl"})
        result = plan(step, job)
        self.assertEqual("ready", result.verdict["status"], result.findings)
        self.assertEqual([("block.top.1-T1.nc", "T1"), ("block.top.2-T2.nc", "T2")],
                         [(Path(p["file"]).name, p["tool"]) for p in result.posts])
        first, second = (Path(p["file"]).read_text(encoding="utf-8") for p in result.posts)
        self.assertNotIn("G81", re.sub(r"\(.*?\)", "", second))   # GRBL has no drilling cycle: written out as moves


class Refused(unittest.TestCase):
    def test_no_freecad_is_refused_with_how_to_install_it_and_writes_nothing(self):
        from cadgen._internal.cam import freecad

        directory = class_directory(type(self))
        step = block_step(directory)
        with mock.patch.dict(os.environ, {freecad.FREECAD_ENV: str(directory / "no-freecad")}):
            result = plan(step, mill_job([{"op": "face", "tool": "T1"}]))
        self.assertFalse(result.ok)
        (found,) = result.findings
        self.assertEqual(("job", "freecad"), (found["check"], found["type"]))
        self.assertIn("install FreeCAD 1.1 or newer", found["summary"])
        self.assertEqual(["block.step"], sorted(p.name for p in directory.iterdir()))


@needs_freecad
class FailedWrite(unittest.TestCase):
    def test_a_write_that_fails_leaves_the_earlier_files_byte_for_byte(self):
        directory = class_directory(type(self))
        step = block_step(directory)
        job = mill_job([{"op": "face", "tool": "T1"}], tools=LONG_FLUTES)
        first = plan(step, job)
        self.assertEqual("ready", first.verdict["status"], first.findings)
        before = {path.name: path.read_bytes() for path in directory.iterdir()}
        job["setups"][0]["operations"].append({"op": "profile", "tool": "T1"})
        real = __import__("cadgen._internal.cam.run", fromlist=["replace_atomic"]).replace_atomic
        calls = []

        def second_fails(tmp, final):
            calls.append(final)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            real(tmp, final)

        with mock.patch("cadgen._internal.cam.run.replace_atomic", second_fails):
            result = plan(step, job)
        self.assertFalse(result.ok)
        self.assertIn("No space left on device", result.findings[0]["summary"])
        # The GLB went into place, the program failed, and the earlier GLB was put back.
        self.assertEqual([".glb", ".ngc", ".glb"], [path.suffix for path in calls])
        after = {path.name: path.read_bytes() for path in directory.iterdir()}
        self.assertEqual(before, after)                    # every earlier file back, no temporary left


if __name__ == "__main__":
    unittest.main()
