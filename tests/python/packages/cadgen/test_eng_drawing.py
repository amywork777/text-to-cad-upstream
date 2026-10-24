"""``@eng_drawing``: a PDF sheet derived from a part.

The part is built with build123d so every expected number is known from the
construction: a 40 x 30 x 10 box with one 6 mm hole dimensioned overall reads
40 and 30 because it was built that way, and its hole gets a centre mark
because the projected outline contains a full circle.

``_render_sheet`` returns the in-memory ezdxf document the PDF is rendered
from, so the sheet's content is asserted there; the decorator's own tests
cover the document that reaches disk.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from tests.python.support.tmp_root import temporary_directory


def _facts():
    """An empty record of what a drawing states, for _render_sheet and _unstated."""
    from cadgen._internal.drawing_report import _Facts

    return _Facts()


def _part():
    from build123d import Align, Box, Cylinder, Pos

    align = (Align.CENTER, Align.CENTER, Align.MIN)
    return Box(40, 30, 10, align=align) - Pos(10, 5, 0) * Cylinder(3, 10, align=align)


def _sheet(part):
    from cadgen.eng_drawing import Sheet

    sheet = Sheet("A4", title="TEST BLOCK", part_number="T-1", revision="B", notes=["ONE", "TWO"])
    top = sheet.view(part, "top", at=(100, 120))
    front = sheet.view(part, "front", at=(100, 50))
    top.overall()
    top.diameter((10, 5, 10), text="%%c6 THRU")
    front.dim((20, -15, 0), (20, -15, 10), offset=12)
    return sheet


def _dim_texts(doc):
    texts = []
    for dim in doc.modelspace().query("DIMENSION"):
        block = doc.blocks.get(dim.dxf.geometry)
        texts.extend(e.text for e in block if e.dxftype() == "MTEXT")
    return texts


class DrawingSheetTests(unittest.TestCase):
    def test_a_sheet_writes_views_dimensions_marks_frame_and_title(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        doc = _render_sheet(_sheet(_part()), index=1, count=2, label="t")
        msp = doc.modelspace()
        kinds = {}
        for entity in msp:
            kinds[entity.dxftype()] = kinds.get(entity.dxftype(), 0) + 1
        self.assertEqual(kinds.get("DIMENSION"), 3, "overall width + height, the front height")
        self.assertEqual(kinds.get("LEADER"), 1, "the hole callout is a leader to text outside the view")
        self.assertGreaterEqual(kinds.get("TEXT", 0), 6, "title block, notes and two view labels")
        by_layer = {}
        for entity in msp:
            by_layer.setdefault(entity.dxf.layer, 0)
            by_layer[entity.dxf.layer] += 1
        self.assertGreater(by_layer.get("VISIBLE", 0), 0)
        self.assertGreater(by_layer.get("HIDDEN", 0), 0, "the hole is hidden in the front view")
        self.assertEqual(by_layer.get("CENTER", 0), 3, "one centre mark (two lines) and the bore's axis in the front view")
        # Measured, not typed: the overall dimensions read the box.
        texts = _dim_texts(doc)
        self.assertIn("40", texts)
        self.assertIn("30", texts)
        self.assertIn("10", texts)
        self.assertEqual(_callouts(doc), ["%%c6 THRU"])
        # The callout text sits outside the view's extent, not across the part.
        callout = next(e for e in msp.query("TEXT") if e.dxf.layer == "DIM")
        outline_x = [p[0] for e in msp.query("LWPOLYLINE LINE") if e.dxf.layer == "VISIBLE" for p in _points(e)]
        self.assertTrue(callout.dxf.insert.x > max(outline_x) or callout.dxf.insert.x < min(outline_x))
        # A4 landscape frame at the margin.
        frame = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "SHEET"]
        self.assertEqual(len(frame), 1)
        xs = [p[0] for p in frame[0].get_points("xy")]
        self.assertAlmostEqual(max(xs) - min(xs), 297 - 20, places=6)
        title_text = [e.dxf.text for e in msp.query("TEXT")]
        self.assertIn("TEST BLOCK", title_text)
        for caption, value in (("DWG NO.", "T-1"), ("REV", "B"), ("SHEET", "1 OF 2"), ("SCALE", "1:1"),
                               ("SIZE", "A4"), ("UNITS", "MM")):
            self.assertIn(caption, title_text)
            self.assertIn(value, title_text)

    def test_every_layer_linetype_exists_in_the_table(self) -> None:
        """A layer naming a linetype the document does not define draws continuous.

        ezdxf's `setup=True` table has DASHED and CENTER and no HIDDEN, and it
        substitutes silently (the audit reports "Replaced undefined linetype"),
        so hidden edges printed solid. Asserting the NAME on the layer cannot
        catch that; asserting the table can.
        """
        from cadgen._internal.drawing_base import _LAYERS
        from cadgen._internal.drawing_render import _render_sheet

        doc = _render_sheet(_sheet(_part()), index=1, count=1, label="t")
        defined = {lt.dxf.name.upper() for lt in doc.linetypes}
        for name, (_color, linetype, _weight) in _LAYERS.items():
            self.assertIn(linetype.upper(), defined, f"layer {name} names an undefined linetype")
        auditor = doc.audit()
        self.assertEqual(list(auditor.errors), [])
        self.assertEqual([str(fix) for fix in auditor.fixes], [])

    def test_the_hidden_line_pass_writes_each_edge_once(self) -> None:
        """The kernel returns a hidden edge once per face that hides it."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        sheet = Sheet("A4")
        sheet.view(part, "front", at=(150, 105))
        doc = _render_sheet(sheet, index=1, count=1, label="dupes")
        drawn: dict[str, list] = {}
        for entity in doc.modelspace().query("LINE LWPOLYLINE CIRCLE ARC"):
            if entity.dxf.layer not in ("VISIBLE", "HIDDEN"):
                continue
            key = (entity.dxftype(), tuple(sorted(tuple(round(v, 6) for v in p) for p in _points(entity))))
            drawn.setdefault(entity.dxf.layer, []).append(key)
        for layer, keys in drawn.items():
            self.assertEqual(len(keys), len(set(keys)), f"{layer} holds duplicate geometry")
        self.assertGreater(len(drawn.get("HIDDEN", [])), 0, "the bore is hidden in the front view")

    def test_dimension_points_land_on_the_projected_geometry(self) -> None:
        """A dimension between the box's top corners spans exactly the drawn outline."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        sheet = Sheet("A4")
        top = sheet.view(part, "top", at=(100, 100))
        top.dim((-20, 15, 10), (20, 15, 10), offset=10)
        doc = _render_sheet(sheet, index=1, count=1, label="t")
        msp = doc.modelspace()
        dim = list(msp.query("DIMENSION"))[0]
        p1, p2 = dim.dxf.defpoint2, dim.dxf.defpoint3
        self.assertAlmostEqual(abs(p2.x - p1.x), 40.0, places=5)
        xs = [p[0] for e in msp.query("LWPOLYLINE LINE") if e.dxf.layer == "VISIBLE" for p in _points(e)]
        self.assertAlmostEqual(min(p1.x, p2.x), min(xs), places=4)
        self.assertAlmostEqual(max(p1.x, p2.x), max(xs), places=4)

    def test_a_scaled_sheet_prints_true_size_values(self) -> None:
        """At 1:2 an 80 x 50 x 10 plate still reads 80, 50 and 10.

        The dimension measures SHEET millimetres, which are the model's only at
        1:1, so each view sets dimlfac to the inverse of its own scale.
        """
        from build123d import Align, Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(80, 50, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        for scale in (1.0, 0.5, 0.25):
            with self.subTest(scale=scale):
                sheet = Sheet("A3", scale=scale, title="PLATE")
                top, front, _right = sheet.three_views(part)
                top.overall()
                front.dim((-40, -25, 0), (-40, -25, 10), offset=-14)
                doc = _render_sheet(sheet, index=1, count=1, label="s")
                texts = _dim_texts(doc)
                self.assertIn("80", texts)
                self.assertIn("50", texts)
                self.assertIn("10", texts)
        # A view drawn at its own scale reads true size too.
        sheet = Sheet("A3", scale=1.0)
        sheet.view(part, "top", at=(210, 150), scale=0.5).overall()
        self.assertEqual(sorted(_dim_texts(_render_sheet(sheet, index=1, count=1, label="s"))), ["50", "80"])

    def test_a_tolerance_prints_the_authors_deviation_at_any_scale(self) -> None:
        from build123d import Align, Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(80, 50, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        sheet = Sheet("A3", scale=0.5)
        front = sheet.view(part, "front", at=(210, 150))
        front.dim((-40, -25, 0), (40, -25, 0), offset=-14, tol=0.1)
        texts = _dim_texts(_render_sheet(sheet, index=1, count=1, label="tol"))
        self.assertTrue(any("80" in t and "±0.10" in t for t in texts), texts)

    def test_an_unplaced_dimension_takes_the_next_free_row_on_its_own_side(self) -> None:
        """`dim()` used to default to the row `overall()` writes into, and then to
        the top of the view whatever it measured: a pitch along the bottom edge ran
        its extension lines up across the whole part to a row above it."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        sheet = Sheet("A4")
        top = sheet.view(part, "top", at=(150, 105))
        top.overall()
        top.dim((-20, 15, 10), (20, 15, 10))
        top.dim((-20, -15, 10), (20, -15, 10))
        doc = _render_sheet(sheet, index=1, count=1, label="rows")
        rows = sorted(round(d.dxf.defpoint.y, 3) for d in doc.modelspace().query("DIMENSION")
                      if abs(float(d.dxf.angle)) < 1e-9)
        self.assertEqual(len(rows), 3)
        below, above = [r for r in rows if r < 105], [r for r in rows if r > 105]
        self.assertEqual(len(below), 1, "the bottom edge's dimension sits below the view")
        self.assertEqual(len(above), 2, "the top edge's, and the overall width, above it")
        self.assertAlmostEqual(above[1] - above[0], 12.0, places=3, msg="one clear row apart, overall outermost")
        self.assertAlmostEqual(105 - 15 - below[0], 12.0, places=3, msg="the first row under the view")

    def test_views_that_run_off_the_frame_are_refused_with_a_scale_that_fits(self) -> None:
        from build123d import Align, Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(3000, 1200, 200, align=(Align.CENTER, Align.CENTER, Align.MIN))
        sheet = Sheet("A3")
        sheet.three_views(part)
        with self.assertRaises(ValueError) as caught:
            _render_sheet(sheet, index=1, count=1, label="big")
        message = str(caught.exception)
        self.assertIn("off the frame", message)
        suggested = float(message.split("Sheet(scale=")[1].split(")")[0])
        self.assertLess(suggested, 1.0)
        # The suggestion has to be one that actually works.
        fits = Sheet("A3", scale=suggested)
        fits.three_views(part)
        _render_sheet(fits, index=1, count=1, label="big")

    def test_a_title_longer_than_its_cell_is_cut_not_overrun(self) -> None:
        """Measured the way it is drawn, whatever font this machine resolves.

        A character is not a fixed fraction of the cap height, and which
        fraction it is depends on the font the renderer finds: proportional
        here, near-monospace on a runner with no system fonts. Whether a given
        title has to be cut or merely shrunk is that font's business. That it
        ends up inside its cell is not.
        """
        from cadgen._internal.drawing_base import _MIN_TEXT_MM, _text_width
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_sheet import _TITLE_FIT
        from cadgen.eng_drawing import Sheet

        cell = _TITLE_FIT
        for title in ("ENCLOSURE",
                      "ELECTRONICS ENCLOSURE BASE",
                      "ELECTRONICS ENCLOSURE BASE, LOWER HALF, REVISION C, MACHINED FROM 6061-T6 BILLET",
                      "M" * 400):
            with self.subTest(title=title):
                sheet = Sheet("A4", title=title)
                sheet.view(_part(), "top", at=(150, 120))
                doc = _render_sheet(sheet, index=1, count=1, label="long")
                drawn = next(e for e in doc.modelspace().query("TEXT[layer=='TITLE']")
                             if len(e.dxf.text.rstrip("…")) >= 4 and title.startswith(e.dxf.text.rstrip("…")))
                self.assertGreaterEqual(drawn.dxf.height, _MIN_TEXT_MM, "still legible")
                self.assertLessEqual(_text_width(drawn.dxf.text, drawn.dxf.height), cell + 1e-6,
                                     f"{drawn.dxf.text!r} at {drawn.dxf.height} runs into the SCALE cell")
                if drawn.dxf.text != title:
                    self.assertTrue(drawn.dxf.text.endswith("…"),
                                    f"{drawn.dxf.text!r} was shortened without saying so")

    def test_first_angle_lays_the_views_out_first_angle(self) -> None:
        """The label and the arrangement are the same decision."""
        from cadgen.eng_drawing import Sheet

        part = _part()
        third = Sheet("A3")
        t_top, t_front, t_right = third.three_views(part)
        self.assertGreater(t_top.at[1], t_front.at[1], "third angle: the plan sits above the front")
        self.assertGreater(t_right.at[0], t_front.at[0], "third angle: the view from the right sits right")
        first = Sheet("A3", projection="FIRST ANGLE")
        f_top, f_front, f_right = first.three_views(part)
        self.assertLess(f_top.at[1], f_front.at[1], "first angle: the plan sits below the front")
        self.assertLess(f_right.at[0], f_front.at[0], "first angle: the view from the right sits left")

    def test_the_bottom_view_lines_up_under_the_front_view(self) -> None:
        """Third angle draws the bottom view as the top view mirrored, not rotated."""
        from cadgen._internal.drawing_views import _Projection
        from cadgen.eng_drawing import VIEW_DIRECTIONS

        part = _part()
        top, bottom = _Projection(part, VIEW_DIRECTIONS["top"]), _Projection(part, VIEW_DIRECTIONS["bottom"])

        def axes(proj):
            origin = proj.point((0, 0, 0))
            return [tuple(round(a - b, 6) for a, b in zip(proj.point(p), origin))
                    for p in ((1, 0, 0), (0, 1, 0))]

        self.assertEqual(axes(top), [(1.0, 0.0), (0.0, 1.0)])
        self.assertEqual(axes(bottom), [(1.0, 0.0), (0.0, -1.0)], "+X must stay right; +Y flips")

    def test_every_side_view_maps_up_to_up(self) -> None:
        """A model point higher in Z lands higher on the sheet in every view that
        looks along a horizontal direction; the right and left views once mirrored."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        for name in ("front", "back", "right", "left"):
            with self.subTest(view=name):
                sheet = Sheet("A3")
                view = sheet.view(part, name, at=(210, 150))
                view.dim((0, 0, 0), (0, 0, 10), offset=12)
                doc = _render_sheet(sheet, index=1, count=1, label="sides")
                dim = doc.modelspace().query("DIMENSION")[0]
                self.assertGreater(dim.dxf.defpoint3.y, dim.dxf.defpoint2.y, "z=10 should sit above z=0")
                self.assertGreater(dim.dxf.defpoint3.y, view.at[1], "the top of the part is above the centre")

    def test_view_label_sits_below_bottom_dimensions(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        sheet = Sheet("A4")
        front = sheet.view(part, "front", at=(100, 100))
        front.dim((-20, -15, 0), (20, -15, 0), offset=-12)
        doc = _render_sheet(sheet, index=1, count=1, label="label")
        label = next(e for e in doc.modelspace().query("TEXT[layer=='NOTES']") if e.dxf.text == "FRONT")
        dim = doc.modelspace().query("DIMENSION")[0]
        self.assertLess(label.dxf.insert.y, dim.dxf.defpoint.y - 3, "the label hangs under the dimension line")

    def test_round_edges_are_written_as_circles_and_arcs(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_part(), "top", at=(100, 120))
        doc = _render_sheet(sheet, index=1, count=1, label="round")
        circles = [c for c in doc.modelspace().query("CIRCLE") if c.dxf.layer == "VISIBLE"]
        self.assertEqual(len(circles), 1, "the hole seen from above is one CIRCLE")
        self.assertAlmostEqual(circles[0].dxf.radius, 3.0, places=3)

    def test_shop_annotations_are_written(self) -> None:
        from cadgen._internal.drawing_annotation import hole_callout_text
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = _part()
        sheet = Sheet("A4", title="TAGGED", general_tolerance="ISO 2768-m",
                      revisions=[("A", "2026-09-01", "INITIAL RELEASE"), ("B", "2026-09-17", "HOLE MOVED")])
        top = sheet.view(part, "top", at=(100, 120))
        front = sheet.view(part, "front", at=(100, 50))
        front.dim((20, -15, 0), (20, -15, 10), offset=12, tol=0.1)
        front.dim((-20, -15, 0), (20, -15, 0), offset=-12, tol=(0.05, 0.02), fit="h6")
        top.hole((10, 5, 10), 6, thru=True, count=1)
        top.hole((10, 5, 10), thread="M6x1 - 6H")
        doc = _render_sheet(sheet, index=1, count=1, label="tagged")
        msp = doc.modelspace()
        texts = _dim_texts(doc)
        self.assertTrue(any("±0.10" in t for t in texts), texts)
        self.assertTrue(any("+0.05" in t and "0.02" in t and "h6" in t for t in texts), texts)
        notes = [e.dxf.text for e in msp.query("TEXT[layer=='NOTES']")]
        self.assertTrue(any("ISO 2768-m" in n for n in notes), notes)
        title_texts = [e.dxf.text for e in msp.query("TEXT[layer=='TITLE']")]
        self.assertIn("DESCRIPTION", title_texts)
        self.assertIn("HOLE MOVED", title_texts)
        callouts = _callouts(doc)
        self.assertIn("%%c6 THRU", callouts, "one hole is not '1×'")
        self.assertIn("M6x1 - 6H THRU", callouts, "a thread replaces the diameter; THRU is still the part's")
        self.assertEqual(hole_callout_text({"diameter": 6.6, "depth": 12, "thru": False, "cbore": (11, 6.5), "csk": None,
                                            "thread": "M6x1 - 6H", "count": None}), "M6x1 - 6H ↧12   ⌴ %%c11 ↧6.5")

    def test_an_angular_dimension_is_written(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        front = sheet.view(_part(), "front", at=(100, 100))
        front.angle((-20, -15, 0), (20, -15, 0), (-20, -15, 10), offset=14)
        doc = _render_sheet(sheet, index=1, count=1, label="angle")
        dims = doc.modelspace().query("DIMENSION")
        self.assertTrue(any(d.dimtype == 5 for d in dims), "an angular dimension on the DIM layer")


class SheetWarningTests(unittest.TestCase):
    """What the sheet draws but a reader should look at. Found by running the
    skill on parts it was not written against."""

    def test_a_dimension_whose_points_miss_the_geometry_says_so(self) -> None:
        """A part built from a corner, dimensioned as if it were centred.

        The dimension renders perfectly and measures blank paper, which is the
        one error a shop cannot catch from the print.
        """
        from build123d import Align, Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(120, 30, 30, align=(Align.MIN, Align.CENTER, Align.CENTER))  # X runs 0..120
        sheet = Sheet("A3")
        front = sheet.view(part, "front", at=(210, 150))
        front.dim((0, 0, 15), (30, 0, 15))          # on the part
        front.dim((-60, 0, 15), (-30, 0, 15))       # as if it were centred: off in space
        front.note("BORE", (-55, 0, 0))
        notices: list[str] = []
        _render_sheet(sheet, index=1, count=1, label="off", warnings=notices)

        self.assertEqual(len(notices), 2, notices)
        self.assertTrue(any("dim 1" in n for n in notices), notices)
        self.assertTrue(any("note 2" in n for n in notices), notices)
        self.assertTrue(all("measures blank paper" in n for n in notices), notices)

    def test_a_clean_sheet_warns_about_nothing(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        notices: list[str] = []
        _render_sheet(_sheet(_part()), index=1, count=1, label="clean", warnings=notices)
        self.assertEqual(notices, [])

    def test_annotation_printed_over_annotation_says_so(self) -> None:
        """Two views are laid out knowing only where the views are, so one view's
        outermost dimension can land on the view label of the view above it."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        def build(gap):
            # A fixed gap of 47 mm reserves two dimension rows. Asking the front
            # view for three puts its outermost row where the top view's label hangs.
            sheet = Sheet("A3")
            _top, front, _right = sheet.three_views(_part(), gap=gap)
            front.overall()
            # Both along the top edge, so both take rows above the view.
            front.dim((-20, -15, 10), (0, -15, 10))
            front.dim((0, -15, 10), (20, -15, 10))
            notices: list[str] = []
            _render_sheet(sheet, index=1, count=1, label="rows", warnings=notices)
            return [n for n in notices if "annotation overlaps" in n]

        crowded = build(47)
        self.assertTrue(crowded, "three rows into a two-row gap should be reported")
        self.assertIn("three_views(gap=", crowded[0])
        self.assertEqual(build(70), [], "given the room, the same sheet is quiet")
        self.assertEqual(build(None), [], "left to itself, the layout makes the room")


class DrawingVocabularyTests(unittest.TestCase):
    """Every argument is checked where it is written, not at render time."""

    def setUp(self) -> None:
        from cadgen.eng_drawing import Sheet

        self.view = Sheet("A4").view(_part(), "top", at=(100, 100))

    def test_unknown_view_sheet_and_projection_are_refused(self) -> None:
        from cadgen.eng_drawing import Sheet

        with self.assertRaises(ValueError):
            Sheet("Letter")
        with self.assertRaises(ValueError):
            Sheet("A4").view(_part(), "diagonal", at=(0, 0))
        with self.assertRaisesRegex(ValueError, "projection"):
            Sheet("A4", projection="THIRD-ANGLE")

    def test_an_unknown_orientation_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "orientation"):
            self.view.dim((0, 0, 0), (1, 0, 0), orientation="x")

    def test_a_hole_that_cannot_be_made_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "diameter"):
            self.view.hole((0, 0, 0), -5)
        with self.assertRaisesRegex(ValueError, "diameter"):
            self.view.hole((0, 0, 0), 0)
        with self.assertRaisesRegex((TypeError, ValueError), "cbore"):
            self.view.hole((0, 0, 0), 6, cbore=5)
        with self.assertRaisesRegex(ValueError, "cbore"):
            self.view.hole((0, 0, 0), 6, cbore=(11, -2))
        with self.assertRaisesRegex(ValueError, "THRU"):
            self.view.hole((0, 0, 0), 6, thru=True, depth=12)
        with self.assertRaisesRegex(ValueError, "size"):
            self.view.diameter((0, 0, 0), size=0)
        with self.assertRaisesRegex(TypeError, "measures the circle"):
            self.view.diameter((0, 0, 0), 3)

    def test_a_tolerance_that_is_not_a_tolerance_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            self.view.dim((0, 0, 0), (1, 0, 0), tol="abc")
        with self.assertRaises(TypeError):
            self.view.dim((0, 0, 0), (1, 0, 0), tol=(1, 2, 3))

    def test_an_offset_that_is_not_a_number_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            self.view.dim((0, 0, 0), (1, 0, 0), offset="far")


class DrawingDocumentTests(unittest.TestCase):
    """What reaches disk: one PDF, at the path the caller named, byte-stable."""

    def test_running_the_decorated_function_writes_one_deterministic_pdf(self) -> None:
        from cadgen.eng_drawing import eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as td:
            out = Path(td) / "PDF" / "block.pdf"

            @eng_drawing(out=str(out))
            def block_drawing():
                return _sheet(_part())

            written = block_drawing()
            self.assertEqual(written, [out])
            self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ["block.pdf"],
                             "no DXF, and no half-written file left behind")
            payload = out.read_bytes()
            self.assertTrue(payload.startswith(b"%PDF"))
            self.assertNotIn(b"CreationDate", payload, "a clock stamp would make the bytes differ per run")
            block_drawing()
            self.assertEqual(out.read_bytes(), payload, "an unchanged drawing rebuilds to identical bytes")

    def test_a_sheet_per_page(self) -> None:
        from cadgen.eng_drawing import Sheet, eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as td:
            out = Path(td) / "pair.pdf"
            part = _part()

            @eng_drawing(out=str(out))
            def pair():
                a = Sheet("A4", title="ONE"); a.view(part, "top", at=(150, 105))
                b = Sheet("A4", title="TWO"); b.view(part, "front", at=(150, 105))
                return [a, b]

            self.assertEqual(pair(), [out])
            # matplotlib writes the page tree uncompressed: the tree's /Count is the page count.
            self.assertIn(b"/Count 2", out.read_bytes())

    def test_the_output_path_is_required_and_names_a_pdf(self) -> None:
        from cadgen.eng_drawing import eng_drawing

        with self.assertRaisesRegex(ValueError, "out="):
            @eng_drawing
            def no_path():
                return _sheet(_part())

        with self.assertRaisesRegex(ValueError, r"\.pdf"):
            @eng_drawing(out="../DXF/wrong.dxf")
            def wrong_suffix():
                return _sheet(_part())

    def test_a_missing_renderer_fails_loudly_and_writes_nothing(self) -> None:
        """The PDF is the drawing: no renderer is a failure, not a skipped half."""
        from cadgen.eng_drawing import eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as td:
            out = Path(td) / "PDF" / "block.pdf"

            @eng_drawing(out=str(out))
            def block_drawing():
                return _sheet(_part())

            # Only this key is swapped and restored: `patch.dict` on sys.modules
            # rebuilds the whole mapping on exit and would drop every submodule
            # imported inside the block, the CAD kernel's included.
            missing = object()
            previous = sys.modules.get("matplotlib", missing)
            sys.modules["matplotlib"] = None  # `import matplotlib` now raises ImportError
            try:
                with self.assertRaisesRegex(RuntimeError, "PDF"):
                    block_drawing()
            finally:
                if previous is missing:
                    sys.modules.pop("matplotlib", None)
                else:
                    sys.modules["matplotlib"] = previous
            self.assertFalse(out.exists())

    def test_a_function_that_returns_no_sheet_is_refused(self) -> None:
        from cadgen.eng_drawing import eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as td:
            @eng_drawing(out=str(Path(td) / "x.pdf"))
            def not_a_sheet():
                return 42

            with self.assertRaises(TypeError):
                not_a_sheet()


class UndimensionedSheetTests(unittest.TestCase):
    """A sheet is a drawing before its author has written a dimension."""

    def test_views_alone_with_curved_geometry_still_write_a_pdf(self) -> None:
        """The cut-profile checks graded it as a broken laser-cut file.

        `document_is_drawing` needs a DIMENSION or a LEADER before it will
        believe a document is a document, which is right for a DXF that arrived
        from elsewhere and wrong for one @eng_drawing just built. A projected
        outline with a fillet in it does not close, so every part that was not a
        plain box failed the first time it was drawn -- which is step 3 of the
        skill's own workflow, before step 4 says to dimension anything.
        """
        from build123d import Axis, Box, Cylinder, fillet
        from cadgen.eng_drawing import Sheet, eng_drawing

        parts = {
            "filleted": fillet(Box(80, 50, 10).edges().filter_by(Axis.Z), 8),
            "cylinder": Cylinder(20, 40),
        }
        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            for name, part in parts.items():
                target = Path(tmp) / f"{name}.pdf"

                @eng_drawing(out=str(target))
                def undimensioned(part=part):
                    sheet = Sheet("A3", title=name.upper())
                    sheet.three_views(part)
                    return sheet

                undimensioned()
                self.assertTrue(target.exists(), f"{name} wrote no PDF")
                self.assertGreater(target.stat().st_size, 1000)

    def test_the_duplicate_and_empty_checks_still_run(self) -> None:
        """Exempting the cut-profile checks must not exempt the rest."""
        from cadgen.drawing_checks import validate_drawing_document

        import ezdxf

        doc = ezdxf.new("R2010", setup=True)
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        msp.add_lwpolyline(square, close=True, dxfattribs={"layer": "VISIBLE"})
        msp.add_lwpolyline(square, close=True, dxfattribs={"layer": "VISIBLE"})
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], dxfattribs={"layer": "VISIBLE"})
        codes = {f.code for f in validate_drawing_document(doc, drawing=True)}
        self.assertIn("duplicate_entity", codes, "the check that caught the doubled hidden lines")
        self.assertNotIn("open_cut_profile", codes)
        # And the open polyline IS still a finding when nobody vouches for the file.
        self.assertIn("open_cut_profile", {f.code for f in validate_drawing_document(doc)})

        empty = ezdxf.new("R2010", setup=True)
        self.assertIn("empty_drawing", {f.code for f in validate_drawing_document(empty, drawing=True)})


class TextMeasurementTests(unittest.TestCase):
    """The markup is not the text.

    Everything here is asserted against the font this machine resolves, never
    against a millimetre figure. The frontend turns text into glyph paths
    through the same font machinery the measurement asks, so the two agree by
    construction -- on a workstation full of typefaces and on a runner with
    none. Baking in one font's numbers tests the runner, not the code.
    """

    def test_mtext_is_measured_by_the_glyphs_it_draws(self) -> None:
        r"""A toleranced 30 is `\A0;30{\H0.70x;±0.10}`: 15 characters, 7 of
        which draw nothing and 5 of which draw at 0.7 of the height. Counted raw
        at full height that was 37.8 mm of ink where about 14 mm exists."""
        from cadgen._internal.drawing_base import _mtext_extent, _text_width

        plain, _ = _mtext_extent("\\A0;30", 3.5)
        toleranced, _ = _mtext_extent("\\A0;30{\\H0.70x;\u00b10.10}", 3.5)
        stacked, _ = _mtext_extent("\\A0;30{\\H0.70x;\\S+0.05^-0.02;}", 3.5)

        # The control codes draw nothing, so the plain value is exactly its digits.
        self.assertAlmostEqual(plain, _text_width("30", 3.5), delta=0.01)
        # And the deviation is charged at 0.7 of the height, as it is drawn.
        self.assertAlmostEqual(toleranced, plain + _text_width("\u00b10.10", 3.5 * 0.7), delta=0.01)
        # Far short of the raw count that produced the false positives: fifteen
        # characters at full height, braces and \H0.70x; included.
        self.assertLess(toleranced, _text_width("30\\H0.70x;\u00b10.10", 3.5) * 0.6)
        # A stacked deviation prints its halves one above the other, so it is as
        # wide as the wider half and not as wide as both.
        self.assertLess(stacked, plain + 2 * _text_width("+0.05", 3.5))

    def test_the_measurement_is_the_font_the_renderer_will_use(self) -> None:
        """No fixed fraction of the cap height serves every string: the ratio
        that fits "ELECTRONICS ENCLOSURE BASE" runs "+0.10" 25% over in a
        proportional font, and a machine with no system fonts resolves a
        different one again. Ask the font, do not assume it."""
        from cadgen._internal.drawing_base import _font, _text_width

        font = _font(5.0)
        if font is None:
            self.skipTest("no font machinery here; the conservative ratio applies")
        for value in ("ELECTRONICS ENCLOSURE BASE", "+0.10", "\u00d86 THRU", "R18"):
            with self.subTest(value=value):
                self.assertAlmostEqual(_text_width(value, 5.0), float(font.text_width(value)),
                                       delta=1e-6)

    def test_width_grows_with_the_string_and_the_height(self) -> None:
        from cadgen._internal.drawing_base import _text_width

        self.assertEqual(0.0, _text_width("", 3.5))
        self.assertLess(_text_width("12", 3.5), _text_width("1234", 3.5))
        self.assertAlmostEqual(_text_width("1234", 7.0), 2 * _text_width("1234", 3.5), delta=1e-6)

class ChainDimensionTests(unittest.TestCase):
    """The overlap warning has to survive the commonest idiom in drafting."""

    def _warnings(self, pitch: float, tol) -> list:
        from build123d import Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        span = 160.0
        sheet = Sheet("A3", title="CHAIN")
        top, _front, _right = sheet.three_views(Box(span, 60, 10))
        for i in range(int(span // pitch)):
            top.dim((-span / 2 + pitch * i, 30, 0), (-span / 2 + pitch * (i + 1), 30, 0),
                    tol=tol, offset=14.0)
        notices: list = []
        _render_sheet(sheet, index=1, count=1, label="chain", warnings=notices)
        return [n for n in notices if "overlaps" in n]

    def test_a_toleranced_chain_with_clear_paper_does_not_warn(self) -> None:
        """Five values about 14 mm wide at 30 mm pitch: 16 mm of clear paper.

        The same chain without `tol=` warned about nothing, which is what gave
        the false positive away: the tolerance changed the measurement, not the
        drawing. A warning that cries on a correct sheet is one an agent learns
        to ignore, and that costs the cases where it is right.
        """
        for pitch in (25.0, 30.0, 36.0, 40.0):
            with self.subTest(pitch=pitch):
                self.assertEqual([], self._warnings(pitch, 0.1))
                self.assertEqual([], self._warnings(pitch, None))

    def test_values_that_really_do_collide_still_warn(self) -> None:
        """The pitch comes from the measurement, so this is a collision on any
        font: values packed at half the width of the value itself."""
        from cadgen._internal.drawing_base import _mtext_extent

        width, _ = _mtext_extent("\\A0;30{\\H0.70x;±0.10}", 3.5)
        self.assertNotEqual([], self._warnings(round(width / 2, 1), 0.1))


class InkTests(unittest.TestCase):
    def test_no_edge_is_drawn_on_both_visible_and_hidden(self) -> None:
        """HIDDEN was written second, so it drew over every visible line.

        HLR returns an edge from each face that bounds it, so a silhouette edge
        comes back in both passes. One `seen` set per pass caught the repeats
        inside each pass and none across them: a 600 dpi crop of one view in
        colour was 34,842 grey pixels against 2,635 black -- the outline
        printing grey-dashed, the visible/hidden distinction gone. In mono it is
        black over black, which is why it went unnoticed.
        """
        from build123d import Box, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(60, 40, 20) - Cylinder(6, 40) - Pos(0, 0, 6) * Cylinder(9, 8)
        sheet = Sheet("A3", title="INK")
        sheet.three_views(part)
        doc = _render_sheet(sheet, index=1, count=1, label="ink")

        drawn: dict[str, set] = {"VISIBLE": set(), "HIDDEN": set()}
        for entity in doc.modelspace():
            layer = entity.dxf.layer
            if layer not in drawn:
                continue
            points = tuple((round(x, 6), round(y, 6)) for x, y in _points(entity))
            drawn[layer].add(min(points, points[::-1]))

        self.assertTrue(drawn["VISIBLE"] and drawn["HIDDEN"], "both passes drew something")
        self.assertEqual(set(), drawn["VISIBLE"] & drawn["HIDDEN"])

    def test_a_tangent_transition_is_not_drawn_as_a_hidden_edge(self) -> None:
        """A drawing has no tangent transition line, and one behind material
        marks nothing a shop can look at.

        `project_to_viewport` bundles OCCT's smooth edges into the hidden half
        along with sharp edges and silhouettes. A cylindrical face carries a
        SEAM where it closes on itself, the seam is smooth, and it lands in that
        bundle -- so wherever the seam happens to face the camera it prints as
        an extra dashed line the length of the feature. On this disc the right
        view drew two, the full width of the part, inside its real edges; on a
        bore the same line runs down the hole's own axis.

        Which view shows it is an accident of where the kernel put the seam, so
        every view is checked.
        """
        from build123d import Cylinder, GeomType, Pos, fillet
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        radius, height, blend = 40.0, 10.0, 1.5
        blank = Pos(0, 0, height / 2) * Cylinder(radius, height)
        part = fillet(blank.edges().filter_by(GeomType.CIRCLE), blend)
        tangent = round(height / 2 - blend, 3)

        def spans(name: str) -> list:
            sheet = Sheet("A3", title="FLANGE")
            view = sheet.view(part, name, at=(200, 150))
            doc = _render_sheet(sheet, index=1, count=1, label="flange")
            found = []
            for entity in doc.modelspace():
                if entity.dxf.layer != "HIDDEN":
                    continue
                points = _points(entity)
                ys = {round(y - view.at[1], 2) for _x, y in points}
                xs = [x for x, _y in points]
                if len(ys) == 1 and max(xs) - min(xs) > radius:
                    found.append(ys.pop())
            return found

        for name in ("front", "right"):
            with self.subTest(view=name):
                drawn = spans(name)
                self.assertNotIn(tangent, drawn, f"{name}: a seam is drawn as a hidden edge")
                self.assertNotIn(-tangent, drawn, f"{name}: a seam is drawn as a hidden edge")

    def test_real_hidden_edges_and_silhouettes_survive(self) -> None:
        """Dropping tangents must not drop a bore's walls or a sharp edge."""
        from build123d import Box, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(60, 40, 20) - Cylinder(6, 40) - Pos(0, 0, 6) * Cylinder(9, 8)
        sheet = Sheet("A3", title="BORES")
        front = sheet.view(part, "front", at=(200, 150))
        doc = _render_sheet(sheet, index=1, count=1, label="bores")

        walls = set()
        for entity in doc.modelspace().query("LINE[layer=='HIDDEN']"):
            a, b = entity.dxf.start, entity.dxf.end
            if abs(a.x - b.x) < 1e-6:
                walls.add(round(a.x - front.at[0], 2))
        # Both bores, both walls each: the silhouettes a hole is read from.
        for x in (-9.0, -6.0, 6.0, 9.0):
            self.assertIn(x, walls, f"the bore wall at {x} is missing: {sorted(walls)}")

    def test_the_layer_weights_reach_the_pdf(self) -> None:
        """The backend clamps every width to 72/dpi unless given a floor.

        The sample PDF carried one non-zero width operator: 0.72, 180 times.
        Thick against thin is most of what makes a print readable at a glance.
        """
        import re
        import zlib

        from cadgen.eng_drawing import Sheet, eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            target = Path(tmp) / "weights.pdf"

            @eng_drawing(out=str(target))
            def weights():
                sheet = Sheet("A3", title="WEIGHTS")
                top, _f, _r = sheet.three_views(_part())
                top.overall()
                return sheet

            weights()
            raw = target.read_bytes()

        widths = set()
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
            data = match.group(1)
            try:
                data = zlib.decompress(data)
            except zlib.error:
                continue
            widths.update(float(w.group(1)) for w in re.finditer(rb"([\d.]+) w\b", data))
        widths.discard(0.0)

        self.assertGreaterEqual(len(widths), 4, f"one width per layer, not one for all: {sorted(widths)}")
        self.assertIn(0.5, widths, "VISIBLE, the heavy outline")
        self.assertIn(0.18, widths, "CENTER and DIM, the thin ones")
        self.assertNotEqual({0.72}, widths, "0.72 is 72/dpi, the clamp")

    def test_a_counterbore_gets_one_centre_mark(self) -> None:
        """Two crosses drawn over each other fill the CENTER gaps in.

        The centre line then prints solid, which is the one thing its dashes are
        there to say it is not.
        """
        from build123d import Box, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part = Box(60, 40, 20) - Cylinder(4, 40) - Pos(0, 0, 6) * Cylinder(8, 8)
        sheet = Sheet("A3", title="CBORE")
        sheet.view(part, "top", at=(150, 150))
        doc = _render_sheet(sheet, index=1, count=1, label="cbore")

        marks = [e for e in doc.modelspace().query("LINE") if e.dxf.layer == "CENTER"]
        self.assertEqual(2, len(marks), "one horizontal and one vertical arm, not two of each")


class ScaleSuggestionTests(unittest.TestCase):
    def test_the_scale_the_refusal_names_actually_fits(self) -> None:
        """Dividing the overflow out treats the whole sheet as if it scaled.

        The 47 mm between views and the 27 mm of annotation reach do not, so the
        ratio overstated what a smaller scale buys: three of four ordinary sizes
        needed two refusals, each naming another scale that did not fit either.
        """
        import re

        from build123d import Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        def attempt(dims, scale, iso):
            sheet = Sheet("A3", title="BIG", scale=scale)
            sheet.three_views(Box(*dims), iso=iso)
            try:
                _render_sheet(sheet, index=1, count=1, label="big")
            except ValueError as exc:
                return str(exc)
            return None

        for dims in ((450, 270, 112), (600, 400, 200), (320, 260, 90)):
            for iso in (False, True):
                with self.subTest(dims=dims, iso=iso):
                    message = attempt(dims, 1.0, iso)
                    self.assertIsNotNone(message, "this part does not fit at 1:1")
                    named = re.search(r"Sheet\(scale=([0-9.eE+-]+)\)", message)
                    self.assertIsNotNone(named, message)
                    self.assertIsNone(attempt(dims, float(named.group(1)), iso),
                                      f"{message}\n...and the scale it named did not fit either")

    def test_a_part_no_standard_scale_fits_says_so(self) -> None:
        from build123d import Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4", title="ENORMOUS")
        sheet.three_views(Box(4_000_000, 3_000_000, 1_000_000))
        with self.assertRaisesRegex(ValueError, "No standard scale"):
            _render_sheet(sheet, index=1, count=1, label="enormous")

    def test_the_isometric_label_states_the_scale_it_drew_at(self) -> None:
        """It stated its RATIO to the sheet, not the scale it drew at.

        On a 2:1 sheet an isometric that fitted itself to 1.96 is very nearly
        full size, and the label read "ISOMETRIC (1:1.02)" -- a reduction from
        full size that never happened. A view's scale is the shop's number.
        """
        from build123d import Box
        from cadgen.eng_drawing import Sheet

        from cadgen._internal.drawing_base import _STANDARD_SCALES, _scale_label

        sheet = Sheet("A3", title="ISO", scale=2.0)
        iso = sheet.three_views(Box(150, 90, 60), iso=True)[3]
        self.assertIsNotNone(iso.scale)
        self.assertLess(iso.scale, 2.0, "too big for the corner at the sheet's 2:1")
        self.assertIn(iso.scale, _STANDARD_SCALES, "a pictorial still states a scale a reader can use")
        self.assertEqual(iso.label, f"ISOMETRIC {_scale_label(iso.scale)}")

        full = Sheet("A3", title="ISO", scale=2.0).three_views(Box(30, 20, 10), iso=True)[3]
        self.assertIsNone(full.scale, "it fitted at the sheet's own scale")
        self.assertEqual("ISOMETRIC", full.label)


class MoreVocabularyTests(unittest.TestCase):
    """The holes left in the class the vocabulary checks closed."""

    def setUp(self) -> None:
        from cadgen.eng_drawing import Sheet

        self.view = Sheet("A4").view(_part(), "top", at=(100, 100))

    def test_a_bare_string_of_notes_is_refused(self) -> None:
        """notes="BREAK EDGES" printed eleven notes reading B, R, E, A, K...

        A str is a Sequence[str] of its own characters, and the wrong spelling
        cannot be told from the right one after the fact.
        """
        from cadgen.eng_drawing import Sheet

        with self.assertRaisesRegex(TypeError, "notes"):
            Sheet("A4", notes="BREAK EDGES")
        with self.assertRaisesRegex(TypeError, "revisions"):
            Sheet("A4", revisions="A")
        Sheet("A4", notes=["BREAK EDGES"])  # the right spelling still works

    def test_a_note_wider_than_the_sheet_is_refused(self) -> None:
        from cadgen.eng_drawing import Sheet

        with self.assertRaisesRegex(ValueError, "wider than"):
            Sheet("A4", notes=["BREAK ALL SHARP EDGES AND REMOVE BURRS " * 4])

    def test_an_ordinary_shop_note_is_accepted(self) -> None:
        """The inverse of the guard above, and the case it used to refuse.

        The guard measured `8. {note}` at `text_height` while the sheet drew
        `NOTES:  1. {note}` at 2.5 mm against the full width of the paper, so
        it refused a 44-character note with 130 mm of room to spare.
        """
        from cadgen.eng_drawing import Sheet

        for note in (
            "BREAK ALL SHARP EDGES 0.3 MAX AND DEBURR THOROUGHLY",
            "REMOVE ALL BURRS AND SHARP EDGES BEFORE FINISHING",
            "ANODISE CLEAR PER MIL-A-8625 TYPE II CLASS 1",
        ):
            with self.subTest(note=note):
                Sheet("A4", notes=[note])

    def test_the_general_tolerance_is_measured_as_it_is_spelled_out(self) -> None:
        """It reaches the paper as a whole sentence, so that is what is measured."""
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4", general_tolerance="ISO 2768-m")
        self.assertEqual(
            sheet.drawn_notes()[0],
            "TOLERANCES PER ISO 2768-m UNLESS OTHERWISE SPECIFIED.",
        )
        with self.assertRaisesRegex(ValueError, "wider than"):
            Sheet("A4", general_tolerance="ISO 2768-m AND " + "ASME Y14.5 " * 12)

    def test_every_accepted_note_fits_between_the_frame_edges(self) -> None:
        """The guard and the ink agree: what it passes, the paper holds."""
        from cadgen._internal.drawing_base import _MARGIN, _NOTE_HEIGHT, _text_width
        from cadgen.eng_drawing import Sheet

        sheet = Sheet(
            "A4",
            general_tolerance="ISO 2768-fH AND ASME Y14.5-2018 WHERE APPLICABLE",
            notes=["BREAK ALL SHARP EDGES 0.3 MAX AND DEBURR THOROUGHLY"],
        )
        room = sheet.width - 2 * _MARGIN
        for line in sheet.note_lines():
            self.assertLessEqual(_text_width(line, _NOTE_HEIGHT), room)

    def test_notes_given_as_a_generator_still_reach_the_sheet(self) -> None:
        """They are read twice, by the guard and by the draw."""
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4", notes=iter(["FIRST NOTE", "SECOND NOTE"]))
        self.assertEqual(sheet.drawn_notes(), ["FIRST NOTE", "SECOND NOTE"])
        self.assertEqual(len(sheet.note_lines()), 2)

    def test_angle_checks_its_arguments_like_every_other_verb(self) -> None:
        """It was the one verb whose arguments went unread."""
        with self.assertRaisesRegex(ValueError, "collinear"):
            self.view.angle((0, 0, 0), (1, 0, 0), (2, 0, 0))
        with self.assertRaisesRegex(ValueError, "collinear"):
            self.view.angle((0, 0, 0), (1, 0, 0), (-3, 0, 0))
        with self.assertRaisesRegex(ValueError, "non-zero length"):
            self.view.angle((0, 0, 0), (0, 0, 0), (1, 0, 0))
        with self.assertRaises(ValueError):
            self.view.angle((0, 0, 0), (1, 0, 0), (0, 1, 0), offset=float("nan"))
        with self.assertRaises(ValueError):
            self.view.angle((0, 0, 0), (1, 0, 0), (0, 1, 0), offset=0)
        self.view.angle((0, 0, 0), (1, 0, 0), (0, 1, 0))  # a real angle still works

    def test_a_note_offset_that_is_not_a_pair_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            self.view.note("HI", (0, 0, 0), offset="over there")
        with self.assertRaises(ValueError):
            self.view.note("HI", (0, 0, 0), offset=(float("inf"), 10))

    def test_a_non_finite_view_position_is_refused(self) -> None:
        """It compared False against every frame edge, so the off-frame guard
        passed it and the sheet rendered blank at exit 0."""
        from cadgen.eng_drawing import Sheet

        with self.assertRaisesRegex(ValueError, "finite"):
            Sheet("A4").view(_part(), "top", at=(float("nan"), 100))
        with self.assertRaises(TypeError):
            Sheet("A4").view(_part(), "top", at="middle")


class OverallRowTests(unittest.TestCase):
    def test_overall_clears_an_explicitly_placed_dimension(self) -> None:
        """Counting only the UNPLACED dimensions put them on the same row.

        overall() is the outermost row on its side, and an offset= the author
        wrote occupies a row just as surely as one the sheet handed out.
        """
        from build123d import Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", title="ROWS")
        top, _front, _right = sheet.three_views(Box(60, 40, 10))
        top.dim((-30, 20, 0), (0, 20, 0), offset=24.0)   # the author places this one
        top.dim((0, 20, 0), (30, 20, 0))                 # and lets the sheet place this one
        top.overall()
        doc = _render_sheet(sheet, index=1, count=1, label="rows")

        # Every horizontal dimension line above the top view, by the height it
        # was drawn at. Three dimensions, three rows: the overall pair is the
        # outermost, and no two share.
        rows = [round(d.dxf.defpoint.y, 2) for d in doc.modelspace().query("DIMENSION")
                if d.dxf.defpoint.y > top.at[1] and abs(d.dxf.angle) < 1e-6]
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len(rows), len(set(rows)), f"two dimension lines share a row: {sorted(rows)}")
        self.assertGreater(max(rows) - sorted(rows)[-2], 1.0,
                           "overall() is outermost, and clear of the row below it")


def _plate():
    """80 x 50 x 6 with four ⌀5.5 holes at (±30, ±18) and a ⌀20 bore in the middle."""
    from build123d import Align, Box, Cylinder, Pos

    align = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Box(80, 50, 6, align=align) - Cylinder(10, 6, align=align)
    for x in (-30, 30):
        for y in (-18, 18):
            part -= Pos(x, y, 0) * Cylinder(2.75, 6, align=align)
    return part


def _counterbored():
    from build123d import Align, Box, BuildPart, CounterBoreHole, Locations, Pos

    with BuildPart() as part:
        Box(60, 40, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(Pos(-15, 0, 12), Pos(15, 0, 12)):
            CounterBoreHole(radius=3.3, counter_bore_radius=5.5, counter_bore_depth=6.5)
    return part.part


def _shaft():
    from build123d import Align, Cylinder, Pos, Rot

    align = (Align.CENTER, Align.CENTER, Align.MIN)
    along_x = Rot(0, 90, 0)
    return (Pos(-50, 0, 0) * along_x * Cylinder(10, 30, align=align)
            + Pos(-20, 0, 0) * along_x * Cylinder(15, 40, align=align)
            + Pos(20, 0, 0) * along_x * Cylinder(10, 30, align=align))


def _callouts(doc, h: float = 3.5) -> list[str]:
    """Each callout as a reader reads it: its text runs and its drawn symbols, left
    to right along one line, the symbols spelled the way hole_callout_text spells
    them. A symbol is line work on the DIM layer with its own stroke weight; which
    one it is follows from its shape."""
    rows: dict[float, list[tuple[float, str]]] = {}

    def put(mid: float, x: float, piece: str) -> None:
        key = next((k for k in rows if abs(k - mid) < h * 0.3), round(mid, 3))
        rows.setdefault(key, []).append((x, piece))

    msp = doc.modelspace()
    for text in msp.query("TEXT[layer=='DIM']"):
        put(text.dxf.insert.y, text.dxf.insert.x, text.dxf.text)
    for circle in msp.query("CIRCLE[layer=='DIM']"):
        put(circle.dxf.center.y, circle.dxf.center.x - 0.5 * h, "%%c")
    for line in msp.query("LWPOLYLINE[layer=='DIM']"):
        points = list(line.get_points("xy"))
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        if len(points) == 4:
            put(min(ys) + h / 2, min(xs) - 0.12 * h, "\u2334")
        elif len(points) == 3 and max(xs) - min(xs) > 0.6 * h:
            put(min(ys) + h / 2, min(xs) - 0.1 * h, "\u2335")
        elif len(points) == 3:
            put(min(ys) + h / 2, min(xs) - 0.18 * h, "\u21a7")
    return ["".join(piece for _x, piece in sorted(row)) for _y, row in sorted(rows.items(), reverse=True)]


class FromThePartTests(unittest.TestCase):
    """A callout's numbers are the part's: read off it, or checked against it."""

    def test_a_hole_callout_reads_every_size_off_the_part(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_counterbored(), "top", at=(140, 120)).hole((15, 0, 12))
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="cb")),
                         ["2× %%c6.6 THRU   ⌴ %%c11 ↧6.5"])

    def test_a_typed_size_the_part_contradicts_is_refused(self) -> None:
        """A callout that says ⌀6 over a ⌀6.6 bore is machined faithfully, and wrong."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        for given, named in (({"diameter": 6}, "diameter=6"), ({"count": 3}, "count=3"),
                             ({"depth": 8}, "depth=8"), ({"cbore": (12, 6.5)}, "cbore=(12, 6.5)")):
            with self.subTest(given=given):
                sheet = Sheet("A4")
                sheet.view(_counterbored(), "top", at=(140, 120)).hole((15, 0, 12), **given)
                with self.assertRaises(ValueError) as caught:
                    _render_sheet(sheet, index=1, count=1, label="cb")
                self.assertIn(named, str(caught.exception))
                self.assertIn("2× ⌀6.6 THRU", str(caught.exception), "the message states what the part has")
        # What agrees with the part is accepted and changes nothing.
        sheet = Sheet("A4")
        sheet.view(_counterbored(), "top", at=(140, 120)).hole((15, 0, 12), 6.6, thru=True, count=2,
                                                               cbore=(11, 6.5))
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="cb")),
                         ["2× %%c6.6 THRU   ⌴ %%c11 ↧6.5"])

    def test_a_callout_where_there_is_no_hole_names_the_holes_there_are(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_counterbored(), "top", at=(140, 120)).hole((0, 0, 12))
        with self.assertRaisesRegex(ValueError, r"no hole runs along .* at \(-15, 0, 12\)"):
            _render_sheet(sheet, index=1, count=1, label="none")
        sheet = Sheet("A4")
        sheet.view(_counterbored(), "front", at=(140, 120)).hole((15, 0, 12))
        with self.assertRaisesRegex(ValueError, "looks down no hole"):
            _render_sheet(sheet, index=1, count=1, label="side")

    def test_a_counterbore_on_the_far_side_belongs_to_the_other_view(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_counterbored(), "bottom", at=(140, 120)).hole((15, 0, 0))
        with self.assertRaisesRegex(ValueError, "top view"):
            _render_sheet(sheet, index=1, count=1, label="far")

    def test_holes_calls_out_each_kind_of_hole_once(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 120)).holes()
        self.assertEqual(sorted(_callouts(_render_sheet(sheet, index=1, count=1, label="all"))),
                         sorted(["4× %%c5.5 THRU", "%%c20 THRU"]))

    def test_diameter_and_radius_are_measured_off_the_view(self) -> None:
        from build123d import Align, Box, fillet, Axis
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        right = sheet.view(_shaft(), "right", at=(140, 120))
        right.diameter((0, 0, 0))
        with self.assertRaisesRegex(ValueError, r"share that centre \(⌀20, ⌀30\); pass size="):
            _render_sheet(sheet, index=1, count=1, label="d")
        sheet = Sheet("A4")
        sheet.view(_shaft(), "right", at=(140, 120)).diameter((0, 0, 0), size=30)
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="d")), ["%%c30"])
        sheet = Sheet("A4")
        sheet.view(_shaft(), "right", at=(140, 120)).diameter((0, 0, 0), size=25)
        with self.assertRaisesRegex(ValueError, "no circle of that size"):
            _render_sheet(sheet, index=1, count=1, label="d")

        corners = fillet(Box(60, 40, 5, align=(Align.CENTER, Align.CENTER, Align.MIN)).edges().filter_by(Axis.Z), 6)
        sheet = Sheet("A4")
        sheet.view(corners, "top", at=(140, 120)).radius((24, 14, 5))
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="r")), ["R6"])

    def test_a_leader_points_at_the_centre_of_its_circle(self) -> None:
        """ISO 128 and ASME Y14.2 both: a leader to a circle is radial."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 120)).hole((30, 18, 6), angle=70)
        doc = _render_sheet(sheet, index=1, count=1, label="radial")
        leader = doc.modelspace().query("LEADER")[0]
        start, knee = leader.vertices[0], leader.vertices[1]
        centre = (140 + 30, 120 + 18)
        self.assertAlmostEqual(math.hypot(start[0] - centre[0], start[1] - centre[1]), 2.75, places=4,
                               msg="the arrow stops on the circle")
        cross = (start[0] - centre[0]) * (knee[1] - centre[1]) - (start[1] - centre[1]) * (knee[0] - centre[0])
        self.assertAlmostEqual(cross, 0.0, places=6, msg="and its line runs through the centre")


class ReviewFindingTests(unittest.TestCase):
    """Plausible-wrong output the first review of the hole reader found."""

    def test_holes_drilled_from_the_other_face_are_their_own_callout(self) -> None:
        from build123d import Align, Box, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = Box(80, 40, 20, align=align)
        for x in (-30, -10):
            part -= Pos(x, 0, 12) * Cylinder(3, 8, align=align)
        for x in (10, 30):
            part -= Pos(x, 0, 0) * Cylinder(3, 8, align=align)
        sheet = Sheet("A3")
        top, front, _right = sheet.three_views(part)
        top.holes()
        top.overall()
        front.overall(width=False)
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="faces", facts=facts)
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="faces")), ["2× %%c6 ↧8"])
        missing = _unstated(facts)
        self.assertEqual(len(missing), 1, missing)
        self.assertIn("2× ⌀6 ↧8 is not called out", missing[0], "the pair drilled from below")

    def test_a_section_calls_out_only_the_holes_it_keeps(self) -> None:
        from build123d import Align, Box, Cylinder, Pos, Rot
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = Box(60, 40, 20, align=align) - Pos(10, -20, 10) * Rot(-90, 0, 0) * Cylinder(3, 6, align=align)
        sheet = Sheet("A3")
        _top, front, _right = sheet.three_views(part)
        front.section("A")
        front.holes()
        notices: list[str] = []
        doc = _render_sheet(sheet, index=1, count=1, label="kept", warnings=notices)
        self.assertEqual(_callouts(doc), [], "the hole is in the half the section took away")
        self.assertTrue(any("looks down no hole" in n for n in notices), notices)

    def test_a_hole_callout_does_not_state_a_boss_of_its_radius(self) -> None:
        from build123d import Align, Box, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = Box(80, 60, 10, align=align) - Pos(-20, 0, 0) * Cylinder(15, 10, align=align) \
            + Pos(25, 0, 10) * Cylinder(7.5, 6, align=align)
        sheet = Sheet("A3")
        top, front, _right = sheet.three_views(part)
        top.overall()
        top.holes()
        front.overall(width=False)
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="boss", facts=facts)
        self.assertTrue(any("⌀15" in line for line in _unstated(facts)), "the ⌀15 boss is still unstated")

    def test_an_isometric_the_author_relabelled_keeps_its_label(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        iso = sheet.three_views(_plate(), iso=True)[3]
        iso.label = "PICTORIAL (REF)"
        texts = [e.dxf.text for e in _render_sheet(sheet, index=1, count=1, label="iso").modelspace().query("TEXT")]
        self.assertIn("PICTORIAL (REF)", texts)
        self.assertEqual(iso.label, "PICTORIAL (REF)")


class ConsoleTests(unittest.TestCase):
    def test_a_notice_prints_on_a_console_that_cannot_encode_its_symbols(self) -> None:
        """Windows CI's cp1252 console has no ⌀: the notice raised after the PDF
        was written, and the drawing failed from the message, not the work."""
        import io
        from unittest import mock

        from cadgen.eng_drawing import Sheet, eng_drawing

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            out = Path(tmp) / "plate.pdf"

            @eng_drawing(out=str(out))
            def plate():
                sheet = Sheet("A4")
                sheet.view(_plate(), "top", at=(140, 110))  # its holes are never called out
                return sheet

            console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
            with mock.patch.object(sys, "stdout", console):
                self.assertEqual(plate(), [out])
                console.flush()
                printed = console.buffer.getvalue().decode("cp1252")
            self.assertIn("\\u2300", printed, "the diameter sign as an escape, not an exception")
            self.assertTrue(out.exists())


class ColdTrialTests(unittest.TestCase):
    """What an agent given only the skill tripped over."""

    def test_a_bore_chamfered_at_both_ends_is_called_out_both_ends(self) -> None:
        from build123d import Align, Box, Cone, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        part = (Box(40, 40, 12, align=align) - Cylinder(5, 12, align=align)
                - Pos(0, 0, 11) * Cone(5, 6, 1, align=align) - Cone(6, 5, 1, align=align))
        sheet = Sheet("A4")
        sheet.view(part, "top", at=(140, 110)).holes()
        self.assertEqual(_callouts(_render_sheet(sheet, index=1, count=1, label="both")),
                         ["%%c10 THRU   ⌵ %%c12 × 90° BOTH ENDS"])

    def test_a_guessed_orientation_is_said(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        front = sheet.view(_plate(), "front", at=(140, 110))
        front.dim((40, -25, 0), (34, -25, 6))
        front.dim((-40, -25, 0), (40, -25, 6))  # 80 across, 6 up: no doubt which
        notices: list[str] = []
        _render_sheet(sheet, index=1, count=1, label="guess", warnings=notices)
        guessed = [n for n in notices if "was guessed" in n]
        self.assertEqual(len(guessed), 1, notices)
        self.assertIn("front dim 0", guessed[0])

    def test_a_part_that_is_several_solids_is_said(self) -> None:
        from build123d import Align, Box, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        split = Box(30, 20, 10, align=align) - Box(4, 30, 20, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        sheet = Sheet("A4")
        sheet.view(split, "top", at=(140, 110))
        notices: list[str] = []
        _render_sheet(sheet, index=1, count=1, label="split", warnings=notices)
        self.assertTrue(any("2 separate solids" in n for n in notices), notices)

    def test_a_dimension_to_a_hole_centre_extends_the_centre_line(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 110)).dim((-30, -18, 6), (-40, -18, 6))
        doc = _render_sheet(sheet, index=1, count=1, label="ext")
        dim = doc.modelspace().query("DIMENSION")[0]
        types = {e.dxf.linetype.upper() for e in doc.blocks.get(dim.dxf.geometry)
                 if e.dxftype() == "LINE" and e.dxf.hasattr("linetype")}
        self.assertIn("CENTER", types, "the extension line from the hole centre is a centre line")


class AssemblyEdgeTests(unittest.TestCase):
    """What a whole assembly brought out that single parts never did. The case was
    a motorcycle shock absorber, whose coil spring is 156 tilted cylinders fused
    into one solid -- too slow to build here, so each failure is forced."""

    def test_a_curve_occt_cannot_measure_is_sampled_by_its_parameter(self) -> None:
        from unittest import mock

        from build123d import Edge
        from cadgen._internal.drawing_views import _edge_polyline

        arc = Edge.make_spline([(0, 0, 0), (5, 3, 0), (10, 0, 0)])
        with mock.patch.object(type(arc), "position_at", side_effect=RuntimeError("Standard_Failure")):
            points = _edge_polyline(arc, samples=5)
        self.assertEqual(len(points), 5)
        self.assertAlmostEqual(points[0][0], 0.0, places=6)
        self.assertAlmostEqual(points[-1][0], 10.0, places=6)

    def test_an_edge_seen_end_on_draws_nothing(self) -> None:
        """A point is not a line; written, it is a zero-length entity the drawing
        checks refuse, and the whole sheet with it."""
        from unittest import mock

        import cadgen._internal.drawing_render as render
        from cadgen.drawing_checks import validate_drawing_document
        from cadgen.eng_drawing import Sheet

        real = render._edge_polyline

        def collapse(edge, samples=24):
            points = real(edge, samples)
            return [points[0]] * len(points) if len(points) > 2 else points

        sheet = Sheet("A4")
        sheet.view(_shaft(), "iso", at=(150, 110), hidden=False)
        with mock.patch.object(render, "_edge_polyline", collapse):
            doc = render._render_sheet(sheet, index=1, count=1, label="point")
        errors = [f.code for f in validate_drawing_document(doc, drawing=True) if f.severity == "error"]
        self.assertNotIn("zero_length_entity", errors)


class SymbolTests(unittest.TestCase):
    def test_drawing_symbols_are_line_work_not_glyphs(self) -> None:
        """⌴ and ⌵ are missing from common fonts and ezdxf fills Ø solid in the
        ones that have it, so no symbol reaches the page as a glyph."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        turned = Sheet("A3")
        _top, front, _right = turned.three_views(_shaft())
        front.dim((0, 0, -15), (0, 0, 15), text="%%c<>")
        cbored = Sheet("A4")
        cbored.view(_counterbored(), "top", at=(140, 120)).hole((15, 0, 12))
        for sheet in (turned, cbored):
            doc = _render_sheet(sheet, index=1, count=1, label="symbols")
            texts = [e.dxf.text for e in doc.modelspace().query("TEXT")]
            for dim in doc.modelspace().query("DIMENSION"):
                texts += [e.text for e in doc.blocks.get(dim.dxf.geometry) if e.dxftype() == "MTEXT"]
            for glyph in ("%%c", "\u00d8", "\u2300", "\u21a7", "\u2334", "\u2335"):
                self.assertFalse(any(glyph in text for text in texts), f"{glyph!r} set as a glyph: {texts}")
        doc = _render_sheet(turned, index=1, count=1, label="symbols")
        dim = next(d for d in doc.modelspace().query("DIMENSION")
                   if any(e.dxftype() == "CIRCLE" for e in doc.blocks.get(d.dxf.geometry)))
        values = [e.text for e in doc.blocks.get(dim.dxf.geometry) if e.dxftype() == "MTEXT"]
        self.assertEqual(values, ["30"], "the number stays text; the ⌀ beside it is drawn")

    def test_a_crowded_sheet_says_what_gives_it_room(self) -> None:
        from build123d import Align, Box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        top, front, _right = sheet.three_views(Box(120, 60, 50, align=(Align.CENTER, Align.CENTER, Align.MIN)))
        top.overall()
        front.overall()
        for i in range(5):
            front.dim((-60 + 8 * i, -30, 50), (60, -30, 50))
        notices: list[str] = []
        _render_sheet(sheet, index=1, count=1, label="crowded", warnings=notices)
        crowded = [n for n in notices if n.startswith("views crowded")]
        self.assertEqual(len(crowded), 1, notices)
        self.assertIn('Sheet("A3")', crowded[0])
        self.assertIn("the largest ask is the front view's top side", crowded[0].lower())


class LayoutTests(unittest.TestCase):
    def test_dimensions_nest_shortest_nearest_the_view(self) -> None:
        """Given longest first, they would cross: the long one's extension lines
        through the short one's dimension line."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 100)).dim((-40, 25, 6), (40, 25, 6)).dim((-30, 25, 6), (30, 25, 6))
        doc = _render_sheet(sheet, index=1, count=1, label="nest")
        rows = {round(abs(d.dxf.defpoint3.x - d.dxf.defpoint2.x)): d.dxf.defpoint.y
                for d in doc.modelspace().query("DIMENSION")}
        self.assertLess(rows[60], rows[80])

    def test_a_vertical_dimension_goes_on_its_own_side(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 100)).dim((-30, -18, 6), (-30, 18, 6))
        dim = _render_sheet(sheet, index=1, count=1, label="left").modelspace().query("DIMENSION")[0]
        self.assertLess(dim.dxf.defpoint.x, 140 - 40, "left of the view, beside the holes it measures")

    def test_views_are_spaced_for_the_annotation_they_carry(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        def top_view_lift(rows: int) -> float:
            sheet = Sheet("A3")
            top, front, _right = sheet.three_views(_plate())
            front.overall()
            for i in range(rows):
                front.dim((-40 + 5 * i, -25, 6), (40, -25, 6))
            notices: list[str] = []
            _render_sheet(sheet, index=1, count=1, label="room", warnings=notices)
            self.assertEqual([n for n in notices if "overlaps" in n], [])
            return top.at[1] - front.at[1]

        self.assertGreater(top_view_lift(4), top_view_lift(0) + 4 * 12 - 1e-6,
                           "four more rows above the front view push the top view up by four rows")

    def test_a_value_wider_than_its_extension_lines_is_set_beside_them(self) -> None:
        """Centred, "3 WALL" printed with both witness lines through its glyphs."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        right = sheet.view(_plate(), "right", at=(140, 100))
        right.dim((40, -25, 0), (40, -25, 3), text="<> FLOOR")
        right.dim((40, 25, 0), (40, 25, 6))
        doc = _render_sheet(sheet, index=1, count=1, label="narrow")
        for dim in doc.modelspace().query("DIMENSION"):
            low, high = sorted((dim.dxf.defpoint2.y, dim.dxf.defpoint3.y))
            mtext = next(e for e in doc.blocks.get(dim.dxf.geometry) if e.dxftype() == "MTEXT")
            inside = low < mtext.dxf.insert.y < high
            if "FLOOR" in mtext.text:
                self.assertFalse(inside, "the wide value moved beside its 3 mm")
            else:
                self.assertTrue(inside, "a value that fits stays centred; only its arrows go outside")

    def test_a_turned_part_seen_from_the_side_has_one_centre_line_end_to_end(self) -> None:
        from cadgen._internal.drawing_base import _CENTRE_OVERSHOOT
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_shaft(), "front", at=(140, 100))
        lines = [e for e in _render_sheet(sheet, index=1, count=1, label="axis").modelspace().query("LINE")
                 if e.dxf.layer == "CENTER"]
        self.assertEqual(len(lines), 1, "three steps, one axis")
        xs = sorted((lines[0].dxf.start.x, lines[0].dxf.end.x))
        self.assertAlmostEqual(xs[1] - xs[0], 100 + 2 * _CENTRE_OVERSHOOT, places=6)
        self.assertAlmostEqual(lines[0].dxf.start.y, 100, places=6, msg="on the axis")


class SheetFurnitureTests(unittest.TestCase):
    def test_the_border_is_zoned(self) -> None:
        """ISO 5457: numbered columns and lettered rows, about 50 mm each, so a
        note or a phone call can say "see C4"."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", revision="X1")  # not a zone letter, so every A..F below is a zone's
        sheet.view(_plate(), "top", at=(200, 150))
        texts = [e.dxf.text for e in _render_sheet(sheet, index=1, count=1, label="z").modelspace().query("TEXT")]
        for label in [str(n) for n in range(1, 9)] + list("ABCDEF"):
            self.assertEqual(texts.count(label), 2, f"zone {label} marked on both edges")
        self.assertNotIn("G", texts)

    def test_the_projection_symbol_is_drawn_in_the_projection_it_names(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        def symbol(projection: str) -> tuple[float, float]:
            sheet = Sheet("A3", projection=projection)
            sheet.view(_plate(), "top", at=(200, 150))
            msp = _render_sheet(sheet, index=1, count=1, label="p").modelspace()
            circles = [c for c in msp.query("CIRCLE") if c.dxf.layer == "TITLE"]
            cone = next(p for p in msp.query("LWPOLYLINE") if p.dxf.layer == "TITLE" and len(p) == 4
                        and len({round(y, 3) for _x, y in p.get_points("xy")}) == 4)
            self.assertEqual(sorted(round(c.dxf.radius, 3) for c in circles), [1.5, 3.0])
            xs = [x for x, _y in cone.get_points("xy")]
            return circles[0].dxf.center.x, sum(xs) / len(xs)

        circles_x, cone_x = symbol("THIRD ANGLE")
        self.assertGreater(circles_x, cone_x, "third angle: the end view right of the cone")
        circles_x, cone_x = symbol("FIRST ANGLE")
        self.assertLess(circles_x, cone_x, "first angle: the end view left of it")

    def test_a_field_not_given_is_an_empty_captioned_cell(self) -> None:
        """No material is not "ABS": the cell says the drawing states none."""
        from cadgen._internal.drawing_base import _MARGIN, _TITLE_W
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_sheet import _TITLE_CELLS
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", title="T")
        sheet.view(_plate(), "top", at=(200, 150))
        msp = _render_sheet(sheet, index=1, count=1, label="m").modelspace()
        x, y, w, h = _TITLE_CELLS["MATERIAL"]
        x0, y0 = 420 - _MARGIN - _TITLE_W + x, _MARGIN + y
        inside = [e.dxf.text for e in msp.query("TEXT")
                  if x0 <= e.dxf.insert.x <= x0 + w and y0 <= e.dxf.insert.y <= y0 + h]
        self.assertEqual(inside, ["MATERIAL"])

    def test_a_unit_the_sheet_does_not_measure_in_is_refused(self) -> None:
        from cadgen.eng_drawing import Sheet

        with self.assertRaisesRegex(ValueError, "25.4"):
            Sheet("A3", units="in")


class UnstatedTests(unittest.TestCase):
    """The drawing says what it leaves out, read off the part."""

    def _unstated(self, build) -> list[str]:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated

        facts = _facts()
        _render_sheet(build(), index=1, count=1, label="u", facts=facts)
        return _unstated(facts)

    def test_holes_and_sizes_left_out_are_named_with_the_call_that_states_them(self) -> None:
        from cadgen.eng_drawing import Sheet

        def build():
            sheet = Sheet("A3")
            top, _front, _right = sheet.three_views(_plate())
            top.overall()
            return sheet

        lines = self._unstated(build)
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(any("4× ⌀5.5 THRU is not called out" in line and "top.holes()" in line for line in lines))
        self.assertTrue(any("⌀20 THRU is not called out" in line for line in lines))
        self.assertTrue(any("along Z (6)" in line and "front.overall()" in line for line in lines))

    def test_a_drawing_that_states_the_part_reports_nothing(self) -> None:
        from cadgen.eng_drawing import Sheet

        def build():
            sheet = Sheet("A3")
            top, front, _right = sheet.three_views(_plate())
            top.overall()
            top.holes()
            front.overall(width=False)
            return sheet

        self.assertEqual(self._unstated(build), [])

    def test_a_turned_diameter_is_stated_and_states_the_width_across_it(self) -> None:
        from cadgen.eng_drawing import Sheet

        def build(stated: bool):
            def make():
                sheet = Sheet("A3")
                _top, front, _right = sheet.three_views(_shaft())
                front.overall(height=False)
                if stated:
                    front.dim((-35, 0, -10), (-35, 0, 10), text="%%c<>")
                    front.dim((0, 0, -15), (0, 0, 15), text="%%c<>")
                return sheet
            return make

        lines = self._unstated(build(False))
        self.assertTrue(any("⌀30" in line for line in lines) and any("⌀20" in line for line in lines), lines)
        self.assertEqual(self._unstated(build(True)), [], "⌀30 is the shaft's size in Y and in Z too")


class SectionTests(unittest.TestCase):
    """A section shows what hidden lines can only hint at."""

    def _sheet(self, part=None, **section):
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        top, front, _right = sheet.three_views(part if part is not None else _counterbored())
        front.section("A", **section)
        return sheet, top, front

    def test_a_section_hatches_what_it_cuts_and_leaves_hidden_lines_out(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        sheet, _top, front = self._sheet()
        doc = _render_sheet(sheet, index=1, count=1, label="sec")
        msp = doc.modelspace()
        hatches = list(msp.query("HATCH"))
        self.assertEqual(len(hatches), 3, "two counterbores split the cut face into three")
        self.assertTrue(all(h.dxf.pattern_name == "ANSI31" for h in hatches))
        labels = [e.dxf.text for e in msp.query("TEXT[layer=='NOTES']")]
        self.assertIn("SECTION A-A", labels)
        hidden_in_section = [e for e in msp.query("LINE LWPOLYLINE") if e.dxf.layer == "HIDDEN"
                             and all(abs(x - front.at[0]) <= 31 and abs(y - front.at[1]) <= 7
                                     for x, y in _points(e))]
        self.assertEqual(hidden_in_section, [], "a section draws no hidden lines")
        self.assertEqual(list(doc.audit().errors), [])

    def test_the_cutting_plane_is_drawn_where_it_is_seen_edge_on(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        sheet, top, _front = self._sheet(through=(0, 5, 0))
        msp = _render_sheet(sheet, index=1, count=1, label="sec").modelspace()
        plane_y = top.at[1] + 5  # the top view draws model Y up, at 1:1
        chain = [e for e in msp.query("LINE") if e.dxf.layer == "CENTER"
                 and abs(e.dxf.start.y - plane_y) < 1e-6 and abs(e.dxf.end.y - plane_y) < 1e-6]
        self.assertEqual(len(chain), 1, "one chain line across the top view, at the plane")
        self.assertGreater(abs(chain[0].dxf.end.x - chain[0].dxf.start.x), 60, "across the whole view")
        letters = [e for e in msp.query("TEXT[layer=='NOTES']") if e.dxf.text == "A"]
        self.assertEqual(len(letters), 2, "the letter at both ends")
        arrows = [l for l in msp.query("LEADER") if abs(l.vertices[1][1] - plane_y) < 1e-6]
        self.assertEqual(len(arrows), 2)
        for arrow in arrows:
            self.assertGreater(arrow.vertices[0][1], plane_y, "the front section is looked at toward +Y")

    def test_a_section_lines_up_with_the_view_above_it(self) -> None:
        """The half it keeps need not be symmetric; the drawing still aligns."""
        from build123d import Align, Box, Pos
        from cadgen._internal.drawing_render import _render_sheet

        align = (Align.MIN, Align.MIN, Align.MIN)
        step = Box(60, 20, 10, align=align) + Pos(0, 20, 0) * Box(30, 20, 25, align=align)
        sheet, top, front = self._sheet(step, through=(0, 30, 0))
        msp = _render_sheet(sheet, index=1, count=1, label="sec").modelspace()

        def xs(view):
            return [x for e in msp.query("LINE LWPOLYLINE") if e.dxf.layer == "VISIBLE"
                    for x, y in _points(e) if abs(y - view.at[1]) < 20 and abs(x - view.at[0]) < 40]

        self.assertAlmostEqual(min(xs(front)), min(xs(top)), places=6)
        self.assertLess(max(xs(front)), max(xs(top)) - 20, "it keeps only the 30 mm step, not the 60 mm base")

    def test_a_section_that_cannot_be_drawn_is_refused(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet, _top, _front = self._sheet(through=(0, 500, 0))
        with self.assertRaisesRegex(ValueError, "does not cut the part"):
            _render_sheet(sheet, index=1, count=1, label="miss")
        view = Sheet("A4").view(_plate(), "front", at=(150, 100))
        with self.assertRaisesRegex(ValueError, "ISO 128-40"):
            view.section("I")
        with self.assertRaisesRegex(ValueError, "isometric"):
            Sheet("A4").view(_plate(), "iso", at=(150, 100)).section()


class SlotAndBoltCircleTests(unittest.TestCase):
    def _plate(self):
        from build123d import Align, Box, Pos, SlotCenterToCenter, extrude

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        return _plate() - Pos(30, 0, 0) * extrude(SlotCenterToCenter(10, 6), 6) \
            - Pos(-30, 0, 0) * extrude(SlotCenterToCenter(10, 6), 6)

    def test_a_slot_is_called_out_from_the_part(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(self._plate(), "top", at=(140, 110)).holes()
        self.assertEqual(sorted(_callouts(_render_sheet(sheet, index=1, count=1, label="slot"))),
                         sorted(["2× 6 × 16 SLOT THRU", "4× %%c5.5 THRU", "%%c20 THRU"]))
        sheet = Sheet("A4")
        sheet.view(self._plate(), "top", at=(140, 110)).slot((35, 0, 6), width=8)
        with self.assertRaisesRegex(ValueError, r"reads 2× 6 × 16 SLOT THRU, but the callout was given width=8"):
            _render_sheet(sheet, index=1, count=1, label="slot")
        sheet = Sheet("A4")
        sheet.view(self._plate(), "top", at=(140, 110)).hole((30, 0, 6))
        with self.assertRaisesRegex(ValueError, r"that is a slot, not a hole; call it out with top.slot"):
            _render_sheet(sheet, index=1, count=1, label="slot")

    def test_a_slot_gets_its_centre_lines(self) -> None:
        """One down its length, past both rounded ends, and one across each end."""
        from cadgen._internal.drawing_base import _CENTRE_OVERSHOOT
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(self._plate(), "top", at=(140, 110))  # slots along X, ends at x = 25 and 35
        lines = [e for e in _render_sheet(sheet, index=1, count=1, label="slot").modelspace().query("LINE")
                 if e.dxf.layer == "CENTER"]
        along = [e for e in lines if abs(e.dxf.start.y - 110) < 1e-6 and abs(e.dxf.end.y - 110) < 1e-6
                 and min(e.dxf.start.x, e.dxf.end.x) < 170 < max(e.dxf.start.x, e.dxf.end.x)]
        self.assertEqual(len(along), 1)
        xs = sorted((along[0].dxf.start.x, along[0].dxf.end.x))
        self.assertAlmostEqual(xs[1] - xs[0], 16 + 2 * _CENTRE_OVERSHOOT, places=6)
        across = sorted(round(e.dxf.start.x, 6) for e in lines
                        if abs(e.dxf.start.x - e.dxf.end.x) < 1e-6 and abs(e.dxf.start.y - 110) < 12)
        self.assertIn(165.0, across)
        self.assertIn(175.0, across)

    def test_an_unstated_slot_is_reported(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        top, front, _right = sheet.three_views(self._plate())
        top.overall()
        top.hole((30, 18, 6))
        top.hole((0, 0, 6))
        front.overall(width=False)
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="slot", facts=facts)
        lines = _unstated(facts)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("2× 6 × 16 SLOT THRU is not called out", lines[0])
        self.assertIn("top.slot(", lines[0])

    def test_a_bolt_circle_is_stated_and_drawn(self) -> None:
        import math

        from build123d import Align, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        flange = Cylinder(40, 10, align=align) - Cylinder(15, 10, align=align)
        for k in range(6):
            a = 2 * math.pi * k / 6
            flange -= Pos(30 * math.cos(a), 30 * math.sin(a), 0) * Cylinder(3, 10, align=align)
        sheet = Sheet("A4")
        sheet.view(flange, "top", at=(140, 110)).holes()
        doc = _render_sheet(sheet, index=1, count=1, label="pcd")
        self.assertIn("6× %%c6 THRU EQ SP ON %%c60", _callouts(doc))
        pitch = [c for c in doc.modelspace().query("CIRCLE") if c.dxf.layer == "CENTER"]
        self.assertEqual([round(c.dxf.radius, 6) for c in pitch], [30.0], "the pitch circle as a chain line")

    def test_an_isometric_looks_down_no_hole(self) -> None:
        import math

        from build123d import Align, Cylinder, Pos
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        align = (Align.CENTER, Align.CENTER, Align.MIN)
        flange = Cylinder(40, 10, align=align) - Cylinder(15, 10, align=align)
        for k in range(6):
            a = 2 * math.pi * k / 6
            flange -= Pos(30 * math.cos(a), 30 * math.sin(a), 0) * Cylinder(3, 10, align=align)
        sheet = Sheet("A4")
        iso = sheet.view(flange, "iso", at=(140, 110))
        msp = _render_sheet(sheet, index=1, count=1, label="iso").modelspace()
        self.assertFalse(list(msp.query("CIRCLE LINE[layer=='CENTER']")),
                         "no pitch circle or centre marks: the isometric sees every hole slantwise")
        for call in (iso.holes, lambda: iso.hole((30, 0, 10)), lambda: iso.slot((30, 0, 10))):
            with self.assertRaisesRegex(ValueError, "isometric looks down no hole"):
                call()

    def test_overlapping_centre_lines_are_one_line(self) -> None:
        """Chain lines struck over each other out of phase print solid."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        sheet.view(_plate(), "top", at=(140, 110))
        lines = [e for e in _render_sheet(sheet, index=1, count=1, label="merge").modelspace().query("LINE")
                 if e.dxf.layer == "CENTER"]
        keys = {}
        for e in lines:
            a, b = e.dxf.start, e.dxf.end
            if abs(a.y - b.y) < 1e-6:
                keys.setdefault(("h", round(a.y, 4)), []).append(sorted((a.x, b.x)))
            elif abs(a.x - b.x) < 1e-6:
                keys.setdefault(("v", round(a.x, 4)), []).append(sorted((a.y, b.y)))
        for spans in keys.values():
            spans.sort()
            for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
                self.assertGreater(b0, a1, "two centre lines on one line overlap")


class DetailTests(unittest.TestCase):
    def _sheet(self, **detail):
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        top, front, right, iso = sheet.three_views(_shaft(), iso=True)
        front.overall(height=False)
        return sheet, front, sheet.detail(front, (50, 0, 10), 4, **detail)

    def test_a_detail_is_drawn_larger_clipped_and_marked(self) -> None:
        from cadgen._internal.drawing_base import _MARGIN
        from cadgen._internal.drawing_render import _render_sheet

        sheet, front, detail = self._sheet()
        msp = _render_sheet(sheet, index=1, count=1, label="detail").modelspace()
        self.assertEqual(detail.scale, 5.0, "the largest standard scale that keeps the circle within 60 mm")
        labels = [e.dxf.text for e in msp.query("TEXT[layer=='NOTES']")]
        self.assertIn("DETAIL B (5:1)", labels)
        self.assertIn("B", labels, "the letter beside the circle on the parent")
        rings = sorted(round(c.dxf.radius, 6) for c in msp.query("CIRCLE") if c.dxf.layer == "NOTES")
        self.assertEqual(rings, [4.0, 20.0], "the parent's circle at 1:1, the detail's boundary at 5:1")
        cx, cy = detail.at
        for entity in msp.query("LINE LWPOLYLINE"):
            if entity.dxf.layer != "VISIBLE":
                continue
            for x, y in _points(entity):
                if abs(x - cx) < 30 and abs(y - cy) < 30:
                    self.assertLessEqual(math.hypot(x - cx, y - cy), 20 + 1e-6, "geometry outside the circle")
        self.assertTrue(_MARGIN < cx - 20 and cx + 20 < 420 - _MARGIN and _MARGIN < cy - 20 and cy + 20 < 297 - _MARGIN)

    def test_a_detail_is_cut_by_cutting_its_parent(self) -> None:
        _sheet, _front, detail = self._sheet()
        with self.assertRaisesRegex(ValueError, "cut the parent view"):
            detail.section("A")

    def test_a_detail_steps_down_when_the_paper_is_short(self) -> None:
        """A scale the sheet chose gives way to the next standard one down; the
        label says the scale it was drawn at."""
        from unittest import mock

        import cadgen._internal.drawing_render as render
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        _top, front, _right = sheet.three_views(_shaft())
        detail = sheet.detail(front, (50, 0, 10), 2.5)
        self.assertEqual(detail.scale, 10.0)
        real = render._place_detail
        with mock.patch.object(render, "_place_detail",
                               side_effect=lambda sh, size, *a: None if size > 30 else real(sh, size, *a)):
            render._render_sheet(sheet, index=1, count=1, label="detail")
        self.assertEqual(detail.scale, 5.0)
        self.assertEqual(detail.label, "DETAIL B (5:1)")

    def test_a_detail_given_its_scale_is_refused_when_it_cannot_fit(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A4")
        _top, front, _right = sheet.three_views(_shaft())
        sheet.detail(front, (50, 0, 10), 10, scale=10)
        with self.assertRaisesRegex(ValueError, "no free paper"):
            _render_sheet(sheet, index=1, count=1, label="detail")

    def test_a_detail_of_a_section_keeps_the_hatching(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        _top, front, right = sheet.three_views(_counterbored())
        front.section("A")
        detail = sheet.detail(front, (15, 0, 12), 6, letter="C")
        doc = _render_sheet(sheet, index=1, count=1, label="detail")
        hatches = [h for h in doc.modelspace().query("HATCH")
                   if all(math.hypot(x - detail.at[0], y - detail.at[1]) <= 6 * detail.scale + 1e-3
                          for path in h.paths for x, y, *_ in path.vertices)]
        self.assertTrue(hatches, "the section's hatch, clipped to the detail")
        self.assertEqual(sum(1 for e in doc.modelspace().query("TEXT[layer=='NOTES']") if e.dxf.text == "A"), 2,
                         "one cutting plane, not one per view of the section")

    def test_a_detail_states_only_what_it_holds(self) -> None:
        """One identical hole in the circle is one callout; the other three are
        still unstated."""
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        top, front, _right = sheet.three_views(_plate())
        top.overall()
        top.hole((0, 0, 6))
        front.overall(width=False)
        sheet.detail(top, (30, 18, 6), 5).holes()
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="d", facts=facts)
        missing = _unstated(facts)
        self.assertEqual(len(missing), 1, missing)
        self.assertIn("3× ⌀5.5 THRU is not called out", missing[0])

    def test_a_detail_follows_a_section_made_after_it(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        _top, front, _right = sheet.three_views(_counterbored())
        detail = sheet.detail(front, (15, 0, 12), 6, letter="C")
        front.section("A")
        doc = _render_sheet(sheet, index=1, count=1, label="d")
        self.assertTrue(any(all(math.hypot(x - detail.at[0], y - detail.at[1]) <= 6 * detail.scale + 1e-3
                                for path in h.paths for x, y, *_ in path.vertices)
                            for h in doc.modelspace().query("HATCH")))

    def test_a_letter_names_one_view(self) -> None:
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        _top, front, right = sheet.three_views(_shaft())
        front.section("A")
        sheet.detail(front, (50, 0, 10), 4)
        with self.assertRaisesRegex(ValueError, "already names DETAIL B"):
            sheet.detail(front, (-50, 0, 10), 4)
        with self.assertRaisesRegex(ValueError, "already names SECTION A-A"):
            sheet.detail(right, (0, 0, 0), 4, letter="A")
        with self.assertRaisesRegex(ValueError, "already names SECTION A-A"):
            right.section("A")

    def test_a_detail_of_an_isometric_is_refused(self) -> None:
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        iso = sheet.three_views(_shaft(), iso=True)[3]
        with self.assertRaisesRegex(ValueError, "isometric"):
            sheet.detail(iso, (0, 0, 0), 5)
        with self.assertRaisesRegex(ValueError, "ISO 128-40"):
            sheet.detail(sheet.views[1], (0, 0, 0), 5, letter="O")

    def test_cutting_plane_letters_keep_clear_of_the_view_label(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        _top, front, right = sheet.three_views(_shaft())
        right.section("A", through=(0, 0, 0))
        msp = _render_sheet(sheet, index=1, count=1, label="letters").modelspace()
        label = next(e for e in msp.query("TEXT[layer=='NOTES']") if e.dxf.text == "FRONT")
        letters = [e for e in msp.query("TEXT[layer=='NOTES']") if e.dxf.text == "A"]
        lowest = min(e.dxf.insert.y for e in letters)
        self.assertLess(label.dxf.insert.y, lowest - 3, "the label hangs under the cutting plane's letter")


def _assembly():
    """A plate, two identical pins standing in its holes, a closed housing on it
    and a core sealed inside the housing, which no view can show."""
    from build123d import Align, Box, Compound, Cylinder, Pos

    base_align = (Align.CENTER, Align.CENTER, Align.MIN)
    base = Box(80, 50, 6, align=base_align) - Pos(25, 0, 0) * Cylinder(3, 6, align=base_align) \
        - Pos(-25, 0, 0) * Cylinder(3, 6, align=base_align)
    base.label = "base"
    pins = []
    for x in (-25, 25):
        pin = Pos(x, 0, 0) * Cylinder(3, 20, align=base_align)
        pin.label = "pin"
        pins.append(pin)
    housing = Pos(0, 0, 6) * (Box(20, 20, 10, align=base_align) - Pos(0, 0, 2) * Box(16, 16, 6, align=base_align))
    housing.label = "housing"
    core = Pos(0, 0, 9) * Box(4, 4, 4, align=base_align)
    core.label = "core"
    return Compound(children=[base, *pins, housing, core], label="fixture")


def _balloons(doc):
    """Each balloon as (item number, its centre, the point its leader keys)."""
    from cadgen._internal.drawing_assembly import _BALLOON_R, _BALLOON_TEXT

    msp = doc.modelspace()
    circles = [e for e in msp.query("CIRCLE[layer=='NOTES']") if abs(e.dxf.radius - _BALLOON_R) < 1e-9]
    numbers = [e for e in msp.query("TEXT[layer=='NOTES']") if abs(e.dxf.height - _BALLOON_TEXT) < 1e-9]
    lines = list(msp.query("LINE[layer=='NOTES']"))
    out = []
    for circle in circles:
        c = (circle.dxf.center.x, circle.dxf.center.y)
        number = next(int(t.dxf.text) for t in numbers
                      if math.hypot(t.dxf.align_point.x - c[0], t.dxf.align_point.y - c[1]) < 1e-6)
        leader = next(e for e in lines if abs(math.hypot(e.dxf.start.x - c[0], e.dxf.start.y - c[1]) - _BALLOON_R)
                      < 1e-6)
        out.append((number, c, (leader.dxf.end.x, leader.dxf.end.y)))
    return out


class AssemblyDrawingTests(unittest.TestCase):
    """An assembly drawn as one: a parts list read off it, balloons keyed to that
    list, and a sheet per part."""

    def test_the_parts_list_counts_copies_and_keeps_named_and_mirrored_parts_apart(self) -> None:
        from build123d import Box, Compound, Cylinder, Plane, Pos

        from cadgen.eng_drawing import parts_list

        parts = parts_list(_assembly())
        self.assertEqual([(i.number, i.description, i.quantity) for i in parts],
                         [(1, "BASE", 1), (2, "PIN", 2), (3, "HOUSING", 1), (4, "CORE", 1)])
        self.assertIs(parts["pin"], parts[2])
        self.assertEqual(len(parts[2].occurrences), 2)
        # Mirror images share a name and a volume, never a part number; and one
        # shape under two names may be two materials.
        bracket = Box(20, 10, 5) - Pos(5, 2, 0) * Cylinder(1.5, 5)
        left, right = Pos(0, 0, 0) * bracket, Pos(40, 0, 0) * bracket.mirror(Plane.YZ)
        left.label, right.label = "bracket:left", "bracket:right"
        spacer_a, spacer_b = Pos(0, 30, 0) * Box(5, 5, 5), Pos(10, 30, 0) * Box(5, 5, 5)
        spacer_a.label, spacer_b.label = "spacer_steel", "spacer_brass"
        kept = parts_list(Compound(children=[left, right, spacer_a, spacer_b]))
        self.assertEqual([i.quantity for i in kept], [1, 1, 1, 1])
        self.assertEqual([i.description for i in kept], ["BRACKET, LEFT", "BRACKET, RIGHT", "SPACER STEEL",
                                                         "SPACER BRASS"])

    def test_items_are_found_by_number_or_name_and_filled_in_only_where_asked(self) -> None:
        from cadgen.eng_drawing import parts_list

        parts = parts_list(_assembly())
        parts.set("base", material="6061-T6", part_number="FX-101").set(3, description="SEALED HOUSING")
        self.assertEqual((parts[1].material, parts[1].part_number), ("6061-T6", "FX-101"))
        self.assertEqual(parts[3].description, "SEALED HOUSING")
        self.assertEqual((parts[2].material, parts[2].part_number), ("", ""), "nothing invented")
        with self.assertRaisesRegex(KeyError, "its items are 1 base"):
            parts["washer"]
        with self.assertRaisesRegex(KeyError, "numbers 1 to 4"):
            parts[5]
        with self.assertRaisesRegex(TypeError, "not finish"):
            parts.set(1, finish="ANODISE")
        with self.assertRaisesRegex(TypeError, "single part"):
            parts_list(_plate())

    def test_a_saved_assembly_counts_shared_prototypes(self) -> None:
        import os
        from unittest import mock

        from build123d import Box, Compound, Cylinder, Location

        import cadgen
        from cadgen.eng_drawing import parts_list
        from cadgen.step_export import export_build123d_step_file

        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(Path(tmp) / "store"), "CADGEN_DAEMON": "0"}):
                pin = Cylinder(3, 20)
                placed = []
                for x in (-10.0, 10.0, 30.0):
                    copy = pin.moved(Location((x, 0, 0)))
                    copy.label = "pin"
                    placed.append(copy)
                plate = Box(60, 20, 4)
                plate.label = "plate"
                # One geometry, two names: the STEP shares their prototype, and they
                # are still two parts (a steel spacer is not a brass one).
                steel, brass = Box(5, 5, 5).moved(Location((0, 30, 0))), Box(5, 5, 5).moved(Location((20, 30, 0)))
                steel.label, brass.label = "spacer_steel", "spacer_brass"
                path = Path(tmp) / "fixture.step"
                export_build123d_step_file(Compound(children=[plate, *placed, steel, brass], label="fixture"), path)
                parts = parts_list(cadgen.read_scene(path))
        self.assertEqual([(i.description, i.quantity) for i in parts],
                         [("PLATE", 1), ("PIN", 3), ("SPACER STEEL", 1), ("SPACER BRASS", 1)])
        self.assertEqual(parts[2].refs, ("#o1.2", "#o1.3", "#o1.4"))
        self.assertEqual(parts.twins, ((3, 4),))
        parts.merge(3, 4, description="SPACER")
        self.assertEqual([(i.number, i.description, i.quantity) for i in parts],
                         [(1, "PLATE", 1), (2, "PIN", 3), (3, "SPACER", 2)])
        with self.assertRaisesRegex(ValueError, "not the same shape"):
            parts.merge(1, 2)

    def test_balloons_key_each_part_it_shows_once_with_a_dot_on_the_part(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly())
        sheet = Sheet("A3", title="FIXTURE")
        sheet.parts_list(parts)
        front = sheet.view(parts.assembly, "front", at=(110, 200), hidden=False)
        iso = sheet.view(parts.assembly, "iso", at=(110, 90), hidden=False)
        front.balloons(parts)
        iso.balloons(parts)
        warnings: list = []
        facts = _facts()
        doc = _render_sheet(sheet, index=1, count=1, label="balloons", warnings=warnings, facts=facts)
        found = _balloons(doc)
        self.assertEqual(sorted(n for n, _c, _p in found), [1, 2, 3], "the sealed core has no balloon")
        for _n, centre, point in found:
            self.assertGreater(math.hypot(centre[0] - point[0], centre[1] - point[1]), 5.0)
        dots = [e for e in doc.modelspace().query("HATCH[layer=='NOTES']")]
        self.assertEqual(len(dots), 3)
        self.assertFalse([w for w in warnings if "separate solids" in w], warnings)
        from cadgen._internal.drawing_report import _unstated

        report = _unstated(facts)
        self.assertTrue(any("item 4 (CORE) has no balloon" in line for line in report), report)
        self.assertFalse([line for line in report if "turned diameter" in line or "not called out" in line],
                         "an assembly's holes are its parts' to state")

    def test_a_column_of_balloons_keeps_its_leaders_in_order(self) -> None:
        from build123d import Box, Compound, Pos

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        stack = []
        for k in range(6):
            block = Pos(0, 0, 12 * k) * Box(30 - 2 * k, 30 - 2 * k, 10)
            block.label = f"block_{k}"
            stack.append(block)
        parts = parts_list(Compound(children=stack))
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        sheet.view(parts.assembly, "front", at=(120, 180), hidden=False).overall().balloons(parts)
        doc = _render_sheet(sheet, index=1, count=1, label="column")
        found = _balloons(doc)
        self.assertEqual(len(found), 6)
        # No leader runs through the overall height's value, which reads up the
        # dimension line beside the left column.
        value = next(m for d in doc.modelspace().query("DIMENSION") for m in doc.blocks.get(d.dxf.geometry)
                     if m.dxftype() == "MTEXT" and abs(float(m.dxf.get("rotation", 0) or 0) - 90) < 1e-6)
        half = len(value.text) * 0.7 * value.dxf.char_height / 2
        x, y = value.dxf.insert.x, value.dxf.insert.y
        for _n, c, p in found:
            through = [(c[0] + (p[0] - c[0]) * t / 50, c[1] + (p[1] - c[1]) * t / 50) for t in range(51)]
            self.assertFalse([q for q in through if abs(q[0] - x) < 1.5 and abs(q[1] - y) < half],
                             "a leader runs through the height's value")
        for side in (-1, 1):
            column = sorted((c[1], p[1]) for _n, c, p in found if (c[0] - 120) * side > 0)
            self.assertEqual([p for _c, p in column], sorted(p for _c, p in column), "leaders cross")
        self.assertLessEqual(abs(sum(1 for _n, c, _p in found if c[0] < 120) - 3), 1, "columns are even")

    def test_a_vertical_dimension_value_claims_the_paper_it_reads_up(self) -> None:
        """A height's value is turned with its line. Measured unturned, its box was
        wide and short, and a balloon's leader or a note over its digits went
        unnoticed."""
        from build123d import Box

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        tall = Box(20, 20, 150)
        probe = Sheet("A3")
        probe.view(tall, "front", at=(150, 150)).overall()
        doc = _render_sheet(probe, index=1, count=1, label="probe")
        value = next(m for d in doc.modelspace().query("DIMENSION") for m in doc.blocks.get(d.dxf.geometry)
                     if m.dxftype() == "MTEXT" and m.text == "150")
        x, y = value.dxf.insert.x, value.dxf.insert.y
        # A note whose text starts just above the value's middle: on its digits,
        # clear of the box an unturned value would claim. Its model point is
        # drawn at (140, 225); a note leading left ends its text 4 short of the
        # leader's end, 1 above it.
        sheet = Sheet("A3")
        sheet.view(tall, "front", at=(150, 150)).overall().note("X", (-10, -10, 75),
                                                                  offset=(x + 5.25 - 140.0, y + 1.5 - 225.0))
        warnings: list = []
        _render_sheet(sheet, index=1, count=1, label="over", warnings=warnings)
        self.assertTrue(any("'X' is printed over '150'" in w for w in warnings), warnings)

    def test_a_separate_solids_notice_points_an_assembly_at_the_parts_list(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3")
        sheet.view(_assembly(), "front", at=(150, 150), hidden=False)
        warnings: list = []
        _render_sheet(sheet, index=1, count=1, label="solids", warnings=warnings)
        self.assertTrue(any("separate solids" in w and "assembly_sheets(parts_list(" in w for w in warnings), warnings)

    def test_balloons_refuse_another_shape_a_section_or_a_detail(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly())
        sheet = Sheet("A3")
        with self.assertRaisesRegex(ValueError, "parts.assembly"):
            sheet.view(_plate(), "front", at=(150, 150)).balloons(parts)
        front = sheet.view(parts.assembly, "front", at=(150, 150))
        front.section("A")
        with self.assertRaisesRegex(ValueError, "is a section"):
            front.balloons(parts)
        sheet = Sheet("A3")
        front = sheet.view(parts.assembly, "front", at=(150, 150)).balloons(parts)
        front.section("A")
        with self.assertRaisesRegex(ValueError, "is a section"):
            _render_sheet(sheet, index=1, count=1, label="cut")

    def test_the_parts_list_stands_on_the_title_block_and_reads_upward(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly())
        parts.set(1, material="6061-T6")
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        msp = _render_sheet(sheet, index=1, count=1, label="list").modelspace()
        rows = {e.dxf.text: e.dxf.align_point.y for e in msp.query("TEXT[layer=='TITLE']")}
        self.assertLess(rows["DESCRIPTION"], rows["BASE"])
        self.assertLess(rows["BASE"], rows["PIN"])
        self.assertLess(rows["PIN"], rows["CORE"])
        self.assertIn("6061-T6", rows)
        self.assertLess(rows["DESCRIPTION"], 10 + 40 + 7, "the header sits on the title block")

    def test_a_long_parts_list_is_refused_with_where_to_split_it(self) -> None:
        from build123d import Box, Compound, Pos

        from cadgen.eng_drawing import Sheet, parts_list

        blocks = []
        for k in range(40):
            block = Pos(0, 0, 12 * k) * Box(10, 10, 10 + k * 0.1)
            block.label = f"block_{k}"
            blocks.append(block)
        parts = parts_list(Compound(children=blocks))
        with self.assertRaisesRegex(ValueError, r"parts_list\(parts, last=\d+\).*parts_list\(parts, first=\d+\)"):
            Sheet("A4").parts_list(parts)

    def test_a_split_parts_list_says_where_it_continues(self) -> None:
        from cadgen.eng_drawing import Sheet, eng_drawing, parts_list

        parts = parts_list(_assembly())
        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            seen = {}

            @eng_drawing(out=str(Path(tmp) / "split.pdf"))
            def split():
                first, rest = Sheet("A4"), Sheet("A4")
                first.parts_list(parts, last=2)
                rest.parts_list(parts, first=3)
                return [first, rest]

            import cadgen.eng_drawing as drawing

            real = drawing._render_sheet

            def capture(sheet, **kwargs):
                doc = real(sheet, **kwargs)
                seen[kwargs["index"]] = [e.dxf.text for e in doc.modelspace().query("TEXT")]
                return doc

            from unittest import mock

            with mock.patch.object(drawing, "_render_sheet", capture):
                split()
        self.assertIn("PARTS LIST, CONTINUED ON SHEET 2", seen[1])
        self.assertIn("PARTS LIST, CONTINUED FROM SHEET 1", seen[2])

    def test_a_view_over_the_parts_list_or_a_note_under_it_is_refused(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly())
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        sheet.view(_plate(), "top", at=(330, 70))
        with self.assertRaisesRegex(ValueError, "over the parts list"):
            _render_sheet(sheet, index=1, count=1, label="over")
        sheet = Sheet("A4", notes=["A NOTE LONG ENOUGH TO RUN PAST THE LEFT HALF OF AN A4 SHEET AND UNDER IT"])
        sheet.parts_list(parts)
        with self.assertRaisesRegex(ValueError, "runs under the parts list"):
            _render_sheet(sheet, index=1, count=1, label="note")

    def test_assembly_sheets_draws_an_arrangement_and_a_sheet_per_part(self) -> None:
        from cadgen.eng_drawing import assembly_sheets, eng_drawing, parts_list

        parts = parts_list(_assembly())
        sheets = assembly_sheets(parts, title="FIXTURE", part_number="FX-100")
        self.assertEqual(len(sheets), 1 + len(parts))
        ga, pin = sheets[0], sheets.part("pin")
        self.assertEqual([v.name for v in ga.views], ["front", "top", "iso"])
        self.assertTrue(all(not v.hidden for v in ga.views))
        self.assertEqual((pin.title, pin.subtitle, pin.part_number), ("PIN", "ITEM 2 (QTY 2) OF FIXTURE", "FX-100"))
        self.assertEqual(sheets.part(1).views[0].shape.bounding_box().size.Z, 6, "drawn in its own frame")
        with temporary_directory(prefix="tmp-cad-eng-drawing-") as tmp:
            printed: list[str] = []

            @eng_drawing(out=str(Path(tmp) / "fixture.pdf"))
            def fixture():
                return sheets

            from unittest import mock

            with mock.patch("builtins.print", side_effect=lambda line: printed.append(str(line))):
                fixture()
        self.assertFalse([line for line in printed if "separate solids" in line or "holes():" in line], printed)
        self.assertTrue(any("item 4 (CORE) has no balloon" in line for line in printed), printed)
        self.assertFalse([line for line in printed if "incomplete: sheet" in line],
                         "a first pass states every part's overall sizes and holes")

    def test_a_round_parts_sheet_has_one_side_view_and_states_its_diameters(self) -> None:
        from build123d import Align, Box, Compound, Cylinder, Pos

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import assembly_sheets, parts_list

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        plate = Box(60, 40, 8, align=up)
        plate.label = "plate"
        pin = Pos(15, 0, 8) * (Cylinder(3, 20, align=up) + Pos(0, 0, 20) * Cylinder(5, 4, align=up))
        pin.label = "pin"
        sheets = assembly_sheets(parts_list(Compound(children=[plate, pin])), title="RIG")
        sheet = sheets.part("pin")
        names = [v.name for v in sheet.views]
        self.assertEqual(names, ["front", "right", "iso"], "one side view and the end view; no repeat")
        size = sheet.views[0].shape.bounding_box().size
        self.assertGreater(size.X, size.Z, "a long turned part is drawn lying down, its axis across the sheet")
        facts = _facts()
        doc = _render_sheet(sheet, index=1, count=1, label="pin", facts=facts)
        # The ⌀ is drawn as line work beside each value, so the text is the number.
        self.assertEqual(sorted(_dim_texts(doc)), ["10", "24", "6"], "two diameters and the length, once each")
        self.assertFalse([line for line in _unstated(facts) if "overall size" in line or "turned diameter" in line],
                         "the diameters state the sizes across the axis")

    def test_a_flat_turned_part_keeps_its_face_view(self) -> None:
        from build123d import Align, Box, Compound, Cylinder

        from cadgen.eng_drawing import assembly_sheets, parts_list

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        base = Box(80, 80, 6, align=up)
        base.label = "base"
        washer = Cylinder(20, 3, align=up) - Cylinder(8, 3, align=up)
        washer.label = "washer"
        sheet = assembly_sheets(parts_list(Compound(children=[base, washer])), title="RIG").part("washer")
        self.assertEqual([v.name for v in sheet.views], ["top", "front", "iso"], "a disc stays flat: face and edge")

    def test_a_cones_widest_diameter_states_its_size_across_the_axis(self) -> None:
        from build123d import Align, Box, Compound, Cone

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import assembly_sheets, parts_list

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        base = Box(80, 80, 6, align=up)
        base.label = "base"
        seat = Cone(36, 20, 12, align=up)
        seat.label = "seat"
        sheet = assembly_sheets(parts_list(Compound(children=[base, seat])), title="RIG").part("seat")
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="seat", facts=facts)
        self.assertFalse([line for line in _unstated(facts) if "overall size" in line], _unstated(facts))

    def test_on_a_drawing_of_several_parts_each_gap_names_its_sheet(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet

        facts = _facts()
        for index, (title, part) in enumerate((("SHAFT", _shaft()), ("PLATE", _plate())), start=1):
            sheet = Sheet("A3", title=title)
            sheet.three_views(part)
            _render_sheet(sheet, index=index, count=2, label="two", facts=facts)
        report = _unstated(facts)
        self.assertTrue(report)
        self.assertTrue(all(line.startswith(("incomplete: sheet 1 (SHAFT): ", "incomplete: sheet 2 (PLATE): "))
                            for line in report), report)

    def test_a_sheet_that_chose_its_scale_steps_down_rather_than_refusing(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        def bracket(sheet):
            part, point = _inclined()
            top, front, _right, _iso = sheet.three_views(part, iso=True)
            top.overall()
            top.holes()
            front.overall(width=False)
            sheet.auxiliary(front, point).holes()
            return sheet

        chosen = bracket(Sheet("A4", None))
        _render_sheet(chosen, index=1, count=1, label="fit")
        self.assertLess(chosen._scale(), 1.0, "no room for VIEW C at 1:1 on A4, so the next scale down")
        with self.assertRaisesRegex(ValueError, "no free paper"):
            _render_sheet(bracket(Sheet("A4", 1.0)), index=1, count=1, label="fixed")

    def test_balloons_spread_clear_of_each_other_and_of_text_beside_them(self) -> None:
        from cadgen._internal.drawing_assembly import spread

        self.assertEqual(spread([0, 1, 2], 10, -100, 100), [-9.0, 1.0, 11.0])
        self.assertEqual(spread([0, 1, 2], 10, 0, 100), [0, 10, 20])
        for desired, gap, avoid in (([0, 10, 20, 30], 10, [(5, 15)]), ([0, 1, 2, 26], 12, [(15, 25)]),
                                    ([40, 41, 42, 43, 44], 12, [(45, 55)])):
            placed = spread(desired, gap, 0 if gap == 12 else -100, 100, avoid=avoid)
            self.assertFalse([y for y in placed for a, b in avoid if a < y < b], placed)
            self.assertTrue(all(b - a >= gap - 1e-9 for a, b in zip(placed, placed[1:])), placed)
        # A run that cannot fit runs past the end, for the caller to refuse.
        self.assertGreater(spread([0, 1, 2], 12, 0, 20)[-1], 20)

    def test_balloons_stay_on_the_paper_clear_of_the_parts_list_or_are_refused(self) -> None:
        from build123d import Box, Compound, Pos

        from cadgen._internal.drawing_base import _MARGIN, _TITLE_H, _TITLE_W
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_sheet import _list_height
        from cadgen.eng_drawing import Sheet, parts_list

        def stack(count):
            kids = []
            for k in range(count):
                block = Pos(-20 + (k % 2) * 40, 0, 6 * k) * Box(6 + 0.1 * k, 6, 3)
                block.label = f"block_{k}"
                kids.append(block)
            return parts_list(Compound(children=kids))

        parts = stack(16)
        sheet = Sheet("A3", scale=0.5)  # the view is shorter than its balloon columns
        sheet.parts_list(parts)
        sheet.view(parts.assembly, "front", at=(150, 250), hidden=False).balloons(parts)
        found = _balloons(_render_sheet(sheet, index=1, count=1, label="off"))
        self.assertEqual(len(found), 16)
        table = (sheet.width - _MARGIN - _TITLE_W, _MARGIN + _TITLE_H + _list_height(sheet))
        for _n, c, _p in found:
            self.assertTrue(_MARGIN + 5 <= c[1] <= sheet.height - _MARGIN - 5, c)
            self.assertFalse(c[0] + 5 > table[0] and c[1] - 5 < table[1], "a balloon on the parts list")
        crowd = stack(40)
        crowded = Sheet("A4", scale=0.5)
        crowded.view(crowd.assembly, "front", at=(100, 140), hidden=False).balloons(crowd)
        with self.assertRaisesRegex(ValueError, "do not fit"):
            _render_sheet(crowded, index=1, count=1, label="crowded")

    def test_leaders_neither_cross_nor_run_through_a_value(self) -> None:
        from build123d import Box, Compound, Pos
        from shapely.geometry import LineString

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        post = Pos(100, 0, 150) * Box(10, 10, 300)
        post.label = "post"
        kids = [post]
        for name, x, z in (("near", -100, 150.0), ("far", -30, 150.1), ("b", -90, 150.2), ("c", -80, 150.3)):
            block = Pos(x, 0, z) * Box(8, 8, 8)
            block.label = name
            kids.append(block)
        parts = parts_list(Compound(children=kids))
        sheet = Sheet("A3", scale=0.5)
        sheet.parts_list(parts)
        sheet.view(parts.assembly, "front", at=(120, 170), hidden=False).overall().balloons(parts)
        doc = _render_sheet(sheet, index=1, count=1, label="cross")
        leaders = [LineString([c, p]) for _n, c, p in _balloons(doc)]
        self.assertFalse([(a, b) for i, a in enumerate(leaders) for b in leaders[i + 1:] if a.crosses(b)])
        value = next(m for d in doc.modelspace().query("DIMENSION") for m in doc.blocks.get(d.dxf.geometry)
                     if m.dxftype() == "MTEXT" and abs(float(m.dxf.get("rotation", 0) or 0) - 90) < 1e-6)
        x, y, half = value.dxf.insert.x, value.dxf.insert.y, len(value.text) * 0.7 * value.dxf.char_height / 2
        from shapely.geometry import box

        self.assertFalse([path for path in leaders if path.intersects(box(x - 1.75, y - half, x + 1.75, y + half))])

    def test_a_part_showing_a_narrow_band_is_still_ballooned(self) -> None:
        from build123d import Align, Compound, Cylinder, Pos

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        rod = Cylinder(4, 100, align=up)
        rod.label = "rod"
        body = Cylinder(12, 82, align=up) - Cylinder(4, 82, align=up)
        body.label = "body"
        eye = Pos(0, 0, 100) * Cylinder(10, 20, align=up)
        eye.label = "eye"
        parts = parts_list(Compound(children=[body, rod, eye]))
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        sheet.view(parts.assembly, "front", at=(120, 170), hidden=False).balloons(parts)
        self.assertEqual(sorted(n for n, _c, _p in _balloons(_render_sheet(sheet, index=1, count=1, label="rod"))),
                         [1, 2, 3], "18 mm of the rod shows between the body and the eye")

    def test_balloons_stand_outside_the_hole_callouts(self) -> None:
        from build123d import Box, Compound, Cylinder, Pos, Rot
        from shapely.geometry import LineString, Point

        from cadgen._internal.drawing_assembly import _BALLOON_R
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        plate = Box(40, 10, 150) - Pos(-10, 0, 40) * Rot(90, 0, 0) * Cylinder(4, 10)
        plate.label = "plate"
        block = Pos(0, 0, 85) * Box(20, 20, 20)
        block.label = "block"
        lug = Pos(-25, 0, 44) * Box(6, 6, 6)
        lug.label = "lug"
        parts = parts_list(Compound(children=[plate, block, lug]))
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        front = sheet.view(parts.assembly, "front", at=(140, 170), hidden=False)
        front.hole((-10, -5, 40))
        front.balloons(parts)
        doc = _render_sheet(sheet, index=1, count=1, label="callout")
        callouts = [LineString([(v[0], v[1]) for v in e.vertices]) for e in doc.modelspace().query("LEADER[layer=='DIM']")]
        for _n, c, _p in _balloons(doc):
            self.assertTrue(all(path.distance(Point(c)) > _BALLOON_R for path in callouts))

    def test_the_general_arrangement_refuses_paper_too_small_for_it(self) -> None:
        from build123d import Box, Compound, Pos

        from cadgen.eng_drawing import assembly_sheets, parts_list

        post = Box(20, 20, 120)
        post.label = "post"
        cap = Pos(0, 0, 65) * Box(30, 30, 10)
        cap.label = "cap"
        with self.assertRaisesRegex(ValueError, "larger size="):
            assembly_sheets(parts_list(Compound(children=[post, cap])), title="POST", size="A4")

    def test_a_value_too_long_for_its_column_is_refused_not_cut(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly()).set(1, part_number="MSA-100-0042-REV-C-ALT-STEEL-OPTION-77")
        sheet = Sheet("A3")
        sheet.parts_list(parts)
        with self.assertRaisesRegex(ValueError, r"parts.set\(1, part_number=\.\.\.\)"):
            _render_sheet(sheet, index=1, count=1, label="long")

    def test_runs_of_one_list_may_not_overlap_or_climb_into_the_revisions(self) -> None:
        from cadgen._internal.drawing_assembly import _continuations
        from cadgen.eng_drawing import Sheet, parts_list

        parts = parts_list(_assembly())
        first, second = Sheet("A3"), Sheet("A3")
        first.parts_list(parts, last=3)
        second.parts_list(parts, first=2)
        with self.assertRaisesRegex(ValueError, "items 2 to 3"):
            _continuations([first, second])
        from build123d import Box, Compound, Pos

        many = []
        for k in range(18):
            block = Pos(12 * k, 0, 0) * Box(10, 10, 10 + k * 0.1)
            block.label = f"block_{k}"
            many.append(block)
        crowded = Sheet("A4", revisions=[("A", "", "ONE"), ("B", "", "TWO"), ("C", "", "THREE"), ("D", "", "FOUR")])
        with self.assertRaisesRegex(ValueError, "Draw items 1 to"):
            crowded.parts_list(parts_list(Compound(children=many)))

    def test_part_sheets_follow_the_list_and_keep_a_scale_the_author_sets(self) -> None:
        from build123d import Box, Compound, Pos

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import assembly_sheets, parts_list

        plate, block = Box(60, 40, 10), Pos(100, 0, 0) * Box(10, 10, 10)
        plate.label, block.label = "plate", "block"
        parts = parts_list(Compound(children=[plate, block]))
        sheets = assembly_sheets(parts, title="T")
        parts.set("plate", description="BASE PLATE", material="6061-T6")
        texts = {e.dxf.text for e in _render_sheet(sheets.part(1), index=2, count=3, label="t")
                 .modelspace().query("TEXT[layer=='TITLE']")}
        self.assertTrue({"BASE PLATE", "6061-T6"} <= texts, "the part's sheet reads the list when it renders")
        with self.assertRaisesRegex(ValueError, "merge before"):
            parts.merge(1, 2)
        sheet = sheets.part("block")
        sheet.scale = 2.0
        _render_sheet(sheet, index=3, count=3, label="t")
        self.assertEqual(sheet.scale, 2.0, "a scale the author set is theirs")
        plate_sheet = sheets.part("plate")
        plate_sheet.material = "AL 6061-T6"
        _render_sheet(plate_sheet, index=2, count=3, label="t")
        self.assertEqual(plate_sheet.material, "AL 6061-T6", "a material the author set on the sheet is theirs")


def _perforated():
    """A plate with three kinds of hole and a slot, for a hole table."""
    from build123d import Align, Box, Cylinder, Pos, SlotCenterToCenter, extrude

    up = (Align.CENTER, Align.CENTER, Align.MIN)
    plate = Box(160, 100, 8, align=up)
    for x in (-60, -30, 0, 30, 60):
        for y in (-35, 35):
            plate -= Pos(x, y, 0) * Cylinder(3, 8, align=up)
    for x in (-60, 60):
        plate -= Pos(x, 0, 0) * Cylinder(5, 8, align=up)
    plate -= Cylinder(12, 8, align=up)
    plate -= Pos(30, 0, 0) * extrude(SlotCenterToCenter(16, 8), 8)
    return plate


def _inclined():
    """A base plate with a tab leaning 30 degrees, a hole square through the tab;
    and a point on the tab's inner face."""
    from build123d import Align, Box, Cylinder, Location, Pos, Rot

    up = (Align.CENTER, Align.CENTER, Align.MIN)
    base = Box(80, 50, 8, align=up) - Pos(-25, 0, 0) * Cylinder(4, 8, align=up)
    tab = Box(8, 50, 40, align=(Align.MAX, Align.CENTER, Align.MIN)) - Pos(-4, 0, 25) * Rot(0, 90, 0) * Cylinder(5, 8)
    return (base + Location((40, 0, 0), (0, 1, 0), 30) * tab).clean(), (44.164, 0, 23.212)




def _clevis():
    """A clevis on a base plate: two ears with a pin bore, four mounting holes
    and two slots."""
    from build123d import Align, Axis, Box, Cylinder, Pos, Rot, SlotCenterToCenter, extrude, fillet

    up = (Align.CENTER, Align.CENTER, Align.MIN)
    part = fillet(Box(100, 64, 8, align=up).edges().filter_by(Axis.Z), 4)
    for sign in (-1, 1):
        y = sign * 16
        part += Pos(0, y, 8) * Box(30, 8, 28, align=up) + Pos(0, y, 36) * Rot(90, 0, 0) * Cylinder(15, 8)
    part -= Pos(0, 0, 36) * Rot(90, 0, 0) * Cylinder(6, 40)
    for x, y in ((-40, -24), (-40, 24), (40, -24), (40, 24)):
        part -= Pos(x, y, 0) * Cylinder(3.3, 8, align=up)
    for x in (-32, 32):
        part -= Pos(x, 0, 0) * Rot(0, 0, 90) * extrude(SlotCenterToCenter(18, 12), 8)
    return part.clean()


def _dimension_lines(doc) -> list:
    """Each DIMENSION's dimension line, as shapely lines: in its block, the lines
    that run the way the dimension measures (its extension lines run across)."""
    from shapely.geometry import LineString

    found = []
    for dim in doc.modelspace().query("DIMENSION"):
        horizontal = abs(math.sin(math.radians(dim.dxf.get("angle", 0.0)))) < 0.5
        for e in doc.blocks.get(dim.dxf.geometry):
            if e.dxftype() != "LINE":
                continue
            a, b = e.dxf.start, e.dxf.end
            if (abs(b.y - a.y) < 1e-6) == horizontal and math.hypot(b.x - a.x, b.y - a.y) > 1e-6:
                found.append(LineString([(a.x, a.y), (b.x, b.y)]))
    return found

def _bar():
    """A 600 mm bar, 20 mm square, with a turned spigot on its end and a cross hole
    near each end. Square, not round: hidden-line removal on a round bar's cross
    holes takes seconds a view, and the break does not care."""
    from build123d import Align, Box, Cylinder, Pos, Rot

    bar = Box(600, 20, 20, align=(Align.MIN, Align.CENTER, Align.CENTER))
    bar += Pos(600, 0, 0) * Rot(0, 90, 0) * Cylinder(6, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x in (20, 580):
        bar -= Pos(x, 0, 0) * Cylinder(3, 40)
    return bar


class ChosenSheetTests(unittest.TestCase):
    """Sheet(size=None, scale=None): the sheet picks its paper and scale."""

    def test_the_smallest_sheet_at_full_size_else_a3_reduced(self) -> None:
        from build123d import Box, Cylinder

        from cadgen.eng_drawing import Sheet

        for part, size, at_least in ((Cylinder(7, 11), "A4", 1.0), (Box(600, 40, 40), "A3", 0.0),
                                     (Box(1500, 800, 300), "A3", 0.0)):
            sheet = Sheet(None, None)
            sheet.three_views(part, iso=True)
            self.assertEqual(sheet._size(), size)
            self.assertGreaterEqual(sheet._scale(), at_least)
        fixed = Sheet("A3", None)
        fixed.three_views(Cylinder(7, 11), iso=True)
        self.assertEqual(fixed._scale(), 5.0, "a given size takes the largest scale that fits it")
        full = Sheet(None, 1.0)
        full.three_views(Box(600, 40, 40), iso=True)
        self.assertEqual(full._size(), "A1", "a given scale takes the smallest sheet that fits it")

    def test_a_hand_placed_view_needs_a_known_sheet(self) -> None:
        from cadgen.eng_drawing import Sheet

        with self.assertRaisesRegex(ValueError, "three_views"):
            Sheet(None, None).view(_plate(), "top", at=(100, 100))

    def test_running_out_of_paper_tries_a_larger_sheet_before_a_smaller_scale(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part, point = _inclined()
        sheet = Sheet(None, None)
        top, front, _right, _iso = sheet.three_views(part, iso=True)
        top.overall()
        top.holes()
        front.overall(width=False)
        sheet.auxiliary(front, point).holes()
        _render_sheet(sheet, index=1, count=1, label="chosen")
        self.assertEqual((sheet._size(), sheet._scale()), ("A3", 1.0), "A4 has no room left for VIEW C at 1:1")

    def test_a_chosen_size_grows_for_paper_a_fixed_scale_needs(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part, point = _inclined()
        sheet = Sheet(None, 1.0)
        top, front, _right, _iso = sheet.three_views(part, iso=True)
        top.overall()
        top.holes()
        front.overall(width=False)
        sheet.auxiliary(front, point).holes()
        _render_sheet(sheet, index=1, count=1, label="size")
        self.assertEqual((sheet._size(), sheet._scale()), ("A3", 1.0))

    def test_two_arrangements_on_a_chosen_sheet_settle_rather_than_loop(self) -> None:
        from build123d import Box

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet(None, None)
        sheet.three_views(Box(20, 20, 20))
        sheet.three_views(Box(300, 200, 100))
        try:
            _render_sheet(sheet, index=1, count=1, label="two")
        except ValueError as refused:
            self.assertIn("off the frame", str(refused))

    def test_a_value_the_author_sets_is_kept_even_when_it_matches_the_choice(self) -> None:
        from build123d import Cylinder

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet(None, None)
        sheet.three_views(Cylinder(7, 11), iso=True)
        sheet.size, sheet.scale = "A3", 1.0
        _render_sheet(sheet, index=1, count=1, label="pinned")
        self.assertEqual((sheet._size(), sheet._scale()), ("A3", 1.0))




class WhiteSpaceTests(unittest.TestCase):
    def test_an_enlarged_sheet_out_of_paper_draws_smaller_before_taking_a_bigger_sheet(self) -> None:
        """A small part drawn enlarged that runs out of paper is drawn at the next
        scale down on its own sheet, down to 1:1, not at the same scale on a sheet
        twice the size that it then leaves mostly empty."""
        from unittest import mock

        from build123d import Align, Box, Cylinder, Pos

        import cadgen._internal.drawing_render as render
        from cadgen._internal.drawing_sheet import _OffFrame
        from cadgen.eng_drawing import Sheet

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        block = Box(24, 16, 6, align=up) - Pos(-7, 0, 0) * Cylinder(2, 6, align=up) - Pos(7, 0, 0) * Cylinder(2, 6, align=up)
        sheet = Sheet(size=None, scale=None)
        top, _front, _right = sheet.three_views(block)
        top.hole_table()
        real = render._place_hole_tables

        def tables(sheet, *args):
            if sheet._scale() > 1:
                raise _OffFrame("no room for the table", None)
            return real(sheet, *args)

        with mock.patch.object(render, "_place_hole_tables", tables):
            render._render_sheet(sheet, index=1, count=1, label="small")
        self.assertEqual((sheet._size(), sheet._scale()), ("A4", 1.0))


class CrossingTests(unittest.TestCase):
    """Alex: dimension lines crossing other dimension lines are not acceptable."""

    def test_no_leader_or_dimension_line_crosses_a_dimension_line(self) -> None:
        from shapely.geometry import LineString

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A2", 2.0)
        top, front, right = sheet.three_views(_clevis())
        top.overall()
        top.radius((-46, 28, 8), size=4, angle=135)
        front.overall(width=False)
        front.holes()
        front.dim((-50, -32, 0), (-50, -32, 8))
        front.dim((15, -24, 0), (15, -24, 36))
        front.radius((0, -24, 36), size=15, angle=135)
        doc = _render_sheet(sheet, index=1, count=1, label="crossing", warnings=[])
        lines = _dimension_lines(doc)
        leaders = [LineString([(v[0], v[1]) for v in e.vertices]) for e in doc.modelspace().query("LEADER")]
        crossing = [(i, j) for i, a in enumerate(lines) for j, b in enumerate(lines) if i < j and a.crosses(b)]
        self.assertFalse(crossing, "two dimension lines cross")
        crossing = [(i, j) for i, a in enumerate(leaders) for j, b in enumerate(lines) if a.crosses(b)]
        self.assertFalse(crossing, "a leader crosses a dimension line")
        crossing = [(i, j) for i, a in enumerate(leaders) for j, b in enumerate(leaders) if i < j and a.crosses(b)]
        self.assertFalse(crossing, "two leaders cross")


class DimensionKindTests(unittest.TestCase):
    """Toleranced, basic and reference dimensions each mean what Y14.5 says."""

    def _block_sheet(self):
        from build123d import Align, Box

        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        top, front, right = sheet.three_views(Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)))
        return sheet, top, front

    def test_a_reference_dimension_prints_in_parentheses_and_states_nothing(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated

        sheet, top, front = self._block_sheet()
        top.dim((-20, -15, 10), (20, -15, 10), reference=True)
        facts = _facts()
        doc = _render_sheet(sheet, index=1, count=1, label="ref", facts=facts)
        self.assertIn("(40)", _dim_texts(doc))
        self.assertTrue(any("overall size along X (40)" in line for line in _unstated(facts)),
                        "a reference dimension is information, not the requirement")

    def test_a_basic_dimensions_value_is_boxed(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        sheet, top, front = self._block_sheet()
        top.dim((-20, -15, 10), (20, -15, 10), basic=True)
        doc = _render_sheet(sheet, index=1, count=1, label="basic", warnings=[])
        (dim,) = doc.modelspace().query("DIMENSION")
        self.assertLess(dim.override().get("dimgap"), 0, "the DXF says basic too")
        block = list(doc.blocks.get(dim.dxf.geometry))
        (value,) = [e for e in block if e.dxftype() == "MTEXT"]
        frames = [e for e in block if e.dxftype() == "LWPOLYLINE" and e.closed]
        self.assertEqual(len(frames), 1)
        xs, ys = zip(*[(p[0], p[1]) for p in frames[0].get_points()])
        self.assertTrue(min(xs) < value.dxf.insert.x < max(xs) and min(ys) < value.dxf.insert.y < max(ys))

    def test_limits_print_the_two_limits_the_part_lies_between(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        sheet, top, front = self._block_sheet()
        top.dim((-20, -15, 10), (20, -15, 10), limits=(39.98, 40.02))
        doc = _render_sheet(sheet, index=1, count=1, label="limits")
        (dim,) = doc.modelspace().query("DIMENSION")
        self.assertEqual(dim.override().get("dimlim"), 1)
        text = " ".join(_dim_texts(doc))
        self.assertIn("40.02", text)
        self.assertIn("39.98", text)
        sheet, top, front = self._block_sheet()
        top.dim((-20, -15, 10), (20, -15, 10), limits=(40.1, 40.2))
        with self.assertRaisesRegex(ValueError, "measures 40"):
            _render_sheet(sheet, index=1, count=1, label="outside")

    def test_kinds_that_cannot_combine_are_refused(self) -> None:
        sheet, top, front = self._block_sheet()
        a, b = (-20, -15, 10), (20, -15, 10)
        for kinds, words in (({"basic": True, "tol": 0.1}, "basic"), ({"reference": True, "fit": "H7"}, "reference"),
                             ({"basic": True, "reference": True}, "basic"), ({"limits": (39, 41), "tol": 0.1}, "limits"),
                             ({"limits": (41, 39)}, "limits")):
            with self.assertRaisesRegex(ValueError, words):
                top.dim(a, b, **kinds)
        with self.assertRaisesRegex(ValueError, "basic"):
            top.diameter((0, 0, 10), basic=True, reference=True)

    def test_round_callouts_and_overall_sizes_take_the_kinds_too(self) -> None:
        from build123d import Align, Box, Cylinder

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        up = (Align.CENTER, Align.CENTER, Align.MIN)
        sheet = Sheet("A3", 1.0)
        top, front, right = sheet.three_views(Box(60, 40, 10, align=up) - Cylinder(8, 10, align=up))
        top.diameter((0, 0, 10), reference=True)
        front.overall(reference=True)
        top.angle((-30, -20, 10), (30, -20, 10), (-30, 20, 10), basic=True)
        doc = _render_sheet(sheet, index=1, count=1, label="kinds", warnings=[])
        self.assertIn("(%%c16)", _callouts(doc))
        self.assertTrue({"(60)", "(10)"} <= set(_dim_texts(doc)), _dim_texts(doc))
        (angle,) = [d for d in doc.modelspace().query("DIMENSION") if d.dxf.dimtype & 0x0F == 5]  # 3-point angular
        self.assertTrue([e for e in doc.blocks.get(angle.dxf.geometry) if e.dxftype() == "LWPOLYLINE" and e.closed],
                        "a basic angle is boxed too")

    @unittest.expectedFailure  # needs the GD&T frames of the next change
    def test_a_basic_dimension_without_a_frame_is_reported(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet

        sheet, top, front = self._block_sheet()
        top.dim((-20, -15, 10), (20, -15, 10), basic=True)
        warnings: list = []
        _render_sheet(sheet, index=1, count=1, label="lonely", warnings=warnings)
        self.assertTrue(any("basic dimension" in w for w in warnings), warnings)

class HoleTableTests(unittest.TestCase):
    def test_a_hole_table_tags_each_hole_and_states_where_and_what(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A2", 1.0)
        top, _front, _right = sheet.three_views(_perforated())
        top.hole_table()
        facts = _facts()
        doc = _render_sheet(sheet, index=1, count=1, label="table", facts=facts)
        texts = [e.dxf.text for e in doc.modelspace().query("TEXT")]
        for tag in ("A1", "B1", "B2", "C1", "C10", "D1"):
            self.assertEqual(texts.count(tag), 2, f"{tag} tags its hole and heads its row")
        cells = {e.dxf.text for e in doc.modelspace().query("TEXT[layer=='NOTES']")}
        self.assertTrue({"24 THRU", "10 THRU", "6 THRU", "8 × 24 SLOT THRU"} <= cells, cells)
        # Positions from the lower-left corner: the bore is at the plate's middle.
        self.assertTrue({"80", "50", "140"} <= set(texts))
        from cadgen._internal.drawing_report import _unstated

        self.assertFalse([line for line in _unstated(facts) if "called out" in line], "the table states each hole")

    def test_the_tags_and_the_origin_stand_clear_of_the_line_work(self) -> None:
        import re

        from ezdxf import path
        from shapely.geometry import LineString, box

        from cadgen._internal.drawing_base import _text_box
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A2", 1.0)
        top, _front, _right = sheet.three_views(_perforated())
        top.hole_table()
        msp = _render_sheet(sheet, index=1, count=1, label="tags").modelspace()
        lines = [LineString([(v.x, v.y) for v in path.make_path(e).flattening(0.05)])
                 for e in msp.query("LINE ARC CIRCLE LWPOLYLINE SPLINE ELLIPSE[layer=='VISIBLE' | layer=='CENTER']")]
        tags = [e for e in msp.query("TEXT[layer=='DIM']") if re.fullmatch(r"[A-Z]\d+|X|Y|0,0", e.dxf.text)]
        self.assertEqual(len(tags), 17)  # A1, B1-B2, C1-C10, D1, and the origin's X, Y and 0,0
        for tag in tags:
            align, at, _end = tag.get_placement()
            ink = box(*_text_box(tag.dxf.text, at.x, at.y, tag.dxf.height, align))
            self.assertFalse([line for line in lines if line.intersects(ink)], f"{tag.dxf.text} is printed on line work")

    def test_a_hole_table_and_callouts_do_not_share_a_view(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A2", 1.0)
        top, front, _right = sheet.three_views(_perforated())
        top.hole_table()
        top.holes()
        with self.assertRaisesRegex(ValueError, "both tabulates"):
            _render_sheet(sheet, index=1, count=1, label="both")
        sheet = Sheet("A2", 1.0)
        _top, front, _right = sheet.three_views(_perforated())
        front.hole_table()
        with self.assertRaisesRegex(ValueError, "looks down no hole"):
            _render_sheet(sheet, index=1, count=1, label="none")

    def test_a_hole_table_on_a_broken_view_measures_the_part_and_leaves_out_the_break(self) -> None:
        from build123d import Cylinder, Pos

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A0", 1.0)  # no tag reads A0, so the size cell cannot be counted as one
        top, front, _right = sheet.three_views(_bar() - Pos(300, 0, 0) * Cylinder(3, 40))
        front.broken((100, 0, 0), (500, 0, 0))
        top.hole_table()
        texts = [e.dxf.text for e in _render_sheet(sheet, index=1, count=1, label="broken").modelspace().query("TEXT")]
        self.assertIn("580", texts, "X is measured on the whole bar, not on the shortened drawing")
        self.assertEqual((texts.count("A1"), texts.count("A2"), texts.count("A3")), (2, 2, 0),
                         "the hole at X = 300 is in the break, so it is neither tagged nor listed")

    def test_a_hole_table_placed_by_hand_must_be_on_the_paper(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A2", 1.0)
        top, _front, _right = sheet.three_views(_perforated())
        top.hole_table(at=(800, 900))
        with self.assertRaisesRegex(ValueError, "runs off"):
            _render_sheet(sheet, index=1, count=1, label="off")
        sheet = Sheet("A2", 1.0, revisions=[("A", "2026-10-01", "FIRST ISSUE")])
        top, _front, _right = sheet.three_views(_perforated())
        top.hole_table(at=(480, 405))  # under the revision table, top right
        with self.assertRaisesRegex(ValueError, "revision table"):
            _render_sheet(sheet, index=1, count=1, label="revisions")


class EdgeNoteTests(unittest.TestCase):
    """Fillets, rounds and chamfers: read off the part, stated by a general note
    only where the note is true."""

    def _block(self, *, chamfer_bottom: bool):
        from build123d import Align, Axis, Box, chamfer, fillet

        block = Box(60, 40, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
        block = fillet(block.edges().filter_by(Axis.Z), 5)
        block = chamfer(block.edges().group_by(Axis.Z)[-1], 1)
        return chamfer(block.edges().group_by(Axis.Z)[0], 1) if chamfer_bottom else block

    def test_a_general_note_is_written_only_when_no_edge_of_its_kind_is_left_sharp(self) -> None:
        from build123d import Align, Axis, Box, Pos, fillet

        from cadgen.eng_drawing import geometry_notes

        self.assertEqual(geometry_notes(self._block(chamfer_bottom=True)),
                         ["CHAMFERS 1 × 45° UNLESS OTHERWISE SPECIFIED."], "every outside edge is broken")
        self.assertEqual(geometry_notes(self._block(chamfer_bottom=False)), [],
                         "the bottom edges are sharp, so no note may govern the outside edges")
        up = (Align.CENTER, Align.CENTER, Align.MIN)
        pocket = Box(80, 50, 15, align=up) - Pos(0, 0, 5) * Box(40, 20, 10, align=up)
        inside = [e for e in pocket.edges() if abs(e.center().X) <= 20 + 1e-6 and abs(e.center().Y) <= 10 + 1e-6
                  and 5 - 1e-6 <= e.center().Z < 15 - 1e-6]
        self.assertEqual(geometry_notes(fillet(inside, 3)), ["FILLETS R3 UNLESS OTHERWISE SPECIFIED."])
        walls_only = fillet(pocket.edges().filter_by(Axis.Z).group_by(lambda e: abs(e.center().X))[0], 3)
        self.assertEqual(geometry_notes(walls_only), [], "the pocket's floor corners are sharp")

    def test_unstated_blends_and_chamfers_are_reported_until_stated(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen._internal.drawing_report import _unstated
        from cadgen.eng_drawing import Sheet, geometry_notes

        part = self._block(chamfer_bottom=True)
        for notes, corner_radius, expected in (((), False, 2), (geometry_notes(part), False, 1),
                                               (geometry_notes(part), True, 0)):
            sheet = Sheet("A3", notes=list(notes))
            top, front, _right = sheet.three_views(part)
            top.overall()
            front.overall(width=False)
            if corner_radius:
                top.radius((25, 15, 20), size=5)
            facts = _facts()
            _render_sheet(sheet, index=1, count=1, label="edges", facts=facts)
            lines = [line for line in _unstated(facts) if "round" in line or "chamfer" in line]
            self.assertEqual(len(lines), expected, lines)
        sheet = Sheet("A3", notes=["CHAMFERS 0.1 × 45° UNLESS OTHERWISE SPECIFIED."])
        sheet.three_views(part)
        facts = _facts()
        _render_sheet(sheet, index=1, count=1, label="edges", facts=facts)
        self.assertTrue(any("chamfers 1 × 45°" in line for line in _unstated(facts)), "0.1 × 45° is not 1 × 45°")


class AuxiliaryViewTests(unittest.TestCase):
    def test_an_auxiliary_view_shows_an_inclined_face_true_and_calls_out_its_hole(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part, point = _inclined()
        sheet = Sheet("A3", 1.0)
        _top, front, _right = sheet.three_views(part)
        view = sheet.auxiliary(front, point)
        view.holes()
        doc = _render_sheet(sheet, index=1, count=1, label="aux")
        self.assertIn("%%c10 THRU", _callouts(doc))
        notes = [e.dxf.text for e in doc.modelspace().query("TEXT[layer=='NOTES']")]
        self.assertIn("VIEW C", notes)
        self.assertIn("C", notes, "the parent view's arrow carries the letter")

    def test_an_auxiliary_view_needs_an_inclined_flat_face(self) -> None:
        from cadgen.eng_drawing import Sheet

        part, point = _inclined()
        sheet = Sheet("A3", 1.0)
        top, front, _right = sheet.three_views(part)
        with self.assertRaisesRegex(ValueError, "faces the top view"):
            sheet.auxiliary(front, (0, 0, 8))
        with self.assertRaisesRegex(ValueError, "no flat face"):
            sheet.auxiliary(front, (0, 0, 100))
        view = sheet.auxiliary(front, point)
        with self.assertRaisesRegex(ValueError, "drawn whole"):
            view.section("A")

    def test_an_auxiliary_view_projects_from_a_view_that_sees_the_face_edge_on(self) -> None:
        from build123d import Box, Plane

        from cadgen.eng_drawing import Sheet

        corner = Box(40, 40, 40).split(Plane((10, -10, 10), z_dir=(1, -1, 1)))
        sheet = Sheet("A3", 1.0)
        _top, front, _right = sheet.three_views(corner)
        with self.assertRaisesRegex(ValueError, "not seen edge-on"):
            sheet.auxiliary(front, (10, -10, 10))

    def test_an_auxiliary_views_label_states_a_scale_unlike_the_sheets(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        part, point = _inclined()
        sheet = Sheet("A3", 0.5)
        _top, front, _right = sheet.three_views(part)
        front.scale = 1.0
        view = sheet.auxiliary(front, point)
        _render_sheet(sheet, index=1, count=1, label="label")
        self.assertEqual(view.label, "VIEW C (1:1)")
        view.label = "VIEW C (TAB)"
        _render_sheet(sheet, index=1, count=1, label="label")
        self.assertEqual(view.label, "VIEW C (TAB)", "a label the author set is theirs")

    def test_a_hole_opening_away_from_an_auxiliary_view_names_where_to_call_it_out(self) -> None:
        from build123d import Align, Box, Cylinder, Location, Pos, Rot

        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        # The inclined tab with a blind hole drilled from its outer face, which
        # VIEW C, looking at the inner face, sees from behind.
        up = (Align.CENTER, Align.CENTER, Align.MIN)
        tab = Box(8, 50, 40, align=(Align.MAX, Align.CENTER, Align.MIN)) \
            - Pos(-2, 0, 25) * Rot(0, 90, 0) * Cylinder(3, 4)
        part = (Box(80, 50, 8, align=up) + Location((40, 0, 0), (0, 1, 0), 30) * tab).clean()
        sheet = Sheet("A3", 1.0)
        _top, front, _right = sheet.three_views(part)
        view = sheet.auxiliary(front, _inclined()[1])
        hole = Location((40, 0, 0), (0, 1, 0), 30) * Pos(-2, 0, 25)
        view.hole((hole.position.X, hole.position.Y, hole.position.Z))
        with self.assertRaisesRegex(ValueError, "opens on the far side .* a view that looks into it"):
            _render_sheet(sheet, index=1, count=1, label="far")


class BrokenViewTests(unittest.TestCase):
    def test_a_broken_view_draws_both_ends_and_states_true_lengths(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        top, front, _right = sheet.three_views(_bar())
        front.broken((100, 0, 0), (500, 0, 0))
        front.overall()
        front.dim((0, 0, -10), (580, 0, -10))
        doc = _render_sheet(sheet, index=1, count=1, label="broken")
        values = _dim_texts(doc)
        self.assertIn("630", values)
        self.assertIn("580", values)
        zigzags = [e for e in doc.modelspace().query("LWPOLYLINE[layer=='NOTES']") if len(e) == 6]
        self.assertEqual(len(zigzags), 4, "a break line across each end, in both views")

    def test_a_break_where_the_part_changes_is_reported(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        _top, front, _right = sheet.three_views(_bar())
        front.broken((10, 0, 0), (500, 0, 0))
        warnings: list = []
        _render_sheet(sheet, index=1, count=1, label="hides", warnings=warnings)
        self.assertTrue(any("hides some of the part" in w for w in warnings), warnings)

    def test_a_break_needs_a_length_the_view_shows(self) -> None:
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        top, front, right, iso = sheet.three_views(_bar(), iso=True)
        with self.assertRaisesRegex(ValueError, "looks along X"):
            right.broken((100, 0, 0), (500, 0, 0))
        with self.assertRaisesRegex(ValueError, "isometric"):
            iso.broken((100, 0, 0), (500, 0, 0))
        with self.assertRaisesRegex(ValueError, "differ along X and Z"):
            front.broken((100, 0, -10), (500, 0, 10))

    def test_a_section_and_a_break_do_not_share_a_view(self) -> None:
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        top, front, _right = sheet.three_views(_bar())
        front.section("A")
        with self.assertRaisesRegex(ValueError, "is a section"):
            top.broken((100, 0, 0), (500, 0, 0))
        sheet = Sheet("A3", 1.0)
        top, front, _right = sheet.three_views(_bar())
        top.broken((100, 0, 0), (500, 0, 0))
        with self.assertRaisesRegex(ValueError, "broken"):
            front.section("A")

    def test_a_dimension_into_the_break_is_reported(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        _top, front, _right = sheet.three_views(_bar())
        front.broken((100, 0, 0), (500, 0, 0))
        front.dim((0, 0, 10), (300, 0, 10))
        warnings: list = []
        _render_sheet(sheet, index=1, count=1, label="into", warnings=warnings)
        self.assertTrue(any("inside the break" in w for w in warnings), warnings)



class ViewChoiceTests(unittest.TestCase):
    """The views a part needs, and no repeat of one it already has."""

    def test_three_views_draws_only_the_views_asked_for(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        sheet = Sheet("A3", 1.0)
        front, right = sheet.three_views(_shaft(), views=("front", "right"))
        self.assertEqual([v.name for v in sheet.views], ["front", "right"])
        self.assertEqual((front.name, right.name), ("front", "right"))
        labels = [e.dxf.text for e in _render_sheet(sheet, index=1, count=1, label="v").modelspace()
                  .query("TEXT[layer=='NOTES']")]
        self.assertNotIn("TOP", labels)
        self.assertIn("FRONT", labels)

    def test_a_bad_choice_of_views_is_refused(self) -> None:
        from cadgen.eng_drawing import Sheet

        for views in ((), ("front", "front"), ("iso",), ("side",)):
            with self.assertRaisesRegex(ValueError, "views"):
                Sheet("A3", 1.0).three_views(_shaft(), views=views)

    def test_two_views_of_the_same_picture_are_reported(self) -> None:
        from cadgen._internal.drawing_render import _render_sheet
        from cadgen.eng_drawing import Sheet

        warnings: list = []
        sheet = Sheet("A3", 1.0)
        sheet.three_views(_shaft())  # turned about X: the top and front views draw the same lines
        _render_sheet(sheet, index=1, count=1, label="same", warnings=warnings)
        self.assertTrue(any("top and front views draw the same picture" in w for w in warnings), warnings)
        warnings = []
        sheet = Sheet("A2", 1.0)
        sheet.three_views(_perforated())  # a plate: no two of its views alike
        _render_sheet(sheet, index=1, count=1, label="unlike", warnings=warnings)
        self.assertFalse([w for w in warnings if "same picture" in w], warnings)

def _points(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        return [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    if kind == "CIRCLE":
        return [(entity.dxf.center.x, entity.dxf.center.y), (entity.dxf.radius, entity.dxf.radius)]
    if kind == "ARC":
        return [(entity.dxf.center.x, entity.dxf.center.y), (entity.dxf.radius, entity.dxf.radius),
                (entity.dxf.start_angle, entity.dxf.end_angle)]
    return list(entity.get_points("xy"))


if __name__ == "__main__":
    unittest.main()
