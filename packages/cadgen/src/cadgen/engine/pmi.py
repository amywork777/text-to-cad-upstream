"""Semantic PMI: manufacturing requirements on a part's own faces, kept in its XCAF document
as XCAF's GD&T objects and written to STEP AP242 as AP242's semantic entities.

A model gives its part annotations, each on faces of that part, and returns the part::

    from cadgen.engine import pmi, step, xbf

    @xbf(out="XBF/plate.xbf")
    @step("plate.step")
    def plate():
        body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
        bottom = body.faces().sort_by(bd.Axis.Z)[0]
        top = body.faces().sort_by(bd.Axis.Z)[-1]
        hole = body.faces().filter_by(bd.GeomType.CYLINDER)[0]
        return pmi.annotate(body,
            pmi.datum("A", bottom),
            pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus(0.2)),
            pmi.diameter("hole", hole, tolerance=pmi.plus_minus(0.1, 0)),
            pmi.flatness("top-flat", top, 0.05),
            pmi.position("hole-pos", hole, 0.1, datums=["A"]))

**What is held.** What the code says and what this build's geometry resolves, nothing else: XCAF's
``XCAFDimTolObjects`` objects on the GD&T tool's labels (``XCAFDoc_DimTolTool``) hold the kind,
values and units (millimetres, the document's) and link the annotation to the sub-shape labels of
the faces it is on; beside each, a ``TDF_Reference`` to its part's shape label and one cadgen
attribute (``EXTRA_GUID``, JSON of ``SCHEMA``) holding what XCAF has no place for: the author's id
and label, the kind, each ref as the code wrote it, the presentation, and an annotation linked to
nothing its values (XCAF gives values meaning only through geometry). The id and the kind are in
XCAF too (its semantic name, its object). No status, no problem and nothing of a previous build is
held: an annotation's status is derived where the document is read (``records_of_document``), as a
build derives it. The STEP writer reads the XCAF objects and writes AP242's semantic PMI
(``DIMENSIONAL_SIZE``/``DIMENSIONAL_LOCATION`` with ``PLUS_MINUS_TOLERANCE``,
``DATUM``/``DATUM_FEATURE``, ``FLATNESS_TOLERANCE``, ``POSITION_TOLERANCE`` with its
``DATUM_SYSTEM``) on ``SHAPE_ASPECT``s whose ``GEOMETRIC_ITEM_SPECIFIC_USAGE`` names the face.
The cadgen attribute is not written to a STEP.

**Values.** A dimension's nominal is the geometry's, measured at document time: a cylinder's
diameter, the distance between two parallel planes. No nominal is typed in. A tolerance is held
only where the code gives one (``plus_minus``: signed deviations, upper above lower). XCAF holds
a dimension's lower deviation as a magnitude and the STEP writer negates it, so ``plus_minus(0.2)``
is written ``TOLERANCE_VALUE(-0.2, 0.2)``; the conversion is this module's, both ways.

**References.** A ref is a face of the part annotated: a build123d ``Face`` of the shape given to
``annotate`` (numbered against it at once), or a ref in the engine's grammar (``refs``) -- an
element name (``f:plate.body.6``), the canonical ``owner/element`` ref a document serves, or an
ordinal (``face 7``). Element names are the engine's persistent naming (``kernel.trace``): a face
keeps its name across edits that do not change how it is made. Each build resolves every ref
against the part as built now: ``ok``; ``missing`` -- it names nothing (with what the name's atom
is called now, where anything is); ``ambiguous`` -- it names several faces (each listed); or
``invalid`` -- it names a face the annotation cannot stand on (a diameter on a plane, two planes
not parallel, a datum letter the part does not define). An annotation's status is its worst ref's.
One not ``ok`` is kept in the document, with its values and refs as written, and linked to no
geometry; the build reports it, and a STEP export refuses to drop it. A ref written as text that
names another kind of face than on the model's last build (a hole whose name passed to a flat side
of the cut that replaced it) is warned of (``warn``): the build's report and its served structure
say so, the document never.

**A document another system wrote** (a vendor's STEP, or an xbf converted from one) lists its
GD&T as XCAF reads it. What this module does not hold whole -- another characteristic or dimension
type, limits, a fit, a modifier, a datum target, a link to an edge or a point -- is listed
``unsupported`` with its XCAF type and why, never refused and never read as less than it says.
An xbf converted from it copies its GD&T as read (``copy``); an export of it says what it leaves
out (``dropped``) where one of a document the code made is refused (``refuse_dropped``).

**Presentation** (``place``) is where a viewer draws an annotation: an anchor and a text offset in
millimetres, in the annotated part's frame. It is no part of the semantic record: it is never
written to a STEP, and moving it changes nothing an annotation means.

**Scope.** What is written and read back is verified end to end (the engine's PMI tests, with
an AP242 reader of no OCCT):
datums on a plane or cylinder; diameter and linear-distance dimensions with a plus-minus
tolerance; basic (theoretically exact) distances, from planes and hole axes, with no tolerance,
marked as AP242 marks them (CAx-IF's 'theoretical' dimension note); flatness; position with an
ordered datum reference frame and a diametral zone. Every
other XCAF characteristic, dimension type, modifier and tolerance form is refused by name
(``PMIUnsupported``), never approximated. PMI is part-level: an annotation is on one part, and an
assembly is refused.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

__all__ = ["DIMENSION_TYPES", "GEOMETRIC_CHARACTERISTICS", "PMIError", "PMIUnsupported", "annotate", "basic", "datum",
           "diameter", "dimension", "distance", "flatness", "geometric", "place", "plus_minus", "position", "read"]

# The attribute an annotated shape holds its annotations in (a tuple of plain dicts), as a part's
# configurations are held (``kernel.memo`` keys it).
PMI = "xbf_pmi"
# The GUID of the cadgen attribute beside each XCAF GD&T object, and its JSON's schema (see the
# module): an attribute of another schema is not read.
EXTRA_GUID = "5d3a7c1e-9f42-4b86-a0e5-3c7b9d2f6e18"
SCHEMA = "cadgen.pmi/1"
# The GD&T tool's label under the main label (``XCAFDoc_DocumentTool::DimTolLabel``).
DIMTOL_TAG = 4
STATUSES = ("ok", "missing", "ambiguous", "invalid")
# A basic dimension's mark in AP242 (CAx-IF PMI Recommended Practices 4.1, 5.3, Table 7): the
# descriptive item's name and description.
THEORETICAL = ("dimensional note", "theoretical")
UNIT = "mm"

# The dimension types and geometric characteristics written and read back, verified; every other
# XCAF one is refused by name.
DIMENSION_TYPES = ("diameter", "distance")
GEOMETRIC_CHARACTERISTICS = ("flatness", "position")
# XCAF's other characteristics, so a request for one is refused as unsupported rather than unknown.
_XCAF_CHARACTERISTICS = ("angularity", "circular_runout", "circularity_or_roundness", "coaxiality", "concentricity",
                         "cylindricity", "flatness", "line_profile", "parallelism", "perpendicularity", "position",
                         "straightness", "surface_profile", "symmetry", "total_runout")
_XCAF_DIMENSION_TYPES = ("diameter", "distance", "radius", "angle", "curved_distance", "linear_distance",
                         "spherical_diameter", "spherical_radius", "toroidal_minor_diameter", "thickness")
# The faces each annotation stands on.
# A basic dimension is a distance between planes, a plane and a hole's axis, or two axes.
_SURFACES = {"datum": ("plane", "cylinder"), "diameter": ("cylinder",), "distance": ("plane",),
             "basic": ("plane", "cylinder"),
             "flatness": ("plane",), "position": ("cylinder",)}


class PMIError(ValueError):
    """An annotation the code gave wrongly: said by name, before anything is written."""


class PMIUnsupported(PMIError):
    """An annotation outside what this module writes and reads back verified: refused by name,
    never approximated."""


# --- authoring -------------------------------------------------------------------------------


def plus_minus(upper: float, lower: float | None = None) -> dict[str, Any]:
    """A plus-minus tolerance: signed deviations from the nominal, ``lower`` below ``upper``
    (``-upper`` when not given: ``plus_minus(0.2)`` is ±0.2; ``plus_minus(0.1, 0)`` is +0.1/0)."""
    upper = _number(upper, "a tolerance's upper deviation")
    lower = -upper if lower is None else _number(lower, "a tolerance's lower deviation")
    if not upper > lower:
        raise PMIError(f"a plus-minus tolerance's upper deviation is above its lower ({lower}), not {upper}")
    return {"type": "plus_minus", "upper": upper, "lower": lower}


def place(anchor: Iterable[float], offset: Iterable[float] = (0.0, 0.0, 0.0)) -> dict[str, Any]:
    """Where a viewer draws an annotation (provisional): ``anchor`` on or near its feature and the
    text ``offset`` from it, millimetres in the annotated part's frame. Not semantic: never in a
    STEP, and moving it changes nothing the annotation means."""
    return {"anchor": _point(anchor, "an anchor"), "offset": _point(offset, "an offset")}


def datum(letter: str, ref: Any, *, label: str | None = None, presentation: dict | None = None) -> dict[str, Any]:
    """Datum ``letter`` (``A``..``Z``) on a planar or cylindrical face. Its id is its letter."""
    if not isinstance(letter, str) or len(letter) != 1 or not letter.isascii() or not letter.isupper():
        raise PMIError(f"a datum's letter is one capital A..Z, not {letter!r}")
    return _annotation(letter, "datum", [("feature", ref)], label, presentation, datum={"letter": letter})


def dimension(id: str, type: str, *refs: Any, tolerance: dict | None = None, basic: bool = False,
              label: str | None = None, presentation: dict | None = None) -> dict[str, Any]:
    """A dimension of ``type`` (``DIMENSION_TYPES``) between ``refs``; its nominal is measured
    from the geometry. ``basic``: theoretically exact (ASME's basic, ISO's theoretical), a
    distance with no tolerance that locates what a geometric tolerance controls. Other types
    are refused (``PMIUnsupported``)."""
    if basic and tolerance is not None:
        raise PMIError(f"dimension {id!r}: a basic dimension is theoretically exact: it takes no tolerance")
    if basic and type != "distance":
        raise PMIUnsupported(f"dimension {id!r}: a basic {type} is not written verified yet; a basic dimension "
                             "is a distance")
    if type not in DIMENSION_TYPES:
        if type in _XCAF_DIMENSION_TYPES:
            raise PMIUnsupported(f"dimension {id!r}: a {type} dimension is not written verified yet; "
                                 f"the types are {', '.join(DIMENSION_TYPES)}")
        raise PMIError(f"dimension {id!r}: no dimension type {type!r}; the types are {', '.join(DIMENSION_TYPES)}")
    wanted = 1 if type == "diameter" else 2
    if len(refs) != wanted:
        raise PMIError(f"dimension {id!r}: a {type} dimension is on {wanted} face{'s' if wanted > 1 else ''}, "
                       f"not {len(refs)}")
    roles = ["feature"] if wanted == 1 else ["from", "to"]
    return _annotation(id, "dimension", list(zip(roles, refs)), label, presentation,
                       dimension={"type": type, "basic": bool(basic), "tolerance": _tolerance(tolerance, id)})


def diameter(id: str, ref: Any, *, tolerance: dict | None = None, label: str | None = None,
             presentation: dict | None = None) -> dict[str, Any]:
    """The diameter of a cylindrical face (a hole, a boss), measured; ``tolerance`` given explicitly."""
    return dimension(id, "diameter", ref, tolerance=tolerance, label=label, presentation=presentation)


def distance(id: str, ref_from: Any, ref_to: Any, *, tolerance: dict | None = None, label: str | None = None,
             presentation: dict | None = None) -> dict[str, Any]:
    """The distance between two parallel planar faces, measured; ``tolerance`` given explicitly."""
    return dimension(id, "distance", ref_from, ref_to, tolerance=tolerance, label=label, presentation=presentation)


def basic(id: str, ref_from: Any, ref_to: Any, *, label: str | None = None,
          presentation: dict | None = None) -> dict[str, Any]:
    """A basic (theoretically exact) distance, measured, with no tolerance: between two parallel
    planes, from a plane to a hole's axis parallel to it, or between two parallel axes. What a
    position tolerance's true position is located by."""
    return dimension(id, "distance", ref_from, ref_to, basic=True, label=label, presentation=presentation)


def geometric(id: str, characteristic: str, ref: Any, value: float, *, datums: Iterable[str] = (),
              diameter_zone: bool = False, label: str | None = None, presentation: dict | None = None) -> dict[str, Any]:
    """A geometric tolerance of ``characteristic`` (``GEOMETRIC_CHARACTERISTICS``) of ``value``
    millimetres on one face, referring to ``datums`` in order (primary first); a diametral zone
    with ``diameter_zone``. Other characteristics are refused (``PMIUnsupported``)."""
    if characteristic not in GEOMETRIC_CHARACTERISTICS:
        if characteristic in _XCAF_CHARACTERISTICS:
            raise PMIUnsupported(f"tolerance {id!r}: {characteristic} is not written verified yet; the "
                                 f"characteristics are {', '.join(GEOMETRIC_CHARACTERISTICS)}")
        raise PMIError(f"tolerance {id!r}: no characteristic {characteristic!r}; the characteristics are "
                       f"{', '.join(GEOMETRIC_CHARACTERISTICS)}")
    value = _number(value, f"tolerance {id!r}'s value")
    if not value > 0:
        raise PMIError(f"tolerance {id!r}: a tolerance zone is wider than 0, not {value}")
    letters = list(datums)
    for letter in letters:
        if not isinstance(letter, str) or len(letter) != 1 or not letter.isupper():
            raise PMIError(f"tolerance {id!r}: a datum is named by its letter, not {letter!r}")
    if len(set(letters)) != len(letters):
        raise PMIError(f"tolerance {id!r}: a datum is named once in a frame, not {letters}")
    if len(letters) > 3:
        raise PMIError(f"tolerance {id!r}: a datum reference frame has three datums at most, not {len(letters)}")
    if characteristic == "flatness" and (letters or diameter_zone):
        raise PMIError(f"tolerance {id!r}: flatness is a form tolerance, with no datum and no diametral zone")
    if characteristic == "position" and not letters:
        raise PMIUnsupported(f"tolerance {id!r}: a position with no datum is not written verified yet; name its datums")
    return _annotation(id, "geometric_tolerance", [("feature", ref)], label, presentation,
                       geometric_tolerance={"characteristic": characteristic, "value": value, "unit": UNIT,
                                            "zone": "diameter" if diameter_zone else None, "modifier": None,
                                            "datums": letters})


def flatness(id: str, ref: Any, value: float, *, label: str | None = None,
             presentation: dict | None = None) -> dict[str, Any]:
    """Flatness of ``value`` millimetres on a planar face."""
    return geometric(id, "flatness", ref, value, label=label, presentation=presentation)


def position(id: str, ref: Any, value: float, *, datums: Iterable[str], diameter_zone: bool = True,
             label: str | None = None, presentation: dict | None = None) -> dict[str, Any]:
    """Position of a cylindrical feature (a hole's axis), ``value`` millimetres, a diametral
    zone by default, relative to ``datums`` in order."""
    return geometric(id, "position", ref, value, datums=datums, diameter_zone=diameter_zone, label=label,
                     presentation=presentation)


def annotate(shape: Any, *annotations: dict[str, Any]) -> Any:
    """``shape`` given ``annotations`` (replacing any it held): the part a model returns, or
    one part of its assembly. A ``Face`` given as a ref is numbered against ``shape`` now. Ids are
    unique on a part, as are datum letters, and a datum holds one place in every frame that
    names it (XCAF holds one position per datum). Returns ``shape``."""
    import build123d as bd

    if not isinstance(shape, bd.Shape) or getattr(shape, "wrapped", None) is None:
        raise PMIError(f"pmi.annotate() takes the part its annotations are on, not {type(shape).__name__}")
    if getattr(shape, "children", None):
        raise PMIUnsupported("pmi.annotate() is given one part: assembly-level PMI is not written yet; annotate "
                             "each part")
    held: list[dict[str, Any]] = []
    ids: set[str] = set()
    places: dict[str, tuple[int, str]] = {}
    faces = None
    for given in annotations:
        if not isinstance(given, dict) or given.get("pmi") != 1:
            raise PMIError(f"pmi.annotate() takes annotations made by pmi.datum(), pmi.diameter(), ...: "
                           f"not {given!r}")
        if given["id"] in ids:
            raise PMIError(f"two annotations on one part are {given['id']!r}: an id is unique")
        ids.add(given["id"])
        refs = []
        for ref in given["refs"]:
            target = ref["target"]
            if isinstance(target, str):
                refs.append({"role": ref["role"], "written": target, "face": None})
                continue
            if faces is None:
                faces = _faces(shape.wrapped)
            ordinal = faces.FindIndex(target.wrapped)
            refs.append({"role": ref["role"], "written": f"face {ordinal}" if ordinal else "a face of another shape",
                         "face": ordinal or 0})
        entry = {key: value for key, value in given.items() if key != "refs"}
        entry["refs"] = refs
        for at, letter in enumerate((given.get("geometric_tolerance") or {}).get("datums") or (), 1):
            if letter in places and places[letter][0] != at:
                raise PMIUnsupported(f"datum {letter} is datum {places[letter][0]} of {places[letter][1]!r} and datum "
                                     f"{at} of {given['id']!r}: XCAF holds one position per datum")
            places.setdefault(letter, (at, given["id"]))
        held.append(entry)
    letters = [entry["datum"]["letter"] for entry in held if entry["kind"] == "datum"]
    if len(set(letters)) != len(letters):
        raise PMIError(f"a part defines each datum letter once, not {letters}")
    shape.__dict__[PMI] = tuple(held)
    _note_call(held)
    return shape


def _annotation(id: str, kind: str, refs: list[tuple[str, Any]], label: str | None, presentation: dict | None,
                **values: Any) -> dict[str, Any]:
    import build123d as bd

    if not isinstance(id, str) or not id.strip():
        raise PMIError(f"an annotation's id is a non-empty string, not {id!r}")
    if label is not None and not isinstance(label, str):
        raise PMIError(f"annotation {id!r}: a label is a string, not {label!r}")
    for _role, target in refs:
        if not isinstance(target, (str, bd.Face)):
            raise PMIError(f"annotation {id!r}: a ref is a face of the part -- a build123d Face, or a ref such as "
                           f"'f:plate.body.6' or 'face 7' -- not {type(target).__name__}")
    if presentation is not None and (not isinstance(presentation, dict) or set(presentation) != {"anchor", "offset"}):
        raise PMIError(f"annotation {id!r}: a presentation is pmi.place(anchor, offset)")
    return {"pmi": 1, "id": id, "kind": kind, "label": label, "presentation": presentation,
            "refs": [{"role": role, "target": target} for role, target in refs], **values}


def _tolerance(tolerance: dict | None, id: str) -> dict | None:
    if tolerance is None:
        return None
    if not isinstance(tolerance, dict) or tolerance.get("type") != "plus_minus":
        raise PMIUnsupported(f"dimension {id!r}: a tolerance is pmi.plus_minus(...); limits, fits and "
                             "general tolerances are not written yet")
    return dict(tolerance)


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PMIError(f"{what} is a finite number, not {value!r}")
    return float(value)


def _point(value: Any, what: str) -> list[float]:
    try:
        found = [_number(item, what) for item in value]
    except TypeError:
        found = []
    if len(found) != 3:
        raise PMIError(f"{what} is three numbers, millimetres, not {value!r}")
    return found


def _note_call(held: list[dict[str, Any]]) -> None:
    """``annotate``'s annotations, kept on the build's run under the model whose body gave them."""
    from cadgen.engine.refs import _current_run

    run = _current_run()
    if run is not None:
        run.pmi.setdefault(run.scope, []).extend(_text(entry) for entry in held)


def unattached(run: Any, scope: str, tree: Any) -> list[str]:
    """The ids of the annotations the model ``scope``'s body gave to a shape its result does not
    hold (one a later operation replaced), each once."""
    held = {_text(entry) for _part, given in tree.pmi for entry in given}
    return sorted({json.loads(text)["id"] for text in run.pmi.get(scope, ()) if text not in held})


def _text(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


# --- document time: harvest and resolve --------------------------------------------------------


def harvest(obj: Any, part: Any, held: dict[int, tuple[Any, tuple]], path: str) -> None:
    """The annotations ``obj`` holds, for the part prototype it is (``document.collect``): one
    geometry placed twice with two sets of annotations is refused by name."""
    given = obj.__dict__.get(PMI) if obj is not None else None
    if not given:
        return
    found = held.get(id(part))
    if found is not None and found[1] != given:
        raise PMIError(f"{path}: one part placed twice is given two sets of annotations; PMI is on the part, once")
    held[id(part)] = (part, given)


def refuse_assembly(obj: Any, path: str) -> None:
    if obj is not None and obj.__dict__.get(PMI):
        raise PMIUnsupported(f"{path}: an assembly is annotated; assembly-level PMI is not written yet: annotate "
                             "each part")


@dataclass
class Ref:
    role: str
    written: str
    ordinal: int | None
    status: str
    candidates: list[int] = field(default_factory=list)
    problem: str | None = None


@dataclass
class Resolved:
    """One annotation as the part is built now: its refs resolved, its status, and its nominal."""

    spec: dict[str, Any]
    refs: list[Ref]
    status: str
    problem: str | None
    nominal: float | None = None


def resolve(tree: Any) -> list[tuple[Any, list[Resolved]]]:
    """Each annotated part of ``tree`` (named: ``Part.names``) with its annotations resolved
    against it, in the tree's order, made once per tree."""
    if tree.pmi_resolved is not None:
        return tree.pmi_resolved
    found = []
    for part, given in tree.pmi or ():
        names = list((part.names or {}).get("faces") or [])
        found.append((part, _resolved_part(given, part.shape, names, {part.name, tree.root.name})))
    tree.pmi_resolved = found
    return found


def _resolved_part(given: Iterable[dict[str, Any]], shape: Any, names: list[str | None],
                   owners: set[str]) -> list[Resolved]:
    """A part's annotations (as the code gives them) resolved against its ``shape``, whose faces
    are named ``names`` by ordinal, in the document owned as ``owners`` name it."""
    given = list(given)
    faces = _faces(shape)
    letters = {entry["datum"]["letter"] for entry in given if entry["kind"] == "datum"}
    return [_resolved(entry, faces, names, owners, letters) for entry in given]


def _resolved(spec: dict[str, Any], faces: Any, names: list[str | None], owners: set[str],
              letters: set[str]) -> Resolved:
    """One annotation against the part as built: each ref, then the faces it names against the
    faces its kind stands on (``_SURFACES``), then its nominal measured."""
    refs = [_ref(given, faces, names, owners) for given in spec["refs"]]
    nominal = None
    problem = next((ref.problem for ref in refs if ref.status != "ok"), None)
    if all(ref.status == "ok" for ref in refs):
        surfaces = [_surface(faces.FindKey(ref.ordinal)) for ref in refs]
        what = _what(spec)
        wanted = _SURFACES[what]
        for ref, surface in zip(refs, surfaces):
            if surface[0] not in wanted:
                ref.status = "invalid"
                ref.problem = (f"{ref.written} is a {surface[0]} face; a {what.replace('_', ' ')} is on a "
                               f"{' or '.join(wanted)} face")
        if all(ref.status == "ok" for ref in refs):
            if what == "diameter":
                nominal = 2.0 * surfaces[0][1]["radius"]
            elif what in ("distance", "basic"):
                nominal, why = _separation([faces.FindKey(ref.ordinal) for ref in refs], [ref.written for ref in refs])
                if why is not None:
                    refs[1].status, refs[1].problem = "invalid", why
        problem = next((ref.problem for ref in refs if ref.status != "ok"), None)
    status = _worst(ref.status for ref in refs)
    if status == "ok" and spec["kind"] == "geometric_tolerance":
        undefined = [letter for letter in spec["geometric_tolerance"]["datums"] if letter not in letters]
        if undefined:
            status, problem = "invalid", f"datum {', '.join(undefined)} is not defined on this part"
    return Resolved(spec, refs, status, problem, nominal)


def _what(spec: dict[str, Any]) -> str:
    """What an annotation is, as ``_SURFACES`` knows it: a datum, a dimension's type (``basic`` for
    a basic one) or a tolerance's characteristic."""
    if spec["kind"] == "datum":
        return "datum"
    if spec["kind"] == "dimension":
        return "basic" if spec["dimension"].get("basic") else spec["dimension"]["type"]
    return spec["geometric_tolerance"]["characteristic"]


def _owner_label(segment: Any, owners: set[str]) -> str:
    """The label an owner's last segment names: ``LABEL.N`` is the N-th ``LABEL`` where no owner
    bears the text whole, as the grammar reads it (``refs._group``)."""
    from cadgen.engine import refs as grammar

    numbered = None if segment.quoted or segment.text in owners else grammar._INDEXED.fullmatch(segment.text)
    return numbered[1] if numbered else segment.text


def _ref(given: dict[str, Any], faces: Any, names: list[str | None], owners: set[str]) -> Ref:
    from cadgen.engine import refs as grammar

    role, written = given["role"], given["written"]
    count = faces.Extent()
    if given["face"] is not None:
        ordinal = given["face"]
        if not 1 <= ordinal <= count:
            return Ref(role, written, None, "missing", problem=f"{written} is not a face of the annotated part")
        return Ref(role, written, ordinal, "ok")
    try:
        file, selectors = grammar.parse(written)
    except grammar.RefError as error:
        return Ref(role, written, None, "invalid", problem=str(error))
    if file is not None or len(selectors) != 1 or selectors[0].element is None or selectors[0].kind != "face":
        return Ref(role, written, None, "invalid", problem=f"{written}: a PMI ref names one face of the annotated part")
    selector = selectors[0]
    if selector.owner:
        if _owner_label(selector.owner[-1], owners) not in owners:
            return Ref(role, written, None, "invalid", problem=f"{written}: {'/'.join(map(str, selector.owner))} is "
                                                               f"not the annotated part ({sorted(owners)[0]})")
    element = selector.element
    if isinstance(element, tuple):
        ordinal = element[1]
        if not 1 <= ordinal <= count:
            return Ref(role, written, None, "missing", problem=f"the part has no face {ordinal} (it has {count})")
        return Ref(role, written, ordinal, "ok")
    held = [at for at, text in enumerate(names, 1) if text == element and at <= count]
    if len(held) == 1:
        return Ref(role, written, held[0], "ok")
    if len(held) > 1:
        return Ref(role, written, None, "ambiguous", held,
                   f"{written} names {len(held)} faces: {', '.join(f'face {at}' for at in held)}")
    said = f"the part has no face {element}"
    atom = element.split(":", 1)[1].split(";", 1)[0]
    if "~" not in atom:  # a folded name: its digest says nothing of what it became (``refs._missing``)
        now = sorted({text for text in names if text and text.split(":", 1)[1].split(";", 1)[0] == atom})
        said += f": {atom} is now {', '.join(now)}" if now else f": no face is made of {atom} now"
    return Ref(role, written, None, "missing", problem=said)


def _datums_first(items: list[Resolved]) -> list[Resolved]:
    """A part's annotations in the order its document holds them: its datums, then the rest."""
    return [item for item in items if item.spec["kind"] == "datum"] + [item for item in items if item.spec["kind"] != "datum"]


def _separation(shapes: list[Any], written: list[str]) -> tuple[float | None, str | None]:
    """The distance between two faces as a location dimension measures it: between parallel
    planes, from a plane to a cylinder's axis parallel to it, or between parallel axes; or why
    there is none."""
    import numpy as np

    held = []
    for shape in shapes:
        kind, found = _surface(shape)
        held.append((kind, found if kind == "plane" else _axis(shape)))
    (first_kind, first), (second_kind, second) = held
    if first_kind == "plane" and second_kind == "plane":
        normal, other = np.array(first["normal"]), np.array(second["normal"])
        if abs(abs(float(normal @ other)) - 1.0) > 1e-9:
            return None, f"{written[0]} and {written[1]} are not parallel planes"
        found = abs(float((np.array(second["origin"]) - np.array(first["origin"])) @ normal))
        return (found, None) if found > 1e-9 else (None, f"{written[0]} and {written[1]} lie in one plane")
    if first_kind == "cylinder" and second_kind == "cylinder":
        point, direction = np.array(first["point"]), np.array(first["direction"])
        if abs(abs(float(direction @ np.array(second["direction"]))) - 1.0) > 1e-9:
            return None, f"the axes of {written[0]} and {written[1]} are not parallel"
        found = float(np.linalg.norm(np.cross(np.array(second["point"]) - point, direction)))
        return (found, None) if found > 1e-9 else (None, f"{written[0]} and {written[1]} share one axis")
    plane, axis = (first, second) if first_kind == "plane" else (second, first)
    normal = np.array(plane["normal"])
    if abs(float(normal @ np.array(axis["direction"]))) > 1e-9:
        axis_of, plane_of = (written[1], written[0]) if first_kind == "plane" else (written[0], written[1])
        return None, f"the axis of {axis_of} is not parallel to the plane {plane_of}"
    found = abs(float((np.array(axis["point"]) - np.array(plane["origin"])) @ normal))
    return (found, None) if found > 1e-9 else (None, f"the axis lies in the plane {written[0]}")


def _axis(face: Any) -> dict[str, Any]:
    """A cylindrical face's axis: a point on it and its unit direction."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    axis = BRepAdaptor_Surface(TopoDS.Face_s(face)).Cylinder().Axis()
    point, direction = axis.Location(), axis.Direction()
    return {"point": (point.X(), point.Y(), point.Z()), "direction": (direction.X(), direction.Y(), direction.Z())}


def _worst(statuses: Iterable[str]) -> str:
    found = "ok"
    for status in statuses:
        if STATUSES.index(status) > STATUSES.index(found):
            found = status
    return found


def _faces(shape: Any) -> Any:
    """A part's faces by their ordinals, as the ref grammar numbers them (``refs._map``)."""
    from cadgen.engine import refs as grammar

    return grammar._map(shape, "face")


def _surface(face: Any) -> tuple[str, dict[str, Any]]:
    """A face's surface: ``plane`` (origin, unit normal), ``cylinder`` (radius, axis), or another
    kind by name."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.TopoDS import TopoDS

    adaptor = BRepAdaptor_Surface(TopoDS.Face_s(face))
    kind = adaptor.GetType()
    if kind == GeomAbs_Plane:
        plane = adaptor.Plane()
        origin, normal = plane.Location(), plane.Axis().Direction()
        return "plane", {"origin": (origin.X(), origin.Y(), origin.Z()), "normal": (normal.X(), normal.Y(), normal.Z())}
    if kind == GeomAbs_Cylinder:
        return "cylinder", {"radius": adaptor.Cylinder().Radius()}
    return str(kind.name).replace("GeomAbs_", "").lower(), {}


def faces_named(tree: Any) -> dict[tuple[str, str], dict[tuple[str, str], str]]:
    """The kind of face (plane, cylinder) each ref of a built tree's annotations names, by
    annotation (part, id), then ref (role, written): what ``warn`` compares two builds by."""
    found: dict = {}
    for part, items in resolve(tree) if tree is not None and tree.pmi else ():
        faces = _faces(part.shape)
        for item in items:
            found[(part.name, item.spec["id"])] = {(ref.role, ref.written): _surface(faces.FindKey(ref.ordinal))[0]
                                                   for ref in item.refs if ref.ordinal is not None}
    return found


def faces_named_in(path: Any) -> dict[tuple[str, str], dict[tuple[str, str], str]]:
    """The same, of the model's saved xbf: its last build, where this process has not built it. A
    file that cannot be read holds nothing to compare with."""
    from cadgen.engine import document

    try:
        loaded = document.load(path)
        records = records_of_document(loaded.doc, loaded.prototypes, loaded.name)
    except Exception:  # noqa: BLE001 - no last build is nothing to warn of, never a failed build
        return {}
    found: dict = {}
    for record in records:
        if record["extra"] is None:
            continue
        prototype = loaded.prototypes[record["part"]]
        faces = _faces(prototype.shape)
        found[(prototype.name, record["extra"]["id"])] = {(ref["role"], ref["written"]): _surface(
            faces.FindKey(ref["ordinal"]))[0] for ref in record["refs"] if ref["ordinal"] is not None}
    return found


def warn(tree: Any, previous: dict[tuple[str, str], dict[tuple[str, str], str]]) -> None:
    """Each ref of ``tree``'s annotations written as text that names another kind of face than on
    the model's last build (``previous``: ``faces_named`` of its tree, or ``faces_named_in`` its
    xbf) -- a hole whose name passed to a flat side of the cut that replaced it -- where the
    annotation stands on the face it names now (elsewhere its status says so): warned of in
    ``Tree.pmi_warnings``, the build's report and its served structure, never the document, which
    is what the code makes."""
    now = faces_named(tree)
    for part, items in resolve(tree):
        for item in items:
            key = (part.name, item.spec["id"])
            for ref, given in zip(item.refs, item.spec["refs"]):
                was = (previous.get(key) or {}).get((ref.role, ref.written))
                named = now[key].get((ref.role, ref.written))
                if given["face"] is None and ref.status == "ok" and was is not None and was != named:
                    tree.pmi_warnings.setdefault(key, []).append(
                        f"{ref.written} named a {was} face on the last build and names a {named} face now: another "
                        "face than the annotation was made on, measured as it is. Point the ref at the face meant, "
                        "or remove the annotation")


def signature(tree: Any) -> tuple:
    """What a tree's annotations are, for the build's signature: a change to one remakes the document."""
    return tuple(_text({"part": part.name, "pmi": list(given)}) for part, given in tree.pmi or ())


def problems(tree: Any) -> list[dict[str, Any]]:
    """Every annotation of ``tree`` that is not ``ok``: its part, id, status and why."""
    return [{"part": part.name, "id": item.spec["id"], "status": item.status, "problem": item.problem}
            for part, items in resolve(tree) for item in items if item.status != "ok"]


def warnings(tree: Any) -> list[str]:
    """Every warning of ``tree``'s annotations (``warn``), each naming its annotation (``part/id``)."""
    return [f"{part}/{id}: {text}" for (part, id), texts in tree.pmi_warnings.items() for text in texts]


# --- the XCAF document -------------------------------------------------------------------------


def write(doc: Any, tree: Any, label_of: Any) -> None:
    """The tree's annotations into ``doc``'s GD&T tool, each part's in its order, datums first
    (a tolerance's frame names them), and the GD&T of the document the tree was read from
    (``Tree.pmi_source``: ``copy``); ``label_of(part)`` is the part's shape label."""
    if tree.pmi_source is not None:
        loaded, parts = tree.pmi_source
        copy(doc, loaded, lambda index: label_of(parts[index]))
    if not tree.pmi:
        return
    from OCP.Standard import Standard_GUID
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDataStd import TDataStd_AsciiString
    from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Reference
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    tool = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    guid = Standard_GUID(EXTRA_GUID)
    for part, items in resolve(tree):
        label = label_of(part)
        faces = _faces(XCAFDoc_ShapeTool.GetShape_s(label))

        def sub(ordinal: int) -> Any:
            found = TDF_Label()
            face = faces.FindKey(ordinal)
            if not shapes.FindSubShape(label, face, found):
                shapes.AddSubShape(label, face, found)
            return found

        datums: dict[str, Any] = {}
        positions = {letter: at for item in items if item.spec["kind"] == "geometric_tolerance"
                     for at, letter in enumerate(item.spec["geometric_tolerance"]["datums"], 1)}
        ordered = _datums_first(items)
        for item in ordered:
            spec = item.spec
            linked = item.status == "ok"
            refs = [sub(ref.ordinal) for ref in item.refs] if linked else []
            if spec["kind"] == "datum":
                at = tool.AddDatum()
                _datum(at, spec["datum"]["letter"], positions.get(spec["datum"]["letter"], 0), spec["id"])
                if linked:
                    sequence = TDF_LabelSequence()
                    sequence.Append(refs[0])
                    tool.SetDatum(sequence, at)
                datums[spec["datum"]["letter"]] = at
            elif spec["kind"] == "dimension":
                at = tool.AddDimension()
                _dimension(at, spec, item.nominal)
                if linked and len(refs) == 1:
                    tool.SetDimension(refs[0], at)
                elif linked:
                    tool.SetDimension(refs[0], refs[1], at)
            else:
                at = tool.AddGeomTolerance()
                _tolerance_object(at, spec)
                if linked:
                    tool.SetGeomTolerance(refs[0], at)
                    for letter in spec["geometric_tolerance"]["datums"]:
                        tool.SetDatumToGeomTol(datums[letter], at)
            TDataStd_AsciiString.Set_s(at, guid, TCollection_AsciiString(_text(_extra(item))))
            TDF_Reference.Set_s(at, label)


def _extra(item: Resolved) -> dict[str, Any]:
    """The cadgen attribute's JSON (see the module): what the code says that XCAF has no place for."""
    spec = item.spec
    return {"schema": SCHEMA, "id": spec["id"], "kind": spec["kind"], "label": spec["label"],
            "presentation": spec["presentation"], "refs": spec["refs"],
            # What an unlinked annotation meant, for a reader: XCAF links values to geometry alone.
            "unlinked": None if item.status == "ok" else
            {key: spec[key] for key in ("dimension", "datum", "geometric_tolerance") if key in spec}}


def _ascii(text: str) -> Any:
    from OCP.TCollection import TCollection_HAsciiString

    return TCollection_HAsciiString(text)


def _datum(label: Any, letter: str, place: int, id: str) -> None:
    from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DatumObject
    from OCP.XCAFDoc import XCAFDoc_Datum

    found = XCAFDimTolObjects_DatumObject()
    found.SetName(_ascii(letter))
    found.SetSemanticName(_ascii(id))
    if place:
        # A datum's place in the frames that name it: the writer writes a datum system of the
        # datums with a place, in its order, and none without.
        found.SetPosition(place)
    XCAFDoc_Datum.Set_s(label).SetObject(found)


def _dimension(label: Any, spec: dict[str, Any], nominal: float | None) -> None:
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_DimensionObject,
                                        XCAFDimTolObjects_DimensionType_Location_LinearDistance,
                                        XCAFDimTolObjects_DimensionType_Size_Diameter)
    from OCP.XCAFDoc import XCAFDoc_Dimension

    found = XCAFDimTolObjects_DimensionObject()
    found.SetSemanticName(_ascii(spec["id"]))
    kind = spec["dimension"]["type"]
    found.SetType(XCAFDimTolObjects_DimensionType_Size_Diameter if kind == "diameter"
                  else XCAFDimTolObjects_DimensionType_Location_LinearDistance)
    found.SetValue(nominal if nominal is not None else 0.0)
    if spec["dimension"].get("basic"):
        # CAx-IF's type 1 dimension modifier: a descriptive item 'dimensional note' of description
        # 'theoretical' in the dimension's shape_dimension_representation, which is what the
        # writer makes of an XCAF description (and its reader makes one of again).
        found.AddDescription(_ascii(THEORETICAL[1]), _ascii(THEORETICAL[0]))
    tolerance = spec["dimension"]["tolerance"]
    if tolerance is not None and nominal is not None:
        # XCAF's lower deviation is a magnitude the writer negates (see the module): -lower.
        found.SetLowerTolValue(-tolerance["lower"])
        found.SetUpperTolValue(tolerance["upper"])
    XCAFDoc_Dimension.Set_s(label).SetObject(found)


def _tolerance_object(label: Any, spec: dict[str, Any]) -> None:
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_GeomToleranceObject,
                                        XCAFDimTolObjects_GeomToleranceType_Flatness,
                                        XCAFDimTolObjects_GeomToleranceType_Position,
                                        XCAFDimTolObjects_GeomToleranceTypeValue_Diameter)
    from OCP.XCAFDoc import XCAFDoc_GeomTolerance

    given = spec["geometric_tolerance"]
    found = XCAFDimTolObjects_GeomToleranceObject()
    found.SetSemanticName(_ascii(spec["id"]))
    found.SetType(XCAFDimTolObjects_GeomToleranceType_Flatness if given["characteristic"] == "flatness"
                  else XCAFDimTolObjects_GeomToleranceType_Position)
    found.SetValue(given["value"])
    if given["zone"] == "diameter":
        found.SetTypeOfValue(XCAFDimTolObjects_GeomToleranceTypeValue_Diameter)
    XCAFDoc_GeomTolerance.Set_s(label).SetObject(found)


def copy(doc: Any, loaded: Any, label_of: Callable[[int], Any]) -> None:
    """The GD&T of a document read from a file another system wrote (``loaded``, a
    ``document.Loaded``) copied as read into ``doc``, the document made of it again (an xbf of a
    STEP): every datum, dimension and geometric tolerance as XCAF holds it, each linked to the same
    faces, edges and points of the same parts (``label_of(index)``: prototype ``index``'s label in
    ``doc``), a tolerance to the same datums. One the file links to anything else (an occurrence's
    face, a whole part) is copied linked to nothing, as reading the file says it is (``missing``):
    its values kept, nothing approximated."""
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_DatumObject, XCAFDimTolObjects_DimensionObject,
                                        XCAFDimTolObjects_GeomToleranceObject)
    from OCP.XCAFDoc import (XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_DocumentTool, XCAFDoc_GeomTolerance,
                             XCAFDoc_ShapeTool)

    from cadgen.engine import refs as grammar
    from cadgen.engine.document import _entry

    source = _tool(loaded.doc)
    if source is None:
        return
    tool = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    by_entry = {prototype.entry: prototype for prototype in loaded.prototypes}
    theirs: dict[tuple[int, str], Any] = {}  # each prototype's elements, in the file's document and in ``doc``
    ours: dict[tuple[int, str], Any] = {}

    def placed(label: Any) -> Any:
        """A ref label's element as ``doc`` holds it, a sub-shape label of its part; None for none."""
        hit = _element(label, by_entry, theirs)
        if hit is None:
            return None
        index, kind, ordinal = hit
        part = label_of(index)
        if (index, kind) not in ours:
            ours[(index, kind)] = grammar._map(XCAFDoc_ShapeTool.GetShape_s(part), kind)
        element = ours[(index, kind)].FindKey(ordinal)
        found = TDF_Label()
        if not shapes.FindSubShape(part, element, found):
            shapes.AddSubShape(part, element, found)
        return found

    def linked(label: Any) -> list[Any]:
        """The elements a label links to, first and second, as ``doc``'s labels: none where one of
        them has no place there."""
        found = []
        for sequence in _linked(source, label):
            labels = TDF_LabelSequence()
            for at in range(1, sequence.Length() + 1):
                hit = placed(sequence.Value(at))
                if hit is None:
                    return [TDF_LabelSequence(), TDF_LabelSequence()]
                labels.Append(hit)
            found.append(labels)
        return found

    datums: dict[str, Any] = {}
    for label in _labels(source, "datum"):
        at = tool.AddDatum()
        XCAFDoc_Datum.Set_s(at).SetObject(XCAFDimTolObjects_DatumObject(XCAFDoc_Datum.Set_s(label).GetObject()))
        first, _second = linked(label)
        if first.Length():
            tool.SetDatum(first, at)
        datums[_entry(label)] = at
    for label in _labels(source, "dimension"):
        at = tool.AddDimension()
        XCAFDoc_Dimension.Set_s(at).SetObject(
            XCAFDimTolObjects_DimensionObject(XCAFDoc_Dimension.Set_s(label).GetObject()))
        first, second = linked(label)
        if first.Length():
            tool.SetDimension(first, second, at)
    for label in _labels(source, "geometric_tolerance"):
        at = tool.AddGeomTolerance()
        XCAFDoc_GeomTolerance.Set_s(at).SetObject(
            XCAFDimTolObjects_GeomToleranceObject(XCAFDoc_GeomTolerance.Set_s(label).GetObject()))
        first, _second = linked(label)
        if first.Length():
            tool.SetGeomTolerance(first, at)
        for datum in _datums_of(label):
            tool.SetDatumToGeomTol(datums[_entry(datum)], at)


def _tool(doc: Any) -> Any:
    """A document's GD&T tool (``XCAFDoc_DimTolTool``), or None where it has none."""
    from OCP.XCAFDoc import XCAFDoc_DimTolTool

    label = doc.Main().FindChild(DIMTOL_TAG, False)
    if label.IsNull() or not label.IsAttribute(XCAFDoc_DimTolTool.GetID_s()):
        return None
    return XCAFDoc_DimTolTool.Set_s(label)


def _labels(tool: Any, kind: str) -> list[Any]:
    """The GD&T tool's labels of ``kind`` (``datum``, ``dimension``, ``geometric_tolerance``) that hold
    their object, in the tool's order."""
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_GeomTolerance

    listed, attribute = {"datum": (tool.GetDatumLabels, XCAFDoc_Datum),
                         "dimension": (tool.GetDimensionLabels, XCAFDoc_Dimension),
                         "geometric_tolerance": (tool.GetGeomToleranceLabels, XCAFDoc_GeomTolerance)}[kind]
    sequence = TDF_LabelSequence()
    listed(sequence)
    return [sequence.Value(at) for at in range(1, sequence.Length() + 1)
            if sequence.Value(at).IsAttribute(attribute.GetID_s())]


def _linked(tool: Any, label: Any) -> tuple[Any, Any]:
    """The shape labels a GD&T label is linked to: its first and its second (a dimension's ``to``)."""
    from OCP.TDF import TDF_LabelSequence

    first, second = TDF_LabelSequence(), TDF_LabelSequence()
    tool.GetRefShapeLabel_s(label, first, second)
    return first, second


def _datums_of(label: Any) -> list[Any]:
    """The datum labels a geometric tolerance's frame names."""
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DimTolTool

    named = TDF_LabelSequence()
    XCAFDoc_DimTolTool.GetDatumWithObjectOfTolerLabels_s(label, named)
    return [named.Value(at) for at in range(1, named.Length() + 1)]


def _element(label: Any, by_entry: dict[str, Any], maps: dict[tuple[int, str], Any]) -> tuple[int, str, int] | None:
    """The element a ref label is -- its prototype's index, its kind (``face``, ``edge``, ``vertex``)
    and its ordinal there -- or None where it is no element of a prototype (``by_entry``: the
    document's prototypes by their labels' entries; ``maps``: each prototype's elements, made once)."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    from cadgen.engine import refs as grammar
    from cadgen.engine.document import _entry

    shape = XCAFDoc_ShapeTool.GetShape_s(label)
    kinds = {TopAbs_FACE: "face", TopAbs_EDGE: "edge", TopAbs_VERTEX: "vertex"}
    kind = None if shape.IsNull() else kinds.get(shape.ShapeType())
    owner = label.Father()
    prototype = by_entry.get(_entry(owner))
    if kind is None or prototype is None:
        return None
    if (prototype.index, kind) not in maps:
        maps[(prototype.index, kind)] = grammar._map(XCAFDoc_ShapeTool.GetShape_s(owner), kind)
    ordinal = maps[(prototype.index, kind)].FindIndex(shape)
    return (prototype.index, kind, ordinal) if ordinal else None


# --- read back ---------------------------------------------------------------------------------

# Why a ref of a document another system wrote resolves to nothing.
_NOT_LINKED = "the file links it to no face, edge or point of a part"


def records_of_document(doc: Any, prototypes: list[Any], root: str) -> list[dict[str, Any]]:
    """A document's annotations as records (``entries``' input): every GD&T object its tool holds,
    datums, dimensions and geometric tolerances in the tool's order, each resolved as the document
    is now. One the code made (its cadgen attribute) is resolved as its build resolved it
    (``_resolved``, against its part's faces and their names): its status is derived, never read.
    One another system wrote is resolved by the elements the file links it to, and what this module
    does not hold whole is ``unsupported``, with why (``_beyond_*``). ``prototypes`` are the document's
    (``document.Prototype``: each its label's entry and shape), ``root`` the name of its root."""
    from OCP.Standard import Standard_GUID
    from OCP.TDataStd import TDataStd_AsciiString
    from OCP.TDF import TDF_Reference
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_DimensionType_Location_LinearDistance,
                                        XCAFDimTolObjects_DimensionType_Size_Diameter,
                                        XCAFDimTolObjects_GeomToleranceType_Flatness,
                                        XCAFDimTolObjects_GeomToleranceType_Position,
                                        XCAFDimTolObjects_GeomToleranceTypeValue_Diameter,
                                        XCAFDimTolObjects_GeomToleranceTypeValue_None)
    from OCP.XCAFDoc import XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_GeomTolerance

    from cadgen.engine.document import _entry

    dimensions = {XCAFDimTolObjects_DimensionType_Size_Diameter: "diameter",
                  XCAFDimTolObjects_DimensionType_Location_LinearDistance: "distance"}
    characteristics = {XCAFDimTolObjects_GeomToleranceType_Flatness: "flatness",
                       XCAFDimTolObjects_GeomToleranceType_Position: "position"}
    tool = _tool(doc)
    if tool is None:
        return []
    by_entry = {prototype.entry: prototype for prototype in prototypes}
    maps: dict[tuple[int, str], Any] = {}
    guid = Standard_GUID(EXTRA_GUID)

    def extra(label: Any) -> dict[str, Any] | None:
        found = TDataStd_AsciiString()
        if label.IsAttribute(guid) and label.FindAttribute(guid, found):
            held = json.loads(found.Get().ToCString())
            return held if held.get("schema") == SCHEMA else None
        return None

    def part_of(label: Any) -> int | None:
        """The prototype an annotation the code made is of: its ``TDF_Reference``'s."""
        found = TDF_Reference()
        if not label.FindAttribute(TDF_Reference.GetID_s(), found):
            return None
        prototype = by_entry.get(_entry(found.Get()))
        return None if prototype is None else prototype.index

    records: list[dict[str, Any]] = []

    def add(label: Any, kind: str, values: dict[str, Any], beyond: list[str], xcaf_type: str | None) -> None:
        """The record of a GD&T label holding an object of ``kind``."""
        held = extra(label)
        first, second = ([_element(sequence.Value(at), by_entry, maps) for at in range(1, sequence.Length() + 1)]
                         for sequence in _linked(tool, label))
        if kind == "dimension" and second:
            targets = [("from", hit) for hit in first] + [("to", hit) for hit in second]
        else:
            targets = [("feature", hit) for hit in first]
        found = {"values": values, "targets": targets, "extra": held, "entry": _entry(label), "warnings": []}
        if held is not None:
            found.update(kind=held["kind"], xcaf_type=None, reason=None, part=part_of(label))
            records.append(found)
            return
        # Linked to an edge or a point: no annotation on faces, kept and listed, never drawn.
        beyond = beyond + [f"linked to {'an edge' if element == 'edge' else 'a point'}"
                           for element in sorted({hit[1] for _role, hit in targets if hit is not None} - {"face"})]
        refs = [{"role": role, "written": None, "status": "missing" if hit is None else "ok",
                 "ordinal": None if hit is None else hit[2], "candidates": [],
                 "problem": _NOT_LINKED if hit is None else None} for role, hit in targets]
        status = _worst(ref["status"] for ref in refs) if refs else "missing"
        parts = {hit[0] for _role, hit in targets if hit is not None}
        found.update(kind="unsupported" if beyond else kind, xcaf_type=xcaf_type if beyond else None,
                     reason="; ".join(beyond) or None, part=min(parts) if parts else None, status=status,
                     problem=None if status == "ok" else _NOT_LINKED, refs=refs)
        records.append(found)

    modified: set[str] = set()  # the datums a tolerance cannot be read with: modified, or targets
    for label in _labels(tool, "datum"):
        found = XCAFDoc_Datum.Set_s(label).GetObject()
        beyond = _beyond_datum(found)
        if beyond:
            modified.add(_entry(label))
        add(label, "datum", {"letter": _name_of(found)}, beyond, "XCAFDimTolObjects_DatumObject")
    for label in _labels(tool, "dimension"):
        found = XCAFDoc_Dimension.Set_s(label).GetObject()
        kind = dimensions.get(found.GetType())
        tolerance = None
        if found.IsDimWithPlusMinusTolerance():
            tolerance = {"type": "plus_minus", "upper": _as_held(found.GetUpperTolValue()),
                         "lower": _as_held(-found.GetLowerTolValue())}
        notes = [(found.GetDescriptionName(at).ToCString(), found.GetDescription(at).ToCString())
                 for at in range(found.NbDescriptions())] if found.HasDescriptions() else []
        values = {"type": kind, "basic": THEORETICAL in notes, "nominal": _as_held(found.GetValue()),
                  "tolerance": tolerance}
        if notes:
            values["notes"] = [list(note) for note in notes]
        add(label, "dimension", values, _beyond_dimension(found, kind, notes), found.GetType().name)
    for label in _labels(tool, "geometric_tolerance"):
        found = XCAFDoc_GeomTolerance.Set_s(label).GetObject()
        datums = _datums_of(label)
        letters = sorted((datum.GetPosition(), _name_of(datum))
                         for datum in (XCAFDoc_Datum.Set_s(named).GetObject() for named in datums))
        value_type = found.GetTypeOfValue()
        if value_type == XCAFDimTolObjects_GeomToleranceTypeValue_Diameter:
            zone = "diameter"
        elif value_type == XCAFDimTolObjects_GeomToleranceTypeValue_None:
            zone = None
        else:
            zone = "other"
        characteristic = characteristics.get(found.GetType())
        values = {"characteristic": characteristic, "value": _as_held(found.GetValue()), "unit": UNIT, "zone": zone,
                  "modifier": None, "datums": [letter for _place, letter in letters]}
        beyond = _beyond_tolerance(found, characteristic, zone)
        if any(_entry(named) in modified for named in datums):
            beyond.append("a datum it names has modifiers or is a datum target")
        add(label, "geometric_tolerance", values, beyond, found.GetType().name)
    # The code's annotations resolved as their build resolved them, each against its part.
    letters_of: dict[int, set[str]] = {}
    for record in records:
        if record["extra"] is not None and record["kind"] == "datum":
            letters_of.setdefault(record["part"], set()).add(record["values"]["letter"])
    for record in records:
        if record["extra"] is not None:
            prototype = prototypes[record["part"]]
            faces = _faces(prototype.shape)
            names = [prototype.face_names.get(at) for at in range(1, faces.Extent() + 1)]
            given = record["extra"]
            spec = {"kind": given["kind"], "refs": given["refs"], **(given["unlinked"] or {given["kind"]: record["values"]})}
            resolved = _resolved(spec, faces, names, {prototype.name, root}, letters_of.get(record["part"], set()))
            record.update(status=resolved.status, problem=resolved.problem, refs=_refs(resolved))
    return records


def _words(name: str) -> str:
    """An XCAF enumerator's name as words: ``..._Location_LinearDistance`` is ``location linear distance``."""
    tail = name.split("_", 2)[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tail).replace("_", " ").lower()


def _beyond_datum(found: Any) -> list[str]:
    """What a datum of a file says that this module does not hold: modifiers, or a datum target."""
    from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DatumModifWithValue_None

    beyond = []
    # The binding hands back a modifier-with-value's value alone (its kind is an out-parameter it
    # cannot fill): a value says one is set.
    if found.GetModifiers().Length() or found.GetModifierWithValue(XCAFDimTolObjects_DatumModifWithValue_None)[0]:
        beyond.append("it has modifiers")
    if found.IsDatumTarget():
        beyond.append("it is a datum target")
    return beyond


def _beyond_dimension(found: Any, kind: str | None, notes: list[tuple[str, str]]) -> list[str]:
    """What a dimension of a file says that this module does not hold: another type, limits, a fit, a
    qualifier, modifiers, a note other than a basic one's, a basic dimension other than a distance."""
    beyond = []
    if kind is None:
        beyond.append(f"a {_words(found.GetType().name)} dimension is not one this holds")
    if found.IsDimWithRange():
        beyond.append("it has limits (a range) in place of a tolerance")
    if found.IsDimWithClassOfTolerance():
        beyond.append("it has a class of tolerance (a fit)")
    if found.HasQualifier():
        beyond.append(f"it has a qualifier ({_words(found.GetQualifier().name)})")
    if found.GetModifiers().Length():
        beyond.append("it has modifiers")
    other = [list(note) for note in notes if note != THEORETICAL]
    if other:
        beyond.append(f"it has notes {other}")
    if THEORETICAL in notes and kind not in (None, "distance"):
        beyond.append(f"a basic {kind} is not one this holds")
    return beyond


def _beyond_tolerance(found: Any, characteristic: str | None, zone: str | None) -> list[str]:
    """What a geometric tolerance of a file says that this module does not hold: another
    characteristic, modifiers, a material requirement, a zone modifier, a maximum value, a zone
    other than a width's or a diameter's."""
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_GeomToleranceMatReqModif_None,
                                        XCAFDimTolObjects_GeomToleranceZoneModif_None)

    beyond = []
    if characteristic is None:
        beyond.append(f"{_words(found.GetType().name)} is not a characteristic this holds")
    if found.GetModifiers().Length():
        beyond.append("it has modifiers")
    if found.GetMaterialRequirementModifier() != XCAFDimTolObjects_GeomToleranceMatReqModif_None:
        beyond.append(f"it has a material requirement ({_words(found.GetMaterialRequirementModifier().name)})")
    if found.GetZoneModifier() != XCAFDimTolObjects_GeomToleranceZoneModif_None:
        beyond.append(f"it has a {_words(found.GetZoneModifier().name)} zone")
    if found.GetMaxValueModifier() > 0:
        beyond.append("it has a maximum value")
    if zone == "other":
        beyond.append(f"its zone is {_words(found.GetTypeOfValue().name)}")
    return beyond


def _refs(item: Resolved) -> list[dict[str, Any]]:
    """An annotation's refs as a record holds them (``records_of_document``, ``records_of_tree``)."""
    return [{"role": ref.role, "written": ref.written, "status": ref.status, "ordinal": ref.ordinal,
             "candidates": list(ref.candidates), "problem": ref.problem} for ref in item.refs]


def _name_of(datum: Any) -> str:
    """A datum object's letter; the empty string for none (a null handle reads as None)."""
    name = datum.GetName()
    return name.ToCString() if name is not None else ""


def records_of_tree(tree: Any, index_of: dict[int, int]) -> list[dict[str, Any]]:
    """A built tree's annotations as the records ``records_of_document`` reads back from its
    document: the same order (each part's datums, then the rest), the same values, as XCAF
    holds them (``_as_held``), the same refs resolved; and each one's warnings (``warn``), which
    are the build's and no document's."""
    records = []
    for part, items in resolve(tree):
        index = index_of[id(part)]
        ordered = _datums_first(items)
        by_kind = {"datum": [], "dimension": [], "geometric_tolerance": []}
        for item in ordered:
            spec = item.spec
            linked = item.status == "ok"
            targets = [(ref.role, (index, "face", ref.ordinal)) for ref in item.refs] if linked else []
            if spec["kind"] == "datum":
                values = {"letter": spec["datum"]["letter"]}
            elif spec["kind"] == "dimension":
                tolerance = spec["dimension"]["tolerance"] if item.nominal is not None else None
                values = {"type": spec["dimension"]["type"], "basic": bool(spec["dimension"].get("basic")),
                          "nominal": _as_held(item.nominal or 0.0),
                          "tolerance": None if tolerance is None else
                          {"type": "plus_minus", "upper": _as_held(tolerance["upper"]),
                           "lower": _as_held(tolerance["lower"])}}
            else:
                given = spec["geometric_tolerance"]
                values = {"characteristic": given["characteristic"], "value": _as_held(given["value"]), "unit": UNIT,
                          "zone": given["zone"], "modifier": None, "datums": list(given["datums"]) if linked else []}
            by_kind[spec["kind"]].append({
                "kind": spec["kind"], "values": values, "xcaf_type": None, "reason": None, "part": index,
                "targets": targets, "extra": json.loads(_text(_extra(item))), "entry": None, "status": item.status,
                "problem": item.problem, "refs": _refs(item),
                "warnings": list(tree.pmi_warnings.get((part.name, spec["id"])) or ())})
        records.extend(by_kind["datum"] + by_kind["dimension"] + by_kind["geometric_tolerance"])
    # The document's tool lists datums, then dimensions, then tolerances, of every part.
    return sorted(records, key=lambda record: ("datum", "dimension", "geometric_tolerance").index(record["kind"]))


def _as_held(value: float) -> float:
    """A real as XCAF holds and reads it back: a double, its zero unsigned (a deviation of 0 is
    held as the magnitude -0)."""
    return float(value) + 0.0


def entries(records: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
    """The structure's ``pmi``: one JSON-plain entry per record -- ``id``, ``kind`` (``dimension``,
    ``datum``, ``geometric_tolerance``, ``unsupported``), ``label``, ``status``, ``problem``,
    ``warnings``, ``part`` (a prototype index), ``refs`` (each ``role``, ``ref`` -- canonical as
    ``refs`` spells it for this document --, ``written``, ``status``, ``candidates``, ``problem``),
    ``presentation``, ``xcaf_type``, an unsupported one's ``reason``, and the kind's own block of
    values."""
    from cadgen.engine import refs as grammar

    root = grammar.structure_tree(structure)
    first_node: dict[int, Any] = {}
    for node in root.parts():
        first_node.setdefault(node.payload["prototype"], node)
    one_part = len(root.parts()) == 1
    prototypes = structure["prototypes"]
    named = {"face": "faceNames", "edge": "edgeNames", "vertex": "vertexNames"}

    def canonical(index: int, kind: str, ordinal: int) -> str:
        name = (prototypes[index].get(named[kind]) or {}).get(str(ordinal))
        node = first_node.get(index)
        if node is None:
            return name or f"{kind} {ordinal}"
        return grammar._element_ref(root, node, kind, ordinal, name, one_part)

    found = []
    counters: dict[str, int] = {}
    for record in records:
        extra, kind = record["extra"], record["kind"]
        targets = list(record["targets"])
        refs = []
        for at, ref in enumerate(record["refs"]):
            hit = targets[at][1] if at < len(targets) else None
            refs.append({"role": ref["role"], "written": ref["written"], "status": ref["status"],
                         "ref": canonical(*hit) if hit is not None else ref["written"],
                         "candidates": [canonical(record["part"], "face", ordinal)
                                        for ordinal in ref["candidates"]] or None,
                         "problem": ref["problem"]})
        if extra is not None:
            ident, label, presentation, unlinked = extra["id"], extra["label"], extra["presentation"], extra["unlinked"]
        else:
            counters[kind] = counters.get(kind, 0) + 1
            ident = (record["values"].get("letter") or kind) if kind == "datum" else f"{kind}-{counters[kind]}"
            label, presentation, unlinked = None, None, None
        entry = {"id": ident, "kind": kind, "label": label, "status": record["status"], "problem": record["problem"],
                 "warnings": list(record["warnings"]), "part": record["part"], "refs": refs,
                 "presentation": presentation, "xcaf_type": record["xcaf_type"]}
        values = record["values"]
        if kind == "datum":
            entry["datum"] = {"letter": values["letter"]}
        elif kind == "dimension":
            if unlinked is not None:
                entry["dimension"] = {"type": unlinked["dimension"]["type"],
                                      "basic": bool(unlinked["dimension"].get("basic")), "nominal": None,
                                      "tolerance": unlinked["dimension"]["tolerance"]}
            else:
                # Measured from the geometry where the code made it; as the file says, where another system did.
                entry["dimension"] = {"type": values["type"], "basic": bool(values.get("basic")),
                                      "nominal": {"value": values["nominal"], "unit": UNIT,
                                                  "source": "geometry" if extra is not None else "file"},
                                      "tolerance": values["tolerance"]}
        elif kind == "geometric_tolerance":
            entry["geometric_tolerance"] = dict(unlinked["geometric_tolerance"] if unlinked is not None else values)
        else:
            entry["reason"] = record["reason"]
            entry["values"] = values
        found.append(entry)
    return found


def read(source: Any) -> list[dict[str, Any]]:
    """The annotations a document holds (``entries``): an ``.xbf`` or a ``.step`` by its path,
    read as the viewer reads it (``document.Loaded``)."""
    from pathlib import Path

    from cadgen.engine import document

    return list(document.Loaded(Path(source)).structure().get("pmi") or [])


# --- exports -----------------------------------------------------------------------------------


def dropped(view: Any, kind: str) -> list[tuple[dict[str, Any], str]]:
    """Each annotation of a document that a ``kind`` file written from ``view`` does not carry whole,
    and why: a posed or partial STEP or xbf, or an xbf of a document this engine wrote, is a document
    made again from the view (``tree.tree_of``), which carries no PMI; and a STEP drops one linked to
    no geometry, as an xbf of a STEP (which copies its GD&T as read, ``copy``) keeps one the file links
    to no element of a part linked to nothing. A mesh carries no B-rep, so no PMI."""
    entries = view.source.structure.get("pmi") or []
    if kind not in ("step", "xbf") or not entries:
        return []
    shown = "STEP" if kind == "step" else kind
    if view.posed or view.parted:
        why = f"a {'posed' if view.posed else 'partial'} {shown} is a document made again, which carries no PMI"
        return [(entry, why) for entry in entries]
    if kind == "xbf" and not view.source.foreign:
        return [(entry, "an xbf written from it is a document made again, which carries no PMI") for entry in entries]
    return [(entry, f"{entry['status']}: {entry['problem']}") for entry in entries if entry["status"] != "ok"]


def refuse_dropped(view: Any, kind: str) -> None:
    """A ``kind`` file of ``view`` that would not carry whole an annotation the code made
    (``dropped``), refused by name: it would be no translation of the model's document. One of a
    document another system wrote is written: ``export.translate`` says what it leaves out."""
    from cadgen.engine.export import ExportRefused

    lost = [(entry, why) for entry, why in dropped(view, kind) if _from_code(entry)]
    if not lost:
        return
    held = len(view.source.structure["pmi"])
    if kind == "xbf":
        raise ExportRefused(f"{view.source.name} holds {held} PMI annotation(s), and an xbf written from it is a "
                            "document made again, which carries none yet: export it as built, whole")
    if view.posed or view.parted:
        raise ExportRefused(f"the document holds {held} PMI annotation(s), and a posed or partial STEP is a "
                            "document made again, which carries none: export it as built, whole")
    raise ExportRefused("a STEP would drop PMI linked to no geometry: "
                        + "; ".join(f"{entry['id']} ({why})" for entry, why in lost)
                        + ". Fix the refs in the model, or remove the annotations")


def _from_code(entry: dict[str, Any]) -> bool:
    """Whether an entry is an annotation a model's code made (its refs as the code wrote them), not
    one read from a file another system wrote."""
    return any(ref.get("written") is not None for ref in entry.get("refs") or ())
