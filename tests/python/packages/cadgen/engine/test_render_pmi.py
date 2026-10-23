"""PMI in the stills is the viewer's: `engine/render/pmi.py` ports what a callout says and where it
stands, and is held to the constructions the viewer's own layout made
(`packages/core/src/lib/xbf/__fixtures__/pmi_plate/constructions.json`, which `xbfPmiLayout.test.js`
holds the viewer to), over the plate the engine served (`__fixtures__/pmi_plate`): as its code
placed its PMI, with no placement at all, and after the edit that left the hole's callouts invalid,
to 1e-6. No node runs.

And a still of a document carrying PMI draws it -- by default, as the viewer shows it, and not with
`display.pmi` false -- every callout inside the picture; asking for it where it cannot be drawn
(a document with none, the parts exploded, posed or in Preview) is refused by name. Drawing needs
an OpenGL context (`tests/python/support/opengl.py`): skipped, saying why, where none can be made."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from cadgen.engine.mesh import Mesh
from cadgen.engine.render import pmi
from cadgen.engine.render.explode import part_box, placed_box
from cadgen.engine.snapshot import SnapshotRefused, Still, parse_display, pmi_drawn
from tests.python.support import opengl

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


# A plate with a hole, its PMI on its own faces: a datum on the bottom, the thickness, a flatness on
# the top. Tolerance values are illustrative.
PLATE = """
import build123d as bd
from cadgen.engine import pmi, xbf

@xbf(out="XBF/plate.xbf")
def plate():
    body = bd.Box(60, 40, 8) - bd.Cylinder(4, 8)
    body.label = "plate"
    bottom, top = body.faces().sort_by(bd.Axis.Z)[0], body.faces().sort_by(bd.Axis.Z)[-1]
    return pmi.annotate(body, pmi.datum("A", bottom), pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus(0.2)),
                        pmi.flatness("top-flat", top, 0.05))

if __name__ == "__main__":
    plate()
"""


def build(folder: Path) -> Path:
    from cadgen.engine import build as engine_build

    script = folder / "plate.py"
    script.write_text(textwrap.dedent(PLATE), encoding="utf-8")
    reports = engine_build.build(script, None, cwd=folder)
    assert all(report["ok"] for report in reports), reports
    return folder / "XBF/plate.xbf"


def served_document(document: Path) -> tuple[dict, dict[str, bytes]]:
    from cadgen.engine.serve import Server

    server = Server(port=0, mesh_mode="inline")
    try:
        doc = server.document(server.add(document))
        server.mesh_all(doc, None)
        structure = server.structure(doc)
        return structure, {p["key"]: server.cache.get(p["key"]) for p in structure["prototypes"]}
    finally:
        server.stop()


def pixels(data: bytes) -> np.ndarray:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB")).astype(np.int16)


class PmiAskedTest(unittest.TestCase):
    """What a still is asked to draw of the PMI, checked before anything renders: no OpenGL."""

    def test_pmi_is_drawn_by_default_at_rest_and_refused_by_name_where_it_cannot_be(self) -> None:
        carried, bare = {"pmi": [{"id": "A"}]}, {"name": "box"}
        self.assertTrue(pmi_drawn(Still(), carried, "plate.xbf"))
        self.assertFalse(pmi_drawn(Still(), bare, "box.xbf"), "a document with none draws none, asked for nothing")
        self.assertFalse(pmi_drawn(Still(display={"pmi": False}), carried, "plate.xbf"))
        # Moved parts draw none by default, as the viewer shows none; asked for, it is refused.
        self.assertFalse(pmi_drawn(Still(display={"exploded": {"enabled": True, "amount": 0.5}}), carried, "plate.xbf"))
        with self.assertRaisesRegex(SnapshotRefused, r"plate\.xbf .*|display\.exploded moves"):
            pmi_drawn(Still(display={"pmi": True, "exploded": {"enabled": True, "amount": 0.5}}), carried, "plate.xbf")
        with self.assertRaisesRegex(SnapshotRefused, "--preview"):
            pmi_drawn(Still(display={"pmi": True}, preview=True), carried, "plate.xbf")
        with self.assertRaisesRegex(SnapshotRefused, "box.xbf carries none"):
            pmi_drawn(Still(display={"pmi": True}), bare, "box.xbf")

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
        from cadgen.engine.render import context
        from cadgen.engine.render.service import Held

        opengl.require(context.available())
        cls.folder = Path(tempfile.mkdtemp(prefix="engine-render-pmi-")).resolve()
        # The engine's own state, should anything here reach for it, is the test's: never the person's.
        cls.state = mock.patch.dict(os.environ, {"CADGEN_ENGINE_DIR": str(cls.folder / "engine")})
        cls.state.start()
        cls.document = build(cls.folder)
        cls.structure, cls.buffers = served_document(cls.document)
        cls.held = Held(cls.document)
        cls.held.hold(cls.structure, cls.buffers)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.held.close()
        cls.state.stop()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_a_still_draws_the_document_s_pmi_unless_asked_not_to(self) -> None:
        self.assertEqual([entry["id"] for entry in self.structure["pmi"]], ["A", "thickness", "top-flat"])
        # As tall as the viewer the callouts are drawn for (`overlay.REFERENCE_HEIGHT`): their words full size.
        drawn, report = self.held.draw(Still(size=(1200, 900)))
        self.assertEqual(report["pmi"], 3, report)
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
        with self.assertRaisesRegex(SnapshotRefused, "--pose|exploded|--preview"):
            self.held.draw(Still(size=(160, 120), display={"pmi": True}, preview=True))


if __name__ == "__main__":
    unittest.main()
