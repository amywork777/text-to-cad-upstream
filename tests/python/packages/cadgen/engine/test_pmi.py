"""Semantic PMI (``cadgen.engine.pmi``): a plate's datums, dimensions and geometric tolerances
written into its xbf as XCAF's GD&T objects and read back the same from the file as from the
build; its AP242 STEP read by OCCT and by a reader of no OCCT (``scripts/pmi/ap242_pmi_report``),
which agree on values, units, datum frames and the faces each annotation is on; a warm rebuild,
an edit of the geometry and of a tolerance, a ref the model no longer satisfies (missing,
ambiguous, invalid) kept in the document and refused by a STEP; what is not supported refused
by name; and the committed fixture (``docs/pmi``) the same as a fresh build's."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from cadgen.engine import build as engine_build
from cadgen.engine import document, export, pmi

ROOT = Path(__file__).resolve().parents[5]
FIXTURE = ROOT / "docs" / "pmi"


def _reporter():
    """The AP242 reader of no OCCT (``scripts/pmi``), loaded by its path."""
    held = sys.modules.get("ap242_pmi_report")
    if held is not None:
        return held
    spec = importlib.util.spec_from_file_location("ap242_pmi_report", ROOT / "scripts" / "pmi" / "ap242_pmi_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ap242_pmi_report"] = module
    spec.loader.exec_module(module)
    return module


# The fixture's model (``models/examples/src/pmi_plate.py``): tolerance values ILLUSTRATIVE.
PLATE = '''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, {thickness}) - bd.Cylinder({radius}, {thickness})
    body.label = "plate"
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
    )
'''


def plate(thickness: float = 10, radius: float = 5, thickness_tolerance: float = 0.2) -> str:
    return PLATE.format(thickness=thickness, radius=radius, thickness_tolerance=thickness_tolerance)


class _Folder(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="engine-pmi-")).resolve()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def build(self, source: str, name: str = "pmi_plate", *, ok: bool = True) -> dict:
        script = self.folder / f"{name}.py"
        script.write_text(textwrap.dedent(source), encoding="utf-8")
        os.utime(script, ns=(time.time_ns(), time.time_ns()))
        report = engine_build.build(script, [name], cwd=self.folder)[0]
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


def _face(loaded: document.Loaded, entry: dict, at: int = 0) -> tuple[str, dict]:
    """The surface of the face an entry's ``at``-th ref names, from the document's own geometry."""
    from cadgen.engine.refs import resolve_structure

    [hit] = resolve_structure(loaded.structure(), entry["refs"][at]["ref"])
    prototype = loaded.prototypes[hit.node.payload["prototype"]]
    return pmi._surface(pmi._faces(prototype.shape).FindKey(hit.ordinal))


class PlateTest(_Folder):
    def test_the_document_holds_each_annotation_on_its_face(self) -> None:
        report = self.build(plate())
        self.assertEqual(report["pmi"], {"annotations": 7, "problems": []})
        loaded = document.Loaded(self.xbf)
        found = _by_id(loaded.structure()["pmi"])
        self.assertEqual(list(found), ["A", "B", "C", "thickness", "hole-diameter", "top-flatness", "hole-position"])
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
            "type": "distance", "nominal": {"value": 10.0, "unit": "mm", "source": "geometry"},
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
            return (entry["kind"], json.dumps(entry.get("dimension"), sort_keys=True), json.dumps(entry.get("datum")),
                    json.dumps(entry.get("geometric_tolerance"), sort_keys=True), [ref["ref"] for ref in entry["refs"]])

        self.assertEqual(sorted(map(meaning, theirs)), sorted(map(meaning, ours.values())))
        # The reader of no OCCT: AP242's entities, their values, units and faces, and nothing malformed.
        found = _reporter().report(self.step)
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
        location = dimensions["DIMENSIONAL_LOCATION"]
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
        reporter = _reporter()
        fresh, reopened = reporter.report(self.step), reporter.report(again)
        fresh.pop("file"), reopened.pop("file")
        self.assertEqual(reopened, fresh)

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
        report = _reporter().report(self.step)
        self.assertEqual({entry["entity"]: entry["nominal"]["value"] for entry in report["dimensions"]},
                         {"DIMENSIONAL_SIZE": 12.0, "DIMENSIONAL_LOCATION": 12.0})

    def test_an_edit_of_a_tolerance_alone_is_written(self) -> None:
        self.build(plate())
        self.build(plate(thickness_tolerance=0.3))
        found = _by_id(pmi.read(self.xbf))
        self.assertEqual(found["thickness"]["dimension"]["tolerance"], {"type": "plus_minus", "upper": 0.3, "lower": -0.3})
        location = next(e for e in _reporter().report(self.step)["dimensions"] if e["entity"] == "DIMENSIONAL_LOCATION")
        self.assertEqual((location["tolerance"]["lower"], location["tolerance"]["upper"]), (-0.3, 0.3))

    def test_annotations_removed_from_the_code_leave_the_document(self) -> None:
        self.build(plate())
        self.build('''
import build123d as bd
from cadgen.engine import step, xbf


@xbf
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
    body.label = "plate"
    return body
''')
        self.assertNotIn("pmi", document.Loaded(self.xbf).structure())
        self.assertEqual(_reporter().report(self.step)["datums"], [])


# A plate whose hole is named by its element name, as a viewer's Quick Edit writes it.
NAMED = '''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf
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


@xbf
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
        report = _reporter().report(self.step)
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


class UnitsTest(_Folder):
    def test_a_tolerance_with_no_dimension_beside_it_is_in_millimetres(self) -> None:
        """OCCT's writer takes the GD&T unit from the first dimension and, with none, writes a bare
        metre: the export puts the millimetre back (``export.step._pmi_records``)."""
        self.build('''
import build123d as bd
from cadgen.engine import pmi, step, xbf


@xbf
@step(out="pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10)
    body.label = "plate"
    return pmi.annotate(body, pmi.flatness("top", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))
''')
        [tolerance] = _reporter().report(self.step)["tolerances"]
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
        self.assertEqual(kept["dimension"], {"type": "diameter", "nominal": None,
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


@xbf
def pmi_plate():
    body = bd.Box(100, 60, 10)
    pmi.annotate(body, pmi.flatness("top", body.faces().sort_by(bd.Axis.Z)[-1], 0.05))
    body = bd.fillet(body.edges().filter_by(bd.Axis.Z), 2)
    return body
''')
        self.assertEqual(report["pmi"]["unattached"], ["top"])


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
        with self.assertRaisesRegex(pmi.PMIError, "upper deviation"):
            pmi.plus_minus(-0.1, 0.1)
        with self.assertRaisesRegex(pmi.PMIUnsupported, "one position per datum"):
            pmi.annotate(box, pmi.datum("A", top), pmi.datum("B", top),
                         pmi.position("p1", top, 0.1, datums=["A", "B"]), pmi.position("p2", top, 0.1, datums=["B", "A"]))

    def test_an_export_that_makes_the_document_again_is_refused(self) -> None:
        self.build(plate())
        with self.assertRaisesRegex(export.ExportRefused, "PMI annotation"):
            export.translate(self.step, "xbf", self.folder / "from_step.xbf")
        with self.assertRaisesRegex(export.ExportRefused, "PMI annotation"):
            export.translate(self.xbf, "step", self.folder / "part.step", part="plate")
        # A mesh carries no PMI, as it carries no B-rep: written.
        export.translate(self.xbf, "stl", self.folder / "plate.stl")


class ForeignTest(unittest.TestCase):
    def test_pmi_this_module_does_not_model_is_listed_as_unsupported(self) -> None:
        """A STEP written with a cylindricity (XCAF's, by OCCT directly) reads back listed. (OCCT's
        writer drops a perpendicularity that names no datum, silently: hence a form tolerance.)"""
        import build123d as bd
        from OCP import XCAFDimTolObjects as X
        from OCP.TDF import TDF_Label
        from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_GeomTolerance

        from cadgen.engine.export.step import write_document

        folder = Path(tempfile.mkdtemp(prefix="engine-pmi-foreign-")).resolve()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        from OCP.UnitsMethods import UnitsMethods_LengthUnit_Millimeter

        doc = document._new_document()
        XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 1.0, UnitsMethods_LengthUnit_Millimeter)  # as the engine's are
        shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        box = bd.Box(10, 10, 10)
        label = shapes.AddShape(box.wrapped, False, False)
        face = TDF_Label()
        shapes.AddSubShape(label, box.faces().sort_by(bd.Axis.Z)[-1].wrapped, face)
        tool = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
        at = tool.AddGeomTolerance()
        given = X.XCAFDimTolObjects_GeomToleranceObject()
        given.SetType(X.XCAFDimTolObjects_GeomToleranceType_Cylindricity)
        given.SetValue(0.2)
        XCAFDoc_GeomTolerance.Set_s(at).SetObject(given)
        tool.SetGeomTolerance(face, at)
        shapes.UpdateAssemblies()
        path = folder / "foreign.step"
        write_document(doc, path)
        [entry] = pmi.read(path)
        self.assertEqual((entry["kind"], entry["xcaf_type"], entry["status"]),
                         ("unsupported", "XCAFDimTolObjects_GeomToleranceType_Cylindricity", "ok"))
        self.assertEqual(entry["values"]["value"], 0.2)


class FixtureTest(_Folder):
    def test_the_committed_fixture_is_a_fresh_builds_pmi(self) -> None:
        """``docs/pmi/pmi_plate.step`` says what a build of the example says, to a reader of no OCCT;
        and ``docs/pmi/pmi_plate.pmi.json`` is the structure's ``pmi`` a viewer is served."""
        self.build(plate())
        reporter = _reporter()
        fresh, committed = reporter.report(self.step), reporter.report(FIXTURE / "pmi_plate.step")
        for found in (fresh, committed):
            found.pop("file")
        self.assertEqual(committed, fresh)
        served = json.loads((FIXTURE / "pmi_plate.pmi.json").read_text(encoding="utf-8"))
        self.assertEqual(served, pmi.read(self.xbf))
        self.assertEqual(served, pmi.read(FIXTURE / "pmi_plate.xbf"))


if __name__ == "__main__":
    unittest.main()
