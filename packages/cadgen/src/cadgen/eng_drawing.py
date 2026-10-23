"""Engineering drawings: ``@eng_drawing``, :class:`Sheet` and :class:`View`.

An engineering drawing is a DOCUMENT derived from a part: orthographic and
section views projected from the part's geometry, dimensions that reference
points ON that geometry, hole callouts whose sizes, depths and counts are read
off its faces, centre lines on its turned features, and an ISO sheet with a
zoned frame and a title block. Because every view and every value is computed
from the shape at run time, the drawing follows the part: change the model,
rerun the drawing script, and the views, hidden lines and measured values move
with it. Nothing on the sheet is drawn by hand.

The output is one PDF. A shop receives a PDF, every operating system opens and
marks one up, and nothing here pairs the document with a second file. ezdxf is
the in-memory drawing engine -- real ``DIMENSION`` entities so the value is
measured and the arrowheads and witness lines are the dimension style's, ``TEXT``
for notes and the title block, a LAYER table whose linetypes say which lines are
hidden or centre lines -- and no ``.dxf`` reaches disk. ``@dxf`` remains the
decorator for a DXF: a cut layout is a toolpath, and a drawing is not.

Usage::

    import cadgen
    from cadgen.eng_drawing import eng_drawing, Sheet
    from pathlib import Path

    @eng_drawing(out="../PDF/bracket_drawing.pdf")
    def bracket_drawing():
        part = cadgen.read_step(Path(__file__).parent / "../STEP/bracket.step")
        sheet = Sheet("A3", title="BRACKET", part_number="BRK-001", revision="A")
        top, front, right, iso = sheet.three_views(part, iso=True)
        front.section("A")                               # the front view, cut
        top.overall()                                    # width and height
        top.dim((-35, 25, 0), (35, 25, 0))               # model coordinates
        top.holes()                                      # sizes read off the part
        return sheet                                     # or [sheet1, sheet2]

    if __name__ == "__main__":
        bracket_drawing()

Running the script writes one PDF at ``out`` with a page per sheet, and prints
what the sheet noticed (a dimension measuring blank paper, crowded annotation)
and what the drawing leaves unstated (a hole not called out, a size not
dimensioned). There is no default location: ``out`` is the path the caller
passes. A live build123d shape works in place of ``read_step``.

Bytes are a function of the content: the PDF carries no creation date, so an
unchanged drawing rebuilds to an identical file.

This module keeps ``@eng_drawing`` outside the build store on purpose: a drawing
is a document over a part, not a model with a closure to hash. Import
discipline: nothing here pulls in ezdxf or the CAD kernel at module scope.
"""

from __future__ import annotations

import functools
import math
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from cadgen._internal.drawing_assembly import Item, PartsList, parts_list

__all__ = ["eng_drawing", "Sheet", "View", "SHEET_SIZES", "parts_list", "PartsList", "Item", "assembly_sheets",
           "AssemblySheets", "geometry_notes"]

#: ISO 216 sheet sizes, landscape, in millimetres.
SHEET_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}

#: Standard view names -> (view direction: where the viewer STANDS relative to the
#: part, up vector). Third-angle projection places each view on the side it looks
#: from; the sheet does not enforce placement, the author picks ``at=``.
VIEW_DIRECTIONS = {
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    # Looking up from below, the sheet's up is the model's -Y: the bottom view is the
    # top view mirrored about the horizontal, which is what third angle draws. With
    # up=+Y it comes out rotated 180 degrees (+X to the left), so it would not line up
    # with the front view above it.
    "bottom": ((0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "iso": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
}

#: Layers a sheet writes, with ACI colour and linetype. ``ink="mono"`` collapses
#: the colours to the default ink; the linetypes are the drawing's meaning and stay.
#: Every linetype here must be one ``ezdxf.new(setup=True)` defines, or ezdxf draws
#: the layer continuous and its audit reports the substitution: there is no HIDDEN
#: in that table, DASHED is the ISO 128 dashed line it does define.
_LAYERS = {
    "SHEET": (7, "CONTINUOUS", 0.35),
    "TITLE": (7, "CONTINUOUS", 0.25),
    "VISIBLE": (7, "CONTINUOUS", 0.5),
    "HIDDEN": (8, "DASHED", 0.25),
    "CENTER": (4, "CENTER", 0.18),
    "DIM": (1, "CONTINUOUS", 0.18),
    "NOTES": (3, "CONTINUOUS", 0.25),
    # A section's cut faces: 45-degree lines, thin, as ISO 128-50 hatches them.
    "HATCH": (8, "CONTINUOUS", 0.18),
}
#: Letters a section may be named by: ISO 128-40 leaves out I, O and Q, which read
#: as 1, 0 and O on a print.
_SECTION_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
#: ANSI31 at this scale is 45-degree lines 3.2 mm apart: legible on A4, not grey on A0.
_HATCH_SCALE = 1.0

#: Projection conventions the title block may name. The two differ only in WHERE a
#: view is placed: third angle puts the view from above above the front view and the
#: view from the right to its right; first angle puts each on the opposite side. The
#: pictures are the same, so only :meth:`Sheet.three_views` reads this.
PROJECTIONS = ("THIRD ANGLE", "FIRST ANGLE")

_MARGIN = 10.0
_TITLE_W, _TITLE_H = 180.0, 40.0
#: Text height the notes block is drawn at, and the left inset of its first glyph.
#: The guard that refuses an over-wide note measures at these, because a guard
#: that measures a different string at a different height than the draw either
#: refuses a note that fits or passes one that does not.
_NOTE_HEIGHT = 2.5
_NOTE_INSET = 3.0
#: One row of dimensions: the line's distance from the last, with room for its text.
_DIM_ROW = 12.0
#: The smallest text a print stays legible at. Below it, text is cut, not shrunk.
_MIN_TEXT_MM = 1.6
#: Drawing scales a shop expects to read, largest first. An over-size part is
#: refused with the first of these that fits rather than an arbitrary ratio.
_STANDARD_SCALES = (50.0, 20.0, 10.0, 5.0, 2.0, 1.0, 1 / 2, 1 / 2.5, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100,
                    1 / 200, 1 / 500, 1 / 1000)
#: The only unit a sheet prints. Every value on it is measured off the model, whose
#: unit is the millimetre; a title block reading IN over millimetre values is a
#: drawing that is wrong by 25.4 everywhere and looks right.
UNITS = ("mm",)


@dataclass
class _Dim:
    kind: str
    p1: tuple[float, float, float]
    p2: tuple[float, float, float] | None
    #: Sheet millimetres from the dimensioned points, or None for the next free row.
    offset: float | None
    text: str | None
    orientation: str | None
    radius: float = 0.0
    angle: float = 45.0
    tol: Any = None
    fit: str | None = None
    hole: dict | None = None
    #: Filled in at render time, on a copy: the hole a callout states, the side and
    #: row an unplaced dimension was given, and the call's index for messages.
    feature: Any = None
    side: str | None = None
    row: int = 0
    index: int = 0
    #: The holes or slots a callout states, each one: its ``4×`` covers four.
    covers: tuple = ()


@dataclass
class View:
    """One orthographic view of a shape on a sheet.

    Points handed to :meth:`dim`, :meth:`diameter` and :meth:`note` are MODEL
    coordinates; the view projects them exactly as it projected the geometry, so
    a dimension between two model points measures what the sheet shows.
    """

    sheet: "Sheet"
    shape: Any
    name: str
    at: tuple[float, float]
    label: str | None = None
    hidden: bool = True
    centre_marks: bool = True
    #: This view's own drawing scale; None means the sheet's. A pictorial view is
    #: often drawn smaller so it fits the free corner.
    scale: float | None = None
    _dims: list[_Dim] = field(default_factory=list)
    #: Which overall sizes ``overall()`` asked for: {"width", "height"}, or empty.
    _overall: frozenset = frozenset()
    #: ``(letter, model point or None)`` when :meth:`section` made this a section.
    _section: tuple | None = None
    #: ``(label, scale)`` the arrangement gave an isometric, so the render knows
    #: whether the author has since set their own and leaves it alone.
    _auto: tuple | None = None
    #: ``(parent view, model centre, model radius, letter)`` when :meth:`Sheet.detail`
    #: made this a detail view; its ``at`` is None until the render places it.
    _detail: tuple | None = None
    #: ``(bounding-box size, gap, iso extent or False)`` when :meth:`Sheet.three_views`
    #: placed this view, one tuple shared by the arrangement's views: the render
    #: lays them out again from it, and the off-frame guard does at each candidate
    #: scale. None for a hand-placed ``at=``, which does not move.
    _arranged: tuple | None = None
    #: The parts lists :meth:`balloons` keys this view to.
    _balloons: list = field(default_factory=list)
    #: ``(origin model point or None, table corner or None)`` when
    #: :meth:`hole_table` tabulates this view's holes.
    _table: tuple | None = None
    #: ``(where the viewer stands, up)`` for a view whose direction is its own
    #: rather than its name's: an auxiliary view.
    _direction: tuple | None = None
    #: ``(model axis 0-2, low, high)`` when :meth:`broken` takes the stretch
    #: between low and high along that axis out of the view.
    _break: tuple | None = None
    #: ``(parent view, model point, letter, placed by the sheet, outline points or
    #: None)`` when :meth:`Sheet.auxiliary` made this an auxiliary view; the
    #: outline is the face's, for a partial view.
    _aux: tuple | None = None

    def dim(self, p1, p2, *, offset: float | None = None, text: str | None = None, orientation: str | None = None,
            tol: float | tuple[float, float] | None = None, fit: str | None = None) -> "View":
        """A linear dimension between two model points. ``orientation`` is ``"h"``,
        ``"v"`` or None (whichever the projected pair spans more); ``offset`` is
        the dimension line's distance from the farther point, in sheet mm, and its
        sign picks the side. Left unset, the dimension takes the next free row on
        its side, so defaults never stack on each other or on :meth:`overall`.
        ``tol=0.1`` states ±0.1; ``tol=(0.05, 0.02)`` states +0.05/-0.02
        deviations; ``fit="H7"`` appends an ISO fit class."""
        if orientation not in (None, "h", "v"):
            raise ValueError(f"orientation must be 'h', 'v' or None, got {orientation!r}")
        self._dims.append(_Dim("linear", _p3(p1), _p3(p2), _offset(offset), text, orientation,
                               tol=_tol(tol), fit=fit))
        return self

    def hole(self, center, diameter: float | None = None, *, depth: float | None = None, thru: bool | None = None,
             cbore: tuple[float, float] | None = None, csk: tuple[float, float] | None = None,
             thread: str | None = None, count: int | None = None, angle: float = 45.0,
             tol: float | tuple[float, float] | None = None, fit: str | None = None,
             label: str | None = None) -> "View":
        """A hole callout in the standard symbols -- ``4× ⌀6.6 THRU ⌴ ⌀11 ↧6.5`` --
        read off the part. ``center`` is any model point on the hole's axis (its
        mouth is the natural one), in a view that looks down that axis.

        The diameter, THRU or depth, counterbore, countersink and the ``4×``
        count all come from the geometry. Anything given here is checked against
        it and a disagreement is refused: a callout that says ⌀6 over a ⌀6.6
        bore is the one error a shop machines faithfully. ``thread`` replaces
        the diameter with the thread spec (``"M6x1 - 6H"``), which the B-rep
        cannot carry; ``tol``/``fit`` qualify the diameter the way :meth:`dim`
        does; ``label`` is appended (``"WHEEL"``). ``angle`` is where the leader
        leaves the circle, degrees from horizontal."""
        given = {"diameter": _positive("diameter", diameter, allow_none=True),
                 "depth": _positive("depth", depth, allow_none=True),
                 "thru": None if thru is None else bool(thru), "cbore": _pair("cbore", cbore),
                 "csk": _pair("csk", csk),
                 "count": None if count is None else _positive("count", count, integer=True)}
        if thru and depth is not None:
            raise ValueError("a hole is either THRU or has a depth, not both")
        spec = {"given": given, "thread": None if thread is None else str(thread),
                "label": None if label is None else str(label)}
        self._dims.append(_Dim("hole", _p3(center), None, 0.0, None, None, radius=0.0,
                               angle=float(angle), tol=_tol(tol), fit=fit, hole=spec))
        return self

    def slot(self, center, *, width: float | None = None, length: float | None = None, thru: bool | None = None,
             depth: float | None = None, count: int | None = None, angle: float = 45.0,
             label: str | None = None) -> "View":
        """A slot callout -- ``2× 8 × 30 SLOT THRU`` -- read off the part, in a view
        that looks down the slot. ``center`` is the slot's centre or the centre of
        either rounded end. Width, length (end to end), THRU or depth and the count
        come from the geometry; any given here is checked and a contradiction is
        refused. ``label`` is appended."""
        given = {"width": _positive("width", width, allow_none=True),
                 "length": _positive("length", length, allow_none=True),
                 "thru": None if thru is None else bool(thru), "depth": _positive("depth", depth, allow_none=True),
                 "count": None if count is None else _positive("count", count, integer=True)}
        if thru and depth is not None:
            raise ValueError("a slot is either THRU or has a depth, not both")
        self._dims.append(_Dim("slot", _p3(center), None, 0.0, None, None, angle=float(angle),
                               hole={"given": given, "label": None if label is None else str(label)}))
        return self

    def holes(self, *, angle: float = 45.0) -> "View":
        """Call out every hole and slot this view looks down, one callout per kind
        (``4× ⌀5.5 THRU``, ``⌀28 THRU``, ``8 × 30 SLOT THRU``), each read off the
        part and placed on the one nearest the edge of the view so its leader is
        short. Holes on a bolt circle say so (``EQ SP ON ⌀60``). A blind hole that
        opens on the far side belongs to the opposite view."""
        self._dims.append(_Dim("holes", (0.0, 0.0, 0.0), None, 0.0, None, None, angle=float(angle)))
        return self

    def hole_table(self, origin=None, *, at=None) -> "View":
        """Tabulate the holes and slots this view looks down, as a part with many
        holes is drawn: each tagged on the view (A1, A2 ... for one kind, B1 ...
        for the next), and a table of TAG, X, Y and SIZE in free paper beside it.
        Positions are measured from ``origin`` (a model point; the lower-left
        corner of the view's extent by default), which the view marks with its
        X and Y arrows; sizes are read off the part, as a callout reads them.
        ``at`` puts the table's top-left corner at that sheet point instead.
        A view tabulates its holes or calls them out, not both."""
        if self.name == "iso":
            raise ValueError("hole_table() tabulates an orthographic view's holes; an isometric has no X and Y")
        corner = None
        if at is not None:
            corner = _pair("at", at)
        self._table = (None if origin is None else _p3(origin), corner)
        return self

    def diameter(self, center, *retired, size: float | None = None, angle: float = 45.0,
                 text: str | None = None) -> "View":
        """A diameter callout on the circle centred at ``center``, measured off the
        view. ``size`` picks one of several concentric circles (a chamfered
        shaft end shows two) and is checked against the geometry."""
        _refuse_retired_size("diameter", retired)
        self._dims.append(_Dim("diameter", _p3(center), None, 0.0, text, None,
                               radius=0.0 if size is None else _positive("size", size) / 2, angle=float(angle)))
        return self

    def radius(self, center, *retired, size: float | None = None, angle: float = 45.0,
               text: str | None = None) -> "View":
        """A radius callout on the arc centred at ``center``, measured off the view;
        ``size`` (the radius) picks one of several and is checked like ``diameter``'s."""
        _refuse_retired_size("radius", retired)
        self._dims.append(_Dim("radius", _p3(center), None, 0.0, text, None,
                               radius=0.0 if size is None else _positive("size", size), angle=float(angle)))
        return self

    def angle(self, vertex, p1, p2, *, offset: float = 14.0) -> "View":
        """The angle at ``vertex`` between the legs toward ``p1`` and ``p2`` (model
        points); ``offset`` is the arc's distance from the vertex, in sheet mm."""
        # angle() was the one verb whose arguments went unchecked: offset=nan
        # reached the PDF, and two legs along one line printed "0 degrees" as
        # though that were a measurement.
        vertex, a, b = _p3(vertex), _p3(p1), _p3(p2)
        distance = _offset(offset)
        if distance is None or distance == 0.0:
            raise ValueError(f"angle offset must be a non-zero number of sheet millimetres, got {offset!r}")
        _assert_legs_measure_an_angle(vertex, a, b)
        self._dims.append(_Dim("angle", vertex, a, distance, None, None, radius=0.0, angle=0.0, hole={"p2": b}))
        return self

    def note(self, text: str, at, *, offset: tuple[float, float] = (10.0, 10.0)) -> "View":
        """A note with a leader from a model point; ``offset`` places the text, in
        sheet mm, relative to the projected point."""
        try:
            dx, dy = (float(offset[0]), float(offset[1]))
        except (TypeError, ValueError, IndexError) as exc:
            raise TypeError(f"note offset must be an (x, y) pair of sheet millimetres, got {offset!r}") from exc
        if not (math.isfinite(dx) and math.isfinite(dy)):
            raise ValueError(f"note offset must be finite, got {offset!r}")
        self._dims.append(_Dim("note", _p3(at), None, 0.0, str(text), None, radius=dx, angle=dy))
        return self

    def section(self, letter: str = "A", *, through=None) -> "View":
        """Draw this view as a full section, the way a drawing shows what hidden
        lines cannot: the part cut by the plane through ``through`` (a model
        point; the middle of the part by default) square to the line of sight,
        the half nearer the viewer taken away, the cut faces hatched at 45
        degrees, and no hidden lines. The cutting plane is drawn, with ``letter``
        at both ends and arrows in the viewing direction, on a view of the same
        part that sees it edge-on, and this view is labelled ``SECTION A-A``.
        Dimensions and callouts are given in model coordinates as on any view."""
        if self.name == "iso":
            raise ValueError("section() cuts an orthographic view; an isometric is drawn whole")
        if self._direction is not None:
            raise ValueError("section() cuts a principal view; an auxiliary view is drawn whole")
        letter = str(letter).upper()
        if len(letter) != 1 or letter not in _SECTION_LETTERS:
            raise ValueError(f"section letter must be one of {_SECTION_LETTERS} (ISO 128-40 leaves out I, O "
                             f"and Q), got {letter!r}")
        _refuse_used_letter(self.sheet, letter, self)
        self._section = (letter, None if through is None else _p3(through))
        self.hidden = False
        if self.label is None:
            self.label = f"SECTION {letter}-{letter}"
        return self

    def overall(self, *, width: bool = True, height: bool = True) -> "View":
        """Overall width (above) and height (left) of the view's projected extent,
        each on the outermost row of its side. Turn one off where another
        dimension already states it -- a turned part's height is its diameter,
        and a drawing states a size once."""
        self._overall = frozenset(name for name, on in (("width", width), ("height", height)) if on)
        return self

    def broken(self, start, end) -> "View":
        """Draw the view with the stretch between two model points taken out, the
        way a long part of constant section is drawn: the two ends at the sheet's
        scale, close together, a break line across each cut. ``start`` and
        ``end`` lie along one of the model's axes, in the plane of the view. A
        dimension across the break states its true length. The other views of
        the same arrangement that show that length are broken alike, so the
        views stay in line; the isometric is drawn whole. The drawing says if
        the part changes inside the break, since the break would hide it."""
        if self.name == "iso" or self._detail is not None or self._aux is not None or self._section is not None:
            raise ValueError("broken() shortens a whole principal view, not an isometric, a detail, an auxiliary "
                             "view or a section")
        a, b = _p3(start), _p3(end)
        axis = max(range(3), key=lambda k: abs(b[k] - a[k]))
        if abs(b[axis] - a[axis]) < 1e-6:
            raise ValueError("broken() takes two different points along the part's length")
        if abs(_look(self)[axis]) > 1e-9:
            raise ValueError(f"the {self.name} view looks along {'XYZ'[axis]}, so it shows no length to break; "
                             f"break a view that shows {'XYZ'[axis]} across the sheet")
        brk = (axis, min(a[axis], b[axis]), max(a[axis], b[axis]))
        views = [self]
        if self._arranged is not None:
            views = [v for v in self.sheet.views if v._arranged is self._arranged and v.name != "iso"
                     and abs(_look(v)[axis]) < 1e-9]
        for view in views:
            view._break = brk
        return self

    def balloons(self, parts: PartsList) -> "View":
        """Balloon every item of ``parts`` this view shows: its item number in a
        circle, with a leader ending in a dot on a point of the part the view
        sees. The balloons stand in a column beside a tall view (a row above and
        below a wide one), in the order of the points they key, so no two
        leaders cross. An item already ballooned in an earlier view of the sheet
        is not ballooned again, so ``balloons()`` on each view in turn keys each
        part once, where it is first seen; an item no view shows unhidden is
        reported. The view must draw ``parts.assembly``."""
        if not isinstance(parts, PartsList):
            raise TypeError(f"balloons() takes the PartsList that parts_list() returns, got {type(parts).__name__}")
        if self.shape is not parts.assembly:
            raise ValueError(
                "balloons() keys a view of the assembly the parts list was read from: draw parts.assembly "
                "(sheet.view(parts.assembly, ...)) and balloon that view."
            )
        _refuse_balloons_on(self)
        parts._frozen = True
        if parts not in self._balloons:
            self._balloons.append(parts)
        return self


def _fmt(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _refuse_used_letter(sheet, letter: str, view=None) -> None:
    """A letter names one section or one detail per sheet: two DETAIL Bs, or a
    DETAIL A beside SECTION A-A, send a reader to the wrong view."""
    if sheet is None:
        return
    for other in sheet.views:
        if other is view:
            continue
        if other._detail is not None and other._detail[3] == letter:
            raise ValueError(f"letter {letter} already names DETAIL {letter} on this sheet; pick another letter")
        if other._detail is None and other._section is not None and other._section[0] == letter:
            raise ValueError(f"letter {letter} already names SECTION {letter}-{letter} on this sheet; pick another letter")
        if other._aux is not None and other._aux[2] == letter:
            raise ValueError(f"letter {letter} already names VIEW {letter} on this sheet; pick another letter")


def _refuse_retired_size(verb: str, retired: tuple) -> None:
    """``diameter(center, radius)`` took a RADIUS and printed twice it, so
    ``diameter(c, 30)`` on a ⌀30 shaft printed ⌀60. The size is measured now."""
    if retired:
        raise TypeError(
            f"{verb}() no longer takes a size argument: it measures the circle at `center`. "
            f"Pass size=<{'diameter' if verb == 'diameter' else 'radius'}> only to pick one of several "
            "concentric circles; it is checked against the part."
        )


def _refuse_balloons_on(view) -> None:
    """Balloons key a whole view. A section's cut faces are not any part's faces,
    and a detail is a piece of another view; neither is ballooned yet."""
    if view._section is not None or view._detail is not None:
        kind = "a section" if view._detail is None else "a detail"
        raise ValueError(f"balloons() keys a whole view, and the {view.name} view is {kind}; balloon a view "
                         "of the assembly that is not cut or enlarged.")


def _tol(value):
    """Normalise a tolerance argument to (plus, minus) or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"tol must be a number or a (plus, minus) pair, got {value!r}")
    if isinstance(value, (int, float)):
        return (abs(float(value)), abs(float(value)))
    try:
        plus, minus = value
        return (abs(float(plus)), abs(float(minus)))
    except (TypeError, ValueError) as exc:
        raise TypeError(f"tol must be a number or a (plus, minus) pair, got {value!r}") from exc


def _assert_legs_measure_an_angle(vertex, a, b, *, tol_deg: float = 0.05) -> None:
    """Refuse two legs that do not subtend an angle.

    A zero-length leg has no direction, and two legs along one line subtend
    nothing: rendered anyway they print "0" beside an arc of no radius, which
    reads as a measured right angle gone wrong rather than as a bad call.
    """
    u = tuple(p - q for p, q in zip(a, vertex))
    v = tuple(p - q for p, q in zip(b, vertex))
    nu = math.sqrt(sum(c * c for c in u))
    nv = math.sqrt(sum(c * c for c in v))
    if not (nu > 0 and nv > 0):
        raise ValueError("angle needs two legs of non-zero length; p1 or p2 is the vertex itself")
    cosine = sum(c * d for c, d in zip(u, v)) / (nu * nv)
    degrees = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    if degrees < tol_deg or degrees > 180.0 - tol_deg:
        raise ValueError(
            f"angle legs are collinear ({degrees:.3g} deg apart), so there is no angle to dimension. "
            "Give p1 and p2 on the two different faces the angle is between."
        )


def _offset(value) -> float | None:
    """A dimension offset in sheet millimetres, or None for the next free row."""
    if value is None:
        return None
    try:
        offset = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"offset must be a number of sheet millimetres, got {value!r}") from exc
    if not math.isfinite(offset):
        raise ValueError(f"offset must be finite, got {value!r}")
    return offset


def _positive(name: str, value, *, allow_none: bool = False, integer: bool = False):
    """A dimension the shop can make: a real, finite, positive number."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a number, got {value!r}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive number, got {value!r}")
    return int(round(number)) if integer else number


def _pair(name: str, value) -> tuple[float, float] | None:
    """A (diameter, depth) or (diameter, angle) pair, both positive."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a pair of numbers, got {value!r}")
    values = tuple(value)
    if len(values) != 2:
        raise ValueError(f"{name} must be a pair of numbers, got {value!r}")
    return (_positive(f"{name}[0]", values[0]), _positive(f"{name}[1]", values[1]))


def _tol_suffix(tol) -> str:
    if not tol:
        return ""
    plus, minus = tol
    if abs(plus - minus) < 1e-9:
        return f" ±{_fmt(plus)}"
    return f" +{_fmt(plus)}/-{_fmt(minus)}"


def hole_callout_text(spec: dict, *, tol=None, fit: str | None = None) -> str:
    """The text of a hole callout, in the ISO/ASME symbols a shop reads."""
    parts = []
    # One hole is not "1×": a count prints only when there is something to count.
    lead = f"{spec['count']}× " if (spec.get("count") or 1) > 1 else ""
    if spec.get("slot"):
        text = f"{lead}{_fmt(spec['width'])} × {_fmt(spec['length'])} SLOT"
        text += " THRU" if spec.get("thru") else (f" \u21a7{_fmt(spec['depth'])}" if spec.get("depth") else "")
        if spec.get("cbore"):
            width, length, depth = spec["cbore"]
            text += f"   \u2334 {_fmt(width)} × {_fmt(length)} \u21a7{_fmt(depth)}"
        return text + (f"   {spec['label']}" if spec.get("label") else "")
    size = spec["thread"] if spec.get("thread") else f"%%c{_fmt(spec['diameter'])}"
    size += _tol_suffix(tol) + (f" {fit}" if fit else "")
    if spec.get("thru"):
        size += " THRU"
    elif spec.get("depth") is not None:
        size += f" \u21a7{_fmt(spec['depth'])}"
    if spec.get("pcd"):
        # The bolt circle: equally spaced on a circle of this diameter.
        size += f" EQ SP ON %%c{_fmt(spec['pcd'])}"
    parts.append(lead + size)

    def same(a, b) -> bool:
        return a is not None and b is not None and all(abs(x - y) < 1e-3 for x, y in zip(a, b))

    def cbore(pair) -> str:
        return f"\u2334 %%c{_fmt(pair[0])} \u21a7{_fmt(pair[1])}"

    def csk(pair) -> str:
        return f"\u2335 %%c{_fmt(pair[0])} × {_fmt(pair[1])}°"

    # A through hole can be opened out at both ends: the same at each is stated
    # once, BOTH ENDS; something different at the far end is stated FAR SIDE.
    for near, far, text in ((spec.get("cbore"), spec.get("far_cbore"), cbore),
                            (spec.get("csk"), spec.get("far_csk"), csk)):
        if near:
            parts.append(text(near) + (" BOTH ENDS" if same(near, far) else ""))
    for near, far, text in ((spec.get("cbore"), spec.get("far_cbore"), cbore),
                            (spec.get("csk"), spec.get("far_csk"), csk)):
        if far and not same(near, far):
            parts.append("FAR SIDE " + text(far))
    if spec.get("label"):
        parts.append(str(spec["label"]))
    return "   ".join(parts)


def _p3(p) -> tuple[float, float, float]:
    values = tuple(float(v) for v in p)
    if len(values) == 2:
        values = (values[0], values[1], 0.0)
    if len(values) != 3:
        raise ValueError(f"expected a 2D or 3D point, got {p!r}")
    return values  # type: ignore[return-value]


def _dirs(view) -> tuple:
    """Where a view's viewer stands, and its up: an auxiliary view's own, or its name's."""
    return view._direction or VIEW_DIRECTIONS[view.name]


def _look(view) -> tuple:
    return _dirs(view)[0]


def _face_normal(shape, point) -> tuple:
    """The outward normal of the flat face of ``shape`` through ``point``, and the
    points of that face's outline."""
    from build123d import GeomType, Vector

    target = Vector(*point)
    near = []
    for face in shape.faces():
        if face.geom_type != GeomType.PLANE:
            continue
        # On the face's plane and inside its outline: the middle of a face with a
        # hole in it is a point on that face to whoever names it.
        normal = face.normal_at(face.center())
        box = face.bounding_box()
        if abs((target - face.center()).dot(normal)) < 1e-3 and all(
                lo - 1e-3 <= v <= hi + 1e-3 for v, lo, hi in zip(target, box.min, box.max)):
            near.append((face.distance_to(target), face))
    if not near:
        raise ValueError(f"no flat face of the part passes through {_where(point)}; an auxiliary view looks "
                         "square onto a flat face, so give a point on one")
    face = min(near, key=lambda pair: pair[0])[1]
    normal = face.normal_at(target)
    return (normal.X, normal.Y, normal.Z), _wire_points(face.outer_wire())


@dataclass
class Sheet:
    """One sheet of a drawing: a frame, a title block and the views placed on it.

    ``at`` positions on views are the sheet's own millimetres with the origin at
    the sheet's bottom-left corner; ``scale`` is drawing scale (1 = 1:1, 0.5 = 1:2).

    ``size=None`` and ``scale=None`` let the sheet choose: :meth:`three_views`
    picks the smallest sheet and the largest standard scale its views and their
    annotation fit at, and a scale the sheet chose steps down when it renders,
    should the annotation added afterwards need more paper.
    """

    size: str | None = "A3"
    scale: float | None = 1.0
    title: str = "UNTITLED"
    part_number: str = ""
    material: str = ""
    revision: str = "A"
    author: str = ""
    #: Surface finish or treatment, as the requirement states it ("ANODISE CLEAR").
    finish: str = ""
    #: The drawing's date, as the author writes it. Never stamped from the clock:
    #: the PDF's bytes are a function of its content.
    date: str = ""
    units: str = "mm"
    projection: str = "THIRD ANGLE"
    notes: Sequence[str] = ()
    ink: str = "mono"
    text_height: float = 3.5
    #: A general tolerance standard, e.g. "ISO 2768-m": written as the first note.
    general_tolerance: str = ""
    #: Revision history rows (rev, date, description), drawn as a table top-right.
    revisions: Sequence[tuple[str, str, str]] = ()
    #: A second line under the title: on a part's sheet of an assembly drawing,
    #: which item it details and of what ("ITEM 4 OF SHOCK ABSORBER").
    subtitle: str = ""
    views: list[View] = field(default_factory=list)
    #: ``(parts list, first item, last item)`` when :meth:`parts_list` draws one.
    _parts: tuple | None = field(default=None, init=False, repr=False)
    #: The sheet chose its own scale (``scale=None``) and may take a smaller
    #: standard one when its views and their annotation need it.
    _fit: bool = field(default=False, init=False, repr=False)
    #: ``(size chosen, scale chosen)``: which of the two the sheet settles itself.
    _auto: tuple = field(default=(False, False), init=False, repr=False)
    #: The largest scale a chosen scale may take: one that ran off the frame
    #: lowers it, so the next choice does not take it again.
    _ceiling: float | None = field(default=None, init=False, repr=False)
    #: The smallest size a chosen size may take: a sheet that ran out of paper
    #: raises it, so the next choice tries a larger sheet before a smaller scale.
    _floor: int = field(default=0, init=False, repr=False)
    #: ``(size, scale)`` as the sheet last chose them: a value the author sets
    #: afterwards is theirs, and the sheet stops choosing it.
    _chosen: tuple | None = field(default=None, init=False, repr=False)
    #: ``(item, assembly title)`` for a part's sheet of an assembly drawing: its
    #: title, subtitle and material are the item's when it renders.
    _item: tuple | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.size is not None and self.size not in SHEET_SIZES:
            raise ValueError(f"unknown sheet size {self.size!r}; one of {sorted(SHEET_SIZES)}, or None to let "
                             "three_views() choose")
        if self.scale is not None and (isinstance(self.scale, bool) or not isinstance(self.scale, (int, float))
                                       or not (self.scale > 0)):
            raise ValueError(f"scale must be a positive number, or None to let three_views() choose; got "
                             f"{self.scale!r}")
        self._fit = self.scale is None
        self._auto = (self.size is None, self.scale is None)
        if self.units not in UNITS:
            raise ValueError(
                f"units={self.units!r}: a sheet prints millimetres, the unit every value on it is measured "
                "in. An inch drawing would need every measured value converted, and nothing here does that "
                "yet; labelling millimetre values IN would make each one wrong by 25.4."
            )
        # The title block prints this label and `three_views` lays the views out to
        # match it. Accepting any string would print "FIRST ANGLE" over a third-angle
        # arrangement, which is the one mislabel a shop cannot recover from.
        if self.projection not in PROJECTIONS:
            raise ValueError(
                f"unknown projection {self.projection!r}; one of {sorted(PROJECTIONS)}. "
                "The label and the view arrangement are the same decision."
            )
        # A str is a Sequence[str] of its own characters, so notes="BREAK EDGES"
        # printed eleven numbered notes reading B, R, E, A, K... The one-note case
        # is the common one and the wrong spelling of it cannot be told apart from
        # the right one later, so it is refused here.
        for name in ("notes", "revisions"):
            if isinstance(getattr(self, name), (str, bytes)):
                raise TypeError(
                    f"{name} must be a sequence, not a string: {name}=[{getattr(self, name)!r}] "
                    "for one entry. A bare string is a sequence of its own characters."
                )
        # `notes` and `revisions` are read twice, by this guard and by the draw. A
        # generator would be empty the second time and the sheet would print no
        # notes at all, so they are materialized once, here.
        self.notes = tuple(self.notes)
        self.revisions = tuple(tuple(row) for row in self.revisions)
        for row in self.revisions:
            if isinstance(row, (str, bytes)) or len(row) != 3:
                raise ValueError(f"each revision must be a (rev, date, description) triple, got {row!r}")
        if self.size is not None:
            self._check_notes()

    def _check_notes(self) -> None:
        """A note wider than the sheet runs off the paper, and the sheet is the one
        thing here that cannot be made bigger after the fact. Measure the line the
        sheet DRAWS -- numbered, prefixed, general tolerance expanded -- at the
        height it draws it, against the room it has."""
        room = self.width - 2 * (_MARGIN + _NOTE_INSET)
        for line, note in zip(self.note_lines(), self.drawn_notes()):
            if _text_width(line, _NOTE_HEIGHT) > room:
                raise ValueError(
                    f"note {note!r} is wider than the {self.size} sheet's note row "
                    f"({round(room)} mm). Shorten it, or split it across two notes."
                )

    def drawn_notes(self) -> list[str]:
        """The note strings as they reach the paper: the general tolerance, spelled
        out, is note 1 when it is given."""
        general = [f"TOLERANCES PER {self.general_tolerance} UNLESS OTHERWISE SPECIFIED."]
        return (general if self.general_tolerance else []) + list(self.notes)

    def note_lines(self) -> list[str]:
        """Each drawn note with the prefix and number the sheet prints before it."""
        notes = self.drawn_notes()
        return [f"{'NOTES:  ' if row == 0 else '        '}{row + 1}. {note}"
                for row, note in enumerate(notes)]

    @property
    def width(self) -> float:
        return SHEET_SIZES[self._size()][0]

    @property
    def height(self) -> float:
        return SHEET_SIZES[self._size()][1]

    def _size(self) -> str:
        if self.size is None:
            raise ValueError(
                "Sheet(size=None) chooses its size when three_views() places the part, and nothing has been "
                "placed yet. Call three_views() first, or give size= for views placed by hand."
            )
        return self.size

    def _scale(self) -> float:
        if self.scale is None:
            raise ValueError(
                "Sheet(scale=None) chooses its scale when three_views() places the part, and nothing has been "
                "placed yet. Call three_views() first, or give scale= for views placed by hand."
            )
        return self.scale

    def three_views(self, shape, *, gap: float | None = None, hidden: bool = True, centre_marks: bool = True,
                    iso: bool = False) -> tuple[View, View, View] | tuple[View, View, View, View]:
        """Top, front and right views in the arrangement ``projection`` names, placed
        from the part's own extents. ``iso=True`` adds an isometric in the free
        corner, at a standard scale, and returns it fourth.

        The positions returned are provisional: when the sheet renders, the views
        are laid out again with each gap sized to the dimensions and callouts the
        facing views actually carry, so annotation added after this call gets
        room. ``gap`` fixes the clear space between views instead.

        On a sheet made with ``size=None`` or ``scale=None``, the first call
        chooses them for this part (see :class:`Sheet`)."""
        size = shape.bounding_box().size
        arranged = (size, gap, _view_extent(shape, "iso", 1.0) if iso else False)
        if self.size is None or self.scale is None:
            _choose_size_and_scale(self, shape, arranged[2], {n: dict(_DEFAULT_ROOM) for n in ("top", "front", "right")},
                                   gap)
        slots = _arrange_three_views(self, shape, size, gap, self._scale(), arranged[2])
        views = tuple(
            self.view(shape, name, at=at, hidden=hidden if name != "iso" else False,
                      centre_marks=centre_marks if name != "iso" else False,
                      label=label, scale=view_scale)
            for name, at, view_scale, label in slots
        )
        # One arrangement, shared by its views, so the render lays them out again
        # together from what each carries.
        for view in views:
            view._arranged = arranged
            if view.name == "iso":
                view._auto = (view.label, view.scale)
        return views

    def detail(self, view: "View", center, radius: float, *, letter: str = "B", scale: float | None = None,
               at=None) -> "View":
        """A detail view: the part of ``view`` inside a circle of ``radius`` (model
        mm) round ``center`` (a model point), drawn larger and labelled
        ``DETAIL B (5:1)``. The parent view gets the circle and the letter.

        ``scale`` defaults to the largest standard scale, at least twice the
        parent's, that draws the circle no more than 60 mm across, stepping down
        if the paper has no room for that. ``at`` places it by hand; left unset,
        the render puts it in the nearest free paper. A
        detail of a section keeps the section's cut and hatching. Dimensions and
        callouts are given in model coordinates as on any view, and ``holes()``
        calls out only what the circle holds."""
        if view not in self.views:
            raise ValueError("detail() takes a view of this sheet")
        if view.name == "iso" or view._detail is not None:
            raise ValueError("detail() enlarges an orthographic view or a section, not an isometric or a detail")
        letter = str(letter).upper()
        if len(letter) != 1 or letter not in _SECTION_LETTERS:
            raise ValueError(f"detail letter must be one of {_SECTION_LETTERS} (ISO 128-40 leaves out I, O and Q), "
                             f"got {letter!r}")
        _refuse_used_letter(self, letter)
        r = _positive("radius", radius)
        parent_scale = view.scale or self.scale
        chosen = scale is None
        if scale is None:
            fits = [c for c in _STANDARD_SCALES if c >= 2 * parent_scale - 1e-9 and 2 * r * c <= _DETAIL_SIZE]
            larger = [c for c in _STANDARD_SCALES if c > parent_scale + 1e-9]
            scale = max(fits) if fits else (min(larger) if larger else 2 * parent_scale)
        elif not (scale > 0):
            raise ValueError("a detail's scale must be positive")
        if at is not None:
            try:
                at = (float(at[0]), float(at[1]))
            except (TypeError, ValueError, IndexError) as exc:
                raise TypeError(f"detail at= must be an (x, y) pair of sheet millimetres, got {at!r}") from exc
            if not (math.isfinite(at[0]) and math.isfinite(at[1])):
                raise ValueError(f"detail at= must be finite sheet millimetres, got {at!r}")
        detail = View(self, view.shape, view.name, at or (0.0, 0.0), f"DETAIL {letter} ({_scale_label(scale)})",
                      view.hidden, view.centre_marks, scale)
        detail._detail = (view, _p3(center), r, letter, at is None, chosen)
        detail._direction = view._direction
        self.views.append(detail)
        return detail

    def auxiliary(self, view: "View", point, *, letter: str = "C", scale: float | None = None, at=None,
                  partial: bool = True) -> "View":
        """An auxiliary view: the part seen square to the flat face through
        ``point`` (a model point on it), so an inclined face shows its true shape
        and its holes as circles. Labelled ``VIEW C``; ``view``, the view it is
        projected from, gets an arrow pointing the way it looks, and the letter.

        It is drawn with the face's slope running up the sheet, at ``view``'s
        scale unless ``scale`` is given, and placed in the free paper nearest
        ``view`` unless ``at`` places it. It shows that face and what lies within
        its outline, as a partial view does, since the rest of the part is
        foreshortened there; ``partial=False`` draws the whole part. Give it
        dimensions and callouts like any view; ``holes()`` on it calls out the
        holes in that face."""
        if view not in self.views:
            raise ValueError("auxiliary() takes a view of this sheet")
        if view.name == "iso" or view._detail is not None or view._aux is not None:
            raise ValueError("auxiliary() projects from a principal view, not an isometric, a detail or another "
                             "auxiliary view")
        letter = str(letter).upper()
        if len(letter) != 1 or letter not in _SECTION_LETTERS:
            raise ValueError(f"auxiliary view letter must be one of {_SECTION_LETTERS} (ISO 128-40 leaves out I, O "
                             f"and Q), got {letter!r}")
        _refuse_used_letter(self, letter)
        if scale is not None and not (scale > 0):
            raise ValueError("an auxiliary view's scale must be positive")
        corner = None if at is None else _pair("at", at)
        n, outline = _face_normal(view.shape, _p3(point))
        for name, (direction, _up) in VIEW_DIRECTIONS.items():
            if name != "iso" and _dot(n, direction) > 1 - 1e-6:
                raise ValueError(f"the face at {_where(point)} faces the {name} view square on; draw that view "
                                 "rather than an auxiliary one")
        look = _look(view)
        if abs(_dot(n, look)) > 1 - 1e-6:
            raise ValueError(f"the face at {_where(point)} faces the {view.name} view square on already")
        # Up is the parent's up laid onto the face, so the face's slope runs up the sheet.
        parent_up = _dirs(view)[1]
        up = tuple(u - _dot(parent_up, n) * c for u, c in zip(parent_up, n))
        if math.sqrt(_dot(up, up)) < 1e-6:
            up = tuple(u - _dot(look, n) * c for u, c in zip(look, n))
        length = math.sqrt(_dot(up, up))
        up = tuple(c / length for c in up)
        own = scale if scale is not None else view.scale
        label = f"VIEW {letter}" + (f" ({_scale_label(own)})" if own is not None and own != self.scale else "")
        aux = View(self, view.shape, "auxiliary", corner or (0.0, 0.0), label, view.hidden, view.centre_marks, own)
        aux._direction = (n, up)
        aux._aux = (view, _p3(point), letter, corner is None, outline if partial else None)
        self.views.append(aux)
        return aux

    def parts_list(self, parts: PartsList, *, first: int = 1, last: int | None = None) -> "Sheet":
        """Draw ``parts`` as the parts list, directly above the title block and as
        wide as it, the way ISO 7573 and ASME Y14.34 place one: ITEM, QTY,
        DESCRIPTION, PART NO. and MATERIAL, the header against the title block
        and item 1 above it, so the list reads upward. A blank PART NO. or
        MATERIAL is one the drawing does not state.

        ``first`` and ``last`` draw a run of the items, for a list too long for
        one sheet; the rest goes on a further sheet's ``parts_list``, and each
        run says on which sheet the list continues."""
        if not isinstance(parts, PartsList):
            raise TypeError(f"parts_list() takes the PartsList that parts_list() returns, got {type(parts).__name__}")
        if self._parts is not None:
            raise ValueError("a sheet carries one parts list; draw the rest of a long one on a further sheet")
        last = len(parts) if last is None else last
        if (isinstance(first, bool) or isinstance(last, bool) or not isinstance(first, int)
                or not isinstance(last, int) or not 1 <= first <= last <= len(parts)):
            raise ValueError(f"parts_list(first={first!r}, last={last!r}): the items run 1 to {len(parts)}")
        parts._frozen = True
        room = _list_room(self)
        if (last - first + 2) * _LIST_ROW > room:
            fits = int(room // _LIST_ROW) - 1
            raise ValueError(
                f"a parts list of {last - first + 1} items needs {(last - first + 2) * _LIST_ROW:.0f} mm above the "
                f"title block, and {self.size} has {room:.0f}. Draw items {first} to {first + fits - 1} here "
                f"(parts_list(parts, last={first + fits - 1})) and the rest on a further sheet "
                f"(parts_list(parts, first={first + fits}))."
            )
        self._parts = (parts, first, last)
        return self

    def view(self, shape, name: str, *, at, label: str | None = None, hidden: bool = True, centre_marks: bool = True,
             scale: float | None = None) -> View:
        if name not in VIEW_DIRECTIONS:
            raise ValueError(f"unknown view {name!r}; one of {sorted(VIEW_DIRECTIONS)}")
        if scale is not None and not (scale > 0):
            raise ValueError("a view's scale must be positive")
        self._size()
        self._scale()  # a view placed by hand is placed on a sheet of known size and scale
        # A non-finite at= compares False against every frame edge, so the off-frame
        # guard passed it and the sheet rendered blank at exit 0 -- the one outcome
        # the guard exists to prevent.
        try:
            at = (float(at[0]), float(at[1]))
        except (TypeError, ValueError, IndexError) as exc:
            raise TypeError(f"view at= must be an (x, y) pair of sheet millimetres, got {at!r}") from exc
        if not (math.isfinite(at[0]) and math.isfinite(at[1])):
            raise ValueError(f"view at= must be finite sheet millimetres, got {at!r}")
        view = View(self, shape, name, at, label, hidden, centre_marks, scale)
        self.views.append(view)
        return view


# --- projection ---------------------------------------------------------------------

def _project_to_viewport(shape, origin, up, look_at):
    """Hidden-line projection, with tangent transitions left out of the hidden half.

    ``Shape.project_to_viewport`` bundles three OCCT compounds into each half.
    For the hidden half those are sharp edges (``HCompound``), silhouettes
    (``OutLineHCompound``) and SMOOTH edges (``Rg1LineHCompound``) -- the
    tangent transition where a fillet runs into a face, or a cylinder into the
    plane it touches. A drawing does not draw those: ISO 128 has no tangent
    transition line, and one that is behind material marks nothing a shop could
    look at. Drawn anyway they print as extra dashed lines running the length of
    the feature they belong to, which reads as a hidden edge that is not there.
    On the examples' circular flange the right view drew two, the full width of
    the part.

    The visible half keeps all three: a tangent line you can see is the
    conventional runout, and the sheets already read correctly with them.
    """
    from build123d import Edge, ShapeList, Vector
    from build123d.topology import downcast
    from OCP.BRepLib import BRepLib
    from OCP.gp import gp_Ax1, gp_Ax2
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    hlr = HLRBRep_Algo()
    hlr.Add(shape.wrapped)
    camera = gp_Ax2()
    camera.SetAxis(gp_Ax1(Vector(origin).to_pnt(), (Vector(origin) - Vector(look_at)).normalized().to_dir()))
    camera.SetYDirection(Vector(up).normalized().to_dir())
    hlr.Projector(HLRAlgo_Projector(camera))
    hlr.Update()
    hlr.Hide()
    shapes = HLRBRep_HLRToShape(hlr)

    def edges(compound) -> list:
        found = []
        if compound is None or compound.IsNull():
            return found
        explorer = TopExp_Explorer(downcast(compound), TopAbs_ShapeEnum.TopAbs_EDGE)
        while explorer.More():
            edge = downcast(explorer.Current())
            # Without this the curve is 2D only and later reads segfault.
            BRepLib.BuildCurves3d_s(edge, 1e-9)
            found.append(Edge(edge))
            explorer.Next()
        return found

    # Same compounds in the same order as build123d, so the entity order on the
    # sheet -- and the PDF bytes -- do not move; the hidden half drops Rg1Line.
    visible = (edges(shapes.VCompound()) + edges(shapes.Rg1LineVCompound())
               + edges(shapes.OutLineVCompound()))
    hidden = edges(shapes.HCompound()) + edges(shapes.OutLineHCompound())
    return ShapeList(visible), ShapeList(hidden)


class _Projection:
    """The affine map a build123d viewport applies, recovered from the viewport
    itself, so dimension points land exactly where the geometry did."""

    def __init__(self, shape, name: str, draw=None) -> None:
        """``draw`` is what to project, when it is not ``shape`` itself: a section
        draws the cut part through the whole part's map, so it lines up with the
        views beside it."""
        from build123d import Axis, Edge, Vector

        direction, up = VIEW_DIRECTIONS[name] if isinstance(name, str) else name
        bbox = shape.bounding_box()
        centre = bbox.center()
        radius = max(bbox.size.length, 1.0)
        d = Vector(*direction).normalized()
        origin = centre + d * (radius * 10.0)
        self.origin, self.up, self.look_at = origin, up, centre
        self.visible, self.hidden = _project_to_viewport(shape if draw is None else draw, origin, up, centre)
        # Recover the map from three unit lines along the model axes.
        probes = []
        for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            line = Edge.make_line(Vector(0, 0, 0), Vector(*axis))
            vis, hid = line.project_to_viewport(viewport_origin=origin, viewport_up=up, look_at=centre)
            edges = list(vis) + list(hid)
            if not edges:
                probes.append(((0.0, 0.0), (0.0, 0.0)))
                continue
            e = edges[0]
            a, b = e.position_at(0), e.position_at(1)
            probes.append(((a.X, a.Y), (b.X, b.Y)))
        # Each probe's start is the projected origin; its end minus start is the axis image.
        # Anchor on the first probe that projected to a line: the X probe is parallel
        # to the right and left views and comes back empty, and anchoring on its
        # zero placeholder put the projected centre in the wrong place, so the
        # fix-up below chose the wrong end of the Z probe and mirrored those views'
        # annotations vertically.
        o = next((p[0] for p in probes if p[0] != p[1]), (0.0, 0.0))
        self.c = o
        self.m = [(p[1][0] - p[0][0], p[1][1] - p[0][1]) for p in probes]
        # A probe whose line is parallel to the view direction projects to a point;
        # its axis image is zero, which is correct. A projected edge can come back
        # with its ends swapped, so the map is settled by probes anchored at the
        # model centre, whose projected start is unambiguous.
        self._m_fixup(shape, centre)

    def _m_fixup(self, shape, centre) -> None:
        from build123d import Edge, Vector

        # Probe with a line from the centre to the centre + axis, whose START is
        # unambiguous: its projected start must equal the projected centre.
        for index, axis in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
            line = Edge.make_line(centre, centre + Vector(*axis) * 7.0)
            vis, hid = line.project_to_viewport(viewport_origin=self.origin, viewport_up=self.up, look_at=self.look_at)
            edges = list(vis) + list(hid)
            if not edges:
                continue
            e = edges[0]
            a, b = e.position_at(0), e.position_at(1)
            # Whichever end is closer to the projected centre is the start.
            pc = self._raw_point(tuple(centre))
            da = math.hypot(a.X - pc[0], a.Y - pc[1])
            db = math.hypot(b.X - pc[0], b.Y - pc[1])
            start, end = (a, b) if da <= db else (b, a)
            self.m[index] = ((end.X - start.X) / 7.0, (end.Y - start.Y) / 7.0)
            self.c = (pc[0] - (self.m[0][0] * centre.X + self.m[1][0] * centre.Y + self.m[2][0] * centre.Z),
                      pc[1] - (self.m[0][1] * centre.X + self.m[1][1] * centre.Y + self.m[2][1] * centre.Z))

    def _raw_point(self, p) -> tuple[float, float]:
        x = self.c[0] + self.m[0][0] * p[0] + self.m[1][0] * p[1] + self.m[2][0] * p[2]
        y = self.c[1] + self.m[0][1] * p[0] + self.m[1][1] * p[1] + self.m[2][1] * p[2]
        return (x, y)

    #: A broken view's map from model points to the shortened part's, or None.
    shift: Callable | None = None

    def point(self, p) -> tuple[float, float]:
        return self._raw_point(self.shift(p) if self.shift else p)


def _edges_bounds(edges) -> tuple[float, float, float, float] | None:
    """Exact (x0, x1, y0, y1) of projected edges, from the kernel's own bounding boxes,
    so a circle's extent is its diameter and not the chord of a few samples."""
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for edge in edges:
        bb = edge.bounding_box()
        x0, x1 = min(x0, bb.min.X), max(x1, bb.max.X)
        y0, y1 = min(y0, bb.min.Y), max(y1, bb.max.Y)
    if not math.isfinite(x0):
        return None
    return (x0, x1, y0, y1)


def _view_extent(shape, name: str, scale: float) -> tuple[float, float]:
    """The projected (width, height) of a view in sheet millimetres, for placement."""
    proj = _Projection(shape, name)
    bounds = _edges_bounds(list(proj.visible) + list(proj.hidden))
    if not bounds:
        return (0.0, 0.0)
    return ((bounds[1] - bounds[0]) * scale, (bounds[3] - bounds[2]) * scale)


def _edge_polyline(edge, samples: int = 24) -> list[tuple[float, float]]:
    """A projected edge as points. Sampled by arc length where OCCT can measure it;
    a projected spline that has collapsed to almost nothing (an assembly's hidden
    seam seen edge-on, say) makes that fail inside OCCT, so such an edge is
    sampled by its own curve parameter instead."""
    from build123d import GeomType

    n = 2 if edge.geom_type == GeomType.LINE else samples
    try:
        return [(float(v.X), float(v.Y)) for v in (edge.position_at(i / (n - 1)) for i in range(n))]
    except Exception:  # noqa: BLE001 - OCCT's Standard_Failure carries no type worth naming
        from OCP.BRepAdaptor import BRepAdaptor_Curve

        curve = BRepAdaptor_Curve(edge.wrapped)
        t0, t1 = curve.FirstParameter(), curve.LastParameter()
        points = [curve.Value(t0 + (t1 - t0) * i / (n - 1)) for i in range(n)]
        return [(float(p.X()), float(p.Y())) for p in points]


def _circles(edges) -> list[tuple[tuple[float, float], float]]:
    """Full circles among projected edges: (centre, radius) in viewport coordinates."""
    from build123d import GeomType

    found: list[tuple[tuple[float, float], float]] = []
    for edge in edges:
        if edge.geom_type != GeomType.CIRCLE or not edge.is_closed:
            continue
        c = edge.arc_center
        key = ((round(c.X, 3), round(c.Y, 3)), round(edge.radius, 3))
        if key not in found:
            found.append(key)
    return found


def _centres(circles: Sequence[tuple[tuple[float, float], float]]) -> list[tuple[tuple[float, float], float]]:
    """One entry per circle centre, carrying the largest radius found on it."""
    largest: dict[tuple[float, float], float] = {}
    for centre, radius in circles:
        if radius > largest.get(centre, -1.0):
            largest[centre] = radius
    return list(largest.items())


# --- writing ------------------------------------------------------------------------

def _dimstyle(doc, text_height: float):
    style = doc.dimstyles.get("Standard")
    style.dxf.dimtxt = text_height
    style.dxf.dimasz = text_height * 0.85
    style.dxf.dimexo = 1.5
    style.dxf.dimexe = 2.0
    style.dxf.dimgap = 1.0
    style.dxf.dimtad = 1
    style.dxf.dimdec = 2
    style.dxf.dimzin = 8
    style.dxf.dimdsep = ord(".")
    style.dxf.dimtdec = 2
    style.dxf.dimblk = "_CLOSEDFILLED"
    return "Standard"


#: The least clear space between two views, and the air left between one view's
#: annotation and the next view's.
_MIN_GAP = 20.0
_AIR = 8.0
#: What a view's annotation is assumed to need before its dimensions are known:
#: two rows above and to the left, a label below. Only the positions
#: :meth:`Sheet.three_views` hands back at once use it; the render lays the sheet
#: out again from what each view actually carries.
_DEFAULT_ROOM = {"top": 2 * _DIM_ROW + 5.0, "bottom": 12.0, "left": 2 * _DIM_ROW + 5.0, "right": 12.0}


def _arrange_three_views(sheet: "Sheet", shape, size, gap: float | None, s: float, iso,
                         room: dict | None = None, crowding: list | None = None
                         ) -> list[tuple[str, tuple[float, float], float | None, str | None]]:
    """Where the three (or four) views of a standard arrangement go at scale ``s``.

    ``room`` is what each view's annotation takes on every side, in sheet
    millimetres -- its dimension rows, its hole callouts, the label underneath --
    so the space between two views is what their facing sides need, not one
    figure for every sheet. A front view with three rows of dimensions above it
    pushes the top view up instead of printing its outermost row over the top
    view's label. A ``gap`` the author gives is used as is. When the room asked
    for does not fit the paper, the gaps give it back first, down to
    ``_MIN_GAP``, and anything that still collides is reported by the render.

    Separate from :meth:`Sheet.three_views` so the off-frame guard can ask the
    same question of a candidate scale: the views shrink with the scale and
    their annotation does not. ``iso`` is False, or the isometric's projected
    (width, height) at 1:1, measured once by the caller: it is a hidden-line
    projection, and the guard asks this question at every candidate scale.
    """
    L, W, H = size.X * s, size.Y * s, size.Z * s
    need = {name: dict(_DEFAULT_ROOM) for name in ("top", "front", "right")}
    for name, value in (room or {}).items():
        if name in need:
            need[name] = dict(value)
    third = sheet.projection == "THIRD ANGLE"
    if gap is not None:
        gap_v = gap_h = gap
    elif third:
        gap_v = max(_MIN_GAP, need["top"]["bottom"] + need["front"]["top"] + _AIR)
        gap_h = max(_MIN_GAP, need["front"]["right"] + need["right"]["left"] + _AIR)
    else:
        gap_v = max(_MIN_GAP, need["front"]["bottom"] + need["top"]["top"] + _AIR)
        gap_h = max(_MIN_GAP, need["right"]["right"] + need["front"]["left"] + _AIR)
    m = _MARGIN
    note_rows = len(sheet.drawn_notes())
    notes_h = (note_rows * 5.0 + 8.0) if note_rows else 0.0
    # A parts list stands on the title block beside the notes; the views go above both.
    list_h = _list_height(sheet) + 6.0 if sheet._parts is not None else 0.0
    x_lo, x_hi = m + 4.0, sheet.width - m - 4.0
    y_lo, y_hi = m + _TITLE_H + max(notes_h, list_h) + 4.0, sheet.height - m - 4.0
    sizes = {"top": (L, W), "front": (L, H), "right": (W, H)}

    def place(gv: float, gh: float):
        if third:
            centres = {"front": (L / 2, H / 2), "top": (L / 2, H + gv + W / 2), "right": (L + gh + W / 2, H / 2)}
        else:
            # First angle places each view on the side opposite the one it looks
            # from: the plan below the front, the view from the right to its left.
            # The pictures are the third-angle pictures; only the slots swap.
            centres = {"right": (W / 2, W + gv + H / 2), "front": (W + gh + L / 2, W + gv + H / 2),
                       "top": (W + gh + L / 2, W / 2)}
        boxes = [(cx - sizes[n][0] / 2 - need[n]["left"], cx + sizes[n][0] / 2 + need[n]["right"],
                  cy - sizes[n][1] / 2 - need[n]["bottom"], cy + sizes[n][1] / 2 + need[n]["top"])
                 for n, (cx, cy) in centres.items()]
        block = (min(b[0] for b in boxes), max(b[1] for b in boxes),
                 min(b[2] for b in boxes), max(b[3] for b in boxes))
        return centres, block

    centres, block = place(gap_v, gap_h)
    over_w = (block[1] - block[0]) - (x_hi - x_lo)
    over_h = (block[3] - block[2]) - (y_hi - y_lo)
    if crowding is not None:
        crowding[:] = [max(0.0, over_w), max(0.0, over_h)]
    if gap is None and (over_w > 0 or over_h > 0):
        centres, block = place(max(_MIN_GAP, gap_v - max(0.0, over_h)), max(_MIN_GAP, gap_h - max(0.0, over_w)))
    # Centred in the paper the views and their annotation leave free; a block that
    # does not fit starts at the bottom-left, so it is the top and right that run
    # off and the guard names a scale. With a pictorial the block keeps to the
    # left, as a print does, and the right of the sheet is the pictorial's.
    slack_w = max(0.0, (x_hi - x_lo) - (block[1] - block[0]))
    dx = x_lo - block[0] + (min(slack_w / 2, 12.0) if iso else slack_w / 2)
    dy = y_lo - block[2] + max(0.0, ((y_hi - y_lo) - (block[3] - block[2])) / 2)
    at = {n: (cx + dx, cy + dy) for n, (cx, cy) in centres.items()}
    slots: list[tuple[str, tuple[float, float], float | None, str | None]] = [
        ("top", at["top"], None, None), ("front", at["front"], None, None), ("right", at["right"], None, None)]
    if not iso:
        return slots
    # Where the pictorial can go: the corner right of the upper row's annotation
    # (above the right view's, in third angle), or the full height right of every
    # view. It takes whichever draws it larger, at the sheet's scale if it fits,
    # else at the largest STANDARD scale that does: a pictorial still states its
    # scale, and 1:1.17 is not one anybody can use.
    upper = "top" if third else "front"
    upper_w, upper_h = sizes[upper]
    upper_right = at[upper][0] + upper_w / 2 + need[upper]["right"] + 4.0
    corner_bottom = at[upper][1] - upper_h / 2
    if third:
        corner_bottom = max(corner_bottom, at["right"][1] + H / 2 + need["right"]["top"] + 4.0)
    rightmost = max(at[n][0] + sizes[n][0] / 2 + need[n]["right"] for n in sizes) + 4.0
    # The revision table, when there is one, owns the top-right corner.
    table_h = (len(sheet.revisions) + 1) * 6.0 + 6.0 if sheet.revisions else 0.0
    x_top, y_top = sheet.width - m - 6.0, sheet.height - m - 6.0 - table_h
    label_room = 12.0  # the pictorial's own label hangs under it
    regions = [(upper_right, corner_bottom + label_room), (rightmost, y_lo + label_room)]
    iso_w, iso_h = iso

    def fit_in(region) -> float:
        x0, y0 = region
        return min((x_top - x0) / iso_w if iso_w else s, (y_top - y0) / iso_h if iso_h else s)

    x_free, y_free = max(regions, key=fit_in)
    fit = fit_in((x_free, y_free))
    iso_scale = s if fit >= s else next((c for c in _STANDARD_SCALES if c <= max(fit, s / 5)),
                                        _STANDARD_SCALES[-1])
    w, h = iso_w * iso_scale, iso_h * iso_scale
    iso_at = (x_free + max(0.0, (x_top - x_free - w) / 2) + w / 2,
              y_free + max(0.0, (y_top - y_free - h) / 2) + h / 2)
    own = None if abs(iso_scale / s - 1) < 1e-9 else iso_scale
    # The label states the scale the pictorial was DRAWN at, not its ratio to the
    # sheet: at 2:1 a half-size iso is 1:1, and calling it "1:2" claimed a
    # reduction from full size that never happened.
    slots.append(("iso", iso_at, own, "ISOMETRIC" if own is None else f"ISOMETRIC {_scale_label(iso_scale)}"))
    return slots


class _OffFrame(ValueError):
    """Views that run off the frame, with the largest standard scale that fits
    them (``fits``, None when none does)."""

    def __init__(self, message: str, fits: float | None) -> None:
        super().__init__(message)
        self.fits = fits


def _assert_views_fit(sheet: Sheet, placed: Sequence[tuple], *, index: int, groups: Sequence[tuple] = ()) -> None:
    """Refuse a sheet whose views run off the frame, naming the scale that fits.

    A part far larger than the paper still writes valid geometry -- out at
    x = 4284 on a 420 mm sheet -- and the render then crops to a near-empty page.
    Nothing downstream can tell that from a drawing of a small feature, so the
    script stops here, at the one place that knows both extents.
    """
    m = _MARGIN
    frame = (m, sheet.width - m, m, sheet.height - m)
    over = []
    for view, _proj, _bounds, _cx, _cy, box in placed:
        if box[0] < frame[0] or box[1] > frame[1] or box[2] < frame[2] or box[3] > frame[3]:
            over.append((view, box))
    if not over:
        return
    # Lay the sheet out again at each smaller standard scale and name the first that
    # actually fits. Dividing the overflow out instead -- usable width over the union
    # width -- treats the whole arrangement as if it scaled, and the room between
    # views and the annotation around them do not: three of four ordinary part
    # sizes then needed two refusals before a scale rendered, each naming another
    # that did not fit either.
    fits = next((candidate for candidate in _STANDARD_SCALES
                 if candidate < sheet.scale and _fits_at(sheet, placed, candidate, frame, groups)), None)
    names = ", ".join(sorted({view.name for view, _ in over}))
    remedy = (f"Use Sheet(scale={fits:g}) ({_scale_label(fits)}), a larger sheet size, or place the "
              "views closer." if fits is not None else
              f"No standard scale down to {_scale_label(_STANDARD_SCALES[-1])} fits this part on "
              f"{sheet.size}; use a larger sheet size, or fewer views.")
    raise _OffFrame(
        f"sheet {index} ({sheet.size}, scale {_scale_label(sheet.scale)}): the {names} view"
        f"{'s run' if len(over) > 1 else ' runs'} off the frame. {remedy}", fits)


def _fits_at(sheet: Sheet, placed: Sequence[tuple], candidate: float, frame, groups: Sequence[tuple]) -> bool:
    """Would every view sit inside the frame if the sheet were drawn at `candidate`?

    A standard arrangement is laid out again, because the views move when they
    shrink; ``groups`` carries each one's (views by name, size, gap, iso, room).
    A hand-placed view keeps its ``at=``, which is what would happen, and only
    its box shrinks about that point.
    """
    moved: dict[int, tuple[tuple[float, float], float]] = {}
    for by_name, shape, size, gap, iso, room in groups:
        for name, at, own, _label in _arrange_three_views(sheet, shape, size, gap, candidate, iso, room):
            if name in by_name:
                moved[id(by_name[name])] = (at, own or candidate)
    for view, _proj, bounds, _cx, _cy, _box in placed:
        at, scale = moved.get(id(view), (view.at, view.scale or candidate))
        half_w = (bounds[1] - bounds[0]) * scale / 2
        half_h = (bounds[3] - bounds[2]) * scale / 2
        if (at[0] - half_w < frame[0] or at[0] + half_w > frame[1]
                or at[1] - half_h < frame[2] or at[1] + half_h > frame[3]):
            return False
    return True


def _spans(a, b) -> str:
    """Whether a projected point pair reads as a horizontal or a vertical dimension."""
    return "h" if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else "v"


def _scale_label(scale: float, digits: str = "g") -> str:
    """"1:2", "2:1", "1:1". ``digits`` rounds a scale nobody chose, such as the
    one an isometric fitted itself to, to something a reader can take in."""
    if abs(scale - 1) < 1e-9:
        return "1:1"
    return f"1:{1 / scale:{digits}}" if scale < 1 else f"{scale:{digits}}:1"


#: Fallback width per character, as a multiple of cap height, for when the font
#: the renderer uses cannot be measured. Set at the wide end of what was
#: measured (0.70 for "+0.10", 0.89 for "ELECTRONICS ENCLOSURE BASE") so the
#: fallback overruns nothing.
_CHAR_WIDTH = 0.9
#: MTEXT's own control codes: a backslash, a letter, and everything to the ";".
_MTEXT_CODE = re.compile(r"\\([A-Za-z])([^;]*);")


@lru_cache(maxsize=8)
def _font(height: float):
    """The renderer's own font at a cap height, or None if it cannot be had.

    A constant width per character is wrong for every proportional font: the
    same ratio that fits "ELECTRONICS ENCLOSURE BASE" runs "+0.10" 25% over.
    ezdxf measures the glyphs it is about to draw, so ask it.
    """
    try:
        from ezdxf.fonts import fonts

        return fonts.make_font("txt.shx", height)
    except Exception:  # noqa: BLE001 - no font manager, no cache; fall back to a ratio
        return None


def _text_width(value: str, height: float) -> float:
    """How wide `value` prints at this cap height, in millimetres."""
    if not value:
        return 0.0
    # %%c, %%d and %%p each draw one glyph; measured as written they read three wide.
    value = value.replace("%%c", "Ø").replace("%%d", "°").replace("%%p", "±")
    font = _font(round(float(height), 4))
    if font is None:
        return len(value) * height * _CHAR_WIDTH
    try:
        return float(font.text_width(value))
    except Exception:  # noqa: BLE001 - an unmappable glyph is not worth a failed drawing
        return len(value) * height * _CHAR_WIDTH


def _mtext_extent(raw: str, height: float) -> tuple[float, float]:
    """The width and height of rendered MTEXT, from the glyphs it actually draws.

    A dimension's value lives as MTEXT markup, and the markup is not the text:
    a toleranced ``30`` is ``\\A0;30{\\H0.70x;±0.10}``, 15 characters of which 7
    draw nothing and 5 draw at 0.7 of the height. Counted raw at full height
    that estimated 37.8 mm of ink where 14 mm exists, and every chain-dimensioned
    toleranced row -- the commonest idiom in drafting -- reported an overlap.
    """
    lines: list[float] = []
    width = 0.0
    tallest = height
    factor = 1.0
    run: list[str] = []

    def flush() -> None:
        nonlocal width
        if run:
            width += _text_width("".join(run), height * factor)
            run.clear()

    index = 0
    while index < len(raw):
        char = raw[index]
        if char in "{}":
            index += 1
        elif char == "\\" and raw[index + 1:index + 2] in ("\\", "{", "}"):
            run.append(raw[index + 1])
            index += 2
        elif char == "\\" and raw[index + 1:index + 2] in ("P", "p"):
            flush()
            lines.append(width)
            width, tallest = 0.0, tallest + height * factor
            index += 2
        elif char == "\\" and (match := _MTEXT_CODE.match(raw, index)):
            code, body = match.group(1), match.group(2)
            flush()
            if code in "Hh":
                # \H0.70x; is relative to the current height, \H2.5; absolute.
                try:
                    value = float(body.rstrip("xX"))
                except ValueError:
                    value = 1.0
                factor = value if body[-1:].lower() == "x" else (value / height if height else 1.0)
            elif code in "Ss":
                # A stacked tolerance prints its halves one above the other, so
                # it is as wide as the wider half, not as wide as both.
                upper, _, lower = body.partition("^")
                # Charged at the height in force, not smaller again: the halves
                # draw at some fraction of it that varies by renderer, and a box
                # that errs wide misses no overlap.
                stacked = height * factor
                width += max(_text_width(upper.strip("^ "), stacked),
                             _text_width(lower.strip("^ "), stacked))
                tallest = max(tallest, 2 * stacked)
            index = match.end()
        elif raw.startswith("%%", index) and raw[index + 2:index + 3]:
            run.append("Ø")  # %%c, %%d and %%p each draw exactly one glyph
            index += 3
        else:
            run.append(char)
            index += 1
    flush()
    lines.append(width)
    return max(lines), tallest


#: The drawing symbols a callout prints, drawn as line work rather than set as
#: glyphs. Glyphs for them are a property of whatever font the machine resolves:
#: ⌴ and ⌵ are missing from Arial and DejaVu alike (an empty box where the
#: counterbore should be), and ezdxf fills the crossing strokes of Ø solid in
#: every font that has it. Drawn, they print the same on every machine.
_SYMBOLS = {"%%c": "diameter", "Ø": "diameter", "\u2300": "diameter", "\u21a7": "depth",
            "\u2334": "cbore", "\u2335": "csk"}
#: Each symbol's advance, as a multiple of the cap height.
_SYMBOL_ADVANCE = {"diameter": 1.0, "depth": 0.8, "cbore": 1.0, "csk": 1.0}


def _runs(value: str) -> list[tuple[str, str]]:
    """``value`` split into ("text", run) and ("symbol", kind) pieces."""
    out: list[tuple[str, str]] = []
    run: list[str] = []
    index = 0
    while index < len(value):
        token = next((t for t in _SYMBOLS if value.startswith(t, index)), None)
        if token is None:
            run.append(value[index])
            index += 1
            continue
        if run:
            out.append(("text", "".join(run)))
            run = []
        out.append(("symbol", _SYMBOLS[token]))
        index += len(token)
    if run:
        out.append(("text", "".join(run)))
    return out


def _ink_width(value: str, height: float) -> float:
    """How wide ``value`` prints with its symbols drawn: what a callout occupies."""
    return sum(_text_width(piece, height) if kind == "text" else _SYMBOL_ADVANCE[piece] * height
               for kind, piece in _runs(value))


def _symbol(kind: str, x: float, mid: float, h: float) -> list[tuple]:
    """One symbol as line work, its advance box starting at ``x`` and centred on
    ``mid``, in the proportions ASME Y14.5 and ISO 129 draw them: ``("circle",
    centre, radius)`` and ``("line", points)`` pieces."""
    y0 = mid - h / 2
    if kind == "diameter":
        centre, r = (x + 0.5 * h, mid), 0.38 * h
        dx, dy = 0.55 * h * math.cos(math.radians(60)), 0.55 * h * math.sin(math.radians(60))
        return [("circle", centre, r), ("line", [(centre[0] - dx, mid - dy), (centre[0] + dx, mid + dy)])]
    if kind == "depth":
        stem = x + 0.4 * h
        return [("line", [(stem, y0 + h), (stem, y0)]),
                ("line", [(stem - 0.22 * h, y0 + 0.4 * h), (stem, y0), (stem + 0.22 * h, y0 + 0.4 * h)]),
                ("line", [(x + 0.08 * h, y0), (x + 0.72 * h, y0)])]
    if kind == "cbore":
        return [("line", [(x + 0.12 * h, y0 + 0.75 * h), (x + 0.12 * h, y0), (x + 0.88 * h, y0),
                          (x + 0.88 * h, y0 + 0.75 * h)])]
    return [("line", [(x + 0.1 * h, y0 + 0.8 * h), (x + 0.5 * h, y0), (x + 0.9 * h, y0 + 0.8 * h)])]


def _draw_symbol(layout, kind: str, x: float, mid: float, h: float, layer: str, place=None) -> None:
    """Write :func:`_symbol`'s pieces into ``layout``, through ``place`` (a map from
    the symbol's own frame to the layout's) when the text it sits in is rotated."""
    place = place or (lambda p: p)
    # Stroked as heavy as the glyphs beside it, not at the layer's hairline.
    attribs = {"layer": layer, "lineweight": max(13, min(50, int(round(h * 10))))}
    for piece in _symbol(kind, x, mid, h):
        if piece[0] == "circle":
            layout.add_circle(place(piece[1]), piece[2], dxfattribs=attribs)
        else:
            layout.add_lwpolyline([place(p) for p in piece[1]], dxfattribs=attribs)


def _draw_dimension_symbols(doc, dimension, layer: str = "DIM") -> None:
    """A dimension's value prefixed with ⌀ (``text="%%c<>"``) gets the symbol drawn
    in its block, beside the number, instead of set as a glyph."""
    try:
        block = doc.blocks.get(dimension.dxf.geometry)
    except Exception:  # noqa: BLE001 - nothing rendered, nothing to draw
        return
    for entity in list(block):
        if entity.dxftype() != "MTEXT":
            continue
        raw = str(entity.text or "")
        head = re.match(r"((?:\\A\d;)?)(%%c|Ø)", raw)
        if not head:
            continue
        rest = raw[: head.start(2)] + raw[head.end(2):]
        h = float(entity.dxf.char_height)
        advance = _SYMBOL_ADVANCE["diameter"] * h
        width, _tall = _mtext_extent(rest, h)
        angle = math.radians(float(entity.dxf.rotation or 0.0))
        along, across = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
        insert = entity.dxf.insert

        def place(p, insert=insert, along=along, across=across):
            return (insert.x + p[0] * along[0] + p[1] * across[0], insert.y + p[0] * along[1] + p[1] * across[1])

        # The value was centred on the insert; symbol and number now share the space.
        _draw_symbol(block, "diameter", -(width + advance) / 2, 0.0, h, layer, place)
        entity.text = rest
        entity.dxf.insert = place((advance / 2, 0.0))


def _text_box(value: str, x: float, y: float, height: float, align) -> tuple[float, float, float, float]:
    """The rectangle a TEXT entity occupies, from its anchor and alignment."""
    width = _ink_width(value, height)
    name = getattr(align, "name", str(align)).upper()
    if "CENTER" in name and "LEFT" not in name and "RIGHT" not in name:
        x0 = x - width / 2
    elif "RIGHT" in name:
        x0 = x - width
    else:
        x0 = x
    if "TOP" in name:
        y0 = y - height
    elif "MIDDLE" in name:
        y0 = y - height / 2
    else:
        y0 = y
    return (x0, y0, x0 + width, y0 + height)


#: Where each standard view's opposite stands, for "call it out there instead".
_OPPOSITE = {"top": "bottom", "bottom": "top", "front": "back", "back": "front",
             "right": "left", "left": "right", "iso": "iso"}
#: Model millimetres within which a point a callout was given and a feature's
#: projected centre are the same place.
_SAME_PLACE = 0.05
#: How far a centre line runs past the feature it marks, in sheet millimetres.
_CENTRE_OVERSHOOT = 3.0
#: What a cutting plane's end takes past the view it crosses: the line's overshoot
#: and the letter beside it.
_PLANE_ROOM = 12.0
#: The most a detail's circle is drawn across when its scale is left to the sheet.
_DETAIL_SIZE = 60.0
_SIDES = ("top", "bottom", "left", "right")


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _near(p, q, tol: float = _SAME_PLACE) -> bool:
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def _where(p) -> str:
    return "(" + ", ".join(_fmt(v) for v in p) + ")"


def _shown(text: str) -> str:
    """Callout text as a message prints it: the diameter sign, not its DXF escape."""
    return text.replace("%%c", "⌀")


def _faces_viewer(hole, look) -> bool:
    """Whether a view sees a hole's mouth: its axis runs into the material away
    from the viewer, or it is a plain through hole, which reads the same from
    either end. A counterbore on the far side is not something this view shows."""
    return _dot(hole.axis, look) < 0 or (hole.thru and not hole.cbore and not hole.csk)


@dataclass
class _Features:
    """What a drawing reads off one part, once however many views show it."""

    holes: list
    slots: list
    circles: list

    def pcd(self, members) -> float | None:
        """The bolt circle's diameter when these holes are exactly one bolt circle."""
        mouths = {tuple(round(c, 6) for c in h.mouth) for h in members}
        for circle in self.circles:
            if {tuple(round(c, 6) for c in m) for m in circle.mouths} == mouths:
                return circle.diameter
        return None


def _hole_spec(hole, count: int, thread: str | None = None, label: str | None = None,
               pcd: float | None = None) -> dict:
    return {"diameter": hole.diameter, "depth": hole.depth, "thru": hole.thru, "cbore": hole.cbore,
            "csk": hole.csk, "far_cbore": hole.far_cbore, "far_csk": hole.far_csk, "count": count,
            "thread": thread, "label": label, "pcd": pcd}


def _slot_spec(slot, count: int, label: str | None = None) -> dict:
    return {"slot": True, "width": slot.width, "length": slot.length, "thru": slot.thru, "depth": slot.depth,
            "cbore": slot.cbore, "count": count, "label": label}


def _slot_faces_viewer(slot, look) -> bool:
    return _dot(slot.axis, look) < 0 or (slot.thru and not slot.cbore)


def _outer_radius(spec: dict) -> float:
    """Where a callout's leader ends: on the outermost circle the hole shows, so the
    arrow does not cross a counterbore to reach the bore inside it; on a slot,
    the arc of its end."""
    if spec.get("slot"):
        return (spec.get("cbore") or (spec["width"],))[0] / 2
    return max(spec["diameter"], (spec.get("cbore") or (0.0,))[0], (spec.get("csk") or (0.0,))[0]) / 2


def _radii_at(proj, target, *, closed_only: bool) -> list[float]:
    """The radii of the circles (and, unless ``closed_only``, arcs) a view draws
    centred on ``target``, in model millimetres."""
    from build123d import GeomType

    radii: set[float] = set()
    for edge in list(proj.visible) + list(proj.hidden):
        if edge.geom_type != GeomType.CIRCLE or (closed_only and not edge.is_closed):
            continue
        if _near((edge.arc_center.X, edge.arc_center.Y), target):
            radii.add(round(edge.radius, 4))
    return sorted(radii)


def _callout_value(dim: "_Dim") -> str:
    if dim.kind in ("hole", "slot"):
        return hole_callout_text(dim.hole, tol=dim.tol, fit=dim.fit)
    if dim.text:
        return dim.text
    return f"%%c{_fmt(2 * dim.radius)}" if dim.kind == "diameter" else f"R{_fmt(dim.radius)}"


def _holes_hint(view: View, proj, seen, look) -> str:
    mine = [h for h in seen if _faces_viewer(h, look)]
    if not mine:
        return ("This view looks down no hole; a hole is called out in the view that sees it as a circle "
                "and looks into its mouth.")
    listed = ", ".join(f"⌀{_fmt(h.diameter)} at {_where(h.mouth)}" for h in mine[:6])
    return f"The holes it looks down open at {listed}{' ...' if len(mine) > 6 else ''}; view.holes() calls out every one."


def _resolve_view(view: View, proj, bounds, part_features, warnings: list | None, cut=None) -> list["_Dim"]:
    """The view's annotation with every size the part decides filled in from the
    part, on copies: a hole callout's diameter, depth, counterbore, countersink and
    count, a diameter or radius callout's value, and ``holes()`` expanded into one
    callout per kind of hole. Anything the author typed is checked on the way."""
    import dataclasses

    look = _look(view)
    seen_cache: tuple | None = None

    def kept(feature, run: float) -> bool:
        """A section draws only the half beyond its plane: a hole or slot wholly in
        the half taken away is not on it. A detail draws only what its circle holds."""
        if view._detail is not None:
            centre, radius = view._detail[1], view._detail[2]
            if math.dist(proj.point(feature.mouth), proj.point(centre)) > radius + 1e-6:
                return False
        if view._break is not None:
            # Taken out with the stretch a broken view leaves out.
            axis, lo, hi = view._break
            if lo < feature.mouth[axis] < hi:
                return False
        if cut is None:
            return True
        far = tuple(m + a * run for m, a in zip(feature.mouth, feature.axis))
        return min(_dot(tuple(e - c for e, c in zip(end, cut[2])), look) for end in (feature.mouth, far)) <= 1e-6

    def seen() -> tuple:
        nonlocal seen_cache
        if seen_cache is None:
            features = part_features(view.shape)
            seen_cache = (
                [h for h in features.holes if abs(_dot(h.axis, look)) > 1 - 1e-6 and kept(h, h.length)],
                [sl for sl in features.slots if abs(_dot(sl.axis, look)) > 1 - 1e-6 and kept(sl, sl.run)],
                features,
            )
        return seen_cache

    out: list[_Dim] = []
    for index, dim in enumerate(view._dims):
        if dim.kind == "hole":
            holes, slots, features = seen()
            resolved = [_resolve_hole(view, proj, dim, holes, look, features, slots)]
        elif dim.kind == "slot":
            _holes, slots, _features = seen()
            resolved = [_resolve_slot(view, proj, bounds, dim, slots, look)]
        elif dim.kind == "holes":
            holes, slots, features = seen()
            resolved = _expand_holes(view, proj, bounds, dim, holes, look, warnings, features, slots)
        elif dim.kind in ("diameter", "radius"):
            resolved = [_resolve_round(view, proj, dim)]
        else:
            resolved = [dataclasses.replace(dim)]
        for item in resolved:
            item.index = index
        out.extend(resolved)
    return out


def _resolve_hole(view: View, proj, dim: "_Dim", seen, look, features=None, slots=()) -> "_Dim":
    import dataclasses

    given, thread, label = dim.hole["given"], dim.hole["thread"], dim.hole["label"]
    call = f"{view.name}.hole({_where(dim.p1)})"
    target = proj.point(dim.p1)
    here = [h for h in seen if _near(proj.point(h.mouth), target)]
    if not here:
        if given["diameter"] is None and any(_near(proj.point(p), target) for sl in slots
                                             for p in (sl.mouth, *sl.ends)):
            raise ValueError(f"{call}: that is a slot, not a hole; call it out with "
                             f"{view.name}.slot({_where(dim.p1)}).")
        if given["diameter"] is None:
            raise ValueError(f"{call}: no hole runs along the {view.name} view's line of sight there. "
                             + _holes_hint(view, proj, seen, look))
        # A bore the reader does not recognise as a hole can still be stated, but
        # only over a circle that is really there.
        radii = _radii_at(proj, target, closed_only=True)
        if not any(abs(2 * r - given["diameter"]) <= 0.01 for r in radii):
            shown = ", ".join("⌀" + _fmt(2 * r) for r in radii)
            raise ValueError(f"{call}: the {view.name} view shows no ⌀{_fmt(given['diameter'])} circle there"
                             f"{f' (it shows {shown})' if radii else ''}, so the callout would point at a hole "
                             "the part does not have.")
        spec = {"diameter": given["diameter"], "depth": given["depth"], "thru": bool(given["thru"]),
                "cbore": given["cbore"], "csk": given["csk"], "count": given["count"], "thread": thread,
                "label": label}
        return dataclasses.replace(dim, hole=spec, radius=_outer_radius(spec))
    # Two holes on one line (a clevis) both match; the one whose mouth this view
    # looks into, nearest the viewer, is the one it calls out.
    here.sort(key=lambda h: (not _faces_viewer(h, look), -_dot(h.mouth, look)))
    hole = here[0]
    if not _faces_viewer(hole, look):
        raise ValueError(f"{call}: that hole opens on the far side of the part. Call it out in the "
                         f"{_OPPOSITE[view.name]} view, which looks into it.")
    same = [h for h in seen if h.signature() == hole.signature() and _faces_viewer(h, look)]
    problems = []
    if given["diameter"] is not None and thread is None and abs(given["diameter"] - hole.diameter) > 0.01:
        problems.append(f"diameter={_fmt(given['diameter'])}")
    if given["thru"] is not None and given["thru"] != hole.thru:
        problems.append(f"thru={given['thru']}")
    if given["depth"] is not None and (hole.thru or abs(given["depth"] - hole.depth) > 0.01):
        problems.append(f"depth={_fmt(given['depth'])}")
    if given["cbore"] is not None and (hole.cbore is None or any(
            abs(a - b) > 0.01 for a, b in zip(given["cbore"], hole.cbore))):
        problems.append(f"cbore=({_fmt(given['cbore'][0])}, {_fmt(given['cbore'][1])})")
    if given["csk"] is not None and (hole.csk is None or abs(given["csk"][0] - hole.csk[0]) > 0.01
                                     or abs(given["csk"][1] - hole.csk[1]) > 0.5):
        problems.append(f"csk=({_fmt(given['csk'][0])}, {_fmt(given['csk'][1])})")
    if given["count"] is not None and given["count"] != len(same):
        problems.append(f"count={given['count']}")
    if problems:
        raise ValueError(
            f"{call}: the part's hole reads {_shown(hole_callout_text(_hole_spec(hole, len(same))))}, but the "
            f"callout was given {', '.join(problems)}. Leave {'it' if len(problems) == 1 else 'them'} unset so "
            "the drawing states the part, or change the model."
        )
    spec = _hole_spec(hole, len(same), thread, label, features.pcd(same) if features else None)
    return dataclasses.replace(dim, hole=spec, radius=_outer_radius(spec), feature=hole, covers=tuple(same))


def _slot_end(proj, bounds, slot) -> tuple:
    """The end of a slot a callout's leader goes to: the one nearer the view's
    left or right edge, the short way out."""
    x0, x1 = bounds[0], bounds[1]
    return min(slot.ends, key=lambda e: (round(min(proj.point(e)[0] - x0, x1 - proj.point(e)[0]), 6),
                                         -round(proj.point(e)[1], 6)))


def _resolve_slot(view: View, proj, bounds, dim: "_Dim", seen, look) -> "_Dim":
    import dataclasses

    given, label = dim.hole["given"], dim.hole["label"]
    call = f"{view.name}.slot({_where(dim.p1)})"
    target = proj.point(dim.p1)
    here = [sl for sl in seen if any(_near(proj.point(p), target) for p in (sl.mouth, *sl.ends))]
    if not here:
        mine = [sl for sl in seen if _slot_faces_viewer(sl, look)]
        hint = (f"The slots it looks down are centred at {', '.join(_where(sl.mouth) for sl in mine[:6])}."
                if mine else "This view looks down no slot.")
        raise ValueError(f"{call}: no slot runs along the {view.name} view's line of sight there. {hint}")
    slot = here[0]
    if not _slot_faces_viewer(slot, look):
        raise ValueError(f"{call}: that slot opens on the far side of the part. Call it out in the "
                         f"{_OPPOSITE[view.name]} view, which looks into it.")
    same = [sl for sl in seen if sl.signature() == slot.signature() and _slot_faces_viewer(sl, look)]
    problems = []
    for name, value in (("width", slot.width), ("length", slot.length)):
        if given[name] is not None and abs(given[name] - value) > 0.01:
            problems.append(f"{name}={_fmt(given[name])}")
    if given["thru"] is not None and given["thru"] != slot.thru:
        problems.append(f"thru={given['thru']}")
    if given["depth"] is not None and (slot.thru or abs(given["depth"] - slot.depth) > 0.01):
        problems.append(f"depth={_fmt(given['depth'])}")
    if given["count"] is not None and given["count"] != len(same):
        problems.append(f"count={given['count']}")
    if problems:
        raise ValueError(
            f"{call}: the part's slot reads {_shown(hole_callout_text(_slot_spec(slot, len(same))))}, but the "
            f"callout was given {', '.join(problems)}. Leave {'it' if len(problems) == 1 else 'them'} unset so "
            "the drawing states the part, or change the model."
        )
    spec = _slot_spec(slot, len(same), label)
    end = _slot_end(proj, bounds, slot)
    return dataclasses.replace(dim, p1=end, hole=spec, radius=_outer_radius(spec), feature=slot, covers=tuple(same))


def _expand_holes(view: View, proj, bounds, dim: "_Dim", seen, look, warnings: list | None,
                  features=None, slots=()) -> list["_Dim"]:
    import dataclasses

    groups: dict[tuple, list] = {}
    for hole in seen:
        if _faces_viewer(hole, look):
            groups.setdefault(hole.signature(), []).append(hole)
    slot_groups: dict[tuple, list] = {}
    for slot in slots:
        if _slot_faces_viewer(slot, look):
            slot_groups.setdefault(slot.signature(), []).append(slot)
    if not groups and not slot_groups:
        if warnings is not None:
            warnings.append(f"{view.name}.holes(): the {view.name} view looks down no hole or slot, so it calls "
                            "nothing out.")
        return []
    x0, x1 = bounds[0], bounds[1]

    def short_way_out(point) -> tuple:
        p = proj.point(point)
        return (round(min(p[0] - x0, x1 - p[0]), 6), -round(p[1], 6))

    out = []
    for members in sorted(groups.values(), key=lambda g: (-g[0].diameter, g[0].signature())):
        hole = min(members, key=lambda h: short_way_out(h.mouth))
        spec = _hole_spec(hole, len(members), pcd=features.pcd(members) if features else None)
        out.append(dataclasses.replace(dim, kind="hole", p1=hole.mouth, hole=spec, radius=_outer_radius(spec),
                                       feature=hole, covers=tuple(members)))
    for members in sorted(slot_groups.values(), key=lambda g: g[0].signature()):
        slot = min(members, key=lambda sl: short_way_out(_slot_end(proj, bounds, sl)))
        spec = _slot_spec(slot, len(members))
        out.append(dataclasses.replace(dim, kind="slot", p1=_slot_end(proj, bounds, slot), hole=spec,
                                       radius=_outer_radius(spec), feature=slot, covers=tuple(members)))
    return out


def _resolve_round(view: View, proj, dim: "_Dim") -> "_Dim":
    import dataclasses

    closed = dim.kind == "diameter"
    what = "circle" if closed else "arc"
    target = proj.point(dim.p1)
    radii = _radii_at(proj, target, closed_only=closed)
    stated = "" if not dim.radius else f", size={_fmt(2 * dim.radius if closed else dim.radius)}"
    call = f"{view.name}.{dim.kind}({_where(dim.p1)}{stated})"
    shown = ", ".join(("⌀" + _fmt(2 * r)) if closed else ("R" + _fmt(r)) for r in radii)
    if dim.radius:
        if not any(abs(r - dim.radius) <= 0.01 for r in radii):
            raise ValueError(f"{call}: no {what} of that size is centred there in the {view.name} view"
                             f"{f'; it shows {shown}' if radii else ''}.")
        radius = dim.radius
    elif len(radii) == 1:
        radius = radii[0]
    elif not radii:
        raise ValueError(f"{call}: no {what} is centred there in the {view.name} view. A {dim.kind} is "
                         f"stated where the feature is seen as a {what}, at its centre.")
    else:
        raise ValueError(f"{call}: {len(radii)} {what}s share that centre ({shown}); pass size= to say "
                         "which one this states.")
    return dataclasses.replace(dim, radius=radius)


def _plan_view(view: View, proj, bounds, items: list["_Dim"], sheet: Sheet) -> dict:
    """Which side and row each dimension takes, and the room the view's annotation
    needs on each side, before anything is drawn.

    A dimension left unplaced goes on the side of the view its points are on --
    a hole pitch along the top edge above the view, a height on the right half
    to the right -- so its extension lines do not cross the part to reach the
    far side. On each side the shortest dimension sits nearest the view and the
    longest outermost, so no extension line crosses another dimension's line;
    ``overall()`` is the longest and outermost of all. The room is what
    :func:`_arrange_three_views` spaces the views by.
    """
    bx0, bx1, by0, by1 = bounds
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    th = sheet.text_height
    sv = view.scale or sheet.scale
    explicit = dict.fromkeys(_SIDES, 0)
    pending: dict[str, list] = {side: [] for side in _SIDES}
    for order, dim in enumerate(items):
        if dim.kind != "linear":
            continue
        a, b = proj.point(dim.p1), proj.point(dim.p2)
        horizontal = (dim.orientation or _spans(a, b)) == "h"
        if dim.offset is not None:
            dim.side = (("top" if dim.offset >= 0 else "bottom") if horizontal
                        else ("right" if dim.offset >= 0 else "left"))
            explicit[dim.side] = max(explicit[dim.side], int(abs(dim.offset) // _DIM_ROW))
            continue
        if horizontal:
            side, span = ("top" if (a[1] + b[1]) / 2 >= cy - 1e-9 else "bottom"), abs(b[0] - a[0])
        else:
            side, span = ("right" if (a[0] + b[0]) / 2 >= cx - 1e-9 else "left"), abs(b[1] - a[1])
        pending[side].append((round(span, 6), order, dim))
    rows: dict[str, int] = {}
    for side in _SIDES:
        for i, (_span, _order, dim) in enumerate(sorted(pending[side], key=lambda t: (t[0], t[1]))):
            dim.side, dim.row = side, explicit[side] + 1 + i
        rows[side] = explicit[side] + len(pending[side])
    overall = {}
    if "width" in view._overall:
        overall["top"] = rows["top"] + 1
    if "height" in view._overall:
        overall["left"] = rows["left"] + 1
    rows_out = {side: overall.get(side, rows[side]) for side in _SIDES}
    room = {side: (rows_out[side] * _DIM_ROW + th * 1.5) if rows_out[side] else 0.0 for side in _SIDES}
    rowed = dict(room)
    for dim in items:
        if dim.kind in ("hole", "slot", "diameter", "radius"):
            # The side a callout prefers is its hole's own half of the view, the
            # short way out, past every dimension row on that side.
            side = "right" if proj.point(dim.p1)[0] > cx + 1e-6 else "left"
            room[side] = max(room[side], rowed[side] + 10.0 + 8.0 + _ink_width(_callout_value(dim), th) + 2.0)
        elif dim.kind == "note":
            p = proj.point(dim.p1)
            width = _text_width(dim.text, th) + 4.0
            if dim.radius >= 0:
                room["right"] = max(room["right"], (p[0] - bx1) * sv + dim.radius + width)
            else:
                room["left"] = max(room["left"], (bx0 - p[0]) * sv - dim.radius + width)
            if dim.angle >= 0:
                room["top"] = max(room["top"], (p[1] - by1) * sv + dim.angle + th + 1.0)
            else:
                room["bottom"] = max(room["bottom"], (by0 - p[1]) * sv - dim.angle)
    if view._balloons:
        # A column of balloons each side of a tall view, a row above and below a wide one.
        for side in (("left", "right") if _balloon_axis(bounds) else ("bottom", "top")):
            room[side] += _BALLOON_LEAD + 2 * _BALLOON_R + 2.0
    room["bottom"] += 6.0 + 3.5 + 2.0  # the view's label hangs under everything below it
    return {"rows": rows, "overall": overall, "room": room}


def _axis_lines(view: View, proj, part_axes, to_sheet) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Centre lines for the turned features a view sees from the side: a shaft's
    axis, a hole drawn hidden through a plate. Axes that land on one drawn line
    (two holes one behind the other, a shaft's steps) merge into one line, which
    runs ``_CENTRE_OVERSHOOT`` past the feature at each end."""
    look = _look(view)
    lines: dict[tuple, list[list[float]]] = {}
    for axis in part_axes:
        d = tuple(e - s for e, s in zip(axis.end, axis.start))
        n = math.sqrt(_dot(d, d))
        if n < 1e-9 or abs(_dot(d, look)) / n > 1e-6:
            continue  # seen end-on, where the centre mark is the cross on its circle
        a, b = to_sheet(proj.point(axis.start)), to_sheet(proj.point(axis.end))
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
            ux, uy = -ux, -uy
        offset = -uy * a[0] + ux * a[1]
        t0, t1 = sorted((ux * a[0] + uy * a[1], ux * b[0] + uy * b[1]))
        lines.setdefault((round(ux, 6), round(uy, 6), round(offset, 3)), []).append([t0, t1])
    out = []
    for (ux, uy, offset), spans in sorted(lines.items()):
        merged: list[list[float]] = []
        for t0, t1 in sorted(spans):
            if merged and t0 <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], t1)
            else:
                merged.append([t0, t1])
        for t0, t1 in merged:
            def at(t: float) -> tuple[float, float]:
                return (ux * t - uy * offset, uy * t + ux * offset)

            out.append((at(t0 - _CENTRE_OVERSHOOT), at(t1 + _CENTRE_OVERSHOOT)))
    return out


def _end_on(view: View, proj, part_axes) -> list[tuple[tuple[float, float], float]]:
    """(centre, radius) of every turned feature a view looks straight down: its
    centre mark belongs there even when part of its circle is hidden behind
    something nearer, which leaves no closed circle to find it by."""
    look = _look(view)
    marks = []
    for axis in part_axes:
        d = tuple(e - s for e, s in zip(axis.end, axis.start))
        n = math.sqrt(_dot(d, d))
        if n > 1e-9 and abs(_dot(d, look)) / n > 1 - 1e-6:
            c = proj.point(axis.start)
            marks.append(((round(c[0], 3), round(c[1], 3)), round(axis.radius, 3)))
    return marks


def _sheet_axis(proj, horizontal: bool) -> int | None:
    """The model axis (0, 1, 2 for X, Y, Z) a view draws along the sheet's
    horizontal or vertical, or None for a pictorial view that draws none."""
    component = 0 if horizontal else 1
    for index, image in enumerate(proj.m):
        if abs(abs(image[component]) - 1.0) < 1e-6 and abs(image[1 - component]) < 1e-6:
            return index
    return None


#: The title block's cells as (x, y, width, height), millimetres from its
#: bottom-left corner: ISO 7200's fields in the arrangement shops read -- what the
#: part is and its number across the top, what it is made of and the scale in the
#: middle, who drew it, in what unit and projection, along the bottom. A field the
#: author did not give stays an empty, captioned cell: a blank MATERIAL says the
#: drawing does not state one, where a missing cell says nothing at all.
_TITLE_CELLS = {
    "TITLE": (0.0, 20.0, 110.0, 20.0),
    "DWG NO.": (110.0, 30.0, 70.0, 10.0),
    "REV": (110.0, 20.0, 30.0, 10.0),
    "SHEET": (140.0, 20.0, 40.0, 10.0),
    "MATERIAL": (0.0, 10.0, 60.0, 10.0),
    "FINISH": (60.0, 10.0, 50.0, 10.0),
    "SCALE": (110.0, 10.0, 30.0, 10.0),
    "SIZE": (140.0, 10.0, 40.0, 10.0),
    "DRAWN": (0.0, 0.0, 40.0, 10.0),
    "DATE": (40.0, 0.0, 30.0, 10.0),
    "UNITS": (70.0, 0.0, 40.0, 10.0),
    "PROJECTION": (110.0, 0.0, 70.0, 10.0),
}
#: The grid between those cells, drawn as lines so no edge is written twice.
_TITLE_RULES = (
    ((0.0, 10.0), (180.0, 10.0)), ((0.0, 20.0), (180.0, 20.0)), ((110.0, 30.0), (180.0, 30.0)),
    ((110.0, 0.0), (110.0, 40.0)), ((60.0, 10.0), (60.0, 20.0)), ((40.0, 0.0), (40.0, 10.0)),
    ((70.0, 0.0), (70.0, 10.0)), ((140.0, 10.0), (140.0, 30.0)),
)
#: Cap height of a cell's caption, and the width the title itself may take.
_CAPTION_HEIGHT = 1.8
_TITLE_FIT = _TITLE_CELLS["TITLE"][2] - 6.0
#: ISO 5457 zone letters: I and O are left out, being read as 1 and 0.
_ZONE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
#: A parts list: its row height and its columns, which together span the title
#: block's width so the list stands on the block as one column of the sheet.
_LIST_ROW = 7.0
_LIST_COLUMNS = (("ITEM", 12.0), ("QTY", 12.0), ("DESCRIPTION", 68.0), ("PART NO.", 44.0), ("MATERIAL", 44.0))


def _list_room(sheet: Sheet) -> float:
    """The height a parts list may take above the title block: the frame, less
    the block, a row for the line saying where a long list continues, and air."""
    revisions = (len(sheet.revisions) + 1) * 6.0 + 4.0 if sheet.revisions else 0.0
    return sheet.height - 2 * _MARGIN - _TITLE_H - _LIST_ROW - 4.0 - revisions


def _list_height(sheet: Sheet) -> float:
    """How far a sheet's parts list rises above its title block, its caption row
    included; 0 without one."""
    if sheet._parts is None:
        return 0.0
    parts, first, last = sheet._parts
    partial = first > 1 or last < len(parts)
    return (last - first + 2) * _LIST_ROW + (_LIST_ROW if partial else 0.0)


def _draw_parts_list(msp, sheet: Sheet, text, continued: dict) -> None:
    """The parts list, standing on the title block: header row at the bottom,
    item numbers rising from it. ``continued`` says on which sheet the rest of a
    split list is, ``{"from": n, "to": m}``, either or both."""
    from ezdxf.enums import TextEntityAlignment as A

    parts, first, last = sheet._parts
    fields = {"DESCRIPTION": "description", "PART NO.": "part_number", "MATERIAL": "material"}
    for item in parts.items[first - 1:last]:
        for name, width in _LIST_COLUMNS:
            value = getattr(item, fields[name]) if name in fields else ""
            if value and _text_width(value, _MIN_TEXT_MM) > width - 3:
                raise ValueError(
                    f"item {item.number}'s {name} {value!r} does not fit the parts list's {name} column "
                    f"({width:.0f} mm) even at the smallest legible text, and a parts list cut short is wrong. "
                    f"Shorten it: parts.set({item.number}, {fields[name]}=...)."
                )
    x0, y0 = sheet.width - _MARGIN - _TITLE_W, _MARGIN + _TITLE_H
    rows = [tuple(name for name, _w in _LIST_COLUMNS)] + [
        (str(item.number), str(item.quantity), item.description, item.part_number, item.material)
        for item in parts.items[first - 1:last]]
    top = y0 + len(rows) * _LIST_ROW
    msp.add_lwpolyline([(x0, y0), (x0 + _TITLE_W, y0), (x0 + _TITLE_W, top), (x0, top)], close=True,
                       dxfattribs={"layer": "TITLE"})
    for r in range(1, len(rows)):
        msp.add_line((x0, y0 + r * _LIST_ROW), (x0 + _TITLE_W, y0 + r * _LIST_ROW), dxfattribs={"layer": "TITLE"})
    x = x0
    for c, (_name, width) in enumerate(_LIST_COLUMNS):
        if c:
            msp.add_line((x, y0), (x, top), dxfattribs={"layer": "TITLE"})
        for r, row in enumerate(rows):
            if not row[c]:
                continue
            mid = y0 + (r + 0.5) * _LIST_ROW
            if c < 2:  # the numbers, centred in their narrow columns
                text(row[c], x + width / 2, mid, _CAPTION_HEIGHT if r == 0 else 2.5, A.MIDDLE_CENTER, fit=width - 2)
            else:
                text(row[c], x + 1.5, mid, _CAPTION_HEIGHT if r == 0 else 2.5, A.MIDDLE_LEFT, fit=width - 3)
        x += width
    words = [f"CONTINUED FROM SHEET {continued['from']}" if "from" in continued else "",
             f"CONTINUED ON SHEET {continued['to']}" if "to" in continued else ""]
    if any(words):
        text("PARTS LIST, " + ", ".join(w for w in words if w), x0, top + 2.0, 2.5, A.BOTTOM_LEFT, fit=_TITLE_W)


def _draw_furniture(msp, sheet: Sheet, *, index: int, count: int, label: str, text,
                    continued: dict | None = None) -> None:
    """Frame, zone grid, title block, notes and any parts list: what makes a page a
    drawing sheet."""
    from ezdxf.enums import TextEntityAlignment as A

    W, H, m = sheet.width, sheet.height, _MARGIN
    msp.add_lwpolyline([(m, m), (W - m, m), (W - m, H - m), (m, H - m)], close=True, dxfattribs={"layer": "SHEET"})
    # Zones (ISO 5457): numbered columns along the top and bottom, lettered rows
    # down both sides, about 50 mm each and an even count, so a note can say
    # "see C4" and a reader finds it. The marks at the middle of each side run to
    # the paper's edge: they are the centring marks a scan or a reproduction is
    # aligned by.
    cols, rows = max(2, 2 * round(W / 100)), max(2, 2 * round(H / 100))
    for i in range(1, cols):
        x = m + i * (W - 2 * m) / cols
        reach = m if 2 * i == cols else 5.0
        msp.add_line((x, H - m), (x, H - m + reach), dxfattribs={"layer": "SHEET"})
        msp.add_line((x, m), (x, m - reach), dxfattribs={"layer": "SHEET"})
    for j in range(1, rows):
        y = m + j * (H - 2 * m) / rows
        reach = m if 2 * j == rows else 5.0
        msp.add_line((m, y), (m - reach, y), dxfattribs={"layer": "SHEET"})
        msp.add_line((W - m, y), (W - m + reach, y), dxfattribs={"layer": "SHEET"})
    for i in range(cols):
        x = m + (i + 0.5) * (W - 2 * m) / cols
        text(str(i + 1), x, H - m / 2, 3.0, A.MIDDLE_CENTER)
        text(str(i + 1), x, m / 2, 3.0, A.MIDDLE_CENTER)
    for j in range(rows):
        y = H - m - (j + 0.5) * (H - 2 * m) / rows
        text(_ZONE_LETTERS[j], m / 2, y, 3.0, A.MIDDLE_CENTER)
        text(_ZONE_LETTERS[j], W - m / 2, y, 3.0, A.MIDDLE_CENTER)

    x0, y0 = W - m - _TITLE_W, m
    msp.add_lwpolyline([(x0, y0), (x0 + _TITLE_W, y0), (x0 + _TITLE_W, y0 + _TITLE_H), (x0, y0 + _TITLE_H)],
                       close=True, dxfattribs={"layer": "TITLE"})
    for (ax, ay), (bx, by) in _TITLE_RULES:
        msp.add_line((x0 + ax, y0 + ay), (x0 + bx, y0 + by), dxfattribs={"layer": "TITLE"})
    values = {
        "DWG NO.": (sheet.part_number, 3.5), "REV": (sheet.revision, 2.5), "SHEET": (f"{index} OF {count}", 2.5),
        "MATERIAL": (sheet.material, 2.5), "FINISH": (sheet.finish, 2.5),
        "SCALE": (_scale_label(sheet.scale), 2.5), "SIZE": (sheet.size, 2.5),
        "DRAWN": (sheet.author, 2.5), "DATE": (sheet.date, 2.5), "UNITS": (sheet.units.upper(), 2.5),
    }
    for name, (x, y, w, h) in _TITLE_CELLS.items():
        if name == "PROJECTION":
            continue  # the symbol is its own caption
        text(name, x0 + x + 1.2, y0 + y + h - 1.0, _CAPTION_HEIGHT, A.TOP_LEFT, fit=w - 2.4)
        if name in values and values[name][0]:
            value, height = values[name]
            text(str(value), x0 + x + 1.5, y0 + y + 1.6, height, A.BOTTOM_LEFT, fit=w - 3.0)
    tx, ty, _tw, th = _TITLE_CELLS["TITLE"]
    # A subtitle takes the line under the title, which moves up to make room.
    text(sheet.title, x0 + tx + 3.0, y0 + ty + th / 2 + (2.5 if sheet.subtitle else 1.0), 5.0, A.MIDDLE_LEFT,
         fit=_TITLE_FIT)
    if sheet.subtitle:
        text(sheet.subtitle, x0 + tx + 3.0, y0 + ty + 4.2, 2.5, A.BOTTOM_LEFT, fit=_TITLE_FIT)
    # The script that drew the sheet, so a print leads back to its source.
    text(label, x0 + tx + 3.0, y0 + ty + 1.4, _CAPTION_HEIGHT, A.BOTTOM_LEFT, fit=_TITLE_FIT)
    px, py, pw, ph = _TITLE_CELLS["PROJECTION"]
    right = _projection_symbol(msp, x0 + px + 4.0, y0 + py + ph / 2, first_angle=sheet.projection == "FIRST ANGLE")
    text(sheet.projection, right + 4.0, y0 + py + ph / 2, 2.5, A.MIDDLE_LEFT, fit=x0 + px + pw - right - 6.0)

    lines = sheet.note_lines()
    if sheet._parts is not None:
        # The notes share the strip above the title block with the parts list, so
        # each must end before the list begins.
        room = x0 - 4.0 - (m + _NOTE_INSET)
        for line in lines:
            if _text_width(line, _NOTE_HEIGHT) > room:
                raise ValueError(
                    f"note {line.strip()!r} runs under the parts list: beside it the {sheet.size} sheet leaves "
                    f"{round(room)} mm. Shorten the note or split it across two."
                )
        _draw_parts_list(msp, sheet, text, continued or {})
    for row, line in enumerate(lines):
        text(line, m + _NOTE_INSET, y0 + _TITLE_H + 4 + (len(lines) - 1 - row) * 5, _NOTE_HEIGHT,
             A.BOTTOM_LEFT, "NOTES")
    if sheet.revisions:
        # Revision table, top-right inside the frame: REV | DATE | DESCRIPTION.
        widths = (14.0, 26.0, 70.0)
        rw, rh = sum(widths), 6.0
        rx, ry = W - m - rw, H - m - rh
        table = [("REV", "DATE", "DESCRIPTION")] + [tuple(str(v) for v in row) for row in sheet.revisions]
        for r, row in enumerate(table):
            y = ry - r * rh
            msp.add_lwpolyline([(rx, y), (rx + rw, y), (rx + rw, y + rh), (rx, y + rh)], close=True,
                               dxfattribs={"layer": "TITLE"})
            x = rx
            for c, (width, value) in enumerate(zip(widths, row)):
                if c:
                    msp.add_line((x, y), (x, y + rh), dxfattribs={"layer": "TITLE"})
                text(value, x + 2, y + rh / 2, 2.5, A.MIDDLE_LEFT, fit=width - 4)
                x += width


def _projection_symbol(msp, x: float, y: float, *, first_angle: bool) -> float:
    """The ISO 5456-2 projection symbol with its left edge at ``x``, centred on
    ``y``; returns its right edge.

    It is a truncated cone drawn in the projection it names: its side view, wide
    end left, and its end view seen from the small end, where both circles show.
    Third angle places the view from the right on the right, so the circles sit
    right of the cone; first angle places it on the left. The cone is the same
    picture in both.
    """
    big, small, length, gap = 6.0, 3.0, 7.0, 3.0
    if first_angle:
        circles_x, cone_x = x + big / 2, x + big + gap
    else:
        cone_x, circles_x = x, x + length + gap + big / 2
    msp.add_lwpolyline([(cone_x, y - big / 2), (cone_x + length, y - small / 2), (cone_x + length, y + small / 2),
                        (cone_x, y + big / 2)], close=True, dxfattribs={"layer": "TITLE"})
    msp.add_circle((circles_x, y), big / 2, dxfattribs={"layer": "TITLE"})
    msp.add_circle((circles_x, y), small / 2, dxfattribs={"layer": "TITLE"})
    right = x + length + gap + big
    # Its axis, thin and on the title block's layer: it is part of the symbol, and
    # the CENTER layer holds the views' centre lines and nothing else.
    msp.add_line((x - 1.0, y), (right + 1.0, y), dxfattribs={"layer": "TITLE"})
    return right


#: For a section in each view, the views that see its cutting plane edge-on, in the
#: order a drawing shows it: a front section's plane on the top view, and so on.
_PLANE_SHOWN_ON = {
    "front": ("top", "bottom", "right", "left"), "back": ("top", "bottom", "right", "left"),
    "right": ("front", "top", "back", "bottom"), "left": ("front", "top", "back", "bottom"),
    "top": ("front", "right", "back", "left"), "bottom": ("front", "right", "back", "left"),
}


def _cut(view: View) -> tuple:
    """The part a section view draws: (the half beyond the plane, its cut faces,
    the point the plane passes through)."""
    from build123d import Compound, GeomType, Keep, Plane

    letter, through = view._section
    shape = view.shape
    point = through if through is not None else tuple(shape.bounding_box().center())
    look = _look(view)
    kept = shape.split(Plane(origin=point, z_dir=look), keep=Keep.BOTTOM)
    if isinstance(kept, (list, tuple)):
        kept = Compound(list(kept))
    faces = []
    for face in (kept.faces() if kept is not None else []):
        if face.geom_type != GeomType.PLANE:
            continue
        normal, centre = face.normal_at(), face.center()
        if (abs(abs(_dot((normal.X, normal.Y, normal.Z), look)) - 1) < 1e-6
                and abs(_dot((centre.X - point[0], centre.Y - point[1], centre.Z - point[2]), look)) < 1e-6):
            faces.append(face)
    if not faces:
        raise ValueError(
            f"{view.name}.section({letter!r}): the plane through {_where(point)} square to the {view.name} "
            "view's line of sight does not cut the part. Give through= a model point inside it."
        )
    return kept, faces, point


def _edge_points(edge) -> list[tuple[float, float]]:
    """A projected edge as points close enough to clip: a line's two ends, a circle
    or arc in short chords."""
    from build123d import GeomType

    if edge.geom_type == GeomType.LINE:
        n = 2
    elif edge.geom_type == GeomType.CIRCLE:
        # A full circle at three degrees a point; an arc, at most a half circle's worth.
        n = 121 if edge.is_closed else 61
    else:
        n = 48
    return [(float(v.X), float(v.Y)) for v in (edge.position_at(i / (n - 1)) for i in range(n))]


def _clip_runs(points, region) -> list[list[tuple[float, float]]]:
    """The runs of a polyline that lie inside ``region`` (a shapely shape)."""
    from shapely.geometry import LineString

    if len(points) < 2:
        return []
    clipped = LineString(points).intersection(region)
    runs: list[list[tuple[float, float]]] = []
    for part in getattr(clipped, "geoms", [clipped]):
        if part.geom_type == "LineString" and len(part.coords) >= 2:
            runs.append([tuple(c) for c in part.coords])
        elif part.geom_type == "MultiLineString":
            runs.extend([tuple(c) for c in line.coords] for line in part.geoms)
    return runs


#: A hole table's row height and its fixed columns; SIZE is as wide as its longest entry.
_TABLE_ROW = 6.0
_TABLE_COLUMNS = (("TAG", 12.0), ("X", 20.0), ("Y", 20.0))


def _hole_table_rows(view: View, proj, bounds, features, cut, items) -> dict:
    """The holes and slots a view tabulates, tagged and measured from its origin:
    ``{"rows": [...], "origin": (x, y) projected, "size": (w, h)}``. Each row is a
    dict of tag, x, y (model mm from the origin), size (the callout text without
    a count), the feature and its projected centre."""
    if any(dim.kind in ("hole", "slot", "holes") for dim in items):
        raise ValueError(f"the {view.name} view both tabulates its holes and calls them out; hole_table() lists "
                         "every hole the view looks down, so drop its holes(), hole() and slot() calls")
    look = _look(view)

    def kept(feature, run: float) -> bool:
        if not cut:
            return True
        far = tuple(m + a * run for m, a in zip(feature.mouth, feature.axis))
        return min(_dot(tuple(e - c for e, c in zip(end, cut[2])), look) for end in (feature.mouth, far)) <= 1e-6

    holes = [h for h in features.holes if abs(_dot(h.axis, look)) > 1 - 1e-6 and _faces_viewer(h, look)
             and kept(h, h.length)]
    slots = [sl for sl in features.slots if abs(_dot(sl.axis, look)) > 1 - 1e-6 and _slot_faces_viewer(sl, look)
             and kept(sl, sl.run)]
    if not holes and not slots:
        raise ValueError(f"{view.name}.hole_table(): the {view.name} view looks down no hole or slot")
    origin = proj.point(view._table[0]) if view._table[0] is not None else (bounds[0], bounds[2])
    kinds: dict[tuple, list] = {}
    for feature in holes:
        kinds.setdefault(feature.signature(), []).append(feature)
    order = sorted(kinds.values(), key=lambda g: (-g[0].diameter, g[0].signature()))
    slot_kinds: dict[tuple, list] = {}
    for feature in slots:
        slot_kinds.setdefault(feature.signature(), []).append(feature)
    order += sorted(slot_kinds.values(), key=lambda g: g[0].signature())
    if len(order) > len(_SECTION_LETTERS):
        raise ValueError(f"{view.name}.hole_table(): {len(order)} kinds of hole is more than the "
                         f"{len(_SECTION_LETTERS)} letters a table tags them with")
    def centre(feature):
        """Where a hole's axis or a slot's middle meets the view."""
        if hasattr(feature, "width"):
            return proj.point(tuple((a + b) / 2 for a, b in zip(*feature.ends)))
        return proj.point(feature.mouth)

    rows = []
    for letter, members in zip(_SECTION_LETTERS, order):
        is_slot = hasattr(members[0], "width")
        spec = _slot_spec(members[0], 1) if is_slot else _hole_spec(members[0], 1)
        size = hole_callout_text(spec)
        placed = sorted(((centre(f), f) for f in members),
                        key=lambda pf: (round(pf[0][0] - origin[0], 3), round(pf[0][1] - origin[1], 3)))
        for number, (point, feature) in enumerate(placed, start=1):
            rows.append({"tag": f"{letter}{number}", "x": point[0] - origin[0], "y": point[1] - origin[1],
                         "size": size, "feature": feature, "centre": point,
                         "radius": _outer_radius(spec) if not is_slot else feature.width / 2})
    width = sum(w for _n, w in _TABLE_COLUMNS) + max(28.0, max(_ink_width(r["size"], 2.5) for r in rows) + 6.0)
    return {"rows": rows, "origin": origin, "size": (width, (len(rows) + 1) * _TABLE_ROW), "view": view}


def _draw_hole_tags(msp, table: dict, to_sheet, sv: float, th: float, text) -> None:
    """Each tabulated hole's tag beside it, and the origin its X and Y run from."""
    from ezdxf.enums import TextEntityAlignment as A

    for row in table["rows"]:
        c, r = to_sheet(row["centre"]), row["radius"] * sv
        lean = r * 0.71 + 0.8
        text(row["tag"], c[0] + lean, c[1] + lean, 2.5, A.BOTTOM_LEFT, "DIM")
    o = to_sheet(table["origin"])
    for tip, name in (((o[0] + 10.0, o[1]), "X"), ((o[0], o[1] + 10.0), "Y")):
        msp.add_leader([tip, o], dxfattribs={"layer": "DIM"},
                       override={"dimasz": th * 0.7, "dimldrblk": "_CLOSEDFILLED"})
        text(name, tip[0] + (1.5 if name == "X" else 0.0), tip[1] + (1.5 if name == "Y" else 0.0), 2.5,
             A.MIDDLE_LEFT if name == "X" else A.BOTTOM_CENTER, "DIM")
    text("0,0", o[0] - 1.0, o[1] - 1.0, 2.5, A.TOP_RIGHT, "DIM")


def _draw_hole_table(msp, table: dict, text) -> None:
    """The table itself, header on top: TAG, X, Y, SIZE."""
    from ezdxf.enums import TextEntityAlignment as A

    x0, y1 = table["corner"]
    w, h = table["size"]
    columns = list(_TABLE_COLUMNS) + [("SIZE", w - sum(cw for _n, cw in _TABLE_COLUMNS))]
    msp.add_lwpolyline([(x0, y1), (x0 + w, y1), (x0 + w, y1 - h), (x0, y1 - h)], close=True,
                       dxfattribs={"layer": "TITLE"})
    for r in range(1, len(table["rows"]) + 1):
        msp.add_line((x0, y1 - r * _TABLE_ROW), (x0 + w, y1 - r * _TABLE_ROW), dxfattribs={"layer": "TITLE"})
    x = x0
    for c, (name, width) in enumerate(columns):
        if c:
            msp.add_line((x, y1), (x, y1 - h), dxfattribs={"layer": "TITLE"})
        text(name, x + width / 2, y1 - _TABLE_ROW / 2, _CAPTION_HEIGHT, A.MIDDLE_CENTER, fit=width - 2)
        for r, row in enumerate(table["rows"], start=1):
            value = (row["tag"], _fmt(row["x"]), _fmt(row["y"]), row["size"])[c]
            mid = y1 - (r + 0.5) * _TABLE_ROW
            if c == 3:
                text(value, x + 2.0, mid, 2.5, A.MIDDLE_LEFT, "NOTES")
            else:
                text(value, x + width / 2, mid, 2.5, A.MIDDLE_CENTER, fit=width - 2)
        x += width


def _place_box(sheet: Sheet, w: float, h: float, occupied: list, near) -> tuple[float, float] | None:
    """The top-left corner of the free ``w`` x ``h`` box nearest ``near``: inside
    the paper above the notes, title block and any parts list, clear of everything
    in ``occupied``."""
    m = _MARGIN
    note_rows = len(sheet.drawn_notes())
    notes_h = (note_rows * 5.0 + 8.0) if note_rows else 0.0
    table_h = (len(sheet.revisions) + 1) * 6.0 + 6.0 if sheet.revisions else 0.0
    list_h = _list_height(sheet) + 6.0 if sheet._parts is not None else 0.0
    x_lo, x_hi = m + 4.0, sheet.width - m - 4.0
    y_lo, y_hi = m + _TITLE_H + max(notes_h, list_h) + 4.0, sheet.height - m - 4.0 - table_h
    best = None
    y = y_hi
    while y - h >= y_lo:
        x = x_lo
        while x + w <= x_hi:
            box = (x - 4.0, x + w + 4.0, y - h - 4.0, y + 4.0)
            if not any(box[0] < o[1] and box[1] > o[0] and box[2] < o[3] and box[3] > o[2] for o in occupied):
                distance = math.hypot(x + w / 2 - near[0], y - h / 2 - near[1])
                if best is None or distance < best[0]:
                    best = (distance, (x, y))
            x += 2.0
        y -= 2.0
    return None if best is None else best[1]


def _place_detail(sheet: Sheet, size: float, room: dict, occupied: list, near) -> tuple[float, float] | None:
    """The free spot nearest ``near`` for a detail ``size`` mm across with its
    annotation ``room``: inside the paper above the notes and title block, clear
    of every view and its annotation."""
    m = _MARGIN
    note_rows = len(sheet.drawn_notes())
    notes_h = (note_rows * 5.0 + 8.0) if note_rows else 0.0
    table_h = (len(sheet.revisions) + 1) * 6.0 + 6.0 if sheet.revisions else 0.0
    x_lo, x_hi = m + 4.0, sheet.width - m - 4.0
    list_h = _list_height(sheet) + 6.0 if sheet._parts is not None else 0.0
    y_lo, y_hi = m + _TITLE_H + max(notes_h, list_h) + 4.0, sheet.height - m - 4.0 - table_h
    half = size / 2
    best = None
    step = 2.0
    y = y_hi - half - room["top"]
    while y - half - room["bottom"] >= y_lo:
        x = x_lo + half + room["left"]
        while x + half + room["right"] <= x_hi:
            box = (x - half - room["left"] - 4.0, x + half + room["right"] + 4.0,
                   y - half - room["bottom"] - 4.0, y + half + room["top"] + 4.0)
            if not any(box[0] < o[1] and box[1] > o[0] and box[2] < o[3] and box[3] > o[2] for o in occupied):
                distance = math.hypot(x - near[0], y - near[1])
                if best is None or distance < best[0]:
                    best = (distance, (x, y))
            x += step
        y -= step
    return None if best is None else best[1]


def _merge_centre_lines(msp) -> None:
    """One chain line where several land on one line and overlap: a row of holes'
    centre marks, a bore's mark, a cutting plane through them. Overlapping chain
    lines strike their dashes out of phase and print solid, which reads as an
    edge."""
    lines: dict[tuple, list] = {}
    for entity in list(msp.query("LINE[layer=='CENTER']")):
        a, b = entity.dxf.start, entity.dxf.end
        length = math.hypot(b.x - a.x, b.y - a.y)
        if length < 1e-9:
            continue
        ux, uy = (b.x - a.x) / length, (b.y - a.y) / length
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
            ux, uy = -ux, -uy
        offset = -uy * a.x + ux * a.y
        t0, t1 = sorted((ux * a.x + uy * a.y, ux * b.x + uy * b.y))
        lines.setdefault((round(ux, 6), round(uy, 6), round(offset, 4)), []).append((t0, t1, entity))
    for (ux, uy, offset), spans in lines.items():
        if len(spans) < 2:
            continue
        spans.sort(key=lambda s: (s[0], s[1]))
        merged: list[list] = []
        for t0, t1, entity in spans:
            if merged and t0 <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], t1)
                merged[-1][2].append(entity)
            else:
                merged.append([t0, t1, [entity]])
        for t0, t1, entities in merged:
            if len(entities) < 2:
                continue
            for entity in entities:
                msp.delete_entity(entity)
            msp.add_line((ux * t0 - uy * offset, uy * t0 + ux * offset), (ux * t1 - uy * offset, uy * t1 + ux * offset),
                         dxfattribs={"layer": "CENTER"})


def _model_to_sheet(proj, at, centre, scale, point) -> tuple[float, float]:
    """Where a model point lands on the sheet in a placed view."""
    x, y = proj.point(point)
    return (at[0] + (x - centre[0]) * scale, at[1] + (y - centre[1]) * scale)


#: The paper left between the two ends of a broken view.
_BREAK_GAP = 10.0


def _break_shift(brk: tuple, gap: float) -> Callable:
    """Where a model point lands in a broken view's shortened part: past the break
    it moves back by the length taken out, less ``gap`` (model mm); inside it, it
    is squeezed into the gap."""
    axis, lo, hi = brk

    def shift(p):
        q = list(p)
        if q[axis] >= hi:
            q[axis] -= (hi - lo) - gap
        elif q[axis] > lo:
            q[axis] = lo + (q[axis] - lo) * gap / (hi - lo)
        return tuple(q)

    return shift


def _broken_shape(shape, brk: tuple, gap: float):
    """The part with the stretch between the break's ends taken out and its far
    end moved up to ``gap`` (model mm) from its near one."""
    from build123d import Compound, Keep, Location, Plane, Vector

    axis, lo, hi = brk
    normal = Vector(*(1.0 if k == axis else 0.0 for k in range(3)))
    near = shape.split(Plane(origin=normal * lo, z_dir=normal), keep=Keep.BOTTOM)
    far = shape.split(Plane(origin=normal * hi, z_dir=normal), keep=Keep.TOP)
    far = far.moved(Location(normal * -((hi - lo) - gap)))
    return Compound([near, far])


def _broken_size(size, brk: tuple, scale: float):
    """A part's extents as a broken view draws them at ``scale``."""
    from build123d import Vector

    axis, lo, hi = brk
    shorter = [size.X, size.Y, size.Z]
    shorter[axis] -= (hi - lo) - _BREAK_GAP / scale
    return Vector(*shorter)


def _break_hides(shape, brk: tuple) -> bool:
    """Whether the part changes inside a break: the stretch taken out is not one
    section drawn long, so the break hides some of the part."""
    from build123d import Keep, Plane, Vector

    axis, lo, hi = brk
    normal = Vector(*(1.0 if k == axis else 0.0 for k in range(3)))
    middle = shape.split(Plane(origin=normal * lo, z_dir=normal), keep=Keep.TOP)
    middle = middle.split(Plane(origin=normal * hi, z_dir=normal), keep=Keep.BOTTOM)
    # The section at each end, and the mean section between: one section drawn
    # long has all three equal.
    ends = [sum(f.area for f in middle.faces() if abs(f.center().dot(normal) - at) < 1e-6) for at in (lo, hi)]
    mean = middle.volume / (hi - lo)
    tolerance = 1e-6 * max(ends[0], 1.0)
    return abs(ends[0] - ends[1]) > tolerance or abs(mean - ends[0]) > tolerance


def _choose_for_breaks(sheet: Sheet) -> None:
    """Settle a chosen size or scale before a sheet's broken views are projected,
    with the room three_views() assumes and the extents the breaks leave."""
    arranged = next((view for view in sheet.views if view._arranged is not None), None)
    if arranged is None:
        return
    size, gap, iso = arranged._arranged
    brk = next(view._break for view in sheet.views if view._break is not None)
    _choose_size_and_scale(sheet, arranged.shape, iso, {n: dict(_DEFAULT_ROOM) for n in ("top", "front", "right")},
                           gap, size=_broken_size(size, brk, sheet._scale()))


def _break_cuts(view: View, proj) -> list[tuple]:
    """A broken view's two cuts as projected lines: a point on each, and the unit
    direction across them (the image of the broken axis)."""
    axis, lo, hi = view._break
    origin = proj.point((0.0, 0.0, 0.0))
    unit = proj.point(tuple(1.0 if k == axis else 0.0 for k in range(3)))
    length = math.hypot(unit[0] - origin[0], unit[1] - origin[1]) or 1.0
    across = ((unit[0] - origin[0]) / length, (unit[1] - origin[1]) / length)
    return [(proj.point(tuple(at if k == axis else 0.0 for k in range(3))), across) for at in (lo, hi)]


def _on_cut(edge, cuts: list[tuple]) -> bool:
    """Whether a projected edge lies along one of those cuts."""
    points = [edge.position_at(t) for t in (0.0, 0.5, 1.0)]
    return any(all(abs((p.X - c[0]) * d[0] + (p.Y - c[1]) * d[1]) < 1e-5 for p in points) for c, d in cuts)


def _draw_break_lines(msp, view: View, proj, to_sheet) -> None:
    """A thin zigzag line across each end of a broken view's break (ISO 128-2,
    type 01.1), as long as the part's section there and a little over."""
    from build123d import Keep, Plane, Vector

    axis, lo, hi = view._break
    normal = Vector(*(1.0 if k == axis else 0.0 for k in range(3)))
    near = view.shape.split(Plane(origin=normal * lo, z_dir=normal), keep=Keep.BOTTOM)
    section = [f for f in near.faces() if abs(f.center().dot(normal) - lo) < 1e-6]
    if not section:
        return
    corners = []
    for face in section:
        box = face.bounding_box()
        corners += [(x, y, z) for x in (box.min.X, box.max.X) for y in (box.min.Y, box.max.Y)
                    for z in (box.min.Z, box.max.Z)]
    for at in (lo, hi):
        ends = [to_sheet(proj.point(tuple(at if k == axis else c[k] for k in range(3)))) for c in corners]
        start, finish = min(ends), max(ends)
        if math.dist(start, finish) < 1e-6:
            continue
        length = math.dist(start, finish)
        t = ((finish[0] - start[0]) / length, (finish[1] - start[1]) / length)
        d = (t[1], -t[0])
        mid = ((start[0] + finish[0]) / 2, (start[1] + finish[1]) / 2)

        def along(point, k: float, j: float = 0.0):
            return (point[0] + t[0] * k + d[0] * j, point[1] + t[1] * k + d[1] * j)

        msp.add_lwpolyline([along(start, -2.0), along(mid, -2.0), along(mid, -0.7, 2.5), along(mid, 0.7, -2.5),
                            along(mid, 2.0), along(finish, 2.0)], dxfattribs={"layer": "NOTES"})


def _bbox_bounds(shape, proj, raw: bool = False) -> tuple[float, float, float, float]:
    """A part's projected (x0, x1, y0, y1), from its bounding box's corners;
    ``raw`` maps them as the whole part, not a broken view's shortened one."""
    bb = shape.bounding_box()
    to = proj._raw_point if raw else proj.point
    points = [to((x, y, z)) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y)
              for z in (bb.min.Z, bb.max.Z)]
    return (min(p[0] for p in points), max(p[0] for p in points),
            min(p[1] for p in points), max(p[1] for p in points))


def _wire_points(wire) -> list[tuple[float, float, float]]:
    """A closed wire as points close enough together that a hatch fills its arcs."""
    count = max(24, min(720, int(wire.length / 0.5)))
    return [tuple(wire.position_at(i / count)) for i in range(count)]


def _draw_cutting_plane(msp, parent: tuple, point, look, letter: str, text, th: float) -> None:
    """ISO 128-40's cutting plane on the view that sees it edge-on: a thin chain line
    across the view, thick at its ends, with arrows in the direction the section is
    viewed and the section's letter at each."""
    from ezdxf.enums import TextEntityAlignment

    _view, model_to_sheet, box = parent
    parent_look = _look(_view)
    along = (parent_look[1] * look[2] - parent_look[2] * look[1], parent_look[2] * look[0] - parent_look[0] * look[2],
             parent_look[0] * look[1] - parent_look[1] * look[0])
    p0 = model_to_sheet(point)
    p1 = model_to_sheet(tuple(a + b for a, b in zip(point, along)))
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1.0
    u = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
    ts = [(x - p0[0]) * u[0] + (y - p0[1]) * u[1] for x in box[:2] for y in box[2:]]
    # Just past the view, inside the first dimension row on either side.
    a = (p0[0] + u[0] * (min(ts) - 4.0), p0[1] + u[1] * (min(ts) - 4.0))
    b = (p0[0] + u[0] * (max(ts) + 4.0), p0[1] + u[1] * (max(ts) + 4.0))
    msp.add_line(a, b, dxfattribs={"layer": "CENTER"})
    # The section is viewed looking AWAY from where its viewer stands.
    q = model_to_sheet(tuple(c - d for c, d in zip(point, look)))
    run = math.hypot(q[0] - p0[0], q[1] - p0[1]) or 1.0
    d = ((q[0] - p0[0]) / run, (q[1] - p0[1]) / run)
    for end, inward in ((a, u), (b, (-u[0], -u[1]))):
        # Thick at the ends, at the outline's weight, but not on VISIBLE: that layer
        # is the part's edges and nothing else.
        msp.add_line(end, (end[0] + inward[0] * 7.0, end[1] + inward[1] * 7.0),
                     dxfattribs={"layer": "NOTES", "lineweight": int(round(_LAYERS["VISIBLE"][2] * 100))})
        head = (end[0] + d[0] * 7.0, end[1] + d[1] * 7.0)
        msp.add_leader([head, end], dxfattribs={"layer": "DIM"},
                       override={"dimasz": th * 0.85, "dimldrblk": "_CLOSEDFILLED"})
        # The letter just past the end of the line, level with the middle of its
        # arrow: at the arrow's tip it sat on the extension lines that leave the
        # view's corners, and further out it reached the first dimension row.
        out, gap = (-inward[0], -inward[1]), (th + 1.5) / 2 + 1.0
        text(letter, end[0] + d[0] * 3.5 + out[0] * gap, end[1] + d[1] * 3.5 + out[1] * gap,
             th + 1.5, TextEntityAlignment.MIDDLE_CENTER, "NOTES")


def _render_sheet(sheet: Sheet, *, index: int, count: int, label: str, warnings: list | None = None,
                  facts: dict | None = None, continued: dict | None = None):
    """Build the ezdxf document for one sheet. Returns the document.

    A sheet that chose its own scale (a part sheet ``assembly_sheets`` made) and
    whose views, with the annotation they turned out to carry, run off the frame
    is drawn again at the largest standard scale that fits, rather than refused:
    the scale was the sheet's choice, not the author's. Only the drawing that
    succeeds reports anything.
    """
    if sheet._item is not None:
        item, whole = sheet._item
        sheet.title = item.description or f"ITEM {item.number}"
        sheet.material = item.material
        sheet.subtitle = f"ITEM {item.number}{f' (QTY {item.quantity})' if item.quantity > 1 else ''} OF {whole}"
    if sheet._chosen is not None:
        # A size or scale the author set after the sheet chose one is theirs.
        size_set, scale_set = sheet.size != sheet._chosen[0], sheet.scale != sheet._chosen[1]
        if size_set or scale_set:
            sheet._auto = (sheet._auto[0] and not size_set, sheet._auto[1] and not scale_set)
            sheet._fit = sheet._auto[1]
            sheet._chosen = None
    if not sheet._fit:
        return _draw_sheet(sheet, index=index, count=count, label=label, warnings=warnings, facts=facts,
                           continued=continued)
    while True:
        tried_warnings: list = []
        tried_facts: dict = {}
        try:
            doc = _draw_sheet(sheet, index=index, count=count, label=label, warnings=tried_warnings,
                              facts=tried_facts, continued=continued)
        except _OffFrame as exc:
            # A larger sheet first, when the sheet chose its size and has a larger
            # one to try at the scale it wanted; then a smaller scale.
            if sheet._auto[0] and _SIZES_SMALLEST_FIRST.index(sheet._size()) < len(_SIZES_CHOSEN) - 1:
                sheet._floor = _SIZES_SMALLEST_FIRST.index(sheet._size()) + 1
                if sheet._auto[1]:
                    # No larger than the scale that ran out of paper: the larger
                    # sheet is for room, not for a larger scale.
                    sheet._ceiling = min(sheet._ceiling or _PART_LARGEST, sheet._scale())
                continue
            if exc.fits is None or exc.fits >= sheet._scale():
                raise
            sheet.scale = sheet._ceiling = exc.fits
            continue
        if warnings is not None:
            warnings.extend(tried_warnings)
        if facts is not None:
            _merge_facts(facts, tried_facts)
        return doc


def _merge_facts(into: dict, more: dict) -> None:
    """Fold one sheet's facts into the drawing's: a part shown on two sheets is
    stated by both."""
    for key, record in more.items():
        if key not in into:
            into[key] = record
            continue
        have = into[key]
        for name, value in record.items():
            if isinstance(value, set):
                have[name] |= value
            elif isinstance(value, list):
                have[name].extend(value)


def _draw_sheet(sheet: Sheet, *, index: int, count: int, label: str, warnings: list | None = None,
                facts: dict | None = None, continued: dict | None = None):
    """Build the ezdxf document for one sheet at its scale. Returns the document.

    ``warnings`` collects anything the sheet renders but a reader should look
    at -- a dimension whose points miss the geometry, say. The render never
    stops for one: it is the PDF that answers whether the sheet is right.
    ``facts`` collects what the sheet states about each part (holes called out,
    values dimensioned), so the drawing can say what it leaves unstated.
    """
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    from cadgen._internal.drawing_features import axes as find_axes, bolt_circles, holes as find_holes, slots as find_slots

    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for name, (color, linetype, weight) in _LAYERS.items():
        aci = 7 if sheet.ink == "mono" and name != "HIDDEN" else color
        doc.layers.add(name, color=aci, linetype=linetype, lineweight=int(round(weight * 100)))
    dimstyle = _dimstyle(doc, sheet.text_height)
    W, th = sheet.width, sheet.text_height

    def text(value, x, y, height, align, layer="TITLE", fit: float | None = None):
        # ``fit`` is the width the text may occupy; longer text is set smaller
        # rather than run through a cell divider or off the sheet. Below the
        # smallest legible height the text is cut instead, with an ellipsis, so a
        # long title ends inside its cell rather than running over the next one.
        if fit is not None and value:
            width = _text_width(value, height)
            if width > fit:
                # 0.999 so the shrink lands inside the cell rather than exactly on
                # its edge, where the re-measure rounds over and cuts text that fits.
                height = max(_MIN_TEXT_MM, height * fit / width * 0.999)
                if _text_width(value, height) > fit:
                    # Below the smallest legible height, cut rather than overrun:
                    # a title that runs into the SCALE cell is worse than a short one.
                    while len(value) > 1 and _text_width(value[:-1] + "…", height) > fit:
                        value = value[:-1]
                    value = (value[:-1] + "…") if len(value) > 1 else value[:1]
        if layer in ("DIM", "NOTES") and value and any(kind == "symbol" for kind, _ in _runs(value)):
            symbols(value, x, y, height, align, layer)
            return None
        entity = msp.add_text(value, dxfattribs={"height": height, "layer": layer})
        entity.set_placement((x, y), align=align)
        if layer in ("DIM", "NOTES") and value:
            claim(value, _text_box(value, x, y, height, align))
        return entity

    def symbols(value, x, y, height, align, layer) -> None:
        """Text whose symbols are drawn: each run of plain text a TEXT entity,
        each symbol its line work, laid end to end where one TEXT would sit."""
        box = _text_box(value, x, y, height, align)
        cursor, mid = box[0], (box[1] + box[3]) / 2
        for kind, piece in _runs(value):
            if kind == "text":
                run = msp.add_text(piece, dxfattribs={"height": height, "layer": layer})
                run.set_placement((cursor, mid), align=TextEntityAlignment.MIDDLE_LEFT)
                cursor += _text_width(piece, height)
            else:
                _draw_symbol(msp, piece, cursor, mid, height, layer)
                cursor += _SYMBOL_ADVANCE[piece] * height
        claim(value, box)

    # Annotation already on the paper, as (what it says, its box). The layout
    # gives each view the room its annotation asks for, but a sheet squeezed for
    # paper, or one with views placed by hand, can still land one view's callouts
    # on another's. Nothing here moves them, because which of the two should give
    # way is the author's call; it says so instead of leaving it to the print.
    claimed: list[tuple[str, tuple[float, float, float, float]]] = []

    def claim_rendered(dimension) -> None:
        """A dimension's VALUE lives as MTEXT inside its rendered block, not as
        TEXT on the sheet, so it is registered from there once it is drawn."""
        try:
            block = doc.blocks.get(dimension.dxf.geometry)
        except Exception:  # noqa: BLE001 - a dimension with no block draws nothing to collide with
            return
        for entity in block:
            if entity.dxftype() != "MTEXT":
                continue
            value = str(entity.text or "")
            height = float(entity.dxf.char_height or th)
            width, tall = _mtext_extent(value, height)
            # A vertical dimension's value is turned with its line: its box is too.
            turn = math.radians(float(entity.dxf.get("rotation", 0.0) or 0.0))
            width, tall = (abs(width * math.cos(turn)) + abs(tall * math.sin(turn)),
                           abs(width * math.sin(turn)) + abs(tall * math.cos(turn)))
            insert = entity.dxf.insert
            claim(value, (insert.x - width / 2, insert.y - tall / 2, insert.x + width / 2, insert.y + tall / 2))

    def claim(value: str, box: tuple[float, float, float, float]) -> None:
        for other, taken in claimed:
            if (box[0] < taken[2] and box[2] > taken[0] and box[1] < taken[3] and box[3] > taken[1]):
                if warnings is not None:
                    warnings.append(
                        f"annotation overlaps: {value.strip()!r} is printed over {other.strip()!r} "
                        f"around ({box[0]:.0f}, {box[1]:.0f}). Give the view more room "
                        "(three_views(gap=...), a larger sheet), or place one of them with offset=."
                    )
                break
        claimed.append((value, box))

    # What the part's faces say, read once per part however many views show it.
    found_features: dict[int, _Features] = {}
    found_axes: dict[int, list] = {}

    def part_features(shape) -> _Features:
        if id(shape) not in found_features:
            holes = find_holes(shape)
            found_features[id(shape)] = _Features(holes, find_slots(shape), bolt_circles(shape, holes))
        return found_features[id(shape)]

    def part_axes(shape) -> list:
        if id(shape) not in found_axes:
            found_axes[id(shape)] = find_axes(shape)
        return found_axes[id(shape)]

    # Every view is projected, its callouts read off the part and its annotation
    # planned before anything is placed, so the layout knows what each view carries.
    sheet._size()
    if any(sheet._auto) and any(view._break is not None for view in sheet.views):
        # A break leaves a fixed gap of paper, so its views are drawn at the scale
        # the sheet settles on now, not at the one three_views() guessed.
        _choose_for_breaks(sheet)
    s = sheet._scale()
    work = []
    tables: dict[int, dict] = {}
    outlines: dict[int, list] = {}
    hidden_by_breaks: set = set()
    cuts: dict[int, tuple] = {}
    checked: set[int] = set()
    # The assemblies this sheet draws as assemblies: the one its parts list was
    # read from, and any a view balloons. Many solids there are the point.
    assemblies = {id(parts.assembly) for view in sheet.views for parts in view._balloons}
    if sheet._parts is not None:
        assemblies.add(id(sheet._parts[0].assembly))
    for view in sheet.views:
        if view._detail is not None:
            # A detail shows what its parent shows when the sheet renders, so a
            # section() made after detail() still reaches it.
            parent = view._detail[0]
            view._section, view.hidden, view.centre_marks = parent._section, parent.hidden, parent.centre_marks
        if view._balloons:
            _refuse_balloons_on(view)
        if id(view.shape) not in checked:
            checked.add(id(view.shape))
            solids = len(view.shape.solids()) if hasattr(view.shape, "solids") else 1
            if solids > 1 and id(view.shape) not in assemblies and warnings is not None:
                warnings.append(
                    f"the part in the {view.name} view is {solids} separate solids, and a drawing documents one "
                    "part. A cut that runs right through the model splits it; check the model, or draw each "
                    "solid on its own sheet. An assembly is drawn with a parts list and balloons: "
                    "assembly_sheets(parts_list(cadgen.read_scene(path)), ...)."
                )
        cut = _cut(view) if view._section else None
        draw = cut[0] if cut else None
        if view._break is not None:
            # A broken view draws the part shortened, and maps every model point
            # given to it onto the shortened part.
            gap = _BREAK_GAP / (view.scale or s)
            draw = _broken_shape(view.shape, view._break, gap)
            if (id(view.shape), view._break) not in hidden_by_breaks:
                hidden_by_breaks.add((id(view.shape), view._break))
                if _break_hides(view.shape, view._break) and warnings is not None:
                    axis, lo, hi = view._break
                    warnings.append(
                        f"the break from {'XYZ'[axis]} = {_fmt(lo)} to {_fmt(hi)} hides some of the part: it is not "
                        "the same section all along that stretch. Move the break to where the part does not change."
                    )
        proj = _Projection(view.shape, _dirs(view), draw=draw)
        if view._break is not None:
            proj.shift = _break_shift(view._break, gap)
            # Each end of the break is bounded by its break line, not by the edge
            # of the cut.
            break_cuts = _break_cuts(view, proj)
            proj.visible = [e for e in proj.visible if not _on_cut(e, break_cuts)]
            proj.hidden = [e for e in proj.hidden if not _on_cut(e, break_cuts)]
        bounds = _edges_bounds(list(proj.visible) + (list(proj.hidden) if view.hidden else []))
        if not bounds:
            continue
        if cut:
            cuts[id(view)] = cut
        if view._detail is not None:
            # A detail is the circle round its centre, whatever falls inside it.
            c2, r = proj.point(view._detail[1]), view._detail[2]
            bounds, centre = (c2[0] - r, c2[0] + r, c2[1] - r, c2[1] + r), c2
        elif view._aux is not None and view._aux[4] is not None:
            # A partial auxiliary view is its face's outline, whatever lies within it.
            ring = [proj.point(p) for p in view._aux[4]]
            outlines[id(view)] = ring
            bounds = (min(x for x, _ in ring), max(x for x, _ in ring), min(y for _, y in ring),
                      max(y for _, y in ring))
            centre = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2)
        elif cut:
            # Centred on the WHOLE part, so the section lines up with the views
            # beside it even when the half it keeps is not symmetric.
            corners = _bbox_bounds(view.shape, proj)
            centre = ((corners[0] + corners[1]) / 2, (corners[2] + corners[3]) / 2)
        else:
            centre = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2)
        items = _resolve_view(view, proj, bounds, part_features, warnings, cut)
        if view._table is not None:
            tables[id(view)] = _hole_table_rows(view, proj, bounds, part_features(view.shape), cut, items)
        work.append((view, proj, bounds, items, _plan_view(view, proj, bounds, items, sheet), centre))

    # A cutting plane runs out past the view it is drawn on, with an arrow and a
    # letter at each end: that view needs room on those two sides, or the letter
    # lands on its label.
    plane_sides: dict[int, set] = {}
    projections = {id(item[0]): item[1] for item in work}
    for view in sheet.views:
        if view._section is None or view._detail is not None:
            continue
        look = _look(view)
        parent = next((other for name in _PLANE_SHOWN_ON[view.name] for other in sheet.views
                       if other.name == name and other.shape is view.shape and other._section is None
                       and other._detail is None and id(other) in projections), None)
        if parent is None:
            continue
        parent_look = _look(parent)
        along = (parent_look[1] * look[2] - parent_look[2] * look[1], parent_look[2] * look[0] - parent_look[0] * look[2],
                 parent_look[0] * look[1] - parent_look[1] * look[0])
        image = [sum(row[k] * a for row, a in zip(projections[id(parent)].m, along)) for k in (0, 1)]
        plane_sides.setdefault(id(parent), set()).update(
            ("left", "right") if abs(image[0]) >= abs(image[1]) else ("top", "bottom"))
    for view, _proj, _bounds, _items, plan, _centre in work:
        for side in plane_sides.get(id(view), ()):
            plan["room"][side] = max(plan["room"][side], _PLANE_ROOM + (11.5 if side == "bottom" else 0.0))

    # A sheet that chooses its own size or scale chooses again now that each
    # view's annotation is known: the choice three_views() made assumed two rows
    # of dimensions round every view.
    if any(sheet._auto) and not any(view._break is not None for view in sheet.views):
        groups_seen = {id(view._arranged): view for view, *_rest in work if view._arranged is not None}
        if len(groups_seen) == 1:
            first = next(iter(groups_seen.values()))
            rooms = {view.name: plan["room"] for view, _proj, _bounds, _items, plan, _centre in work
                     if view._arranged is first._arranged}
            size, gap, iso = first._arranged
            brk = next((view._break for view, *_rest in work if view._arranged is first._arranged
                        and view._break is not None), None)
            _choose_size_and_scale(sheet, first.shape, iso, rooms, gap,
                                   size=_broken_size(size, brk, s) if brk is not None else None)
            s = sheet._scale()
    _draw_furniture(msp, sheet, index=index, count=count, label=label, text=text, continued=continued)

    # A standard arrangement is laid out again from the room its views' annotation
    # takes; a view placed by hand stays where its author put it.
    arranged: dict[int, tuple] = {}
    for view, _proj, _bounds, _items, plan, _centre in work:
        if view._arranged is not None:
            arranged.setdefault(id(view._arranged), (view._arranged, {}, {}))
            arranged[id(view._arranged)][1][view.name] = view
            arranged[id(view._arranged)][2][view.name] = plan["room"]
    groups = []
    for (size, gap, iso), by_name, room in arranged.values():
        shape = next(iter(by_name.values())).shape
        brk = next((view._break for view in by_name.values() if view._break is not None), None)
        if brk is not None:
            size = _broken_size(size, brk, s)
        over: list = []
        for name, at, own, slot_label in _arrange_three_views(sheet, shape, size, gap, s, iso, room, over):
            if name in by_name:
                view = by_name[name]
                view.at = at
                if name == "iso" and (view._auto is None or (view.label, view.scale) == view._auto):
                    view.scale, view.label = own, slot_label
                    view._auto = (slot_label, own)
        groups.append((by_name, shape, size, gap, iso, room))
        if gap is None and max(over) > _AIR and warnings is not None:
            # The views were squeezed together past the air between them, so one
            # view's annotation now crowds the next. Say what gives them the room.
            def roomy(scale: float) -> bool:
                over_at: list = []
                _arrange_three_views(sheet, shape, size, None, scale, iso, room, over_at)
                return max(over_at) <= 0

            roomier = next((name for name in sorted(SHEET_SIZES, key=lambda n: SHEET_SIZES[n][0])
                            if SHEET_SIZES[name][0] > sheet.width), None)
            smaller = next((c for c in _STANDARD_SCALES if c < s and roomy(c)), None)
            remedies = [f'Sheet("{roomier}")' if roomier else None,
                        f"Sheet(scale={smaller:g}) ({_scale_label(smaller)})" if smaller else None]
            ask = max(((name, side, value) for name, sides in room.items() for side, value in sides.items()),
                      key=lambda t: t[2])
            warnings.append(
                f"views crowded: their dimensions and callouts need {max(over):.0f} mm more than {sheet.size} "
                f"leaves at {_scale_label(s)}, so the space between views was narrowed and one view's "
                f"annotation can crowd the next. The largest ask is the {ask[0]} view's {ask[1]} side "
                f"({ask[2]:.0f} mm of dimensions, callouts and notes). "
                f"{' or '.join(r for r in remedies if r) or 'Fewer views'} gives them room; or move that "
                "annotation to a view with space to spare."
            )

    # Details go in the free paper nearest their parent, once everything else has
    # its place.
    occupied = []
    for view, _proj, bounds, _items, plan, (cx, cy) in work:
        if (view._detail is not None and view._detail[4]) or (view._aux is not None and view._aux[3]):
            continue
        sv = view.scale or s
        room = plan["room"]
        occupied.append((view.at[0] + (bounds[0] - cx) * sv - room["left"], view.at[0] + (bounds[1] - cx) * sv + room["right"],
                         view.at[1] + (bounds[2] - cy) * sv - room["bottom"], view.at[1] + (bounds[3] - cy) * sv + room["top"]))
    centres = {id(item[0]): (item[1], item[5]) for item in work}
    for view in sheet.views:
        # Each detail's circle and letter on its parent are paper a detail cannot use.
        if view._detail is None or id(view._detail[0]) not in centres:
            continue
        parent, point, radius, _letter, _auto, _chosen = view._detail
        parent_proj, parent_centre = centres[id(parent)]
        ps = parent.scale or s
        x, y = (parent.at[k] + (parent_proj.point(point)[k] - parent_centre[k]) * ps for k in (0, 1))
        ring = radius * ps + th + 4.0
        occupied.append((x - ring, x + ring, y - ring, y + ring))
    for view, _proj, _bounds, _items, plan, _centre in work:
        if view._detail is None or not view._detail[4]:
            continue
        parent, _point, radius, letter, _auto, chosen = view._detail
        # A scale the sheet chose steps down until the circle finds paper; one the
        # author gave is theirs, and no room for it is a refusal.
        parent_scale = parent.scale or s
        tries = [view.scale] + ([c for c in _STANDARD_SCALES if parent_scale * 2 - 1e-9 <= c < view.scale]
                                if chosen else [])
        spot = None
        for scale in tries:
            size = 2 * radius * scale
            spot = _place_detail(sheet, size, plan["room"], occupied, parent.at)
            if spot is not None:
                if scale != view.scale and view.label == f"DETAIL {letter} ({_scale_label(view.scale)})":
                    view.label = f"DETAIL {letter} ({_scale_label(scale)})"
                view.scale = scale
                break
        if spot is None:
            raise ValueError(
                f"DETAIL {letter}: no free paper on {sheet.size} for a {2 * radius * tries[-1]:.0f} mm circle at "
                f"{_scale_label(tries[-1])} and its annotation. Give it at=, a smaller scale=, or a larger sheet."
            )
        size = 2 * radius * view.scale
        view.at = spot
        room = plan["room"]
        occupied.append((spot[0] - size / 2 - room["left"], spot[0] + size / 2 + room["right"],
                         spot[1] - size / 2 - room["bottom"], spot[1] + size / 2 + room["top"]))
    # Auxiliary views the sheet places: the free paper nearest the view they
    # project from.
    for view, _proj, bounds, _items, plan, _centre in work:
        if view._aux is None or not view._aux[3]:
            continue
        sv = view.scale or s
        room = plan["room"]
        w = (bounds[1] - bounds[0]) * sv + room["left"] + room["right"]
        h = (bounds[3] - bounds[2]) * sv + room["bottom"] + room["top"]
        spot = _place_box(sheet, w, h, occupied, view._aux[0].at)
        if spot is None:
            smaller = next((c for c in _STANDARD_SCALES if c < s), None)
            raise _OffFrame(f"VIEW {view._aux[2]}: no free paper on {sheet.size} for it at {_scale_label(sv)}. "
                            "Give it at=, a smaller scale or a larger sheet.", smaller)
        view.at = (spot[0] + room["left"] + (bounds[1] - bounds[0]) * sv / 2,
                   spot[1] - room["top"] - (bounds[3] - bounds[2]) * sv / 2)
        occupied.append((spot[0], spot[0] + w, spot[1] - h, spot[1]))
    # Hole tables last: free paper nearest their view, or the corner given.
    for view in sheet.views:
        if id(view) not in tables:
            continue
        table = tables[id(view)]
        w, h = table["size"]
        if view._table[1] is not None:
            x0, y1 = view._table[1]
        else:
            spot = _place_box(sheet, w, h, occupied, view.at)
            if spot is None:
                smaller = next((c for c in _STANDARD_SCALES if c < s), None)
                raise _OffFrame(
                    f"{view.name}.hole_table(): no free paper on {sheet.size} for a {w:.0f} x {h:.0f} mm table. "
                    "Give it at=, a smaller scale or a larger sheet.", smaller)
            x0, y1 = spot
        table["corner"] = (x0, y1)
        occupied.append((x0 - 4.0, x0 + w + 4.0, y1 - h - 4.0, y1 + 4.0))

    placed = []
    for view, proj, bounds, _items, _plan, (cx, cy) in work:
        bx0, bx1, by0, by1 = bounds
        sv = view.scale or s
        placed.append((view, proj, bounds, cx, cy,
                       (view.at[0] + (bx0 - cx) * sv, view.at[0] + (bx1 - cx) * sv,
                        view.at[1] + (by0 - cy) * sv, view.at[1] + (by1 - cy) * sv)))
    boxes = [box for (_, _, _, _, _, box) in placed]
    # The sheet's own furniture as (x0, x1, y0, y1): the title block with any
    # parts list on it, and the revision table.
    furniture = [(sheet.width - _MARGIN - _TITLE_W, sheet.width - _MARGIN, _MARGIN,
                  _MARGIN + _TITLE_H + _list_height(sheet))]
    if sheet.revisions:
        rows_h = (len(sheet.revisions) + 1) * 6.0
        furniture.append((sheet.width - _MARGIN - 110.0, sheet.width - _MARGIN, sheet.height - _MARGIN - rows_h,
                          sheet.height - _MARGIN))
    if sheet._parts is not None:
        # Annotation printed over the parts list makes both unreadable; say so.
        claim("the parts list", (sheet.width - _MARGIN - _TITLE_W, _MARGIN + _TITLE_H, sheet.width - _MARGIN,
                                 _MARGIN + _TITLE_H + _list_height(sheet)))
    _assert_views_fit(sheet, placed, index=index, groups=groups)
    # A view drawn over the parts list prints both illegible.
    x_block, y_title = sheet.width - _MARGIN - _TITLE_W, _MARGIN + _TITLE_H
    y_list = y_title + _list_height(sheet)
    for view, _proj, _bounds, _cx, _cy, box in placed:
        if sheet._parts is not None and box[1] > x_block + 1e-6 and box[2] < y_list - 1e-6 and box[3] > y_title:
            raise ValueError(
                f"sheet {index}: the {view.name} view is drawn over the parts list, which stands on the title "
                f"block from {x_block:.0f} mm across and up to {y_list:.0f} mm. Place the view clear of it, or "
                "draw at a smaller scale."
            )
    m = _MARGIN

    def blocked(x0, x1, y0, y1, own_box):
        """Whether a landing area [x0,x1]x[y0,y1] runs off the frame or into another view."""
        if min(x0, x1) < m + 2 or max(x0, x1) > W - m - 2:
            return True
        for box in boxes:
            if box is own_box:
                continue
            if max(x0, x1) >= box[0] - 4 and min(x0, x1) <= box[1] + 4 and y1 >= box[2] - 4 and y0 <= box[3] + 4:
                return True
        return False

    drawn: dict[int, tuple] = {}
    # Items ballooned on this sheet so far, as (parts list, item number): an item
    # is keyed once per sheet, in the first view that shows it.
    keyed_on_sheet: set[tuple[int, int]] = set()
    if sheet._parts is not None and facts is not None:
        parts, first, last = sheet._parts
        _parts_facts(facts, parts)["listed"].update(range(first, last + 1))
    for (view, proj, bounds, items, plan, _centre), (_v, _p, _b, cx, cy, own_box) in zip(work, placed):
        sv = view.scale or s
        cut = cuts.get(id(view))
        record = None
        if facts is not None:
            record = facts.setdefault(id(view.shape), {"shape": view.shape, "called": set(), "values": [],
                                                       "axes": set(), "views": [], "sheet": (index, sheet.title),
                                                       "assembly": id(view.shape) in assemblies,
                                                       "notes": set(), "radii": set()})
            # What the sheet's notes and this view's notes say, for the blends and
            # chamfers a general note states.
            record["notes"].update(sheet.drawn_notes())
            record["notes"].update(d.text for d in view._dims if d.kind == "note" and d.text)
            if view.name != "iso":
                record["views"].append((view.name, _look(view)))

        def to_sheet(p2):
            # Centre the projected geometry on `at`.
            return (view.at[0] + (p2[0] - cx) * sv, view.at[1] + (p2[1] - cy) * sv)

        def model_to_sheet(p3):
            return to_sheet(proj.point(p3))

        # Bound now, not looked up later: the closures above read this loop's
        # variables, which belong to the last view by the time the loop is done.
        drawn[id(view)] = (view, functools.partial(_model_to_sheet, proj, view.at, (cx, cy), sv), own_box)

        # One set for the whole view, not one per pass. HLR returns an edge from
        # every face that bounds it, so an edge on the silhouette comes back
        # visible AND hidden: a per-pass set caught the repeats within each pass
        # and none across them, and since HIDDEN is written second it drew over
        # every visible line on the sheet. A 600 dpi crop of one view in colour
        # was 34,842 grey pixels against 2,635 black -- the outline printing
        # grey-dashed, the whole visible/hidden distinction gone. In mono it is
        # black over black, which is why it went unnoticed.
        seen: set = set()

        def once(key) -> bool:
            if key in seen:
                return False
            seen.add(key)
            return True

        def q(value: float) -> float:
            return round(value, 6)

        # A detail draws only inside its circle, in sheet coordinates.
        region = None
        if view._detail is not None:
            from shapely.geometry import Point

            region = Point(view.at).buffer(view._detail[2] * sv, quad_segs=64)
        elif id(view) in outlines:
            from shapely.geometry import Polygon

            region = Polygon([to_sheet(p) for p in outlines[id(view)]]).buffer(0.5, join_style=2)

        def centre_line(a, b) -> None:
            for run in _clip_runs([a, b], region) if region is not None else [[a, b]]:
                msp.add_line(run[0], run[-1], dxfattribs={"layer": "CENTER"})

        def centre_circle(c, r) -> None:
            if region is None:
                msp.add_circle(c, r, dxfattribs={"layer": "CENTER"})
                return
            ring = [(c[0] + r * math.cos(2 * math.pi * i / 180), c[1] + r * math.sin(2 * math.pi * i / 180))
                    for i in range(181)]
            for run in _clip_runs(ring, region):
                msp.add_lwpolyline(run, dxfattribs={"layer": "CENTER"})

        def put(edges, layer):
            """Write projected edges once each.

            The hidden-line pass returns an edge per face that hides it, so a slot
            behind two faces comes back twice and the same polyline lands on HIDDEN
            twice over. Written that way the dashes double-strike and
            ``validate_drawing_document`` reports every pair, so an edge is keyed by
            its drawn geometry -- rounded to a micron, and for a line or polyline
            read the same in either direction -- and a repeat is dropped.
            """
            from build123d import GeomType

            if region is not None:
                # A detail clips every edge to its circle; what it keeps is drawn as
                # the polyline it was cut to.
                for edge in edges:
                    for run in _clip_runs([to_sheet(p) for p in _edge_points(edge)], region):
                        points = tuple((q(x), q(y)) for x, y in run)
                        if not once(("poly", min(points, points[::-1]))):
                            continue
                        if len(run) == 2:
                            msp.add_line(run[0], run[1], dxfattribs={"layer": layer})
                        else:
                            msp.add_lwpolyline(run, dxfattribs={"layer": layer})
                return
            for edge in edges:
                # A circular edge stays a CIRCLE or ARC: exact on the sheet, so a hole
                # reads as a hole and a fillet as a radius rather than as a polyline.
                if edge.geom_type == GeomType.CIRCLE:
                    c = to_sheet((edge.arc_center.X, edge.arc_center.Y))
                    r = edge.radius * sv
                    if r < 1e-6:
                        continue
                    if edge.is_closed:
                        if once(("circle", q(c[0]), q(c[1]), q(r))):
                            msp.add_circle(c, r, dxfattribs={"layer": layer})
                        continue
                    a, b = edge.position_at(0), edge.position_at(1)
                    mid = edge.position_at(0.5)
                    ang = lambda p: math.degrees(math.atan2(p.Y - edge.arc_center.Y, p.X - edge.arc_center.X)) % 360
                    a0, a1, am = ang(a), ang(b), ang(mid)
                    # ezdxf arcs run counter-clockwise from start to end; pick the
                    # order whose sweep passes through the edge's midpoint.
                    if (am - a0) % 360 > (a1 - a0) % 360:
                        a0, a1 = a1, a0
                    if once(("arc", q(c[0]), q(c[1]), q(r), q(a0), q(a1))):
                        msp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})
                    continue
                poly = [to_sheet(p) for p in _edge_polyline(edge)]
                points = tuple((q(x), q(y)) for x, y in poly)
                # An edge seen exactly end-on projects to a point, and a point is
                # not a line: drawn, it is a zero-length entity the drawing checks
                # refuse. Single parts rarely show one; assemblies show many.
                if max(math.hypot(x - points[0][0], y - points[0][1]) for x, y in points) < 1e-6:
                    continue
                # The same edge can come back with its ends swapped; one drawn line is
                # one key whichever way it was walked.
                key = ("poly", min(points, points[::-1]))
                if not once(key):
                    continue
                if len(poly) == 2:
                    msp.add_line(poly[0], poly[1], dxfattribs={"layer": layer})
                else:
                    msp.add_lwpolyline(poly, dxfattribs={"layer": layer})

        put(proj.visible, "VISIBLE")
        if view.hidden:
            put(proj.hidden, "HIDDEN")
        if view._break is not None:
            _draw_break_lines(msp, view, proj, to_sheet)
        if cut:
            from ezdxf import const

            # The cut faces, hatched: what the section is there to show.
            for face in cut[1]:
                rings = [[to_sheet(proj.point(point)) for point in _wire_points(wire)]
                         for wire in [face.outer_wire(), *face.inner_wires()]]
                if region is not None:
                    from shapely.geometry import Polygon

                    clipped = Polygon(rings[0], rings[1:]).buffer(0).intersection(region)
                    pieces = [[list(g.exterior.coords), *[list(i.coords) for i in g.interiors]]
                              for g in getattr(clipped, "geoms", [clipped])
                              if g.geom_type == "Polygon" and not g.is_empty]
                else:
                    pieces = [rings]
                for piece in pieces:
                    hatch = msp.add_hatch(dxfattribs={"layer": "HATCH"})
                    hatch.set_pattern_fill("ANSI31", scale=_HATCH_SCALE)
                    for k, ring in enumerate(piece):
                        hatch.paths.add_polyline_path(
                            ring, is_closed=True,
                            flags=const.BOUNDARY_PATH_EXTERNAL if k == 0 else const.BOUNDARY_PATH_DEFAULT)
        if view.centre_marks:
            # One cross per CENTRE, sized to the largest circle on it. A counterbore
            # is two concentric circles, and two crosses drawn over each other fill
            # the CENTER linetype's gaps in: the centre line printed solid, which is
            # the one thing its dashes are there to say it is not.
            # A section cuts its bores and bosses in half, which leaves no full
            # cylinder to find their axes by; the whole part's axes that reach the
            # kept side of the plane (or lie in it) are the section's.
            turned = part_axes(view.shape)
            if cut:
                look = _look(view)
                turned = [a for a in turned if min(_dot(tuple(e - c for e, c in zip(end, cut[2])), look)
                                                   for end in (a.start, a.end)) <= 1e-6]
            for centre, radius in _centres(_circles(proj.visible) + _end_on(view, proj, turned)):
                c = to_sheet(centre)
                arm = radius * sv + 2.0
                centre_line((c[0] - arm, c[1]), (c[0] + arm, c[1]))
                centre_line((c[0], c[1] - arm), (c[0], c[1] + arm))
            # And a centre line down every turned feature seen from the side: a
            # shaft's axis, a bore drawn hidden through a plate.
            for a, b in _axis_lines(view, proj, turned, to_sheet):
                centre_line(a, b)
            # A slot seen end-on: a centre line down its length and one across each
            # rounded end. A bolt circle: its pitch circle as a chain line.
            look = _look(view)
            features = part_features(view.shape)

            def kept(feature, run: float) -> bool:
                # As for the section's axes above: what lies wholly in the half the
                # section took away has no centre line on it.
                if not cut:
                    return True
                far = tuple(m + a * run for m, a in zip(feature.mouth, feature.axis))
                return min(_dot(tuple(e - c for e, c in zip(end, cut[2])), look)
                           for end in (feature.mouth, far)) <= 1e-6

            for slot in features.slots:
                if abs(_dot(slot.axis, look)) < 1 - 1e-6 or not kept(slot, slot.run):
                    continue
                a, b = to_sheet(proj.point(slot.ends[0])), to_sheet(proj.point(slot.ends[1]))
                run = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                u = ((b[0] - a[0]) / run, (b[1] - a[1]) / run)
                reach = slot.width / 2 * sv + _CENTRE_OVERSHOOT
                centre_line((a[0] - u[0] * reach, a[1] - u[1] * reach), (b[0] + u[0] * reach, b[1] + u[1] * reach))
                for end in (a, b):
                    centre_line((end[0] + u[1] * reach, end[1] - u[0] * reach),
                                (end[0] - u[1] * reach, end[1] + u[0] * reach))
            for circle in features.circles:
                members = [h for h in features.holes if h.mouth in circle.mouths]
                if abs(_dot(circle.axis, look)) > 1 - 1e-6 and any(kept(h, h.length) for h in members):
                    centre_circle(to_sheet(proj.point(circle.centre)), circle.diameter / 2 * sv)
        if view._detail is not None:
            # The detail's own boundary: a thin continuous circle, as ISO 128-34 draws it.
            msp.add_circle(view.at, view._detail[2] * sv, dxfattribs={"layer": "NOTES"})
        vx0, vx1, vy0, vy1 = own_box
        centres = [to_sheet(c) for c, _r in _centres(_circles(proj.visible) + _end_on(view, proj, part_axes(view.shape)))]

        # How far annotation already reaches past each side of the view, so a
        # callout lands outside the dimensions on its side. Callouts on one side
        # share a knee and stack upward instead of pushing each other outward.
        reach = {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
        for side in plane_sides.get(id(view), ()):
            reach[side] = _PLANE_ROOM  # the cutting plane's letters, drawn after the views
        landings: dict[str, list[float]] = {"left": [], "right": []}

        def free_landing_y(side, y):
            step = th * 2.2
            while any(abs(y - used) < th * 1.6 for used in landings[side]):
                y += step
            landings[side].append(y)
            return y

        def state(value: float, axis: int | None) -> None:
            if record is not None:
                record["values"].append(value)
                if axis is not None:
                    record["axes"].add((axis, round(value, 3)))

        def linear(a, b, offset, side, row, override, orientation, tol=None, fit=None, true=None):
            """``true`` is the length measured on the whole part, when the paper's
            is shorter: a dimension across a broken view's break."""
            horizontal = (orientation or _spans(a, b)) == "h"
            if offset is None:
                # The row the plan gave it, measured from the VIEW's edge, so two
                # dimensions on different features still land on different lines.
                if horizontal:
                    offset = ((vy1 + _DIM_ROW * row) - max(a[1], b[1]) if side == "top"
                              else (vy0 - _DIM_ROW * row) - min(a[1], b[1]))
                else:
                    offset = ((vx1 + _DIM_ROW * row) - max(a[0], b[0]) if side == "right"
                              else (vx0 - _DIM_ROW * row) - min(a[0], b[0]))
            label = (override or "<>") + (f" {fit}" if fit else "")
            # The value is measured in SHEET millimetres, which are the model's only
            # at 1:1. dimlfac scales what the dimension prints back to true size, per
            # view, so a view drawn at its own scale still reads the part.
            style_override = {"dimlfac": 1.0 / sv}
            # A dimension to a hole's or a boss's centre runs its extension line as a
            # centre line, the way a drafter extends the centre mark to the dimension.
            for point, key in ((a, "dimltex1"), (b, "dimltex2")):
                if any(math.hypot(point[0] - c[0], point[1] - c[1]) < _SAME_PLACE * sv for c in centres):
                    style_override[key] = "CENTER"
            if tol:
                # The deviations are the author's, in true size, and ezdxf prints them
                # as given -- dimlfac scales the measurement, not the tolerance.
                style_override |= {"dimtol": 1, "dimtp": tol[0], "dimtm": tol[1],
                                   "dimtdec": 2, "dimtfac": 0.7}
            span = abs(b[0] - a[0]) if horizontal else abs(b[1] - a[1])
            measured = span / sv
            if true is not None and abs(true - measured) > 1e-6:
                # The paper's length is the broken view's; the value is the part's.
                measured = true
                label = label.replace("<>", _fmt(true))
            # A value wider than the space between its extension lines is set beside
            # them, on the dimension line's side, instead of across them: centred,
            # "3 WALL" printed with both witness lines running through its glyphs.
            # One that fits stays centred and only its arrows go outside.
            printed = label.replace("<>", _fmt(measured))
            width = _ink_width(printed, th) + (_text_width(_tol_suffix(tol), th * 0.7) if tol else 0.0)
            arrow = th * 0.85
            location = None
            if horizontal:
                base = (a[0], (max(a[1], b[1]) if offset >= 0 else min(a[1], b[1])) + offset)
                if width + 1.0 > span:
                    location = (max(a[0], b[0]) + 1.5 * arrow + 1.0 + width / 2, base[1] + 1.0 + th / 2)
                d = msp.add_linear_dim(base=base, p1=a, p2=b, location=location, angle=0, dimstyle=dimstyle,
                                       text=label, override=style_override, dxfattribs={"layer": "DIM"})
                side = "top" if offset >= 0 else "bottom"
                edge = vy1 if offset >= 0 else vy0
                reach[side] = max(reach[side], abs(base[1] - edge) + th * 1.5)
            else:
                base = ((max(a[0], b[0]) if offset >= 0 else min(a[0], b[0])) + offset, a[1])
                if width + 1.0 > span:
                    location = (base[0] - 1.0 - th / 2, max(a[1], b[1]) + 1.5 * arrow + 1.0 + width / 2)
                d = msp.add_linear_dim(base=base, p1=a, p2=b, location=location, angle=90, dimstyle=dimstyle,
                                       text=label, override=style_override, dxfattribs={"layer": "DIM"})
                side = "right" if offset >= 0 else "left"
                edge = vx1 if offset >= 0 else vx0
                reach[side] = max(reach[side], abs(base[0] - edge) + th * 1.5)
            d.render()
            claim_rendered(d.dimension)
            _draw_dimension_symbols(doc, d.dimension)
            state(measured, _sheet_axis(proj, horizontal))

        def on_view(point, margin: float = 1.0) -> bool:
            """Does a projected point land on the view's own drawn extent?"""
            return (vx0 - margin <= point[0] <= vx1 + margin
                    and vy0 - margin <= point[1] <= vy1 + margin)

        def check(kind: str, index: int, *points) -> None:
            # A dimension between two points in SPACE draws perfectly and measures
            # nothing: move the holes in the model, leave the constants alone, and
            # the sheet prints a clean dimension over blank paper. The commonest
            # cause is model coordinates assumed to be centred when the part was
            # built from a corner.
            off = [p for p in points if not on_view(p)]
            if off and warnings is not None:
                where = ", ".join(f"({p[0]:.1f}, {p[1]:.1f})" for p in off)
                warnings.append(
                    f"{view.name} {kind} {index}: {len(off)} of {len(points)} point(s) fall outside the "
                    f"view's geometry at sheet {where}. The dimension is drawn, but it measures blank "
                    "paper -- check the model coordinates it was given."
                )

        # A broken view's overall sizes are the whole part's, not the paper's.
        whole = _bbox_bounds(view.shape, proj, raw=True) if view._break is not None else None
        # Dimensions first, in the rows the plan gave them, then the overall pair
        # outermost, then the callouts outside all of them, then notes and angles.
        for dim in items:
            if dim.kind == "linear":
                a, b = model_to_sheet(dim.p1), model_to_sheet(dim.p2)
                check("dim", dim.index, a, b)
                across, up = abs(b[0] - a[0]) / sv, abs(b[1] - a[1]) / sv
                if dim.orientation is None and min(across, up) > 0.5 and min(across, up) > 0.5 * max(across, up) \
                        and warnings is not None:
                    warnings.append(
                        f"{view.name} dim {dim.index}: its points are {_fmt(across)} apart across and {_fmt(up)} "
                        f"up, so which one it measures was guessed: {_fmt(max(across, up))}, "
                        f"{'horizontal' if across >= up else 'vertical'}. Pass orientation=\"h\" or \"v\", or give "
                        "two points that differ in one direction only."
                    )
                true = None
                if view._break is not None:
                    ra, rb = proj._raw_point(dim.p1), proj._raw_point(dim.p2)
                    horizontal = (dim.orientation or _spans(a, b)) == "h"
                    true = abs(rb[0] - ra[0]) if horizontal else abs(rb[1] - ra[1])
                linear(a, b, dim.offset, dim.side, dim.row, dim.text, dim.orientation, dim.tol, dim.fit, true)
        if "width" in view._overall:
            linear((vx0, vy1), (vx1, vy1), None, "top", plan["overall"]["top"], None, "h",
                   true=whole[1] - whole[0] if whole else None)
        if "height" in view._overall:
            linear((vx0, vy0), (vx0, vy1), None, "left", plan["overall"]["left"], None, "v",
                   true=whole[3] - whole[2] if whole else None)
        # How far the callouts reach past each side, so balloons drawn later
        # stand outside them; callouts on one side share a knee, so this is not
        # applied until they are all placed.
        callout_reach = {"left": 0.0, "right": 0.0}
        for dim in items:
            if dim.kind not in ("diameter", "radius", "hole", "slot"):
                continue
            # A callout: a radial leader from the circle to a horizontal landing
            # outside the view, past whatever dimensions stand on that side, with
            # the text reading along the landing. Stacked callouts on one side land
            # at their own hole's height.
            centre = model_to_sheet(dim.p1)
            check(dim.kind, dim.index, centre)
            r = dim.radius * sv
            value = _callout_value(dim)
            text_w = 8.0 + _ink_width(value, th)
            # Exit on the hole's own side of the view (the short way out), unless the
            # landing there would run into another view or off the frame; then the
            # other side. A leader across the whole part is the last resort.
            # A hole on the centreline leaves to the left: in third angle the right
            # of the upper view is where the pictorial goes.
            prefer_right = centre[0] > (vx0 + vx1) / 2 + 1e-6
            choice = None
            for go_right in (prefer_right, not prefer_right):
                clear_try = reach["right" if go_right else "left"] + 10.0
                knee_try = (vx1 + clear_try) if go_right else (vx0 - clear_try)
                land_x0, land_x1 = (knee_try, knee_try + text_w) if go_right else (knee_try - text_w, knee_try)
                if not blocked(land_x0, land_x1, centre[1] - th, centre[1] + r + 6.0 + th, own_box):
                    choice = go_right
                    break
            go_right = prefer_right if choice is None else choice
            if go_right != prefer_right and warnings is not None:
                warnings.append(
                    f"{view.name} {dim.kind} {dim.index}: there is no room for {_shown(value)!r} on the "
                    f"{'right' if prefer_right else 'left'}, so its leader crosses the view to the other side. "
                    "Give the view more room (a larger sheet, or three_views(gap=...)), or call out a hole of "
                    "the same kind nearer the other edge."
                )
            side = "right" if go_right else "left"
            knee_x = (vx1 + reach[side] + 10.0) if go_right else (vx0 - reach[side] - 10.0)
            exit_angle = math.radians(dim.angle if dim.angle is not None else 45.0)
            land_y = free_landing_y(side, centre[1] + r * math.sin(exit_angle) + 6.0)
            sign = 1.0 if go_right else -1.0
            knee = (knee_x, land_y)
            # The leader points at the centre, as a leader to a circle must, and
            # stops on the circle; then it runs level to the text.
            run = math.hypot(knee[0] - centre[0], knee[1] - centre[1]) or 1.0
            start = (centre[0] + r * (knee[0] - centre[0]) / run, centre[1] + r * (knee[1] - centre[1]) / run)
            landing = (knee[0] + sign * 6.0, knee[1])
            msp.add_leader([start, knee, landing], dxfattribs={"layer": "DIM"},
                           override={"dimasz": th * 0.85, "dimldrblk": "_CLOSEDFILLED"})
            align = TextEntityAlignment.MIDDLE_LEFT if go_right else TextEntityAlignment.MIDDLE_RIGHT
            text(value, landing[0] + sign * 2.0, landing[1], th, align, "DIM")
            tip = landing[0] + sign * (2.0 + _ink_width(value, th))
            callout_reach[side] = max(callout_reach[side], abs(tip - (vx1 if go_right else vx0)) + 2.0)
            if record is not None:
                # A hole callout states its hole; a diameter callout states a diameter.
                # A leader's radius is neither, so it is not a stated value.
                if dim.kind in ("hole", "slot") and dim.feature is not None:
                    record["called"].update(_member_key(f) for f in (dim.covers or (dim.feature,)))
                elif dim.kind == "diameter":
                    record["values"].append(2 * dim.radius)
                elif dim.kind == "radius":
                    record["radii"].add(round(dim.radius, 3))
        for name, value in callout_reach.items():
            reach[name] = max(reach[name], value)
        if id(view) in tables:
            _draw_hole_tags(msp, tables[id(view)], to_sheet, sv, th, text)
            if record is not None:
                record["called"].update(_member_key(row["feature"]) for row in tables[id(view)]["rows"])
        for dim in items:
            if dim.kind == "angle":
                v = model_to_sheet(dim.p1)
                a = model_to_sheet(dim.p2)
                b = model_to_sheet(dim.hole["p2"])
                check("angle", dim.index, v, a, b)
                ua = math.atan2(a[1] - v[1], a[0] - v[0])
                ub = math.atan2(b[1] - v[1], b[0] - v[0])
                mid = ua + ((ub - ua + math.pi) % (2 * math.pi) - math.pi) / 2
                base = (v[0] + dim.offset * math.cos(mid), v[1] + dim.offset * math.sin(mid))
                d = msp.add_angular_dim_3p(base=base, center=v, p1=a, p2=b, dimstyle=dimstyle,
                                           dxfattribs={"layer": "DIM"})
                d.render()
                claim_rendered(d.dimension)
            elif dim.kind == "note":
                p = model_to_sheet(dim.p1)
                check("note", dim.index, p)
                q = (p[0] + dim.radius, p[1] + dim.angle)
                msp.add_leader([p, q, (q[0] + (3 if dim.radius >= 0 else -3), q[1])], dxfattribs={"layer": "NOTES"},
                               override={"dimasz": th * 0.85, "dimldrblk": "_CLOSEDFILLED"})
                align = TextEntityAlignment.BOTTOM_LEFT if dim.radius >= 0 else TextEntityAlignment.BOTTOM_RIGHT
                text(dim.text, q[0] + (4 if dim.radius >= 0 else -4), q[1] + 1, th, align, "NOTES")
                # A note hanging below the view pushes the view's label down, as a
                # dimension row there does.
                reach["bottom"] = max(reach["bottom"], vy0 - q[1] + 1.0)

        if view._balloons:
            _draw_balloons(msp, sheet, view, keyed_on_sheet, facts, model_to_sheet, own_box, reach, text,
                           list(claimed), [b for b in boxes if b is not own_box] + furniture, warnings)

        # The view label goes under everything that hangs below the view, so a
        # dimension on the bottom side never sits on it.
        text((view.label or view.name).upper(), view.at[0], vy0 - reach["bottom"] - 6, 3.5,
             TextEntityAlignment.TOP_CENTER, "NOTES")

    for table in tables.values():
        _draw_hole_table(msp, table, text)

    # Each section's cutting plane, on a view that sees it edge-on.
    for view_id, (kept, _faces, point) in cuts.items():
        view = drawn[view_id][0]
        if view._detail is not None:
            continue  # a detail of a section shares its section's plane, drawn once
        letter, look = view._section[0], _look(view)
        parent = next((drawn[id(other)] for name in _PLANE_SHOWN_ON[view.name]
                       for other in sheet.views
                       if other.name == name and other.shape is view.shape and other._section is None
                       and id(other) in drawn), None)
        if parent is None:
            if warnings is not None:
                warnings.append(
                    f"SECTION {letter}-{letter} has no view on this sheet that sees its cutting plane edge-on, "
                    f"so the plane is not shown; add the {_PLANE_SHOWN_ON[view.name][0]} view."
                )
            continue
        _draw_cutting_plane(msp, parent, point, look, letter, text, th)
    # Each detail's circle and letter on the view it enlarges.
    for view in sheet.views:
        if view._detail is None or id(view._detail[0]) not in drawn or id(view) not in drawn:
            continue
        parent, point, radius, letter, _auto, _chosen = view._detail
        _parent_view, parent_to_sheet, _box = drawn[id(parent)]
        c = parent_to_sheet(point)
        ring = radius * (parent.scale or s)
        msp.add_circle(c, ring, dxfattribs={"layer": "NOTES"})
        lean = (math.cos(math.radians(45)), math.sin(math.radians(45)))
        text(letter, c[0] + lean[0] * (ring + th), c[1] + lean[1] * (ring + th), th + 1.5,
             TextEntityAlignment.MIDDLE_CENTER, "NOTES")
    # Each auxiliary view's arrow and letter on the view it is projected from.
    for view in sheet.views:
        if view._aux is None or id(view._aux[0]) not in drawn or id(view) not in drawn:
            continue
        parent, point, letter, _auto, _outline = view._aux
        _parent_view, parent_to_sheet, _box = drawn[id(parent)]
        n = view._direction[0]
        tip = parent_to_sheet(point)
        ahead = parent_to_sheet(tuple(p + c for p, c in zip(point, n)))
        run = math.hypot(ahead[0] - tip[0], ahead[1] - tip[1]) or 1.0
        d = ((ahead[0] - tip[0]) / run, (ahead[1] - tip[1]) / run)
        head = (tip[0] + d[0] * 5.0, tip[1] + d[1] * 5.0)
        tail = (tip[0] + d[0] * 20.0, tip[1] + d[1] * 20.0)
        msp.add_leader([head, tail], dxfattribs={"layer": "NOTES"},
                       override={"dimasz": th, "dimldrblk": "_CLOSEDFILLED"})
        text(letter, tail[0] + d[0] * 4.0, tail[1] + d[1] * 4.0, th + 1.5, TextEntityAlignment.MIDDLE_CENTER, "NOTES")
    _merge_centre_lines(msp)
    return doc


#: A balloon: its radius and numeral height, the run of leader between the
#: annotation it stands outside and its circle, the space between two balloons,
#: and the dot a leader ends in on the part.
_BALLOON_R = 5.0
_BALLOON_TEXT = 5.0
_BALLOON_LEAD = 8.0
_BALLOON_AIR = 2.0
_DOT_R = 0.7


def _parts_facts(facts: dict, parts) -> dict:
    """What the drawing says about one parts list: the items its tables list and
    the items its balloons key."""
    return facts.setdefault(("parts", id(parts)), {"parts": parts, "listed": set(), "ballooned": set()})


def _balloon_axis(bounds) -> bool:
    """Whether a view's balloons stand in columns beside it (a tall view) rather
    than in rows above and below it (a wide one)."""
    return (bounds[3] - bounds[2]) >= (bounds[1] - bounds[0])


def _draw_balloons(msp, sheet: Sheet, view: View, keyed_on_sheet: set, facts: dict | None, model_to_sheet, box,
                   reach: dict, text, printed: Sequence[tuple], obstacles: Sequence[tuple],
                   warnings: list | None) -> None:
    """Balloon each item the view shows that this sheet has not yet keyed.

    Each leader ends in a dot on a point of the part that the view sees (nothing
    of the assembly in front of it). The balloons stand in a column on each side
    of a tall view (a row above and below a wide one), outside everything
    already drawn there, each as near the height of the point it keys as the
    others allow. Points near the middle go to whichever side has fewer, which
    keeps the two columns even. A column may run the frame's height but keeps
    off ``obstacles`` (other views, the title block, the parts list), and no
    balloon stands where its leader would run through text already ``printed``
    (``(value, box)`` pairs); leaders that would cross are swapped. A column the
    paper cannot hold is refused, never drawn off the sheet.
    """
    from ezdxf.enums import TextEntityAlignment
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from shapely.geometry import LineString, box as rect

    from cadgen._internal.drawing_assembly import spread, visible_point

    direction = _look(view)
    length = math.sqrt(sum(c * c for c in direction))
    look = tuple(c / length for c in direction)
    cast = IntCurvesFace_ShapeIntersector()
    cast.Load(view.shape.wrapped, 1e-7)
    keyed = []
    for parts in view._balloons:
        for item in parts:
            if (id(parts), item.number) in keyed_on_sheet:
                continue
            point = visible_point(item.occurrences, cast, look)
            if point is None:
                continue
            keyed.append((item.number, model_to_sheet(point), parts))
    vx0, vx1, vy0, vy1 = box
    tall = _balloon_axis(box)
    pick, along = (0, 1) if tall else (1, 0)
    mid = ((vx0 + vx1) / 2, (vy0 + vy1) / 2)
    band = 0.1 * ((vx1 - vx0) if tall else (vy1 - vy0))
    low, high = ("left", "right") if tall else ("bottom", "top")
    sides: dict[str, list] = {low: [], high: []}
    for number, point, parts in sorted(keyed, key=lambda k: (k[1][along], k[0])):
        if point[pick] < mid[pick] - band:
            side = low
        elif point[pick] > mid[pick] + band:
            side = high
        else:
            side = low if len(sides[low]) <= len(sides[high]) else high
        sides[side].append((number, point, parts))
    r, pitch, m = _BALLOON_R, 2 * _BALLOON_R + _BALLOON_AIR, _MARGIN
    frame = ((m, sheet.width - m), (m, sheet.height - m))
    texts = [(value, rect(b[0], b[1], b[2], b[3])) for value, b in printed]

    def centre_of(line: float, spot: float) -> tuple[float, float]:
        return (line, spot) if tall else (spot, line)

    def leader(centre, point) -> LineString:
        run = math.hypot(point[0] - centre[0], point[1] - centre[1]) or 1.0
        return LineString([(centre[0] + (point[0] - centre[0]) * r / run, centre[1] + (point[1] - centre[1]) * r / run),
                           point])

    for side, rows in sides.items():
        if not rows:
            continue
        out = -1.0 if side in ("left", "bottom") else 1.0
        edge = {"left": vx0, "right": vx1, "bottom": vy0, "top": vy1}[side]
        line = edge + out * (reach[side] + _BALLOON_LEAD + r)
        across, lengthwise = frame[pick], frame[along]
        if not across[0] + 1.0 <= line - r and line + r <= across[1] - 1.0:
            raise _OffFrame(f"{view.name}.balloons(): no room on {sheet.size} for a column of balloons on the "
                            f"{side} of the {view.name} view. A larger sheet or a smaller scale gives it room.",
                            next((c for c in _STANDARD_SCALES if c < sheet._scale()), None))
        lo, hi = lengthwise[0] + r + 1.0, lengthwise[1] - r - 1.0
        # The strip the leaders cross, between the column and the view.
        near, far = sorted((edge, line - out * r))
        avoid = [(b[along] - 1.0, b[along + 2] + 1.0) for _v, b in printed if b[pick] < far and b[pick + 2] > near]
        # Paper the column itself may not take: other views, the title block and
        # parts list, the revision table.
        avoid += [(o[2 * along] - r - 1.0, o[2 * along + 1] + r + 1.0) for o in obstacles
                  if o[2 * pick] < line + r + 1.0 and o[2 * pick + 1] > line - r - 1.0]
        spots = spread([point[along] for _n, point, _p in rows], pitch, lo, hi, avoid)
        if spots and (spots[-1] > hi + 1e-6 or spots[0] < lo - 1e-6):
            raise _OffFrame(
                f"{view.name}.balloons(): {len(rows)} balloons do not fit on the {side} of the {view.name} view on "
                f"{sheet.size}, clear of the other views and the parts list. A larger sheet or a smaller scale gives "
                "them room, or balloon some items on another view.",
                next((c for c in _STANDARD_SCALES if c < sheet._scale()), None))
        # Leaders that cross swap balloons until none do.
        for _round in range(len(spots) ** 2):
            crossed = next(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))
                            if leader(centre_of(line, spots[i]), rows[i][1]).crosses(
                                leader(centre_of(line, spots[j]), rows[j][1]))), None)
            if crossed is None:
                break
            i, j = crossed
            spots[i], spots[j] = spots[j], spots[i]
        # A leader through text: the nearest free place along the column where it
        # runs clear, or a word saying where it does not.
        for i, (number, point, _parts) in enumerate(rows):
            def clear(spot: float) -> bool:
                path = leader(centre_of(line, spot), point)
                return not any(path.intersects(shape) for _v, shape in texts)

            if clear(spots[i]):
                continue
            others = [spot for k, spot in enumerate(spots) if k != i]
            candidates = sorted((spots[i] + k * 0.5 for k in range(-160, 161) if k),
                                key=lambda y: abs(y - spots[i]))
            better = next((y for y in candidates if lo <= y <= hi
                           and all(abs(y - o) >= pitch - 1e-6 for o in others)
                           and not any(a < y < b for a, b in avoid) and clear(y)
                           and not any(leader(centre_of(line, y), point).crosses(
                               leader(centre_of(line, spots[k]), rows[k][1])) for k in range(len(rows)) if k != i)),
                          None)
            if better is not None:
                spots[i] = better
            elif warnings is not None:
                hit = next(v for v, shape in texts if leader(centre_of(line, spots[i]), point).intersects(shape))
                warnings.append(f"{view.name}.balloons(): the leader to balloon {number} runs through {hit.strip()!r}; "
                                "give the view more room, or balloon that item on another view.")
        for (number, point, parts), spot in zip(rows, spots):
            centre = centre_of(line, spot)
            path = leader(centre, point)
            msp.add_line(path.coords[0], path.coords[1], dxfattribs={"layer": "NOTES"})
            dot = msp.add_hatch(dxfattribs={"layer": "NOTES"})
            dot.set_solid_fill(color=256)
            dot.paths.add_edge_path().add_arc(point, _DOT_R, 0.0, 360.0)
            msp.add_circle(centre, r, dxfattribs={"layer": "NOTES"})
            text(str(number), centre[0], centre[1], _BALLOON_TEXT, TextEntityAlignment.MIDDLE_CENTER, "NOTES")
            keyed_on_sheet.add((id(parts), number))
            if facts is not None:
                _parts_facts(facts, parts)["ballooned"].add(number)
        reach[side] += _BALLOON_LEAD + 2 * r


def _member_key(feature) -> tuple:
    """One hole or slot, by what it is and where it opens."""
    return (feature.signature(), tuple(round(c, 4) for c in feature.mouth))


def _feature_key(feature) -> tuple:
    """Holes or slots one callout covers: the same kind, opening the same way. A
    plain through hole or slot reads the same from either end; a blind or
    opened-out one made from the other face is a different callout, in the other
    view."""
    from cadgen._internal.drawing_features import _canonical

    plain = feature.thru and not any(getattr(feature, name, None)
                                     for name in ("cbore", "csk", "far_cbore", "far_csk"))
    direction = _canonical(feature.axis, (0.0, 0.0, 0.0))[0] if plain else feature.axis
    return (feature.signature(), tuple(round(c, 4) for c in direction))


def _unstated(facts: dict) -> list[str]:
    """What the drawing leaves out that a shop needs to make the part.

    Read off the part, not guessed at: every kind of hole it has, its overall
    size along each axis, and every turned diameter, each checked against what
    the sheets call out or measure. A drawing is allowed to be unfinished; it
    is not allowed to look finished when it is not, so each line names the call
    that states the missing fact.
    """
    from cadgen._internal.drawing_features import holes as find_holes, slots as find_slots, turned_diameters

    lines: list[str] = []
    records = [record for record in facts.values() if "shape" in record]
    for record in records:
        shape, views = record["shape"], record["views"]
        # On a drawing of several parts, each line says whose sheet it is about.
        whose = f"sheet {record['sheet'][0]} ({record['sheet'][1]}): " if len(records) > 1 else ""
        kinds: dict[tuple, list] = {}
        # An assembly's holes and diameters are its parts', stated on their sheets.
        features = [] if record.get("assembly") else [*find_holes(shape), *find_slots(shape)]
        for feature in features:
            kinds.setdefault(_feature_key(feature), []).append(feature)
        for key, members in kinds.items():
            # Each one, not each kind: a detail's callout covers what its circle
            # holds, and the identical holes outside it are still unstated.
            members = [m for m in members if _member_key(m) not in record["called"]]
            if not members:
                continue
            feature = members[0]
            is_slot = hasattr(feature, "width")
            text = _shown(hole_callout_text(_slot_spec(feature, len(members)) if is_slot
                                            else _hole_spec(feature, len(members))))
            faces = _slot_faces_viewer if is_slot else _faces_viewer
            where = next((name for name, look in views
                          if abs(_dot(feature.axis, look)) > 1 - 1e-6 and faces(feature, look)), None)
            verb = "slot" if is_slot else "hole"
            fix = (f"{where}.{verb}({_where(feature.mouth)}) states it, or {where}.holes() calls out every hole "
                   f"and slot the {where} view looks down." if where else
                   f"No view on the drawing looks into it; add the view that looks down the {verb}.")
            lines.append(f"incomplete: {whose}{text} is not called out. {fix}")
        size = shape.bounding_box().size
        turned = [] if record.get("assembly") else turned_diameters(shape)
        # A stated diameter of the part's largest turned surface states its width
        # across that axis too: a shaft's ⌀30 is its size in Y and in Z.
        across = [d for d in turned if any(abs(v - d) <= 0.01 for v in record["values"])]
        for axis, extent in enumerate((size.X, size.Y, size.Z)):
            if any(a == axis and abs(v - extent) <= 0.01 for a, v in record["axes"]):
                continue
            if any(abs(d - extent) <= 0.01 for d in across):
                continue
            where = next((name for name, look in views if abs(look[axis]) < 1e-9), None)
            fix = f"{where}.overall() states it." if where else "No view on the drawing shows that direction."
            lines.append(f"incomplete: {whose}the overall size along {'XYZ'[axis]} ({_fmt(extent)}) is not "
                         f"dimensioned. {fix}")
        for diameter in turned:
            if any(abs(v - diameter) <= 0.01 for v in record["values"]):
                continue
            lines.append(
                f"incomplete: {whose}the turned diameter ⌀{_fmt(diameter)} is not dimensioned. Dimension it across "
                f"its profile with text=\"%%c<>\", or diameter(..., size={_fmt(diameter)}) where it is seen as a "
                "circle."
            )
    for record in records:
        if record.get("assembly"):
            continue
        whose = f"sheet {record['sheet'][0]} ({record['sheet'][1]}): " if len(records) > 1 else ""
        lines.extend(_unstated_edges(record, whose))
    for entry in (record for record in facts.values() if "parts" in record):
        parts, listed, keyed = entry["parts"], entry["listed"], entry["ballooned"]
        if not listed:
            lines.append("incomplete: balloons key a parts list that no sheet draws; sheet.parts_list(parts) draws "
                         "it above the title block.")
            continue
        missing = [n for n in range(1, len(parts) + 1) if n not in listed]
        if missing:
            lines.append(f"incomplete: the parts list leaves out item{'s' if len(missing) > 1 else ''} "
                         f"{', '.join(map(str, missing))}; draw the rest with parts_list(parts, first=...) on a "
                         "further sheet.")
        for a, b in parts.twins:
            lines.append(f"note: items {a} and {b} ({parts[a].description or 'unnamed'} and "
                         f"{parts[b].description or 'unnamed'}) are the same shape under different names; "
                         f"parts.merge({a}, {b}) lists them as one part, if they are one.")
        for item in parts:
            if item.number in listed and item.number not in keyed:
                lines.append(
                    f"incomplete: item {item.number} ({item.description or 'unnamed'}) has no balloon: no ballooned "
                    "view shows any of it unhidden. balloons() on a view from a side where it shows keys it."
                )
    return lines


# --- assembly drawings ---------------------------------------------------------------

class AssemblySheets(list):
    """The sheets :func:`assembly_sheets` makes, in order: the general arrangement,
    any sheets its parts list continues onto, then one sheet per item.
    ``part(key)`` is an item's sheet, by item number or part name; ``parts`` is
    the parts list they key."""

    def __init__(self, sheets: Sequence[Sheet], parts: PartsList, by_item: dict[int, Sheet]) -> None:
        super().__init__(sheets)
        self.parts = parts
        self._by_item = by_item

    def part(self, key: int | str) -> Sheet:
        return self._by_item[self.parts[key].number]


#: The room a hole callout is assumed to take beside a view before it is
#: planned: the run out to its knee, the landing and a typical callout's text.
_CALLOUT_ROOM = 50.0
#: The largest enlargement a part sheet chooses: past it a part is a detail view.
_PART_LARGEST = 10.0
#: The smallest scale a general arrangement is drawn at: below it the views are specks.
_GA_SMALLEST = 1 / 50
#: The share of the general arrangement's frame height its parts list may take;
#: longer lists continue on further sheets.
_GA_LIST_SHARE = 0.45


def assembly_sheets(parts: PartsList, *, title: str, part_number: str = "", revision: str = "A",
                    size: str = "A3", author: str = "", date: str = "", projection: str = "THIRD ANGLE",
                    ink: str = "mono", notes: Sequence[str] = (), general_tolerance: str = "",
                    revisions: Sequence[tuple[str, str, str]] = ()) -> AssemblySheets:
    """An assembly drawing: a general arrangement sheet and a sheet for each part.

    The general arrangement draws the assembly whole and without hidden lines: the
    front view, whichever of the top and right views shows more of it, and an
    isometric, at the largest standard scale that fits beside the parts list.
    Overall sizes are stated, every part is ballooned in the first view that
    shows it, and the parts list stands on the title block, continued on further
    sheets when it is too long for one. Each part then has a sheet of its own,
    drawn in its own frame: three views and an isometric at the largest standard
    scale that fits, its overall sizes, every hole and slot called out in a view
    that looks down it, and ``ITEM n OF <title>`` under its name. ``size`` is the
    general arrangement's; each part's sheet chooses its own (``Sheet(size=None)``),
    so a small part goes on A4.

    It is a first pass. The completeness report names what each sheet still
    leaves unstated, and every sheet is an ordinary :class:`Sheet` the script can
    add to before returning them: ``sheets.part("coil_spring")`` is that part's.
    The title block on every sheet carries the assembly's drawing number,
    revision, author and date, the set being one drawing; ``notes`` and
    ``revisions`` go on the general arrangement, ``general_tolerance`` on the part
    sheets, whose sizes it governs. Materials and part numbers come from
    ``parts.set(...)`` and are blank otherwise.
    """
    from cadgen._internal.drawing_features import holes as find_holes, slots as find_slots

    if not isinstance(parts, PartsList):
        raise TypeError(f"assembly_sheets() takes the PartsList that parts_list() returns, got {type(parts).__name__}")
    common = dict(size=size, part_number=part_number, revision=revision, author=author, date=date,
                  projection=projection, ink=ink)
    ga = Sheet(title=title, notes=notes, revisions=revisions, **common)
    frame = ga.height - 2 * _MARGIN
    on_ga = min(len(parts), max(1, int(_GA_LIST_SHARE * frame // _LIST_ROW) - 1))
    ga.parts_list(parts, last=on_ga)
    more = []
    first = on_ga + 1
    while first <= len(parts):
        sheet = Sheet(title=title, **common)
        last = min(len(parts), first + int(_list_room(sheet) // _LIST_ROW) - 2)
        sheet.parts_list(parts, first=first, last=last)
        more.append(sheet)
        first = last + 1
    shape = parts.assembly
    box = shape.bounding_box().size
    second = "top" if box.X * box.Y > box.Y * box.Z else "right"
    ga.scale, slots = _arrange_assembly(ga, shape, second)
    views = {name: ga.view(shape, name, at=at, label=label, hidden=False, centre_marks=name != "iso", scale=own)
             for name, at, own, label in slots}
    views["front"].overall()
    views[second].overall(width=second == "right", height=second == "top")
    for name in ("front", second, "iso"):
        if name in views:
            views[name].balloons(parts)

    by_item: dict[int, Sheet] = {}
    for item in parts:
        subtitle = f"ITEM {item.number}{f' (QTY {item.quantity})' if item.quantity > 1 else ''} OF {title}"
        sheet = Sheet(title=item.description or f"ITEM {item.number}", subtitle=subtitle, material=item.material,
                      general_tolerance=general_tolerance, **(common | {"size": None, "scale": None}))
        # Which views look down a hole or slot, and on which side its callout goes.
        features = [*find_holes(item.shape), *find_slots(item.shape)]
        middle = item.shape.bounding_box().center()
        centre = (middle.X, middle.Y, middle.Z)
        callouts: dict[str, set] = {}
        for name, across in (("top", 0), ("front", 0), ("right", 1)):
            look = VIEW_DIRECTIONS[name][0]
            for f in features:
                faces = _slot_faces_viewer(f, look) if hasattr(f, "width") else _faces_viewer(f, look)
                if abs(_dot(f.axis, look)) > 1 - 1e-6 and faces:
                    callouts.setdefault(name, set()).add("right" if f.mouth[across] > centre[across] + 1e-6
                                                         else "left")
        sheet._item = (item, title)
        _choose_size_and_scale(sheet, item.shape, _view_extent(item.shape, "iso", 1.0), _first_pass_room(callouts))
        top, front, right = sheet.three_views(item.shape, iso=True)[:3]
        top.overall()
        front.overall(width=False)
        for view in (top, front, right):
            if view.name in callouts:
                view.holes()
        by_item[item.number] = sheet
    return AssemblySheets([ga, *more, *by_item.values()], parts, by_item)


def _first_pass_room(callouts: dict[str, set]) -> dict:
    """The room each view of a first-pass part sheet takes: the top view's overall
    width above and height to its left, the front view's height to its left, a
    callout on each side a view's holes leave by, and every view's label."""
    row = _DIM_ROW + 3.5 * 1.5
    room = {name: {"top": 4.0, "left": 4.0, "right": 4.0, "bottom": 6.0 + 3.5 + 2.0 + 4.0}
            for name in ("top", "front", "right")}
    room["top"]["top"] += row
    room["top"]["left"] += row
    room["front"]["left"] += row
    for name, sides in callouts.items():
        for side in sides:
            room[name][side] += _CALLOUT_ROOM
    return room


#: The sheets a sheet choosing its own size tries, smallest first, for a part it
#: can draw at full size or larger; a part bigger than that goes on A3, reduced.
#: A1 and A0 are tried only at a scale the author fixed.
_SIZES_SMALLEST_FIRST = ("A4", "A3", "A2", "A1", "A0")
_SIZES_CHOSEN = ("A4", "A3", "A2")
_SIZE_REDUCED = "A3"


def _choose_size_and_scale(sheet: Sheet, shape, iso, room: dict, gap: float | None = None, size=None) -> None:
    """Settle a sheet's chosen size or scale for ``shape`` drawn in three views
    (and an isometric, ``iso`` being its 1:1 extent or False), each view with
    ``room`` for its annotation. ``size`` is the extent the views draw, when it
    is not the part's own (a broken view draws less).

    A chosen scale is the largest standard one, up to 10:1 and no larger than
    the sheet's ceiling (a scale that already ran off), that fits. A chosen size
    is the smallest of A4 to A2 that draws the part at 1:1 or larger; failing
    that, A3 at the largest scale that fits. Given a fixed scale, it is the
    smallest sheet that fits it. A part too big for all of it takes the last
    candidate, and the render refuses it, naming the scale that fits."""
    extent = size or shape.bounding_box().size
    auto_size, auto_scale = sheet._auto
    ceiling = sheet._ceiling or _PART_LARGEST
    scales = [c for c in _STANDARD_SCALES if c <= ceiling + 1e-9] if auto_scale else [sheet._scale()]

    def largest(name: str) -> float | None:
        sheet.size = name
        try:
            sheet._check_notes()
        except ValueError:
            return None  # its notes do not fit this sheet's width
        for scale in scales:
            over: list = []
            _arrange_three_views(sheet, shape, extent, gap, scale, iso, room, over)
            if max(over) <= 0:
                return scale
        return None

    floor = sheet._floor
    if not auto_size:
        chosen = (sheet._size(), largest(sheet._size()))
    elif not auto_scale:
        # A fixed scale: the smallest sheet it fits.
        chosen = (_SIZES_SMALLEST_FIRST[-1], None)
        for name in _SIZES_SMALLEST_FIRST[floor:]:
            fit = largest(name)
            if fit is not None:
                chosen = (name, fit)
                break
    else:
        # Both chosen: the smallest sheet that draws the part full size or
        # larger, else A3 (or the floor, if larger) reduced.
        reduced = _SIZES_SMALLEST_FIRST[max(floor, _SIZES_SMALLEST_FIRST.index(_SIZE_REDUCED))]
        chosen = None
        for name in _SIZES_CHOSEN[floor:]:
            fit = largest(name)
            if fit is not None and fit >= 1.0 - 1e-9:
                chosen = (name, fit)
                break
        if chosen is None:
            chosen = (reduced, largest(reduced))
    if chosen[1] is None and not auto_scale:
        chosen = (chosen[0], sheet._scale())  # the render refuses it, naming the scale that fits
    if chosen[1] is None:
        raise ValueError(
            f"the views do not fit {chosen[0]} at any standard scale: the room their dimensions, callouts and "
            "labels take alone is more than the sheet has. Give Sheet a larger size=, or fewer views."
        )
    sheet.size = chosen[0]
    if auto_scale:
        sheet.scale = chosen[1]
    sheet._check_notes()
    sheet._chosen = (sheet.size, sheet.scale)


def _assembly_room(name: str, size: tuple[float, float], overall: set) -> dict:
    """What a general-arrangement view's annotation takes on each side: its
    overall sizes, its balloons (beside a tall view, above and below a wide one)
    and its label."""
    room = {side: 4.0 for side in _SIDES}
    row = _DIM_ROW + 3.5 * 1.5
    if "width" in overall:
        room["top"] += row
    if "height" in overall:
        room["left"] += row
    for side in (("left", "right") if size[1] >= size[0] else ("bottom", "top")):
        room[side] += _BALLOON_LEAD + 2 * _BALLOON_R + 2.0
    room["bottom"] += 6.0 + 3.5 + 2.0
    return room


def _arrange_assembly(sheet: Sheet, shape, second: str) -> tuple[float, list]:
    """The general arrangement's scale and views: the front view and ``second``
    side by side (or one above the other) in the paper left of the title block,
    each with room for its overall sizes, balloons and label, at the largest
    standard scale that fits; the isometric in the column above the parts list,
    at the largest standard scale up to that one which fits there, or left out
    when even a fifth of it does not."""
    m, W, H = _MARGIN, sheet.width, sheet.height
    box = shape.bounding_box().size
    extents = {"front": (box.X, box.Z), "right": (box.Y, box.Z), "top": (box.X, box.Y)}
    overall = {"front": {"width", "height"}, second: {"width"} if second == "right" else {"height"}}
    note_rows = len(sheet.drawn_notes())
    a_x = (m + 4.0, W - m - _TITLE_W - 6.0)
    a_y = (m + 4.0 + ((_TITLE_H + note_rows * 5.0 + 8.0) if note_rows else 0.0), H - m - 4.0)
    third = sheet.projection == "THIRD ANGLE"

    def layout(s: float):
        sizes = {n: (extents[n][0] * s, extents[n][1] * s) for n in ("front", second)}
        rooms = {n: _assembly_room(n, extents[n], overall[n]) for n in ("front", second)}
        f, o = sizes["front"], sizes[second]
        rf, ro = rooms["front"], rooms[second]
        if second == "right":
            # Side by side, sharing the front view's height: third angle puts the
            # view from the right on the right.
            left, right = ((f, rf), (o, ro)) if third else ((o, ro), (f, rf))
            w = left[1]["left"] + left[0][0] + left[1]["right"] + right[1]["left"] + right[0][0] + right[1]["right"]
            h = max(f[1] + rf["top"] + rf["bottom"], o[1] + ro["top"] + ro["bottom"])
            x = a_x[0] + max(0.0, (a_x[1] - a_x[0] - w) / 2)
            y = a_y[0] + max(0.0, (a_y[1] - a_y[0] - h) / 2) + max(rf["bottom"], ro["bottom"]) + f[1] / 2
            cl = x + left[1]["left"] + left[0][0] / 2
            cr = x + left[1]["left"] + left[0][0] + left[1]["right"] + right[1]["left"] + right[0][0] / 2
            at = {"front": (cl, y), second: (cr, y)} if third else {"front": (cr, y), second: (cl, y)}
        else:
            # One above the other, sharing the front view's width: third angle
            # puts the view from above above.
            low, high = ((f, rf), (o, ro)) if third else ((o, ro), (f, rf))
            h = low[1]["bottom"] + low[0][1] + low[1]["top"] + high[1]["bottom"] + high[0][1] + high[1]["top"]
            w = max(f[0] + rf["left"] + rf["right"], o[0] + ro["left"] + ro["right"])
            y = a_y[0] + max(0.0, (a_y[1] - a_y[0] - h) / 2)
            x = a_x[0] + max(0.0, (a_x[1] - a_x[0] - w) / 2) + max(rf["left"], ro["left"]) + f[0] / 2
            yl = y + low[1]["bottom"] + low[0][1] / 2
            yh = y + low[1]["bottom"] + low[0][1] + low[1]["top"] + high[1]["bottom"] + high[0][1] / 2
            at = {"front": (x, yl), second: (x, yh)} if third else {"front": (x, yh), second: (x, yl)}
        return w <= a_x[1] - a_x[0] and h <= a_y[1] - a_y[0], at

    fitting = None
    for c in _STANDARD_SCALES:
        if not _GA_SMALLEST - 1e-12 <= c <= _PART_LARGEST:
            continue
        fits, at = layout(c)
        if fits:
            fitting = (c, at)
            break
    if fitting is None:
        # The views' own annotation -- overall sizes, balloon columns, labels --
        # does not fit beside the parts list at any useful scale. Drawing it at
        # 1:1000 would print the views as specks.
        raise ValueError(
            f"the general arrangement does not fit {sheet.size} beside its parts list at any scale down to "
            f"{_scale_label(_GA_SMALLEST)}: the front and {second} views with their sizes and balloons need more "
            "than the paper left of the parts list. Give assembly_sheets() a larger size=."
        )
    scale, at = fitting
    slots = [("front", at["front"], None, None), (second, at[second], None, None)]
    table_h = (len(sheet.revisions) + 1) * 6.0 + 6.0 if sheet.revisions else 0.0
    b_x = (W - m - _TITLE_W, W - m - 4.0)
    b_y = (m + _TITLE_H + _list_height(sheet) + 6.0, H - m - 4.0 - table_h)
    iso_w, iso_h = _view_extent(shape, "iso", 1.0)
    room = _assembly_room("iso", (iso_w, iso_h), set())
    for c in (c for c in _STANDARD_SCALES if scale / 5 - 1e-9 <= c <= scale):
        if (iso_w * c + room["left"] + room["right"] <= b_x[1] - b_x[0]
                and iso_h * c + room["bottom"] + room["top"] <= b_y[1] - b_y[0]):
            x = b_x[0] + room["left"] + iso_w * c / 2 + (b_x[1] - b_x[0] - iso_w * c - room["left"] - room["right"]) / 2
            y = b_y[0] + room["bottom"] + iso_h * c / 2 + (b_y[1] - b_y[0] - iso_h * c - room["bottom"] - room["top"]) / 2
            own = None if abs(c / scale - 1) < 1e-9 else c
            slots.append(("iso", (x, y), own, "ISOMETRIC" if own is None else f"ISOMETRIC {_scale_label(c)}"))
            break
    return scale, slots


def _continuations(sheets: Sequence[Sheet]) -> dict[int, dict]:
    """For each sheet carrying part of a split parts list, where the list
    continues from and to: ``{sheet number: {"from": n, "to": m}}``."""
    runs: dict[int, list] = {}
    for index, sheet in enumerate(sheets, start=1):
        if sheet._parts is not None:
            parts, first, last = sheet._parts
            runs.setdefault(id(parts), []).append((first, last, index))
    out: dict[int, dict] = {}
    for spans in runs.values():
        spans.sort()
        for (_f0, l0, before), (f1, _l1, after) in zip(spans, spans[1:]):
            if f1 <= l0:
                raise ValueError(f"items {f1} to {l0} of one parts list are listed on sheet {before} and again on "
                                 f"sheet {after}; each item belongs to one run of the list")
            out.setdefault(before, {})["to"] = after
            out.setdefault(after, {})["from"] = before
    return out


def geometry_notes(part) -> list[str]:
    """The general notes the part's own geometry states, for ``Sheet(notes=...)``:
    its most common blend radius (``FILLETS R2 UNLESS OTHERWISE SPECIFIED.``,
    ``ROUNDS`` for outside edges, ``FILLETS AND ROUNDS`` for both) and its most
    common 45-degree chamfer (``CHAMFERS 1 × 45° UNLESS OTHERWISE SPECIFIED.``).
    Each is a measured fact of the model, not a requirement: a blend or chamfer
    of any other size still needs stating, and the completeness report says
    which. A part with neither gets no notes."""
    from collections import Counter

    from cadgen._internal.drawing_features import blends, chamfers

    notes = []
    found = blends(part)
    if found:
        counts = Counter(round(b.radius, 3) for b in found)
        radius = max(counts, key=lambda r: (counts[r], r))
        kinds = {b.concave for b in found if abs(b.radius - radius) < 1e-3}
        word = "FILLETS AND ROUNDS" if len(kinds) == 2 else ("FILLETS" if True in kinds else "ROUNDS")
        notes.append(f"{word} R{_fmt(radius)} UNLESS OTHERWISE SPECIFIED.")
    bevels = Counter(round(c.legs[0], 3) for c in chamfers(part) if c.symmetric)
    if bevels:
        size = max(bevels, key=lambda d: (bevels[d], d))
        notes.append(f"CHAMFERS {_fmt(size)} × 45° UNLESS OTHERWISE SPECIFIED.")
    return notes


def _unstated_edges(record: dict, whose: str) -> list[str]:
    """The blends and chamfers a part's sheets leave unstated. A blend is stated by
    a note naming its radius and kind (FILLETS for inside corners, ROUNDS for
    outside edges, RADII for either) or by a ``radius()`` callout of its size; a
    chamfer by a note giving its size (``1 × 45°``) or, at 45 degrees, a
    dimension of its leg."""
    from cadgen._internal.drawing_features import blends, chamfers

    notes = [note.upper() for note in record.get("notes", ())]
    lines = []
    groups: dict[tuple, int] = {}
    for blend in blends(record["shape"]):
        key = (round(blend.radius, 3), blend.concave)
        groups[key] = groups.get(key, 0) + 1
    for (radius, concave), count in sorted(groups.items()):
        word = ("FILLET" if concave else "ROUND")
        mark = re.compile(rf"\bR{re.escape(_fmt(radius))}(?![\d.])")
        named = any(mark.search(note) and (word in note or "RADII" in note) for note in notes)
        if named or radius in record.get("radii", ()):
            continue
        plural = count > 1
        lines.append(
            f"incomplete: {whose}{count} {word.lower()}{'s' if plural else ''} R{_fmt(radius)} "
            f"{'are' if plural else 'is'} not stated. Sheet(notes=geometry_notes(part)) states the commonest "
            "radius as a general note, or radius(...) states one where a view shows it as an arc."
        )
    bevels: dict[tuple, int] = {}
    for chamfer in chamfers(record["shape"]):
        key = tuple(sorted((round(chamfer.legs[0], 3), round(chamfer.legs[1], 3))))
        bevels[key] = bevels.get(key, 0) + 1
    for (a, b), count in sorted(bevels.items()):
        size = f"{_fmt(a)} × 45°" if abs(a - b) < 1e-3 else f"{_fmt(a)} × {_fmt(b)}"
        if any(size.upper() in note for note in notes):
            continue
        if abs(a - b) < 1e-3 and any(abs(v - a) <= 0.01 for v in record["values"]):
            continue
        plural = count > 1
        lines.append(
            f"incomplete: {whose}{count} chamfer{'s' if plural else ''} {size} {'are' if plural else 'is'} not "
            "stated. Sheet(notes=geometry_notes(part)) states the commonest as a general note, or a note or a "
            "dimension of its leg states it."
        )
    return lines


def _write_pdf(docs, sheets: Sequence[Sheet], path: Path) -> None:
    """Render the sheets to one PDF, a page each.

    The PDF is the drawing, so a missing renderer is a failure, not a downgrade:
    an exit 0 with no document is the one outcome a build cannot recover from.
    The page carries no creation date, so the bytes are a function of the
    content, and the render goes to a temporary file that is renamed on success,
    so a failed run never leaves a half-written document behind.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from ezdxf.addons.drawing import Frontend, RenderContext, config
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    except ImportError as exc:
        raise RuntimeError(
            "@eng_drawing writes a PDF and its renderer is missing: "
            f"{exc}. Install cadgen's dependencies (pip install matplotlib pillow)."
        ) from exc
    from cadgen._internal.atomic_replace import temp_suffix

    path.parent.mkdir(parents=True, exist_ok=True)
    # A temp_suffix name, so a model listing this folder leaves it out while it exists.
    partial = path.with_name(f".{path.name}{temp_suffix()}")
    try:
        # CreationDate=None drops the one field matplotlib stamps from the clock.
        with PdfPages(partial, metadata={"CreationDate": None}) as pdf:
            for doc, sheet in zip(docs, sheets):
                fig = plt.figure(figsize=(sheet.width / 25.4, sheet.height / 25.4))
                ax = fig.add_axes([0, 0, 1, 1])
                ax.set_xlim(0, sheet.width)
                ax.set_ylim(0, sheet.height)
                ctx = RenderContext(doc)
                ctx.set_current_layout(doc.modelspace())
                backend = MatplotlibBackend(ax, adjust_figure=False)
                Frontend(ctx, backend, config=config.Configuration(
                    background_policy=config.BackgroundPolicy.WHITE,
                    color_policy=config.ColorPolicy.BLACK if sheet.ink == "mono" else config.ColorPolicy.COLOR,
                    # Without a floor of its own the matplotlib backend clamps every
                    # width to 72/dpi, and the sheet printed one width throughout --
                    # the LAYER table resolves 0.5 for VISIBLE against 0.18 for DIM
                    # and CENTER, and none of it reached the page. Thick against thin
                    # is most of what makes a print readable at a glance. The unit is
                    # 1/300 inch, so this is a floor low enough to be no floor.
                    min_lineweight=0.05,
                )).draw_layout(doc.modelspace(), finalize=False)
                ax.set_xlim(0, sheet.width)
                ax.set_ylim(0, sheet.height)
                ax.set_aspect("equal")
                ax.axis("off")
                pdf.savefig(fig)
                plt.close(fig)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def _say(line: str) -> None:
    """Print one line the drawing has to say, on any console.

    A drawing's notices quote its callouts, and a Windows console on a legacy
    code page cannot encode ⌀, ↧, ⌴ or ⌵: under strict error handling the
    print raised after the drawing was made, from the message rather than the
    work. A line that will not encode goes out with backslash escapes instead,
    as cadgen's CLI does. Only this write degrades; the stream's settings belong
    to the process that embedded us.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, "backslashreplace").decode(encoding))


def _counted(run: Callable[..., list[Path]]) -> Callable[..., list[Path]]:
    """``run``, counted for telemetry (``cadgen/analytics.py``): a drawing made, or a mistake in
    cadgen's own code making one. A drawing is made in the script's own process, which sends nothing
    itself: both are handed to a running build daemon, as a command hands it its snapshots
    (``cadgen.daemon.client.hand_over``), and neither ever changes what the drawing does."""

    @functools.wraps(run)
    def counted(*args: Any, **kwargs: Any) -> list[Path]:
        try:
            drawn = run(*args, **kwargs)
        except Exception as error:
            try:
                from cadgen import analytics

                analytics.report(error, "build", bugs_only=True)  # the person's own mistakes are theirs
            except Exception:  # noqa: BLE001 - a crash report never adds a failure to one
                pass
            raise
        try:
            from cadgen.daemon.client import hand_over

            hand_over({"features": ["drawing"]})
        except Exception:  # noqa: BLE001 - a count never fails the drawing it counts
            pass
        return drawn

    return counted


def eng_drawing(func: Callable[..., Any] | None = None, *, out: str | Path | None = None):
    """Declare an engineering drawing. The function returns a :class:`Sheet` or a
    list of them; calling it (the script's ``__main__`` does) writes one PDF with a
    page per sheet at ``out`` and returns the path written.

    ``out`` is required and relative paths resolve against the script, because
    cadgen has no opinion on where a document belongs -- the caller does.
    """

    def apply(fn: Callable[..., Any]) -> Callable[..., Any]:
        import inspect

        if out is None:
            raise ValueError(
                f"@eng_drawing {fn.__name__} needs out=<path>.pdf: the drawing is that PDF, "
                "and cadgen does not choose where it lands."
            )
        target_spec = Path(out)
        if target_spec.suffix.lower() != ".pdf":
            raise ValueError(f"@eng_drawing out= must name a .pdf, got {out!r}")
        script = Path(inspect.getsourcefile(fn) or inspect.getfile(fn)).resolve()

        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> list[Path]:
            result = fn(*args, **kwargs)
            sheets = list(result) if isinstance(result, (list, tuple)) else [result]
            if not sheets or not all(isinstance(s, Sheet) for s in sheets):
                raise TypeError(f"@eng_drawing {fn.__name__} must return a Sheet or a list of Sheets")
            from cadgen.drawing_checks import raise_on_error_findings, validate_drawing_document

            target = target_spec if target_spec.is_absolute() else (script.parent / target_spec).resolve()
            docs = []
            notices: list[str] = []
            facts: dict = {}
            continued = _continuations(sheets)
            for index, sheet in enumerate(sheets, start=1):
                doc = _render_sheet(sheet, index=index, count=len(sheets), label=fn.__name__,
                                    warnings=notices, facts=facts, continued=continued.get(index))
                # The same checks every @dxf build runs, against the document the
                # page is rendered from: duplicate geometry, unset units, an empty
                # sheet. A drawing skipping them is how the duplicates went unseen.
                # drawing=True because this IS one: the cut-profile checks grade a
                # file as a laser-cut layout, and a projected outline with a fillet
                # in it does not close.
                findings = validate_drawing_document(doc, drawing=True)
                raise_on_error_findings(findings, label=f"{fn.__name__} sheet {index}")
                for finding in findings:
                    if finding.severity == "warning":
                        _say(f"{fn.__name__} sheet {index} {finding.render()}")
                docs.append(doc)
            # What the drawing does not state, across every sheet of it: printed, not
            # raised, because a sheet of views is a drawing before it is a finished one.
            notices.extend(_unstated(facts))
            for notice in notices:
                _say(f"{fn.__name__}: {notice}")
            _write_pdf(docs, sheets, target)
            _say(f"wrote {target} ({len(sheets)} page{'s' if len(sheets) != 1 else ''})")
            return [target]

        run.__cadgen_eng_drawing__ = True  # type: ignore[attr-defined]
        return _counted(run)

    return apply(func) if func is not None else apply
