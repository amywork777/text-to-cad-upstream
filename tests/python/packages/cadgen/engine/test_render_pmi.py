"""PMI in the stills is the viewer's: `engine/render/pmi.py` ports what a callout says and where it
stands, and is held to the constructions the viewer's own layout made
(`packages/core/src/lib/xbf/__fixtures__/pmi_plate/constructions.json`, which `xbfPmiLayout.test.js`
holds the viewer to), over the plate the engine served (`__fixtures__/pmi_plate`): as its code
placed its PMI, with no placement at all, and after the edit that left the hole's callouts invalid,
to 1e-6. No node runs.

And a still of a document carrying PMI draws it -- by default, as the viewer shows it, and not with
`display.pmi` false -- every callout inside the picture, as its golden (`render_golden/pmi.png`,
held and written as `test_render.py` holds its own); asking for it where it cannot be drawn (a
document with none, the parts exploded, posed or in Preview) is refused by name. Drawing needs an
OpenGL context (`tests/python/support/opengl.py`): skipped, saying why, where none can be made."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from cadgen.engine.mesh import Mesh
from cadgen.engine.render import pmi
from cadgen.engine.snapshot import SnapshotRefused, Still, draws_pmi, parse_display
from tests.python.packages.cadgen.engine.test_render import GOLDEN, WRITE, build, gl, mismatch, pixels, served

FIXTURES = Path(__file__).resolve().parents[5] / "packages" / "core" / "src" / "lib" / "xbf" / "__fixtures__" / "pmi_plate"
TOLERANCE = 1e-6


def fixture(version: str) -> tuple[dict, dict]:
    """The plate as the engine served it to the viewer: its structure and each part's mesh."""
    structure = json.loads((FIXTURES / version / "structure.json").read_text(encoding="utf-8"))
    meshes = {p["key"]: Mesh.from_bytes((FIXTURES / version / f"{p['key']}.xbm").read_bytes()) for p in structure["prototypes"]}
    return structure, meshes


def reversed_basic(item: dict) -> dict:
    """A basic dimension the other way round, from the hole's axis to its side, placed nowhere; any
    other entry as it is."""
    if not (item.get("dimension") or {}).get("basic"):
        return item
    refs = [{**ref, "role": "to" if ref["role"] == "from" else "from"} for ref in reversed(item["refs"])]
    return {**item, "presentation": None, "refs": refs}


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
        self.assertEqual(sorted(self.golden), ["v1", "v1-reversed", "v1-unplaced", "v3"])
        for name, expected in self.golden.items():
            structure, meshes = fixture(name.split("-")[0])
            if name.endswith("unplaced"):
                structure = {**structure, "pmi": [{**item, "presentation": None} for item in structure["pmi"]]}
            if name.endswith("reversed"):
                structure = {**structure, "pmi": [reversed_basic(item) for item in structure["pmi"]]}
            made = pmi.constructions(structure, meshes, pmi.rest_bounds(structure, meshes))
            found = [{"id": entry["id"], "construction": construction} for entry, construction in made]
            # JSON's own spelling of what the viewer wrote: no tuples, no NaN.
            self.assert_near(json.loads(json.dumps(found)), expected, name)

    def test_what_a_callout_says_is_what_the_viewer_says(self) -> None:
        structure, _meshes = fixture("v1")
        said = {entry["id"]: pmi.callout(entry) for entry in pmi.entries(structure)}
        self.assertEqual([item["kind"] for item in said.values()], ["datum", "dimension", "dimension", "dimension", "dimension", "frame", "frame"])
        self.assertEqual(said["A"]["letter"], "A")
        self.assertEqual([said["thickness"]["nominal"], said["thickness"]["tolerance"]["text"], said["thickness"]["basic"]], ["10.0", "±0.2", False])
        hole = said["hole-diameter"]
        self.assertEqual([hole["diameter"], hole["nominal"], hole["tolerance"]["upper"], hole["tolerance"]["lower"]], [True, "10.0", "+0.1", "0"])
        # Exact: boxed, no tolerance.
        self.assertEqual([said["hole-from-front"][key] for key in ("basic", "nominal", "tolerance")], [True, "30", None])
        position = said["hole-position"]
        self.assertEqual([position["characteristic"], position["diameter"], position["value"], position["datums"]], ["position", True, "0.1", ["A"]])
        broken, _ = fixture("v3")
        hole = next(entry for entry in pmi.entries(broken) if entry["id"] == "hole-diameter")
        self.assertEqual([hole["status"], hole["supported"], pmi.callout(hole)["nominal"]], ["invalid", True, "?"])

    def test_a_basic_dimension_between_two_holes_is_measured_square_to_both(self) -> None:
        # The bracket's hole (r 4, its axis z through the origin) and a peg (r 3, its axis z through x 12).
        hole = {"surface": {"type": "cylinder", "axis": [0, 0, 1], "origin": [0, 0, 0], "radius": 4},
                "points": [[4, 0, 2], [-4, 0, 2], [0, 4, -2]]}
        peg = {"surface": {"type": "cylinder", "axis": [0, 0, -1], "origin": [12, 0, 8], "radius": 3}, "points": [[15, 0, 2]]}
        entry = {"id": "peg-from-hole", "kind": "dimension", "presentation": {"anchor": [0, 0, 2], "offset": [6, -8, 0]},
                 "dimension": {"type": "distance", "basic": True, "nominal": 12.0, "tolerance": None}}
        made = pmi.construction(entry, {"from": hole, "to": peg}, ([-20, -10, -2], [20, 10, 14]))
        self.assert_near(made["label"], [6, -8, 2], "the label")
        self.assert_near(made["dimension"]["from"], [0, -8, 2], "at the hole's axis, level with the label")
        self.assert_near(made["dimension"]["to"], [12, -8, 2], "at the peg's")
        self.assert_near(made["dimension"]["extensions"][0][0], [0, 0, 2], "from the hole's centre line")
        self.assert_near(made["dimension"]["extensions"][1][0], [12, 0, 2], "from the peg's centre line")
        # Axes that are not parallel measure nothing.
        crossed = {"surface": {"type": "cylinder", "axis": [1, 0, 0], "origin": [0, 5, 0], "radius": 1}, "points": [[0, 6, 0]]}
        self.assertTrue(pmi.construction(entry, {"from": hole, "to": crossed}, None)["broken"])

    def test_numbers_are_written_as_the_viewer_writes_them(self) -> None:
        self.assertEqual(pmi.number(-0.0000001, 2), "0.00")
        self.assertEqual(pmi.number(12.5), "12.5")
        self.assertEqual(pmi.number(-0.05, 2), "−0.05")
        # JavaScript's toFixed takes the larger of two as near: Python's own format would not.
        self.assertEqual(pmi.number(0.125, 2), "0.13")
        self.assertEqual(pmi.tolerance_text({"upper": 0.05, "lower": -0.1})["text"], "+0.05/−0.10")


# A plate with a hole, its PMI on its own faces: a datum on the bottom, the thickness, a flatness on
# the top, the hole located by a basic distance from the left side. Tolerance values are illustrative.
PLATE = """
import build123d as bd
from cadgen.engine import pmi, xbf

@xbf(out="XBF/plate.xbf")
def plate():
    body = bd.Box(60, 40, 8) - bd.Cylinder(4, 8)
    body.label = "plate"
    bottom, top = body.faces().sort_by(bd.Axis.Z)[0], body.faces().sort_by(bd.Axis.Z)[-1]
    left, hole = body.faces().sort_by(bd.Axis.X)[0], body.faces().filter_by(bd.GeomType.CYLINDER)[0]
    return pmi.annotate(body, pmi.datum("A", bottom), pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus(0.2)),
                        pmi.flatness("top-flat", top, 0.05), pmi.basic("hole-from-left", left, hole))

if __name__ == "__main__":
    plate()
"""


class PmiAskedTest(unittest.TestCase):
    """What a still is asked to draw of the PMI, checked before anything renders: no OpenGL."""

    def test_pmi_is_drawn_by_default_at_rest_and_refused_by_name_where_it_cannot_be(self) -> None:
        carried, bare = {"pmi": [{"id": "A"}]}, {"name": "box"}
        self.assertTrue(draws_pmi(Still(), carried, "plate.xbf"))
        self.assertFalse(draws_pmi(Still(), bare, "box.xbf"), "a document with none draws none, asked for nothing")
        self.assertFalse(draws_pmi(Still(display={"pmi": False}), carried, "plate.xbf"))
        # Moved parts draw none by default, as the viewer shows none; asked for, it is refused.
        self.assertFalse(draws_pmi(Still(display={"exploded": {"enabled": True, "amount": 0.5}}), carried, "plate.xbf"))
        with self.assertRaisesRegex(SnapshotRefused, "on the parts as made; display.exploded moves or restages them"):
            draws_pmi(Still(display={"pmi": True, "exploded": {"enabled": True, "amount": 0.5}}), carried, "plate.xbf")
        with self.assertRaisesRegex(SnapshotRefused, "on the parts as made; --preview moves or restages them"):
            draws_pmi(Still(display={"pmi": True}, preview=True), carried, "plate.xbf")
        with self.assertRaisesRegex(SnapshotRefused, "display.pmi draws a document's PMI; box.xbf carries none"):
            draws_pmi(Still(display={"pmi": True}), bare, "box.xbf")

    def test_display_takes_pmi_as_a_word_or_a_boolean_and_nothing_else(self) -> None:
        self.assertEqual(parse_display("pmi", False), {"pmi": True})
        self.assertEqual(parse_display("hidden-line,pmi=off", False), {"mode": "hidden-line", "pmi": False})
        self.assertEqual(parse_display('{"pmi": false}', False), {"pmi": False})
        with self.assertRaisesRegex(SnapshotRefused, "display.pmi is true or false"):
            parse_display('{"pmi": "yes"}', False)
        with self.assertRaisesRegex(SnapshotRefused, "pmi or pmi=off"):
            parse_display("pmi=maybe", False)


class PmiStillTest(unittest.TestCase):
    """A document carrying PMI, built, served and held by a renderer, drawn."""

    @classmethod
    def setUpClass(cls) -> None:
        gl()
        from cadgen.engine.render.service import Held

        cls.folder = Path(tempfile.mkdtemp(prefix="engine-render-pmi-")).resolve()
        # The engine's own state, should anything here reach for it, is the test's: never the person's.
        cls.state = mock.patch.dict(os.environ, {"CADGEN_ENGINE_DIR": str(cls.folder / "engine")})
        cls.state.start()
        cls.document = build(cls.folder, PLATE, "plate")
        cls.structure, cls.buffers = served(cls.document)
        cls.held = Held(cls.document)
        cls.held.hold(cls.structure, cls.buffers)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.held.close()
        cls.state.stop()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_a_still_draws_the_document_s_pmi_unless_asked_not_to(self) -> None:
        self.assertEqual([entry["id"] for entry in self.structure["pmi"]], ["A", "thickness", "hole-from-left", "top-flat"])
        # As tall as the viewer the callouts are drawn for (`overlay.REFERENCE_HEIGHT`): their words full size.
        drawn, report = self.held.draw(Still(size=(1200, 900)))
        self.assertEqual(report["pmi"], 4, report)
        golden = GOLDEN / "pmi.png"
        if WRITE:
            golden.write_bytes(drawn)
        else:
            share = mismatch(pixels(drawn), pixels(golden.read_bytes()))
            self.assertLessEqual(share, 0.015, f"pmi: {share:.1%} of its pixels are not the golden's")
        bare, report_bare = self.held.draw(Still(size=(1200, 900), display={"pmi": False}))
        self.assertNotIn("pmi", report_bare)
        # The callouts' words are the ink, near black: nothing of the model is as dark. The fit takes
        # the callouts in, so the two pictures are framed apart and only the ink is compared.
        inked, inked_bare = pixels(drawn).max(axis=2) < 40, pixels(bare).max(axis=2) < 40
        self.assertEqual(int(inked_bare.sum()), 0)
        self.assertGreater(int(inked.sum()), 60, "the callouts' words are drawn")
        # Every callout inside the picture, clear of its edge.
        rim = np.ones_like(inked)
        rim[3:-3, 3:-3] = False
        self.assertFalse((inked & rim).any(), "a callout runs off the picture")

    def test_asking_for_pmi_on_moved_parts_is_refused_before_anything_renders(self) -> None:
        with self.assertRaisesRegex(SnapshotRefused, "on the parts as made; --preview moves or restages them"):
            self.held.draw(Still(size=(160, 120), display={"pmi": True}, preview=True))


if __name__ == "__main__":
    unittest.main()
