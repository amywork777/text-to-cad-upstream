"""``@work_instruction``: the steps to build one assembly, as a PDF.

The assembly is three boxes built here -- a base plate, a bracket on it and two
pins of one label on the bracket -- so every part ref and face is known from the
construction. Most tests write with ``pictures=False``, which needs no browser;
one renders the pictures through the real snapshot runtime, because the marks
and the selection are validated there and nowhere else.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from tests.python.support.paths import add_repo_path
from tests.python.support.tmp_root import generated_cad_directory

add_repo_path("packages/cadgen/src")


_FIXTURE: dict[str, Path] = {}


def setUpModule() -> None:
    """One assembly and one store for every test here: its scene compiles once."""
    from build123d import Box, Compound, Pos
    from cadgen.step_export import export_build123d_step_file

    temporary = generated_cad_directory(prefix="work-instruction-")
    unittest.addModuleCleanup(temporary.cleanup)
    root = Path(temporary.name)
    patch = mock.patch.dict(os.environ, {
        "CADGEN_CACHE_DIR": str(root / "store"), "CADGEN_DAEMON": "0", "CADGEN_COMPONENT_WORKERS": "1",
    })
    patch.start()
    unittest.addModuleCleanup(patch.stop)
    base = Box(100, 60, 10)
    base.label = "base_plate"
    bracket = Pos(0, 0, 25) * Box(40, 40, 40)
    bracket.label = "bracket"
    pins = []
    for x in (-10, 10):
        pin = Pos(x, 0, 50) * Box(4, 4, 10)
        pin.label = "pin"
        pins.append(pin)
    step = root / "assembly.step"
    export_build123d_step_file(Compound(children=[base, bracket, *pins], label="assembly"), step)
    _FIXTURE.update(root=root, step=step)


class _Assembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root, cls.step = _FIXTURE["root"], _FIXTURE["step"]

    def instruction(self, **kwargs):
        from cadgen.work_instruction import Instruction

        kwargs.setdefault("pictures", False)
        return Instruction(self.step, title="BRACKET ASSEMBLY", number="WI-1", revision="A", **kwargs)


def _sources():
    from cadgen.work_instruction import Drawing, Spec

    return Spec("PS-2001", "Threaded fastener installation", revision="D"), Drawing("DWG-1", revision="B")


class _Page:
    """A matplotlib axes that keeps the text drawn on it and draws nothing."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def text(self, _x, _y, value, **_kwargs) -> None:
        self.texts.append(value)

    def plot(self, *_args, **_kwargs) -> None:
        pass

    add_patch = imshow = plot


def _page_texts(wi) -> list[list[str]]:
    """Each page's text, laid out as the PDF is (no pictures)."""
    from cadgen._internal.work_instruction_pages import draw_page, layout

    items = wi.open_items()
    flow = layout(wi, items, {})
    pages = []
    for index in range(1, len(flow.pages) + 1):
        page = _Page()
        draw_page(page, flow, index, len(items))
        pages.append(page.texts)
    return pages


class SourceTests(unittest.TestCase):
    def test_every_process_value_names_where_it_comes_from(self) -> None:
        from cadgen.work_instruction import Adhesive, Cure, Machining, Material, Torque

        for make in (lambda: Torque(20, 25, "in-lbf"), lambda: Adhesive("EA 9394", mix="100:17"),
                     lambda: Cure("cure", cycle="1 h at 150 F"), lambda: Machining("drill", tool="#21"),
                     lambda: Material("Loctite 242")):
            with self.subTest(make=make), self.assertRaisesRegex(TypeError, r"Spec\(\.\.\.\)\.at"):
                make()

    def test_a_source_names_a_known_kind_a_document_and_where_in_it(self) -> None:
        from cadgen.work_instruction import Source

        for kind, document, where in (("bogus", "X", "y"), ("stated", "", ""), ("spec", "PS-1 Rev A", "")):
            with self.subTest(kind=kind, document=document), self.assertRaises((ValueError, TypeError)):
                Source(kind, document, where)

    def test_a_field_from_a_second_document_cites_that_document(self) -> None:
        from cadgen.work_instruction import Adhesive, Cited, Datasheet

        spec, _ = _sources()
        tds = Datasheet("EA 9394", revision="2019-05")
        adhesive = Adhesive("EA 9394", prep="IPA wipe", mix=Cited("100:17", per=tds.at("Mixing")),
                            per=spec.at("5.1"))
        cites = {caption: source.cite() if source else None for caption, _text, source in adhesive.fields()}
        self.assertEqual(cites, {"prep": "PS-2001 Rev D \u00a75.1", "mix": "EA 9394 datasheet, 2019-05, Mixing",
                                 "pot life": None, "cure": None})
        self.assertEqual(adhesive.missing(), ["pot life", "cure"])

    def test_a_torque_prints_the_numbers_given(self) -> None:
        from cadgen.work_instruction import Torque

        spec, _ = _sources()
        self.assertEqual(Torque(12.345678, unit="N-m", per=spec.at("4")).text(), "12.345678 N-m")
        self.assertEqual(Torque(40.0, 45, "in-lbf", per=spec.at("4")).text(), "40\u201345 in-lbf")

    def test_a_citation_says_which_document_and_where(self) -> None:
        from cadgen.work_instruction import Stated

        spec, drawing = _sources()
        self.assertEqual(spec.at("4.2, Table 3").cite(), "PS-2001 Rev D §4.2, Table 3")
        self.assertEqual(drawing.at("note 4").cite(), "DWG-1 Rev B, note 4 (drawing callout)")
        self.assertEqual(Stated("A. Zhou", on="2026-10-23").cite(), "stated by A. Zhou, 2026-10-23")


class VocabularyTests(_Assembly):
    def test_closed_sets_refuse_what_they_do_not_name(self) -> None:
        from cadgen.work_instruction import Instruction, Torque

        spec, _ = _sources()
        cases = [
            (ValueError, lambda: Torque(20, unit="Nm", per=spec.at("4"))),
            (ValueError, lambda: Torque(30, 20, "in-lbf", per=spec.at("4"))),
            (ValueError, lambda: Torque(0, unit="in-lbf", per=spec.at("4"))),
            (ValueError, lambda: self.instruction(status="approved")),
            (ValueError, lambda: self.instruction(camera="isometric")),
            (ValueError, lambda: self.instruction(size="A3")),
            (ValueError, lambda: Instruction(self.step, title="  ", number="WI-1", revision="A", pictures=False)),
            (TypeError, lambda: self.instruction().step("Load", install="base_plate")),
            (ValueError, lambda: self.instruction().step("Load", install=["base_plate"]).bond(None, surfaces=["#o1.1"])),
        ]
        for error, make in cases:
            with self.subTest(make=make), self.assertRaises(error):
                make()

    def test_a_single_part_is_not_an_assembly(self) -> None:
        from build123d import Box
        from cadgen.step_export import export_build123d_step_file
        from cadgen.work_instruction import Instruction

        single = self.root / "single.step"
        export_build123d_step_file(Box(1, 1, 1), single)
        with self.assertRaisesRegex(TypeError, "single part"):
            Instruction(single, title="T", number="N", revision="A", pictures=False)


class PartTests(_Assembly):
    def test_a_label_installs_every_part_that_carries_it(self) -> None:
        wi = self.instruction()
        self.assertEqual(wi.step("Pins", install=["pin"]).install, ("#o1.3", "#o1.4"))

    def test_a_surface_is_resolved_to_one_face_when_the_step_names_it(self) -> None:
        step = self.instruction().step("Load", install=["bracket"])
        self.assertEqual(step.bond(None, surfaces=["#o1.2.f5"]).ops[-1].surfaces, (("#o1.2.f5", "#o1.2"),))
        with self.assertRaisesRegex(ValueError, "face refs"):
            step.bond(None, surfaces=["#o1.2"])
        with self.assertRaisesRegex(ValueError, "is not on assembly.step"):
            step.bond(None, surfaces=["#o1.9.f1"])

    def test_an_unknown_part_is_refused_with_the_parts_there_are(self) -> None:
        with self.assertRaisesRegex(KeyError, r"#o1\.2 bracket"):
            self.instruction().step("Load", install=["brackett"])

    def test_a_refused_step_leaves_its_parts_for_the_next(self) -> None:
        wi = self.instruction()
        with self.assertRaises(ValueError):
            wi.step("Load", install=["base_plate"], camera="isometric")
        self.assertEqual(wi.step("Load", install=["base_plate"]).install, ("#o1.1",))

    def test_a_part_is_installed_by_one_step(self) -> None:
        wi = self.instruction()
        wi.step("Load", install=["base_plate"])
        with self.assertRaisesRegex(ValueError, "step 1 already installs"):
            wi.step("Again", install=["#o1.1"])


class OpenItemTests(_Assembly):
    def _wi(self, **kwargs):
        from cadgen.work_instruction import Adhesive, Torque

        spec, drawing = _sources()
        kwargs.setdefault("rigor", "controlled")
        wi = self.instruction(**kwargs)
        wi.step("Load", install=["base_plate"])
        wi.step("Bond", install=["bracket"]).bond(
            Adhesive("EA 9394", prep="IPA wipe", mix="100:17", cure="5 days at 77 F", per=spec.at("5.1")))
        wi.step("Pins", install=["#o1.3"]).fasten("NAS1352-3", qty=1,
                                                  torque=Torque(40, 45, "in-lbf", per=drawing.at("note 4")))
        return wi

    def test_every_value_nobody_stated_and_every_part_no_step_installs_is_listed(self) -> None:
        wi = self._wi()
        wi.steps[-1].fasten("MS21042-3 nut").inspect("Pin seated")
        self.assertEqual(wi.open_items(), [
            "step 2 (bond): pot life not stated",
            "step 3 (fasten): torque not stated",
            "step 3 (inspect): criterion source not stated",
            "#o1.4 pin: no step installs it",
        ])

    def test_a_released_instruction_with_open_items_is_refused_and_writes_nothing(self) -> None:
        from cadgen.work_instruction import work_instruction

        target = self.root / "refused.pdf"
        target.write_bytes(b"%PDF an earlier, released instruction")

        @work_instruction(out=str(target))
        def released():
            return self._wi(status="released")

        with self.assertRaisesRegex(ValueError, "released with 2 open item"):
            released()
        self.assertFalse(target.exists(), "the earlier file would read as this run's")

    def test_every_blank_prints_not_stated_and_a_draft_says_so_on_every_page(self) -> None:
        wi = self._wi()
        wi.steps[-1].inspect("Pin seated")
        pages = _page_texts(wi)
        self.assertEqual(sum(page.count("NOT STATED") for page in pages), 2, "pot life, the inspection's source")
        self.assertTrue(all(any(text.startswith("DRAFT") for text in page) for page in pages))

    def test_a_block_taller_than_a_page_is_refused_naming_its_step(self) -> None:
        wi = self.instruction()
        wi.step("Load", install=["base_plate"]).instruct("word " * 6000)
        with self.assertRaisesRegex(ValueError, "step 1 is taller than a page"):
            _page_texts(wi)


class DocumentTests(_Assembly):
    def _write(self, name: str, wi_factory):
        from cadgen.work_instruction import work_instruction

        target = self.root / name

        @work_instruction(out=str(target))
        def wi():
            return wi_factory()

        self.assertEqual(wi(), [target])
        return target.read_bytes()

    def _complete(self, **kwargs):
        wi = self.instruction(**kwargs)
        wi.step("Load", install=["base_plate"]).instruct("Datum A down.")
        wi.step("Fit", install=["bracket", "pin"]).inspect("Pins seated", per=_sources()[1].at("note 2"))
        return wi

    def test_a_draft_writes_deterministically(self) -> None:
        first = self._write("a.pdf", self._complete)
        second = self._write("b.pdf", self._complete)
        self.assertEqual(first, second, "no clock reaches the bytes")
        self.assertNotIn(b"/CreationDate", first)

    def test_front_pages_then_a_procedure_table_with_hold_points_and_a_close_out(self) -> None:
        wi = self.instruction(safety=["Safety glasses"], tools=["Fixture F-12"], rigor="controlled")
        wi.operation("Load")
        wi.step("Load", install=["base_plate"]).caution("Lift with two people.")
        wi.operation("Fit")
        wi.step("Fit", install=["bracket", "pin"]).inspect("Pins seated", per=_sources()[1].at("note 2"),
                                                           record="Pin height, mm")
        text = [t for page in _page_texts(wi) for t in page]
        order = [text.index(t) for t in ("APPLICABLE DOCUMENTS", "SAFETY", "PARTS", "EQUIPMENT", "OPERATIONS",
                                         "APPROVALS", "PROCEDURE", "OPERATION 1   Load", "CAUTION", "Close-out")]
        self.assertEqual(order, sorted(order), "front pages, then the procedure in order")
        self.assertIn("Fixture F-12", text)
        self.assertIn("PIN HEIGHT, MM", text, "the measured value has a blank")
        self.assertEqual(text.count("HOLD"), 2, "the inspection and the close-out")

    def test_released_with_nothing_open_writes_with_no_draft_banner(self) -> None:
        self.assertTrue(self._write("released.pdf", lambda: self._complete(status="released")).startswith(b"%PDF"))
        pages = _page_texts(self._complete(status="released"))
        self.assertFalse([text for page in pages for text in page if "DRAFT" in text or "NOT STATED" in text])

    def test_the_output_path_is_required_and_names_a_pdf(self) -> None:
        from cadgen.work_instruction import work_instruction

        with self.assertRaisesRegex(ValueError, "needs out="):
            work_instruction(lambda: None)
        with self.assertRaisesRegex(ValueError, "must name a .pdf"):
            work_instruction(out="wi.docx")(lambda: None)
        with self.assertRaisesRegex(TypeError, "must return an Instruction"):
            work_instruction(out=str(self.root / "x.pdf"))(lambda: "steps")()


class LayoutTests(_Assembly):
    """What a rigor lays out, what a process emphasis changes, and a house format."""

    def _texts(self, **kwargs) -> list[str]:
        wi = self.instruction(**kwargs)
        wi.step("Load", install=["base_plate"])
        wi.step("Fit", install=["bracket", "pin"]).inspect("Pins seated")
        return [t for page in _page_texts(wi) for t in page]

    def test_each_rigor_lays_out_what_it_names(self) -> None:
        prototype = self._texts(rigor="prototype")
        self.assertIn("DONE", prototype)
        for absent in ("WORK ORDER", "APPROVALS", "Close-out", "TECH", "QA", "HOLD"):
            self.assertNotIn(absent, prototype, absent)
        production = self._texts()
        for present in ("WORK ORDER", "TECH", "APPROVALS", "Close-out"):
            self.assertIn(present, production, present)
        for absent in ("QA", "HOLD", "NOT STATED"):
            self.assertNotIn(absent, production, f"{absent}: an uncited inspection is fine outside controlled work")
        controlled = self._texts(rigor="controlled")
        self.assertEqual(controlled.count("HOLD"), 2, "the inspection and the close-out")
        self.assertIn("NOT STATED", controlled, "a controlled inspection cites its criterion")

    def test_a_process_emphasis_drops_the_figures_and_maps_documents_to_steps(self) -> None:
        from cadgen.work_instruction import Adhesive

        spec, _ = _sources()
        wi = self.instruction(emphasis="process", pictures=True)
        self.assertFalse(wi.pictures)
        wi.step("Load", install=["base_plate"])
        wi.step("Bond", install=["bracket"]).bond(Adhesive("A", prep="p", mix="m", pot_life="l", cure="c",
                                                           per=spec.at("5.1")))
        text = [t for page in _page_texts(wi) for t in page]
        self.assertNotIn("FIGURE", text)
        self.assertIn("PROCESS REFERENCES", text)
        self.assertEqual(wi.references(), [("PS-2001 Rev D", "\u00a75.1", ["2"])])

    def test_a_house_format_overrides_only_what_it_states(self) -> None:
        from cadgen.work_instruction import Format

        house = Format(title="ASSEMBLY PROCEDURE", company="Acme", step_label="OP", numbering="by-ten",
                       stamps=("MECH", "INSP"), approvals=("Written by", "Quality"))
        wi = self.instruction(rigor="controlled", format=house)
        wi.step("Load", install=["base_plate"])
        wi.step("Fit", install=["bracket", "pin"]).inspect("Pins seated")
        self.assertEqual([step.label for step in wi.steps], ["10", "20"])
        self.assertEqual(wi.open_items(), ["step 20 (inspect): criterion source not stated"])
        text = [t for page in _page_texts(wi) for t in page]
        for present in ("ASSEMBLY PROCEDURE", "OP", "MECH", "INSP", "WRITTEN BY", "QUALITY", "10", "20"):
            self.assertIn(present, text, present)
        self.assertNotIn("TECH", text)
        self.assertEqual(text.count("HOLD"), 2, "controlled still holds, in the house's last column")

    def test_a_format_is_a_closed_set(self) -> None:
        from cadgen.work_instruction import Format

        for make in (lambda: Format(numbering="by-five"), lambda: Format(stamps=()), lambda: Format(stamps="QA"),
                     lambda: Format(logo="acme.png"), lambda: self.instruction(rigor="aerospace"),
                     lambda: self.instruction(emphasis="photos"), lambda: self.instruction(format={"stamps": ["QA"]})):
            with self.subTest(make=make), self.assertRaises((ValueError, TypeError)):
                make()


class WhatTheTestsFoundTests(_Assembly):
    """What agents using the skill on real assemblies tripped over."""

    def test_no_value_is_not_an_open_item_and_needs_no_wrench(self) -> None:
        from cadgen.work_instruction import Stated, Unspecified

        wi = self.instruction()
        wi.step("Bolt", install=["base_plate"]).fasten(
            "M8 bolt", qty=4, torque=Unspecified("Snug; no torque is specified",
                                                 per=Stated("A. Zhou", on="2026-10-25")))
        self.assertEqual(wi.open_items()[:1], ["#o1.2 bracket: no step installs it"])
        self.assertEqual(wi.equipment(), [])
        text = [t for page in _page_texts(wi) for t in page]
        self.assertIn("stated by A. Zhou, 2026-10-25", text, "a statement prints as one, never 'per stated by'")
        self.assertFalse([t for t in text if t.startswith("ACTUAL TORQUE")])

    def test_a_stated_torque_gets_a_blank_per_fastener_and_a_wrench(self) -> None:
        from cadgen.work_instruction import Cited, Torque

        spec, _ = _sources()
        wi = self.instruction()
        wi.step("Bolt", install=["base_plate"]).fasten(
            "#10-32 screw", qty=4, torque=Torque(32, 36, "in-lbf", per=spec.at("4.2")),
            sequence=Cited("Cross pattern, two passes", per=spec.at("4.3")))
        self.assertEqual(wi.equipment(), ["Torque wrench"])
        text = [t for page in _page_texts(wi) for t in page]
        self.assertEqual([t for t in text if t.startswith("ACTUAL TORQUE")],
                         [f"ACTUAL TORQUE {n}" for n in range(1, 5)])
        self.assertIn(("PS-2001 Rev D", "\u00a74.3", ["1"]), wi.references())

    def test_what_nobody_knows_yet_is_an_open_item(self) -> None:
        wi = self.instruction()
        wi.step("Pins", install=["pin"]).not_stated("Pin retention method")
        self.assertIn("step 1 (ask): pin retention method not stated", wi.open_items())

    def test_instructions_and_notices_cite_and_a_citation_prints_once(self) -> None:
        from cadgen.work_instruction import Adhesive

        spec, drawing = _sources()
        wi = self.instruction(emphasis="process")
        (wi.step("Bond", install=["base_plate"])
           .caution("Clamp evenly", per=spec.at("5.3"))
           .instruct("One witness coupon per mix", per=spec.at("3.4"))
           .bond(Adhesive("A", prep="p", mix="m", pot_life="l", cure="c", per=spec.at("5.1"))))
        self.assertEqual([where for _doc, where, _steps in wi.references()], ["\u00a75.3", "\u00a73.4", "\u00a75.1"])
        text = [t for page in _page_texts(wi) for t in page]
        self.assertEqual(text.count("per PS-2001 Rev D \u00a75.1"), 1, "one citation for the record's five lines")

    def test_a_house_format_renames_the_instruction_column_and_drops_figures(self) -> None:
        from cadgen.work_instruction import Format

        wi = self.instruction(pictures=True, format=Format(instruction_label="OPERATION DESCRIPTION", figures=False))
        self.assertFalse(wi.pictures)
        wi.step("Load", install=["base_plate"])
        text = [t for page in _page_texts(wi) for t in page]
        self.assertIn("OPERATION DESCRIPTION", text)
        self.assertNotIn("FIGURE", text)

    def test_a_table_that_runs_onto_a_new_page_repeats_its_headings(self) -> None:
        wi = self.instruction(revisions=[(str(n), "2026-10-25", "change") for n in range(80)])
        wi.step("Load", install=["base_plate"])
        self.assertGreaterEqual([t for page in _page_texts(wi) for t in page].count("CHANGE"), 2)

    def test_an_empty_safety_section_says_so(self) -> None:
        wi = self.instruction()
        wi.step("Load", install=["base_plate"])
        self.assertIn("None stated.", [t for page in _page_texts(wi) for t in page])


class SubassemblyTests(unittest.TestCase):
    """A subassembly a step installs whole is one line, and copies of a part are one line."""

    @classmethod
    def setUpClass(cls) -> None:
        from build123d import Box, Compound, Pos
        from cadgen.step_export import export_build123d_step_file

        base = Box(100, 60, 10)
        base.label = "base_plate"
        hub = Pos(0, 0, 10) * Box(10, 10, 10)
        hub.label = "hub"
        rim = Pos(0, 0, 10) * Box(30, 30, 4)
        rim.label = "rim"
        pins = []
        for n, x in enumerate((-40, 40), start=1):
            pin = Pos(x, 0, 10) * Box(4, 4, 10)
            pin.label = f"pin_{n}"
            pins.append(pin)
        wheel = Compound(children=[hub, rim], label="wheel")
        cls.step = _FIXTURE["root"] / "nested.step"
        export_build123d_step_file(Compound(children=[base, wheel, *pins], label="nested"), cls.step)

    def test_units_and_kinds(self) -> None:
        from cadgen._internal.work_instruction_pages import parts
        from cadgen.work_instruction import Instruction

        wi = Instruction(self.step, title="T", number="N", revision="A", pictures=False)
        self.assertIn("wheel", wi.tree())
        wi.step("Base", install=["base_plate"])
        wheel = wi.step("Wheel", install=["wheel"])
        self.assertEqual(len(wheel.units), 1, "the wheel is one unit")
        self.assertEqual(len(wheel.install), 2, "and two parts in its figure")
        wi.step("Pin 1", install=["pin_1"])
        wi.step("Pin 2", install=["pin_2"])
        rows = [(name, len(refs), steps) for name, refs, steps in parts(wi)]
        self.assertEqual(rows, [("base_plate", 1, ["1"]), ("wheel", 1, ["2"]), ("pin", 2, ["3", "4"])])


class PictureTests(_Assembly):
    def test_each_picture_hides_what_is_still_to_come_and_tints_what_the_step_installs(self) -> None:
        from cadgen._internal.work_instruction_pages import picture_plan

        wi = self.instruction(pictures=True)
        wi.step("Prepare the fixture")
        wi.step("Load", install=["base_plate"])
        wi.step("Bond", install=["bracket"]).bond(None, surfaces=["#o1.2.f5"])
        wi.step("Pins", install=["pin"], camera="top")
        plan = {p.step: p for p in picture_plan(wi)}
        self.assertNotIn(1, plan, "nothing is installed yet, so there is nothing to picture")
        self.assertEqual(plan[2].hide, ("#o1.2", "#o1.3", "#o1.4"))
        self.assertEqual((plan[3].tint, plan[3].surfaces), (("#o1.2",), ("#o1.2.f5",)))
        self.assertEqual((plan[4].hide, plan[4].camera), ((), "top"))
        self.assertEqual(plan[3].focus, ("#o1.2",), "a figure is framed on the parts its step installs")

    def test_a_surface_on_a_part_not_yet_installed_is_refused(self) -> None:
        from cadgen._internal.work_instruction_pages import picture_plan

        wi = self.instruction(pictures=True)
        wi.step("Load", install=["base_plate"]).bond(None, surfaces=["#o1.2.f5"])
        with self.assertRaisesRegex(ValueError, "not installed by step 1"):
            picture_plan(wi)

    def test_the_pictures_render_through_the_snapshot_runtime_into_the_pdf(self) -> None:
        from cadgen.work_instruction import work_instruction

        target = self.root / "pictured.pdf"

        @work_instruction(out=str(target))
        def pictured():
            wi = self.instruction(pictures=True)
            wi.step("Load", install=["base_plate"])
            wi.step("Bond", install=["bracket"]).bond(None, surfaces=["#o1.2.f6"])
            return wi

        pictured()
        self.assertEqual(len(re.findall(rb"/Subtype\s*/Image", target.read_bytes())), 2)


if __name__ == "__main__":
    unittest.main()
