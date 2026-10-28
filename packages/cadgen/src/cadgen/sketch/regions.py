"""A solved sketch's closed regions, as build123d faces on its plane.

The sketch's curves (construction geometry aside) are chained into closed loops: a circle is one
alone, and lines and arcs join where their points meet (the same point, a coincident pair, or
points solved to one place). A sketch fillet's arc takes its corner (``fillets.py``). A loop inside another is a hole in it, and a loop inside a hole is a
region of its own again, as a CAD tool reads a profile. Each region is a face whose normal is the
sketch plane's, so an extrude of it goes the way the plane faces.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .fillets import fillet_arcs
from .sketch import PLANE_NAMES, Arc, Circle, Line, Point, SketchError, Spline

__all__ = ["faces", "loops", "path", "plane_of"]

ARC_SAMPLES = 24
CIRCLE_SAMPLES = 64


def plane_of(sketch):
    """The build123d Plane a sketch lies on, offset along its normal by the sketch's offset."""
    import build123d as B

    plane = sketch.plane
    if isinstance(plane, str):
        name = PLANE_NAMES.get(plane)
        if name is None:
            raise SketchError(f"{sketch.name}: no plane called {plane}. Use Top, Front or Right, or a build123d Plane or Face.")
        base = getattr(B.Plane, name)
    elif isinstance(plane, B.Plane):
        base = plane
    elif isinstance(plane, B.Face):
        # As a CAD tool places a sketch on a face: its origin where the part's origin falls on the
        # face's plane, and its x along the part's X (its Y, on a face square to X), so the
        # sketch's dimensions from its origin are the part's.
        normal = B.Plane(plane).z_dir
        origin = normal * normal.dot(B.Plane(plane).origin)
        along = B.Vector(1, 0, 0) - normal * normal.X
        if along.length < 1e-6:
            along = B.Vector(0, 1, 0) - normal * normal.Y
        base = B.Plane(origin=origin, x_dir=along.normalized(), z_dir=normal)
    else:
        raise SketchError(f"{sketch.name}: a sketch's plane is Top, Front or Right, or a build123d Plane or Face.")
    return base.offset(sketch.offset * sketch.unit) if sketch.offset else base


def _arc_angles(arc):
    """Where an arc starts and how far it sweeps, in radians (negative when clockwise)."""
    a0 = math.atan2(arc.start.y - arc.center.y, arc.start.x - arc.center.x)
    a1 = math.atan2(arc.end.y - arc.center.y, arc.end.x - arc.center.x)
    sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    return a0, (sweep - 2 * math.pi if arc.clockwise else sweep)


def _round(curve) -> bool:
    """Whether a curve is a loop on its own, with no ends: a circle, or a closed spline."""
    return isinstance(curve, Circle) or (isinstance(curve, Spline) and curve.closed)


def _samples(curve, forward: bool) -> list[tuple[float, float]]:
    """Points along a curve, start to end (end to start when not ``forward``), its end left off."""
    if isinstance(curve, Spline):
        points = curve.samples()
        if curve.closed:
            return points[:-1]
    elif isinstance(curve, Circle):
        return [(curve.center.x + curve.radius * math.cos(2 * math.pi * i / CIRCLE_SAMPLES),
                 curve.center.y + curve.radius * math.sin(2 * math.pi * i / CIRCLE_SAMPLES)) for i in range(CIRCLE_SAMPLES)]
    elif isinstance(curve, Arc):
        a0, sweep = _arc_angles(curve)
        r = curve.radius
        points = [(curve.center.x + r * math.cos(a0 + sweep * i / ARC_SAMPLES), curve.center.y + r * math.sin(a0 + sweep * i / ARC_SAMPLES))
                  for i in range(ARC_SAMPLES + 1)]
    else:
        points = [(curve.start.x, curve.start.y), (curve.end.x, curve.end.y)]
    if not forward:
        points.reverse()
    return points[:-1]


class _Loop:
    def __init__(self, parts):
        self.parts = parts  # (curve, forward), in order around the loop
        self.polygon = [point for curve, forward in parts for point in _samples(curve, forward)]
        self.area = 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(self.polygon, self.polygon[1:] + self.polygon[:1]))

    def contains(self, other: _Loop) -> bool:
        x, y = other.polygon[0]
        inside = False
        for (x0, y0), (x1, y1) in zip(self.polygon, self.polygon[1:] + self.polygon[:1]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
        return inside and abs(other.area) < abs(self.area)


def _rounded(curves, arcs):
    """The curves with each fillet's or chamfer's corner taken off its two lines, and its arc or line between them."""
    ends: dict[tuple[int, str], Point] = {}
    made = []
    for arc in arcs:
        start, end = Point(f"{arc.name}.start", *arc.start), Point(f"{arc.name}.end", *arc.end)
        ends[(id(arc.a), arc.end_of(arc.a))] = start
        ends[(id(arc.b), arc.end_of(arc.b))] = end
        if arc.kind == "chamfer":
            made.append(Line(arc.name, start, end, False, None))
            continue
        made.append(Arc(arc.name, Point(f"{arc.name}.center", *arc.center), start, end, arc.clockwise))
    out = []
    for curve in curves:
        if isinstance(curve, Line) and ((id(curve), "start") in ends or (id(curve), "end") in ends):
            curve = Line(curve.name, ends.get((id(curve), "start"), curve.start), ends.get((id(curve), "end"), curve.end),
                         curve.construction, curve.source)
        out.append(curve)
    return out + made


def _drawn(sketch) -> list:
    """The sketch's curves a solid is made from: construction aside, each fillet's arc in its corner."""
    curves = [curve for curve in sketch.curves if not curve.construction]
    rounded = [arc for arc in fillet_arcs(sketch) if not arc.a.construction]
    return _rounded(curves, rounded) if rounded else curves


def _joints(sketch, curves):
    """Which ends of the curves are one place (the same point, a coincident pair, or points
    solved to one place): `root` gives each end the one point standing for its place, and
    `meeting` the curves at each place, by that point's id. Circles have no ends."""
    scale = max([1.0, *(abs(c) for p in sketch.points for c in (p.x, p.y))])
    parent: dict[int, Point] = {}

    def root(point: Point) -> Point:
        while id(point) in parent and parent[id(point)] is not point:
            point = parent[id(point)]
        return point

    def join(a: Point, b: Point) -> None:
        ra, rb = root(a), root(b)
        if ra is not rb:
            parent[id(rb)] = ra

    ends = [point for curve in curves if not _round(curve) for point in (curve.start, curve.end)]
    for relation in sketch.relations:
        if relation.kind == "coincident" and all(isinstance(ref, Point) for ref in relation.refs):
            join(*relation.refs)
    for i, a in enumerate(ends):
        for b in ends[i + 1:]:
            if math.hypot(a.x - b.x, a.y - b.y) <= 1e-6 * scale:
                join(a, b)
    meeting: dict[int, list] = defaultdict(list)
    for curve in curves:
        if not _round(curve):
            meeting[id(root(curve.start))].append(curve)
            meeting[id(root(curve.end))].append(curve)
    return root, meeting, ends


def loops(sketch) -> list[_Loop]:
    """The sketch's closed loops. Raises SketchError where a profile is open or branches, or a
    fillet does not fit its corner."""
    curves = _drawn(sketch)
    root, meeting, ends = _joints(sketch, curves)
    found = [_Loop([(curve, True)]) for curve in curves if _round(curve)]
    for key, joined in meeting.items():
        if len(joined) != 2:
            where = next(p for p in ends if id(root(p)) == key)
            if len(joined) == 1:
                raise SketchError(f"{sketch.name} is open at {where.name}: a closed profile joins two curves at every point.")
            raise SketchError(f"{sketch.name}: {len(joined)} curves meet at {where.name}; a profile joins two at every point.")
    unused = [curve for curve in curves if not _round(curve)]
    while unused:
        first = unused.pop(0)
        parts = [(first, True)]
        start, at = root(first.start), root(first.end)
        while at is not start:
            curve = next(c for c in meeting[id(at)] if c in unused)
            unused.remove(curve)
            forward = root(curve.start) is at
            parts.append((curve, forward))
            at = root(curve.end) if forward else root(curve.start)
        found.append(_Loop(parts))
    return found


def _edges(loop: _Loop, plane, clockwise: bool, unit: float = 1.0):
    """A loop's edges on the plane, in order, turning the way asked, in millimetres (``unit`` is
    the sketch's unit)."""
    import build123d as B

    if (loop.area < 0) != clockwise:
        parts = [(curve, not forward) for curve, forward in reversed(loop.parts)]
    else:
        parts = loop.parts
    at = lambda x, y: plane.from_local_coords((x * unit, y * unit))  # noqa: E731
    edges = []
    for curve, forward in parts:
        if isinstance(curve, Circle):
            edges.append(B.Edge.make_circle(curve.radius * unit, B.Plane(origin=at(curve.center.x, curve.center.y), x_dir=plane.x_dir,
                                                                         z_dir=plane.z_dir if not clockwise else -plane.z_dir)))
            continue
        if isinstance(curve, Spline):
            edges.append(_spline_edge(curve, forward, at))
            continue
        a, b = (curve.start, curve.end) if forward else (curve.end, curve.start)
        if isinstance(curve, Arc):
            a0, sweep = _arc_angles(curve)
            middle = a0 + sweep / 2
            mid = (curve.center.x + curve.radius * math.cos(middle), curve.center.y + curve.radius * math.sin(middle))
            edges.append(B.Edge.make_three_point_arc(at(a.x, a.y), at(*mid), at(b.x, b.y)))
        else:
            edges.append(B.Edge.make_line(at(a.x, a.y), at(b.x, b.y)))
    return edges


def _spline_edge(curve, forward: bool, at):
    """A spline's edge on the plane, through its points the way the chain runs."""
    edge = curve.edge(at)
    return edge if forward else edge.reversed()


def path(sketch):
    """The sketch's curves, construction aside, joined end to end into one chain on its plane, as
    a build123d Wire in millimetres: open, from one end to the other, or closed. What a sweep runs
    its profile along, or a rib thickens. Raises SketchError where they branch, or make more than
    one chain."""
    import build123d as B

    curves = _drawn(sketch)
    if not curves:
        raise SketchError(f"{sketch.name} has no curves to run along.")
    plane = plane_of(sketch)
    unit = sketch.unit
    at = lambda x, y: plane.from_local_coords((x * unit, y * unit))  # noqa: E731
    circles = [curve for curve in curves if _round(curve)]
    if circles:
        if len(curves) > 1:
            raise SketchError(f"{sketch.name}: a path is one chain of curves, and a circle is a chain of its own.")
        if isinstance(circles[0], Spline):
            return B.Wire([circles[0].edge(at)])
        circle = circles[0]
        return B.Wire([B.Edge.make_circle(circle.radius * unit, B.Plane(origin=at(circle.center.x, circle.center.y), x_dir=plane.x_dir,
                                                                       z_dir=plane.z_dir))])
    root, meeting, ends = _joints(sketch, curves)
    for key, joined in meeting.items():
        if len(joined) > 2:
            where = next(p for p in ends if id(root(p)) == key)
            raise SketchError(f"{sketch.name}: {len(joined)} curves meet at {where.name}; a path joins two at every point.")
    open_ends = [key for key, joined in meeting.items() if len(joined) == 1]
    if len(open_ends) not in (0, 2):
        raise SketchError(f"{sketch.name} is more than one chain of curves: a path is one, end to end.")
    # From one end (or anywhere round a closed one), each curve the way the chain runs.
    first = next(curve for curve in curves if not open_ends or open_ends[0] in (id(root(curve.start)), id(root(curve.end))))
    forward = not open_ends or id(root(first.start)) == open_ends[0]
    parts, used = [(first, forward)], {id(first)}
    place = root(first.end) if forward else root(first.start)
    while True:
        following = [curve for curve in meeting[id(place)] if id(curve) not in used]
        if not following:
            break
        curve = following[0]
        used.add(id(curve))
        forward = root(curve.start) is place
        parts.append((curve, forward))
        place = root(curve.end) if forward else root(curve.start)
    if len(used) != len(curves):
        raise SketchError(f"{sketch.name} is more than one chain of curves: a path is one, end to end.")
    edges = []
    for curve, forward in parts:
        a, b = (curve.start, curve.end) if forward else (curve.end, curve.start)
        if isinstance(curve, Spline):
            edges.append(_spline_edge(curve, forward, at))
        elif isinstance(curve, Arc):
            a0, sweep = _arc_angles(curve)
            middle = a0 + sweep / 2
            mid = (curve.center.x + curve.radius * math.cos(middle), curve.center.y + curve.radius * math.sin(middle))
            edges.append(B.Edge.make_three_point_arc(at(a.x, a.y), at(*mid), at(b.x, b.y)))
        else:
            edges.append(B.Edge.make_line(at(a.x, a.y), at(b.x, b.y)))
    made = B.Wire(edges)
    made._cadgen_sketch = sketch
    return made


def faces(sketch) -> list:
    """The sketch's regions as faces on its plane: each loop that is not a hole, with the loops
    directly inside it cut out."""
    import build123d as B

    found = loops(sketch)
    if not found:
        raise SketchError(f"{sketch.name} has no closed profile to make a face of.")
    plane = plane_of(sketch)
    depth = {id(loop): sum(other.contains(loop) for other in found if other is not loop) for loop in found}
    made = []
    for outer in (loop for loop in found if depth[id(loop)] % 2 == 0):
        holes = [loop for loop in found if depth[id(loop)] == depth[id(outer)] + 1 and outer.contains(loop)]
        face = B.Face(B.Wire(_edges(outer, plane, clockwise=False, unit=sketch.unit)),
                      [B.Wire(_edges(hole, plane, clockwise=True, unit=sketch.unit)) for hole in holes])
        if face.normal_at().dot(plane.z_dir) < 0:
            face = -face
        # Which sketch a face was made from, for edit mode's tree (Boss-Extrude1 > Sketch1).
        face._cadgen_sketch = sketch
        made.append(face)
    made = B.ShapeList(made)
    made._cadgen_sketch = sketch
    return made
