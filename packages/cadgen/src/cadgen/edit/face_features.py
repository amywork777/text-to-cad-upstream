"""Which feature made each face of a part, by its geometry: the fallback for a face no model names.

A model's document says exactly what made each face (the engine's ``made_by``: the feature, and the
function, file and line of its call), and edit mode answers from that (``tracer.face_feature``). A
file names no model -- an imported STEP, or a part's STEP or xbf opened as a file -- and a document
served cold has no worker to ask, so this map, from the trace alone, answers for them. The tracer
keeps the result of each step it traced. A face
belongs to the first step whose result has a face on the same surface (the same plane, the same
cylinder by its axis and radius, and so on: ``surface_key``) that also overlaps it. Where the overlap
can be read off the B-rep it is: a face a boolean leaves untouched is the very same B-rep face
(``IsSame``) in every result after the one that made it. Any other face, one a later feature cut,
trimmed, split or merged, is tested by a point inside it, taken from its own UV interior (OCCT's own
point-in-face search, which a thin-walled tray's narrow rim has a point by too; not its centroid, which
a face with a hole or a bend can lie outside of), and goes to the first step with a face on its surface
that holds that point (OCCT's face classifier, IN or ON, at the part's tolerance). Both tests are made
in the order the steps made the faces, so a face is never given to a feature that only trimmed it. So
a face a later hole cuts through is still the extrude's that made it; a tab's top, flush with an
earlier tab's, is its own tab's; and the hole's wall, on a cylinder no step had before, the hole's. A
face two features' faces merged into goes to the first whose face holds the point taken.

The rule has a blind spot it cannot see past: a later feature's face can go to an earlier feature
whose face once covered that spot. A post standing in a pocket, its top flush with the rim, is the
block's, because the block's own top held that point before the pocket took it away. Telling the two
apart needs each face's lineage through the body, which the tracer does not keep; the engine's
``made_by`` does, which is why it answers first.

Where the rule finds no maker, the face is left out. A face on a free-form surface (a B-spline: a
loft's sides) has no key; one that no step's result has a face overlapping has no maker; one with no
point inside it to test (a sliver) is not tested. So is every face of an assembly (a compound with
children, which the engine's document makes several parts of), whose faces are numbered part by part.

Runs in the tracer's process only: it reads OCCT's B-rep.
"""

from __future__ import annotations

import math

from OCP.Bnd import Bnd_Box
from OCP.BOPTools import BOPTools_AlgoTools3D
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepTools import BRepTools
from OCP.IntTools import IntTools_FClass2d
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.gp import gp_Pnt, gp_Pnt2d
from OCP.IntTools import IntTools_Context
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape

from cadgen._internal.entity_ordinals import entity_map

# What a key's numbers are rounded to: a length to a millionth of the part's size (its bounding box's
# diagonal), so a part in inches keys as the same part in millimetres does; a direction's components
# and an angle to a millionth, a turn that moves a point at the part's size by as much.
PRECISION = 1e-6


def _rounded(value: float, unit: float) -> int:
    """``value`` as a whole number of ``unit``."""
    return round(value / unit)


def _point(point, unit: float) -> tuple[int, int, int]:
    return _rounded(point.X(), unit), _rounded(point.Y(), unit), _rounded(point.Z(), unit)


def _direction(direction) -> tuple[tuple[int, int, int], int]:
    """A unit direction rounded, turned so its first non-zero component is positive (an axis and its
    reverse are one line, a plane's two sides one plane), with the sign that took: 1 or -1."""
    rounded = tuple(_rounded(value, PRECISION) for value in (direction.X(), direction.Y(), direction.Z()))
    sign = -1 if next((value for value in rounded if value), 0) < 0 else 1
    return tuple(sign * value for value in rounded), sign


def _dot(direction, point) -> float:
    return direction.X() * point.X() + direction.Y() * point.Y() + direction.Z() * point.Z()


def _axis(axis, unit: float) -> tuple[int, ...]:
    """An axis line: its direction, sign fixed, and its point nearest the origin."""
    direction, location = axis.Direction(), axis.Location()
    along = _dot(direction, location)
    nearest = (location.X() - along * direction.X(), location.Y() - along * direction.Y(), location.Z() - along * direction.Z())
    return (*_direction(direction)[0], *(_rounded(value, unit) for value in nearest))


def surface_key(face, size: float = 1.0) -> tuple | None:
    """The surface ``face`` lies on (a build123d face, or OCCT's), as a key to tell it by, its lengths
    rounded to a millionth of ``size`` (the part's: its bounding box's diagonal), whichever way the face
    faces. None for a surface it cannot tell by its numbers (a B-spline, a surface of revolution).

    - A plane: its unit normal, turned so its first non-zero component is positive, and its distance
      from the origin along that normal.
    - A cylinder: its axis's direction, turned the same way, the axis's point nearest the origin, and
      its radius.
    - A cone: its apex, its axis's direction, and its half-angle.
    - A sphere: its centre and radius. A torus: its centre, its axis's direction and both radii.
    """
    unit = PRECISION * (size if size and size > 0 else 1.0)
    try:
        surface = BRepAdaptor_Surface(TopoDS.Face(getattr(face, "wrapped", face)), False)
        kind = surface.GetType()
        if kind == GeomAbs_Plane:
            axis = surface.Plane().Axis()
            normal, sign = _direction(axis.Direction())
            return ("plane", *normal, _rounded(sign * _dot(axis.Direction(), axis.Location()), unit))
        if kind == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            return ("cylinder", *_axis(cylinder.Axis(), unit), _rounded(cylinder.Radius(), unit))
        if kind == GeomAbs_Cone:
            # OCCT's cone runs through its apex both ways: the axis's sense and the angle's sign do not tell it.
            cone = surface.Cone()
            return ("cone", *_point(cone.Apex(), unit), *_direction(cone.Axis().Direction())[0],
                    _rounded(abs(cone.SemiAngle()), PRECISION))
        if kind == GeomAbs_Sphere:
            sphere = surface.Sphere()
            return ("sphere", *_point(sphere.Location(), unit), _rounded(sphere.Radius(), unit))
        if kind == GeomAbs_Torus:
            torus = surface.Torus()
            axis = torus.Axis()
            return ("torus", *_point(axis.Location(), unit), *_direction(axis.Direction())[0],
                    _rounded(torus.MajorRadius(), unit), _rounded(torus.MinorRadius(), unit))
    except Exception:  # noqa: BLE001 - a face OCCT cannot read has no key, and so no maker
        return None
    return None


def _brep(step: dict) -> TopoDS_Shape | None:
    """A step's result as it was made: the B-rep the tracer kept of it then (``brep``), which a later
    ``move`` or ``locate`` of the shape in place does not change, else the result as it is now."""
    kept = step.get("brep")
    if isinstance(kept, TopoDS_Shape):
        return kept
    wrapped = getattr(step.get("result"), "_wrapped", None)
    return wrapped if isinstance(wrapped, TopoDS_Shape) else None


def _has(shape: TopoDS_Shape, kind) -> bool:
    return TopExp_Explorer(shape, kind).More()


class _Faces:
    """The faces of the steps' results, each read once: a face a boolean leaves as it was is the same
    B-rep in every result after it (OCCT's hash and ``IsSame`` tell it; its orientation does not change
    its surface). Each has its ``surface_key``, and each surface the faces on it, with the step that
    first had each, in the order the steps made them (``on``)."""

    def __init__(self, size: float) -> None:
        self.size = size
        self.read: dict[int, list[tuple[TopoDS_Shape, tuple | None]]] = {}
        self.on: dict[tuple, list[tuple[int, TopoDS_Shape]]] = {}

    def key(self, face: TopoDS_Shape, step: int | None = None) -> tuple | None:
        """``face``'s surface key; a face read for the first time in a step's result goes on its surface's list."""
        seen = self.read.setdefault(hash(face), [])
        for other, key in seen:
            if other.IsSame(face):
                return key
        key = surface_key(face, self.size)
        seen.append((face, key))
        if key is not None and step is not None:
            self.on.setdefault(key, []).append((step, face))
        return key


# A face's UV bounds sampled this many a side, centre first, for a point inside it where OCCT's own
# search finds none.
GRID = 7
_SAMPLES = sorted((((column + .5) / GRID, (row + .5) / GRID) for column in range(GRID) for row in range(GRID)),
                  key=lambda sample: (sample[0] - .5) ** 2 + (sample[1] - .5) ** 2)


def _inside(face: TopoDS_Shape, context: IntTools_Context | None = None):
    """A point inside ``face``, from its own UV interior. OCCT's own search first
    (``BOPTools_AlgoTools3D.PointInFace``, which a narrow frame of a face, a thin-walled tray's rim,
    has a point by too); where it finds none, a grid over the face's UV bounds: the sample nearest
    their centre that the face's classifier puts inside it with its four neighbours, else the nearest
    inside it at all. None for a face neither finds a point inside (a sliver)."""
    face = TopoDS.Face(face)
    point, uv = gp_Pnt(), gp_Pnt2d()
    try:
        if BOPTools_AlgoTools3D.PointInFace_s(face, point, uv, context or IntTools_Context()) == 0:
            return point
    except Exception:  # noqa: BLE001 - a face OCCT's search fails on is sampled instead
        pass
    u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face)
    classify = IntTools_FClass2d(face, BRep_Tool.Tolerance_s(face))

    def inside(u: float, v: float) -> bool:
        return classify.Perform(gp_Pnt2d(u, v)) == TopAbs_IN

    du, dv = (u_max - u_min) / (2 * GRID), (v_max - v_min) / (2 * GRID)
    shallow = None
    for across, along in _SAMPLES:
        u, v = u_min + across * (u_max - u_min), v_min + along * (v_max - v_min)
        if not inside(u, v):
            continue
        if inside(u + du, v) and inside(u - du, v) and inside(u, v + dv) and inside(u, v - dv):
            return BRepAdaptor_Surface(face, False).Value(u, v)
        shallow = shallow or (u, v)
    return BRepAdaptor_Surface(face, False).Value(*shallow) if shallow else None


def _maker(face: TopoDS_Shape, key: tuple, faces: _Faces, tolerance: float, context: IntTools_Context) -> int | None:
    """The first step whose result has a face on ``face``'s surface that overlaps it: that very face, as
    a boolean left it, or one holding a point inside it. None where none does, or no point can be taken."""
    point = None
    for step, other in faces.on.get(key, ()):
        if other.IsSame(face):
            return step
        if point is None:
            point = _inside(face, context)
            if point is None:
                return None
        if BRepClass_FaceClassifier(TopoDS.Face(other), point, tolerance).State() in (TopAbs_IN, TopAbs_ON):
            return step
    return None


def _size(shape: TopoDS_Shape) -> float:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return 1.0 if box.IsVoid() else math.sqrt(box.SquareExtent()) or 1.0


def _several(shape) -> bool:
    """Whether the engine's document makes several parts of ``shape``: a compound placing children
    (``document.collect``), each numbered on its own. A compound of solids with no children is one part."""
    try:
        return bool(tuple(getattr(shape, "children", ()) or ()))
    except TypeError:
        return False


def face_features(shape, steps: list[dict], row_of: dict[int, str], features: list[dict]) -> dict[str, str]:
    """Each face of ``shape``, a part's body as traced, by its number as the viewer's references name it
    (``"12"`` for ``f12``: ``entity_map``'s order), mapped to the key of the feature that made it.

    ``steps`` are the trace's steps, ``row_of`` the key of the row each step's index is in, and
    ``features`` the part's features, each the rows it stands for (``rows``). A face is the first
    step's whose result has a face on its surface that overlaps it (`_maker`), and that step's row is a
    feature's. A face whose maker is not known is left out: one with no key, one no step's face
    overlaps, one whose step is in no row or in the rows of more than one feature (a cut by several
    tools at once), one OCCT cannot read (the others keep their makers), and every face of a body the
    engine's document makes several parts of (an assembly gets ``{}``).

    The body is read where its features made it: as the step that first made this B-rep kept it, so a
    body placed at its end (``Pos(...) * body``) or moved in place keeps its faces' makers. Only the
    steps up to that one can have made its faces.
    """
    try:
        return _credited(shape, steps, row_of, features)
    except Exception:  # noqa: BLE001 - a body OCCT cannot read has no face known to be any feature's; the part still reads
        return {}


def _credited(shape, steps, row_of, features) -> dict[str, str]:
    wrapped = getattr(shape, "_wrapped", None)
    if not isinstance(wrapped, TopoDS_Shape) or _several(shape):
        return {}
    made = next(((step["index"], brep) for step in steps if (brep := _brep(step)) is not None and brep.IsPartner(wrapped)), None)
    last, body = made if made is not None else (math.inf, wrapped)
    feature_of: dict[str, str | None] = {}
    for feature in features or ():
        for row in {feature.get("key"), *(feature.get("rows") or ())} - {None}:
            feature_of[row] = feature["key"] if feature_of.get(row, feature["key"]) == feature["key"] else None
    size = _size(body)
    made_faces = _Faces(size)
    for step in steps:
        if step["index"] > last:
            break
        brep = _brep(step)
        if brep is None or not _has(brep, TopAbs_SOLID):
            continue  # a sketch, a face or a plane makes no face of a solid itself; what makes a solid of it does
        explorer = TopExp_Explorer(brep, TopAbs_FACE)
        while explorer.More():
            made_faces.key(explorer.Current(), step["index"])
            explorer.Next()
    faces = entity_map(body, "face")
    context = IntTools_Context()
    credited = {}
    for number in range(1, faces.Extent() + 1):
        try:
            face = faces.FindKey(number)
            key = made_faces.key(face)
            maker = _maker(face, key, made_faces, PRECISION * size, context) if key is not None else None
        except Exception:  # noqa: BLE001 - a face OCCT cannot read has no maker known; the others keep theirs
            continue
        feature = feature_of.get(row_of.get(maker)) if maker is not None else None
        if feature:
            credited[str(number)] = feature
    return credited


def face_count(shape) -> int:
    """How many faces ``shape`` has, as the viewer numbers them: what a view checks the faces it shows
    against before it names one by ``face_features`` (a model on screen built from another script has
    other faces)."""
    wrapped = getattr(shape, "_wrapped", None)
    try:
        return entity_map(wrapped, "face").Extent() if isinstance(wrapped, TopoDS_Shape) else 0
    except Exception:  # noqa: BLE001 - none counted: a view then names no face by the map
        return 0
