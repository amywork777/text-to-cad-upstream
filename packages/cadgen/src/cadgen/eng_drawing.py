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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple, Sequence

from cadgen._internal.drawing_annotation import _Dim, _looks_into
from cadgen._internal.drawing_assembly import (
    _GA_LIST_SHARE, Item, _PartOf, PartsList, _arrange_assembly, _continuations, _item_subtitle, parts_list,
    _refuse_balloons_on,
)
from cadgen._internal.drawing_base import (
    _DETAIL_SIZE, _MARGIN, _NOTE_HEIGHT, _NOTE_INSET, PROJECTIONS, _SAME_PLACE, _SECTION_LETTERS, SHEET_SIZES,
    _STANDARD_SCALES, UNITS, VIEW_DIRECTIONS, _cross, _dirs, _dot, _look, _p3, _scale_label, _text_width,
    _view_axes, _where,
)
from cadgen._internal.drawing_gdt import Frame, frame_size
from cadgen._internal.drawing_render import _render_sheet
from cadgen._internal.drawing_report import _Facts, geometry_notes, _unstated
from cadgen._internal.drawing_sheet import (
    _LIST_ROW, _VIEW_NAMES, _Arrangement, _arrange_three_views, _choose_size_and_scale, _default_rooms, _list_room,
    _require_settled, _settle,
)
from cadgen._internal.drawing_views import _flat_face, _view_extent


#: Note 1 of a sheet with a general profile; its frame is drawn after the words.
_GENERAL_PROFILE = "UNLESS OTHERWISE SPECIFIED, ALL SURFACES"

__all__ = ["eng_drawing", "Sheet", "View", "Frame", "SHEET_SIZES", "parts_list", "PartsList", "Item", "assembly_sheets",
           "AssemblySheets", "geometry_notes"]


class _Detail(NamedTuple):
    """What makes a view a detail of another (:meth:`Sheet.detail`)."""

    parent: "View"
    centre: tuple[float, float, float]
    radius: float
    letter: str
    placed_by_sheet: bool
    scale_chosen: bool


class _Aux(NamedTuple):
    """What makes a view an auxiliary view of another (:meth:`Sheet.auxiliary`);
    ``outline`` is the face's, for a partial view, else None."""

    parent: "View"
    point: tuple[float, float, float]
    letter: str
    placed_by_sheet: bool
    outline: list | None


class _Break(NamedTuple):
    """The stretch :meth:`View.broken` leaves out: from ``low`` to ``high`` along a model axis (0-2)."""

    axis: int
    low: float
    high: float


class _TableSpec(NamedTuple):
    """A hole table's origin (a model point, or None for the view's corner) and its
    top-left corner on the sheet (or None for the sheet to place it)."""

    origin: tuple[float, float, float] | None
    corner: tuple[float, float] | None


class _ListRun(NamedTuple):
    """The run of a parts list a sheet draws: items ``first`` to ``last``."""

    parts: PartsList
    first: int
    last: int


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
    #: Which overall sizes ``overall()`` asked for: {"width", "height"}, or empty;
    #: and whether they are reference dimensions.
    _overall: frozenset = frozenset()
    _overall_reference: bool = False
    #: ``(letter, model point or None)`` when :meth:`section` made this a section.
    _section: tuple | None = None
    #: ``(label, scale)`` the sheet gave an isometric or an auxiliary view, so the
    #: render knows whether the author has since set their own and leaves it alone.
    _auto_label: tuple | None = None
    #: Set when :meth:`Sheet.detail` made this a detail view.
    _detail: _Detail | None = None
    #: The arrangement :meth:`Sheet.three_views` placed this view in, shared by its
    #: views: the render lays them out again from it, and the off-frame guard does
    #: at each candidate scale. None for a hand-placed ``at=``, which does not move.
    _arranged: _Arrangement | None = None
    #: The parts lists :meth:`balloons` keys this view to.
    _balloons: list = field(default_factory=list)
    #: Set when :meth:`hole_table` tabulates this view's holes.
    _table: _TableSpec | None = None
    #: ``(where the viewer stands, up)`` for a view whose direction is its own
    #: rather than its name's: an auxiliary view.
    _direction: tuple | None = None
    #: Set when :meth:`broken` takes a stretch of the part out of the view.
    _break: _Break | None = None
    #: Set when :meth:`Sheet.auxiliary` made this an auxiliary view.
    _aux: _Aux | None = None
    #: The datum features :meth:`datum` defines on this view: (letter, model
    #: point, stem offset or None).
    _datums: list = field(default_factory=list)

    def dim(self, p1, p2, *, offset: float | None = None, text: str | None = None, orientation: str | None = None,
            tol: float | tuple[float, float] | None = None, fit: str | None = None,
            limits: tuple[float, float] | None = None, basic: bool = False, reference: bool = False,
            frame: Frame | None = None, datum: str | None = None) -> "View":
        """A linear dimension between two model points. ``orientation`` is ``"h"``,
        ``"v"`` or None (whichever the projected pair spans more); ``offset`` is
        the dimension line's distance from the farther point, in sheet mm, and its
        sign picks the side. Left unset, the dimension takes the next free row on
        its side, so defaults never stack on each other or on :meth:`overall`.
        ``tol=0.1`` states ±0.1; ``tol=(0.05, 0.02)`` states +0.05/-0.02
        deviations; ``fit="H7"`` appends an ISO fit class; ``limits=(39.98,
        40.02)`` prints the two limits the part must lie between, and is checked
        against the part.

        ``basic=True`` makes it a basic dimension: the exact value, in a box, that
        a GD&T frame bounds. ``reference=True`` makes it a reference dimension:
        information only, in parentheses, never inspected and stating no
        requirement; an assembly's overall size is one. Neither takes a
        tolerance. ``frame`` is a :class:`Frame` drawn beyond the value, on a row
        of its own, and ``datum`` makes the dimensioned feature a datum."""
        if orientation not in (None, "h", "v"):
            raise ValueError(f"orientation must be 'h', 'v' or None, got {orientation!r}")
        limits = _dimension_kind(tol=tol, fit=fit, limits=limits, basic=basic, reference=reference)
        self._dims.append(_Dim("linear", _p3(p1), _p3(p2), _offset(offset), text, orientation,
                               tol=_tol(tol), fit=fit, basic=basic, reference=reference, limits=limits,
                               frame=_frame(frame), datum=_new_datum(self.sheet, datum)))
        return self

    def hole(self, center, diameter: float | None = None, *, depth: float | None = None, thru: bool | None = None,
             cbore: tuple[float, float] | None = None, csk: tuple[float, float] | None = None,
             thread: str | None = None, count: int | None = None, angle: float = 45.0,
             tol: float | tuple[float, float] | None = None, fit: str | None = None,
             label: str | None = None, frame: Frame | None = None, datum: str | None = None) -> "View":
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
        leaves the circle, degrees from horizontal. ``frame`` is the
        :class:`Frame` drawn under the callout (its position, say), and ``datum``
        makes the hole a datum feature, its symbol on the callout."""
        _refuse_iso(self, "hole()")
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
                               angle=float(angle), tol=_tol(tol), fit=fit, hole=spec,
                               frame=_frame(frame), datum=_new_datum(self.sheet, datum)))
        return self

    def slot(self, center, *, width: float | None = None, length: float | None = None, thru: bool | None = None,
             depth: float | None = None, count: int | None = None, angle: float = 45.0,
             label: str | None = None, frame: Frame | None = None, datum: str | None = None) -> "View":
        """A slot callout -- ``2× 8 × 30 SLOT THRU`` -- read off the part, in a view
        that looks down the slot. ``center`` is the slot's centre or the centre of
        either rounded end. Width, length (end to end), THRU or depth and the count
        come from the geometry; any given here is checked and a contradiction is
        refused. ``label`` is appended; ``frame`` and ``datum`` are as :meth:`hole`
        takes them."""
        _refuse_iso(self, "slot()")
        given = {"width": _positive("width", width, allow_none=True),
                 "length": _positive("length", length, allow_none=True),
                 "thru": None if thru is None else bool(thru), "depth": _positive("depth", depth, allow_none=True),
                 "count": None if count is None else _positive("count", count, integer=True)}
        if thru and depth is not None:
            raise ValueError("a slot is either THRU or has a depth, not both")
        self._dims.append(_Dim("slot", _p3(center), None, 0.0, None, None, angle=float(angle),
                               hole={"given": given, "label": None if label is None else str(label)},
                               frame=_frame(frame), datum=_new_datum(self.sheet, datum)))
        return self

    def holes(self, *, angle: float = 45.0) -> "View":
        """Call out every hole and slot this view looks down, one callout per kind
        (``4× ⌀5.5 THRU``, ``⌀28 THRU``, ``8 × 30 SLOT THRU``), each read off the
        part and placed on the one nearest the edge of the view so its leader is
        short. Holes on a bolt circle say so (``EQ SP ON ⌀60``). A blind hole that
        opens on the far side belongs to the opposite view."""
        _refuse_iso(self, "holes()")
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
        self._table = _TableSpec(None if origin is None else _p3(origin), corner)
        return self

    def diameter(self, center, *retired, size: float | None = None, angle: float = 45.0,
                 text: str | None = None, basic: bool = False, reference: bool = False,
                 frame: Frame | None = None, datum: str | None = None) -> "View":
        """A diameter callout on the circle centred at ``center``, measured off the
        view. ``size`` picks one of several concentric circles (a chamfered
        shaft end shows two) and is checked against the geometry. ``basic``,
        ``reference``, ``frame`` and ``datum`` as :meth:`dim` takes them."""
        _refuse_retired_size("diameter", retired)
        _dimension_kind(basic=basic, reference=reference)
        self._dims.append(_Dim("diameter", _p3(center), None, 0.0, text, None,
                               radius=0.0 if size is None else _positive("size", size) / 2, angle=float(angle),
                               basic=basic, reference=reference, frame=_frame(frame),
                               datum=_new_datum(self.sheet, datum)))
        return self

    def radius(self, center, *retired, size: float | None = None, angle: float = 45.0,
               text: str | None = None, basic: bool = False, reference: bool = False) -> "View":
        """A radius callout on the arc centred at ``center``, measured off the view;
        ``size`` (the radius) picks one of several and is checked like ``diameter``'s,
        and ``basic`` and ``reference`` are as :meth:`dim` takes them."""
        _refuse_retired_size("radius", retired)
        _dimension_kind(basic=basic, reference=reference)
        self._dims.append(_Dim("radius", _p3(center), None, 0.0, text, None,
                               radius=0.0 if size is None else _positive("size", size), angle=float(angle),
                               basic=basic, reference=reference))
        return self

    def angle(self, vertex, p1, p2, *, offset: float = 14.0, basic: bool = False,
              reference: bool = False) -> "View":
        """The angle at ``vertex`` between the legs toward ``p1`` and ``p2`` (model
        points); ``offset`` is the arc's distance from the vertex, in sheet mm.
        ``basic`` and ``reference`` as :meth:`dim` takes them."""
        _dimension_kind(basic=basic, reference=reference)
        # angle() was the one verb whose arguments went unchecked: offset=nan
        # reached the PDF, and two legs along one line printed "0 degrees" as
        # though that were a measurement.
        vertex, a, b = _p3(vertex), _p3(p1), _p3(p2)
        distance = _offset(offset)
        if distance is None or distance == 0.0:
            raise ValueError(f"angle offset must be a non-zero number of sheet millimetres, got {offset!r}")
        _assert_legs_measure_an_angle(vertex, a, b)
        self._dims.append(_Dim("angle", vertex, a, distance, None, None, radius=0.0, angle=0.0, hole={"p2": b},
                               basic=basic, reference=reference))
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

    def frame(self, at, frame: Frame, *, offset: tuple[float, float] = (10.0, 10.0)) -> "View":
        """A feature control frame with a leader to a surface at ``at`` (a model point
        on it): ``Frame("flatness", 0.05)`` on a face, say. ``offset`` places the
        frame as :meth:`note` places its text."""
        dx, dy = _sheet_offset("frame", offset)
        self._dims.append(_Dim("frame", _p3(at), None, 0.0, None, None, radius=dx, angle=dy, frame=_frame(frame)))
        return self

    def datum(self, letter: str, at, *, offset: tuple[float, float] | None = None) -> "View":
        """Make the surface at ``at`` (a model point on it, as the view shows it)
        datum feature ``letter``: a filled triangle on it, a stem, and the letter
        in a square, which frames name. A letter names one feature per sheet.
        ``offset`` (sheet mm) points the stem; left unset, it leads straight out
        of the view's nearest side."""
        letter = _new_datum(self.sheet, letter)
        self._datums.append((letter, _p3(at), None if offset is None else _sheet_offset("datum", offset)))
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
        if self._detail is not None:
            raise ValueError("a detail shows its parent as the parent is drawn; cut the parent view, and its "
                             "details show the section")
        if self._break is not None:
            raise ValueError("section() cuts a whole view, and this one is broken; cut a view that is not")
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

    def overall(self, *, width: bool = True, height: bool = True, reference: bool = False) -> "View":
        """Overall width (above) and height (left) of the view's projected extent,
        each on the outermost row of its side. Turn one off where another
        dimension already states it -- a turned part's height is its diameter,
        and a drawing states a size once. ``reference=True`` prints them as
        reference dimensions: an assembly's envelope, which nobody inspects."""
        self._overall = frozenset(name for name, on in (("width", width), ("height", height)) if on)
        self._overall_reference = bool(reference)
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
        across = [k for k in range(3) if k != axis and abs(b[k] - a[k]) > _SAME_PLACE]
        if across:
            raise ValueError(f"broken({_where(a)}, {_where(b)}): the points differ along {'XYZ'[axis]} and "
                             f"{'XYZ'[across[0]]}; a break runs along one axis, so give two points on a line along it")
        if abs(_look(self)[axis]) > 1e-9:
            raise ValueError(f"the {self.name} view looks along {'XYZ'[axis]}, so it shows no length to break; "
                             f"break a view that shows {'XYZ'[axis]} across the sheet")
        brk = _Break(axis, min(a[axis], b[axis]), max(a[axis], b[axis]))
        views = [self]
        if self._arranged is not None:
            views = [v for v in self.sheet.views if v._arranged is self._arranged and v.name != "iso"
                     and abs(_look(v)[axis]) < 1e-9]
        sectioned = [view.name for view in views if view._section is not None]
        if sectioned:
            raise ValueError(f"broken() would break the {sectioned[0]} view too, which is a section; a section is "
                             "drawn whole, so break the arrangement before cutting a short view of it")
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


def _refuse_used_letter(sheet: "Sheet", letter: str, view=None) -> None:
    """A letter names one section or one detail per sheet: two DETAIL Bs, or a
    DETAIL A beside SECTION A-A, send a reader to the wrong view."""
    for other in sheet.views:
        if other is view:
            continue
        if other._detail is not None and other._detail.letter == letter:
            raise ValueError(f"letter {letter} already names DETAIL {letter} on this sheet; pick another letter")
        if other._detail is None and other._section is not None and other._section[0] == letter:
            raise ValueError(f"letter {letter} already names SECTION {letter}-{letter} on this sheet; pick another letter")
        if other._aux is not None and other._aux.letter == letter:
            raise ValueError(f"letter {letter} already names VIEW {letter} on this sheet; pick another letter")


def _refuse_iso(view: View, call: str) -> None:
    """A callout reads a hole the view looks down, and an isometric looks down none."""
    if view.name == "iso":
        raise ValueError(f"{call} calls out what a view looks down, and an isometric looks down no hole; "
                         "call it out on an orthographic view")


def _refuse_retired_size(verb: str, retired: tuple) -> None:
    """``diameter(center, radius)`` took a RADIUS and printed twice it, so
    ``diameter(c, 30)`` on a ⌀30 shaft printed ⌀60. The size is measured now."""
    if retired:
        raise TypeError(
            f"{verb}() no longer takes a size argument: it measures the circle at `center`. "
            f"Pass size=<{'diameter' if verb == 'diameter' else 'radius'}> only to pick one of several "
            "concentric circles; it is checked against the part."
        )


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


def _frame(frame) -> Frame | None:
    if frame is not None and not isinstance(frame, Frame):
        raise TypeError(f"frame= takes a Frame, e.g. Frame(\"position\", 0.1, (\"A\", \"B\")), got {frame!r}")
    return frame


def _new_datum(sheet: "Sheet", letter: str | None) -> str | None:
    """A datum letter not yet used on the sheet, or None."""
    if letter is None:
        return None
    letter = str(letter).upper()
    if len(letter) != 1 or letter not in _SECTION_LETTERS:
        raise ValueError(f"a datum letter is one of {_SECTION_LETTERS} (Y14.5 leaves out I, O and Q), "
                         f"got {letter!r}")
    used = {d[0] for view in sheet.views for d in view._datums} | {
        dim.datum for view in sheet.views for dim in view._dims if dim.datum}
    if letter in used:
        raise ValueError(f"datum {letter} is already a feature on this sheet; a letter names one feature")
    return letter


def _sheet_offset(call: str, offset) -> tuple[float, float]:
    try:
        dx, dy = (float(offset[0]), float(offset[1]))
    except (TypeError, ValueError, IndexError) as exc:
        raise TypeError(f"{call} offset must be an (x, y) pair of sheet millimetres, got {offset!r}") from exc
    if not (math.isfinite(dx) and math.isfinite(dy)) or (dx, dy) == (0.0, 0.0):
        raise ValueError(f"{call} offset must be a finite, non-zero (x, y) pair, got {offset!r}")
    return dx, dy


def _dimension_kind(*, tol=None, fit=None, limits=None, basic: bool = False,
                    reference: bool = False) -> tuple[float, float] | None:
    """Check that a dimension's kind and its tolerance agree, and return its limits
    as numbers. A basic dimension is exact, its tolerance the GD&T frame's that
    uses it; a reference dimension is information only; limits are the tolerance
    themselves."""
    if basic and reference:
        raise ValueError("a dimension is basic (exact, boxed) or reference (information, in parentheses), not both")
    for kind, on in (("basic", basic), ("reference", reference)):
        if on and (tol is not None or fit is not None or limits is not None):
            raise ValueError(f"a {kind} dimension takes no tol=, fit= or limits=: "
                             + ("its tolerance is the GD&T frame's that uses it" if kind == "basic"
                                else "it states no requirement to tolerance"))
    if limits is None:
        return None
    if tol is not None:
        raise ValueError("limits= are the tolerance, as the two limits the part lies between; give them or tol=, "
                         "not both")
    low, high = _pair("limits", limits)
    if not low < high:
        raise ValueError(f"limits=(low, high) with low below high, got {limits!r}")
    return low, high


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
    #: A general tolerance standard, e.g. "ISO 2768-m": written as a note, after
    #: any general profile.
    general_tolerance: str = ""
    #: A surface profile every surface meets unless otherwise specified, to its
    #: datums: note 1, "UNLESS OTHERWISE SPECIFIED, ALL SURFACES" and the frame.
    general_profile: Frame | None = None
    #: Revision history rows (rev, date, description), drawn as a table top-right.
    revisions: Sequence[tuple[str, str, str]] = ()
    #: A second line under the title: on a part's sheet of an assembly drawing,
    #: which item it details and of what ("ITEM 4 OF SHOCK ABSORBER").
    subtitle: str = ""
    views: list[View] = field(default_factory=list)
    #: Set when :meth:`parts_list` draws a parts list on the sheet.
    _parts: _ListRun | None = field(default=None, init=False, repr=False)
    #: The size and scale the sheet chose, where the author left ``size`` or
    #: ``scale`` None; a value the author sets is theirs and these go unread.
    _chosen_size: str | None = field(default=None, init=False, repr=False)
    _chosen_scale: float | None = field(default=None, init=False, repr=False)
    #: For a part's sheet of an assembly drawing, the item it details: its title,
    #: subtitle and material follow the item when it renders.
    _item: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.size is not None and self.size not in SHEET_SIZES:
            raise ValueError(f"unknown sheet size {self.size!r}; one of {sorted(SHEET_SIZES)}, or None to let "
                             "three_views() choose")
        if self.scale is not None and (isinstance(self.scale, bool) or not isinstance(self.scale, (int, float))
                                       or not (self.scale > 0)):
            raise ValueError(f"scale must be a positive number, or None to let three_views() choose; got "
                             f"{self.scale!r}")
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
        if self.general_profile is not None and (not isinstance(self.general_profile, Frame)
                                                 or self.general_profile.characteristic != "surface_profile"):
            raise ValueError("general_profile takes a Frame of surface_profile, e.g. Frame(\"surface_profile\", 0.2, "
                             f"(\"A\", \"B\", \"C\")); got {self.general_profile!r}")
        if self.size is not None:
            self._check_notes(self.size)

    def _check_notes(self, paper: str) -> None:
        """A note wider than the sheet runs off the paper, and the sheet is the one
        thing here that cannot be made bigger after the fact. Measure the line the
        sheet DRAWS -- numbered, prefixed, general tolerance expanded -- at the
        height it draws it, against the room ``paper`` gives it."""
        room = SHEET_SIZES[paper][0] - 2 * (_MARGIN + _NOTE_INSET)
        for width, note in zip(self._note_widths(), self.drawn_notes()):
            if width > room:
                raise ValueError(
                    f"note {note!r} is wider than the {paper} sheet's note row "
                    f"({round(room)} mm). Shorten it, or split it across two notes."
                )

    def _note_widths(self) -> list[float]:
        """Each drawn note line's width at the height the sheet draws it, a general
        profile's frame included."""
        widths = []
        for line, note in zip(self.note_lines(), self.drawn_notes()):
            width = _text_width(line, _NOTE_HEIGHT)
            if note == _GENERAL_PROFILE and self.general_profile is not None:
                width += _NOTE_HEIGHT + frame_size(self.general_profile, _NOTE_HEIGHT)[0]
            widths.append(width)
        return widths

    def drawn_notes(self) -> list[str]:
        """The note strings as they reach the paper: a general profile is note 1
        (its frame drawn after the words), then the general tolerance, spelled
        out, then the author's notes."""
        profile = [_GENERAL_PROFILE] if self.general_profile is not None else []
        general = [f"TOLERANCES PER {self.general_tolerance} UNLESS OTHERWISE SPECIFIED."]
        return profile + (general if self.general_tolerance else []) + list(self.notes)

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
        """The paper the sheet is drawn on: the author's, else the one it chose."""
        size = self.size or self._chosen_size
        if size is None:
            raise ValueError(
                "Sheet(size=None) chooses its size when three_views() places the part, and nothing has been "
                "placed yet. Call three_views() first, or give size= for views placed by hand."
            )
        return size

    def _scale(self) -> float:
        """The scale the sheet is drawn at: the author's, else the one it chose."""
        scale = self.scale if self.scale is not None else self._chosen_scale
        if scale is None:
            raise ValueError(
                "Sheet(scale=None) chooses its scale when three_views() places the part, and nothing has been "
                "placed yet. Call three_views() first, or give scale= for views placed by hand."
            )
        return scale

    def _chooses(self) -> bool:
        """Whether the sheet settles its own size or scale."""
        return self.size is None or self.scale is None

    def three_views(self, shape, *, gap: float | None = None, hidden: bool = True, centre_marks: bool = True,
                    iso: bool = False, views: Sequence[str] = _VIEW_NAMES) -> tuple[View, ...]:
        """Top, front and right views in the arrangement ``projection`` names, placed
        from the part's own extents. ``iso=True`` adds an isometric in the free
        corner, at a standard scale, and returns it last.

        ``views`` names the principal views to draw, returned in the order top,
        front, right. A turned or symmetric part shows the same picture from two
        sides; drawing both says nothing twice, so name the ones that differ
        (``views=("front", "right")`` for a shaft along X). The render says when
        two views drawn are the same picture.

        The positions returned are provisional: when the sheet renders, the views
        are laid out again with each gap sized to the dimensions and callouts the
        facing views actually carry, so annotation added after this call gets
        room. ``gap`` fixes the clear space between views instead.

        On a sheet made with ``size=None`` or ``scale=None``, the first call
        chooses them for this part (see :class:`Sheet`)."""
        names = tuple(views)
        if not names or len(set(names)) != len(names) or any(n not in _VIEW_NAMES for n in names):
            raise ValueError(f"three_views(views={views!r}): name each of {_VIEW_NAMES} at most once, at least one "
                             "of them; the isometric comes from iso=True")
        names = tuple(n for n in _VIEW_NAMES if n in names)
        size = shape.bounding_box().size
        arranged = _Arrangement(size, gap, _view_extent(shape, "iso", 1.0) if iso else False, names)
        if self._chooses():
            _settle(self, _choose_size_and_scale(self, size, arranged.iso, _default_rooms(), gap, names=names))
        slots, _over = _arrange_three_views(self, size, gap, self._scale(), arranged.iso, names=names)
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
                view._auto_label = (view.label, view.scale)
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
        parent_scale = view.scale or self._scale()
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
        detail._detail = _Detail(view, _p3(center), r, letter, at is None, chosen)
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
        n, outline = _flat_face(view.shape, _p3(point))
        for name, (direction, _up) in VIEW_DIRECTIONS.items():
            if name != "iso" and _dot(n, direction) > 1 - 1e-6:
                raise ValueError(f"the face at {_where(point)} faces the {name} view square on; draw that view "
                                 "rather than an auxiliary one")
        look = _look(view)
        if abs(_dot(n, look)) > 1e-6:
            raise ValueError(
                f"the face at {_where(point)} is not seen edge-on in the {view.name} view: an auxiliary view is "
                "projected from the view that shows its face as a line. A face inclined to every principal view "
                "needs a secondary auxiliary view, which is not drawn."
            )
        # Up is the parent's up laid onto the face, so the face's slope runs up the sheet.
        parent_up = _dirs(view)[1]
        up = tuple(u - _dot(parent_up, n) * c for u, c in zip(parent_up, n))
        if math.sqrt(_dot(up, up)) < 1e-6:
            up = tuple(u - _dot(look, n) * c for u, c in zip(look, n))
        length = math.sqrt(_dot(up, up))
        up = tuple(c / length for c in up)
        own = scale if scale is not None else view.scale
        # The label is settled when the sheet renders, its scale being known then.
        aux = View(self, view.shape, "auxiliary", corner or (0.0, 0.0), None, view.hidden, view.centre_marks, own)
        aux._direction = (n, up)
        aux._aux = _Aux(view, _p3(point), letter, corner is None, outline if partial else None)
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
            raise TypeError("Sheet.parts_list() takes the PartsList that cadgen.eng_drawing.parts_list() returns, "
                            f"got {type(parts).__name__}")
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
            if fits < 1:
                raise ValueError(f"the {self._size()} sheet has no room above its title block for a parts list "
                                 "(its revision table takes it); draw the list on a larger sheet")
            raise ValueError(
                f"a parts list of {last - first + 1} items needs {(last - first + 2) * _LIST_ROW:.0f} mm above the "
                f"title block, and {self._size()} has {room:.0f}. Draw items {first} to {first + fits - 1} here "
                f"(parts_list(parts, last={first + fits - 1})) and the rest on a further sheet "
                f"(parts_list(parts, first={first + fits}))."
            )
        self._parts = _ListRun(parts, first, last)
        return self

    def view(self, shape, name: str, *, at, label: str | None = None, hidden: bool = True, centre_marks: bool = True,
             scale: float | None = None) -> View:
        if name not in VIEW_DIRECTIONS:
            raise ValueError(f"unknown view {name!r}; one of {sorted(VIEW_DIRECTIONS)}")
        if scale is not None and not (scale > 0):
            raise ValueError("a view's scale must be positive")
        _require_settled(self)  # a view placed by hand is placed on a sheet of known size and scale
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
    from cadgen._internal.drawing_features import (
        holes as find_holes, revolved, slots as find_slots, turned_surfaces,
    )

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
        shown = (item.description or f"ITEM {item.number}", item.material, _item_subtitle(item, title))
        sheet = Sheet(title=shown[0], material=shown[1], subtitle=shown[2], general_tolerance=general_tolerance,
                      **(common | {"size": None, "scale": None}))
        sheet._item = _PartOf(item, title, shown)
        shape = item.shape
        turned = revolved(shape)
        if turned is not None and turned.axis != 0:
            size = shape.bounding_box().size
            if (size.X, size.Y, size.Z)[turned.axis] > turned.diameter:
                # A long turned part is drawn lying down, as it sits in a lathe: its
                # axis across the sheet, where the paper is widest.
                from build123d import Rot

                shape = (Rot(0, 90, 0) if turned.axis == 2 else Rot(0, 0, -90)) * shape
                turned = revolved(shape)
        names = list(_VIEW_NAMES)
        if turned is not None:
            # Turned whole: the two views square to its axis draw the same picture,
            # so the first of them in front, top, right order is drawn.
            beside = [n for n in ("front", "top", "right") if not VIEW_DIRECTIONS[n][0][turned.axis]]
            names.remove(beside[1])
        views = sheet.three_views(shape, iso=True, views=names)[:-1]
        stated: set[int] = set()  # the model axes whose overall size is stated
        if turned is not None:
            # Its diameters, across the profile in the view that sees the axis
            # side-on; the largest states the part's size across the axis both ways.
            side = next(v for v in views if not VIEW_DIRECTIONS[v.name][0][turned.axis])
            unit = tuple(float(k == turned.axis) for k in range(3))
            across = _cross(unit, _look(side))
            steps = [(s.diameter, s.middle) for s in turned_surfaces(shape)
                     if abs(abs(s.axis[turned.axis]) - 1) < 1e-9]
            if all(abs(d - turned.diameter) > 0.01 for d, _m in steps):
                steps.append((turned.diameter, turned.at))
            for diameter, middle in steps:
                r = diameter / 2
                side.dim(tuple(m + r * c for m, c in zip(middle, across)),
                         tuple(m - r * c for m, c in zip(middle, across)), text="%%c<>")
            stated = {k for k in range(3) if k != turned.axis}
        for view in views:
            width_axis, height_axis = _view_axes(view.name)
            if width_axis not in stated or height_axis not in stated:
                view.overall(width=width_axis not in stated, height=height_axis not in stated)
            stated |= {width_axis, height_axis}
        features = [*find_holes(shape), *find_slots(shape)]
        for view in views:
            look = _look(view)
            if any(_looks_into(f, look) for f in features):
                view.holes()
        by_item[item.number] = sheet
    return AssemblySheets([ga, *more, *by_item.values()], parts, by_item)


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
            facts = _Facts()
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
