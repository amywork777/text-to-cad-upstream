"""Semantic PMI (``cadgen.engine.pmi``): a plate's datums, dimensions and geometric tolerances
written into its xbf as XCAF's GD&T objects and read back the same from the file as from the
build; its AP242 STEP read by OCCT and by a reader of no OCCT (``export/ap242.py``),
which agree on values, units, datum frames and the faces each annotation is on; a warm rebuild,
an edit of the geometry and of a tolerance, a ref the model no longer satisfies (missing,
ambiguous, invalid) kept in the document and refused by a STEP, and one that names another kind
of face than on the last build warned of, the document the code's alone; what is not supported
refused by name; a STEP another system wrote read, converted and exported as it is, what this does
not model listed; and the committed fixture (``pmi_golden``) the same as a fresh build's. A
deliberate change to what a build writes makes the fixture again:
`CADGEN_RENDER_GOLDENS=write scripts/test/test-python.sh tests/python/packages/cadgen/engine/test_pmi.py`."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from cadgen.engine import build as engine_build
from cadgen.engine import document, export, pmi
from cadgen.engine.export import ap242

FIXTURE = Path(__file__).resolve().parent / "pmi_golden"
WRITE = os.environ.get("CADGEN_RENDER_GOLDENS") == "write"


# The fixture's model (``models/examples/src/pmi_plate.py``): tolerance values ILLUSTRATIVE.
PLATE = '''
import build123d as bd
from cadgen.engine import materials, pmi, step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, {thickness}) - bd.Cylinder({radius}, {thickness})
    body.label = "plate"
    body.material = materials.aluminium_6061
    bottom = body.faces().sort_by(bd.Axis.Z)[0]
    top = body.faces().sort_by(bd.Axis.Z)[-1]
    front = body.faces().sort_by(bd.Axis.Y)[0]
    left = body.faces().sort_by(bd.Axis.X)[0]
    hole = body.faces().filter_by(bd.GeomType.CYLINDER)[0]
    return pmi.annotate(
        body,
        pmi.datum("A", bottom, presentation=pmi.place((40, -20, -5), (0, -15, -10))),
        pmi.datum("B", front, presentation=pmi.place((40, -30, 0), (0, -15, 0))),
        pmi.datum("C", left, presentation=pmi.place((-50, 20, 0), (-15, 0, 0))),
        pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus({thickness_tolerance}),
                     presentation=pmi.place((50, 30, 0), (15, 0, 0))),
        pmi.diameter("hole-diameter", hole, tolerance=pmi.plus_minus(0.1, 0),
                     presentation=pmi.place((5, 0, 5), (15, 15, 0))),
        pmi.flatness("top-flatness", top, 0.05, presentation=pmi.place((-30, 20, 5), (0, 15, 0))),
        pmi.position("hole-position", hole, 0.1, datums=["A", "B", "C"],
                     presentation=pmi.place((-5, 0, 5), (-15, 15, 0))),
        pmi.basic("hole-from-B", front, hole, presentation=pmi.place((0, -15, 5), (6, 0, 0))),
        pmi.basic("hole-from-C", left, hole, presentation=pmi.place((-25, 0, 5), (0, 6, 0))),
    )
'''


def plate(thickness: float = 10, radius: float = 5, thickness_tolerance: float = 0.2) -> str:
    return PLATE.format(thickness=thickness, radius=radius, thickness_tolerance=thickness_tolerance)


class _Folder(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="engine-pmi-")).resolve()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def build(self, source: str, name: str = "pmi_plate", *, ok: bool | None = True) -> dict:
        """The model built from ``source``, its report ``ok`` as said (None: either)."""
        script = self.folder / f"{name}.py"
        script.write_text(textwrap.dedent(source), encoding="utf-8")
        os.utime(script, ns=(time.time_ns(), time.time_ns()))
        report = engine_build.build(script, [name], cwd=self.folder)[0]
        if ok is not None:
            self.assertEqual(report["ok"], ok, report)
        return report

    @property
    def xbf(self) -> Path:
        return self.folder / "XBF" / "pmi_plate.xbf"

    @property
    def step(self) -> Path:
        return self.folder / "pmi_plate.step"


def _by_id(entries: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in entries}


def _said(found: object) -> object:
    """An AP242 reader's report (``ap242.report``) with the file's name and its record numbers left
    out (a ``record``, a feature's ``face``): a writer numbering its records otherwise says the same."""
    if isinstance(found, dict):
        return {key: _said(value) for key, value in found.items() if key not in ("file", "record", "face")}
    if isinstance(found, list):
        return [_said(value) for value in found]
    return found


def _face(loaded: document.Loaded, entry: dict, at: int = 0) -> tuple[str, dict]:
    """The surface of the face an entry's ``at``-th ref names, from the document's own geometry."""
    from cadgen.engine.refs import resolve_structure

    [hit] = resolve_structure(loaded.structure(), entry["refs"][at]["ref"])
    prototype = loaded.prototypes[hit.node.payload["prototype"]]
    return pmi._surface(pmi._faces(prototype.shape).FindKey(hit.ordinal))


class PlateTest(_Folder):
    def test_the_document_holds_each_annotation_on_its_face(self) -> None:
        report = self.build(plate())
        self.assertEqual(report["pmi"], {"annotations": 9, "problems": []})
        loaded = document.Loaded(self.xbf)
        found = _by_id(loaded.structure()["pmi"])
        self.assertEqual(list(found), ["A", "B", "C", "thickness", "hole-diameter", "hole-from-B", "hole-from-C",
                                       "top-flatness", "hole-position"])
        self.assertTrue(all(entry["status"] == "ok" for entry in found.values()))
        # Datums: A the bottom (z = -5), B the front (y = -30), C the left (x = -50).
        for letter, axis, at in (("A", 2, -5.0), ("B", 1, -30.0), ("C", 0, -50.0)):
            kind, surface = _face(loaded, found[letter])
            self.assertEqual(kind, "plane")
            self.assertAlmostEqual(abs(surface["normal"][axis]), 1.0)
            self.assertAlmostEqual(surface["origin"][axis], at)
            self.assertEqual(found[letter]["datum"], {"letter": letter})
        # The thickness: measured, 10 mm, between the bottom and the top, +/-0.2 as given.
        thickness = found["thickness"]
        self.assertEqual(thickness["dimension"], {
            "type": "distance", "basic": False, "nominal": {"value": 10.0, "unit": "mm", "source": "geometry"},
            "tolerance": {"type": "plus_minus", "upper": 0.2, "lower": -0.2}})
        self.assertEqual([ref["role"] for ref in thickness["refs"]], ["from", "to"])
        self.assertAlmostEqual(_face(loaded, thickness, 0)[1]["origin"][2], -5.0)
        self.assertAlmostEqual(_face(loaded, thickness, 1)[1]["origin"][2], 5.0)
        self.assertEqual(thickness["refs"][0]["ref"], found["A"]["refs"][0]["ref"])
        # The hole: a cylinder of radius 5, its diameter 10 +0.1/0.
        diameter = found["hole-diameter"]
        self.assertEqual(_face(loaded, diameter), ("cylinder", {"radius": 5.0}))
        self.assertEqual(diameter["dimension"]["nominal"]["value"], 10.0)
        self.assertEqual(diameter["dimension"]["tolerance"], {"type": "plus_minus", "upper": 0.1, "lower": 0.0})
        # Flatness on the top; position of the hole to A|B|C, a diametral zone.
        self.assertEqual(found["top-flatness"]["geometric_tolerance"], {
            "characteristic": "flatness", "value": 0.05, "unit": "mm", "zone": None, "modifier": None, "datums": []})
        self.assertEqual(found["top-flatness"]["refs"][0]["ref"], thickness["refs"][1]["ref"])
        self.assertEqual(found["hole-position"]["geometric_tolerance"], {
            "characteristic": "position", "value": 0.1, "unit": "mm", "zone": "diameter", "modifier": None,
            "datums": ["A", "B", "C"]})
        self.assertEqual(found["hole-position"]["refs"][0]["ref"], diameter["refs"][0]["ref"])
        # Presentation is kept, apart from the semantics.
        self.assertEqual(found["hole-position"]["presentation"], {"anchor": [-5.0, 0.0, 5.0], "offset": [-15.0, 15.0, 0.0]})

    def test_the_file_reads_back_what_the_build_served(self) -> None:
        self.build(plate())
        held = engine_build.held(self.folder / "pmi_plate.py", "pmi_plate")
        self.assertIsNotNone(held)
        self.assertEqual(held.structure["pmi"], document.Loaded(self.xbf).structure()["pmi"])

    def test_the_step_carries_the_same_pmi_to_occt_and_to_a_reader_of_no_occt(self) -> None:
        self.build(plate())
        ours = _by_id(pmi.read(self.xbf))
        # OCCT's XCAF reader: the same kinds, values and faces (ids are the engine's, not the file's).
        theirs = pmi.read(self.step)
        self.assertEqual(len(theirs), len(ours))

        def meaning(entry: dict) -> tuple:
            dimension = entry.get("dimension")
            if dimension is not None:  # its nominal's value: read from a file, its source is the file
                dimension = {**dimension, "nominal": dimension["nominal"]["value"]}
            return (entry["kind"], json.dumps(dimension, sort_keys=True), json.dumps(entry.get("datum")),
                    json.dumps(entry.get("geometric_tolerance"), sort_keys=True), [ref["ref"] for ref in entry["refs"]])

        self.assertEqual(sorted(map(meaning, theirs)), sorted(map(meaning, ours.values())))
        # A nominal the file holds, not one measured here.
        self.assertEqual({entry["dimension"]["nominal"]["source"] for entry in theirs if entry["kind"] == "dimension"},
                         {"file"})
        # The reader of no OCCT: AP242's entities, their values, units and faces, and nothing malformed.
        found = ap242.report(self.step)
        self.assertEqual(found["schema"].split(" ")[0], "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF")
        self.assertEqual(found["problems"], [])
        names = {letter: ours[letter]["refs"][0]["ref"].split("/", 1)[1] for letter in "ABC"}
        datums = {datum["identification"]: datum for datum in found["datums"]}
        self.assertEqual(sorted(datums), ["A", "B", "C"])
        for letter in "ABC":
            [feature] = datums[letter]["features"]
            self.assertEqual(feature["name"], names[letter])
            self.assertEqual(feature["surface"]["type"], "plane")
        dimensions = {entry["entity"]: entry for entry in found["dimensions"]}
        size = dimensions["DIMENSIONAL_SIZE"]
        self.assertEqual((size["name"], size["nominal"]["value"], size["nominal"]["unit"]), ("diameter", 10.0, "mm"))
        self.assertEqual((size["tolerance"]["lower"], size["tolerance"]["upper"], size["tolerance"]["unit"]), (0.0, 0.1, "mm"))
        self.assertEqual(size["features"][0]["surface"]["radius"], 5.0)
        [location] = [d for d in found["dimensions"] if d["entity"] == "DIMENSIONAL_LOCATION" and not d["notes"]]
        self.assertEqual((location["nominal"]["value"], location["tolerance"]["lower"], location["tolerance"]["upper"]),
                         (10.0, -0.2, 0.2))
        self.assertEqual([feature["surface"]["origin"][2] for feature in location["features"]], [-5.0, 5.0])
        tolerances = {entry["entity"]: entry for entry in found["tolerances"]}
        flatness = tolerances["FLATNESS_TOLERANCE"]
        self.assertEqual((flatness["magnitude"]["value"], flatness["magnitude"]["unit"], flatness["datums"]),
                         (0.05, "mm", []))
        position = tolerances["POSITION_TOLERANCE"]
        self.assertEqual((position["magnitude"]["value"], position["datums"], position["zone"]),
                         (0.1, ["A", "B", "C"], "cylindrical or circular"))
        self.assertNotIn("zone_definitions", position)
        self.assertEqual(position["features"][0]["name"], ours["hole-position"]["refs"][0]["ref"].split("/", 1)[1])

    def test_the_saved_document_exports_the_pmi_the_build_wrote(self) -> None:
        """Reopened from its xbf, the document writes a STEP whose PMI is the build's, to a reader of
        no OCCT. (Not its bytes: geometry read back from BinXCAF writes some zeros signed.)"""
        self.build(plate())
        again = self.folder / "again.step"
        export.translate(self.xbf, "step", again)
        self.assertEqual(_said(ap242.report(again)), _said(ap242.report(self.step)))

    def test_a_warm_rebuild_writes_the_same_document(self) -> None:
        self.build(plate())
        first = self.xbf.read_bytes()
        self.xbf.unlink()
        self.build(plate())
        self.assertEqual(self.xbf.read_bytes(), first)

    def test_an_edit_of_the_geometry_is_measured_again(self) -> None:
        self.build(plate())
        self.build(plate(thickness=12, radius=6))
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["thickness"]["dimension"]["nominal"]["value"], 12.0)
        self.assertEqual(found["hole-diameter"]["dimension"]["nominal"]["value"], 12.0)
        # The tolerances are the code's, unchanged by the geometry.
        self.assertEqual(found["thickness"]["dimension"]["tolerance"]["upper"], 0.2)
        self.assertTrue(all(entry["status"] == "ok" for entry in found.values()))
        report = ap242.report(self.step)
        self.assertEqual(sorted((entry["entity"], entry["nominal"]["value"], bool(entry["notes"]))
                                for entry in report["dimensions"]),
                         [("DIMENSIONAL_LOCATION", 12.0, False), ("DIMENSIONAL_LOCATION", 30.0, True),
                          ("DIMENSIONAL_LOCATION", 50.0, True), ("DIMENSIONAL_SIZE", 12.0, False)])

    def test_an_edit_of_a_tolerance_alone_is_written(self) -> None:
        self.build(plate())
        self.build(plate(thickness_tolerance=0.3))
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["thickness"]["dimension"]["tolerance"], {"type": "plus_minus", "upper": 0.3, "lower": -0.3})
        location = next(e for e in ap242.report(self.step)["dimensions"]
                        if e["entity"] == "DIMENSIONAL_LOCATION" and not e["notes"])
        self.assertEqual((location["tolerance"]["lower"], location["tolerance"]["upper"]), (-0.3, 0.3))

    def test_annotations_removed_from_the_code_leave_the_document(self) -> None:
        self.build(plate())
        self.build('''
import build123d as bd
from cadgen.engine import step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
    body.label = "plate"
    return body
''')
        self.assertNotIn("pmi", document.Loaded(self.xbf).structure())
        self.assertEqual(ap242.report(self.step)["datums"], [])


# A plate whose hole is named by its element name, as a viewer's Quick Edit writes it.
NAMED = '''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10)
    {cut}
    body.label = "plate"
    bottom = body.faces().sort_by(bd.Axis.Z)[0]
    return pmi.annotate(
        body,
        pmi.datum("A", bottom),
        pmi.diameter("hole-diameter", "{ref}", tolerance=pmi.plus_minus(0.1, 0)),
    )
'''


class BasicTest(_Folder):
    def test_basic_dimensions_locate_the_hole_from_its_datums_with_no_tolerance(self) -> None:
        self.build(plate())
        loaded = document.Loaded(self.xbf)
        found = _by_id(loaded.structure()["pmi"])
        for id, plane_axis, at, nominal in (("hole-from-B", 1, -30.0, 30.0), ("hole-from-C", 0, -50.0, 50.0)):
            entry = found[id]
            self.assertEqual(entry["status"], "ok", entry)
            self.assertEqual(entry["dimension"], {"type": "distance", "basic": True, "tolerance": None,
                                                  "nominal": {"value": nominal, "unit": "mm", "source": "geometry"}})
            self.assertEqual([ref["role"] for ref in entry["refs"]], ["from", "to"])
            kind, surface = _face(loaded, entry, 0)
            self.assertEqual(kind, "plane")
            self.assertAlmostEqual(surface["origin"][plane_axis], at)
            self.assertEqual(_face(loaded, entry, 1), ("cylinder", {"radius": 5.0}))
            # The datum the frame names, and the hole the position is on: the same faces.
            self.assertEqual(entry["refs"][0]["ref"], found["B" if id.endswith("B") else "C"]["refs"][0]["ref"])
            self.assertEqual(entry["refs"][1]["ref"], found["hole-position"]["refs"][0]["ref"])
        self.assertFalse(found["thickness"]["dimension"]["basic"])

    def test_the_step_marks_them_theoretical_to_occt_and_to_a_reader_of_no_occt(self) -> None:
        self.build(plate())
        report = ap242.report(self.step)
        self.assertEqual(report["problems"], [])
        basic = sorted((d["nominal"]["value"], d["nominal"]["unit"], d["tolerance"], d["notes"],
                        [f["surface"]["type"] for f in d["features"]])
                       for d in report["dimensions"] if d["notes"])
        self.assertEqual(basic, [
            (30.0, "mm", None, [["dimensional note", "theoretical"]], ["plane", "cylinder"]),
            (50.0, "mm", None, [["dimensional note", "theoretical"]], ["plane", "cylinder"])])
        theirs = sorted((e["dimension"]["nominal"]["value"], e["dimension"]["basic"])
                        for e in pmi.read(self.step) if e["kind"] == "dimension")
        self.assertEqual(theirs, [(10.0, False), (10.0, False), (30.0, True), (50.0, True)])

    def test_a_moved_hole_is_measured_again(self) -> None:
        self.build(plate())
        self.build(plate().replace("bd.Cylinder(5, 10)", "bd.Pos(10, 5, 0) * bd.Cylinder(5, 10)"))
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["hole-from-B"]["dimension"]["nominal"]["value"], 35.0)
        self.assertEqual(found["hole-from-C"]["dimension"]["nominal"]["value"], 60.0)

    def test_between_two_hole_axes_and_refused_where_the_axis_crosses_the_plane(self) -> None:
        report = self.build('''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10) - bd.Pos(-20, 0, 0) * bd.Cylinder(4, 10) - bd.Pos(20, 0, 0) * bd.Cylinder(4, 10)
    body.label = "plate"
    top = body.faces().sort_by(bd.Axis.Z)[-1]
    left, right = sorted(body.faces().filter_by(bd.GeomType.CYLINDER), key=lambda face: face.center().X)
    return pmi.annotate(body, pmi.basic("pitch", left, right), pmi.basic("crossing", top, left))
''', ok=False)
        [problem] = report["pmi"]["problems"]
        self.assertEqual((problem["id"], problem["status"]), ("crossing", "invalid"))
        self.assertIn("not parallel", problem["problem"])
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["pitch"]["dimension"]["nominal"]["value"], 40.0)
        self.assertTrue(found["pitch"]["dimension"]["basic"])
        self.assertEqual(found["crossing"]["status"], "invalid")
        self.assertTrue(found["crossing"]["dimension"]["basic"], "an unlinked basic dimension stays basic")

    def test_a_basic_dimension_takes_no_tolerance(self) -> None:
        import build123d as bd

        box = bd.Box(10, 10, 10)
        faces = box.faces().sort_by(bd.Axis.Z)
        with self.assertRaisesRegex(pmi.PMIError, "a basic dimension is theoretically exact"):
            pmi.dimension("b", "distance", faces[0], faces[-1], basic=True, tolerance=pmi.plus_minus(0.1))
        with self.assertRaisesRegex(pmi.PMIUnsupported, "basic"):
            pmi.dimension("d", "diameter", faces[0], basic=True)


# A plate whose one variable ``cut`` is a round hole and then a square pocket: the name the hole's face
# gets from it passes to a flat side of the square, parallel to the left face (the viewer's v3).
CUT = '''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10)
    cut = {cut}
    body = body - cut
    body.label = "plate"
    left = body.faces().sort_by(bd.Axis.X)[0]
    return pmi.annotate(body, pmi.datum("C", left), pmi.basic("hole-from-left", left, {hole}))
'''
ROUND, SQUARE = "bd.Cylinder(5, 10)", "bd.Box(12, 12, 10)"


class FaceKindTest(_Folder):
    def hole_name(self) -> str:
        """The round hole's element name, as the served document names it."""
        self.build(CUT.format(cut=ROUND, hole="body.faces().filter_by(bd.GeomType.CYLINDER)[0]"))
        loaded = document.Loaded(self.xbf)
        faces = pmi._faces(loaded.prototypes[0].shape)
        [ordinal] = [at for at in range(1, faces.Extent() + 1) if pmi._surface(faces.FindKey(at))[0] == "cylinder"]
        return loaded.prototypes[0].face_names[ordinal]

    def named(self, cut: str, name: str, *, ok: bool | None = True) -> dict:
        return self.build(CUT.format(cut=cut, hole=repr(name)), ok=ok)

    def test_a_name_that_comes_to_name_another_kind_of_face_is_warned(self) -> None:
        name = self.hole_name()
        report = self.named(ROUND, name)
        self.assertEqual(report["pmi"]["problems"], [])
        self.assertEqual(_by_id(pmi.read(self.xbf))["hole-from-left"]["dimension"]["nominal"]["value"], 50.0)
        # The hole made a square: the name now names a flat side 44 from the left face. The build says
        # so, as a warning of its report and of the structure it serves; the document is the code's.
        report = self.named(SQUARE, name)
        self.assertEqual(report["pmi"]["problems"], [])
        [warning] = report["pmi"]["warnings"]
        said = f"{name} named a cylinder face on the last build and names a plane face now"
        self.assertTrue(warning.startswith(f"plate/hole-from-left: {said}"), warning)
        served = _by_id(engine_build.held(self.folder / "pmi_plate.py", "pmi_plate").structure["pmi"])
        [text] = served["hole-from-left"]["warnings"]
        self.assertTrue(text.startswith(said), text)
        entry = _by_id(pmi.read(self.xbf))["hole-from-left"]
        self.assertEqual((entry["status"], entry["dimension"]["nominal"]["value"], entry["warnings"]), ("ok", 44.0, []))

    def test_after_a_restart_the_saved_document_is_the_last_build(self) -> None:
        name = self.hole_name()
        self.named(ROUND, name)
        engine_build._WRITTEN.clear()  # a fresh process: nothing of the last build but its xbf
        report = self.named(SQUARE, name)
        self.assertEqual([warning.split(":")[0] for warning in report["pmi"]["warnings"]], ["plate/hole-from-left"])

    def test_the_document_is_the_codes_whatever_was_built_before(self) -> None:
        """The same code and closure make the same xbf, built fresh or after the round hole: it holds
        what the code says and this build's geometry resolves, no status, no word of a previous build."""
        name = self.hole_name()
        self.named(ROUND, name)
        self.named(SQUARE, name, ok=None)
        after = self.xbf.read_bytes()
        self.xbf.unlink()
        engine_build._WRITTEN.clear()
        self.named(SQUARE, name, ok=None)
        self.assertEqual(self.xbf.read_bytes(), after)
        loaded = document.Loaded(self.xbf)
        for record in pmi.records_of_document(loaded.doc, loaded.prototypes, loaded.name):
            self.assertEqual(set(record["extra"]), {"schema", "id", "kind", "label", "presentation", "refs", "unlinked"})

    def test_the_warning_is_the_last_builds_alone(self) -> None:
        name = self.hole_name()
        self.named(ROUND, name)
        self.named(SQUARE, name)
        report = self.named(SQUARE, name)  # built again, unchanged: its last build named the plane
        self.assertNotIn("warnings", report["pmi"])

    def test_a_face_the_code_selects_is_not_held_to_its_kind(self) -> None:
        """A build123d Face is what the code's own selection picks each build: never warned of."""
        self.build(CUT.format(cut=ROUND, hole="body.faces().sort_by(bd.Axis.X)[-1]"))
        report = self.build(CUT.format(cut=ROUND, hole="body.faces().filter_by(bd.GeomType.CYLINDER)[0]"))
        self.assertEqual(report["pmi"], {"annotations": 2, "problems": []})


class AssemblyTest(_Folder):
    def test_each_part_of_an_assembly_carries_its_own_pmi_once_however_often_it_is_placed(self) -> None:
        self.build('''
import build123d as bd
from cadgen.engine import pmi, step, xbf


def pin():
    body = bd.Cylinder(3, 20)
    body.label = "pin"
    return pmi.annotate(body, pmi.diameter("pin-diameter", body.faces().filter_by(bd.GeomType.CYLINDER)[0],
                                           tolerance=pmi.plus_minus(0, -0.01)))


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    base = bd.Box(100, 60, 10)
    base.label = "base"
    base = pmi.annotate(base, pmi.datum("A", base.faces().sort_by(bd.Axis.Z)[0]),
                        pmi.flatness("base-top", base.faces().sort_by(bd.Axis.Z)[-1], 0.02))
    first, second = pin().moved(bd.Pos(-30, 0, 15)), pin().moved(bd.Pos(30, 0, 15))
    first.label, second.label = "pin", "pin"
    return bd.Compound(children=[base, first, second], label="fixture")
''')
        loaded = document.Loaded(self.xbf)
        structure = loaded.structure()
        found = _by_id(structure["pmi"])
        self.assertEqual(sorted(found), ["A", "base-top", "pin-diameter"])
        self.assertTrue(all(entry["status"] == "ok" for entry in found.values()))
        names = [prototype["name"] for prototype in structure["prototypes"]]
        self.assertEqual(names[found["A"]["part"]], "base")
        self.assertEqual(names[found["pin-diameter"]["part"]], "pin")
        self.assertEqual(found["pin-diameter"]["dimension"]["nominal"]["value"], 6.0)
        self.assertEqual(found["pin-diameter"]["dimension"]["tolerance"], {"type": "plus_minus", "upper": 0.0, "lower": -0.01})
        self.assertTrue(found["pin-diameter"]["refs"][0]["ref"].startswith("fixture/pin.1/"), found["pin-diameter"]["refs"])
        self.assertEqual(_face(loaded, found["pin-diameter"]), ("cylinder", {"radius": 3.0}))
        # The STEP: each annotation once, on the part's own face.
        report = ap242.report(self.step)
        self.assertEqual(report["problems"], [])
        self.assertEqual([datum["identification"] for datum in report["datums"]], ["A"])
        [size] = report["dimensions"]
        self.assertEqual((size["nominal"]["value"], size["tolerance"]["lower"], size["tolerance"]["upper"]), (6.0, -0.01, 0.0))
        self.assertEqual(size["features"][0]["surface"]["radius"], 3.0)
        [flatness] = report["tolerances"]
        self.assertEqual((flatness["entity"], flatness["magnitude"]["value"], flatness["magnitude"]["unit"]),
                         ("FLATNESS_TOLERANCE", 0.02, "mm"))
        # OCCT's reader finds a datum through the tolerances naming it only: A, named by none, is in
        # the file (above) but not in what OCCT reads back.
        self.assertEqual(sorted(entry["kind"] for entry in pmi.read(self.step)), ["dimension", "geometric_tolerance"])

    def test_an_annotation_linked_to_nothing_keeps_its_part(self) -> None:
        """Its presentation is in its part's frame: a broken callout of a placed pin is the pin's."""
        self.build('''
import build123d as bd
from cadgen.engine import pmi, xbf


@xbf(out="XBF/pmi_plate.xbf")
def pmi_plate():
    base = bd.Box(100, 60, 10)
    base.label = "base"
    base = pmi.annotate(base, pmi.datum("A", base.faces().sort_by(bd.Axis.Z)[0]))
    pin = bd.Cylinder(3, 20)
    pin.label = "pin"
    pin = pmi.annotate(pin, pmi.diameter("pin-diameter", "face 9", presentation=pmi.place((3, 0, 0), (10, 0, 0))))
    placed = pin.moved(bd.Pos(30, 0, 15))
    placed.label = "pin"
    return bd.Compound(children=[base, placed], label="fixture")
''')
        structure = document.Loaded(self.xbf).structure()
        entry = _by_id(structure["pmi"])["pin-diameter"]
        self.assertEqual(entry["status"], "missing")
        self.assertEqual(structure["prototypes"][entry["part"]]["name"], "pin")
        served = engine_build.held(self.folder / "pmi_plate.py", "pmi_plate").structure["pmi"]
        self.assertEqual(served, structure["pmi"])


class UnitsTest(_Folder):
    def test_a_tolerance_with_no_dimension_beside_it_is_in_millimetres(self) -> None:
        """OCCT's writer takes the GD&T unit from the first dimension and, with none, writes a bare
        metre: the export puts the millimetre back (``export.step._pmi_records``)."""
        self.build('''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf(out="XBF/pmi_plate.xbf")
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10)
    body.label = "plate"
    return pmi.annotate(body, pmi.flatness("top", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))
''')
        [tolerance] = ap242.report(self.step)["tolerances"]
        self.assertEqual((tolerance["magnitude"]["value"], tolerance["magnitude"]["unit"]), (0.05, "mm"))
        self.assertNotIn(b"SI_UNIT($,.METRE.)", self.step.read_bytes())
        self.assertEqual(pmi.read(self.step)[0]["geometric_tolerance"]["value"], 0.05)


class RefTest(_Folder):
    def hole_name(self) -> str:
        """The hole's element name, as the served document names it."""
        self.build(NAMED.format(cut="body = body - bd.Cylinder(5, 10)", ref="face 1"), ok=False)
        loaded = document.Loaded(self.xbf)
        faces = pmi._faces(loaded.prototypes[0].shape)
        [ordinal] = [at for at in range(1, faces.Extent() + 1) if pmi._surface(faces.FindKey(at))[0] == "cylinder"]
        return loaded.prototypes[0].face_names[ordinal]

    def test_a_named_ref_resolves_and_a_lost_one_is_missing_and_kept(self) -> None:
        hole = self.hole_name()
        report = self.build(NAMED.format(cut="body = body - bd.Cylinder(5, 10)", ref=hole))
        self.assertEqual(report["pmi"]["problems"], [])
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["hole-diameter"]["refs"][0]["written"], hole)
        self.assertEqual(found["hole-diameter"]["dimension"]["nominal"]["value"], 10.0)
        # The hole removed: the ref names nothing. The build says so, the xbf keeps the annotation
        # with its status and its tolerance, and the STEP refuses to drop it.
        report = self.build(NAMED.format(cut="pass", ref=hole), ok=False)
        self.assertEqual(report["pmi"]["problems"][0]["id"], "hole-diameter")
        self.assertEqual(report["pmi"]["problems"][0]["status"], "missing")
        self.assertIn("hole-diameter", report["error"])
        self.assertIn("a STEP would drop PMI", report["error"])
        kept = _by_id(pmi.read(self.xbf))["hole-diameter"]
        self.assertEqual(kept["status"], "missing")
        self.assertIn(f"no face {hole}", kept["problem"])
        self.assertEqual(kept["refs"][0]["ref"], hole)
        self.assertEqual(kept["dimension"], {"type": "diameter", "basic": False, "nominal": None,
                                             "tolerance": {"type": "plus_minus", "upper": 0.1, "lower": 0.0}})
        self.assertEqual(_by_id(pmi.read(self.xbf))["A"]["status"], "ok")

    def test_a_face_the_annotation_cannot_stand_on_is_invalid(self) -> None:
        report = self.build(NAMED.format(cut="body = body - bd.Cylinder(5, 10)", ref="face 1"), ok=False)
        [problem] = report["pmi"]["problems"]
        self.assertEqual((problem["id"], problem["status"]), ("hole-diameter", "invalid"))
        self.assertIn("is a plane face; a diameter is on a cylinder face", problem["problem"])

    def test_a_ref_naming_several_faces_is_ambiguous(self) -> None:
        faces = pmi._faces(__import__("build123d").Box(1, 1, 1).wrapped)
        found = pmi._ref({"role": "feature", "written": "f:box.twin.1", "face": None}, faces,
                         ["f:box.twin.1", "f:box.other.1", "f:box.twin.1"], {"box"})
        self.assertEqual((found.status, found.candidates), ("ambiguous", [1, 3]))
        found = pmi._ref({"role": "feature", "written": "box/f:box.other.1", "face": None}, faces,
                         ["f:box.twin.1", "f:box.other.1", "f:box.twin.1"], {"box"})
        self.assertEqual((found.status, found.ordinal), ("ok", 2))
        found = pmi._ref({"role": "feature", "written": "lid/f:box.other.1", "face": None}, faces,
                         ["f:box.twin.1", "f:box.other.1", "f:box.twin.1"], {"box"})
        self.assertEqual(found.status, "invalid")

    def test_a_shape_replaced_after_it_was_annotated_is_said(self) -> None:
        report = self.build('''
import build123d as bd
from cadgen.engine import pmi, xbf


@xbf(out="XBF/pmi_plate.xbf")
def pmi_plate():
    body = bd.Box(100, 60, 10)
    pmi.annotate(body, pmi.flatness("top", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))
    body = bd.fillet(body.edges().filter_by(bd.Axis.Z), 2)
    return body
''')
        self.assertEqual(report["pmi"]["unattached"], ["top"])

    def test_each_model_of_a_script_says_only_the_annotations_its_own_body_lost(self) -> None:
        # The first model keeps its annotations: a run's record taken by its first report would
        # say the second's loss there.
        script = self.folder / "two.py"
        script.write_text(textwrap.dedent('''
            import build123d as bd
            from cadgen.engine import pmi, xbf


            @xbf(out="XBF/whole.xbf")
            def whole():
                body = bd.Box(100, 60, 10)
                return pmi.annotate(body, pmi.flatness("kept", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))


            @xbf(out="XBF/lossy.xbf")
            def lossy():
                body = bd.Box(100, 60, 10)
                pmi.annotate(body, pmi.flatness("top", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))
                return bd.fillet(body.edges().filter_by(bd.Axis.Z), 2)
        '''), encoding="utf-8")
        reports = {report["source"]["name"]: report for report in engine_build.build(script, None, cwd=self.folder)}
        self.assertEqual(reports["lossy"]["pmi"]["unattached"], ["top"])
        self.assertNotIn("unattached", reports["whole"]["pmi"])


class RefusedTest(_Folder):
    def test_what_is_not_supported_is_refused_by_name(self) -> None:
        import build123d as bd

        box = bd.Box(10, 10, 10)
        top = box.faces().sort_by(bd.Axis.Z)[-1]
        with self.assertRaisesRegex(pmi.PMIUnsupported, "perpendicularity is not written verified"):
            pmi.geometric("perp", "perpendicularity", top, 0.1, datums=["A"])
        with self.assertRaisesRegex(pmi.PMIUnsupported, "a radius dimension is not written verified"):
            pmi.dimension("r", "radius", top)
        with self.assertRaisesRegex(pmi.PMIUnsupported, "a tolerance is pmi.plus_minus"):
            pmi.diameter("d", top, tolerance={"type": "fit", "class": "H7"})
        with self.assertRaisesRegex(pmi.PMIUnsupported, "assembly-level PMI"):
            pmi.annotate(bd.Compound(children=[box]), pmi.flatness("f", top, 0.1))
        with self.assertRaisesRegex(pmi.PMIError, r"upper deviation is above its lower \(0.1\), not -0.1"):
            pmi.plus_minus(-0.1, 0.1)
        with self.assertRaisesRegex(pmi.PMIUnsupported, "one position per datum"):
            pmi.annotate(box, pmi.datum("A", top), pmi.datum("B", top),
                         pmi.position("p1", top, 0.1, datums=["A", "B"]), pmi.position("p2", top, 0.1, datums=["B", "A"]))

    def test_an_export_that_makes_the_document_again_is_refused(self) -> None:
        self.build(plate())
        with self.assertRaisesRegex(export.ExportRefused, "PMI annotation"):
            export.translate(self.xbf, "step", self.folder / "part.step", part="plate")
        with self.assertRaisesRegex(export.ExportRefused, "PMI annotation"):
            export.translate(self.xbf, "xbf", self.folder / "part.xbf", part="plate")
        # A mesh carries no PMI, as it carries no B-rep: written.
        export.translate(self.xbf, "stl", self.folder / "plate.stl")


class _Foreign:
    """A document another system wrote: a box holding XCAF's GD&T, made by OCCT directly."""

    def __init__(self, shape: object) -> None:
        from OCP.UnitsMethods import UnitsMethods_LengthUnit_Millimeter
        from OCP.XCAFDoc import XCAFDoc_DocumentTool

        self.shape = shape
        self.doc = document._new_document()
        XCAFDoc_DocumentTool.SetLengthUnit_s(self.doc, 1.0, UnitsMethods_LengthUnit_Millimeter)  # as the engine's are
        self.shapes = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
        self.tool = XCAFDoc_DocumentTool.DimTolTool_s(self.doc.Main())
        self.label = self.shapes.AddShape(shape.wrapped, False, False)

    def sub(self, element: object) -> object:
        from OCP.TDF import TDF_Label

        found = TDF_Label()
        self.shapes.AddSubShape(self.label, element.wrapped, found)
        return found

    def tolerance(self, kind: str, element: object, value: float, **set: object) -> object:
        from OCP import XCAFDimTolObjects as X
        from OCP.XCAFDoc import XCAFDoc_GeomTolerance

        at = self.tool.AddGeomTolerance()
        given = X.XCAFDimTolObjects_GeomToleranceObject()
        given.SetType(getattr(X, f"XCAFDimTolObjects_GeomToleranceType_{kind}"))
        given.SetValue(value)
        for name, argument in set.items():
            getattr(given, name)(*argument)
        XCAFDoc_GeomTolerance.Set_s(at).SetObject(given)
        self.tool.SetGeomTolerance(self.sub(element), at)
        return at

    def dimension(self, kind: str, elements: list, value: float, **set: object) -> object:
        from OCP import XCAFDimTolObjects as X
        from OCP.XCAFDoc import XCAFDoc_Dimension

        at = self.tool.AddDimension()
        given = X.XCAFDimTolObjects_DimensionObject()
        given.SetType(getattr(X, f"XCAFDimTolObjects_DimensionType_{kind}"))
        given.SetValue(value)
        for name, argument in set.items():
            getattr(given, name)(*argument)
        XCAFDoc_Dimension.Set_s(at).SetObject(given)
        self.tool.SetDimension(*map(self.sub, elements), at)
        return at

    def step(self, path: Path) -> Path:
        from cadgen.engine.export.step import write_document

        self.shapes.UpdateAssemblies()
        write_document(self.doc, path)
        return path

    def xbf(self, path: Path) -> Path:
        self.shapes.UpdateAssemblies()
        document.save(self.doc, path, compare=False)
        return path


def _meaning(entry: dict) -> tuple:
    """What an entry says, its id and refs' spelling apart."""
    return (entry["kind"], entry["status"], entry["xcaf_type"], entry.get("reason"),
            json.dumps({key: entry.get(key) for key in ("datum", "dimension", "geometric_tolerance", "values")},
                       sort_keys=True), [(ref["role"], ref["status"]) for ref in entry["refs"]])


class ForeignTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="engine-pmi-foreign-")).resolve()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_pmi_this_module_does_not_model_is_listed_as_unsupported(self) -> None:
        """A STEP written with a cylindricity (XCAF's, by OCCT directly) reads back listed. (OCCT's
        writer drops a perpendicularity that names no datum, silently: hence a form tolerance.)"""
        import build123d as bd

        box = bd.Box(10, 10, 10)
        foreign = _Foreign(box)
        foreign.tolerance("Cylindricity", box.faces().sort_by(bd.Axis.Z)[-1], 0.2)
        [entry] = pmi.read(foreign.step(self.folder / "foreign.step"))
        self.assertEqual((entry["kind"], entry["xcaf_type"], entry["status"]),
                         ("unsupported", "XCAFDimTolObjects_GeomToleranceType_Cylindricity", "ok"))
        self.assertIn("cylindricity", entry["reason"])
        self.assertEqual(entry["values"]["value"], 0.2)

    def test_what_a_file_says_beyond_the_model_is_unsupported_with_why(self) -> None:
        """A diameter with limits or a flatness with a projected zone says more than a plain one: it
        is listed unsupported, saying why, never read as the plain one. A nominal read from a file
        was measured by nothing here: its source is the file."""
        import build123d as bd
        from OCP import XCAFDimTolObjects as X

        body = bd.Box(20, 20, 10) - bd.Cylinder(4, 10)
        top, hole = body.faces().sort_by(bd.Axis.Z)[-1], body.faces().filter_by(bd.GeomType.CYLINDER)[0]
        foreign = _Foreign(body)
        foreign.dimension("Size_Diameter", [hole], 8.0, SetLowerBound=(7.9,), SetUpperBound=(8.1,))
        foreign.dimension("Size_Diameter", [hole], 8.0, SetLowerTolValue=(0.0,), SetUpperTolValue=(0.1,))
        foreign.tolerance("Flatness", top, 0.2, SetZoneModifier=(X.XCAFDimTolObjects_GeomToleranceZoneModif_Projected,),
                          SetValueOfZoneModifier=(5.0,))
        foreign.tolerance("Flatness", top, 0.1, SetMaxValueModifier=(0.3,))
        ranged, plain, projected, capped = pmi.read(foreign.xbf(self.folder / "foreign.xbf"))
        self.assertEqual((ranged["kind"], ranged["xcaf_type"]), ("unsupported", "XCAFDimTolObjects_DimensionType_Size_Diameter"))
        self.assertIn("limits", ranged["reason"])
        self.assertEqual(plain["kind"], "dimension")
        self.assertEqual(plain["dimension"]["nominal"], {"value": 8.0, "unit": "mm", "source": "file"})
        self.assertEqual(plain["dimension"]["tolerance"], {"type": "plus_minus", "upper": 0.1, "lower": 0.0})
        self.assertEqual((projected["kind"], projected["xcaf_type"]), ("unsupported", "XCAFDimTolObjects_GeomToleranceType_Flatness"))
        self.assertIn("projected", projected["reason"])
        self.assertIn("maximum", capped["reason"])

    def test_a_vendor_step_converts_and_exports_its_pmi_as_read(self) -> None:
        """A vendor's STEP (the skill's vendor workflow): its xbf keeps the file's GD&T as read, and a
        STEP of either is written. A distance between two edges is no annotation on faces: listed,
        linked to its edges and kept, never refused and never drawn."""
        import build123d as bd

        box = bd.Box(10, 10, 10)
        foreign = _Foreign(box)
        foreign.tolerance("Flatness", box.faces().sort_by(bd.Axis.Z)[-1], 0.2)
        edges = box.edges().filter_by(bd.Axis.Z)
        foreign.dimension("Location_LinearDistance", [edges[0], edges[1]], 10.0)
        vendor = foreign.step(self.folder / "vendor.step")
        flatness, distance = sorted(pmi.read(vendor), key=lambda entry: entry["kind"])
        self.assertEqual((flatness["kind"], flatness["status"]), ("geometric_tolerance", "ok"))
        self.assertEqual((distance["kind"], distance["status"], distance["reason"]), ("unsupported", "ok", "linked to an edge"))
        self.assertEqual(distance["xcaf_type"], "XCAFDimTolObjects_DimensionType_Location_LinearDistance")
        self.assertTrue(all("/edge " in ref["ref"] and ref["status"] == "ok" for ref in distance["refs"]), distance["refs"])
        read = sorted(map(_meaning, pmi.read(vendor)))
        export.translate(vendor, "xbf", self.folder / "vendor.xbf")
        self.assertEqual(sorted(map(_meaning, pmi.read(self.folder / "vendor.xbf"))), read)
        for source in (vendor, self.folder / "vendor.xbf"):
            export.translate(source, "step", self.folder / "again.step")
            self.assertEqual(sorted(map(_meaning, pmi.read(self.folder / "again.step"))), read)

    def test_an_export_of_a_foreign_document_says_what_it_leaves_out(self) -> None:
        """A partial STEP is a document made again, which carries no PMI: written, and said."""
        import build123d as bd

        from cadgen.engine.worker import _export

        box = bd.Box(10, 10, 10)
        foreign = _Foreign(box)
        foreign.tolerance("Flatness", box.faces().sort_by(bd.Axis.Z)[-1], 0.2)
        vendor = foreign.step(self.folder / "vendor.step")
        said: list[str] = []
        part = self.folder / "part.step"
        _export({"source": {"path": str(vendor)}, "destinations": [str(part)], "part": document.Loaded(vendor).name},
                said.append)
        self.assertTrue(part.is_file())
        self.assertEqual([text for text in said if text.startswith("warning: pmi:")],
                         ["warning: pmi: part.step: geometric_tolerance-1 is not carried whole: a partial STEP is a "
                          "document made again, which carries no PMI"])


class FixtureTest(_Folder):
    def test_the_committed_fixture_is_a_fresh_builds_pmi(self) -> None:
        """``pmi_golden/pmi_plate.step`` says what a build of the example says, to a reader of no OCCT;
        and ``pmi_golden/pmi_plate.pmi.json`` is the structure's ``pmi`` a viewer is served."""
        self.build(plate())
        if WRITE:
            shutil.copyfile(self.step, FIXTURE / "pmi_plate.step")
            shutil.copyfile(self.xbf, FIXTURE / "pmi_plate.xbf")
            (FIXTURE / "pmi_plate.pmi.json").write_text(json.dumps(pmi.read(self.xbf), indent=2) + "\n", encoding="utf-8")
        self.assertEqual(_said(ap242.report(FIXTURE / "pmi_plate.step")), _said(ap242.report(self.step)))
        served = json.loads((FIXTURE / "pmi_plate.pmi.json").read_text(encoding="utf-8"))
        self.assertEqual(served, pmi.read(self.xbf))
        self.assertEqual(served, pmi.read(FIXTURE / "pmi_plate.xbf"))


if __name__ == "__main__":
    unittest.main()
