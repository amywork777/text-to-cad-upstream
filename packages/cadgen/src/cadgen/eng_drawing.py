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

from cadgen._internal.drawing_annotation import (
    _Dim, _Features, _HoleTable, _callout_value, _draw_hole_table, _draw_hole_tags, _faces_viewer, _hole_table,
    _plan_view, _resolve_view, _shows, _slot_faces_viewer, _tol_suffix,
)
from cadgen._internal.drawing_assembly import (
    _GA_LIST_SHARE, Item, _PartOf, PartsList, _arrange_assembly, _continuations, _draw_balloons, _item_subtitle,
    parts_list, _refresh_from_item,
)
from cadgen._internal.drawing_base import (
    _CENTRE_OVERSHOOT, _DETAIL_SIZE, _DIM_ROW, _HATCH_SCALE, _LAYERS, _MARGIN, _MIN_TEXT_MM, _NOTE_HEIGHT,
    _NOTE_INSET, _PLANE_ROOM, PROJECTIONS, _SAME_PLACE, _SECTION_LETTERS, SHEET_SIZES, _STANDARD_SCALES,
    _SYMBOL_ADVANCE, _TITLE_H, _TITLE_W, UNITS, VIEW_DIRECTIONS, _dimstyle, _dirs, _dot, _draw_dimension_symbols,
    _draw_symbol, _fmt, _ink_width, _look, _mtext_extent, _p3, _runs, _scale_label, _shown, _spans, _text_box,
    _text_width, _where,
)
from cadgen._internal.drawing_report import _Facts, geometry_notes, _member_key, _merge_facts, _unstated
from cadgen._internal.drawing_sheet import (
    _AIR, _LARGEST_SCALE, _LIST_ROW, _SIZES_CHOSEN, _SIZES_SMALLEST_FIRST, _OffFrame, _arrange_three_views,
    _assert_views_fit, _choose_for_breaks, _choose_size_and_scale, _default_rooms, _draw_furniture, _list_height,
    _list_room, _next_smaller, _place_box, _place_detail, _require_settled, _settle, _within,
)
from cadgen._internal.drawing_views import (
    _BREAK_GAP, _PLANE_SHOWN_ON, _Projection, _axis_lines, _bbox_bounds, _break_cuts, _break_hides, _break_shift,
    _broken_shape, _broken_size, _centres, _circles, _clip_runs, _cut, _draw_break_lines, _draw_cutting_plane,
    _edge_points, _edge_polyline, _edges_bounds, _end_on, _flat_face, _merge_centre_lines, _model_to_sheet, _on_cut,
    _sheet_axis, _view_extent, _wire_points,
)


__all__ = ["eng_drawing", "Sheet", "View", "SHEET_SIZES", "parts_list", "PartsList", "Item", "assembly_sheets",
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
    #: Which overall sizes ``overall()`` asked for: {"width", "height"}, or empty.
    _overall: frozenset = frozenset()
    #: ``(letter, model point or None)`` when :meth:`section` made this a section.
    _section: tuple | None = None
    #: ``(label, scale)`` the arrangement gave an isometric, so the render knows
    #: whether the author has since set their own and leaves it alone.
    _auto_label: tuple | None = None
    #: Set when :meth:`Sheet.detail` made this a detail view.
    _detail: _Detail | None = None
    #: ``(bounding-box size, gap, iso extent or False)`` when :meth:`Sheet.three_views`
    #: placed this view, one tuple shared by the arrangement's views: the render
    #: lays them out again from it, and the off-frame guard does at each candidate
    #: scale. None for a hand-placed ``at=``, which does not move.
    _arranged: tuple | None = None
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
        self._table = _TableSpec(None if origin is None else _p3(origin), corner)
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


def _refuse_used_letter(sheet, letter: str, view=None) -> None:
    """A letter names one section or one detail per sheet: two DETAIL Bs, or a
    DETAIL A beside SECTION A-A, send a reader to the wrong view."""
    if sheet is None:
        return
    for other in sheet.views:
        if other is view:
            continue
        if other._detail is not None and other._detail.letter == letter:
            raise ValueError(f"letter {letter} already names DETAIL {letter} on this sheet; pick another letter")
        if other._detail is None and other._section is not None and other._section[0] == letter:
            raise ValueError(f"letter {letter} already names SECTION {letter}-{letter} on this sheet; pick another letter")
        if other._aux is not None and other._aux.letter == letter:
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
        if self.size is not None:
            self._check_notes(self.size)

    def _check_notes(self, paper: str) -> None:
        """A note wider than the sheet runs off the paper, and the sheet is the one
        thing here that cannot be made bigger after the fact. Measure the line the
        sheet DRAWS -- numbered, prefixed, general tolerance expanded -- at the
        height it draws it, against the room ``paper`` gives it."""
        room = SHEET_SIZES[paper][0] - 2 * (_MARGIN + _NOTE_INSET)
        for line, note in zip(self.note_lines(), self.drawn_notes()):
            if _text_width(line, _NOTE_HEIGHT) > room:
                raise ValueError(
                    f"note {note!r} is wider than the {paper} sheet's note row "
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
        if self._chooses():
            _settle(self, _choose_size_and_scale(self, size, arranged[2], _default_rooms(), gap))
        slots = _arrange_three_views(self, size, gap, self._scale(), arranged[2])
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


#: The arrow on a view an auxiliary view is projected from: its head's distance
#: from the face, its tail's, and the letter's beyond the tail.
_AUX_ARROW = (5.0, 20.0, 4.0)


def _place_auxiliaries(sheet: Sheet, work: list, occupied: list, s: float) -> None:
    """Label each auxiliary view, and place each one the sheet places in the free
    paper nearest the view it is projected from."""
    for view, _proj, bounds, _items, plan, _centre in work:
        if view._aux is None:
            continue
        sv = view.scale or s
        # The label states the view's scale when it is not the sheet's.
        view.label = f"VIEW {view._aux.letter}" + (f" ({_scale_label(sv)})" if abs(sv - s) > 1e-12 else "")
        if not view._aux.placed_by_sheet:
            continue
        room = plan["room"]
        w = (bounds[1] - bounds[0]) * sv + room["left"] + room["right"]
        h = (bounds[3] - bounds[2]) * sv + room["bottom"] + room["top"]
        spot = _place_box(sheet, w, h, occupied, view._aux.parent.at)
        if spot is None:
            raise _OffFrame(f"VIEW {view._aux.letter}: no free paper on {sheet._size()} for it at {_scale_label(sv)}. "
                            "Give it at=, a smaller scale or a larger sheet.", _next_smaller(s))
        view.at = (spot[0] + room["left"] + (bounds[1] - bounds[0]) * sv / 2,
                   spot[1] - room["top"] - (bounds[3] - bounds[2]) * sv / 2)
        occupied.append((spot[0], spot[0] + w, spot[1] - h, spot[1]))


def _place_hole_tables(sheet: Sheet, tables: dict, occupied: list, s: float) -> None:
    """Put each hole table in the free paper nearest its view, or at the corner its
    author gave, which must be on the paper and clear of everything else."""
    for view in sheet.views:
        if id(view) not in tables:
            continue
        table = tables[id(view)]
        w, h = table.size
        if view._table.corner is None:
            spot = _place_box(sheet, w, h, occupied, view.at)
            if spot is None:
                raise _OffFrame(
                    f"{view.name}.hole_table(): no free paper on {sheet._size()} for a {w:.0f} x {h:.0f} mm table. "
                    "Give it at=, a smaller scale or a larger sheet.", _next_smaller(s))
        else:
            spot = view._table.corner
            box = (spot[0], spot[0] + w, spot[1] - h, spot[1])
            m = _MARGIN
            if box[0] < m or box[1] > sheet.width - m or box[2] < m or box[3] > sheet.height - m:
                raise ValueError(f"{view.name}.hole_table(at={spot}): a {w:.0f} x {h:.0f} mm table there runs off "
                                 f"the {sheet._size()} sheet's frame")
            furniture = (sheet.width - m - _TITLE_W, sheet.width - m, m, m + _TITLE_H + _list_height(sheet))
            if any(box[0] < o[1] and box[1] > o[0] and box[2] < o[3] and box[3] > o[2]
                   for o in [*occupied, furniture]):
                raise ValueError(f"{view.name}.hole_table(at={spot}): the table there is drawn over a view, its "
                                 "annotation or the title block; leave at= out to let the sheet place it")
        table.corner = spot
        occupied.append((spot[0] - 4.0, spot[0] + w + 4.0, spot[1] - h - 4.0, spot[1] + 4.0))


def _check_clear_of_parts_list(sheet: Sheet, placed: list, index: int) -> None:
    """Refuse a view drawn over the parts list, which would print both illegible."""
    if sheet._parts is None:
        return
    x_block, y_title = sheet.width - _MARGIN - _TITLE_W, _MARGIN + _TITLE_H
    y_list = y_title + _list_height(sheet)
    for view, _proj, _bounds, _cx, _cy, box in placed:
        if box[1] > x_block + 1e-6 and box[2] < y_list - 1e-6 and box[3] > y_title:
            raise ValueError(
                f"sheet {index}: the {view.name} view is drawn over the parts list, which stands on the title "
                f"block from {x_block:.0f} mm across and up to {y_list:.0f} mm. Place the view clear of it, or "
                "draw at a smaller scale."
            )


def _draw_aux_arrows(msp, sheet: Sheet, drawn: dict, text, th: float) -> None:
    """On each view an auxiliary view is projected from, an arrow pointing at the
    face the way the auxiliary view looks, and its letter."""
    from ezdxf.enums import TextEntityAlignment

    head_at, tail_at, letter_at = _AUX_ARROW
    for view in sheet.views:
        if view._aux is None or id(view._aux.parent) not in drawn or id(view) not in drawn:
            continue
        _parent_view, parent_to_sheet, _box = drawn[id(view._aux.parent)]
        point, n = view._aux.point, view._direction[0]
        tip = parent_to_sheet(point)
        ahead = parent_to_sheet(tuple(p + c for p, c in zip(point, n)))
        run = math.hypot(ahead[0] - tip[0], ahead[1] - tip[1]) or 1.0
        d = ((ahead[0] - tip[0]) / run, (ahead[1] - tip[1]) / run)
        head = (tip[0] + d[0] * head_at, tip[1] + d[1] * head_at)
        tail = (tip[0] + d[0] * tail_at, tip[1] + d[1] * tail_at)
        msp.add_leader([head, tail], dxfattribs={"layer": "NOTES"},
                       override={"dimasz": th, "dimldrblk": "_CLOSEDFILLED"})
        text(view._aux.letter, tail[0] + d[0] * letter_at, tail[1] + d[1] * letter_at, th + 1.5,
             TextEntityAlignment.MIDDLE_CENTER, "NOTES")


def _render_sheet(sheet: Sheet, *, index: int, count: int, label: str, warnings: list | None = None,
                  facts: _Facts | None = None, continued: dict | None = None):
    """Build the ezdxf document for one sheet. Returns the document.

    A sheet that leaves its size or scale to itself and runs out of paper -- its
    views off the frame, no free paper for a detail, a table or balloons -- is
    drawn again rather than refused, those being the sheet's choices, not the
    author's: on the next size up if it chooses its size, at the next standard
    scale down if it chooses its scale. Only the drawing that succeeds reports
    anything.
    """
    if sheet._item is not None:
        _refresh_from_item(sheet)
    floor, ceiling = 0, None
    tried: set = set()
    while True:
        tried_warnings: list = []
        tried_facts = _Facts()
        try:
            doc = _draw_sheet(sheet, index=index, count=count, label=label, warnings=tried_warnings,
                              facts=tried_facts, continued=continued, floor=floor, ceiling=ceiling)
        except _OffFrame as exc:
            attempt = (sheet._size(), sheet._scale())
            if not sheet._chooses() or attempt in tried:
                raise
            tried.add(attempt)
            index_now = _SIZES_SMALLEST_FIRST.index(attempt[0])
            if sheet.size is None and index_now < len(_SIZES_CHOSEN) - 1:
                # A larger sheet is for room, not for a larger scale.
                floor = index_now + 1
                if sheet.scale is None:
                    ceiling = min(ceiling or _LARGEST_SCALE, attempt[1])
                continue
            if sheet.scale is None and exc.fits is not None and exc.fits < attempt[1]:
                ceiling = exc.fits
                continue
            raise
        if warnings is not None:
            warnings.extend(tried_warnings)
        if facts is not None:
            _merge_facts(facts, tried_facts)
        return doc


def _draw_sheet(sheet: Sheet, *, index: int, count: int, label: str, warnings: list | None = None,
                facts: _Facts | None = None, continued: dict | None = None, floor: int = 0,
                ceiling: float | None = None):
    """Build the ezdxf document for one sheet at its scale. Returns the document.
    ``floor`` and ``ceiling`` bound a size or scale the sheet chooses (see
    :func:`_render_sheet`).

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
    _require_settled(sheet)
    breaks = any(view._break is not None for view in sheet.views)
    if sheet._chooses() and breaks:
        # A break leaves a fixed gap of paper, so its views are drawn at the scale
        # the sheet settles on now, not at the one three_views() guessed.
        _choose_for_breaks(sheet, floor, ceiling)
    s = sheet._scale()
    work = []
    tables: dict[int, _HoleTable] = {}
    outlines: dict[int, list] = {}
    breaks_checked: set = set()
    cuts: dict[int, tuple] = {}
    checked: set[int] = set()
    # The assemblies this sheet draws as assemblies: the one its parts list was
    # read from, and any a view balloons. Many solids there are the point.
    assemblies = {id(parts.assembly) for view in sheet.views for parts in view._balloons}
    if sheet._parts is not None:
        assemblies.add(id(sheet._parts.parts.assembly))
    for view in sheet.views:
        if view._detail is not None:
            # A detail shows what its parent shows when the sheet renders, so a
            # section() made after detail() still reaches it.
            parent = view._detail.parent
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
            if (id(view.shape), view._break) not in breaks_checked:
                breaks_checked.add((id(view.shape), view._break))
                if _break_hides(view.shape, view._break) and warnings is not None:
                    axis, lo, hi = view._break
                    warnings.append(
                        f"the break from {'XYZ'[axis]} = {_fmt(lo)} to {_fmt(hi)} hides some of the part: it is not "
                        "the same section all along that stretch. Move the break to where the part does not change."
                    )
        shift = _break_shift(view._break, gap) if view._break is not None else None
        proj = _Projection(view.shape, _dirs(view), draw=draw, shift=shift)
        if view._break is not None:
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
            c2, r = proj.point(view._detail.centre), view._detail.radius
            bounds, centre = (c2[0] - r, c2[0] + r, c2[1] - r, c2[1] + r), c2
        elif view._aux is not None and view._aux.outline is not None:
            # A partial auxiliary view is its face's outline, whatever lies within it.
            ring = [proj.point(p) for p in view._aux.outline]
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
            tables[id(view)] = _hole_table(view, proj, part_features(view.shape), cut, items)
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
    if sheet._chooses() and not breaks:
        groups_seen = {id(view._arranged): view for view, *_rest in work if view._arranged is not None}
        if len(groups_seen) == 1:
            first = next(iter(groups_seen.values()))
            rooms = {view.name: plan["room"] for view, _proj, _bounds, _items, plan, _centre in work
                     if view._arranged is first._arranged}
            size, gap, iso = first._arranged
            _settle(sheet, _choose_size_and_scale(sheet, size, iso, rooms, gap, floor=floor, ceiling=ceiling))
        else:
            # Several arrangements, or none: no one layout to choose by, so the
            # earlier choice stands, held within the bounds a retry set.
            _settle(sheet, _within(sheet, floor, ceiling))
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
        for name, at, own, slot_label in _arrange_three_views(sheet, size, gap, s, iso, room, over):
            if name in by_name:
                view = by_name[name]
                view.at = at
                if name == "iso" and (view._auto_label is None or (view.label, view.scale) == view._auto_label):
                    view.scale, view.label = own, slot_label
                    view._auto_label = (slot_label, own)
        groups.append((by_name, shape, size, gap, iso, room))
        if gap is None and max(over) > _AIR and warnings is not None:
            # The views were squeezed together past the air between them, so one
            # view's annotation now crowds the next. Say what gives them the room.
            def roomy(scale: float) -> bool:
                over_at: list = []
                _arrange_three_views(sheet, size, None, scale, iso, room, over_at)
                return max(over_at) <= 0

            roomier = next((name for name in sorted(SHEET_SIZES, key=lambda n: SHEET_SIZES[n][0])
                            if SHEET_SIZES[name][0] > sheet.width), None)
            smaller = next((c for c in _STANDARD_SCALES if c < s and roomy(c)), None)
            remedies = [f'Sheet("{roomier}")' if roomier else None,
                        f"Sheet(scale={smaller:g}) ({_scale_label(smaller)})" if smaller else None]
            ask = max(((name, side, value) for name, sides in room.items() for side, value in sides.items()),
                      key=lambda t: t[2])
            warnings.append(
                f"views crowded: their dimensions and callouts need {max(over):.0f} mm more than {sheet._size()} "
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
        if (view._detail is not None and view._detail.placed_by_sheet) or (
                view._aux is not None and view._aux.placed_by_sheet):
            continue
        sv = view.scale or s
        room = plan["room"]
        occupied.append((view.at[0] + (bounds[0] - cx) * sv - room["left"], view.at[0] + (bounds[1] - cx) * sv + room["right"],
                         view.at[1] + (bounds[2] - cy) * sv - room["bottom"], view.at[1] + (bounds[3] - cy) * sv + room["top"]))
    centres = {id(item[0]): (item[1], item[5]) for item in work}
    for view in sheet.views:
        # Each detail's circle and letter on its parent are paper a detail cannot use.
        if view._detail is None or id(view._detail.parent) not in centres:
            continue
        parent, point, radius, _letter, _auto, _chosen = view._detail
        parent_proj, parent_centre = centres[id(parent)]
        ps = parent.scale or s
        x, y = (parent.at[k] + (parent_proj.point(point)[k] - parent_centre[k]) * ps for k in (0, 1))
        ring = radius * ps + th + 4.0
        occupied.append((x - ring, x + ring, y - ring, y + ring))
    for view, _proj, _bounds, _items, plan, _centre in work:
        if view._detail is None or not view._detail.placed_by_sheet:
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
            raise _OffFrame(
                f"DETAIL {letter}: no free paper on {sheet._size()} for a {2 * radius * tries[-1]:.0f} mm circle at "
                f"{_scale_label(tries[-1])} and its annotation. Give it at=, a smaller scale=, or a larger sheet.",
                _next_smaller(s))
        size = 2 * radius * view.scale
        view.at = spot
        room = plan["room"]
        occupied.append((spot[0] - size / 2 - room["left"], spot[0] + size / 2 + room["right"],
                         spot[1] - size / 2 - room["bottom"], spot[1] + size / 2 + room["top"]))
    _place_auxiliaries(sheet, work, occupied, s)
    _place_hole_tables(sheet, tables, occupied, s)

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
    _check_clear_of_parts_list(sheet, placed, index)
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
        facts.of_list(parts)["listed"].update(range(first, last + 1))
    for (view, proj, bounds, items, plan, _centre), (_v, _p, _b, cx, cy, own_box) in zip(work, placed):
        sv = view.scale or s
        cut = cuts.get(id(view))
        record = None
        if facts is not None:
            record = facts.parts.setdefault(id(view.shape), {"shape": view.shape, "called": set(), "values": [],
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

            region = Point(view.at).buffer(view._detail.radius * sv, quad_segs=64)
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
                return _shows(view, proj, feature, run, cut)

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
            msp.add_circle(view.at, view._detail.radius * sv, dxfattribs={"layer": "NOTES"})
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
                    axis, low, high = view._break
                    inside = [p for p in (dim.p1, dim.p2) if low < p[axis] < high]
                    if inside and warnings is not None:
                        warnings.append(f"{view.name} dim {dim.index}: {_where(inside[0])} is inside the break, which "
                                        "the view leaves out; dimension to a point the view shows.")
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
            _draw_hole_tags(msp, tables[id(view)], proj, to_sheet, sv, th, text)
            if record is not None:
                record["called"].update(_member_key(row.feature) for row in tables[id(view)].rows)
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
        if view._detail is None or id(view._detail.parent) not in drawn or id(view) not in drawn:
            continue
        parent, point, radius, letter, _auto, _chosen = view._detail
        _parent_view, parent_to_sheet, _box = drawn[id(parent)]
        c = parent_to_sheet(point)
        ring = radius * (parent.scale or s)
        msp.add_circle(c, ring, dxfattribs={"layer": "NOTES"})
        lean = (math.cos(math.radians(45)), math.sin(math.radians(45)))
        text(letter, c[0] + lean[0] * (ring + th), c[1] + lean[1] * (ring + th), th + 1.5,
             TextEntityAlignment.MIDDLE_CENTER, "NOTES")
    _draw_aux_arrows(msp, sheet, drawn, text, th)
    _merge_centre_lines(msp)
    return doc


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
        shown = (item.description or f"ITEM {item.number}", item.material, _item_subtitle(item, title))
        sheet = Sheet(title=shown[0], material=shown[1], subtitle=shown[2], general_tolerance=general_tolerance,
                      **(common | {"size": None, "scale": None}))
        sheet._item = _PartOf(item, title, shown)
        top, front, right = sheet.three_views(item.shape, iso=True)[:3]
        top.overall()
        front.overall(width=False)
        features = [*find_holes(item.shape), *find_slots(item.shape)]
        for view in (top, front, right):
            look = _look(view)
            if any(abs(_dot(f.axis, look)) > 1 - 1e-6
                   and (_slot_faces_viewer(f, look) if hasattr(f, "width") else _faces_viewer(f, look))
                   for f in features):
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
