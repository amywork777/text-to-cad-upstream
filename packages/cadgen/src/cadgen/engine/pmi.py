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

**What is held.** One structured record per annotation, in the document's own terms: XCAF's
``XCAFDimTolObjects`` objects on the GD&T tool's labels (``XCAFDoc_DimTolTool``) hold the kind,
values and units (millimetres, the document's) and link the annotation to the sub-shape labels of
the faces it is on; beside each, one cadgen attribute (``EXTRA_GUID``, JSON) holds what XCAF has
no place for: the author's id and label, each ref as the code wrote it, the annotation's status,
and its presentation. Nothing is held twice. The STEP writer reads the XCAF objects and writes
AP242's semantic PMI (``DIMENSIONAL_SIZE``/``DIMENSIONAL_LOCATION`` with ``PLUS_MINUS_TOLERANCE``,
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
not parallel, a datum letter the part does not define), or, written as text, another kind of face
than it named on the model's last build (a hole whose name passed to a flat side). The kind it is
held to is kept in the document and follows the ref until the code writes it anew. An annotation's status is its worst
ref's. One not ``ok`` is kept in the document, with its status, values and refs as written, and
linked to no geometry; the build reports it, and a STEP export refuses to drop it.

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
(``PMIUnsupported``), never approximated. A document read from a STEP another system wrote lists
its PMI too; what this module does not model is listed as ``unsupported`` with its XCAF type.
PMI is part-level: an annotation is on one part, and an assembly is refused.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = ["DIMENSION_TYPES", "GEOMETRIC_CHARACTERISTICS", "PMIError", "PMIUnsupported", "annotate", "basic", "datum",
           "diameter", "dimension", "distance", "flatness", "geometric", "place", "plus_minus", "position", "read"]

# The attribute an annotated shape holds its annotations in (a tuple of plain dicts), as a part's
# configurations are held (``kernel.memo`` keys it).
PMI = "xbf_pmi"
# The GUID of the cadgen attribute beside each XCAF GD&T object: its JSON (see the module).
EXTRA_GUID = "5d3a7c1e-9f42-4b86-a0e5-3c7b9d2f6e18"
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
        raise PMIError(f"a plus-minus tolerance's upper deviation ({upper}) is above its lower ({lower})")
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
    # The kind of face (plane, cylinder) this ref is held to: what it named when it last resolved,
    # kept in the document (``_extra``) and asked of the next build (``remember``). None for a ref
    # the code selects as a Face, which is whatever that selection picks each build.
    face: str | None = None


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
    previous = tree.pmi_previous
    for part, given in tree.pmi or ():
        faces = _faces(part.shape)
        names = list((part.names or {}).get("faces") or [])
        owners = {part.name, tree.root.name}
        letters = {entry["datum"]["letter"] for entry in given if entry["kind"] == "datum"}
        found.append((part, [_resolved(entry, faces, names, owners, letters, previous.get((part.name, entry["id"])) or {})
                             for entry in given]))
    tree.pmi_resolved = found
    return found


def _resolved(spec: dict[str, Any], faces: Any, names: list[str | None], owners: set[str],
              letters: set[str], held: dict[tuple[str, str], str]) -> Resolved:
    """One annotation against the part as built; ``held`` the face kind each of its refs (by role
    and written text) named on the model's last build."""
    refs = [_ref(given, faces, names, owners) for given in spec["refs"]]
    texts = [given["face"] is None for given in spec["refs"]]  # written in code, not a selected Face
    for ref, text in zip(refs, texts):
        ref.face = held.get((ref.role, ref.written)) if text else None
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
        # A ref written as text that names another kind of face than it did on the last build names
        # another face: a hole made a square cut passes the hole's name to a flat side. It is
        # flagged where the annotation could stand on the new face too (elsewhere the check above
        # has said so), and it stays held to the kind it had until the code writes it anew.
        for ref, surface, text in zip(refs, surfaces, texts):
            if ref.status != "ok" or not text:
                continue
            if ref.face is not None and ref.face != surface[0]:
                ref.status = "invalid"
                ref.problem = (f"{ref.written} named a {ref.face} face on the last build and names a {surface[0]} "
                               "face now: it names another face than the annotation was made on. Point the ref "
                               "at the face meant (written anew, it is held to that face's kind), or remove the "
                               "annotation")
            elif ref.face is None:
                ref.face = surface[0]
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


def remember(tree: Any, previous: dict[tuple[str, str], dict[tuple[str, str], str]]) -> None:
    """What each ref of ``tree``'s annotations named on the model's last build (``previous_of_tree``,
    ``previous_of_file``): asked of before ``tree`` is resolved."""
    tree.pmi_previous, tree.pmi_resolved = previous, None


def previous_of_tree(tree: Any) -> dict[tuple[str, str], dict[tuple[str, str], str]]:
    """Each annotation's refs' face kinds as a build resolved them, by (part, id), then (role, written)."""
    found: dict = {}
    for part, items in resolve(tree) if tree is not None and tree.pmi else ():
        for item in items:
            found[(part.name, item.spec["id"])] = {(ref.role, ref.written): ref.face for ref in item.refs if ref.face}
    return found


def previous_of_file(path: Any) -> dict[tuple[str, str], dict[tuple[str, str], str]]:
    """The same, as the model's saved xbf holds them: the last build of a model this process has not
    built. A file that cannot be read holds nothing to compare with."""
    from cadgen.engine import document

    try:
        loaded = document.load(path)
        records = records_of_document(loaded.doc, loaded.prototypes)
    except Exception:  # noqa: BLE001 - no history is no check, never a failed build
        return {}
    found: dict = {}
    for record in records:
        extra = record["extra"]
        if extra is None or extra.get("part") is None:
            continue
        found[(extra["part"], extra["id"])] = {(ref["role"], ref["written"]): ref["face"]
                                               for ref in extra["refs"] if ref.get("face")}
    return found


def signature(tree: Any) -> tuple:
    """What a tree's annotations are, for the build's signature: a change to one remakes the document."""
    return tuple(_text({"part": part.name, "pmi": list(given)}) for part, given in tree.pmi or ())


def problems(tree: Any) -> list[dict[str, Any]]:
    """Every annotation of ``tree`` that is not ``ok``: its part, id, status and why."""
    return [{"part": part.name, "id": item.spec["id"], "status": item.status, "problem": item.problem}
            for part, items in resolve(tree) for item in items if item.status != "ok"]


# --- the XCAF document -------------------------------------------------------------------------


def write(doc: Any, tree: Any, label_of: Any) -> None:
    """The tree's annotations into ``doc``'s GD&T tool, each part's in its order, datums first
    (a tolerance's frame names them); ``label_of(part)`` is the part's shape label."""
    if not tree.pmi:
        return
    from OCP.Standard import Standard_GUID
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDataStd import TDataStd_AsciiString
    from OCP.TDF import TDF_Label, TDF_LabelSequence
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
            TDataStd_AsciiString.Set_s(at, guid, TCollection_AsciiString(_text(_extra(item, part.name))))


def _extra(item: Resolved, part: str) -> dict[str, Any]:
    spec = item.spec
    return {"id": spec["id"], "label": spec["label"], "presentation": spec["presentation"], "status": item.status,
            "problem": item.problem, "kind": spec["kind"], "part": part,
            "refs": [{"role": ref.role, "written": ref.written, "status": ref.status, "candidates": ref.candidates,
                      "problem": ref.problem, "face": ref.face} for ref in item.refs],
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


# --- read back ---------------------------------------------------------------------------------


def records_of_document(doc: Any, prototypes: list[Any]) -> list[dict[str, Any]]:
    """A document's annotations as records (``entries``' input): every GD&T object its tool holds,
    datums, dimensions and geometric tolerances in the tool's order. ``prototypes`` are the
    document's (``document.Prototype``: each its label's entry and shape)."""
    from OCP.Standard import Standard_GUID
    from OCP.TDataStd import TDataStd_AsciiString
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_DimensionType_Location_LinearDistance,
                                        XCAFDimTolObjects_DimensionType_Size_Diameter,
                                        XCAFDimTolObjects_GeomToleranceMatReqModif_None,
                                        XCAFDimTolObjects_GeomToleranceType_Flatness,
                                        XCAFDimTolObjects_GeomToleranceType_Position,
                                        XCAFDimTolObjects_GeomToleranceTypeValue_Diameter,
                                        XCAFDimTolObjects_GeomToleranceTypeValue_None)
    from OCP.XCAFDoc import XCAFDoc_Datum, XCAFDoc_DimTolTool, XCAFDoc_Dimension, XCAFDoc_GeomTolerance

    from cadgen.engine.document import _entry

    dimensions = {XCAFDimTolObjects_DimensionType_Size_Diameter: "diameter",
                  XCAFDimTolObjects_DimensionType_Location_LinearDistance: "distance"}
    characteristics = {XCAFDimTolObjects_GeomToleranceType_Flatness: "flatness",
                       XCAFDimTolObjects_GeomToleranceType_Position: "position"}
    tool_label = doc.Main().FindChild(DIMTOL_TAG, False)
    if tool_label.IsNull() or not tool_label.IsAttribute(XCAFDoc_DimTolTool.GetID_s()):
        return []
    tool = XCAFDoc_DimTolTool.Set_s(tool_label)
    by_entry = {prototype.entry: prototype for prototype in prototypes}
    face_maps: dict[int, Any] = {}
    guid = Standard_GUID(EXTRA_GUID)

    def located(label: Any) -> tuple[int, int] | None:
        """A ref label's prototype and face ordinal; None where it is no face of a prototype."""
        from OCP.TopAbs import TopAbs_FACE
        from OCP.XCAFDoc import XCAFDoc_ShapeTool

        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        if shape.IsNull() or shape.ShapeType() != TopAbs_FACE:
            return None
        owner = label.Father()
        prototype = by_entry.get(_entry(owner))
        if prototype is None:
            return None
        faces = face_maps.get(prototype.index)
        if faces is None:
            faces = face_maps[prototype.index] = _faces(XCAFDoc_ShapeTool.GetShape_s(owner))
        ordinal = faces.FindIndex(shape)
        return (prototype.index, ordinal) if ordinal else None

    def extra(label: Any) -> dict[str, Any] | None:
        found = TDataStd_AsciiString()
        if label.IsAttribute(guid) and label.FindAttribute(guid, found):
            return json.loads(found.Get().ToCString())
        return None

    def linked(label: Any) -> tuple[list, list]:
        first, second = TDF_LabelSequence(), TDF_LabelSequence()
        tool.GetRefShapeLabel_s(label, first, second)
        return ([located(first.Value(at)) for at in range(1, first.Length() + 1)],
                [located(second.Value(at)) for at in range(1, second.Length() + 1)])

    records: list[dict[str, Any]] = []
    datum_names: dict[str, str] = {}

    def record(label: Any, kind: str, values: dict[str, Any], first: list, second: list,
               xcaf_type: str | None) -> None:
        held = extra(label)
        if kind == "dimension" and second:
            targets = [("from", hit) for hit in first] + [("to", hit) for hit in second]
        else:
            targets = [("feature", hit) for hit in first]
        prototypes_held = {hit[0] for _role, hit in targets if hit is not None}
        record = {"kind": kind, "values": values, "xcaf_type": xcaf_type,
                  "part": min(prototypes_held) if prototypes_held else None,
                  "targets": targets, "extra": held, "entry": _entry(label)}
        records.append(record)

    sequence = TDF_LabelSequence()
    tool.GetDatumLabels(sequence)
    for at in range(1, sequence.Length() + 1):
        label = sequence.Value(at)
        if not label.IsAttribute(XCAFDoc_Datum.GetID_s()):
            continue
        found = XCAFDoc_Datum.Set_s(label).GetObject()
        letter = _name_of(found)
        datum_names[_entry(label)] = letter
        first, _second = linked(label)
        record(label, "datum", {"letter": letter}, first, [], None)
    sequence = TDF_LabelSequence()
    tool.GetDimensionLabels(sequence)
    for at in range(1, sequence.Length() + 1):
        label = sequence.Value(at)
        if not label.IsAttribute(XCAFDoc_Dimension.GetID_s()):
            continue
        found = XCAFDoc_Dimension.Set_s(label).GetObject()
        type_name = found.GetType().name
        first, second = linked(label)
        kind = dimensions.get(found.GetType())
        tolerance = None
        if found.IsDimWithPlusMinusTolerance():
            tolerance = {"type": "plus_minus", "upper": _as_held(found.GetUpperTolValue()),
                         "lower": _as_held(-found.GetLowerTolValue())}
        notes = [(found.GetDescriptionName(at).ToCString(), found.GetDescription(at).ToCString())
                 for at in range(found.NbDescriptions())] if found.HasDescriptions() else []
        is_basic = THEORETICAL in notes
        values = {"type": kind, "basic": is_basic, "nominal": _as_held(found.GetValue()), "tolerance": tolerance}
        # What this module does not model -- a reference (auxiliary) dimension, any other note, a
        # basic dimension of another type -- is listed as unsupported, with what it holds.
        other = [note for note in notes if note != THEORETICAL]
        supported = kind is not None and not other and (kind == "distance" or not is_basic)
        if notes:
            values["notes"] = [list(note) for note in notes]
        record(label, "dimension" if supported else "unsupported", values, first, second,
               None if supported else type_name + (f" (notes {other})" if other else " (basic)" if is_basic else ""))
    sequence = TDF_LabelSequence()
    tool.GetGeomToleranceLabels(sequence)
    for at in range(1, sequence.Length() + 1):
        label = sequence.Value(at)
        if not label.IsAttribute(XCAFDoc_GeomTolerance.GetID_s()):
            continue
        found = XCAFDoc_GeomTolerance.Set_s(label).GetObject()
        type_name = found.GetType().name
        characteristic = characteristics.get(found.GetType())
        first, _second = linked(label)
        named = TDF_LabelSequence()
        XCAFDoc_DimTolTool.GetDatumWithObjectOfTolerLabels_s(label, named)
        letters = []
        for place in range(1, named.Length() + 1):
            datum_label = named.Value(place)
            datum = XCAFDoc_Datum.Set_s(datum_label).GetObject()
            letters.append((datum.GetPosition(), _name_of(datum)))
        modified = (found.GetModifiers().Length() > 0
                    or found.GetMaterialRequirementModifier() != XCAFDimTolObjects_GeomToleranceMatReqModif_None)
        value_type = found.GetTypeOfValue()
        if value_type == XCAFDimTolObjects_GeomToleranceTypeValue_Diameter:
            zone = "diameter"
        elif value_type == XCAFDimTolObjects_GeomToleranceTypeValue_None:
            zone = None
        else:
            zone = "other"
        values = {"characteristic": characteristic, "value": _as_held(found.GetValue()), "unit": UNIT, "zone": zone,
                  "modifier": None, "datums": [letter for _place, letter in sorted(letters)]}
        supported = characteristic is not None and not modified and zone != "other"
        record(label, "geometric_tolerance" if supported else "unsupported", values, first, [],
               None if supported else type_name + (" (with modifiers)" if modified else ""))
    return records


def _name_of(datum: Any) -> str:
    """A datum object's letter; the empty string for none (a null handle reads as None)."""
    name = datum.GetName()
    return name.ToCString() if name is not None else ""


def records_of_tree(tree: Any, index_of: dict[int, int]) -> list[dict[str, Any]]:
    """A built tree's annotations as the records ``records_of_document`` reads back from its
    document: the same order (each part's datums, then the rest), the same values, as XCAF
    holds them (``_as_held``)."""
    records = []
    for part, items in resolve(tree):
        index = index_of[id(part)]
        ordered = _datums_first(items)
        by_kind = {"datum": [], "dimension": [], "geometric_tolerance": []}
        for item in ordered:
            spec = item.spec
            linked = item.status == "ok"
            targets = [(ref.role, (index, ref.ordinal) if linked else None) for ref in item.refs] if linked else []
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
            by_kind[spec["kind"]].append({"kind": spec["kind"], "values": values, "xcaf_type": None,
                                          "part": index if linked else None, "targets": targets,
                                          "extra": json.loads(_text(_extra(item, part.name))), "entry": None})
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
    ``part`` (a prototype index), ``refs`` (each ``role``, ``ref`` -- canonical as ``refs`` spells
    it for this document --, ``written``, ``status``, ``candidates``, ``problem``),
    ``presentation``, ``xcaf_type``, and the kind's own block of values."""
    from cadgen.engine import refs as grammar

    root = grammar.structure_tree(structure)
    first_node: dict[int, Any] = {}
    for node in root.parts():
        first_node.setdefault(node.payload["prototype"], node)
    one_part = len(root.parts()) == 1
    prototypes = structure["prototypes"]

    def canonical(index: int, ordinal: int) -> str:
        name = (prototypes[index].get("faceNames") or {}).get(str(ordinal))
        node = first_node.get(index)
        if node is None:
            return name or f"face {ordinal}"
        return grammar._element_ref(root, node, "face", ordinal, name, one_part)

    found = []
    counters: dict[str, int] = {}
    for record in records:
        extra = record["extra"]
        kind = record["kind"]
        if extra is not None:
            refs = []
            targets = list(record["targets"])
            for at, ref in enumerate(extra["refs"]):
                hit = targets[at][1] if at < len(targets) else None
                refs.append({"role": ref["role"], "written": ref["written"], "status": ref["status"],
                             "ref": canonical(*hit) if hit is not None else ref["written"],
                             # An unlinked annotation names no part of the document: its candidates by ordinal.
                             "candidates": [canonical(record["part"], ordinal) if record["part"] is not None
                                            else f"face {ordinal}" for ordinal in ref["candidates"]] or None,
                             "problem": ref["problem"]})
            entry = {"id": extra["id"], "kind": kind, "label": extra["label"], "status": extra["status"],
                     "problem": extra["problem"], "part": record["part"], "refs": refs,
                     "presentation": extra["presentation"], "xcaf_type": None}
            unlinked = extra.get("unlinked")
        else:
            counters[kind] = counters.get(kind, 0) + 1
            refs = [{"role": role, "written": None, "status": "ok" if hit is not None else "missing",
                     "ref": canonical(*hit) if hit is not None else None, "candidates": None,
                     "problem": None if hit is not None else "the file links it to no face of a part"}
                    for role, hit in record["targets"]]
            status = _worst(ref["status"] for ref in refs) if refs else "missing"
            entry = {"id": f"{record['values'].get('letter') or kind}" if kind == "datum" else f"{kind}-{counters[kind]}",
                     "kind": kind, "label": None, "status": status,
                     "problem": None if status == "ok" else "the file links it to no face of a part",
                     "part": record["part"], "refs": refs, "presentation": None, "xcaf_type": record["xcaf_type"]}
            unlinked = None
        values = record["values"]
        if kind == "datum":
            entry["datum"] = {"letter": values["letter"]}
        elif kind == "dimension":
            if unlinked is not None:
                entry["dimension"] = {"type": unlinked["dimension"]["type"],
                                      "basic": bool(unlinked["dimension"].get("basic")), "nominal": None,
                                      "tolerance": unlinked["dimension"]["tolerance"]}
            else:
                entry["dimension"] = {"type": values["type"], "basic": bool(values.get("basic")),
                                      "nominal": {"value": values["nominal"], "unit": UNIT, "source": "geometry"},
                                      "tolerance": values["tolerance"]}
        elif kind == "geometric_tolerance":
            entry["geometric_tolerance"] = dict(unlinked["geometric_tolerance"] if unlinked is not None else values)
        else:
            entry["values"] = values
        found.append(entry)
    return found


def read(source: Any) -> list[dict[str, Any]]:
    """The annotations a document holds (``entries``): an ``.xbf`` or a ``.step`` by its path,
    read as the viewer reads it (``document.Loaded``)."""
    from pathlib import Path

    from cadgen.engine import document

    return list(document.Loaded(Path(source)).structure().get("pmi") or [])
