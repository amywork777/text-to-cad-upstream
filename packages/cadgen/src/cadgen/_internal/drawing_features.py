"""What a drawing reads off a part's faces: its holes and its turned axes.

An engineering drawing states a hole as one callout -- ``4× ⌀6.6 THRU ⌴ ⌀11 ↧6.5``
-- and every number in it is a fact of the geometry: the diameter of the bore,
whether it runs through, how deep it goes, the counterbore or countersink at its
mouth, and how many identical holes the part has. Typing those numbers into the
drawing script lets them drift from the model, so this module reads them off the
B-rep instead, and :mod:`cadgen.eng_drawing` checks anything the author does type
against them.

A hole is a chain of concave, full-circle cylinders and cones on one axis line,
end to end, whose inside is air. Two pieces of one drilled hole separated by air
-- a pin hole through both arms of a clevis, a bore broken through by a cross hole
or a slot -- are one hole. Which end is its mouth comes from the solid itself: a
point on the axis just past an end is either air (an open end) or material (the
floor of a blind hole). A boss or a shaft is a convex cylinder and is never a
hole; a slot's rounded end is half a cylinder, and an O-ring groove or a pocket
around a standoff has material inside it, so neither is one either.

The same cylinders give a drawing its centre lines: a turned feature seen from
the side is drawn with its axis as a chain line, and :func:`axes` returns those
axes with the length of the part they span.

Nothing here imports the kernel at module scope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Hole", "Axis", "holes", "axes", "turned_diameters"]

#: Model millimetres two positions on an axis may differ by and still touch. A
#: counterbore's floor and the bore below it meet at one plane, so their ranges
#: share an end; tessellation-free B-rep values agree far closer than this.
_TOUCH = 1e-4
#: How far past an end of a hole the solid is sampled to decide whether it is open.
_PROBE = 0.05


@dataclass(frozen=True)
class Hole:
    """One hole, as a callout states it.

    ``mouth`` is the point on the axis where the hole opens (for a through hole,
    the end with the counterbore or countersink, else the end at the larger
    coordinate along ``axis``); ``axis`` is the unit direction from the mouth into
    the material. Sizes are model millimetres; ``depth`` is measured from the
    mouth to the end of the full-diameter bore, so a drill point below it is not
    counted, and is None for a through hole.
    """

    mouth: tuple[float, float, float]
    axis: tuple[float, float, float]
    diameter: float
    thru: bool
    depth: float | None = None
    cbore: tuple[float, float] | None = None
    csk: tuple[float, float] | None = None
    #: A through hole's counterbore or countersink at its far end, as (diameter,
    #: depth) and (diameter, angle): a bore chamfered at both ends has both.
    far_cbore: tuple[float, float] | None = None
    far_csk: tuple[float, float] | None = None
    #: From the mouth to the far end of the hole, along ``axis``.
    length: float = 0.0

    def signature(self) -> tuple:
        """What makes two holes "the same hole" for a ``4×`` count."""
        r = lambda v: None if v is None else round(v, 3)
        pair = lambda p: None if p is None else (round(p[0], 3), round(p[1], 3))
        return (r(self.diameter), self.thru, r(self.depth), pair(self.cbore), pair(self.csk),
                pair(self.far_cbore), pair(self.far_csk))


@dataclass(frozen=True)
class Axis:
    """A turned feature's axis: the line, and the stretch of it the part occupies."""

    start: tuple[float, float, float]
    end: tuple[float, float, float]
    #: The largest radius turned about it, for sizing a centre mark.
    radius: float = 0.0


@dataclass
class _Segment:
    kind: str  # "cyl" or "cone"
    lo: float  # axial range along the line's canonical direction
    hi: float
    r_lo: float  # radius at each end (equal for a cylinder)
    r_hi: float
    concave: bool
    span: float  # angular extent in radians; full is 2*pi


def _canonical(direction, point) -> tuple[tuple, tuple]:
    """A line's direction with a fixed sign, and its point nearest the origin."""
    d = list(direction)
    for c in d:
        if abs(c) > 1e-9:
            if c < 0:
                d = [-v for v in d]
            break
    n = math.sqrt(sum(c * c for c in d))
    d = [c / n for c in d]
    t = sum(p * c for p, c in zip(point, d))
    foot = [p - t * c for p, c in zip(point, d)]
    return tuple(d), tuple(foot)


def _line_key(d, foot) -> tuple:
    return tuple(round(c, 4) for c in d) + tuple(round(c, 3) for c in foot)


def _surface_segments(shape) -> dict[tuple, tuple[tuple, tuple, list[_Segment]]]:
    """Every cylindrical and conical face, grouped by the axis line it turns about."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder

    lines: dict[tuple, tuple[tuple, tuple, list[_Segment]]] = {}
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        kind = surface.GetType()
        if kind == GeomAbs_Cylinder:
            gp = surface.Cylinder()
        elif kind == GeomAbs_Cone:
            gp = surface.Cone()
        else:
            continue
        ax = gp.Axis()
        loc, direction = ax.Location(), ax.Direction()
        d, foot = _canonical((direction.X(), direction.Y(), direction.Z()), (loc.X(), loc.Y(), loc.Z()))
        # The axial range and the radius at each end, from points on the face's own
        # edges: a circle sits at one axial position, so its ends are exact.
        samples = []
        for edge in face.edges():
            for t in (0.0, 0.5, 1.0):
                p = edge.position_at(t)
                rel = (p.X - foot[0], p.Y - foot[1], p.Z - foot[2])
                along = sum(a * b for a, b in zip(rel, d))
                radial = math.sqrt(max(0.0, sum(c * c for c in rel) - along * along))
                samples.append((along, radial))
        if not samples:
            continue
        lo = min(a for a, _ in samples)
        hi = max(a for a, _ in samples)
        if hi - lo < _TOUCH:
            continue
        if kind == GeomAbs_Cylinder:
            r_lo = r_hi = gp.Radius()
        else:
            r_lo = max((r for a, r in samples if abs(a - lo) < 1e-6), default=0.0)
            r_hi = max((r for a, r in samples if abs(a - hi) < 1e-6), default=0.0)
        # Concave when the face's outward normal (out of the material) points back
        # toward the axis: material outside, air inside -- a bore, not a boss.
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
        point = face.position_at(0.5, 0.5)
        normal = face.normal_at(point)
        rel = (point.X - foot[0], point.Y - foot[1], point.Z - foot[2])
        along = sum(a * b for a, b in zip(rel, d))
        radial = tuple(c - along * k for c, k in zip(rel, d))
        concave = sum(a * b for a, b in zip(radial, (normal.X, normal.Y, normal.Z))) < 0
        segment = _Segment("cyl" if kind == GeomAbs_Cylinder else "cone", lo, hi, r_lo, r_hi, concave, u1 - u0)
        lines.setdefault(_line_key(d, foot), (d, foot, []))[2].append(segment)
    return lines


def _merge_split_faces(segments: list[_Segment]) -> list[_Segment]:
    """One segment per surface: a STEP from some kernels splits a full cylinder into
    two half faces, and two halves of one bore are one bore."""
    merged: list[_Segment] = []
    for seg in sorted(segments, key=lambda s: (s.kind, s.lo, s.hi, s.r_lo, s.r_hi, s.concave)):
        for other in merged:
            if (other.kind == seg.kind and other.concave == seg.concave
                    and abs(other.lo - seg.lo) < _TOUCH and abs(other.hi - seg.hi) < _TOUCH
                    and abs(other.r_lo - seg.r_lo) < _TOUCH and abs(other.r_hi - seg.r_hi) < _TOUCH):
                other.span += seg.span
                break
        else:
            merged.append(_Segment(seg.kind, seg.lo, seg.hi, seg.r_lo, seg.r_hi, seg.concave, seg.span))
    return merged


def _full(seg: _Segment) -> bool:
    return seg.span >= 2 * math.pi - 1e-6


def _chains(segments: list[_Segment]) -> list[list[_Segment]]:
    """Runs of segments that touch end to end along the axis."""
    chains: list[list[_Segment]] = []
    for seg in sorted(segments, key=lambda s: (s.lo, s.hi)):
        if chains and abs(chains[-1][-1].hi - seg.lo) < _TOUCH:
            chains[-1].append(seg)
        else:
            chains.append([seg])
    return chains


def _perpendicular(d) -> tuple[tuple, tuple]:
    """Two unit vectors square to ``d`` and to each other."""
    seed = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (d[1] * seed[2] - d[2] * seed[1], d[2] * seed[0] - d[0] * seed[2], d[0] * seed[1] - d[1] * seed[0])
    n = math.sqrt(sum(c * c for c in u))
    u = tuple(c / n for c in u)
    v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
    return u, v


def holes(shape) -> list[Hole]:
    """Every hole in ``shape``, read off its faces, in a deterministic order."""
    from build123d import Vector

    found: list[Hole] = []
    for d, foot, segments in _surface_segments(shape).values():
        u, v = _perpendicular(d)

        def at(a: float, x: float = 0.0, y: float = 0.0):
            return Vector(*(f + a * c + x * cu + y * cv for f, c, cu, cv in zip(foot, d, u, v)))

        def air(a: float, radius: float) -> bool:
            """Is the disc of ``radius`` square to the axis at ``a`` all air? A bore
            is; an O-ring groove or a pocket around a standoff has material inside."""
            samples = [(0.0, 0.0)] + [(radius * f * math.cos(t), radius * f * math.sin(t))
                                      for f in (0.45, 0.85) for t in (0.3, 2.4, 4.5)]
            return not any(shape.is_inside(at(a, x, y)) for x, y in samples)

        bores = [s for s in _merge_split_faces(segments) if s.concave and _full(s)]
        chains = []
        for chain in _chains(bores):
            # Two pieces of one bore with air between them -- a clevis's two arms,
            # a bore broken through by a cross hole or a slot -- are one hole.
            if (chains and abs(chains[-1][-1].r_hi - chain[0].r_lo) < _TOUCH
                    and all(not shape.is_inside(at(chains[-1][-1].hi + (chain[0].lo - chains[-1][-1].hi) * f))
                            for f in (0.1, 0.5, 0.9))):
                chains[-1] = chains[-1] + chain
            else:
                chains.append(chain)
        for chain in chains:
            cylinders = [s for s in chain if s.kind == "cyl"]
            if not cylinders:
                continue  # a conical recess with no bore is not a drilled hole
            longest = max(cylinders, key=lambda s: s.hi - s.lo)
            if not air((longest.lo + longest.hi) / 2, longest.r_lo):
                continue
            lo, hi = chain[0].lo, chain[-1].hi
            open_lo = not shape.is_inside(at(lo - _PROBE))
            open_hi = not shape.is_inside(at(hi + _PROBE))
            if not (open_lo or open_hi):
                continue  # a sealed void, not something a drill makes
            thru = open_lo and open_hi
            narrowest = min(s.r_lo for s in cylinders)
            # The mouth: a blind hole's open end; a through hole's counterbored or
            # countersunk end, else its end at the larger coordinate.
            if thru:
                lo_wide = chain[0].r_lo > narrowest + _TOUCH
                hi_wide = chain[-1].r_hi > narrowest + _TOUCH
                from_hi = hi_wide or not lo_wide
            else:
                from_hi = open_hi
            ordered = list(reversed(chain)) if from_hi else list(chain)
            mouth_at = hi if from_hi else lo
            axis = tuple(-c for c in d) if from_hi else d

            def from_mouth(position: float) -> float:
                return abs(position - mouth_at)

            def widening(seg: _Segment, *, at_mouth: bool) -> tuple | None:
                """The counterbore or countersink a chain's end segment makes, if any."""
                outer_at_hi = from_hi if at_mouth else not from_hi
                outer = seg.r_hi if outer_at_hi else seg.r_lo
                if outer <= narrowest + _TOUCH:
                    return None
                if seg.kind == "cone":
                    inner = seg.r_lo if outer_at_hi else seg.r_hi
                    spread = math.degrees(2 * math.atan2(outer - inner, seg.hi - seg.lo))
                    return ("csk", (2 * outer, round(spread, 1)))
                return ("cbore", (2 * outer, seg.hi - seg.lo))

            mouth_end = widening(ordered[0], at_mouth=True)
            far_end = widening(ordered[-1], at_mouth=False) if thru and len(ordered) > 1 else None
            depth = None
            if not thru:
                # From the mouth to the bottom of the deepest full-diameter stretch: a
                # groove partway down does not end the hole, a drill point does not
                # count.
                deepest = [s for s in ordered if s.kind == "cyl" and abs(s.r_lo - narrowest) < _TOUCH][-1]
                depth = max(from_mouth(deepest.lo), from_mouth(deepest.hi))
            mouth = tuple(f + mouth_at * c for f, c in zip(foot, d))
            found.append(Hole(
                mouth=_tidy(mouth), axis=_tidy(axis), diameter=2 * narrowest, thru=thru, depth=depth,
                cbore=mouth_end[1] if mouth_end and mouth_end[0] == "cbore" else None,
                csk=mouth_end[1] if mouth_end and mouth_end[0] == "csk" else None,
                far_cbore=far_end[1] if far_end and far_end[0] == "cbore" else None,
                far_csk=far_end[1] if far_end and far_end[0] == "csk" else None,
                length=hi - lo,
            ))
    found.sort(key=lambda h: (h.signature(), h.axis, h.mouth))
    return found


def axes(shape) -> list[Axis]:
    """The axis of every turned feature -- a full cylinder or cone, bore or boss --
    spanning the stretch of the line the part's turned faces occupy. Features
    that share a line and touch or overlap (a stepped shaft, a counterbored hole)
    are one axis."""
    found: list[Axis] = []
    for d, foot, segments in _surface_segments(shape).values():
        full = [s for s in _merge_split_faces(segments) if _full(s)]
        if not any(s.kind == "cyl" for s in full):
            continue  # a chamfer alone does not make a turned feature
        spans: list[list[float]] = []
        for seg in sorted(full, key=lambda s: s.lo):
            if spans and seg.lo <= spans[-1][1] + _TOUCH:
                spans[-1][1] = max(spans[-1][1], seg.hi)
                spans[-1][2] = max(spans[-1][2], seg.r_lo, seg.r_hi)
            else:
                spans.append([seg.lo, seg.hi, max(seg.r_lo, seg.r_hi)])
        for lo, hi, radius in spans:
            found.append(Axis(start=_tidy(tuple(f + lo * c for f, c in zip(foot, d))),
                              end=_tidy(tuple(f + hi * c for f, c in zip(foot, d))), radius=round(radius, 9)))
    found.sort(key=lambda a: (a.start, a.end))
    return found


def turned_diameters(shape) -> list[float]:
    """The diameters of the part's turned outside surfaces -- a shaft's steps, a
    boss -- which a drawing must state as surely as it states a hole."""
    found: set[float] = set()
    for _d, _foot, segments in _surface_segments(shape).values():
        for seg in _merge_split_faces(segments):
            if seg.kind == "cyl" and not seg.concave and _full(seg):
                found.add(round(2 * seg.r_lo, 6))
    return sorted(found)


def _tidy(values) -> tuple[float, ...]:
    """Round away the last bits of float noise so equal geometry compares equal."""
    return tuple(0.0 if abs(v) < 1e-9 else round(v, 9) for v in values)
