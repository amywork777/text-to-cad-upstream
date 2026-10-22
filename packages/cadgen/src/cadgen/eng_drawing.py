"""Engineering drawings: ``@eng_drawing``, :class:`Sheet` and :class:`View`.

An engineering drawing is a DOCUMENT derived from a part: orthographic views
projected from the part's geometry, dimensions that reference points ON that
geometry, centre marks found on it, a sheet frame and a title block. Because
every view and every dimension is computed from the shape at run time, the
drawing follows the part: change the model, rerun the drawing script, and the
views, hidden lines and measured values move with it. Nothing on the sheet is
drawn by hand.

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
        top = sheet.view(part, "top", at=(110, 190))
        front = sheet.view(part, "front", at=(110, 90))
        top.overall()                                    # width and height
        top.dim((-35, 25, 0), (35, 25, 0))               # model coordinates
        top.hole((35, 25, 15), 3, depth=8, count=4)
        return sheet                                     # or [sheet1, sheet2]

    if __name__ == "__main__":
        bracket_drawing()

Running the script writes one PDF at ``out`` with a page per sheet. There is no
default location: ``out`` is the path the caller passes. A live build123d shape
works in place of ``read_step``; the part is whatever geometry the function has.

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
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

__all__ = ["eng_drawing", "Sheet", "View", "SHEET_SIZES"]

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
    #: ``(bounding-box size, gap, iso)`` when :meth:`Sheet.three_views` placed this
    #: view, so the off-frame guard can lay the same arrangement out again at a
    #: candidate scale. None for a hand-placed ``at=``, which does not move.
    _arranged: tuple | None = None

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

    def holes(self, *, angle: float = 45.0) -> "View":
        """Call out every hole this view looks down, one callout per kind of hole
        (``4× ⌀5.5 THRU``, ``⌀28 THRU``), each read off the part and placed on
        the hole nearest the edge of the view so its leader is short. A blind
        hole that opens on the far side belongs to the opposite view."""
        self._dims.append(_Dim("holes", (0.0, 0.0, 0.0), None, 0.0, None, None, angle=float(angle)))
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
        letter = str(letter).upper()
        if len(letter) != 1 or letter not in _SECTION_LETTERS:
            raise ValueError(f"section letter must be one of {_SECTION_LETTERS} (ISO 128-40 leaves out I, O "
                             f"and Q), got {letter!r}")
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


def _fmt(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


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
    size = spec["thread"] if spec.get("thread") else f"%%c{_fmt(spec['diameter'])}"
    size += _tol_suffix(tol) + (f" {fit}" if fit else "")
    if spec.get("thru"):
        size += " THRU"
    elif spec.get("depth") is not None:
        size += f" \u21a7{_fmt(spec['depth'])}"
    parts.append(lead + size)
    if spec.get("cbore"):
        d, depth = spec["cbore"]
        parts.append(f"\u2334 %%c{_fmt(d)} \u21a7{_fmt(depth)}")
    if spec.get("csk"):
        d, ang = spec["csk"]
        parts.append(f"\u2335 %%c{_fmt(d)} × {_fmt(ang)}°")
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


@dataclass
class Sheet:
    """One sheet of a drawing: a frame, a title block and the views placed on it.

    ``at`` positions on views are the sheet's own millimetres with the origin at
    the sheet's bottom-left corner; ``scale`` is drawing scale (1 = 1:1, 0.5 = 1:2).
    """

    size: str = "A3"
    scale: float = 1.0
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
    views: list[View] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.size not in SHEET_SIZES:
            raise ValueError(f"unknown sheet size {self.size!r}; one of {sorted(SHEET_SIZES)}")
        if not (self.scale > 0):
            raise ValueError("scale must be positive")
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
        # A note wider than the sheet runs off the paper, and the sheet is the one
        # thing here that cannot be made bigger after the fact. Measure the line
        # the sheet DRAWS -- numbered, prefixed, general tolerance expanded -- at
        # the height it draws it, against the room it has.
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
        return SHEET_SIZES[self.size][0]

    @property
    def height(self) -> float:
        return SHEET_SIZES[self.size][1]

    def three_views(self, shape, *, gap: float | None = None, hidden: bool = True, centre_marks: bool = True,
                    iso: bool = False) -> tuple[View, View, View] | tuple[View, View, View, View]:
        """Top, front and right views in the arrangement ``projection`` names, placed
        from the part's own extents. ``iso=True`` adds an isometric in the free
        corner, at a standard scale, and returns it fourth.

        The positions returned are provisional: when the sheet renders, the views
        are laid out again with each gap sized to the dimensions and callouts the
        facing views actually carry, so annotation added after this call gets
        room. ``gap`` fixes the clear space between views instead."""
        size = shape.bounding_box().size
        arranged = (size, gap, _view_extent(shape, "iso", 1.0) if iso else False)
        slots = _arrange_three_views(self, shape, size, gap, self.scale, arranged[2])
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
        return views

    def view(self, shape, name: str, *, at, label: str | None = None, hidden: bool = True, centre_marks: bool = True,
             scale: float | None = None) -> View:
        if name not in VIEW_DIRECTIONS:
            raise ValueError(f"unknown view {name!r}; one of {sorted(VIEW_DIRECTIONS)}")
        if scale is not None and not (scale > 0):
            raise ValueError("a view's scale must be positive")
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

        direction, up = VIEW_DIRECTIONS[name]
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

    def point(self, p) -> tuple[float, float]:
        return self._raw_point(p)


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
    from build123d import GeomType

    n = 2 if edge.geom_type == GeomType.LINE else samples
    return [(float(v.X), float(v.Y)) for v in (edge.position_at(i / (n - 1)) for i in range(n))]


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
                         room: dict | None = None) -> list[tuple[str, tuple[float, float], float | None, str | None]]:
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
    x_lo, x_hi = m + 4.0, sheet.width - m - 4.0
    y_lo, y_hi = m + _TITLE_H + notes_h + 4.0, sheet.height - m - 4.0
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
    raise ValueError(
        f"sheet {index} ({sheet.size}, scale {_scale_label(sheet.scale)}): the {names} view"
        f"{'s run' if len(over) > 1 else ' runs'} off the frame. {remedy}"
    )


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


def _text_box(value: str, x: float, y: float, height: float, align) -> tuple[float, float, float, float]:
    """The rectangle a TEXT entity occupies, from its anchor and alignment."""
    width = _text_width(value, height)
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


def _hole_spec(hole, count: int, thread: str | None = None, label: str | None = None) -> dict:
    return {"diameter": hole.diameter, "depth": hole.depth, "thru": hole.thru, "cbore": hole.cbore,
            "csk": hole.csk, "count": count, "thread": thread, "label": label}


def _outer_radius(spec: dict) -> float:
    """Where a callout's leader ends: on the outermost circle the hole shows, so the
    arrow does not cross a counterbore to reach the bore inside it."""
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
    if dim.kind == "hole":
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


def _resolve_view(view: View, proj, bounds, part_holes, warnings: list | None) -> list["_Dim"]:
    """The view's annotation with every size the part decides filled in from the
    part, on copies: a hole callout's diameter, depth, counterbore, countersink and
    count, a diameter or radius callout's value, and ``holes()`` expanded into one
    callout per kind of hole. Anything the author typed is checked on the way."""
    import dataclasses

    look = VIEW_DIRECTIONS[view.name][0]
    seen_cache: list | None = None

    def seen() -> list:
        nonlocal seen_cache
        if seen_cache is None:
            seen_cache = [h for h in part_holes(view.shape) if abs(_dot(h.axis, look)) > 1 - 1e-6]
        return seen_cache

    out: list[_Dim] = []
    for index, dim in enumerate(view._dims):
        if dim.kind == "hole":
            resolved = [_resolve_hole(view, proj, dim, seen(), look)]
        elif dim.kind == "holes":
            resolved = _expand_holes(view, proj, bounds, dim, seen(), look, warnings)
        elif dim.kind in ("diameter", "radius"):
            resolved = [_resolve_round(view, proj, dim)]
        else:
            resolved = [dataclasses.replace(dim)]
        for item in resolved:
            item.index = index
        out.extend(resolved)
    return out


def _resolve_hole(view: View, proj, dim: "_Dim", seen, look) -> "_Dim":
    import dataclasses

    given, thread, label = dim.hole["given"], dim.hole["thread"], dim.hole["label"]
    call = f"{view.name}.hole({_where(dim.p1)})"
    target = proj.point(dim.p1)
    here = [h for h in seen if _near(proj.point(h.mouth), target)]
    if not here:
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
    spec = _hole_spec(hole, len(same), thread, label)
    return dataclasses.replace(dim, hole=spec, radius=_outer_radius(spec), feature=hole)


def _expand_holes(view: View, proj, bounds, dim: "_Dim", seen, look, warnings: list | None) -> list["_Dim"]:
    import dataclasses

    groups: dict[tuple, list] = {}
    for hole in seen:
        if _faces_viewer(hole, look):
            groups.setdefault(hole.signature(), []).append(hole)
    if not groups:
        if warnings is not None:
            warnings.append(f"{view.name}.holes(): the {view.name} view looks down no hole, so it calls nothing out.")
        return []
    x0, x1 = bounds[0], bounds[1]

    def short_way_out(hole) -> tuple:
        p = proj.point(hole.mouth)
        return (round(min(p[0] - x0, x1 - p[0]), 6), -round(p[1], 6))

    out = []
    for members in sorted(groups.values(), key=lambda g: (-g[0].diameter, g[0].signature())):
        hole = min(members, key=short_way_out)
        spec = _hole_spec(hole, len(members))
        out.append(dataclasses.replace(dim, kind="hole", p1=hole.mouth, hole=spec, radius=_outer_radius(spec),
                                       feature=hole))
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
        if dim.kind in ("hole", "diameter", "radius"):
            # The side a callout prefers is its hole's own half of the view, the
            # short way out, past every dimension row on that side.
            side = "right" if proj.point(dim.p1)[0] > cx + 1e-6 else "left"
            text = _callout_value(dim).replace("%%c", "Ø")
            room[side] = max(room[side], rowed[side] + 10.0 + 8.0 + _text_width(text, th) + 2.0)
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
    room["bottom"] += 6.0 + 3.5 + 2.0  # the view's label hangs under everything below it
    return {"rows": rows, "overall": overall, "room": room}


def _axis_lines(view: View, proj, part_axes, to_sheet) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Centre lines for the turned features a view sees from the side: a shaft's
    axis, a hole drawn hidden through a plate. Axes that land on one drawn line
    (two holes one behind the other, a shaft's steps) merge into one line, which
    runs ``_CENTRE_OVERSHOOT`` past the feature at each end."""
    look = VIEW_DIRECTIONS[view.name][0]
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
    look = VIEW_DIRECTIONS[view.name][0]
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


def _draw_furniture(msp, sheet: Sheet, *, index: int, count: int, label: str, text) -> None:
    """Frame, zone grid, title block and notes: what makes a page a drawing sheet."""
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
    text(sheet.title, x0 + tx + 3.0, y0 + ty + th / 2 + 1.0, 5.0, A.MIDDLE_LEFT, fit=_TITLE_FIT)
    # The script that drew the sheet, so a print leads back to its source.
    text(label, x0 + tx + 3.0, y0 + ty + 1.4, _CAPTION_HEIGHT, A.BOTTOM_LEFT, fit=_TITLE_FIT)
    px, py, pw, ph = _TITLE_CELLS["PROJECTION"]
    right = _projection_symbol(msp, x0 + px + 4.0, y0 + py + ph / 2, first_angle=sheet.projection == "FIRST ANGLE")
    text(sheet.projection, right + 4.0, y0 + py + ph / 2, 2.5, A.MIDDLE_LEFT, fit=x0 + px + pw - right - 6.0)

    lines = sheet.note_lines()
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
    look = VIEW_DIRECTIONS[view.name][0]
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


def _model_to_sheet(proj, at, centre, scale, point) -> tuple[float, float]:
    """Where a model point lands on the sheet in a placed view."""
    x, y = proj.point(point)
    return (at[0] + (x - centre[0]) * scale, at[1] + (y - centre[1]) * scale)


def _bbox_bounds(shape, proj) -> tuple[float, float, float, float]:
    """A part's projected (x0, x1, y0, y1), from its bounding box's corners."""
    bb = shape.bounding_box()
    points = [proj.point((x, y, z)) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y)
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
    parent_look = VIEW_DIRECTIONS[_view.name][0]
    along = (parent_look[1] * look[2] - parent_look[2] * look[1], parent_look[2] * look[0] - parent_look[0] * look[2],
             parent_look[0] * look[1] - parent_look[1] * look[0])
    p0 = model_to_sheet(point)
    p1 = model_to_sheet(tuple(a + b for a, b in zip(point, along)))
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1.0
    u = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
    ts = [(x - p0[0]) * u[0] + (y - p0[1]) * u[1] for x in box[:2] for y in box[2:]]
    a = (p0[0] + u[0] * (min(ts) - 6.0), p0[1] + u[1] * (min(ts) - 6.0))
    b = (p0[0] + u[0] * (max(ts) + 6.0), p0[1] + u[1] * (max(ts) + 6.0))
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
        head = (end[0] + d[0] * 9.0, end[1] + d[1] * 9.0)
        msp.add_leader([head, end], dxfattribs={"layer": "DIM"},
                       override={"dimasz": th * 0.85, "dimldrblk": "_CLOSEDFILLED"})
        text(letter, head[0] + d[0] * (th + 1.0), head[1] + d[1] * (th + 1.0), th + 1.5,
             TextEntityAlignment.MIDDLE_CENTER, "NOTES")


def _render_sheet(sheet: Sheet, *, index: int, count: int, label: str, warnings: list | None = None,
                  facts: dict | None = None):
    """Build the ezdxf document for one sheet. Returns the document.

    ``warnings`` collects anything the sheet renders but a reader should look
    at -- a dimension whose points miss the geometry, say. The render never
    stops for one: it is the PDF that answers whether the sheet is right.
    ``facts`` collects what the sheet states about each part (holes called out,
    values dimensioned), so the drawing can say what it leaves unstated.
    """
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    from cadgen._internal.drawing_features import axes as find_axes, holes as find_holes

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
        entity = msp.add_text(value, dxfattribs={"height": height, "layer": layer})
        entity.set_placement((x, y), align=align)
        if layer in ("DIM", "NOTES") and value:
            claim(value, _text_box(value, x, y, height, align))
        return entity

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

    _draw_furniture(msp, sheet, index=index, count=count, label=label, text=text)

    # What the part's faces say, read once per part however many views show it.
    found_holes: dict[int, list] = {}
    found_axes: dict[int, list] = {}

    def part_holes(shape) -> list:
        if id(shape) not in found_holes:
            found_holes[id(shape)] = find_holes(shape)
        return found_holes[id(shape)]

    def part_axes(shape) -> list:
        if id(shape) not in found_axes:
            found_axes[id(shape)] = find_axes(shape)
        return found_axes[id(shape)]

    # Every view is projected, its callouts read off the part and its annotation
    # planned before anything is placed, so the layout knows what each view carries.
    s = sheet.scale
    work = []
    cuts: dict[int, tuple] = {}
    for view in sheet.views:
        cut = _cut(view) if view._section else None
        proj = _Projection(view.shape, view.name, draw=cut[0] if cut else None)
        bounds = _edges_bounds(list(proj.visible) + (list(proj.hidden) if view.hidden else []))
        if not bounds:
            continue
        if cut:
            # Centred on the WHOLE part, so the section lines up with the views
            # beside it even when the half it keeps is not symmetric.
            cuts[id(view)] = cut
            corners = _bbox_bounds(view.shape, proj)
            centre = ((corners[0] + corners[1]) / 2, (corners[2] + corners[3]) / 2)
        else:
            centre = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2)
        items = _resolve_view(view, proj, bounds, part_holes, warnings)
        work.append((view, proj, bounds, items, _plan_view(view, proj, bounds, items, sheet), centre))

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
        for name, at, own, slot_label in _arrange_three_views(sheet, shape, size, gap, s, iso, room):
            if name in by_name:
                by_name[name].at = at
                if name == "iso":
                    by_name[name].scale, by_name[name].label = own, slot_label
        groups.append((by_name, shape, size, gap, iso, room))

    placed = []
    for view, proj, bounds, _items, _plan, (cx, cy) in work:
        bx0, bx1, by0, by1 = bounds
        sv = view.scale or s
        placed.append((view, proj, bounds, cx, cy,
                       (view.at[0] + (bx0 - cx) * sv, view.at[0] + (bx1 - cx) * sv,
                        view.at[1] + (by0 - cy) * sv, view.at[1] + (by1 - cy) * sv)))
    boxes = [box for (_, _, _, _, _, box) in placed]
    _assert_views_fit(sheet, placed, index=index, groups=groups)
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
    for (view, proj, bounds, items, plan, _centre), (_v, _p, _b, cx, cy, own_box) in zip(work, placed):
        sv = view.scale or s
        cut = cuts.get(id(view))
        record = None
        if facts is not None:
            record = facts.setdefault(id(view.shape), {"shape": view.shape, "called": set(), "values": [],
                                                       "axes": set(), "views": []})
            if view.name != "iso":
                record["views"].append(view.name)

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

            for edge in edges:
                # A circular edge stays a CIRCLE or ARC: exact on the sheet, so a hole
                # reads as a hole and a fillet as a radius rather than as a polyline.
                if edge.geom_type == GeomType.CIRCLE:
                    c = to_sheet((edge.arc_center.X, edge.arc_center.Y))
                    r = edge.radius * sv
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
        if cut:
            from ezdxf import const

            # The cut faces, hatched: what the section is there to show.
            for face in cut[1]:
                hatch = msp.add_hatch(dxfattribs={"layer": "HATCH"})
                hatch.set_pattern_fill("ANSI31", scale=_HATCH_SCALE)
                for k, wire in enumerate([face.outer_wire(), *face.inner_wires()]):
                    hatch.paths.add_polyline_path(
                        [to_sheet(proj.point(point)) for point in _wire_points(wire)], is_closed=True,
                        flags=const.BOUNDARY_PATH_EXTERNAL if k == 0 else const.BOUNDARY_PATH_DEFAULT)
        if view.centre_marks:
            # One cross per CENTRE, sized to the largest circle on it. A counterbore
            # is two concentric circles, and two crosses drawn over each other fill
            # the CENTER linetype's gaps in: the centre line printed solid, which is
            # the one thing its dashes are there to say it is not.
            # A section cuts its bores and bosses in half, which leaves no full
            # cylinder to find their axes by; the whole part's axes that lie on the
            # kept side of the plane (or in it) are the section's.
            turned = part_axes(view.shape)
            if cut:
                look = VIEW_DIRECTIONS[view.name][0]
                turned = [a for a in turned if max(_dot(tuple(e - c for e, c in zip(end, cut[2])), look)
                                                   for end in (a.start, a.end)) <= 1e-6]
            for centre, radius in _centres(_circles(proj.visible) + _end_on(view, proj, turned)):
                c = to_sheet(centre)
                arm = radius * sv + 2.0
                msp.add_line((c[0] - arm, c[1]), (c[0] + arm, c[1]), dxfattribs={"layer": "CENTER"})
                msp.add_line((c[0], c[1] - arm), (c[0], c[1] + arm), dxfattribs={"layer": "CENTER"})
            # And a centre line down every turned feature seen from the side: a
            # shaft's axis, a bore drawn hidden through a plate.
            for a, b in _axis_lines(view, proj, turned, to_sheet):
                msp.add_line(a, b, dxfattribs={"layer": "CENTER"})
        vx0, vx1, vy0, vy1 = own_box

        # How far annotation already reaches past each side of the view, so a
        # callout lands outside the dimensions on its side. Callouts on one side
        # share a knee and stack upward instead of pushing each other outward.
        reach = {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
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

        def linear(a, b, offset, side, row, override, orientation, tol=None, fit=None):
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
            if tol:
                # The deviations are the author's, in true size, and ezdxf prints them
                # as given -- dimlfac scales the measurement, not the tolerance.
                style_override |= {"dimtol": 1, "dimtp": tol[0], "dimtm": tol[1],
                                   "dimtdec": 2, "dimtfac": 0.7}
            span = abs(b[0] - a[0]) if horizontal else abs(b[1] - a[1])
            # A value wider than the space between its extension lines is set beside
            # them, on the dimension line's side, instead of across them: centred,
            # "3 WALL" printed with both witness lines running through its glyphs.
            # One that fits stays centred and only its arrows go outside.
            printed = label.replace("<>", _fmt(span / sv)).replace("%%c", "Ø")
            width = _text_width(printed, th) + (_text_width(_tol_suffix(tol), th * 0.7) if tol else 0.0)
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
            state(span / sv, _sheet_axis(proj, horizontal))

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

        # Dimensions first, in the rows the plan gave them, then the overall pair
        # outermost, then the callouts outside all of them, then notes and angles.
        for dim in items:
            if dim.kind == "linear":
                a, b = model_to_sheet(dim.p1), model_to_sheet(dim.p2)
                check("dim", dim.index, a, b)
                linear(a, b, dim.offset, dim.side, dim.row, dim.text, dim.orientation, dim.tol, dim.fit)
        if "width" in view._overall:
            linear((vx0, vy1), (vx1, vy1), None, "top", plan["overall"]["top"], None, "h")
        if "height" in view._overall:
            linear((vx0, vy0), (vx0, vy1), None, "left", plan["overall"]["left"], None, "v")
        for dim in items:
            if dim.kind not in ("diameter", "radius", "hole"):
                continue
            # A callout: a radial leader from the circle to a horizontal landing
            # outside the view, past whatever dimensions stand on that side, with
            # the text reading along the landing. Stacked callouts on one side land
            # at their own hole's height.
            centre = model_to_sheet(dim.p1)
            check(dim.kind, dim.index, centre)
            r = dim.radius * sv
            value = _callout_value(dim)
            text_w = 8.0 + _text_width(value.replace("%%c", "Ø"), th)
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
            if record is not None:
                if dim.kind == "hole" and dim.feature is not None:
                    record["called"].add(_hole_key(dim.feature))
                record["values"].append(2 * dim.radius if dim.kind == "diameter" else dim.radius)
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
                msp.add_leader([p, q, (q[0] + (3 if dim.radius >= 0 else -3), q[1])], dxfattribs={"layer": "NOTES"})
                align = TextEntityAlignment.BOTTOM_LEFT if dim.radius >= 0 else TextEntityAlignment.BOTTOM_RIGHT
                text(dim.text, q[0] + (4 if dim.radius >= 0 else -4), q[1] + 1, th, align, "NOTES")

        # The view label goes under everything that hangs below the view, so a
        # dimension on the bottom side never sits on it.
        text((view.label or view.name).upper(), view.at[0], vy0 - reach["bottom"] - 6, 3.5,
             TextEntityAlignment.TOP_CENTER, "NOTES")

    # Each section's cutting plane, on a view that sees it edge-on.
    for view_id, (kept, _faces, point) in cuts.items():
        view = drawn[view_id][0]
        letter, look = view._section[0], VIEW_DIRECTIONS[view.name][0]
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
    return doc


def _hole_key(hole) -> tuple:
    """Holes one callout covers: the same kind of hole along the same line of sight."""
    from cadgen._internal.drawing_features import _canonical

    return (hole.signature(), tuple(round(c, 4) for c in _canonical(hole.axis, (0.0, 0.0, 0.0))[0]))


def _unstated(facts: dict) -> list[str]:
    """What the drawing leaves out that a shop needs to make the part.

    Read off the part, not guessed at: every kind of hole it has, its overall
    size along each axis, and every turned diameter, each checked against what
    the sheets call out or measure. A drawing is allowed to be unfinished; it
    is not allowed to look finished when it is not, so each line names the call
    that states the missing fact.
    """
    from cadgen._internal.drawing_features import holes as find_holes, turned_diameters

    lines: list[str] = []
    for record in facts.values():
        shape, views = record["shape"], record["views"]
        kinds: dict[tuple, list] = {}
        for hole in find_holes(shape):
            kinds.setdefault(_hole_key(hole), []).append(hole)
        for key, members in kinds.items():
            if key in record["called"]:
                continue
            hole = members[0]
            text = _shown(hole_callout_text(_hole_spec(hole, len(members))))
            where = next((name for name in views
                          if abs(_dot(hole.axis, VIEW_DIRECTIONS[name][0])) > 1 - 1e-6
                          and _faces_viewer(hole, VIEW_DIRECTIONS[name][0])), None)
            fix = (f"{where}.hole({_where(hole.mouth)}) states it, or {where}.holes() calls out every hole "
                   f"the {where} view looks down." if where else
                   "No view on the drawing looks into it; add the view that sees it as a circle.")
            lines.append(f"incomplete: {text} is not called out. {fix}")
        size = shape.bounding_box().size
        turned = turned_diameters(shape)
        # A stated diameter of the part's largest turned surface states its width
        # across that axis too: a shaft's ⌀30 is its size in Y and in Z.
        across = [d for d in turned if any(abs(v - d) <= 0.01 for v in record["values"])]
        for axis, extent in enumerate((size.X, size.Y, size.Z)):
            if any(a == axis and abs(v - extent) <= 0.01 for a, v in record["axes"]):
                continue
            if any(abs(d - extent) <= 0.01 for d in across):
                continue
            where = next((name for name in views if abs(VIEW_DIRECTIONS[name][0][axis]) < 1e-9), None)
            fix = f"{where}.overall() states it." if where else "No view on the drawing shows that direction."
            lines.append(f"incomplete: the overall size along {'XYZ'[axis]} ({_fmt(extent)}) is not dimensioned. {fix}")
        for diameter in turned:
            if any(abs(v - diameter) <= 0.01 for v in record["values"]):
                continue
            lines.append(
                f"incomplete: the turned diameter ⌀{_fmt(diameter)} is not dimensioned. Dimension it across its "
                f"profile with text=\"%%c<>\", or diameter(..., size={_fmt(diameter)}) where it is seen as a circle."
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
            for index, sheet in enumerate(sheets, start=1):
                doc = _render_sheet(sheet, index=index, count=len(sheets), label=fn.__name__,
                                    warnings=notices, facts=facts)
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
                        print(f"{fn.__name__} sheet {index} {finding.render()}")
                docs.append(doc)
            # What the drawing does not state, across every sheet of it: printed, not
            # raised, because a sheet of views is a drawing before it is a finished one.
            notices.extend(_unstated(facts))
            for notice in notices:
                print(f"{fn.__name__}: {notice}")
            _write_pdf(docs, sheets, target)
            print(f"wrote {target} ({len(sheets)} page{'s' if len(sheets) != 1 else ''})")
            return [target]

        run.__cadgen_eng_drawing__ = True  # type: ignore[attr-defined]
        return _counted(run)

    return apply(func) if func is not None else apply
