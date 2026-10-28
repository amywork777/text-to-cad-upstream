"""Edit mode's modeling commands (``cadgen.edit.commands``): Fillet, Chamfer, Hole, Shell, Mirror
and Pattern, each written as one line of build123d after the statement that makes the part's
body, read back by the tracer as a feature of the history, and put back by Undo; and Delete on a
feature of the history (``cadgen.edit.deleting``), its lines taken out.

They drive the edit service end to end, as the viewer's server does, on small parts in fresh
folders. A selection is what the viewer sends: each face's or edge's selector with the geometry
the viewer read of it (its kind, centre, and length or area). The selectors' numbers here need not
be the STEP's: the geometry decides, as it does when a part rebuilt with its faces in another
order. Builds are not started.
"""

from __future__ import annotations

import math
import shutil
import tempfile
import textwrap
import os
import unittest
from pathlib import Path

from cadgen.edit import service as edit


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

# A 20 x 10 x 4 block centred on the origin, returned outright, its sizes named in another file
# and build123d imported by name.
BLOCK = {
    "sizes.py": """
        WIDTH = 20
        DEPTH = 10
        HEIGHT = 4
    """,
    "block.py": """
        from build123d import Box
        from cadgen import model
        from sizes import WIDTH, DEPTH, HEIGHT

        @model
        def block():
            return Box(WIDTH, DEPTH, HEIGHT)
    """,
}

# An inch plate with a hole in it, held in a name, build123d reached through `bd`.
PLATE = {
    "plate.py": """
        import build123d as bd
        from cadgen import model

        INCH = 25.4
        LENGTH = 2.00
        WIDTH = 1.00
        THICKNESS = .25


        @model
        def plate():
            plate = bd.Box(LENGTH*INCH, WIDTH*INCH, THICKNESS*INCH)
            plate -= bd.Pos(.5*INCH, 0, 0) * bd.Cylinder(.1*INCH, THICKNESS*INCH)
            plate.label = "plate"
            return plate
    """,
}


# A tray as an agent writes one: a base, filleted in place, a cavity cut from it into a new name,
# pads joined in a loop, and a hole.
TRAY = {
    "tray.py": """
        from build123d import Axis, Box, Cylinder, Pos, fillet
        from cadgen import model


        @model
        def tray():
            outer = Box(40, 20, 10)
            outer = fillet(outer.edges().filter_by(Axis.Z), radius=2)
            cavity = Pos(0, 0, 2) * Box(36, 16, 10)
            tray = outer - cavity
            for x in (-10, 10):
                pad = Pos(x, 0, -6) * Box(6, 6, 2)
                tray = tray + pad
            tray -= Cylinder(1, 20)
            return tray
    """,
}


# A plate with a post joined to it, the post's top rounded before the join, then a hole through
# the plate: the fillet is the post's child feature.
POSTED = {
    "posted.py": """
        from build123d import Axis, Box, Cylinder, Pos, fillet
        from cadgen import model


        @model
        def posted():
            plate = Box(40, 20, 4)
            post = Pos(0, 0, 5) * Cylinder(4, 6)
            post = fillet(post.edges().group_by(Axis.Z)[-1], radius=1)
            plate = plate + post
            plate -= Pos(12, 0, 0) * Cylinder(1, 10)
            return plate
    """,
}


# An assembly of two parts, each a model of its own beside its STEP, as a project lays them out.
ASSEMBLY = {
    "parts/base.py": """
        from build123d import Box
        from cadgen import model


        @model
        def base():
            return Box(20, 10, 4)
    """,
    "parts/pin.py": """
        from build123d import Cylinder, Pos
        from cadgen import model


        @model
        def pin():
            return Pos(0, 0, 5) * Cylinder(2, 6)
    """,
    "assemblies/stack.py": """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "parts"))
        from build123d import Compound
        from cadgen import model
        from base import base
        from pin import pin


        @model
        def stack():
            return Compound(children=[base().shape, pin().shape], label="stack")
    """,
}


def project(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cadgen-edit-commands-"))
    (root / ".git").mkdir()
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return root


def edge(selector: str, center: tuple[float, float, float], length: float, kind: str = "line") -> dict:
    return {"selector": selector, "type": kind, "center": list(center), "size": length}


def face(selector: str, center: tuple[float, float, float], area: float) -> dict:
    return {"selector": selector, "type": "plane", "center": list(center), "size": area}


# The block's top edges and top face, as the viewer reads them.
BLOCK_TOP_EDGES = [edge("e1", (0, -5, 2), 20), edge("e2", (0, 5, 2), 20), edge("e3", (-10, 0, 2), 10), edge("e4", (10, 0, 2), 10)]
BLOCK_TOP = [face("f1", (0, 0, 2), 200)]


class Commands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def open(self, files: dict[str, str], step: str):
        root = project(files)
        self.addCleanup(shutil.rmtree, root, True)
        file = str(root / step)
        state = self.service.state(file)
        self.assertTrue(state["ok"], state.get("error"))
        return root, file, state

    def command(self, file: str, state: dict, command: str, selection=(), inputs=None, feature=None):
        spec = {"command": command, "selection": list(selection), "inputs": inputs or {}}
        if feature:
            spec["feature"] = feature
        return self.service.change({"file": file, "command": spec, "files": state["files"]})


class BlockCommands(Commands):
    def test_a_fillet_on_selected_edges_is_one_line_read_back_as_a_fillet(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        # The returned body is held in a name, the fillet written after it, and the names it uses
        # imported; the edges are written by where they are (the top ones), not their numbers.
        self.assertIn("from build123d import Box, Axis, fillet\n", text)
        self.assertIn("    part = Box(WIDTH, DEPTH, HEIGHT)\n"
                      "    part = fillet(part.edges().group_by(Axis.Z)[-1], radius=1)\n"
                      "    return part\n", text)
        fillet = reply["rows"][-1]
        self.assertEqual((fillet["kind"], fillet["key"]), ("Fillet", reply["change"]["row"]))
        self.assertEqual([(each["label"], each["display"], each["unit"]) for each in fillet["inputs"]], [("Radius", "1", "mm")])
        self.assertEqual((reply["change"]["feature"], reply["change"]["what"]), ("Fillet", "4 edges"))

    def test_undo_puts_the_file_back_and_redo_writes_it_again(self):
        root, file, state = self.open(BLOCK, "block.step")
        script = root / "block.py"
        before = script.read_bytes()
        made = self.command(file, state, "chamfer", BLOCK_TOP_EDGES[:1], {"distance": ".5"})
        self.assertTrue(made["ok"], made.get("error"))
        after = script.read_bytes()
        undone = self.service.change({"file": file, "splice": made["change"]["undo"], "files": made["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_bytes(), before)
        self.assertEqual([row["kind"] for row in undone["rows"]], ["Box"])
        redone = self.service.change({"file": file, "splice": made["change"]["redo"], "files": undone["files"]})
        self.assertTrue(redone["ok"], redone.get("error"))
        self.assertEqual(script.read_bytes(), after)

    def test_every_edge_named_by_its_number_alone(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "chamfer", [{"selector": f"e{n}"} for n in range(1, 13)], {"distance": "0.5"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    part = chamfer(part.edges(), length=0.5)\n", (root / "block.py").read_text(encoding="utf-8"))
        self.assertEqual(reply["rows"][-1]["inputs"][0]["label"], "Distance")

    def test_a_pick_named_as_the_viewer_names_it_is_found_by_its_number(self):
        # The engine's ref by number (`block/edge 3`), as the xbf viewer names a pick, reads as 0.7's `e3` did.
        from cadgen.edit import commands

        self.assertEqual([commands.selector_ordinal(each) for each in
                          ("block/face 12", "face 12", "hand/finger.2/edge 3", "f12", "o1.2.e3", "block", "f:block.box1.2", "surf12", "f0")],
                         [("face", 12), ("face", 12), ("edge", 3), ("face", 12), ("edge", 3), (None, None), (None, None), (None, None),
                          (None, None)])
        # A mate's pick says which part it is on by its owner's label, as the viewer names it, or by 0.7's place.
        from types import SimpleNamespace

        from cadgen.edit import mates

        children = [SimpleNamespace(label="base"), SimpleNamespace(label="pin"), SimpleNamespace(label="pin")]
        self.assertEqual([mates._occurrence(each, children) for each in ("pin/face 3", "pin.2/face 3", "base/edge 1", "o1.2.f3", "lid/face 1", "face 3")],
                         [1, 2, 0, 1, None, None])
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "chamfer", [{"selector": f"block/edge {n}"} for n in range(1, 13)], {"distance": "0.5"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    part = chamfer(part.edges(), length=0.5)\n", (root / "block.py").read_text(encoding="utf-8"))

    def test_a_face_selected_for_a_chamfer_stands_for_its_edges(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "chamfer", BLOCK_TOP, {"distance": "0.5"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)\n", (root / "block.py").read_text(encoding="utf-8"))
        self.assertEqual(reply["change"]["what"], "4 edges")

    def test_a_line_that_does_not_run_is_not_written(self):
        root, file, state = self.open(BLOCK, "block.step")
        before = (root / "block.py").read_bytes()
        refused = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "6"})
        self.assertFalse(refused["ok"])
        self.assertIn("smaller radius", refused["error"])
        self.assertEqual((root / "block.py").read_bytes(), before)

    def test_a_selection_that_is_not_on_the_part_is_refused(self):
        root, file, state = self.open(BLOCK, "block.step")
        refused = self.command(file, state, "fillet", [edge("e3", (100, 100, 100), 10)], {"radius": "1"})
        self.assertFalse(refused["ok"])
        self.assertIn("not on the part", refused["error"])
        self.assertNotIn("fillet", (root / "block.py").read_text(encoding="utf-8"))

    def test_a_hole_goes_where_it_is_set_on_the_face(self):
        root, file, state = self.open(BLOCK, "block.step")
        off = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "x": "30"})
        self.assertFalse(off["ok"])
        self.assertIn("off that face", off["error"])
        reply = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "x": "5"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part -= Pos(5, 0) * Plane(part.faces().sort_by(Axis.Z)[-1]) * Cylinder(2/2, 3, "
                      "align=(Align.CENTER, Align.CENTER, Align.MAX))", (root / "block.py").read_text(encoding="utf-8"))
        hole = reply["rows"][-1]
        self.assertEqual(hole["kind"], "Hole")
        self.assertEqual([(each["label"], each["display"]) for each in hole["inputs"]], [("Diameter", "2"), ("Depth", "3"), ("X", "5")])

    def test_one_hole_feature_drills_its_hole_at_each_place_and_reopens_with_them(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "x": "5", "more": [{"x": "-5"}, {"x": "0", "y": "2.5"}]})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part -= [Pos(*at) * Plane(part.faces().sort_by(Axis.Z)[-1]) * Cylinder(2/2, 3, align=(Align.CENTER, Align.CENTER, Align.MAX)) "
                      "for at in ((5, 0), (-5, 0), (0, 2.5))]\n", (root / "block.py").read_text(encoding="utf-8"))
        hole = next(feature for feature in reply["features"] if feature["kind"] == "Hole")
        self.assertEqual({key: hole["edit"]["values"].get(key) for key in ("x", "y", "more")},
                         {"x": "5", "y": "0", "more": [{"x": "-5", "y": "0"}, {"x": "0", "y": "2.5"}]})
        # Three holes out of the 20 by 10 by 4 block, each 2 across and 3 deep.
        mass = self.service.change({"file": file, "mass": {}, "files": reply["files"]})["mass"]
        self.assertAlmostEqual(mass["volume"], 20 * 10 * 4 - 3 * math.pi * 3, places=3)
        # One taken out with Edit Feature: the line drills two.
        edited = self.service.change({"file": file, "files": reply["files"], "command": {
            "command": "hole", "inputs": {"diameter": "2", "depth": "3", "x": "5", "y": "0", "more": [{"x": "-5", "y": "0"}]},
            "replace": {"row": hole["key"]}}})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertIn("for at in ((5, 0), (-5, 0))]\n", (root / "block.py").read_text(encoding="utf-8"))

    def test_a_tapped_hole_of_a_standard_size_keeps_its_callout_beside_its_line_and_reopens_as_tapped(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2.5", "depth": "3", "type": "tapped", "callout": "M3x0.5 tapped hole"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part -= Plane(part.faces().sort_by(Axis.Z)[-1]) * Cylinder(2.5/2, 3, align=(Align.CENTER, Align.CENTER, Align.MAX))"
                      "  # M3x0.5 tapped hole\n", (root / "block.py").read_text(encoding="utf-8"))
        feature = next(feature for feature in reply["features"] if feature["kind"] == "Hole")
        self.assertEqual({key: feature["edit"]["values"][key] for key in ("type", "diameter", "callout")},
                         {"type": "tapped", "diameter": "2.5", "callout": "M3x0.5 tapped hole"})
        # Opened again and made a plain hole of its own size, its callout goes.
        spec = {"command": "hole", "inputs": {"diameter": "2", "depth": "3"}, "replace": {"row": feature["key"]}}
        edited = self.service.change({"file": file, "command": spec, "files": reply["files"]})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertNotIn("#", (root / "block.py").read_text(encoding="utf-8"))
        odd = self.command(file, edited, "hole", BLOCK_TOP, {"diameter": "2", "callout": "M3\nimport os"})
        self.assertFalse(odd["ok"])

    def test_a_counterbored_hole_is_its_hole_and_its_counterbore_in_one_line(self):
        root, file, state = self.open(BLOCK, "block.step")
        narrow = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "type": "counterbore",
                                                              "cbore_diameter": "1.5", "cbore_depth": "1"})
        self.assertFalse(narrow["ok"])
        self.assertIn("wider than its hole", narrow["error"])
        reply = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "type": "counterbore",
                                                             "cbore_diameter": "4", "cbore_depth": "1"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part -= Plane(part.faces().sort_by(Axis.Z)[-1]) * (Cylinder(2/2, 3, align=(Align.CENTER, Align.CENTER, Align.MAX)) "
                      "+ Cylinder(4/2, 1, align=(Align.CENTER, Align.CENTER, Align.MAX)))", (root / "block.py").read_text(encoding="utf-8"))
        hole = reply["rows"][-1]
        self.assertEqual(hole["kind"], "Hole")
        self.assertEqual([(each["label"], each["display"]) for each in hole["inputs"]],
                         [("Diameter", "2"), ("Depth", "3"), ("Counterbore Diameter", "4"), ("Counterbore Depth", "1")])
        feature = next(feature for feature in reply["features"] if feature["kind"] == "Hole")
        self.assertEqual({key: feature["edit"]["values"][key] for key in ("type", "cbore_diameter", "cbore_depth")},
                         {"type": "counterbore", "cbore_diameter": "4", "cbore_depth": "1"})

    def test_a_countersunk_hole_cones_down_to_the_hole_at_its_angle(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "type": "countersink",
                                                             "csk_diameter": "4", "csk_angle": "90"})
        self.assertTrue(reply["ok"], reply.get("error"))
        # At 90 degrees the cone falls one unit for each unit it narrows.
        self.assertIn("+ Cone(2/2, 4/2, 1, align=(Align.CENTER, Align.CENTER, Align.MAX)))", (root / "block.py").read_text(encoding="utf-8"))
        hole = reply["rows"][-1]
        self.assertEqual([(each["label"], each["display"]) for each in hole["inputs"]],
                         [("Diameter", "2"), ("Depth", "3"), ("Countersink Diameter", "4")])
        feature = next(feature for feature in reply["features"] if feature["kind"] == "Hole")
        self.assertEqual({key: feature["edit"]["values"][key] for key in ("type", "csk_diameter", "csk_angle")},
                         {"type": "countersink", "csk_diameter": "4", "csk_angle": "90"})

    def test_a_shell_opens_the_selected_face(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "shell", BLOCK_TOP, {"thickness": "1"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part = offset(part, amount=-1, openings=part.faces().group_by(Axis.Z)[-1])",
                      (root / "block.py").read_text(encoding="utf-8"))
        shell = reply["rows"][-1]
        self.assertEqual((shell["kind"], [(each["label"], each["display"]) for each in shell["inputs"]]), ("Shell", [("Thickness", "1")]))

    def test_shell_outward_grows_the_wall_outside_and_reopens_so(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.command(file, state, "shell", BLOCK_TOP, {"thickness": "1", "outward": True})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("part = offset(part, amount=1, openings=part.faces().group_by(Axis.Z)[-1])",
                      (root / "block.py").read_text(encoding="utf-8"))
        feature = next(f for f in reply["features"] if f["kind"] == "Shell")
        self.assertEqual(feature["edit"]["values"], {"thickness": "1", "outward": True})


# A block with its top back edge chamfered: a face slanted at 45 degrees, its normal along (0, 1, 1).
WEDGE = {
    "wedge.py": """
        from build123d import Axis, Box, chamfer
        from cadgen import model


        @model
        def wedge():
            part = Box(20, 20, 10)
            part = chamfer(part.edges().group_by(Axis.Z)[-1].sort_by(Axis.Y)[-1], length=6)
            return part
    """,
}
# The chamfer's face as the viewer reads it: from y = 4 at the top to y = 10 at z = -1.
SLANTED = {"selector": "f99", "type": "plane", "center": [0.0, 7.0, 2.0], "size": 20 * 6 * 2 ** 0.5}


class SlantedHoles(Commands):
    def test_a_hole_on_a_slanted_face_goes_where_it_is_put_on_the_face(self):
        root, file, state = self.open(WEDGE, "wedge.step")
        # Along X and down the slope, as a click there gives them, to the places the panel shows.
        reply = self.command(file, state, "hole", [SLANTED], {"diameter": "3", "x": "5", "y": "1.004", "z": "-1"})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "wedge.py").read_text(encoding="utf-8")
        # Put back on the face's plane: a hair off it would leave the hole off the face.
        self.assertIn("part -= Pos(5, 1.002, -1.002) * Plane(part.faces()", text)
        hole = next(feature for feature in reply["features"] if feature["kind"] == "Hole")
        self.assertEqual(hole["edit"]["values"]["type"], "simple")
        self.assertEqual({axis: hole["edit"]["values"][axis] for axis in "xyz"}, {"x": "5", "y": "1.002", "z": "-1.002"})
        refused = self.command(file, reply, "hole", [SLANTED], {"diameter": "3", "z": "3"})
        self.assertFalse(refused["ok"])
        self.assertIn("2.12 mm off the face", refused["error"])


# The tray's rim as the viewer reads it: its top face, 40 by 20 rounded at the corners round the
# 36 by 16 opening, its center over the opening.
RIM = face("f3", (0, 0, 5), 208 + 4 * math.pi)


class RimHoles(Commands):
    def test_mass_properties_give_the_moments_of_inertia_about_the_center_of_mass(self):
        root, file, state = self.open(BLOCK, "block.step")
        mass = self.service.change({"file": file, "mass": {}, "files": state["files"]})["mass"]
        # A 20 x 10 x 4 block, per unit density: Lxx = V(10² + 4²)/12, Lyy = V(20² + 4²)/12, Lzz = V(20² + 10²)/12.
        volume = 20 * 10 * 4
        self.assertEqual([round(mass["inertia"][axis][axis], 3) for axis in range(3)],
                         [round(volume * (100 + 16) / 12, 3), round(volume * (400 + 16) / 12, 3), round(volume * (400 + 100) / 12, 3)])
        self.assertEqual([round(value, 3) for value in mass["principal"]["moments"]], sorted(round(mass["inertia"][axis][axis], 3) for axis in range(3)))
        self.assertEqual([[abs(round(part, 6)) for part in axis] for axis in mass["principal"]["axes"]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def test_a_hole_in_a_rim_goes_where_the_rim_is_clicked(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        before = script.read_bytes()
        weighed = self.service.change({"file": file, "mass": {}, "files": state["files"]})["mass"]
        # Not clicked, the hole would sit at the rim's center, over the opening.
        centered = self.command(file, state, "hole", [RIM], {"diameter": "1", "depth": "3"})
        self.assertFalse(centered["ok"])
        self.assertIn("Click the face where the hole goes.", centered["error"])
        self.assertEqual(script.read_bytes(), before)
        # Clicked on the rim's right side, 19 along X from its center, as the panel takes the click.
        reply = self.command(file, state, "hole", [RIM], {"diameter": "1", "depth": "3", "x": "19", "y": "0"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    tray -= Pos(19, 0) * Plane(tray.faces().sort_by(Axis.Z)[-1]) * Cylinder(1/2, 3, "
                      "align=(Align.CENTER, Align.CENTER, Align.MAX))\n    return tray\n", script.read_text(encoding="utf-8"))
        # Drilled there: what it took out, found from how far the center of mass moved, is 19 along X
        # and 1.5 under the rim.
        drilled = self.service.change({"file": file, "mass": {}, "files": reply["files"]})["mass"]
        taken = weighed["volume"] - drilled["volume"]
        self.assertAlmostEqual(taken, math.pi * 0.5 ** 2 * 3, places=3)
        at = [(weighed["volume"] * was - drilled["volume"] * now) / taken for was, now in zip(weighed["center"], drilled["center"])]
        for got, wanted in zip(at, (19, 0, 3.5)):
            self.assertAlmostEqual(got, wanted, places=2)


class PlateCommands(Commands):
    def hole_row(self, state):
        return next(row for row in state["rows"] if row["kind"] == "Hole")

    def test_a_fillet_in_an_inch_part_is_written_in_inches(self):
        root, file, state = self.open(PLATE, "plate.step")
        half_length, half_width, top = 25.4, 12.7, 3.175
        edges = [edge("e1", (0, -half_width, top), 50.8), edge("e2", (0, half_width, top), 50.8),
                 edge("e3", (-half_length, 0, top), 25.4), edge("e4", (half_length, 0, top), 25.4)]
        reply = self.command(file, state, "fillet", edges, {"radius": ".05"})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        line = next(line.strip() for line in text.splitlines() if "bd.fillet(" in line)
        self.assertTrue(line.startswith("plate = bd.fillet(plate.") and line.endswith(", radius=.05*INCH)"), line)
        # Written before the label is set, so the body keeps it.
        self.assertLess(text.index("bd.fillet("), text.index("plate.label"))
        fillet = reply["rows"][-1]
        self.assertEqual([(each["label"], each["display"], each["unit"]) for each in fillet["inputs"]], [("Radius", "0.05", "in")])

    def test_a_pattern_of_a_hole_names_the_hole_and_repeats_it(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": self.hole_row(state)["key"], "name": "Hole1"}
        reply = self.command(file, state, "pattern", (), {"type": "linear", "direction": "X", "spacing": "-.4", "count": "3"}, feature)
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("plate -= (hole1 := bd.Pos(.5*INCH, 0, 0) * bd.Cylinder(.1*INCH, THICKNESS*INCH))\n", text)
        self.assertIn("plate -= [loc * hole1 for loc in bd.GridLocations(-.4*INCH, 0, 3, 1, "
                      "align=(bd.Align.MIN, bd.Align.CENTER)).locations[1:]]\n", text)
        self.assertEqual([row["kind"] for row in reply["rows"]], ["Box", "Hole", "Pattern"])
        pattern = reply["rows"][-1]
        self.assertEqual([(each["label"], each["display"]) for each in pattern["inputs"]], [("Spacing", "-0.4"), ("Instances", "3")])
        # The new feature's inputs change as any feature's do: a number in its line.
        more = self.service.change({"file": file, "input": {"row": pattern["key"], "index": 1}, "text": "4", "files": reply["files"]})
        self.assertTrue(more["ok"], more.get("error"))
        self.assertIn("GridLocations(-.4*INCH, 0, 4, 1,", (root / "plate.py").read_text(encoding="utf-8"))

    def test_a_hole_patterned_then_mirrored_is_named_once(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": self.hole_row(state)["key"], "name": "Hole1"}
        patterned = self.command(file, state, "pattern", (), {"type": "linear", "direction": "X", "spacing": "-.4", "count": "2"}, feature)
        self.assertTrue(patterned["ok"], patterned.get("error"))
        feature = {"row": self.hole_row(patterned)["key"], "name": "Hole1"}
        mirrored = self.command(file, patterned, "mirror", (), {"plane": "XZ"}, feature)
        self.assertTrue(mirrored["ok"], mirrored.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertEqual(text.count(":= "), 1)
        self.assertIn("plate -= bd.mirror(hole1, about=bd.Plane.XZ)\n", text)

    def test_a_mirror_of_a_feature_about_a_plane(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": self.hole_row(state)["key"], "name": "Hole1"}
        reply = self.command(file, state, "mirror", (), {"plane": "YZ"}, feature)
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("plate -= (hole1 := bd.Pos(.5*INCH, 0, 0) * bd.Cylinder(.1*INCH, THICKNESS*INCH))\n", text)
        self.assertIn("plate -= bd.mirror(hole1, about=bd.Plane.YZ)\n", text)
        self.assertEqual([row["kind"] for row in reply["rows"]], ["Box", "Hole", "Mirror"])

    def test_a_command_on_a_file_changed_since_it_was_read_is_refused(self):
        root, file, state = self.open(PLATE, "plate.step")
        script = root / "plate.py"
        script.write_text(script.read_text(encoding="utf-8").replace("LENGTH = 2.00", "LENGTH = 2.10"), encoding="utf-8")
        refused = self.command(file, state, "mirror", (), {"plane": "XZ"})
        self.assertFalse(refused["ok"])
        self.assertIn("changed since", refused["error"])
        self.assertNotIn("mirror", script.read_text(encoding="utf-8"))


class EditingFeatures(Commands):
    """Edit Feature: a command's feature opened with its values, its own line written again."""

    def feature(self, state: dict, kind: str) -> dict:
        return next(feature for feature in state["features"] if feature["kind"] == kind)

    def edit(self, file: str, state: dict, feature: dict, inputs: dict) -> dict:
        spec = {"command": feature["edit"]["command"], "inputs": inputs, "replace": {"row": feature["key"]}}
        return self.service.change({"file": file, "command": spec, "files": state["files"]})

    def test_a_fillet_opens_with_its_radius_and_is_written_again_in_its_place(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        before = script.read_text(encoding="utf-8")
        fillet = self.feature(made, "Fillet")
        self.assertEqual(fillet["edit"], {"command": "fillet", "values": {"radius": "1"}, "keeps": "4 edges"})
        edited = self.edit(file, made, fillet, {"radius": "0.5"})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before.replace(", radius=1)", ", radius=0.5)"))
        self.assertTrue(edited["change"]["edited"])
        self.assertEqual([feature["kind"] for feature in edited["features"]].count("Fillet"), 1)
        undone = self.service.change({"file": file, "splice": edited["change"]["undo"], "files": edited["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)

    def test_a_chamfer_of_two_distances_or_a_distance_and_an_angle_reopens_as_it_was_made(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "chamfer", BLOCK_TOP_EDGES, {"type": "distances", "distance": "1", "distance2": "0.5", "flip": True})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        self.assertIn(", length=0.5, length2=1)\n", script.read_text(encoding="utf-8"))
        chamfer = self.feature(made, "Chamfer")
        self.assertEqual(chamfer["edit"]["values"], {"distance": "0.5", "type": "distances", "distance2": "1"})
        self.assertEqual([(each["label"], each["display"]) for each in made["rows"][-1]["inputs"]], [("Distance", "0.5"), ("Distance 2", "1")])
        angled = self.edit(file, made, chamfer, {"type": "angle", "distance": "1", "angle": "30"})
        self.assertTrue(angled["ok"], angled.get("error"))
        self.assertIn(", length=1, angle=30)\n", script.read_text(encoding="utf-8"))
        self.assertEqual(self.feature(angled, "Chamfer")["edit"]["values"], {"distance": "1", "type": "angle", "angle": "30"})
        steep = self.edit(file, angled, self.feature(angled, "Chamfer"), {"type": "angle", "distance": "1", "angle": "90"})
        self.assertFalse(steep["ok"])
        # Flipped, the distance runs along each edge's other face: build123d's length is then the
        # distance times the angle's tangent, written so, and it reopens flipped.
        flipped = self.edit(file, angled, self.feature(angled, "Chamfer"), {"type": "angle", "distance": "1", "angle": "30", "flip": True})
        self.assertTrue(flipped["ok"], flipped.get("error"))
        self.assertIn(", length=1 * tan(radians(30)), length2=1)\n", script.read_text(encoding="utf-8"))
        self.assertEqual(self.feature(flipped, "Chamfer")["edit"]["values"], {"distance": "1", "type": "angle", "angle": "30", "flip": True})

    def test_a_value_left_as_it_was_keeps_its_named_size(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        script.write_text(script.read_text(encoding="utf-8").replace("radius=2)", "radius=WALL)").replace(
            "@model", "WALL = 2\n\n\n@model"), encoding="utf-8")
        state = self.service.state(file)
        self.assertTrue(state["ok"], state.get("error"))
        fillet = self.feature(state, "Fillet")
        self.assertEqual(fillet["edit"]["values"], {"radius": "2"})
        self.assertEqual(fillet["edit"]["keeps"], "4 edges")
        edited = self.edit(file, state, fillet, {"radius": "2"})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertIn("outer = fillet(outer.edges().filter_by(Axis.Z), radius=WALL)\n", script.read_text(encoding="utf-8"))
        # A line no command writes opens Edit Parameters on its sizes: the agent's own hole.
        self.assertEqual(self.feature(state, "Hole")["edit"]["command"], "sizes")

    def test_a_hole_keeps_its_face_and_moves_on_it(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3", "x": "5"})
        self.assertTrue(made["ok"], made.get("error"))
        hole = self.feature(made, "Hole")
        self.assertEqual(hole["edit"]["values"], {"diameter": "2", "through": False, "depth": "3", "x": "5", "y": "0", "type": "simple"})
        edited = self.edit(file, made, hole, {"diameter": "3", "depth": "", "x": "5", "y": "-2"})
        self.assertTrue(edited["ok"], edited.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertIn("part -= Pos(5, -2) * Plane(part.faces().sort_by(Axis.Z)[-1]) * Cylinder(3/2, part.bounding_box().diagonal, "
                      "align=(Align.CENTER, Align.CENTER, Align.MAX))\n", text)
        self.assertEqual(text.count("Cylinder("), 1)

    def test_a_pattern_turns_to_another_direction_and_keeps_what_it_repeats(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": next(row for row in state["rows"] if row["kind"] == "Hole")["key"], "name": "Hole1"}
        made = self.command(file, state, "pattern", (), {"type": "linear", "direction": "X", "spacing": "-.4", "count": "3"}, feature)
        self.assertTrue(made["ok"], made.get("error"))
        pattern = self.feature(made, "Pattern")
        self.assertEqual(pattern["edit"]["values"], {"type": "linear", "direction": "X", "spacing": "0.4", "reverse": True, "count": "3"})
        self.assertEqual(pattern["edit"]["keeps"], "hole1")
        edited = self.edit(file, made, pattern, {"type": "linear", "direction": "Y", "spacing": ".3", "count": "3"})
        self.assertTrue(edited["ok"], edited.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("plate -= [loc * hole1 for loc in bd.GridLocations(0, .3*INCH, 1, 3, "
                      "align=(bd.Align.CENTER, bd.Align.MIN)).locations[1:]]\n", text)
        self.assertEqual(text.count("hole1 :="), 1)

    def test_a_pattern_in_two_directions_lays_out_a_grid_and_reopens_with_both(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": next(row for row in state["rows"] if row["kind"] == "Hole")["key"], "name": "Hole1"}
        made = self.command(file, state, "pattern", (), {"type": "linear", "direction": "X", "spacing": ".4", "count": "3",
                                                         "direction2": True, "spacing2": "-(.2)", "count2": "2"}, feature)
        self.assertTrue(made["ok"], made.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("plate -= [loc * hole1 for loc in bd.GridLocations(.4*INCH, -.2*INCH, 3, 2, "
                      "align=(bd.Align.MIN, bd.Align.MIN)).locations[1:]]\n", text)
        self.assertEqual(made["change"]["what"], "3 along X by 2 along Y")
        pattern = self.feature(made, "Pattern")
        self.assertEqual(pattern["edit"]["values"], {"type": "linear", "direction": "X", "spacing": "0.4", "reverse": False, "count": "3",
                                                     "direction2": True, "spacing2": "0.2", "reverse2": True, "count2": "2"})
        # Five more holes than the one: a grid of six.
        self.assertEqual(sum(1 for face in made["rows"] if face["kind"] == "Pattern"), 1)
        refused = self.command(file, made, "pattern", (), {"type": "linear", "direction": "Z", "spacing": "1", "count": "2",
                                                           "direction2": True, "spacing2": "1", "count2": "2"}, feature)
        self.assertFalse(refused["ok"])
        self.assertIn("other of them", refused["error"])

    def test_a_pattern_up_z_places_each_copy_and_reads_back(self):
        root, file, state = self.open(PLATE, "plate.step")
        feature = {"row": next(row for row in state["rows"] if row["kind"] == "Hole")["key"], "name": "Hole1"}
        made = self.command(file, state, "pattern", (), {"type": "linear", "direction": "Z", "spacing": "-(.3)", "count": "3"}, feature)
        self.assertTrue(made["ok"], made.get("error"))
        text = (root / "plate.py").read_text(encoding="utf-8")
        self.assertIn("plate -= [bd.Pos(0, 0, -.3*INCH * i) * hole1 for i in range(1, 3)]\n", text)
        self.assertEqual([row["kind"] for row in made["rows"]], ["Box", "Hole", "Pattern"])
        self.assertEqual([(each["label"], each["display"]) for each in made["rows"][-1]["inputs"]], [("Spacing", "-0.3")])
        pattern = self.feature(made, "Pattern")
        self.assertEqual(pattern["edit"]["values"], {"type": "linear", "direction": "Z", "spacing": "0.3", "reverse": True, "count": "3"})
        edited = self.edit(file, made, pattern, {"type": "linear", "direction": "Z", "spacing": "-(.3)", "count": "5"})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertIn("plate -= [bd.Pos(0, 0, -.3*INCH * i) * hole1 for i in range(1, 5)]\n", (root / "plate.py").read_text(encoding="utf-8"))

    def test_a_circular_pattern_turns_about_a_round_face_or_a_straight_edge(self):
        hub = {"hub.py": """
            from build123d import Box, Cylinder, Pos
            from cadgen import model


            @model
            def hub():
                hub = Box(40, 40, 4) + Pos(5, 5, 4) * Cylinder(4, 4)
                hub -= Pos(15, 5, 0) * Cylinder(1, 10)
                return hub
        """}
        root, file, state = self.open(hub, "hub.step")
        feature = {"row": next(row for row in state["rows"] if row["kind"] == "Hole")["key"], "name": "Hole1"}
        # The boss's side, as the viewer reads it: a bolt circle of the hole about the boss's axis.
        boss = {"selector": "f99", "type": "cylinder", "center": [5.0, 5.0, 4.0], "size": 100.530965}
        made = self.command(file, state, "pattern", [boss], {"type": "circular", "count": "6"}, feature)
        self.assertTrue(made["ok"], made.get("error"))
        text = (root / "hub.py").read_text(encoding="utf-8")
        self.assertRegex(text, r"\n    hub -= \[hole1\.rotate\(hub\.faces\(\)[^\n]*\.axis_of_rotation, i \* 360 / 6\) for i in range\(1, 6\)\]\n")
        self.assertEqual([row["kind"] for row in made["rows"]][-1], "Pattern")
        pattern = self.feature(made, "Pattern")
        self.assertEqual(pattern["edit"]["values"], {"type": "circular", "count": "6", "axis": "a round face's axis"})
        self.assertEqual(made["change"]["what"], "6 around a round face's axis")
        # Edit Feature keeps the axis as written, unless another is picked: a straight edge, the box's corner.
        more = self.edit(file, made, pattern, {"type": "circular", "count": "8"})
        self.assertTrue(more["ok"], more.get("error"))
        self.assertIn(".axis_of_rotation, i * 360 / 8) for i in range(1, 8)]", (root / "hub.py").read_text(encoding="utf-8"))
        corner = edge("e99", (20, 20, 0), 4)
        spec = {"command": "pattern", "selection": [corner], "inputs": {"type": "circular", "count": "4"},
                "replace": {"row": self.feature(more, "Pattern")["key"]}}
        about = self.service.change({"file": file, "command": spec, "files": more["files"]})
        self.assertTrue(about["ok"], about.get("error"))
        text = (root / "hub.py").read_text(encoding="utf-8")
        self.assertRegex(text, r"\n    hub -= \[hole1\.rotate\(Axis\(hub\.edges\(\)[^\n]*\), i \* 360 / 4\) for i in range\(1, 4\)\]\n")
        self.assertTrue(any(line.startswith("from build123d import") and "Axis" in line for line in text.splitlines()))
        # Its Angle, the instances spread from the first to the last over it, reversed: and it reopens so.
        spread = self.edit(file, about, self.feature(about, "Pattern"), {"type": "circular", "count": "4", "angle": "90", "reverse": True})
        self.assertTrue(spread["ok"], spread.get("error"))
        self.assertIn(", i * -90 / (4 - 1)) for i in range(1, 4)]", (root / "hub.py").read_text(encoding="utf-8"))
        self.assertEqual({key: self.feature(spread, "Pattern")["edit"]["values"].get(key) for key in ("angle", "reverse")},
                         {"angle": "90", "reverse": True})
        self.assertEqual(spread["change"]["what"], "4 around a straight edge, over 90 degrees")
        # The boss's top: flat, so no axis to turn about.
        flat = {"selector": "f99", "type": "plane", "center": [5.0, 5.0, 6.0], "size": 50.265482}
        refused = self.command(file, spread, "pattern", [flat], {"type": "circular", "count": "4"}, feature)
        self.assertFalse(refused["ok"])
        self.assertIn("round face's axis or a straight edge", refused["error"])

    def test_a_feature_of_another_kind_is_refused(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        fillet = self.feature(made, "Fillet")
        refused = self.service.change({"file": file, "files": made["files"], "command": {
            "command": "chamfer", "inputs": {"distance": "1"}, "replace": {"row": fillet["key"]}}})
        self.assertFalse(refused["ok"])
        self.assertIn("is a Fillet, not a Chamfer", refused["error"])


class Deleting(Commands):
    """Delete on a feature of the design tree (``cadgen.edit.deleting``)."""

    def remove(self, file: str, state: dict, kind: str, title: str, nth: int = 0) -> dict:
        key = [feature["key"] for feature in state["features"] if feature["kind"] == kind][nth]
        return self.service.change({"file": file, "remove": {"feature": key, "title": title}, "files": state["files"]})

    def test_a_feature_that_changes_the_body_in_place_is_taken_out_and_undo_puts_it_back(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        before = script.read_bytes()
        reply = self.remove(file, state, "Hole", "Hole1")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertNotIn("Cylinder(1, 20)", script.read_text(encoding="utf-8"))
        self.assertNotIn("Hole", [feature["kind"] for feature in reply["features"]])
        self.assertEqual((reply["change"]["kind"], reply["change"]["line"]), ("delete", 14))
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_bytes(), before)

    def test_a_cut_that_starts_a_name_keeps_the_name_as_the_body_it_was_cut_from(self):
        root, file, state = self.open(TRAY, "tray.step")
        reply = self.remove(file, state, "Cut-Extrude", "Cut-Extrude1")
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "tray.py").read_text(encoding="utf-8")
        self.assertIn("    tray = outer\n", text)
        self.assertNotIn("cavity", text)

    def test_a_feature_made_in_a_loop_goes_with_its_loop(self):
        root, file, state = self.open(TRAY, "tray.step")
        reply = self.remove(file, state, "Boss-Extrude", "Boss-Extrude2", nth=1)
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "tray.py").read_text(encoding="utf-8")
        self.assertNotIn("for x in", text)
        self.assertNotIn("pad", text)

    def test_a_feature_whose_name_a_later_one_uses_is_refused_naming_where(self):
        root, file, state = self.open(TRAY, "tray.step")
        before = (root / "tray.py").read_bytes()
        refused = self.remove(file, state, "Boss-Extrude", "Boss-Extrude1")
        self.assertFalse(refused["ok"])
        # Its child features reach the part's `return`, which no feature makes.
        self.assertEqual(refused["error"], "Boss-Extrude1 and its child features make tray, which line 15 still uses. "
                                           "Ask the agent to remove it.")
        self.assertNotIn("children", refused)
        self.assertEqual((root / "tray.py").read_bytes(), before)



    def test_confirm_delete_names_the_child_features_and_deletes_them_with_it(self):
        root, file, state = self.open(POSTED, "posted.step")
        script = root / "posted.py"
        before = script.read_bytes()
        asked = self.remove(file, state, "Boss-Extrude", "Boss-Extrude2", nth=1)
        self.assertFalse(asked["ok"])
        self.assertEqual([child["kind"] for child in asked["children"]], ["Fillet"])
        self.assertEqual(script.read_bytes(), before)
        key = [feature["key"] for feature in state["features"] if feature["kind"] == "Boss-Extrude"][1]
        # Said of other children than it has (the tree changed since), it asks again.
        stale = self.service.change({"file": file, "files": state["files"],
                                     "remove": {"feature": key, "title": "Boss-Extrude2", "children": []}})
        self.assertEqual(stale["children"], asked["children"])
        reply = self.service.change({"file": file, "files": state["files"], "remove": {
            "feature": key, "title": "Boss-Extrude2", "children": [{"key": asked["children"][0]["key"], "title": "Fillet1"}]}})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertNotIn("Cylinder(4, 6)", script.read_text(encoding="utf-8"))
        self.assertEqual([feature["kind"] for feature in reply["features"]], ["Boss-Extrude", "Hole"])
        self.assertEqual(reply["change"]["children"], ["Fillet1"])
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_bytes(), before)


    def reorder(self, state: dict, kind: str, title: str, before: tuple | None, nth: int = 0) -> dict:
        keys = lambda name: [feature["key"] for feature in state["features"] if feature["kind"] == name]
        spec = {"feature": keys(kind)[nth], "title": title, "before": keys(before[0])[before[1]] if before else None}
        return self.service.change({"file": state["file"], "reorder": spec, "files": state["files"]})

    def test_a_feature_dragged_above_another_moves_its_lines_and_undo_puts_them_back(self):
        root, file, state = self.open(POSTED, "posted.step")
        state["file"] = file
        script = root / "posted.py"
        before = script.read_bytes()
        reply = self.reorder(state, "Hole", "Hole1", ("Boss-Extrude", 1))
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual([feature["kind"] for feature in reply["features"]], ["Boss-Extrude", "Hole", "Boss-Extrude", "Fillet"])
        self.assertIn("    plate = Box(40, 20, 4)\n    plate -= Pos(12, 0, 0) * Cylinder(1, 10)\n    post =", script.read_text(encoding="utf-8"))
        self.assertEqual((reply["change"]["kind"], reply["change"]["line"]), ("reorder", 8))
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_bytes(), before)

    def test_a_feature_is_not_moved_past_a_line_that_uses_what_it_changes(self):
        root, file, state = self.open(TRAY, "tray.step")
        state["file"] = file
        before = (root / "tray.py").read_bytes()
        refused = self.reorder(state, "Fillet", "Fillet1", None)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["error"], "Fillet1 and line 10 both use outer, and one changes it, so they cannot change places.")
        above = self.reorder(state, "Hole", "Hole1", ("Cut-Extrude", 0))
        self.assertEqual(above["error"], "Hole1 uses tray, which line 10 makes. It cannot go above that line.")
        self.assertEqual((root / "tray.py").read_bytes(), before)


class Suppressing(Commands):
    """Suppress and Unsuppress on a feature of the design tree (``cadgen.edit.deleting``)."""

    def suppress(self, file: str, state: dict, kind: str, title: str, on: bool = True, nth: int = 0) -> dict:
        key = [feature["key"] for feature in state["features"] if feature["kind"] == kind][nth]
        return self.service.change({"file": file, "suppress": {"feature": key, "title": title, "on": on}, "files": state["files"]})

    def test_a_suppressed_feature_stays_in_the_tree_and_comes_back_exactly(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        before = script.read_text(encoding="utf-8")
        reply = self.suppress(file, state, "Fillet", "Fillet1")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    outer = Box(40, 20, 10)\n    # Suppressed (Fillet, 1 line):\n"
                      "    # outer = fillet(outer.edges().filter_by(Axis.Z), radius=2)\n    cavity =", script.read_text(encoding="utf-8"))
        self.assertEqual([(feature["kind"], bool(feature.get("suppressed"))) for feature in reply["features"]][:3],
                         [("Boss-Extrude", False), ("Fillet", True), ("Cut-Extrude", False)])
        self.assertEqual((reply["change"]["kind"], reply["change"]["on"], reply["change"]["line"]), ("suppress", True, 8))
        back = self.suppress(file, reply, "Fillet", "Fillet1", on=False)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)
        self.assertFalse(any(feature.get("suppressed") for feature in back["features"]))

    def test_a_cut_that_starts_a_name_keeps_the_name_while_suppressed(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        before = script.read_text(encoding="utf-8")
        reply = self.suppress(file, state, "Cut-Extrude", "Cut-Extrude1")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    # Suppressed (Cut-Extrude, 2 lines):\n    # cavity = Pos(0, 0, 2) * Box(36, 16, 10)\n"
                      "    # tray = outer - cavity\n    tray = outer  # Cut-Extrude suppressed\n", script.read_text(encoding="utf-8"))
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)
        # Deleted while suppressed, it goes as Delete takes it out: the name kept as the body.
        again = self.suppress(file, undone, "Cut-Extrude", "Cut-Extrude1")
        deleted = self.service.change({"file": file, "files": again["files"], "remove": {
            "feature": next(f["key"] for f in again["features"] if f.get("suppressed")), "title": "Cut-Extrude1"}})
        self.assertTrue(deleted["ok"], deleted.get("error"))
        text = script.read_text(encoding="utf-8")
        self.assertIn("    tray = outer\n", text)
        self.assertNotIn("cavity", text)
        self.assertNotIn("Suppressed", text)

    def test_a_comment_after_a_suppressed_feature_stays_the_engineers(self):
        root, file, state = self.open(TRAY, "tray.step")
        script = root / "tray.py"
        script.write_text(script.read_text(encoding="utf-8").replace("radius=2)\n", "radius=2)\n    # x = 1\n"), encoding="utf-8")
        before = script.read_text(encoding="utf-8")
        state = self.service.state(file)
        reply = self.suppress(file, state, "Fillet", "Fillet1")
        self.assertTrue(reply["ok"], reply.get("error"))
        back = self.suppress(file, reply, "Fillet", "Fillet1", on=False)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)

    def test_a_feature_a_later_one_uses_is_not_suppressed(self):
        root, file, state = self.open(TRAY, "tray.step")
        before = (root / "tray.py").read_bytes()
        refused = self.suppress(file, state, "Boss-Extrude", "Boss-Extrude1")
        self.assertFalse(refused["ok"])
        self.assertIn("Boss-Extrude1 and its child features make tray, which line 15 still uses. Ask the agent to suppress it.", refused["error"])
        self.assertEqual((root / "tray.py").read_bytes(), before)

    def test_suppress_sets_the_child_features_aside_with_it_and_unsuppress_puts_back_only_it(self):
        root, file, state = self.open(POSTED, "posted.step")
        script = root / "posted.py"
        before = script.read_text(encoding="utf-8")
        reply = self.suppress(file, state, "Boss-Extrude", "Boss-Extrude2", nth=1)
        self.assertTrue(reply["ok"], reply.get("error"))
        # The fillet is made between the post's lines, so its block is inside the post's.
        self.assertEqual([(f["kind"], bool(f.get("suppressed"))) for f in reply["features"]],
                         [("Boss-Extrude", False), ("Boss-Extrude", True), ("Hole", False)])
        self.assertEqual(len(reply["change"]["children"]), 1)
        # Unsuppress puts back the post; its fillet stays suppressed, as SolidWorks leaves it.
        back = self.suppress(file, reply, "Boss-Extrude", "Boss-Extrude2", on=False, nth=1)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual([(f["kind"], bool(f.get("suppressed"))) for f in back["features"]],
                         [("Boss-Extrude", False), ("Boss-Extrude", False), ("Fillet", True), ("Hole", False)])
        whole = self.suppress(file, back, "Fillet", "Fillet1", on=False)
        self.assertTrue(whole["ok"], whole.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)
        again = self.suppress(file, whole, "Boss-Extrude", "Boss-Extrude2", nth=1)
        undone = self.service.change({"file": file, "splice": again["change"]["undo"], "files": again["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)

    def test_a_new_feature_goes_after_a_suppressed_one_at_the_end(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3"})
        self.assertTrue(made["ok"], made.get("error"))
        suppressed = self.suppress(file, made, "Hole", "Hole1")
        self.assertTrue(suppressed["ok"], suppressed.get("error"))
        shelled = self.command(file, suppressed, "shell", BLOCK_TOP, {"thickness": "1"})
        self.assertTrue(shelled["ok"], shelled.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertLess(text.index("# Suppressed (Hole"), text.index("offset(part"))
        self.assertEqual([(f["kind"], bool(f.get("suppressed"))) for f in shelled["features"]],
                         [("Boss-Extrude", False), ("Hole", True), ("Shell", False)])



class RollingBack(Commands):
    """The rollback bar, and Edit Feature picking a feature's edges again on the body before it."""

    def test_the_bar_shows_the_body_above_a_feature_and_a_command_goes_there(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "hole", BLOCK_TOP, {"diameter": "2", "depth": "3"})
        self.assertTrue(made["ok"], made.get("error"))
        hole = next(feature for feature in made["features"] if feature["kind"] == "Hole")
        bar = {"before": f"block.py:{hole['line']}"}
        rolled = self.service.change({"file": file, "files": made["files"], "bar": bar})
        self.assertTrue(rolled["ok"], rolled.get("error"))
        self.assertEqual((rolled["bar"]["before"], rolled["bar"]["item"], rolled["bar"]["name"], rolled["bar"]["kind"]),
                         (bar["before"], hole["key"], "part", "part"))
        # The body there, handed to the engine as a document the viewer opens by its id: the block before its hole.
        from cadgen.engine import api

        summary = api.inspect(rolled["bar"]["document"]["id"], query="summary")["summary"]
        self.assertAlmostEqual(summary["volume"], 20 * 10 * 4, places=3)
        filleted = self.service.change({"file": file, "files": rolled["files"], "bar": rolled["bar"], "command": {
            "command": "fillet", "selection": BLOCK_TOP_EDGES, "inputs": {"radius": "1"}}})
        self.assertTrue(filleted["ok"], filleted.get("error"))
        lines = (root / "block.py").read_text(encoding="utf-8").splitlines()
        at = next(index for index, line in enumerate(lines) if "fillet(" in line)
        self.assertIn("Cylinder(", lines[at + 1])
        self.assertEqual([feature["kind"] for feature in filleted["features"]], ["Boss-Extrude", "Fillet", "Hole"])
        # The bar stays above the hole, which moved down a line.
        self.assertEqual(filleted["bar"]["before"], f"block.py:{hole['line'] + 1}")
        forward = self.service.change({"file": file, "files": filleted["files"], "bar": None})
        self.assertIsNone(forward["bar"])

    def test_moving_the_bar_alone_does_not_run_the_part_again(self):
        root, file, state = self.open(TRAY, "tray.step")
        fillet = next(feature for feature in state["features"] if feature["kind"] == "Fillet")
        moved = self.service.change({"file": file, "files": state["files"], "bar": {"item": fillet["key"]}})
        self.assertTrue(moved["ok"], moved.get("error"))
        # Answered from the last read of the part: the bar, and nothing else to draw again.
        self.assertTrue(moved.get("unchanged"))
        self.assertNotIn("features", moved)
        self.assertEqual(moved["bar"]["item"], fillet["key"])
        # A file changed since that read is read again before the bar is placed.
        script = root / "tray.py"
        script.write_text(script.read_text(encoding="utf-8") + "\n# changed by hand\n", encoding="utf-8")
        again = self.service.change({"file": file, "files": state["files"], "bar": {"item": fillet["key"]}})
        self.assertTrue(again["ok"], again.get("error"))
        self.assertNotIn("unchanged", again)
        self.assertEqual(again["bar"]["item"], fillet["key"])

    def test_edit_feature_picks_a_fillets_edges_again_on_the_body_before_it(self):
        root, file, state = self.open(TRAY, "tray.step")
        fillet = next(feature for feature in state["features"] if feature["kind"] == "Fillet")
        # The box's four top edges, as the viewer reads them on the body before the fillet.
        top = [edge("e1", (0, -10, 5), 40), edge("e2", (0, 10, 5), 40), edge("e3", (-20, 0, 5), 20), edge("e4", (20, 0, 5), 20)]
        edited = self.service.change({"file": file, "files": state["files"], "bar": {"before": "tray.py:8"}, "bar_after": None, "command": {
            "command": "fillet", "selection": top, "inputs": {"radius": "2"}, "replace": {"row": fillet["key"]}}})
        self.assertTrue(edited["ok"], edited.get("error"))
        line = (root / "tray.py").read_text(encoding="utf-8").splitlines()[7]
        self.assertTrue(line.startswith("    outer = fillet(outer.") and line.endswith(", radius=2)"), line)
        self.assertNotIn("filter_by(Axis.Z)", line)
        self.assertIsNone(edited["bar"])
        self.assertEqual(next(f for f in edited["features"] if f["kind"] == "Fillet")["edit"]["keeps"], "4 edges")



class Previews(Commands):
    """Preview: what a command's OK would make, made without writing it, for its panel to draw over
    the model as the material the feature takes away and the material it adds."""

    def preview(self, file: str, state: dict, command: str, selection=(), inputs=None, **request):
        spec = {"command": command, "selection": list(selection), "inputs": inputs or {}}
        return self.service.change({"file": file, "preview": spec, "files": state["files"], **request})

    def test_a_fillets_preview_is_what_it_rounds_off_and_the_file_is_left_as_it_was(self):
        root, file, state = self.open(BLOCK, "block.step")
        before = (root / "block.py").read_bytes()
        reply = self.preview(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertTrue(reply["ok"], reply.get("error"))
        shown = reply["preview"]
        self.assertEqual((shown["error"], shown["added"]), (None, None))
        removed = shown["removed"]
        # Triangles over what comes off, and its edges, each the points along it: all of it along
        # the block's top, within the radius.
        corners = len(removed["positions"]) // 3
        self.assertTrue(removed["triangles"] and max(removed["triangles"]) < corners)
        self.assertGreaterEqual(min(removed["positions"][2::3]), 1 - 1e-6)
        self.assertTrue(removed["edges"] and all(len(points) % 3 == 0 and len(points) >= 6 for points in removed["edges"]))
        self.assertEqual((root / "block.py").read_bytes(), before)
        self.assertNotIn("change", reply)
        # OK then writes the fillet, the part read as it is.
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertTrue(made["ok"], made.get("error"))
        self.assertIn("    part = fillet(part.edges().group_by(Axis.Z)[-1], radius=1)\n", (root / "block.py").read_text(encoding="utf-8"))

    def test_a_preview_that_cannot_be_made_says_why(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.preview(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "6"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("smaller radius", reply["preview"]["error"])
        self.assertNotIn("fillet", (root / "block.py").read_text(encoding="utf-8"))

    def test_a_patterns_preview_is_the_copies_it_adds(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.preview(file, state, "pattern", (), {"type": "linear", "direction": "X", "spacing": "30", "count": "2"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIsNone(reply["preview"]["removed"])
        xs = reply["preview"]["added"]["positions"][0::3]
        self.assertEqual((min(xs), max(xs)), (20, 40))

    def test_a_preview_at_the_bar_leaves_the_part_read_as_it_is(self):
        root, file, state = self.open(TRAY, "tray.step")
        # Above the cavity, the preview's line moves the cavity a line down in the text it runs.
        reply = self.preview(file, state, "chamfer", [edge("e1", (0, -10, 5), 36)], {"distance": "0.5"}, bar={"before": "tray.py:9"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIsNotNone(reply["preview"]["removed"])
        self.assertNotIn("bar", reply)
        # The cavity's length is still where the file has it.
        resized = self.service.change({"file": file, "files": state["files"], "dimension": "2:x", "text": "30"})
        self.assertTrue(resized["ok"], resized.get("error"))
        self.assertEqual((root / "tray.py").read_text(encoding="utf-8").splitlines()[8], "    cavity = Pos(0, 0, 2) * Box(30, 16, 10)")


class MassProperties(Commands):
    """Mass Properties, as SolidWorks' Evaluate tab works them out: volume, area, center of mass and
    size from the part's solids, and the materials it could be made of, the project's own named."""

    def mass(self, file: str, state: dict, **request) -> dict:
        reply = self.service.change({"file": file, "mass": {}, "files": state["files"], **request})
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply["mass"]

    def test_a_block_has_its_volume_and_area_and_balances_at_its_middle(self):
        root, file, state = self.open({**BLOCK, "project.json": '{"brief": {"material": "PETG"}}'}, "block.step")
        mass = self.mass(file, state)
        self.assertAlmostEqual(mass["volume"], 20 * 10 * 4, places=6)
        self.assertAlmostEqual(mass["area"], 2 * (200 + 80 + 40), places=6)
        self.assertEqual([round(value, 6) + 0 for value in mass["center"]], [0, 0, 0])
        self.assertEqual(mass["box"], [[-10, -5, -2], [10, 5, 2]])
        # The project's material, and each the table has with its density in g/cm^3.
        self.assertEqual(mass["material"], "PETG_GENERIC")
        self.assertIn({"key": "Alu_G6061_T6", "name": "Alu_G6061_T6", "density": 2.7, "fea": True}, mass["materials"])

    def test_at_the_rollback_bar_it_is_the_part_as_it_is_there(self):
        root, file, state = self.open(TRAY, "tray.step")
        whole = self.mass(file, state)
        # Above the cavity, the tray is still its solid block.
        above = self.mass(file, state, bar={"before": "tray.py:9"})
        self.assertGreater(above["volume"], whole["volume"])
        self.assertIsNone(above["material"])


# A block with three sketches above it: a circle, a path up and across, and a larger circle 12 up.
SKETCHED = {
    "bracket.py": """
        from build123d import Box, Pos
        from cadgen import model
        from cadgen.sketch import Sketch


        @model
        def bracket():
            part = Pos(0, 0, -5) * Box(40, 20, 10)
            sketch1 = Sketch("Sketch1", plane="Top")
            sketch1.circle((0, 0), 2)
            sketch2 = Sketch("Sketch2", plane="Front")
            up = sketch2.line((0, 0), (0, 20))
            over = sketch2.line((0, 20), (15, 20))
            sketch2.coincident(up.end, over.start)
            sketch3 = Sketch("Sketch3", plane="Top", offset=12)
            sketch3.circle((0, 0), 4)
            return part
    """,
}

# A channel: a floor 5 thick between two walls, and a rib's line across its top, 8 up.
CHANNEL = {
    "channel.py": """
        from build123d import Box, Pos
        from cadgen import model
        from cadgen.sketch import Sketch


        @model
        def channel():
            part = Box(40, 20, 20) - Pos(0, 0, 5) * Box(30, 30, 20)
            sketch1 = Sketch("Sketch1", plane="Front")
            sketch1.line((-15, 8), (15, 8))
            return part
    """,
}

# A block with a rectangle sketched on its top.
WALLED = {
    "box.py": """
        from build123d import Box, Pos
        from cadgen import model
        from cadgen.sketch import Sketch


        @model
        def box():
            part = Pos(0, 0, -5) * Box(40, 20, 10)
            sketch1 = Sketch("Sketch1", plane="Top")
            sketch1.rectangle((-10, -5), (10, 5))
            return part
    """,
}


def sketch(name: str, line: int, file: str = "bracket.py") -> dict:
    return {"file": file, "line": line, "name": name}


class SketchedFeatures(Commands):
    """Sweep, Loft, Rib and Thin Feature, each made from sketches drawn in the part's script."""

    def made(self, root: Path, file: str, state: dict, spec: dict) -> dict:
        reply = self.service.change({"file": file, "command": spec, "files": state["files"]})
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def test_a_sweep_runs_its_profile_along_its_path_and_is_named_with_its_profile_under_it(self):
        root, file, state = self.open(SKETCHED, "bracket.step")
        reply = self.made(root, file, state, {"command": "sweep", "sketches": [sketch("Sketch1", 9), sketch("Sketch2", 11)], "inputs": {}})
        text = (root / "bracket.py").read_text(encoding="utf-8")
        # Its line goes right after the last sketch it is made from.
        self.assertIn("    sketch2.coincident(up.end, over.start)\n    part += sweep(sketch1.face(), path=sketch2.path(), transition=Transition.RIGHT)\n",
                      text)
        sweep = next(feature for feature in reply["features"] if feature["kind"] == "Boss-Sweep")
        self.assertEqual(sweep["sketch"]["name"], "Sketch1")
        self.assertEqual((sweep["edit"]["command"], sweep["edit"]["keeps"]), ("sweep", "Sketch1 along Sketch2"))
        # The path stays a sketch of its own in the tree; the profile is the sweep's.
        self.assertEqual([item["sketch"]["name"] for item in reply["features"] if item["kind"] == "Sketch"], ["Sketch2", "Sketch3"])
        # A sweep takes a profile and a path, both.
        refused = self.service.change({"file": file, "files": reply["files"], "command": {"command": "sweep", "sketches": [sketch("Sketch1", 9)]}})
        self.assertFalse(refused["ok"])
        self.assertIn("profile sketch, then the path sketch", refused["error"])

    def test_a_loft_joins_its_profiles_in_the_order_they_were_picked(self):
        root, file, state = self.open(SKETCHED, "bracket.step")
        reply = self.made(root, file, state, {"command": "loft", "sketches": [sketch("Sketch1", 9), sketch("Sketch3", 15)], "inputs": {}})
        self.assertIn("    part += loft([sketch1.face(), sketch3.face()])\n", (root / "bracket.py").read_text(encoding="utf-8"))
        loft = next(feature for feature in reply["features"] if feature["kind"] == "Boss-Loft")
        self.assertEqual((loft["sketch"]["name"], loft["edit"]["keeps"]), ("Sketch1", "through Sketch1, Sketch3"))
        # A loft's preview is the frustum it adds: 12 tall, from radius 2 to 4.
        before = self.service.change({"file": file, "files": reply["files"], "splice": reply["change"]["undo"]})
        self.assertTrue(before["ok"], before.get("error"))
        shown = self.service.change({"file": file, "files": before["files"], "preview": {"command": "loft",
                                                                                        "sketches": [sketch("Sketch1", 9), sketch("Sketch3", 15)], "inputs": {}}})
        zs = shown["preview"]["added"]["positions"][2::3]
        self.assertEqual((round(min(zs), 3), round(max(zs), 3)), (0, 12))

    def test_a_rib_grows_from_its_line_to_the_body_and_reopens_with_its_thickness(self):
        root, file, state = self.open(CHANNEL, "channel.step")
        # Grown up from its line, it meets nothing: the preview says to flip it.
        shown = self.service.change({"file": file, "files": state["files"], "preview": {"command": "rib", "sketch": sketch("Sketch1", 9, "channel.py"),
                                                                                       "inputs": {"thickness": "2"}}})
        self.assertIn("Flip it", shown["preview"]["error"])
        reply = self.made(root, file, state, {"command": "rib", "sketch": sketch("Sketch1", 9, "channel.py"), "inputs": {"thickness": "2", "flip": True}})
        self.assertIn("    part += sketch1.rib(2, part, flip=True)\n", (root / "channel.py").read_text(encoding="utf-8"))
        rib = next(feature for feature in reply["features"] if feature["kind"] == "Rib")
        self.assertEqual(rib["sketch"]["name"], "Sketch1")
        self.assertEqual(rib["edit"]["values"], {"thickness": "2", "flip": True})
        # Edit Feature writes it again in its place, thicker.
        again = self.service.change({"file": file, "files": reply["files"], "command": {"command": "rib", "sketch": sketch("Sketch1", 9, "channel.py"),
                                                                                       "inputs": {"thickness": "3", "flip": True}, "replace": {"row": rib["key"]}}})
        self.assertTrue(again["ok"], again.get("error"))
        self.assertIn("    part += sketch1.rib(3, part, flip=True)\n", (root / "channel.py").read_text(encoding="utf-8"))

    def test_a_thin_feature_extrudes_the_outline_as_a_wall_and_reopens_as_one(self):
        root, file, state = self.open(WALLED, "box.step")
        reply = self.made(root, file, state, {"command": "extrude", "sketch": sketch("Sketch1", 9, "box.py"),
                                              "inputs": {"end": "blind", "depth": "6", "thin": True, "thin_thickness": "1"}})
        self.assertIn("    part += extrude(sketch1.thin(1), amount=6)\n", (root / "box.py").read_text(encoding="utf-8"))
        boss = next(feature for feature in reply["features"] if feature["kind"] == "Boss-Extrude" and feature["sketch"].get("name") == "Sketch1")
        self.assertEqual({key: boss["edit"]["values"].get(key) for key in ("thin", "thin_thickness", "thin_side", "depth")},
                         {"thin": True, "thin_thickness": "1", "thin_side": "inside", "depth": "6"})
        # Astride the outline, written with its side.
        again = self.service.change({"file": file, "files": reply["files"], "command": {
            "command": "extrude", "sketch": sketch("Sketch1", 9, "box.py"), "replace": {"row": boss["key"]},
            "inputs": {"end": "blind", "depth": "6", "thin": True, "thin_thickness": "1", "thin_side": "mid"}}})
        self.assertTrue(again["ok"], again.get("error"))
        self.assertIn('    part += extrude(sketch1.thin(1, side="mid"), amount=6)\n', (root / "box.py").read_text(encoding="utf-8"))


# A plate 15 below the Top plane, and a square sketched on it to extrude both ways.
TWO_WAY = {
    "plate.py": """
        from build123d import Box, Pos
        from cadgen import model
        from cadgen.sketch import Sketch


        @model
        def plate():
            part = Pos(0, 0, -15) * Box(40, 20, 2)
            sketch1 = Sketch("Sketch1", plane="Top")
            sketch1.rectangle((-5, -5), (5, 5))
            return part
    """,
}


# A part whose first solid is its sketch extruded, as an agent writes one: `part = extrude(...)`, its depth a named size.
FIRST_SOLID = {
    "puck.py": """
        from build123d import extrude
        from cadgen import model
        from cadgen.sketch import Sketch

        HEIGHT = 4

        @model
        def puck():
            sketch1 = Sketch("Sketch1", plane="Top")
            sketch1.rectangle((-5, -5), (5, 5))
            part = extrude(sketch1.face(), amount=HEIGHT)
            return part
    """,
}


class TwoDirections(Commands):
    """Extrude's Direction 2: the sketch made a solid of the other way too, in one feature."""

    def extruded(self, file: str, files: dict, command: str, inputs: dict, replace: str | None = None) -> dict:
        spec = {"command": command, "sketch": sketch("Sketch1", 9, Path(file).with_suffix(".py").name), "inputs": inputs}
        reply = self.service.change({"file": file, "files": files, "command": {**spec, **({"replace": {"row": replace}} if replace else {})}})
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def test_a_boss_goes_both_ways_from_its_sketch_and_reopens_with_direction_2(self):
        root, file, state = self.open(TWO_WAY, "plate.step")
        reply = self.extruded(file, state["files"], "extrude", {"end": "blind", "depth": "6", "direction2": True, "end2": "blind", "depth2": "14"})
        self.assertIn("    part += extrude(sketch1.face(), amount=6) + extrude(sketch1.face(), amount=-14)\n", (root / "plate.py").read_text(encoding="utf-8"))
        boss = next(feature for feature in reply["features"] if feature["kind"] == "Boss-Extrude" and feature["sketch"].get("name") == "Sketch1")
        values = boss["edit"]["values"]
        self.assertNotIn("first", boss["edit"])
        self.assertEqual({key: values.get(key) for key in ("end", "depth", "direction2", "end2", "depth2")},
                         {"end": "blind", "depth": "6", "direction2": True, "end2": "blind", "depth2": "14"})
        # One feature, not two of one: its depths on the model are Height and Height 2.
        self.assertEqual(boss["count"], 1)
        row = next(row for row in reply["rows"] if row["key"] == boss["key"])
        self.assertEqual([(item["label"], item["value"]) for item in row["inputs"][:2]], [("Height", 6.0), ("Height 2", 14.0)])
        # Down 14 it meets the plate: one solid, the square 20 tall on it.
        mass = self.service.change({"file": file, "mass": {}, "files": reply["files"]})["mass"]
        self.assertAlmostEqual(mass["volume"], 40 * 20 * 2 + 10 * 10 * 20, places=4)
        self.assertEqual(mass["box"], [[-20, -10, -16], [20, 10, 6]])
        # Edit Feature: Direction 2 drafted, then turned off, the line one extrude again.
        drafted = self.extruded(file, reply["files"], "extrude", {**values, "draft2": True, "draft_angle2": "2"}, boss["key"])
        self.assertIn("amount=6) + extrude(sketch1.face(), amount=-14, taper=2)\n", (root / "plate.py").read_text(encoding="utf-8"))
        boss = next(feature for feature in drafted["features"] if feature["kind"] == "Boss-Extrude" and feature["sketch"].get("name") == "Sketch1")
        self.assertEqual((boss["edit"]["values"]["draft2"], boss["edit"]["values"]["draft_angle2"]), (True, "2"))
        self.extruded(file, drafted["files"], "extrude", {**boss["edit"]["values"], "direction2": False}, boss["key"])
        self.assertIn("    part += extrude(sketch1.face(), amount=6)\n", (root / "plate.py").read_text(encoding="utf-8"))

    def test_the_parts_first_extrude_reopens_and_is_written_again_with_its_own_assignment(self):
        root, file, state = self.open(FIRST_SOLID, "puck.step")
        boss = next(feature for feature in state["features"] if feature["kind"] == "Boss-Extrude")
        self.assertEqual({key: boss["edit"]["values"].get(key) for key in ("end", "depth", "reverse")}, {"end": "blind", "depth": "4", "reverse": False})
        # The part's first solid: the viewer does not roll back past it while it is edited.
        self.assertTrue(boss["edit"]["first"])
        # Left as it was, its depth stays the size's name; a new depth is written with `=`, as the line was.
        again = self.extruded(file, state["files"], "extrude", {**boss["edit"]["values"], "draft": True, "draft_angle": "3"}, boss["key"])
        self.assertIn("    part = extrude(sketch1.face(), amount=HEIGHT, taper=3)\n", (root / "puck.py").read_text(encoding="utf-8"))
        boss = next(feature for feature in again["features"] if feature["kind"] == "Boss-Extrude")
        deeper = self.extruded(file, again["files"], "extrude", {**boss["edit"]["values"], "draft": False, "depth": "7"}, boss["key"])
        self.assertIn("    part = extrude(sketch1.face(), amount=7)\n", (root / "puck.py").read_text(encoding="utf-8"))
        # Nothing comes before it to go up to.
        refused = self.service.change({"file": file, "files": deeper["files"], "command": {
            "command": "extrude", "sketch": sketch("Sketch1", 9, "puck.py"), "inputs": {"end": "next"}, "replace": {"row": boss["key"]}}})
        self.assertFalse(refused["ok"])
        self.assertIn("no body before it", refused["error"])

    def test_up_to_a_face_below_goes_down_to_it_and_direction_2_goes_up(self):
        root, file, state = self.open(TWO_WAY, "plate.step")
        plate_top = face("f1", (0, 0, -14), 800)
        spec = {"command": "extrude", "sketch": sketch("Sketch1", 9, "plate.py"), "selection": [plate_top],
                "inputs": {"end": "surface", "direction2": True, "end2": "blind", "depth2": "5"}}
        reply = self.service.change({"file": file, "files": state["files"], "command": spec})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn(") + extrude(sketch1.face(), amount=5)\n", (root / "plate.py").read_text(encoding="utf-8"))
        # Down 14 to the plate, up 5 the other way: the square 19 tall on the plate.
        mass = self.service.change({"file": file, "mass": {}, "files": reply["files"]})["mass"]
        self.assertAlmostEqual(mass["volume"], 40 * 20 * 2 + 10 * 10 * 19, places=4)
        boss = next(feature for feature in reply["features"] if feature["kind"] == "Boss-Extrude" and feature["sketch"].get("name") == "Sketch1")
        self.assertEqual({key: boss["edit"]["values"].get(key) for key in ("end", "direction2", "depth2")}, {"end": "surface", "direction2": True, "depth2": "5"})
        # Edit Feature keeps its face, and Direction 2 still goes up.
        again = self.extruded(file, reply["files"], "extrude", {**boss["edit"]["values"], "depth2": "6"}, boss["key"])
        self.assertIn(") + extrude(sketch1.face(), amount=6)\n", (root / "plate.py").read_text(encoding="utf-8"))
        self.assertTrue(again["ok"])

    def test_a_cut_that_takes_nothing_away_is_refused(self):
        root, file, state = self.open(WALLED, "box.step")
        before = (root / "box.py").read_text(encoding="utf-8")
        # The sketch is on the block's top: up, away from it, cuts nothing.
        missed = self.service.change({"file": file, "files": state["files"], "command": {
            "command": "cut", "sketch": sketch("Sketch1", 9, "box.py"), "inputs": {"end": "blind", "depth": "3"}}})
        self.assertFalse(missed["ok"])
        self.assertIn("does not reach the part", missed["error"])
        self.assertEqual((root / "box.py").read_text(encoding="utf-8"), before)
        self.extruded(file, state["files"], "cut", {"end": "blind", "depth": "3", "reverse": True})

    def test_a_cut_goes_through_all_the_other_way_and_refuses_mid_plane(self):
        root, file, state = self.open(WALLED, "box.step")
        reply = self.extruded(file, state["files"], "cut", {"end": "blind", "depth": "2", "direction2": True, "end2": "through"})
        self.assertIn("    part -= extrude(sketch1.face(), amount=2) + extrude(sketch1.face(), amount=-part.bounding_box().diagonal)\n",
                      (root / "box.py").read_text(encoding="utf-8"))
        cut = next(feature for feature in reply["features"] if feature["kind"] == "Cut-Extrude")
        self.assertEqual({key: cut["edit"]["values"].get(key) for key in ("direction2", "end2", "depth2")}, {"direction2": True, "end2": "through", "depth2": ""})
        # The sketch's 20 by 10 taken out of the block all the way down.
        mass = self.service.change({"file": file, "mass": {}, "files": reply["files"]})["mass"]
        self.assertAlmostEqual(mass["volume"], 40 * 20 * 10 - 20 * 10 * 10, places=4)
        # Mid Plane goes both ways already.
        refused = self.service.change({"file": file, "files": reply["files"], "command": {"command": "cut", "sketch": sketch("Sketch1", 9, "box.py"),
                                                                                         "inputs": {"end": "mid", "depth": "4", "direction2": True}}})
        self.assertFalse(refused["ok"])
        self.assertIn("Mid Plane, which goes both ways already", refused["error"])


# The block's four sides and its bottom face, as the viewer reads them.
BLOCK_SIDES =[face("f2", (10, 0, 0), 40), face("f3", (-10, 0, 0), 40), face("f4", (0, 5, 0), 80), face("f5", (0, -5, 0), 80)]
BLOCK_BOTTOM = face("f6", (0, 0, -2), 200)


class Drafts(Commands):
    """Draft, as SolidWorks' Neutral Plane draft: the faces picked tilt by the angle about where they
    meet the neutral plane (a flat face of the part, or an origin plane), the part narrowing the way
    its direction of pull goes."""

    def draft(self, file: str, state: dict, inputs: dict, neutral=None, preview=False) -> dict:
        spec = {"command": "draft", "selection": BLOCK_SIDES, "inputs": inputs, **({"neutral": neutral} if neutral else {})}
        return self.service.change({"file": file, "preview" if preview else "command": spec, "files": state["files"]})

    def test_sides_drafted_from_the_bottom_face_reopen_as_a_draft_of_four_faces(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.draft(file, state, {"angle": "3", "reverse": True}, neutral=BLOCK_BOTTOM)
        self.assertTrue(made["ok"], made.get("error"))
        line = next(each.strip() for each in (root / "block.py").read_text(encoding="utf-8").splitlines() if "draft(" in each)
        self.assertRegex(line, r"^part = draft\(part\.faces\(\).+, -Plane\(part\.faces\(\).+\), 3\)$")
        draft = next(feature for feature in made["features"] if feature["kind"] == "Draft")
        self.assertEqual(draft["edit"], {"command": "draft", "values": {"angle": "3", "neutral": "face", "reverse": True}, "keeps": "4 faces"})
        self.assertEqual([(each["label"], each["display"], each["unit"]) for each in made["rows"][-1]["inputs"]], [("Draft Angle", "3", "deg")])

    def test_the_direction_of_pull_is_the_way_the_part_narrows(self):
        root, file, state = self.open(BLOCK, "block.step")
        before = (root / "block.py").read_bytes()
        # Pulled up from its bottom face, the block keeps its foot and comes in at the top...
        up = self.draft(file, state, {"angle": "3", "reverse": True}, neutral=BLOCK_BOTTOM, preview=True)["preview"]
        self.assertEqual((up["error"], up["added"]), (None, None))
        self.assertGreater(max(up["removed"]["positions"][2::3]), 1.9)
        # ...pulled down, its top grows out.
        down = self.draft(file, state, {"angle": "3"}, neutral=BLOCK_BOTTOM, preview=True)["preview"]
        self.assertEqual((down["error"], down["removed"]), (None, None))
        self.assertIsNotNone(down["added"])
        # The Top Plane through its middle: it comes in above and grows below.
        middle = self.draft(file, state, {"angle": "3", "neutral": "Top"}, preview=True)["preview"]
        self.assertGreaterEqual(min(middle["removed"]["positions"][2::3]), -1e-6)
        self.assertLessEqual(max(middle["added"]["positions"][2::3]), 1e-6)
        self.assertEqual((root / "block.py").read_bytes(), before)

    def test_an_origin_plane_is_written_by_its_axes_and_edit_feature_writes_the_draft_again(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.draft(file, state, {"angle": "2", "neutral": "Top"})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        before = script.read_text(encoding="utf-8")
        self.assertRegex(before, r"\n    part = draft\(part\.faces\(\)[^\n]+, Plane\.XY, 2\)\n")
        draft = next(feature for feature in made["features"] if feature["kind"] == "Draft")
        self.assertEqual(draft["edit"]["values"], {"angle": "2", "neutral": "Top", "reverse": False})
        spec = {"command": "draft", "inputs": {"angle": "4", "neutral": "Top", "reverse": True}, "replace": {"row": draft["key"]}}
        edited = self.service.change({"file": file, "command": spec, "files": made["files"]})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before.replace(", Plane.XY, 2)", ", -Plane.XY, 4)"))

    def test_a_neutral_plane_that_is_not_flat_or_is_drafted_itself_is_refused(self):
        root, file, state = self.open(BLOCK, "block.step")
        drafted = self.draft(file, state, {"angle": "2"}, neutral=BLOCK_SIDES[0])
        self.assertFalse(drafted["ok"])
        self.assertIn("cannot be a face it drafts", drafted["error"])
        missing = self.draft(file, state, {"angle": "2"})
        self.assertFalse(missing["ok"])
        self.assertIn("Select the neutral plane", missing["error"])
        steep = self.draft(file, state, {"angle": "90", "neutral": "Top"})
        self.assertFalse(steep["ok"])
        self.assertIn("less than 90 degrees", steep["error"])


class Renaming(Commands):
    """Rename, as SolidWorks' design tree renames a feature: the name kept as the comment at the end
    of the feature's line, a sketch's as its Sketch's own; nothing built, and Undo puts it back."""

    def rename(self, file: str, state: dict, **spec) -> dict:
        return self.service.change({"file": file, "files": state["files"], "rename": spec})

    def test_a_feature_is_named_at_the_end_of_its_line_and_keeps_its_name_through_edit_feature(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        fillet = next(feature for feature in made["features"] if feature["kind"] == "Fillet")
        renamed = self.rename(file, made, feature=fillet["key"], name="  Top  edge round ", title="Fillet1")
        self.assertTrue(renamed["ok"], renamed.get("error"))
        script = root / "block.py"
        self.assertIn(", radius=1)  # Top edge round\n", script.read_text(encoding="utf-8"))
        self.assertEqual(next(feature for feature in renamed["features"] if feature["kind"] == "Fillet")["named"], "Top edge round")
        self.assertEqual((renamed["change"]["kind"], renamed["change"]["build"]), ("rename", False))
        # Edit Feature writes its line again, its name with it.
        spec = {"command": "fillet", "inputs": {"radius": "0.5"}, "replace": {"row": fillet["key"]}}
        edited = self.service.change({"file": file, "command": spec, "files": renamed["files"]})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertIn(", radius=0.5)  # Top edge round\n", script.read_text(encoding="utf-8"))
        # No name gives it back the tree's own; Undo puts the name back.
        cleared = self.rename(file, edited, feature=fillet["key"], name="", title="Top edge round")
        self.assertTrue(cleared["ok"], cleared.get("error"))
        self.assertNotIn("#", script.read_text(encoding="utf-8"))
        undone = self.service.change({"file": file, "splice": cleared["change"]["undo"], "files": cleared["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertIn("  # Top edge round\n", script.read_text(encoding="utf-8"))

    def test_a_sketch_is_renamed_on_its_own_line_and_no_two_share_a_name(self):
        root, file, state = self.open(SKETCHED, "bracket.step")
        renamed = self.rename(file, state, sketch=sketch("Sketch2", 11), name="Handle path", title="Sketch2")
        self.assertTrue(renamed["ok"], renamed.get("error"))
        self.assertIn('    sketch2 = Sketch("Handle path", plane="Front")\n', (root / "bracket.py").read_text(encoding="utf-8"))
        taken = self.rename(file, renamed, sketch=sketch("Sketch3", 15), name="handle path", title="Sketch3")
        self.assertFalse(taken["ok"])
        self.assertIn("Another feature is named handle path", taken["error"])
        unnamed = self.rename(file, renamed, sketch=sketch("Sketch3", 15), name=" ", title="Sketch3")
        self.assertFalse(unnamed["ok"])
        self.assertIn("A sketch needs a name", unnamed["error"])


class Appearances(Commands):
    """Appearance, as SolidWorks' Edit Appearance colors a part: the hex picked written where the
    part's body takes its color, and read back as the color it shows."""

    def paint(self, file: str, state: dict, color: str) -> dict:
        return self.service.change({"file": file, "files": state["files"], "appearance": {"color": color}})

    def test_a_part_is_colored_before_it_is_returned_then_its_color_changed_in_place(self):
        root, file, state = self.open(PLATE, "plate.step")
        self.assertIsNone(state["color"])
        painted = self.paint(file, state, "#b7a1d7")
        self.assertTrue(painted["ok"], painted.get("error"))
        script = root / "plate.py"
        # sRGB hex, as the engine takes a part's color: nothing to import.
        self.assertIn('    plate.label = "plate"\n    plate.color = "#B7A1D7"\n    return plate\n', script.read_text(encoding="utf-8"))
        self.assertNotIn("srgb", script.read_text(encoding="utf-8"))
        self.assertEqual(painted["color"], "#B7A1D7")
        again = self.paint(file, painted, "#C8B4E5")
        self.assertTrue(again["ok"], again.get("error"))
        text = script.read_text(encoding="utf-8")
        self.assertEqual(text.count(".color = "), 1)
        self.assertIn('plate.color = "#C8B4E5"', text)
        self.assertFalse(self.paint(file, again, "lilac")["ok"])

    def test_a_part_returned_outright_is_named_to_be_colored(self):
        root, file, state = self.open(BLOCK, "block.step")
        painted = self.paint(file, state, "#2E3742")
        self.assertTrue(painted["ok"], painted.get("error"))
        self.assertIn('    part = Box(WIDTH, DEPTH, HEIGHT)\n    part.color = "#2E3742"\n    return part\n',
                      (root / "block.py").read_text(encoding="utf-8"))


class Planes(Commands):
    """Plane, as SolidWorks' Reference Geometry offsets one: a line of its own, Plane1 in the tree,
    that a sketch goes on."""

    def test_a_plane_offset_from_the_top_plane_reopens_flipped_and_a_sketch_goes_on_it(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "plane", (), {"reference": "Top", "distance": "10"})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        self.assertIn("    plane1 = Plane.XY.offset(10)\n", script.read_text(encoding="utf-8"))
        plane = next(feature for feature in made["features"] if feature["kind"] == "Plane")
        self.assertEqual(plane["plane"], {"origin": [0, 0, 10], "x": [1, 0, 0], "z": [0, 0, 1]})
        self.assertEqual(plane["edit"], {"command": "plane", "values": {"reference": "Top", "distance": "10", "flip": False},
                                         "keeps": "the Top Plane"})
        spec = {"command": "plane", "inputs": {"reference": "Top", "distance": "4", "flip": True}, "replace": {"row": plane["key"]}}
        edited = self.service.change({"file": file, "command": spec, "files": made["files"]})
        self.assertTrue(edited["ok"], edited.get("error"))
        self.assertIn("    plane1 = Plane.XY.offset(-4)\n", script.read_text(encoding="utf-8"))
        sketched = self.service.change({"file": file, "files": edited["files"], "sketch": {"op": {
            "kind": "new", "plane": {"feature": plane["key"]}, "name": "Sketch1"}}})
        self.assertTrue(sketched["ok"], sketched.get("error"))
        self.assertIn('    sketch1 = Sketch("Sketch1", plane=plane1)\n', script.read_text(encoding="utf-8"))
        self.assertEqual(sketched["sketch"]["state"]["frame"]["origin"], [0, 0, -4])

    def test_a_parameter_added_is_named_at_the_top_and_listed(self):
        root, file, state = self.open(BLOCK, "block.step")
        added = self.service.change({"file": file, "files": state["files"], "parameter": {"name": "wall", "value": "2.5"}})
        self.assertTrue(added["ok"], added.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertIn("from sizes import WIDTH, DEPTH, HEIGHT\nWALL = 2.5\n", text)
        # Listed in Parameters though nothing uses it yet, to be typed over or used by name.
        self.assertIn("WALL", [param["name"] for param in added["params"]])
        derived = self.service.change({"file": file, "files": added["files"], "parameter": {"name": "LIP", "value": "WALL * 2"}})
        self.assertTrue(derived["ok"], derived.get("error"))
        self.assertIn("WALL = 2.5\nLIP = WALL * 2\n", (root / "block.py").read_text(encoding="utf-8"))
        added = derived
        self.assertEqual(added["change"]["kind"], "parameter")
        taken = self.service.change({"file": file, "files": added["files"], "parameter": {"name": "WIDTH", "value": "3"}})
        self.assertFalse(taken["ok"])
        unknown = self.service.change({"file": file, "files": added["files"], "parameter": {"name": "RIM", "value": "GAP * 2"}})
        self.assertIn("no size called GAP", unknown["error"])

    def test_split_makes_two_bodies_and_delete_body_takes_one_out(self):
        root, file, state = self.open(BLOCK, "block.step")
        split = self.command(file, state, "split", (), {"plane": "YZ", "keep": "both"})
        self.assertTrue(split["ok"], split.get("error"))
        script = root / "block.py"
        self.assertIn("part = split(part, bisect_by=Plane.YZ, keep=Keep.BOTH)\n", script.read_text(encoding="utf-8"))
        # Edit Feature reopens it, as SolidWorks' Split does, and keeps one side instead.
        found = lambda reply: next(feature for feature in reply["features"] if feature["kind"] == "Split")  # noqa: E731
        reopen = lambda reply, inputs: self.service.change({"file": file, "files": reply["files"], "command": {  # noqa: E731
            "command": "split", "inputs": inputs, "replace": {"row": found(reply)["key"]}}})
        self.assertEqual(found(split)["edit"]["values"], {"plane": "YZ", "keep": "both"})
        kept = reopen(split, {"plane": "XZ", "keep": "top"})
        self.assertTrue(kept["ok"], kept.get("error"))
        self.assertIn("part = split(part, bisect_by=Plane.XZ, keep=Keep.TOP)\n", script.read_text(encoding="utf-8"))
        split = reopen(kept, {"plane": "YZ", "keep": "both"})
        self.assertTrue(split["ok"], split.get("error"))
        # One body alone is refused: there is nothing to delete it from.
        alone = self.open(BLOCK, "block.step")
        refused = self.command(alone[1], alone[2], "delete_body", [face("f6", (10, 0, 0), 40)])
        self.assertFalse(refused["ok"])
        deleted = self.command(file, split, "delete_body", [face("f6", (10, 0, 0), 40)], {"mode": "delete"})
        self.assertTrue(deleted["ok"], deleted.get("error"))
        self.assertIn("part -= part.solids().sort_by(Axis.X)[-1]  # Delete Body\n", script.read_text(encoding="utf-8"))
        weighed = self.service.change({"file": file, "files": deleted["files"], "mass": {}})
        self.assertEqual(weighed["mass"]["solids"], 1)
        self.assertAlmostEqual(weighed["mass"]["volume"], 400, places=3)

    def test_draft_analysis_classes_the_block_by_its_pull(self):
        root, file, state = self.open(BLOCK, "block.step")
        reply = self.service.change({"file": file, "files": state["files"], "draft_check": {"pull": [0, 0, 1], "angle": 1}})
        self.assertTrue(reply["ok"], reply.get("error"))
        checked = reply["draft_check"]
        # The top faces the pull, the bottom away from it, and the four walls stand square: they need draft.
        self.assertAlmostEqual(checked["areas"]["positive"], 200, places=3)
        self.assertAlmostEqual(checked["areas"]["negative"], 200, places=3)
        self.assertAlmostEqual(checked["areas"]["needs"], 2 * 20 * 4 + 2 * 10 * 4, places=3)
        self.assertEqual(len(checked["positions"]), 9 * len(checked["classes"]))
        # Nothing is written or built: the script is as it was.
        self.assertNotIn("change", reply)

    def test_a_mid_plane_goes_between_two_faces_and_a_plane_normal_to_an_edge_stands_at_its_start(self):
        root, file, state = self.open(BLOCK, "block.step")
        both = [*BLOCK_TOP, face("f2", (0, 0, -2), 200)]
        made = self.command(file, state, "plane", both, {"mode": "mid"})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        self.assertIn(".z_dir.dot(", script.read_text(encoding="utf-8"))
        plane = next(feature for feature in made["features"] if feature["kind"] == "Plane")
        self.assertEqual([round(value, 6) + 0 for value in plane["plane"]["origin"]], [0, 0, 0])
        self.assertEqual(plane["edit"]["values"], {"mode": "mid"})
        # Faces that are not parallel are refused.
        side = face("f5", (10, 0, 0), 40)
        refused = self.command(file, made, "plane", [BLOCK_TOP[0], side], {"mode": "mid"})
        self.assertFalse(refused["ok"])
        normal = self.command(file, made, "plane", [BLOCK_TOP_EDGES[3]], {"mode": "normal", "end": "start"})
        self.assertTrue(normal["ok"], normal.get("error"))
        self.assertIn(".position_at(0), z_dir=", script.read_text(encoding="utf-8"))
        second = next(feature for feature in normal["features"] if feature["kind"] == "Plane" and feature["edit"]["values"].get("mode") == "normal")
        self.assertEqual([abs(round(value, 6)) for value in second["plane"]["z"]], [0, 1, 0])
        self.assertEqual([round(second["plane"]["origin"][i], 6) for i in (0, 2)], [10, 2])
        self.assertEqual(second["edit"]["values"], {"mode": "normal", "end": "start"})

    def test_a_plane_at_an_angle_turns_about_its_own_axis_and_reopens_with_it(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "plane", (), {"reference": "Front", "distance": "0", "angle": "30", "about": "x"})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block.py"
        self.assertIn("    plane1 = Plane.XZ.offset(0).rotated((30, 0, 0))\n", script.read_text(encoding="utf-8"))
        plane = next(feature for feature in made["features"] if feature["kind"] == "Plane")
        # The Front Plane's normal, -Y, turned 30 degrees about its X axis by the right hand.
        self.assertEqual([round(value, 6) + 0 for value in plane["plane"]["z"]], [0, -0.866025, -0.5])
        self.assertEqual({key: plane["edit"]["values"].get(key) for key in ("angle", "about")}, {"angle": "30", "about": "x"})
        row = next(row for row in made["rows"] if row["key"] == plane["key"])
        self.assertIn(("Angle", 30.0, "deg"), [(item["label"], item["value"], item["unit"]) for item in row["inputs"]])
        # About its Y axis instead, then back to square: the turn goes.
        spec = {"command": "plane", "inputs": {"reference": "Front", "distance": "0", "angle": "15", "about": "y"}, "replace": {"row": plane["key"]}}
        turned = self.service.change({"file": file, "command": spec, "files": made["files"]})
        self.assertTrue(turned["ok"], turned.get("error"))
        self.assertIn("plane1 = Plane.XZ.offset(0).rotated((0, 15, 0))\n", script.read_text(encoding="utf-8"))
        spec["inputs"]["angle"] = "0"
        squared = self.service.change({"file": file, "command": spec, "files": turned["files"]})
        self.assertTrue(squared["ok"], squared.get("error"))
        self.assertIn("    plane1 = Plane.XZ.offset(0)\n", script.read_text(encoding="utf-8"))

    def test_a_reference_plane_is_what_another_plane_and_a_mirror_go_from(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "plane", (), {"reference": "Right", "distance": "15"})
        self.assertTrue(made["ok"], made.get("error"))
        more = self.command(file, made, "plane", (), {"reference": "named:plane1", "distance": "5"})
        self.assertTrue(more["ok"], more.get("error"))
        mirrored = self.command(file, more, "mirror", (), {"plane": "named:plane1"})
        self.assertTrue(mirrored["ok"], mirrored.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertIn("    plane2 = plane1.offset(5)\n", text)
        self.assertIn("    part += mirror(part, about=plane1)\n", text)
        edits = {feature["kind"]: feature["edit"]["values"] for feature in mirrored["features"] if feature.get("edit")}
        self.assertEqual(edits["Mirror"], {"plane": "named:plane1"})
        self.assertEqual(next(feature["edit"]["values"]["reference"] for feature in mirrored["features"]
                              if feature["kind"] == "Plane" and feature["name"] == "plane2"), "named:plane1")
        missing = self.command(file, mirrored, "mirror", (), {"plane": "named:plane9"})
        self.assertFalse(missing["ok"])
        self.assertIn("plane9 is not a plane of this part", missing["error"])

    def test_a_draft_keeps_its_size_at_a_reference_plane(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "plane", (), {"reference": "Top", "distance": "2"})
        drafted = self.service.change({"file": file, "files": made["files"], "command": {
            "command": "draft", "selection": BLOCK_SIDES, "inputs": {"angle": "3", "neutral": "named:plane1", "reverse": True}}})
        self.assertTrue(drafted["ok"], drafted.get("error"))
        self.assertRegex((root / "block.py").read_text(encoding="utf-8"), r"part = draft\(part\.faces\(\)[^\n]+, -plane1, 3\)\n")
        draft = next(feature for feature in drafted["features"] if feature["kind"] == "Draft")
        self.assertEqual(draft["edit"]["values"]["neutral"], "named:plane1")

    def test_a_plane_off_a_face_stands_out_of_the_part(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "plane", BLOCK_TOP, {"distance": "3"})
        self.assertTrue(made["ok"], made.get("error"))
        self.assertIn("    plane1 = Plane(part.faces().sort_by(Axis.Z)[-1]).offset(3)\n", (root / "block.py").read_text(encoding="utf-8"))
        plane = next(feature for feature in made["features"] if feature["kind"] == "Plane")
        self.assertEqual((plane["plane"]["origin"], plane["edit"]["values"]["reference"]), ([0, 0, 5], "face"))
        refused = self.command(file, made, "plane", (), {"distance": "3"})
        self.assertFalse(refused["ok"])
        self.assertIn("to offset from", refused["error"])


class Assemblies(Commands):
    """An assembly places its parts: each is modeled on its own, opened from the design tree."""

    def test_interference_detection_finds_two_parts_that_overlap(self):
        root, file, state = self.open(ASSEMBLY, "assemblies/stack.step")
        clear = self.service.change({"file": file, "files": state["files"], "interference": {}})
        self.assertTrue(clear["ok"], clear.get("error"))
        # The pin stands on the base: touching is not interfering.
        self.assertEqual((clear["interference"]["pairs"], clear["interference"]["parts"]), ([], 2))
        pin = root / "parts" / "pin.py"
        pin.write_text(pin.read_text(encoding="utf-8").replace("Pos(0, 0, 5)", "Pos(0, 0, 4)"), encoding="utf-8")
        state = self.service.state(file)
        found = self.service.change({"file": file, "files": state["files"], "interference": {}})
        pairs = found["interference"]["pairs"]
        self.assertEqual([(pair["a"], pair["b"]) for pair in pairs], [("base", "pin")])
        # A millimetre of the pin sunk into the base: pi * 2^2 * 1.
        self.assertAlmostEqual(pairs[0]["volume"], 4 * 3.141592653589793, places=3)
        self.assertTrue(found["interference"]["shown"]["removed"]["triangles"])

    def test_each_part_names_the_model_open_part_opens_and_the_assembly_takes_no_commands(self):
        root, file, state = self.open(ASSEMBLY, "assemblies/stack.step")
        # Each part's document by the id the engine holds it by: a bare @model writes no STEP to open.
        from cadgen.engine.ids import model_id

        self.assertEqual([(c["name"], c["document"], c["step"]) for c in state["components"]],
                         [("base", model_id(root / "parts" / "base.py", "base"), None),
                          ("pin", model_id(root / "parts" / "pin.py", "pin"), None)])
        refused = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertFalse(refused["ok"])


# A base with a hole at x = 5, and a pin floating above it, to be mated.
MATING = {
    "parts/base.py": """
        from build123d import Box, Cylinder, Pos
        from cadgen import model


        @model
        def base():
            return Box(20, 10, 4) - Pos(5, 0, 0) * Cylinder(1.5, 4)
    """,
    "parts/pin.py": """
        from build123d import Cylinder, Pos
        from cadgen import model


        @model
        def pin():
            return Pos(-3, 2, 10) * Cylinder(1.5, 6)
    """,
    "assemblies/stack.py": ASSEMBLY["assemblies/stack.py"],
}
CIRCLE = 2 * math.pi * 1.5


class Mates(Commands):
    """Mate, as SolidWorks' places an assembly's parts: each in its part's `mate` call, solved together each run."""

    def mated(self, file: str, files: dict, mate: dict) -> dict:
        reply = self.service.change({"file": file, "files": files, "mate": mate})
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def box(self, file: str, files: dict) -> list:
        return [[round(value, 6) + 0 for value in corner] for corner in self.service.change({"file": file, "mass": {}, "files": files})["mass"]["box"]]

    def test_insert_components_lists_the_project_parts_and_adds_one_where_it_is_made(self):
        files = {**ASSEMBLY, "fixtures/cap.py": """
            from build123d import Box
            from cadgen import model


            @model
            def cap():
                return Box(8, 8, 2)
        """}
        root, file, state = self.open(files, "assemblies/stack.step")
        script = root / "assemblies" / "stack.py"
        before = script.read_text(encoding="utf-8")
        listed = self.service.change({"file": file, "files": state["files"], "mate": {"list": True}})
        self.assertEqual(sorted(listed["insertable"]), ["fixtures/cap.py", "parts/base.py", "parts/pin.py"])
        reply = self.mated(file, state["files"], {"insert": "fixtures/cap.py"})
        text = script.read_text(encoding="utf-8")
        self.assertIn('sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))\nfrom cap import cap\n', text)
        self.assertIn("children=[base().shape, pin().shape, cap().shape]", text)
        self.assertEqual([component["name"] for component in reply["components"]], ["base", "pin", "cap"])
        self.assertEqual(reply["change"]["words"], "inserted cap")
        # One already in it is not inserted again; the tree lists each part's model once.
        again = self.service.change({"file": file, "files": reply["files"], "mate": {"insert": "parts/pin.py"}})
        self.assertEqual(again["error"], "pin is in this assembly already. Ask the agent for another of it.")
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_text(encoding="utf-8"), before)

    def test_coincident_then_concentric_seat_the_pin_over_the_hole_and_each_comes_out_on_its_own(self):
        root, file, state = self.open(MATING, "assemblies/stack.step")
        top = {"selector": "o1.1.f6", "type": "plane", "center": [-0.183218, 0, 2], "size": 200 - math.pi * 2.25}
        bottom = {"selector": "o1.2.f3", "type": "plane", "center": [-3, 2, 7], "size": math.pi * 2.25}
        reply = self.mated(file, state["files"], {"type": "coincident", "selection": [top, bottom]})
        script = root / "assemblies" / "stack.py"
        text = script.read_text(encoding="utf-8")
        self.assertIn("from cadgen.mates import Coincident, mate\n", text)
        self.assertIn("    base_part = base().shape\n    pin_part = pin().shape\n    mate(pin_part, Coincident(pin_part.faces()", text)
        self.assertIn('base_part.faces().sort_by(Axis.Z)[-1]))\n    return Compound(children=[base_part, pin_part], label="stack")\n', text)
        # Its bottom on the base's top, as far over it as it was: from z = 2 up to 8, x -4.5 to -1.5.
        self.assertEqual(self.box(file, reply["files"]), [[-10, -5, -2], [10, 5, 8]])
        self.assertEqual([(mate["name"], mate["parts"]) for mate in reply["mates"]], [("Coincident1", ["base", "pin"])])
        # Concentric with the hole as well: the two solved together stand the pin on the hole.
        side = {"selector": "o1.2.f1", "type": "cylinder", "center": [-3, 2, 5], "size": 2 * math.pi * 1.5 * 6}
        hole = {"selector": "o1.1.f7", "type": "cylinder", "center": [5, 0, 0], "size": 2 * math.pi * 1.5 * 4}
        both = self.mated(file, reply["files"], {"type": "concentric", "selection": [hole, side]})
        text = script.read_text(encoding="utf-8")
        self.assertIn("from cadgen.mates import Coincident, Concentric, mate\n", text)
        self.assertIn("    mate(pin_part,\n         Coincident(", text)
        self.assertIn("\n         Concentric(pin_part.faces()", text)
        self.assertEqual([mate["name"] for mate in both["mates"]], ["Coincident1", "Concentric1"])
        self.assertEqual(self.box(file, both["files"]), [[-10, -5, -2], [10, 5, 8]])
        # Taken out, Coincident leaves Concentric: the pin keeps to the hole's axis where it was along it.
        gone = self.mated(file, both["files"], {"delete": "Coincident1"})
        self.assertEqual([mate["name"] for mate in gone["mates"]], ["Concentric1"])
        self.assertNotIn("Coincident(", script.read_text(encoding="utf-8").split("import", 3)[-1].split("def stack", 1)[-1])

    def test_concentric_circular_edges_seat_the_pin_in_the_hole_and_flat_picks_are_refused(self):
        root, file, state = self.open(MATING, "assemblies/stack.step")
        hole = {"selector": "o1.1.e13", "type": "circle", "center": [5, 0, -2], "size": CIRCLE}
        foot = {"selector": "o1.2.e3", "type": "circle", "center": [-3, 2, 7], "size": CIRCLE}
        reply = self.mated(file, state["files"], {"type": "concentric", "selection": [hole, foot]})
        self.assertIn("mate(pin_part, Concentric(pin_part.edges()", (root / "assemblies" / "stack.py").read_text(encoding="utf-8"))
        # Its foot on the hole's bottom edge, standing up through it: x 3.5 to 6.5, z -2 to 4.
        self.assertEqual(self.box(file, reply["files"]), [[-10, -5, -2], [10, 5, 4]])
        flat = {"selector": "o1.1.f6", "type": "plane", "center": [-0.183218, 0, 2], "size": 200 - math.pi * 2.25}
        seated = {**foot, "center": [5, 0, -2]}
        refused = self.service.change({"file": file, "files": reply["files"], "mate": {"type": "concentric", "selection": [flat, seated]}})
        self.assertFalse(refused["ok"])
        self.assertIn("round faces or circular edges", refused["error"])

    def test_mates_that_cannot_all_hold_are_refused_and_the_parallel_angle_and_distance_mates_solve(self):
        import build123d as B

        from cadgen.mates import Angle, Coincident, Distance, MateError, Parallel, Perpendicular, mate

        base = B.Box(20, 10, 4)
        top = base.faces().sort_by(B.Axis.Z)[-1]
        # A block turned 20 degrees made Parallel side to side turns square, where it is.
        block = B.Pos(0, 0, 10) * B.Rot(0, 0, 20) * B.Box(4, 2, 2)
        sides = lambda part: part.faces().filter_by(lambda face: abs(B.Plane(face).z_dir.Z) < 1e-6).sort_by(B.Axis.X)  # noqa: E731
        mate(block, Parallel(sides(block)[-1], base.faces().sort_by(B.Axis.X)[-1]))
        self.assertAlmostEqual(B.Plane(sides(block)[-1]).z_dir.X, 1, places=6)
        self.assertAlmostEqual(block.bounding_box().center().Z, 10, places=6)
        # Its bottom 3 above the base's top, then at 30 degrees to it.
        mate(block, Distance(block.faces().sort_by(B.Axis.Z)[0], top, 3))
        self.assertAlmostEqual(block.bounding_box().min.Z, 5, places=6)
        mate(block, Angle(block.faces().sort_by(B.Axis.Z)[0], top, 150))
        self.assertAlmostEqual(abs(B.Plane(block.faces().sort_by(B.Axis.Z)[0]).z_dir.Z), math.cos(math.radians(30)), places=6)
        # Coincident and Perpendicular between the same two faces cannot both hold.
        pin = B.Pos(0, 0, 10) * B.Cylinder(1, 4)
        foot = pin.faces().sort_by(B.Axis.Z)[0]
        with self.assertRaises(MateError):
            mate(pin, Coincident(foot, top), Perpendicular(foot, top))


class Comparing(Commands):
    """Compare, as SolidWorks' Compare Geometry: what the part gained and lost since a version edit mode read."""

    def test_compare_lists_the_versions_read_and_shows_what_the_part_lost_since_one(self):
        root, file, state = self.open(BLOCK, "block.step")
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES[:1], {"radius": "1"})
        self.assertTrue(made["ok"], made.get("error"))
        listed = self.service.change({"file": file, "files": made["files"], "compare": {}})
        self.assertTrue(listed["ok"], listed.get("error"))
        versions = listed["compare"]["versions"]
        self.assertEqual([version["changed"] for version in versions], [["block.py"]])
        shown = self.service.change({"file": file, "files": made["files"], "compare": {"version": versions[0]["id"]}})["compare"]
        # A 1 mm round along a 20 mm edge takes away (1 - pi/4) square mm all along it, and adds nothing.
        self.assertAlmostEqual(shown["removedVolume"], 20 * (1 - math.pi / 4), places=3)
        self.assertEqual((shown["addedVolume"], shown["added"]), (0, None))
        self.assertTrue(shown["removed"]["triangles"])


class Drawings(Commands):
    """Make Drawing, as SolidWorks' Make Drawing from Part, and the Drawing panel's sheet: a drawing
    script beside the part, run to its PDF."""

    def test_a_model_parts_drawing_calls_its_model_and_is_found_by_it(self):
        from cadgen.edit import drawings

        root = project(BLOCK)
        self.addCleanup(shutil.rmtree, root, True)
        drawing = root / "block_drawing.py"
        text = drawings.template("block", root / "block.py", drawing)
        # Its document, by the model's call, as 0.8 composes one: no STEP needs to be on disk.
        self.assertIn("from block import block\n", text)
        self.assertIn("    part = block().shape\n", text)
        drawing.write_text(text, encoding="utf-8")
        self.assertEqual(drawings.find(root, root / "block.py"), drawing)
        self.assertEqual(drawings.read(text)["out"], "block_drawing.pdf")

    def test_make_drawing_writes_a_script_beside_the_part_that_draws_it_and_its_sheet_changes(self):
        import build123d as B

        root, file, state = self.open(BLOCK, "block.step")
        B.export_step(B.Box(20, 10, 4), str(root / "block.step"))
        made = self.service.change({"file": file, "files": state["files"], "drawing": {"make": True}})
        self.assertTrue(made["ok"], made.get("error"))
        script = root / "block_drawing.py"
        text = script.read_text(encoding="utf-8")
        # The STEP the viewer shows is a file here, so the drawing reads it.
        self.assertIn('    part = read_step(Path(__file__).parent / "block.step")\n', text)
        self.assertIn('    sheet = Sheet("A3", title="BLOCK", part_number="BLOCK", revision="A")\n', text)
        self.assertIn("    top, front, right, iso = sheet.three_views(part, iso=True)\n", text)
        self.assertTrue((root / "block_drawing.pdf").exists())
        self.assertEqual({key: made["drawing"][key] for key in ("script", "pdf", "drawn", "size", "scale", "iso", "revision")},
                         {"script": "block_drawing.py", "pdf": "block_drawing.pdf", "drawn": True, "size": "A3", "scale": "1:1", "iso": True,
                          "revision": "A"})
        # Its sheet: A4 at 1:2, revision B, without the isometric.
        changed = self.service.change({"file": file, "files": state["files"], "drawing": {"sheet": {"size": "A4", "scale": "1:2", "revision": "B",
                                                                                                   "iso": False}}})
        self.assertTrue(changed["ok"], changed.get("error"))
        text = script.read_text(encoding="utf-8")
        self.assertIn('    sheet = Sheet("A4", title="BLOCK", part_number="BLOCK", revision="B", scale=0.5)\n', text)
        self.assertIn("    top, front, right = sheet.three_views(part)\n", text)
        self.assertIn("size A4, scale 1:2, revision B, the isometric taken off", changed["change"]["words"])
        # The part's state names its drawing; a second one is refused.
        self.assertEqual(self.service.state(file)["drawing"]["revision"], "B")
        again = self.service.change({"file": file, "files": state["files"], "drawing": {"make": True}})
        self.assertFalse(again["ok"])
        self.assertIn("has a drawing already", again["error"])

# A part made on a STEP brought in, as another CAD tool imports one: its script reads it, and models on it.
IMPORTED = {
    "lid.py": """
        from pathlib import Path

        from cadgen import model, read_step


        @model
        def lid():
            part = read_step(Path(__file__).parent / "imported" / "bracket.step")
            return part
    """,
}


def _bracket():
    """The imported bracket: a 40 x 20 x 10 block, its upright corners rounded 3, a 6 mm hole through it at x 5."""
    import build123d as bd

    return bd.fillet(bd.Box(40, 20, 10).edges().filter_by(bd.Axis.Z), radius=3) - bd.Pos(5, 0, 0) * bd.Cylinder(3, 20)


def _picked(shape, face) -> dict:
    """A face as the viewer reads it: its kind, centre and area."""
    import build123d as bd

    center = face.center(bd.CenterOf.MASS)
    number = next(n for n, each in enumerate(shape.faces(), 1) if each.is_same(face))
    return {"selector": f"f{number}", "type": face.geom_type.name.lower(), "center": [center.X, center.Y, center.Z], "size": face.area}


class ImportedBodies(Commands):
    """An imported STEP, as SolidWorks, Fusion and NX hold one: one body with no history, modeled on by
    later features and edited directly (Offset Region, Delete Face)."""

    def open_imported(self):
        import build123d as bd

        root = project(IMPORTED)
        self.addCleanup(shutil.rmtree, root, True)
        (root / "imported").mkdir()
        bd.export_step(_bracket(), str(root / "imported" / "bracket.step"))
        file = str(root / "lid.step")
        state = self.service.state(file)
        self.assertTrue(state["ok"], state.get("error"))
        return root, file, state

    def mass(self, file: str, files: dict) -> float:
        return self.service.change({"file": file, "mass": {}, "files": files})["mass"]["volume"]

    def test_an_imported_step_is_one_row_named_by_its_file_with_nothing_to_open(self):
        _, _, state = self.open_imported()
        self.assertEqual([(feature["kind"], feature.get("named"), feature.get("edit")) for feature in state["features"]],
                         [("Imported", "bracket.step", None)])

    def test_features_go_on_an_imported_body_as_on_any_other(self):
        import build123d as bd

        root, file, state = self.open_imported()
        bracket = _bracket()
        top = bracket.faces().sort_by(bd.Axis.Z)[-1]
        reply = self.command(file, state, "hole", [_picked(bracket, top)], {"diameter": "2", "depth": "3", "x": "-10"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual([feature["kind"] for feature in reply["features"]], ["Imported", "Hole"])
        self.assertEqual(reply["features"][-1]["edit"]["command"], "hole")
        # A file that reached build123d nowhere imports it as 0.8 writes it, by its module.
        text = (root / "lid.py").read_text(encoding="utf-8")
        self.assertIn("\nimport build123d as bd\n", text)
        self.assertNotIn("from cadgen import build123d", text)

    def test_offset_region_pulls_a_face_out_and_reopens_with_its_distance(self):
        import build123d as bd

        root, file, state = self.open_imported()
        bracket = _bracket()
        top = bracket.faces().sort_by(bd.Axis.Z)[-1]
        before = self.mass(file, state["files"])
        reply = self.command(file, state, "offset_face", [_picked(bracket, top)], {"distance": "2"})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (root / "lid.py").read_text(encoding="utf-8")
        self.assertIn("from cadgen.direct import offset_faces\n", text)
        # The file reached no build123d before: the selector's names come in through `bd`.
        self.assertIn("    part = offset_faces(part, part.faces().group_by(bd.Axis.Z)[-1], distance=2)\n", text)
        # 10 tall made 12: a fifth more.
        self.assertAlmostEqual(self.mass(file, reply["files"]), before * 1.2, places=3)
        offset = reply["features"][-1]
        self.assertEqual((offset["kind"], offset["edit"]["command"]), ("Offset Face", "offset_face"))
        self.assertEqual({key: offset["edit"]["values"][key] for key in ("distance", "reverse")}, {"distance": "2", "reverse": False})
        # Reopened and reversed: pushed in 1 instead.
        again = self.service.change({"file": file, "files": reply["files"], "command": {
            "command": "offset_face", "inputs": {"distance": "1", "reverse": True}, "selection": [], "replace": {"row": offset["key"]}}})
        self.assertTrue(again["ok"], again.get("error"))
        self.assertIn("distance=-1)\n", (root / "lid.py").read_text(encoding="utf-8"))
        self.assertAlmostEqual(self.mass(file, again["files"]), before * 0.9, places=3)

    def test_delete_face_takes_the_hole_out_and_a_push_the_kernel_cannot_make_is_refused(self):
        import build123d as bd

        root, file, state = self.open_imported()
        bracket = _bracket()
        hole = bracket.faces().filter_by(bd.GeomType.CYLINDER).sort_by(bd.SortBy.AREA)[-1]
        reply = self.command(file, state, "delete_face", [_picked(bracket, hole)])
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    part = delete_faces(part, ", (root / "lid.py").read_text(encoding="utf-8"))
        self.assertAlmostEqual(self.mass(file, reply["files"]), bracket.volume + math.pi * 9 * 10, places=2)
        self.assertEqual(reply["features"][-1]["kind"], "Delete Face")
        # The rounded end pushed in deeper than its rounds: no valid solid, so nothing is written.
        before = (root / "lid.py").read_bytes()
        end = bracket.faces().sort_by(bd.Axis.X)[-1]
        refused = self.command(file, reply, "offset_face", [_picked(bracket, end)], {"distance": "4", "reverse": True})
        self.assertFalse(refused["ok"])
        self.assertEqual((root / "lid.py").read_bytes(), before)

    def test_a_step_with_no_script_is_made_a_part_beside_it_and_the_step_brought_in_is_kept(self):
        import build123d as bd

        root = project({}).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        source = root / "bracket.step"
        bd.export_step(_bracket(), str(source))
        before = source.read_bytes()
        self.assertEqual(self.service.editable(str(source)), {"ok": True, "editable": False, "importable": True})
        made = self.service.change({"file": str(source), "adopt": {}})
        self.assertTrue(made["ok"], made.get("error"))
        # A model's script beside it, opened by its document's id.
        self.assertEqual(made["script"], str(root / "bracket_part.py"))
        self.assertEqual(made["part"], edit.document_of(root / "bracket_part.py"))
        self.assertIn("@model\ndef bracket_part():\n", (root / "bracket_part.py").read_text(encoding="utf-8"))
        # The part opens on the imported body, one row with nothing under it, and the STEP brought in is as it was.
        state = self.service.state(made["script"])
        self.assertTrue(state["ok"], state.get("error"))
        self.assertEqual(state["document"], made["part"])
        self.assertEqual([(feature["kind"], feature.get("named")) for feature in state["features"]], [("Imported", "bracket.step")])
        self.assertEqual(source.read_bytes(), before)
        # Opened again, the STEP names the part made of it; made a part again, it is another one.
        self.assertEqual(self.service.editable(str(source))["part"], made["part"])
        self.assertEqual(self.service.change({"file": str(source), "adopt": {}})["script"], str(root / "bracket_part2.py"))
        # A part's own script is no import.
        self.assertFalse(self.service.change({"file": made["script"], "adopt": {}})["ok"])


# A part as agents write one: Blocks and Cylinders placed with `Pos`, a size from `sizes.py`, a fillet
# ending in `.clean()`, and a joiner made in a helper's file.
PRIMITIVES = {
    "sizes.py": """
        POCKET = 10
    """,
    "geometry.py": """
        import build123d as bd


        def joiner():
            body = bd.Box(40, 18, 4)
            for x in [-10, 10]:
                body -= bd.Pos(x, 0, 0) * bd.Cylinder(2.2, 6)
            return body
    """,
    "cradle.py": """
        import build123d as bd
        from cadgen import model
        from sizes import POCKET


        @model
        def cradle():
            body = bd.Box(40, 20, 10)
            body += bd.Pos(10, 0, 8) * bd.Box(4, 4, 6)
            body -= bd.Pos(0, 0, 5) * bd.Box(POCKET, 6, 6)
            body = bd.fillet(body.edges().filter_by(bd.Axis.Z), radius=1).clean()
            return body
    """,
    "joiner_part.py": """
        from cadgen import model
        from geometry import joiner


        @model
        def joiner_part():
            return joiner()
    """,
}


class EditingSizes(Commands):
    """Edit Parameters on what no command writes: its sizes typed at once, undone at once."""

    def sizes(self, file, state, feature, values):
        inputs = {each["label"]: index for index, each in enumerate(next(row for row in state["rows"] if row["key"] == feature["key"])["inputs"])}
        return self.service.change({"file": file, "files": state["files"], "sizes": {
            "row": feature["edit"]["row"], "values": [{"index": inputs[label], "text": text} for label, text in values.items()]}})

    def test_a_placed_block_opens_its_sizes_and_place_and_takes_them_in_one_change(self):
        root, file, state = self.open(PRIMITIVES, "cradle.step")
        kinds = [(feature["kind"], feature["edit"]["command"]) for feature in state["features"]]
        self.assertEqual(kinds, [("Boss-Extrude", "sizes"), ("Boss-Extrude", "sizes"), ("Cut-Extrude", "sizes"), ("Fillet", "fillet")])
        boss = state["features"][1]
        before = (root / "cradle.py").read_text(encoding="utf-8")
        reply = self.sizes(file, state, boss, {"Length": "6", "X": "12"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    body += bd.Pos(12, 0, 8) * bd.Box(6, 4, 6)\n", (root / "cradle.py").read_text(encoding="utf-8"))
        self.assertEqual(reply["change"]["kind"], "sizes")
        # One Undo puts both back.
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual((root / "cradle.py").read_text(encoding="utf-8"), before)

    def test_edit_parameters_previews_what_its_sizes_add_and_writes_nothing(self):
        root, file, state = self.open(PRIMITIVES, "cradle.step")
        boss = state["features"][1]
        before = (root / "cradle.py").read_bytes()
        inputs = {each["label"]: index for index, each in enumerate(next(row for row in state["rows"] if row["key"] == boss["key"])["inputs"])}
        reply = self.service.change({"file": file, "files": state["files"], "preview_sizes": {
            "row": boss["edit"]["row"], "values": [{"index": inputs["Height"], "text": "10"}]}})
        self.assertTrue(reply["ok"], reply.get("error"))
        # Taller by 4: material added on top, none taken away, and the file as it was.
        self.assertIsNotNone(reply["preview"]["added"])
        self.assertIsNone(reply["preview"]["removed"])
        self.assertEqual((root / "cradle.py").read_bytes(), before)
        # Opened with nothing typed: the boss as it is, and the first block all of the part.
        for feature in state["features"][:2]:
            shown = self.service.change({"file": file, "files": state["files"], "preview_sizes": {"row": feature["edit"]["row"], "values": []}})
            self.assertIsNotNone(shown["preview"]["added"], feature["key"])
        pocket = self.service.change({"file": file, "files": state["files"], "preview_sizes": {"row": state["features"][2]["edit"]["row"], "values": []}})
        self.assertIsNotNone(pocket["preview"]["removed"])

    def test_a_size_named_in_another_file_changes_there_and_undoes_with_the_rest(self):
        root, file, state = self.open(PRIMITIVES, "cradle.step")
        pocket = state["features"][2]
        reply = self.sizes(file, state, pocket, {"Length": "12", "Width": "8"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("POCKET = 12\n", (root / "sizes.py").read_text(encoding="utf-8"))
        self.assertIn("bd.Box(POCKET, 8, 6)", (root / "cradle.py").read_text(encoding="utf-8"))
        undone = self.service.change({"file": file, "splice": reply["change"]["undo"], "files": reply["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertIn("POCKET = 10\n", (root / "sizes.py").read_text(encoding="utf-8"))
        self.assertIn("bd.Box(POCKET, 6, 6)", (root / "cradle.py").read_text(encoding="utf-8"))

    def test_a_feature_made_in_a_helpers_file_is_edited_there(self):
        root, file, state = self.open(PRIMITIVES, "joiner_part.step")
        hole = next(feature for feature in state["features"] if feature["kind"] == "Hole")
        self.assertEqual(hole["edit"]["command"], "sizes")
        reply = self.sizes(file, state, hole, {"Diameter": "5"})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("bd.Cylinder(2.5, 6)", (root / "geometry.py").read_text(encoding="utf-8"))

    def test_a_fillet_ending_in_clean_reopens_and_keeps_it(self):
        root, file, state = self.open(PRIMITIVES, "cradle.step")
        fillet = state["features"][-1]
        self.assertEqual(fillet["edit"]["values"], {"radius": "1"})
        reply = self.service.change({"file": file, "files": state["files"], "command": {
            "command": "fillet", "inputs": {"radius": "0.5"}, "selection": [], "replace": {"row": fillet["key"]}}})
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertIn("    body = bd.fillet(body.edges().filter_by(bd.Axis.Z), radius=0.5).clean()\n", (root / "cradle.py").read_text(encoding="utf-8"))


class EditingMaterial(Commands):
    """Edit Material, as SolidWorks keeps a part's material in the part: one line of its body, the
    engine's (``part.material = resolve("<name>")``), read by Mass Properties."""

    def test_a_parts_material_is_written_on_its_body_weighs_it_and_undoes(self):
        root, file, state = self.open(BLOCK, "block.step")
        self.assertEqual(state["material"], "")
        before = (root / "block.py").read_text(encoding="utf-8")
        # Named by any name bd_materials' catalogue resolves.
        made = self.service.change({"file": file, "files": state["files"], "set_material": {"name": "PLA"}})
        self.assertTrue(made["ok"], made.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertIn("    part = Box(WIDTH, DEPTH, HEIGHT)\n    part.material = resolve(\"PLA_GENERIC\")\n    return part\n", text)
        self.assertIn("from bd_materials import resolve\n", text)
        self.assertEqual((made["material"], made["materialName"]), ("PLA_GENERIC", "PLA_GENERIC"))
        weighed = self.service.change({"file": file, "files": made["files"], "mass": {}})["mass"]
        self.assertEqual(weighed["material"], "PLA_GENERIC")
        self.assertIn({"key": "Alu_G6061_T6", "name": "Alu_G6061_T6", "density": 2.7, "fea": True}, weighed["materials"])
        # One the catalogue gives no stiffness for weighs the part, and says the Toolbox's analyses cannot use it.
        self.assertFalse(next(each for each in weighed["materials"] if each["key"] == "Hardwood_BIRCH")["fea"])
        # Changed in place, refused for a name nobody knows, and undone to what it was.
        again = self.service.change({"file": file, "files": made["files"], "set_material": {"name": "aluminum"}})
        self.assertTrue(again["ok"], again.get("error"))
        text = (root / "block.py").read_text(encoding="utf-8")
        self.assertEqual((text.count(".material ="), text.count('resolve("Alu_G6061_T6")')), (1, 1))
        refused = self.service.change({"file": file, "files": again["files"], "set_material": {"name": "unobtainium"}})
        self.assertFalse(refused["ok"])
        undone = self.service.change({"file": file, "files": again["files"], "splice": again["change"]["undo"]})
        self.service.change({"file": file, "files": undone["files"], "splice": made["change"]["undo"]})
        self.assertEqual((root / "block.py").read_text(encoding="utf-8"), before)

    def test_a_0_7_material_line_still_reads_and_is_taken_out(self):
        root, file, state = self.open({**BLOCK, "block.py": BLOCK["block.py"].replace(
            "        @model", "        MATERIAL = 'aluminum'\n\n\n        @model")}, "block.step")
        self.assertEqual((state["material"], state["materialName"]), ("Alu_G6061_T6", "Alu_G6061_T6"))
        removed = self.service.change({"file": file, "files": state["files"], "set_material": {"name": ""}})
        self.assertTrue(removed["ok"], removed.get("error"))
        self.assertNotIn("MATERIAL", (root / "block.py").read_text(encoding="utf-8"))


class TangentAndLock(unittest.TestCase):
    """SolidWorks' Tangent and Lock mates, as the solver holds them."""

    def test_a_cylinder_rolls_onto_a_face_and_a_locked_part_stays_put(self):
        import build123d as bd
        from cadgen.mates import Lock, Tangent, mate

        floor = bd.Box(40, 40, 4)  # top at z 2
        roller = bd.Pos(3, 1, 20) * bd.Rot(0, 90, 0) * bd.Cylinder(5, 10)  # axis along X, radius 5
        side = roller.faces().filter_by(bd.GeomType.CYLINDER)[0]
        mate(roller, Tangent(side, floor.faces().sort_by(bd.Axis.Z)[-1]))
        # Its axis 5 above the floor's top, still along X: it sits on the floor.
        self.assertAlmostEqual(roller.bounding_box().min.Z, 2, places=5)
        self.assertAlmostEqual(roller.bounding_box().size.X, 10, places=5)
        # Two cylinders side by side: their axes the two radii apart.
        other = bd.Pos(0, 30, 0) * bd.Cylinder(3, 8)
        post = bd.Pos(0, 0, 0) * bd.Cylinder(2, 8)
        mate(post, Tangent(post.faces().filter_by(bd.GeomType.CYLINDER)[0], other.faces().filter_by(bd.GeomType.CYLINDER)[0]))
        gap = (post.bounding_box().center() - other.bounding_box().center())
        self.assertAlmostEqual(math.hypot(gap.X, gap.Y), 5, places=5)
        # Locked, a part is held where its script puts it whatever its other mates say.
        held = bd.Pos(7, 7, 7) * bd.Box(2, 2, 2)
        before = held.bounding_box().center()
        mate(held, Lock(held.faces()[0], floor.faces()[0]))
        self.assertAlmostEqual((held.bounding_box().center() - before).length, 0, places=6)
