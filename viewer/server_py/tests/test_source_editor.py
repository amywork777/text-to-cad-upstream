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
        amount = extrude["params"][0]
        self.assertEqual("6", SOURCE[amount["span"][0]:amount["span"][1]])

    def test_non_ascii_before_a_dimension_does_not_shift_its_span(self):
        source = SOURCE.replace("Rectangle(24, 16)", 'note = "é×°"; Rectangle(24, 16)')
        result = parse_source_features(source)
        width = result["features"][0]["sketch"]["entities"][0]["params"][0]
        self.assertEqual("24", source[width["span"][0]:width["span"][1]])


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
