import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from server_py.source_editor import read_source_model, update_source_model  # noqa: E402
from server_py.source_features import parse_source_features  # noqa: E402


SOURCE = """from build123d import *

def gen_step():
    with BuildPart() as part:
        with BuildSketch() as sketch:
            Rectangle(24, 16)
            Circle(3, mode=Mode.SUBTRACT)
        extrude(amount=6)
        with Locations((0, 0, -5)):
            Hole(radius=1)
    return part.part
"""


class SourceFeatureParserTest(unittest.TestCase):
    def test_pairs_sketch_with_extrude_and_keeps_numeric_spans(self):
        result = parse_source_features(SOURCE)
        self.assertTrue(result["ok"])
        self.assertEqual(["extrude", "Hole"], [feature["op"] for feature in result["features"]])
        extrude = result["features"][0]
        self.assertEqual(["Rectangle", "Circle"], [entity["op"] for entity in extrude["sketch"]["entities"]])
        self.assertEqual("Plane.XY", extrude["sketch"]["plane"]["name"])
        self.assertEqual([0.0, 0.0, 1.0], extrude["sketch"]["plane"]["normal"])
        self.assertEqual([], extrude["sketch"]["entities"][0]["positionParams"])
        amount = extrude["params"][0]
        self.assertEqual("6", SOURCE[amount["span"][0]:amount["span"][1]])

    def test_non_ascii_before_a_dimension_does_not_shift_its_span(self):
        source = SOURCE.replace("Rectangle(24, 16)", 'note = "é×°"; Rectangle(24, 16)')
        result = parse_source_features(source)
        width = result["features"][0]["sketch"]["entities"][0]["params"][0]
        self.assertEqual("24", source[width["span"][0]:width["span"][1]])

    def test_preserves_authored_plane_outer_location_and_profile_location(self):
        source = """from build123d import *

def gen_step():
    with BuildPart() as part:
        with Locations((10, 20, 30)):
            with BuildSketch(Plane.XZ):
                with Locations((2, 3)):
                    Circle(4)
            extrude(amount=5)
    return part.part
"""
        result = parse_source_features(source)
        sketch = result["features"][0]["sketch"]
        self.assertEqual([10.0, 20.0, 30.0], sketch["plane"]["origin"])
        self.assertEqual([1.0, 0.0, 0.0], sketch["plane"]["xAxis"])
        self.assertEqual([0.0, 0.0, 1.0], sketch["plane"]["yAxis"])
        self.assertEqual([0.0, -1.0, 0.0], sketch["plane"]["normal"])
        self.assertEqual([2.0, 3.0], sketch["entities"][0]["position"])
        self.assertEqual([2.0, 3.0], [parameter["value"] for parameter in sketch["entities"][0]["positionParams"]])
        self.assertEqual([0.0, 0.0], [parameter["offset"] for parameter in sketch["entities"][0]["positionParams"]])

    def test_combines_nested_outer_locations_for_sketch_origin(self):
        source = """from build123d import *

def gen_step():
    with BuildPart() as part:
        with Locations((1, 2, 3)):
            with Locations((4, 5, 6)):
                with BuildSketch():
                    Rectangle(24, 16)
                extrude(amount=5)
    return part.part
"""
        sketch = parse_source_features(source)["features"][0]["sketch"]
        self.assertEqual([5.0, 7.0, 9.0], sketch["plane"]["origin"])

    def test_preserves_editable_inner_location_with_outer_offset(self):
        source = """from build123d import *

def gen_step():
    with BuildPart() as part:
        with BuildSketch():
            with Locations((10, 20)):
                with Locations((2, 3)):
                    Circle(4)
        extrude(amount=5)
    return part.part
"""
        entity = parse_source_features(source)["features"][0]["sketch"]["entities"][0]
        self.assertEqual([12.0, 23.0], entity["position"])
        self.assertEqual([2.0, 3.0], [parameter["value"] for parameter in entity["positionParams"]])
        self.assertEqual([10.0, 20.0], [parameter["offset"] for parameter in entity["positionParams"]])

    def test_supports_static_plane_offsets_and_marks_dynamic_planes_unsupported(self):
        offset_source = SOURCE.replace("BuildSketch()", "BuildSketch(Plane.XY.offset(8))")
        offset_plane = parse_source_features(offset_source)["features"][0]["sketch"]["plane"]
        self.assertEqual([0.0, 0.0, 8.0], offset_plane["origin"])
        dynamic_source = SOURCE.replace("BuildSketch()", "BuildSketch(part.faces().sort_by(Axis.Z)[-1])")
        dynamic_plane = parse_source_features(dynamic_source)["features"][0]["sketch"]["plane"]
        self.assertFalse(dynamic_plane["supported"])


class SourceEditorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "part.step.py")
        pathlib.Path(self.path).write_text(SOURCE, encoding="utf-8")

    def test_applies_a_guarded_numeric_edit_atomically(self):
        before = read_source_model(self.path)
        amount = before["features"][0]["params"][0]
        after = update_source_model(self.path, {
            "expectedHash": before["sourceHash"],
            "edits": [{
                "start": amount["span"][0],
                "end": amount["span"][1],
                "expected": "6",
                "replacement": "8.5",
            }],
        })
        self.assertNotEqual(before["sourceHash"], after["sourceHash"])
        self.assertEqual(8.5, after["features"][0]["params"][0]["value"])

    def test_rejects_a_stale_hash_without_touching_the_file(self):
        with self.assertRaisesRegex(ValueError, "changed on disk"):
            update_source_model(self.path, {
                "expectedHash": "stale",
                "edits": [{"start": 0, "end": 1, "replacement": "x"}],
            })
        self.assertEqual(SOURCE, pathlib.Path(self.path).read_text(encoding="utf-8"))

    def test_rejects_invalid_python_without_touching_the_file(self):
        before = read_source_model(self.path)
        with self.assertRaisesRegex(ValueError, "invalid"):
            update_source_model(self.path, {
                "expectedHash": before["sourceHash"],
                "source": "def broken(:\n",
            })
        self.assertEqual(SOURCE, pathlib.Path(self.path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
