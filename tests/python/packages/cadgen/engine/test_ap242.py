"""An exported file's requirements must match its source, without guessing identities
(``export/ap242.py``): the AP242 reader of no OCCT, and ``compare``/``verify`` of a document's PMI
against the file it wrote."""

from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cadgen.engine.export.ap242 import Report, compare, parse, report, verify

GOLDEN = Path(__file__).resolve().parent / "pmi_golden"


def fixtures() -> tuple[list[dict], dict]:
    """Three entries as a document serves them, and the report of a file that holds them."""
    entries = [
        {"id": "A", "kind": "datum", "status": "ok", "refs": [{"ref": "part/f:base.1"}], "datum": {"letter": "A"}},
        {"id": "bore", "kind": "dimension", "status": "ok", "refs": [{"ref": "part/f:bore.1"}],
         "dimension": {"type": "diameter", "nominal": {"value": 10, "unit": "mm"},
                       "tolerance": {"type": "plus_minus", "lower": 0, "upper": 0.05}}},
        {"id": "position", "kind": "geometric_tolerance", "status": "ok", "refs": [{"ref": "part/f:bore.1"}],
         "geometric_tolerance": {"characteristic": "position", "value": 0.1, "unit": "mm", "zone": "diameter",
                                 "datums": ["A"]}},
    ]
    found = {"schema": "AP242_TEST", "problems": [], "ambiguousFaceNames": [],
             "datums": [{"identification": "A", "features": [{"name": "f:base.1"}]}],
             "dimensions": [{"name": "diameter", "features": [{"name": "f:bore.1"}],
                             "nominal": {"value": 10, "unit": "mm"},
                             "tolerance": {"lower": 0, "upper": 0.05, "unit": "mm"}}],
             "tolerances": [{"entity": "POSITION_TOLERANCE", "features": [{"name": "f:bore.1"}],
                             "magnitude": {"value": 0.1, "unit": "mm"}, "zone": "cylindrical or circular",
                             "datums": ["A"]}]}
    return entries, found


class VerificationTest(unittest.TestCase):
    def test_reader_refuses_unchecked_exported_tolerance_extensions(self) -> None:
        records = parse((GOLDEN / "pmi_plate.step").read_text(encoding="utf-8"))
        number = next(number for number, parts in records.items() if any(name == "POSITION_TOLERANCE" for name, _ in parts))
        for extension in ("GEOMETRIC_TOLERANCE_WITH_MODIFIERS", "GEOMETRIC_TOLERANCE_WITH_MAXIMUM_TOLERANCE"):
            altered = copy.deepcopy(records)
            altered[number].append((extension, (("MAXIMUM_MATERIAL_REQUIREMENT",),)))
            reader = Report(altered)
            reader.tolerances()
            self.assertTrue(any(extension in problem for problem in reader.problems), reader.problems)

    def test_matches_and_detects_changed_values_units_faces_datums_and_extras(self) -> None:
        entries, found = fixtures()
        self.assertEqual(compare(entries, found), {"matched": 3, "total": 3, "problems": []})
        for collection, key, value in [("dimensions", "tolerance", {"lower": 0, "upper": 0.5, "unit": "mm"}),
                                       ("tolerances", "magnitude", {"value": 0.1, "unit": "m"}),
                                       ("datums", "features", [{"name": "f:wrong.1"}]),
                                       ("tolerances", "datums", ["B"])]:
            changed = copy.deepcopy(found)
            changed[collection][0][key] = value
            self.assertTrue(compare(entries, changed)["problems"])
        found["dimensions"] *= 2
        self.assertTrue(compare(entries, found)["problems"])

    def test_ambiguous_associations_fail_closed(self) -> None:
        entries, found = fixtures()
        for altered in [{**found, "ambiguousFaceNames": ["f:bore.1"]},
                        {key: value for key, value in found.items() if key != "ambiguousFaceNames"},
                        {**found, "datums": found["datums"] * 2},
                        {**found, "problems": ["Mixed deviation units"]},
                        {**found, "schema": "AUTOMOTIVE_DESIGN"}]:
            self.assertEqual(compare(entries, altered)["matched"], 0)
        other = copy.deepcopy(entries[1])
        other["refs"][0]["ref"] = "other/f:bore.1"
        self.assertEqual(compare(entries + [other], found)["matched"], 0)

    def test_unsupported_modifiers_and_empty_pmi_never_claim_success(self) -> None:
        entries, found = fixtures()
        entries[2]["geometric_tolerance"]["modifier"] = "maximum_material_condition"
        self.assertEqual(compare(entries, found)["matched"], 2)
        self.assertTrue(compare([], {**found, "datums": [], "dimensions": [], "tolerances": []})["problems"])

    def test_checks_the_provided_export_and_binds_result_to_its_bytes(self) -> None:
        entries, found = fixtures()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "export.step"
            target.write_bytes(b"exported bytes")
            with patch("cadgen.engine.export.ap242.report", return_value=found) as reader:
                result = verify(entries, target)
            reader.assert_called_once_with(target, b"exported bytes")
            self.assertEqual(result["matched"], 3)
            self.assertEqual(result["sha256"], hashlib.sha256(b"exported bytes").hexdigest())
            with patch("cadgen.engine.export.ap242.report", side_effect=ValueError("unsupported syntax")):
                self.assertTrue(verify(entries, target)["problems"])

    def test_the_committed_fixture_verifies_whole_basic_dimensions_included(self) -> None:
        """The plate's served PMI against its own exported STEP: every annotation, its two basic
        dimensions too (their 'theoretical' note), matched one to one."""
        from cadgen.engine import pmi

        entries = pmi.read(GOLDEN / "pmi_plate.xbf")
        self.assertEqual(sum(1 for entry in entries if (entry.get("dimension") or {}).get("basic")), 2)
        result = verify(entries, GOLDEN / "pmi_plate.step")
        self.assertEqual((result["matched"], result["total"], result["problems"]), (9, 9, []))

    def test_a_basic_flag_the_file_does_not_carry_is_not_verified(self) -> None:
        entries, found = fixtures()
        entries.append({"id": "hole-from-B", "kind": "dimension", "status": "ok",
                        "refs": [{"ref": "part/f:front.1"}, {"ref": "part/f:bore.1"}],
                        "dimension": {"type": "distance", "basic": True, "nominal": {"value": 30, "unit": "mm"},
                                      "tolerance": None}})
        row = {"name": "linear distance", "features": [{"name": "f:front.1"}, {"name": "f:bore.1"}],
               "nominal": {"value": 30, "unit": "mm"}, "tolerance": None, "notes": [["dimensional note", "theoretical"]]}
        self.assertEqual(compare(entries, {**found, "dimensions": found["dimensions"] + [row]})["matched"], 4)
        bare = {**row, "notes": []}  # the same distance with no 'theoretical' note: not the basic one modelled
        self.assertEqual(compare(entries, {**found, "dimensions": found["dimensions"] + [bare]})["matched"], 3)

    def test_reader_checks_unannotated_face_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            step = Path(temp) / "duplicate.step"
            step.write_text("ISO-10303-21; HEADER; FILE_SCHEMA(('AP242_TEST')); ENDSEC; DATA;\n"
                            "#1=ADVANCED_FACE('f:bore.1',(),$,.T.);\n"
                            "#2=ADVANCED_FACE('f:bore.1',(),$,.T.);\nENDSEC; END-ISO-10303-21;", encoding="utf-8")
            self.assertEqual(report(step)["ambiguousFaceNames"], ["f:bore.1"])

    def test_reader_checks_both_deviation_units(self) -> None:
        reader = Report(parse("""ISO-10303-21; HEADER; ENDSEC; DATA;
          #1=PLUS_MINUS_TOLERANCE(#2,#3,$);
          #2=TOLERANCE_VALUE(#4,#5);
          #3=DIMENSIONAL_SIZE($,'diameter');
          #4=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(-0.2),#6);
          #5=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.2),#7);
          #6=SI_UNIT($,.METRE.);
          #7=SI_UNIT(.MILLI.,.METRE.);
          ENDSEC; END-ISO-10303-21;"""))
        reader.plus_minus(3)
        self.assertTrue(any("unit" in problem.lower() for problem in reader.problems))


if __name__ == "__main__":
    unittest.main()
