"""Mates, as SolidWorks' Mate places a part of an assembly.

A mate holds a face, an edge or a vertex of the part that moves against one of a part it is mated
to: ``Coincident``, ``Concentric``, ``Distance``, ``Parallel``, ``Perpendicular``, ``Angle``,
``Tangent`` and ``Lock``.
``mate`` solves a part's mates together each time the assembly runs and moves the part the least
it can for all of them to hold, so what they leave free (where along a face it sits, how it is
turned about an axis) stays where the part was, and the part follows the parts it is mated to as
they change::

    from cadgen.mates import Coincident, Concentric, mate

    base_part, pin_part = base(), pin()
    mate(pin_part,
         Coincident(pin_part.faces().sort_by(Axis.Z)[0], base_part.faces().sort_by(Axis.Z)[-1]),
         Concentric(pin_part.faces().filter_by(GeomType.CYLINDER)[0], base_part.faces().filter_by(GeomType.CYLINDER)[0]))
    return Compound(children=[base_part, pin_part], label="stack")

Each mate's first item is on the part that moves, its second on the part it is mated to. What a
mate takes: flat faces (their plane), round faces (their axis), straight edges (their line),
circular edges (their centre and axis) and vertices (their point). Two flat faces are Coincident
face to face (``flip=True`` turns them to face the same way), and so is Distance, at its gap; two
circular edges Concentric sit centre on centre, as a pin seats in a hole. Mates that cannot all
hold raise :class:`MateError` naming them, as an over-defined sketch does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Angle", "Coincident", "Concentric", "Distance", "Lock", "MateError", "Parallel", "Perpendicular", "Tangent", "mate"]


class MateError(ValueError):
    """Mates that cannot hold, said to the engineer."""


@dataclass(frozen=True)
class _Place:
    """What a mate takes of a face, an edge or a vertex: a plane (a point on it and its normal), an
    axis or a line (a point on it and its way), a circle (its centre and axis) or a point."""

    kind: str
    point: np.ndarray
    way: np.ndarray | None = None
    # A round face's radius, for Tangent.
    radius: float | None = None


def _vector(value) -> np.ndarray:
    return np.array([float(value.X), float(value.Y), float(value.Z)]) if hasattr(value, "X") else np.array([float(c) for c in value])


def _unit(value) -> np.ndarray:
    vector = _vector(value)
    return vector / (np.linalg.norm(vector) or 1.0)


def _place(item) -> _Place:
    import build123d as B

    if isinstance(item, B.Face):
        if item.geom_type == B.GeomType.PLANE:
            plane = B.Plane(item)
            return _Place("plane", _vector(plane.origin), _unit(plane.z_dir))
        if item.geom_type in (B.GeomType.CYLINDER, B.GeomType.CONE):
            axis = item.axis_of_rotation
            radius = float(item.radius) if item.geom_type == B.GeomType.CYLINDER else None
            return _Place("axis", _vector(axis.position), _unit(axis.direction), radius)
    elif isinstance(item, B.Edge):
        if item.geom_type == B.GeomType.CIRCLE:
            return _Place("circle", _vector(item.arc_center), _unit(item.normal()))
        if item.geom_type == B.GeomType.LINE:
            return _Place("line", _vector(item.start_point()), _unit(item.end_point() - item.start_point()))
    elif isinstance(item, B.Vertex):
        return _Place("point", _vector(B.Vector(item)))
    elif isinstance(item, B.Axis):
        return _Place("axis", _vector(item.position), _unit(item.direction))
    elif isinstance(item, B.Plane):
        return _Place("plane", _vector(item.origin), _unit(item.z_dir))
    raise MateError("A mate takes flat and round faces, straight and circular edges, and vertices.")


# What a mate's places are, as they line up: a plane by its normal, an axis, line or circle by its way.
_LINES = ("axis", "line", "circle")


class _Mate:
    """A mate between ``moving`` (on the part that moves) and ``fixed`` (on a part it is mated to)."""

    label = "Mate"

    def __init__(self, moving, fixed, *, flip: bool = False):
        self.moving, self.fixed = _place(moving), _place(fixed)
        self.flip = bool(flip)
        # How the moving item's way lies against the fixed one's now: the sense an unflipped mate keeps.
        self.sense = 1.0
        if self.moving.way is not None and self.fixed.way is not None:
            self.sense = 1.0 if float(self.moving.way @ self.fixed.way) >= 0 else -1.0
        self.check()

    def check(self) -> None:
        """Raises MateError for items this mate cannot take."""

    def residuals(self, point, way) -> list:
        """How far the mate is from holding, with the moving item's point and way where a move puts them."""
        raise NotImplementedError

    def _refuse(self, words: str):
        raise MateError(f"{self.label} {words}")


def _aligned(way, fixed_way, sense):
    return list(way - sense * fixed_way)


def _parallel(way, fixed_way):
    return list(np.cross(way, fixed_way))


class Coincident(_Mate):
    """Two items made to touch: flat faces face to face (``flip``: facing the same way), a vertex on a
    face, two vertices together, a line or an axis on another, two circular edges centre on centre."""

    label = "Coincident"

    def check(self):
        kinds = {self.moving.kind, self.fixed.kind}
        if kinds <= {"plane", "point"} or kinds <= set(_LINES) | {"point"} or kinds <= {"plane", "line", "axis"}:
            return
        self._refuse("takes flat faces, vertices, straight edges and axes, or two circular edges.")

    def residuals(self, point, way):
        m, f = self.moving, self.fixed
        if m.kind == "plane" and f.kind == "plane":
            return _aligned(way, f.way, 1.0 if self.flip else -1.0) + [float((point - f.point) @ f.way)]
        if m.kind == "point" and f.kind == "plane":
            return [float((point - f.point) @ f.way)]
        if m.kind == "plane" and f.kind == "point":
            return [float((f.point - point) @ way)]
        if m.kind == "point" and f.kind == "point":
            return list(point - f.point)
        if m.kind == "point":
            return list(np.cross(point - f.point, f.way))
        if f.kind == "point":
            return list(np.cross(f.point - point, way))
        if m.kind in _LINES and f.kind == "plane":
            return [float(way @ f.way), float((point - f.point) @ f.way)]
        if m.kind == "plane" and f.kind in _LINES:
            return [float(f.way @ way), float((f.point - point) @ way)]
        sense = -self.sense if self.flip else self.sense
        made = _aligned(way, f.way, sense) + list(np.cross(point - f.point, f.way))
        return made + ([float((point - f.point) @ f.way)] if m.kind == "circle" and f.kind == "circle" else [])


class Concentric(_Mate):
    """Two round faces or circular edges on one axis, pointing the way they point now (``flip``: the
    other way); two circular edges sit centre on centre, as a pin seats in a hole."""

    label = "Concentric"

    def check(self):
        if self.moving.kind not in _LINES or self.fixed.kind not in _LINES:
            self._refuse("puts two round faces or circular edges on one axis.")

    def residuals(self, point, way):
        f = self.fixed
        sense = -self.sense if self.flip else self.sense
        made = _aligned(way, f.way, sense) + list(np.cross(point - f.point, f.way))
        return made + ([float((point - f.point) @ f.way)] if self.moving.kind == "circle" and f.kind == "circle" else [])


class Distance(_Mate):
    """Two flat faces facing each other a distance apart (``flip``: facing the same way), a vertex
    that far from a face or from another vertex, or two parallel axes that far apart."""

    label = "Distance"

    def __init__(self, moving, fixed, distance, *, flip: bool = False):
        self.distance = float(distance)
        if self.distance < 0:
            raise MateError("A distance is 0 or more; flip turns the part the other way.")
        super().__init__(moving, fixed, flip=flip)

    def check(self):
        kinds = {self.moving.kind, self.fixed.kind}
        if not (kinds <= {"plane", "point"} or kinds <= set(_LINES)):
            self._refuse("takes flat faces and vertices, or two axes.")

    def residuals(self, point, way):
        m, f, gap = self.moving, self.fixed, self.distance
        if m.kind == "plane" and f.kind == "plane":
            return _aligned(way, f.way, 1.0 if self.flip else -1.0) + [float((point - f.point) @ f.way) - gap]
        if m.kind == "point" and f.kind == "plane":
            return [float((point - f.point) @ f.way) - gap]
        if m.kind == "plane" and f.kind == "point":
            return [float((f.point - point) @ way) - gap]
        if m.kind == "point" and f.kind == "point":
            return [float(np.linalg.norm(point - f.point)) - gap]
        return _parallel(way, f.way) + [float(np.linalg.norm(np.cross(point - f.point, f.way))) - gap]


class Parallel(_Mate):
    """Two faces, edges or axes made parallel, where they are."""

    label = "Parallel"

    def check(self):
        if self.moving.way is None or self.fixed.way is None:
            self._refuse("takes faces, edges and axes, not vertices.")

    def residuals(self, point, way):
        f = self.fixed
        if (self.moving.kind == "plane") != (f.kind == "plane"):
            return [float(way @ f.way)]  # a line parallel to a face lies square to its normal
        return _aligned(way, f.way, -self.sense if self.flip else self.sense)


class Perpendicular(_Mate):
    """Two faces, edges or axes made square to each other, where they are."""

    label = "Perpendicular"

    def check(self):
        if self.moving.way is None or self.fixed.way is None:
            self._refuse("takes faces, edges and axes, not vertices.")

    def residuals(self, point, way):
        f = self.fixed
        if (self.moving.kind == "plane") != (f.kind == "plane"):
            return _parallel(way, f.way)  # a line square to a face runs along its normal
        return [float(way @ f.way)]


class Angle(_Mate):
    """Two faces, or two edges or axes, at an angle to each other, in degrees."""

    label = "Angle"

    def __init__(self, moving, fixed, degrees):
        self.degrees = float(degrees)
        if not 0 <= self.degrees <= 180:
            raise MateError("An angle mate is 0 to 180 degrees.")
        super().__init__(moving, fixed)

    def check(self):
        if self.moving.way is None or self.fixed.way is None or (self.moving.kind == "plane") != (self.fixed.kind == "plane"):
            self._refuse("takes two faces, or two edges or axes.")

    def residuals(self, point, way):
        return [float(way @ self.fixed.way) - math.cos(math.radians(self.degrees))]


class Tangent(_Mate):
    """A round face against a flat one, or two round faces side by side, touching along a line, as
    SolidWorks' Tangent mate: a cylinder's axis its radius from the face and parallel to it (``flip``:
    on the face's other side); two cylinders' axes parallel, their radii apart."""

    label = "Tangent"

    def check(self):
        m, f = self.moving, self.fixed
        round_ = lambda place: place.kind == "axis" and place.radius is not None  # noqa: E731
        if not ((round_(m) and (f.kind == "plane" or round_(f))) or (m.kind == "plane" and round_(f))):
            self._refuse("takes a round face and a flat one, or two round faces.")

    def residuals(self, point, way):
        m, f = self.moving, self.fixed
        side = -1.0 if self.flip else 1.0
        if m.kind == "axis" and f.kind == "plane":
            return [float(way @ f.way), float((point - f.point) @ f.way) - side * m.radius]
        if m.kind == "plane" and f.kind == "axis":
            return [float(way @ f.way), float((f.point - point) @ way) + side * f.radius]
        return _parallel(way, f.way) + [float(np.linalg.norm(np.cross(point - f.point, f.way))) - (m.radius + f.radius)]


class Lock(_Mate):
    """A part held where it stands against another, as SolidWorks' Lock mate: not moved or turned
    from where its script puts it, whatever its other mates would do."""

    label = "Lock"

    def check(self):
        if self.moving.way is None:
            self._refuse("takes a face or an edge of the part to hold.")

    def residuals(self, point, way):
        return list(point - self.moving.point) + list(way - self.moving.way)


def _turn(vector: np.ndarray) -> np.ndarray:
    """The rotation a rotation vector stands for (its length the angle in radians), as a matrix."""
    angle = float(np.linalg.norm(vector))
    if angle < 1e-15:
        return np.eye(3)
    k = vector / angle
    cross = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * cross + (1 - math.cos(angle)) * cross @ cross


def mate(part, *mates: _Mate):
    """Moves ``part`` the least it can for every mate to hold, and returns it. Raises MateError
    naming the mates that cannot all hold."""
    from scipy.optimize import least_squares

    import build123d as B

    if not mates:
        return part
    for each in mates:
        if not isinstance(each, _Mate):
            raise MateError("mate() takes the part, then its mates: Coincident(...), Concentric(...), ...")
    box = part.bounding_box()
    pivot = _vector(box.center())
    scale = float(box.diagonal) or 1.0

    def residuals(x):
        turn = _turn(x[:3])
        made = []
        for each in mates:
            point = turn @ (each.moving.point - pivot) + pivot + x[3:]
            way = turn @ each.moving.way if each.moving.way is not None else None
            made += each.residuals(point, way)
        return np.array(made, dtype=float)

    # First the least move that holds them, every turn and slide weighed alike (a turn by the part's
    # size), so what they leave free stays put; then exactly, from there.
    weights = np.array([scale, scale, scale, 1.0, 1.0, 1.0]) * 1e-4
    held = least_squares(lambda x: np.concatenate([residuals(x), weights * x]), np.zeros(6), method="lm", xtol=1e-15, ftol=1e-15, gtol=1e-15)
    count = len(residuals(held.x))
    exact = least_squares(residuals, held.x, method="lm" if count >= 6 else "trf", xtol=1e-15, ftol=1e-15, gtol=1e-15)
    left = residuals(exact.x)
    if left.size and float(np.max(np.abs(left))) > 1e-6 * scale:
        names = ", ".join(f"{each.label}" for each in mates)
        raise MateError(f"{names} cannot all hold. Take one out, or change its value.")
    angle = float(np.linalg.norm(exact.x[:3]))
    turn = _turn(exact.x[:3])
    shift = pivot + exact.x[3:] - turn @ pivot
    axis = exact.x[:3] / angle if angle > 1e-15 else np.array([0.0, 0.0, 1.0])
    part.move(B.Location(B.Vector(*shift), B.Vector(*axis), math.degrees(angle)))
    return part
