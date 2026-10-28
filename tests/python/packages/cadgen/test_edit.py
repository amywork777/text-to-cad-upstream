"""Edit mode (``cadgen.edit``): a part script read as a design, and one number of it changed.

The tracer runs in a process of its own, as the viewer's server runs it, so these drive the edit
service end to end on a small part in a fresh folder. Builds are not started here: what a change
would build is checked through ``dependents``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

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

PLATE = {
    "sizes.py": """
        WIDTH = 20
        THICKNESS = 2.50
    """,
    "plate.py": """
        from build123d import Box
        from cadgen import model
        from sizes import WIDTH, THICKNESS

        @model
        def plate():
            return Box(WIDTH, 10, THICKNESS)
    """,
    "bracket.py": """
        from build123d import Box
        from cadgen import model

        @model
        def bracket():
            return Box(5, 5, 5)
    """,
}


# An assembly in a folder of its own, placing parts it imports from beside it. Its module names are
# the plate's: a part another trace left loaded must not stand in for a project's own.
STACK = {
    "parts/sizes.py": """
        WIDTH = 20
    """,
    "parts/plate.py": """
        from build123d import Box
        from cadgen import model
        from sizes import WIDTH

        @model
        def plate():
            return Box(WIDTH, 10, 2)
    """,
    "parts/pin.py": """
        from build123d import Cylinder, Pos
        from cadgen import model

        @model
        def pin():
            return Pos(0, 0, 4) * Cylinder(2, 6)
    """,
    "assemblies/stack.py": """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "parts"))
        from build123d import Compound
        from cadgen import model
        from pin import pin
        from plate import plate

        @model
        def stack():
            return Compound(children=[plate().shape, pin().shape], label="stack")
    """,
}


def project(files: dict[str, str], hidden: bool = False, git: bool = True) -> Path:
    # Studio keeps its projects in a hidden state folder; edit mode must still read them.
    base = Path(tempfile.mkdtemp(prefix="cadgen-edit-"))
    root = base / ".studio" / "plate" if hidden else base
    root.mkdir(parents=True, exist_ok=True)
    if git:
        (root / ".git").mkdir()
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def studio_records(folder: Path, units: str) -> Path:
    """Studio's records folder, with one project listing ``folder``."""
    records = Path(tempfile.mkdtemp(prefix="cadgen-studio-"))
    (records / "stack").mkdir()
    record = {"studio": 1, "name": "Stack", "brief": {"units": units}, "folders": [{"path": str(folder)}]}
    (records / "stack" / "project.json").write_text(json.dumps(record), encoding="utf-8")
    return records


class NumbersAsWritten(unittest.TestCase):
    def test_a_new_value_is_written_the_way_the_old_one_was(self):
        # The tracer's own helpers, in its process: importing it here would patch build123d.
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(PLATE)
        self.addCleanup(shutil.rmtree, root, True)
        file = str(root / "plate.step")
        state = service.state(file)
        thickness = next(p for p in state["params"] if p["name"] == "THICKNESS")
        changed = service.change({"file": file, "literal": thickness["id"], "text": "3", "files": state["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("THICKNESS = 3.00\n", (root / "sizes.py").read_text(encoding="utf-8"))
        self.assertEqual((changed["change"]["from"], changed["change"]["to"]), ("2.50", "3.00"))


class EditService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def setUp(self):
        self.root = project(PLATE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.file = str(self.root / "plate.step")

    def test_the_part_reads_as_its_sizes_history_and_dimensions(self):
        state = self.service.state(self.file)
        self.assertTrue(state["ok"], state.get("error"))
        self.assertEqual([(p["name"], p["text"]) for p in state["params"]], [("WIDTH", "20"), ("THICKNESS", "2.50")])
        self.assertEqual([row["kind"] for row in state["rows"]], ["Box"])
        length = next(d for d in state["dimensions"] if d["formula"] == "WIDTH")
        self.assertEqual((length["name"], length["display"]), ("Length", "20"))
        self.assertIsNone(state.get("mesh"))

    def test_unchanged_files_are_not_read_again(self):
        state = self.service.state(self.file)
        self.assertTrue(self.service.state(self.file, state["files"])["unchanged"])
        (self.root / "sizes.py").write_text("WIDTH = 22\nTHICKNESS = 2.50\n", encoding="utf-8")
        self.assertNotIn("unchanged", self.service.state(self.file, state["files"]))

    def test_a_dimension_changes_the_size_behind_it(self):
        state = self.service.state(self.file)
        length = next(d for d in state["dimensions"] if d["formula"] == "WIDTH")
        changed = self.service.change({"file": self.file, "dimension": length["id"], "text": "25", "files": state["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("WIDTH = 25\n", (self.root / "sizes.py").read_text(encoding="utf-8"))

    def test_a_change_is_undone_by_writing_its_number_back(self):
        state = self.service.state(self.file)
        width = next(p for p in state["params"] if p["name"] == "WIDTH")
        changed = self.service.change({"file": self.file, "literal": width["id"], "text": "24", "files": state["files"]})
        undone = self.service.change({"file": self.file, "literal": changed["change"]["literal"], "text": changed["change"]["from"],
                                      "files": changed["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertIn("WIDTH = 20\n", (self.root / "sizes.py").read_text(encoding="utf-8"))

    def test_a_file_changed_since_it_was_read_is_refused(self):
        state = self.service.state(self.file)
        width = next(p for p in state["params"] if p["name"] == "WIDTH")
        sizes = self.root / "sizes.py"
        sizes.write_text(sizes.read_text(encoding="utf-8").replace("WIDTH = 20", "WIDTH = 22"), encoding="utf-8")
        refused = self.service.change({"file": self.file, "literal": width["id"], "text": "30", "files": state["files"]})
        self.assertFalse(refused["ok"])
        self.assertIn("WIDTH = 22", sizes.read_text(encoding="utf-8"))

    def test_a_project_in_a_hidden_folder(self):
        root = project(PLATE, hidden=True)
        self.addCleanup(shutil.rmtree, root.parent.parent, True)
        state = self.service.state(str(root / "plate.py"))
        self.assertEqual([p["name"] for p in state["params"]], ["WIDTH", "THICKNESS"])

    def test_a_folder_a_studio_project_lists_is_where_the_project_starts(self):
        # A copy, or a folder added from elsewhere, has no git repository of its own.
        root = project(STACK, hidden=True, git=False)
        self.addCleanup(shutil.rmtree, root.parent.parent, True)
        records = studio_records(root, "in")
        self.addCleanup(shutil.rmtree, records, True)
        with mock.patch.dict(os.environ, {"STUDIO_PROJECTS_DIR": str(records)}):
            state = self.service.state(str(root / "assemblies" / "stack.step"))
        self.assertTrue(state["ok"], state.get("error"))
        self.assertEqual(Path(state["root"]), root.resolve())
        self.assertEqual([c["name"] for c in state["components"]], ["plate", "pin"])
        self.assertIn("WIDTH", [p["name"] for p in state["params"]])
        # The project's brief names its units; a part read on its own would guess millimetres.
        self.assertEqual(state["units"], "in")

    def test_a_model_built_outside_the_folder_read_says_why(self):
        root = project(STACK, hidden=True, git=False)
        self.addCleanup(shutil.rmtree, root.parent.parent, True)
        with mock.patch.dict(os.environ, {"STUDIO_PROJECTS_DIR": str(root / "no-records")}):
            state = self.service.state(str(root / "assemblies" / "stack.step"))
        self.assertFalse(state["ok"])
        self.assertEqual(state["reason"], "outside")
        self.assertIn("read only the assemblies folder", state["error"])
        self.assertIn("built in the parts folder", state["error"])

    def test_a_model_without_a_script_is_not_edited(self):
        self.assertEqual(self.service.state(str(self.root / "other.step"))["reason"], "no-script")
        self.assertEqual(self.service.state("relative/plate.step")["reason"], "no-script")


TRAY = {
    "tray.py": """
        from build123d import Axis, Pos, Rectangle, RectangleRounded, extrude, fillet
        from cadgen import model

        LENGTH = 70
        WIDTH = 26
        WALL = 1.5
        FLOOR = 1.5
        HEIGHT = 12

        @model
        def tray():
            outer = extrude(RectangleRounded(LENGTH, WIDTH, 6), amount=HEIGHT)
            outer = fillet(outer.edges().group_by(Axis.Z)[0], radius=0.6)
            cavity = Pos(0, 0, FLOOR) * extrude(Rectangle(LENGTH - 2*WALL, WIDTH - 2*WALL), amount=HEIGHT)
            return outer - cavity
    """,
}


# A part whose fillet is one statement written over several lines, as an agent often writes one.
SPREAD = {
    "spread.py": """
        from build123d import Axis, Box, Cylinder, Pos, fillet
        from cadgen import model

        @model
        def spread():
            base = Box(40, 20, 5)
            base = fillet(
                base.edges().filter_by(Axis.Z),
                radius=2,
            )

            base -= Pos(10, 0) * Cylinder(1.6, 5)
            return base
    """,
}


# A part made in a builder's `with` block, its cut written over five lines; and holes drilled in a loop.
BUILT = {
    "built.py": """
        from build123d import Box, BuildPart, Cylinder, Mode
        from cadgen import model

        @model
        def built():
            with BuildPart() as part:
                Box(40, 20, 5)
                Cylinder(
                    3,
                    5,
                    mode=Mode.SUBTRACT,
                )
            return part.part
    """,
    "looped.py": """
        from build123d import Box, Cylinder, Pos
        from cadgen import model

        @model
        def looped():
            base = Box(40, 20, 5)
            for x in (-10, 10):
                base -= Pos(x, 0) * Cylinder(
                    1.6, 5)
            return base
    """,
}


class FeatureTree(unittest.TestCase):
    def test_the_history_reads_as_a_cad_tree_with_sketches_under_their_features(self):
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(TRAY)
        self.addCleanup(shutil.rmtree, root, True)
        state = service.state(str(root / "tray.step"))
        self.assertTrue(state["ok"], state.get("error"))
        features = state["features"]
        # The cavity's extrude and the line that cuts it are one Cut-Extrude, its rectangle its sketch.
        self.assertEqual([(f["kind"], f["name"]) for f in features],
                         [("Boss-Extrude", "outer"), ("Fillet", "outer"), ("Cut-Extrude", "cavity")])
        self.assertEqual((features[0]["sketch"]["op"], features[0]["sketch"]["plane"]), ("RectangleRounded", "Top"))
        self.assertEqual(features[2]["sketch"]["op"], "Rectangle")
        self.assertEqual(len(features[2]["rows"]), 2)
        self.assertIsNone(features[1]["sketch"])
        (x0, y0, z0), (x1, y1, z1) = state["bounds"]
        self.assertAlmostEqual(x1 - x0, 70, places=3)
        self.assertAlmostEqual(z1 - z0, 12, places=3)

    def test_each_feature_carries_the_last_line_of_its_statement(self):
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(SPREAD)
        self.addCleanup(shutil.rmtree, root, True)
        state = service.state(str(root / "spread.step"))
        self.assertTrue(state["ok"], state.get("error"))
        lines = [line.strip() for line in (root / "spread.py").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([lines[at - 1] for at in (7, 8, 11, 13)],
                         ["base = Box(40, 20, 5)", "base = fillet(", ")", "base -= Pos(10, 0) * Cylinder(1.6, 5)"])
        # The fillet is written over four lines: its statement ends at the bracket that closes it. A line
        # anywhere in it is the fillet's, and the blank line after it is no feature's.
        self.assertEqual([(f["kind"], f["line"], f["end"]) for f in state["features"]],
                         [("Boss-Extrude", 7, 7), ("Fillet", 8, 11), ("Hole", 13, 13)])

    def test_a_feature_inside_a_block_carries_the_last_line_of_its_own_statement(self):
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(BUILT)
        self.addCleanup(shutil.rmtree, root, True)
        # Inside a builder's `with` block, and in a `for` body: the statement that starts at the feature's line, not
        # the block around it.
        built = service.state(str(root / "built.step"))
        self.assertTrue(built["ok"], built.get("error"))
        self.assertEqual([(f["line"], f.get("end")) for f in built["features"]], [(8, 8), (9, 13)])
        looped = service.state(str(root / "looped.step"))
        self.assertTrue(looped["ok"], looped.get("error"))
        self.assertEqual([(f["kind"], f["line"], f.get("end")) for f in looped["features"]], [("Boss-Extrude", 7, 7), ("Hole", 9, 10)])


SKETCHED = {
    "bracket.py": """
        from build123d import extrude
        from cadgen import model
        from cadgen.sketch import Sketch

        LENGTH = 40
        WIDTH = 20
        HOLE = 6
        THICKNESS = 4

        @model
        def bracket():
            s = Sketch("Sketch1", plane="Top")
            bottom, right, top, left = s.rectangle((0, 0), (40, 20))
            s.coincident(bottom.start, s.origin)
            s.length(bottom, LENGTH)
            s.length(left, WIDTH)
            hole = s.circle((20, 10), 3)
            s.diameter(hole, HOLE)
            s.horizontal_distance(bottom.start, hole.center, LENGTH / 2)
            s.vertical_distance(bottom.start, hole.center, WIDTH / 2)
            return extrude(s.face(), amount=THICKNESS)
    """,
}


class ConstrainedSketches(unittest.TestCase):
    def test_a_sketch_sits_under_its_feature_and_its_dimensions_are_the_features_inputs(self):
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(SKETCHED)
        self.addCleanup(shutil.rmtree, root, True)
        file = str(root / "bracket.step")
        state = service.state(file)
        self.assertTrue(state["ok"], state.get("error"))
        (feature,) = state["features"]
        self.assertEqual(feature["kind"], "Boss-Extrude")
        self.assertEqual({key: feature["sketch"][key] for key in ("name", "plane", "status")},
                         {"name": "Sketch1", "plane": "Top", "status": "Fully defined"})
        row = next(row for row in state["rows"] if row["key"] == feature["key"])
        labels = [item["label"] for item in row["inputs"]]
        self.assertIn("D1@Sketch1", labels)
        length = labels.index("D1@Sketch1")
        changed = service.change({"file": file, "input": {"row": row["key"], "index": length}, "text": "50", "files": state["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("LENGTH = 50\n", (root / "bracket.py").read_text(encoding="utf-8"))


# A tray whose fillet cannot be made once WALL is big enough: rounded in the part's own line, by a
# helper's function the part calls, and at the bottom of a chain of helper calls longer than a failure tells of.
ROUNDED = {
    "tray.py": """
        from build123d import Axis, Box, fillet
        from cadgen import model

        WALL = 2


        @model
        def tray():
            outer = Box(40, 20, 10)
            outer = fillet(outer.edges().filter_by(Axis.Z), radius=WALL)
            return outer
    """,
    "helped.py": """
        from build123d import Box
        from cadgen import model
        from helpers import rounded

        WALL = 2


        @model
        def helped():
            outer = Box(40, 20, 10)
            outer = rounded(outer, WALL)
            return outer
    """,
    "deep.py": """
        from build123d import Box
        from cadgen import model
        from helpers import descend

        WALL = 2


        @model
        def deep():
            outer = Box(40, 20, 10)
            outer = descend(outer, WALL, 9)
            return outer
    """,
    "helpers.py": """
        from build123d import Axis, fillet


        def rounded(shape, radius):
            return fillet(shape.edges().filter_by(Axis.Z), radius=radius)


        def descend(shape, radius, depth):
            if depth == 0:
                return rounded(shape, radius)
            return descend(shape, radius, depth - 1)
    """,
}


WRITTEN_FOR_07 = "This part was written for cadgen 0.7. Ask the AI to move it to 0.8."


class FailedBuild(unittest.TestCase):
    """A part whose script stops says where it stopped: the frames of its traceback in its own files, so
    the viewer can tell which row of the last good part held that very line, or made the call that did. A
    row of the history reads its line the same way."""

    def setUp(self):
        self.service = edit.EditService(build=False)
        self.addCleanup(self.service.close)
        self.root = project(ROUNDED)
        self.addCleanup(shutil.rmtree, self.root, True)

    def line_of(self, name: str, text: str) -> int:
        """The line of a file that reads ``text``, counted from 1 as a traceback counts them."""
        return [line.strip() for line in (self.root / name).read_text(encoding="utf-8").splitlines()].index(text) + 1

    def too_big(self, step: str):
        file = str(self.root / f"{step}.step")
        good = self.service.state(file)
        self.assertTrue(good["ok"], good.get("error"))
        wall = next(param for param in good["params"] if param["name"] == "WALL")
        return good, self.service.change({"file": file, "literal": wall["id"], "text": "50", "files": good["files"]})

    def test_a_failed_trace_says_the_line_it_stopped_at(self):
        good, bad = self.too_big("tray")
        self.assertFalse(bad["ok"])
        self.assertIn("ValueError", bad["error"])
        # The frames of the traceback in the project's own files (build123d's and the tracer's are not),
        # deepest first, each as a row names its place: here the part's own line, and no other.
        rounding = "outer = fillet(outer.edges().filter_by(Axis.Z), radius=WALL)"
        frames = [{"file": "tray.py", "line": self.line_of("tray.py", rounding), "text": rounding}]
        self.assertEqual(bad["failure"], {"frames": frames})
        # Its text is the row's own, so the row of the last good part that held this line can be told by it.
        fillet = next(row for row in good["rows"] if row["kind"] == "Fillet")
        self.assertEqual((fillet["file"], fillet["line"], fillet["code"]), tuple(frames[0].values()))

    def test_a_helper_that_stops_gives_its_line_and_then_the_call_the_feature_stands_at(self):
        good, bad = self.too_big("helped")
        self.assertFalse(bad["ok"])
        raising = "return fillet(shape.edges().filter_by(Axis.Z), radius=radius)"
        call = "outer = rounded(outer, WALL)"
        frames = [{"file": "helpers.py", "line": self.line_of("helpers.py", raising), "text": raising},
                  {"file": "helped.py", "line": self.line_of("helped.py", call), "text": call}]
        self.assertEqual(bad["failure"], {"frames": frames})
        # The helper's line makes no row of the history; the call that made the fillet is the row.
        fillet = next(row for row in good["rows"] if row["kind"] == "Fillet")
        self.assertEqual((fillet["file"], fillet["line"], fillet["code"]), tuple(frames[1].values()))
        self.assertNotIn(("helpers.py", frames[0]["line"]), [(row["file"], row["line"]) for row in good["rows"]])

    def test_a_chain_of_helpers_longer_than_six_tells_of_the_deepest_six(self):
        _, bad = self.too_big("deep")
        self.assertFalse(bad["ok"])
        frames = bad["failure"]["frames"]
        self.assertEqual(len(frames), 6)
        # The line that raised first, then each call outwards; the part's own call is past the cap.
        self.assertEqual([frame["file"] for frame in frames], ["helpers.py"] * 6)
        self.assertEqual([frame["text"] for frame in frames],
                         ["return fillet(shape.edges().filter_by(Axis.Z), radius=radius)", "return rounded(shape, radius)"]
                         + ["return descend(shape, radius, depth - 1)"] * 4)

    def test_a_part_written_for_cadgen_07_says_so_first(self):
        written = {
            # A name 0.7 exported, imported from cadgen.
            "from cadgen import model, srgb\n\n\n@model\ndef tray():\n    return srgb(1, 0, 0)\n",
            # One reached through the module as the part runs.
            "import cadgen\nfrom cadgen import model\n\n\n@model\ndef tray():\n    return cadgen.read_scene('tray.step')\n",
            # A module 0.7 had.
            "from cadgen import model\nfrom cadgen.step_scene import scene\n\n\n@model\ndef tray():\n    return scene()\n",
        }
        for text in written:
            with self.subTest(text=text.splitlines()[0]):
                (self.root / "tray.py").write_text(text, encoding="utf-8")
                bad = self.service.state(str(self.root / "tray.step"))
                self.assertFalse(bad["ok"])
                self.assertTrue(bad["error"].startswith(WRITTEN_FOR_07), bad["error"])
                # The traceback follows, for the AI that moves it.
                self.assertIn("Traceback", bad["error"])
        # A name of the project's own that is missing is not 0.7's.
        (self.root / "tray.py").write_text("from cadgen import model\nfrom helpers import srgb\n\n\n@model\ndef tray():\n    return srgb()\n",
                                           encoding="utf-8")
        bad = self.service.state(str(self.root / "tray.step"))
        self.assertFalse(bad["ok"])
        self.assertNotIn(WRITTEN_FOR_07, bad["error"])

    def test_a_script_that_cannot_be_read_names_no_line(self):
        (self.root / "tray.py").write_text("from cadgen import model\n\n\n@model\ndef tray(:\n    pass\n", encoding="utf-8")
        bad = self.service.state(str(self.root / "tray.step"))
        self.assertFalse(bad["ok"])
        # The traceback names the script's line, but no frame of the part ran, so no place is named.
        self.assertIsNone(bad.get("failure"))

    def test_a_good_part_has_no_failure_and_each_feature_carries_its_first_line(self):
        state = self.service.state(str(self.root / "tray.step"))
        self.assertTrue(state["ok"], state.get("error"))
        self.assertNotIn("failure", state)
        lines = (self.root / "tray.py").read_text(encoding="utf-8").splitlines()
        self.assertEqual([(f["kind"], f["text"]) for f in state["features"]],
                         [(f["kind"], lines[f["line"] - 1].strip()) for f in state["features"]])
        self.assertEqual([f["text"] for f in state["features"]],
                         ["outer = Box(40, 20, 10)", "outer = fillet(outer.edges().filter_by(Axis.Z), radius=WALL)"])


class WhatAChangeBuilds(unittest.TestCase):
    def test_the_parts_that_use_the_changed_file(self):
        root = project(PLATE)
        self.addCleanup(shutil.rmtree, root, True)
        self.assertEqual([path.name for path in edit.dependents(root, "sizes.py")], ["plate.py"])
        self.assertEqual([path.name for path in edit.dependents(root, "bracket.py")], ["bracket.py"])


class TypedValues(unittest.TestCase):
    def test_plain_arithmetic_only(self):
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        root = project(PLATE)
        self.addCleanup(shutil.rmtree, root, True)
        file = str(root / "plate.step")
        state = service.state(file)
        width = next(p for p in state["params"] if p["name"] == "WIDTH")
        refused = service.change({"file": file, "literal": width["id"], "text": "__import__('os').getcwd()", "files": state["files"]})
        self.assertFalse(refused["ok"])
        changed = service.change({"file": file, "literal": width["id"], "text": "20 + 1.5", "files": state["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("WIDTH = 21.5\n", (root / "sizes.py").read_text(encoding="utf-8"))

    def test_a_flag_in_arithmetic_is_the_number_it_stands_for(self):
        # build123d's PolarLocations turns each location by `rotate * angle`: rotate is a bool.
        root = project({
            "sizes.py": "CIRCLE = 30\nHOLES = 6\n",
            "flange.py": """
                import build123d as bd
                from cadgen import model
                from sizes import CIRCLE, HOLES

                @model
                def flange():
                    part = bd.Cylinder(25, 5)
                    part -= [loc * bd.Cylinder(2, 5) for loc in bd.PolarLocations(CIRCLE / 2, HOLES, start_angle=360 / HOLES / 2)]
                    return part
            """,
        })
        self.addCleanup(shutil.rmtree, root, True)
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        state = service.state(str(root / "flange.step"))
        self.assertTrue(state["ok"], state.get("error"))
        self.assertNotIn("failure", state)
        self.assertIn("CIRCLE", [p["name"] for p in state["params"]])


# A model-first part, as the agent writes one on cadgen 0.8: build123d by its module, a bare @model,
# no file written. A rig composes it as the engine composes a child: `plate().shape`.
MODELS = {
    "plate.py": """
        import build123d as bd
        from cadgen import model

        WIDTH = 40
        HOLE = 6


        @model
        def plate():
            part = bd.Box(WIDTH, 30, 5)
            part -= bd.Cylinder(HOLE / 2, 5)
            return part
    """,
    "post.py": """
        import build123d as bd
        from cadgen import model


        @model
        def post():
            return bd.Pos(0, 0, 10) * bd.Cylinder(2, 15)
    """,
    "rig.py": """
        import build123d as bd
        from cadgen import model

        from plate import plate
        from post import post


        @model
        def rig():
            return bd.Compound(children=[plate().shape, post().shape], label="rig")
    """,
    "stepped.py": """
        import build123d as bd
        from cadgen import step


        @step(out="stepped.step")
        def stepped():
            part = bd.Box(30, 20, 6)
            part -= bd.Cylinder(4, 6)
            return part
    """,
    "tinted.py": """
        import build123d as bd
        from cadgen import model


        @model
        def tinted():
            part = bd.Box(10, 10, 10)
            part.color = "#11223344"
            return part
    """,
    "broken.py": """
        import build123d as bd
        from cadgen import model


        @model
        def broken():
            raise ValueError("the wall is thicker than the part")
    """,
}

# A process the tracer starts reports here: any request for the engine, or an engine started.
_GUARD = """
import os, sys
if any("cadgen.edit.tracer" in each for each in sys.orig_argv):
    def _refused(what):
        def refuse(*args, **kwargs):
            with open(os.environ["STUDIO_TRACER_GUARD"], "a", encoding="utf-8") as told:
                told.write(what + "\\n")
            raise ConnectionError("the tracer asked the engine: " + what)
        return refuse
    import cadgen.engine.api as _api
    import cadgen.engine.client as _client
    _client.connect, _client.request, _client._start = _refused("connect"), _refused("request"), _refused("start")
    _api._ask = _refused("ask")
"""


def line_reading(script: Path, text: str) -> int:
    """The line of ``script`` that holds ``text``, counted from 1."""
    return next(at for at, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1) if text in line)


class ModelsOfTheEngine(unittest.TestCase):
    """A part is a model of cadgen's engine: its script is the tree, its document is opened by the id
    the engine computes, and a face picked on it names its feature from the engine's ``made_by``."""

    @classmethod
    def setUpClass(cls):
        cls.root = project(MODELS)
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        cls.service = edit.EditService()
        cls.addClassCleanup(cls.service.close)
        # The engine the service's builds reach, as the engine's daemon the service runs in is: they never start one.
        from cadgen.engine import api

        built = api.build_script(cls.root / "plate.py")
        assert built.ok, built.models

    def test_a_model_is_its_engine_id_and_reads_as_a_tree(self):
        from cadgen.engine.ids import model_id

        state = self.service.state(str(self.root / "plate.py"))
        self.assertTrue(state["ok"], state.get("error"))
        ident = model_id(self.root / "plate.py", "plate")
        self.assertEqual((state["document"], edit.document_of(self.root / "plate.py")), (ident, ident))
        self.assertEqual([feature["kind"] for feature in state["features"]], ["Boss-Extrude", "Hole"])

    def test_an_assembly_of_child_models_reads_each_as_a_component(self):
        state = self.service.state(str(self.root / "rig.py"))
        self.assertTrue(state["ok"], state.get("error"))
        from cadgen.engine.ids import model_id

        self.assertEqual([(c["name"], c["document"], c["step"]) for c in state["components"]],
                         [("plate", model_id(self.root / "plate.py", "plate"), None),
                          ("post", model_id(self.root / "post.py", "post"), None)])
        self.assertEqual([feature["kind"] for feature in state["components"][0]["features"]], ["Boss-Extrude", "Hole"])

    def test_tracing_never_asks_the_engine(self):
        guard = Path(tempfile.mkdtemp(prefix="tracer-guard-"))
        self.addCleanup(shutil.rmtree, guard, True)
        (guard / "sitecustomize.py").write_text(_GUARD, encoding="utf-8")
        told = guard / "told.txt"
        environment = mock.patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join([str(guard), os.environ.get("PYTHONPATH", "")]),
                                                   "STUDIO_TRACER_GUARD": str(told)})
        environment.start()
        self.addCleanup(environment.stop)
        engine = Path(os.environ["CADGEN_ENGINE_DIR"])
        doors = sorted(engine.glob("*.door"))
        service = edit.EditService(build=False)
        self.addCleanup(service.close)
        # A part, and an assembly whose children's calls would be builds on the engine anywhere else.
        for name in ("plate.py", "rig.py"):
            state = service.state(str(self.root / name))
            self.assertTrue(state["ok"], state.get("error"))
        self.assertFalse(told.exists(), told.read_text(encoding="utf-8") if told.exists() else "")
        self.assertEqual(sorted(engine.glob("*.door")), doors)
        # The guard is live: the one request a trace may make, the rollback bar's body, is refused by it.
        hole = line_reading(self.root / "plate.py", "Cylinder")
        rolled = service.change({"file": str(self.root / "plate.py"), "bar": {"before": f"plate.py:{hole}"}})
        self.assertTrue(rolled["ok"], rolled.get("error"))
        self.assertIn("the tracer asked the engine", rolled["bar"]["error"])
        self.assertTrue(told.exists())

    def test_a_face_names_its_feature_from_made_by_and_the_bar_is_a_document(self):
        from cadgen.engine import api

        script = self.root / "plate.py"
        built = api.build_script(script)
        self.assertTrue(built.ok, built.models)
        ident = edit.document_of(script)
        self.assertEqual(edit.script_for(ident), script.resolve())
        state = self.service.state(ident)
        self.assertTrue(state["ok"], state.get("error"))
        boss, hole = [feature["key"] for feature in state["features"]]
        for face in range(1, state["faceCount"] + 1):
            made = api.inspect(ident, f"face {face}")["made_by"]
            found = self.service.face_feature({"file": ident, "face": face})["faceFeature"]
            self.assertEqual((found["source"], found["madeBy"]), ("made_by", made))
            self.assertEqual(found["feature"], hole if made["line"] == line_reading(script, "Cylinder") else boss)
        # Given by the viewer, made_by is taken as it is: the route asks the engine nothing then.
        told = self.service.face_feature({"file": ident, "face": "plate/face 1", "made_by": {**made, "line": line_reading(script, "bd.Box")}})
        self.assertEqual(told["faceFeature"]["feature"], boss)
        # The rollback bar's body is handed to the engine and opened by its id.
        rolled = self.service.change({"file": ident, "bar": {"before": f"plate.py:{line_reading(script, 'Cylinder')}"}})
        self.assertTrue(rolled["ok"], rolled.get("error"))
        document = rolled["bar"]["document"]
        self.assertAlmostEqual(api.inspect(document["id"], query="summary")["summary"]["volume"], 40 * 30 * 5, places=3)
        # It is the bar's, not the person's: Recents (the CAD home, Studio's lists) leaves it out.
        from cadgen.viewer.recents import RecentStore

        listed = [entry.path for entry in RecentStore().list()]
        self.assertIn(ident, listed)
        self.assertNotIn(document["id"], listed)

    def wait_built(self, service, deadline_seconds=edit.BUILD_TIMEOUT):
        """The service's last batch of builds, once it is done."""
        deadline = time.monotonic() + deadline_seconds
        while service.building()["done"] < len(service.building()["scripts"]) and time.monotonic() < deadline:
            time.sleep(0.1)
        return service.building()

    def test_a_new_part_is_built_by_asking_and_says_when_it_is_built_or_why_not(self):
        # Studio's New part: its script written, then built (`build`), and opened by its id once built.
        root = project({"parts/fresh.py": MODELS["post.py"].replace("post", "fresh"), "parts/broken.py": MODELS["broken.py"]})
        self.addCleanup(shutil.rmtree, root, True)
        fresh = root / "parts" / "fresh.py"
        probe = self.service.editable(str(fresh))
        self.assertEqual((probe["document"], probe["partBuilt"], probe["partBuilding"]), (edit.document_of(fresh), False, False))
        asked = self.service.change({"file": str(fresh), "build": True})
        self.assertTrue(asked["ok"], asked.get("error"))
        self.assertEqual(asked["document"], edit.document_of(fresh))
        self.assertIsNone(self.wait_built(self.service)["error"])
        built = self.service.editable(str(fresh))
        self.assertEqual((built["partBuilt"], built["partBuilding"]), (True, False))
        self.assertNotIn("partError", built)
        # One whose build fails says why, and is not built: nothing to open, nothing to wait for.
        broken = root / "parts" / "broken.py"
        self.assertTrue(self.service.change({"file": str(broken), "build": True})["ok"])
        self.wait_built(self.service)
        probe = self.service.editable(str(broken))
        self.assertEqual((probe["partBuilt"], probe["partBuilding"]), (False, False))
        self.assertIn("the wall is thicker than the part", probe["partError"])

    def test_a_file_names_no_model_so_its_faces_fall_back_to_the_geometric_map(self):
        from cadgen.engine import api

        # A part that writes its STEP (@step(out=)), the STEP on disk: opened as that file, a face is the trace's map's.
        script = self.root / "stepped.py"
        self.assertTrue(api.build_script(script).ok)
        self.assertTrue((self.root / "stepped.step").is_file())
        state = self.service.state(str(self.root / "stepped.step"))
        self.assertTrue(state["ok"], state.get("error"))
        boss, hole = [feature["key"] for feature in state["features"]]
        found = [self.service.face_feature({"file": str(self.root / "stepped.step"), "face": face})["faceFeature"]
                 for face in range(1, state["faceCount"] + 1)]
        self.assertEqual({(each["source"], each["madeBy"]) for each in found}, {("geometric", None)})
        self.assertEqual({each["feature"] for each in found}, {boss, hole})
        # An element's name is no face number; a face's ref is.
        named = self.service.face_feature({"file": str(self.root / "stepped.step"), "face": "f:stepped.part.1"})["faceFeature"]
        self.assertEqual((named["feature"], named["source"]), (None, None))
        self.assertEqual(self.service.face_feature({"file": str(self.root / "stepped.step"), "face": "stepped/face 1"})
                         ["faceFeature"]["feature"], found[0]["feature"])
        # A STEP brought in with no script names no feature.
        self.assertEqual(self.service.face_feature({"file": str(self.root / "missing.step"), "face": 1})["reason"], "no-script")

    def test_a_face_is_stale_while_its_part_builds_or_its_files_moved_on(self):
        state = self.service.state(str(self.root / "plate.py"))
        moved = dict(state["files"], **{"plate.py": "0" * 16})
        stale = self.service.face_feature({"file": str(self.root / "plate.py"), "face": 1, "files": moved})["faceFeature"]
        self.assertEqual((stale["stale"], stale["feature"], stale["source"]), (True, None, None))
        fresh = self.service.face_feature({"file": str(self.root / "plate.py"), "face": 1, "files": state["files"]})["faceFeature"]
        self.assertNotIn("stale", fresh)
        # A build of it queued or running (one that never ends, by the python it is started with).
        folder = Path(tempfile.mkdtemp(prefix="edit-slow-"))
        self.addCleanup(shutil.rmtree, folder, True)
        python = folder / "python"
        python.write_text("#!/bin/sh\nexec sleep 600\n", encoding="utf-8")
        python.chmod(0o755)
        building = edit.EditService(str(python))
        self.addCleanup(building.close)
        status = building.rebuild(self.root, "plate.py")
        self.assertEqual(status["documents"][status["scripts"].index("plate.py")], edit.document_of(self.root / "plate.py"))
        self.assertTrue(building.face_feature({"file": str(self.root / "plate.py"), "face": 1})["faceFeature"]["stale"])

    def test_the_bar_and_a_build_never_start_an_engine(self):
        engine = Path(tempfile.mkdtemp(prefix="eng-none-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, engine, True)
        environment = mock.patch.dict(os.environ, {"CADGEN_ENGINE_DIR": str(engine)})
        environment.start()
        self.addCleanup(environment.stop)
        service = edit.EditService()
        self.addCleanup(service.close)
        hole = line_reading(self.root / "plate.py", "Cylinder")
        rolled = service.change({"file": str(self.root / "plate.py"), "bar": {"before": f"plate.py:{hole}"}})
        self.assertTrue(rolled["ok"], rolled.get("error"))
        self.assertEqual((rolled["bar"]["step"], rolled["bar"]["error"]), (None, edit.NO_ENGINE))
        service.rebuild(self.root, "post.py")
        status = self.wait_built(service)
        self.assertTrue(status["error"].endswith(f".py: {edit.NO_ENGINE}"), status["error"])
        self.assertEqual([path.name for path in engine.iterdir() if path.suffix in (".door", ".port", ".lock")], [])

    def test_an_adopted_step_moved_away_says_so(self):
        import build123d as bd

        root = project({}, git=True)
        self.addCleanup(shutil.rmtree, root, True)
        source = root / "vendor.step"
        bd.export_step(bd.Box(20, 20, 4), str(source))
        adopted = self.service.change({"file": str(source), "adopt": {}})
        self.assertTrue(adopted["ok"], adopted.get("error"))
        self.assertIsNone(self.wait_built(self.service)["error"])
        self.assertEqual({key: self.service.editable(str(source))[key] for key in ("partBuilt", "partBuilding")},
                         {"partBuilt": True, "partBuilding": False})
        source.rename(root / "elsewhere.step")
        read = self.service.state(adopted["script"])
        self.assertFalse(read["ok"])
        gone = f"the STEP this part reads is gone: {os.path.realpath(source)}"
        self.assertEqual(read["error"], gone)
        self.service.rebuild(root, Path(adopted["script"]).name)
        self.assertIn(gone, self.wait_built(self.service)["error"])

    def test_an_adopted_step_is_building_until_its_build_ends(self):
        import build123d as bd

        root = project({}, git=True)
        self.addCleanup(shutil.rmtree, root, True)
        source = root / "vendor.step"
        bd.export_step(bd.Box(20, 20, 4), str(source))
        # A build that never ends, by the python it is started with: the part is made and building, not yet built.
        folder = Path(tempfile.mkdtemp(prefix="edit-slow-"))
        self.addCleanup(shutil.rmtree, folder, True)
        python = folder / "python"
        python.write_text("#!/bin/sh\nexec sleep 600\n", encoding="utf-8")
        python.chmod(0o755)
        slow = edit.EditService(str(python))
        self.addCleanup(slow.close)
        adopted = slow.change({"file": str(source), "adopt": {}})
        self.assertTrue(adopted["ok"], adopted.get("error"))
        probe = slow.editable(str(source))
        self.assertEqual((probe["part"], probe["partBuilt"], probe["partBuilding"]), (adopted["part"], False, True))
        # One whose build fails: made, neither built nor building, so there is nothing to wait for.
        failing = folder / "fails"
        failing.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        failing.chmod(0o755)
        broken = edit.EditService(str(failing))
        self.addCleanup(broken.close)
        other = root / "other.step"
        bd.export_step(bd.Box(5, 5, 5), str(other))
        self.assertTrue(broken.change({"file": str(other), "adopt": {}})["ok"])
        self.assertIsNotNone(self.wait_built(broken)["error"])
        probe = broken.editable(str(other))
        self.assertEqual((probe["partBuilt"], probe["partBuilding"]), (False, False))
        # Why it did not build, so the page says so rather than making another part of it.
        self.assertEqual(probe["partError"], "other_part.py: the build failed")

    def test_a_color_with_alpha_keeps_it_through_the_engine(self):
        from cadgen.engine import api
        from cadgen.engine.document import read_xbf_shape

        script = self.root / "tinted.py"
        state = self.service.state(str(script))
        painted = self.service.change({"file": str(script), "files": state["files"], "appearance": {"color": "#B7A1D7"}})
        self.assertTrue(painted["ok"], painted.get("error"))
        self.assertIn('    part.color = "#B7A1D744"\n', script.read_text(encoding="utf-8"))
        self.assertTrue(api.build_script(script).ok)
        out = Path(tempfile.mkdtemp(prefix="tinted-")) / "tinted.xbf"
        self.addCleanup(shutil.rmtree, out.parent, True)
        api.export(edit.document_of(script), out)
        held = read_xbf_shape(out)
        part = next(iter(getattr(held, "leaves", None) or [held])) if getattr(held, "children", None) else held
        while getattr(part, "children", None):
            part = part.children[0]
        red, green, blue, alpha = tuple(part.color)
        self.assertEqual("#" + "".join(f"{round(channel * 255):02X}" for channel in (red, green, blue)), "#B7A1D7")
        self.assertEqual(round(alpha * 255), 0x44)

    def test_a_build_that_fails_says_why_in_the_state(self):
        building = self.service.rebuild(self.root, "broken.py")
        self.assertEqual(building["scripts"], ["broken.py"])
        deadline = time.monotonic() + edit.BUILD_TIMEOUT
        while self.service.building()["done"] < 1 and time.monotonic() < deadline:
            time.sleep(0.1)
        status = self.service.building()
        self.assertEqual(status["done"], 1)
        self.assertIn("broken.py: ", status["error"])
        self.assertIn("the wall is thicker than the part", status["error"])

    def test_a_failed_build_says_its_error_without_the_tracebacks_markers(self):
        # A build that fails as Python 3.13 says a NameError: the line, the marker line under it, the error.
        folder = Path(tempfile.mkdtemp(prefix="edit-marked-"))
        self.addCleanup(shutil.rmtree, folder, True)
        python = folder / "python"
        python.write_text("#!/bin/sh\ncat >&2 <<'SAID'\n  File \"plate.py\", line 7, in plate\n"
                          "    return Box(40, 20, HEIGHTT)\n                       ^^^^^^^\n"
                          "NameError: name 'HEIGHTT' is not defined\n   \nSAID\nexit 1\n", encoding="utf-8")
        python.chmod(0o755)
        service = edit.EditService(str(python))
        self.addCleanup(service.close)
        service.rebuild(self.root, "plate.py")
        deadline = time.monotonic() + 60
        while service.building()["done"] < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        # Each script that uses plate.py was built; the error names the last one to fail.
        self.assertRegex(service.building()["error"],
                         r"^\w+\.py: return Box\(40, 20, HEIGHTT\) NameError: name 'HEIGHTT' is not defined$")

    def test_closing_the_service_ends_the_build_it_started(self):
        # A build that never ends: the service's python stands in for one, by the process it starts.
        folder = Path(tempfile.mkdtemp(prefix="edit-slow-"))
        self.addCleanup(shutil.rmtree, folder, True)
        python = folder / "python"
        python.write_text("#!/bin/sh\nexec sleep 600\n", encoding="utf-8")
        python.chmod(0o755)
        service = edit.EditService(str(python))
        self.addCleanup(service.close)
        service.rebuild(self.root, "plate.py")
        deadline = time.monotonic() + 60
        while service._builds._running is None and time.monotonic() < deadline:
            time.sleep(0.05)
        running = service._builds._running
        self.assertIsNotNone(running)
        service.close()
        self.assertIsNotNone(running.poll())


if __name__ == "__main__":
    unittest.main()


class TypedUnits(unittest.TestCase):
    """A size typed with its unit, as SolidWorks' boxes take one, is the number it is in the part's units."""

    def test_a_size_typed_in_another_unit_is_the_parts(self):
        from cadgen.edit import tracer

        self.assertEqual(tracer.parse_number("1in", "mm"), 25.4)
        self.assertEqual(tracer.parse_number("25.4mm", "in"), 1.0)
        self.assertEqual(tracer.parse_number('2 + 1"', "mm"), 27.4)
        self.assertEqual(tracer.parse_number("10cm", "mm"), 100.0)
        self.assertEqual(tracer.parse_number("3"), 3.0)
        with self.assertRaises(ValueError):
            tracer.parse_number("WALL")
