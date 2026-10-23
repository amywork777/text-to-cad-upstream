"""PMI in the stills is the viewer's: `engine/render/pmi.py` ports what a callout says and where it
stands, and is held to the constructions the viewer's own layout made
(`packages/core/src/lib/xbf/__fixtures__/pmi_plate/constructions.json`, which `xbfPmiLayout.test.js`
holds the viewer to), over the plate the engine served (`__fixtures__/pmi_plate`): as its code
placed its PMI, with no placement at all, and after the edit that left the hole's callouts invalid,
to 1e-6. No node runs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from cadgen.engine.mesh import Mesh
from cadgen.engine.render import pmi
from cadgen.engine.render.explode import part_box, placed_box

FIXTURES = Path(__file__).resolve().parents[5] / "packages" / "core" / "src" / "lib" / "xbf" / "__fixtures__" / "pmi_plate"
TOLERANCE = 1e-6


def served(version: str) -> tuple[dict, dict]:
    structure = json.loads((FIXTURES / version / "structure.json").read_text(encoding="utf-8"))
    meshes = {p["key"]: Mesh.from_bytes((FIXTURES / version / f"{p['key']}.xbm").read_bytes()) for p in structure["prototypes"]}
    return structure, meshes


def bounds(structure: dict, meshes: dict) -> tuple:
    """The scene's rest bounds: every instance's part box, placed."""
    import numpy as np

    boxes = []
    for instance in structure["instances"]:
        box = part_box(meshes[structure["prototypes"][instance["prototype"]]["key"]])
        if box is not None:
            boxes.append(placed_box(box, np.array(instance["matrix"], float).reshape(4, 4).T))
    return [min(box[0][axis] for box in boxes) for axis in range(3)], [max(box[1][axis] for box in boxes) for axis in range(3)]


class PmiParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.golden = json.loads((FIXTURES / "constructions.json").read_text(encoding="utf-8"))

    def assert_near(self, found, expected, where: str) -> None:
        if isinstance(expected, list):
            self.assertEqual(len(found), len(expected), where)
            for at, (value, want) in enumerate(zip(found, expected)):
                self.assert_near(value, want, f"{where}[{at}]")
        elif isinstance(expected, dict):
            self.assertEqual(sorted(found), sorted(expected), where)
            for key, want in expected.items():
                self.assert_near(found[key], want, f"{where}.{key}")
        elif isinstance(expected, float) or (isinstance(expected, int) and not isinstance(expected, bool)):
            self.assertLessEqual(abs(found - expected), TOLERANCE, f"{where}: {found} is not {expected}")
        else:
            self.assertEqual(found, expected, where)

    def test_each_callout_stands_where_the_viewer_puts_it(self) -> None:
        self.assertEqual(sorted(self.golden), ["v1", "v1-unplaced", "v3"])
        for name, expected in self.golden.items():
            structure, meshes = served(name.split("-")[0])
            if name.endswith("unplaced"):
                structure = {**structure, "pmi": [{**item, "presentation": None} for item in structure["pmi"]]}
            found = [{"id": entry["id"], "construction": made} for entry, made in pmi.constructions(structure, meshes, bounds(structure, meshes))]
            # JSON's own spelling of what the viewer wrote: no tuples, no NaN.
            self.assert_near(json.loads(json.dumps(found)), expected, name)

    def test_what_a_callout_says_is_what_the_viewer_says(self) -> None:
        structure, _meshes = served("v1")
        said = [pmi.callout(entry) for entry in pmi.read(structure)]
        self.assertEqual([item["kind"] for item in said], ["datum", "dimension", "dimension", "frame", "frame"])
        self.assertEqual(said[0]["letter"], "A")
        self.assertEqual([said[1]["nominal"], said[1]["tolerance"]["text"]], ["10.0", "±0.2"])
        self.assertEqual([said[2]["diameter"], said[2]["nominal"], said[2]["tolerance"]["upper"], said[2]["tolerance"]["lower"]], [True, "10.0", "+0.1", "0"])
        self.assertEqual([said[4]["characteristic"], said[4]["diameter"], said[4]["value"], said[4]["datums"]], ["position", True, "0.1", ["A"]])
        broken, _ = served("v3")
        hole = next(entry for entry in pmi.read(broken) if entry["id"] == "hole-diameter")
        self.assertEqual([hole["status"], hole["supported"], pmi.callout(hole)["nominal"]], ["invalid", True, "?"])

    def test_numbers_are_written_as_the_viewer_writes_them(self) -> None:
        self.assertEqual(pmi.number(-0.0000001, 2), "0.00")
        self.assertEqual(pmi.number(12.5), "12.5")
        self.assertEqual(pmi.number(-0.05, 2), "−0.05")
        # JavaScript's toFixed takes the larger of two as near: Python's own format would not.
        self.assertEqual(pmi.number(0.125, 2), "0.13")
        self.assertEqual(pmi.tolerance_text({"upper": 0.05, "lower": -0.1})["text"], "+0.05/−0.10")


if __name__ == "__main__":
    unittest.main()
