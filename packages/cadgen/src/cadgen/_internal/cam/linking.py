"""How cuts are joined: heights, entries (helix, ramp, plunge), leads, tabs and ordering.

* :class:`Heights` of a setup, in WCS mm: ``clearance`` (rapids between features), ``retract`` (the feed-to plane
  just above the stock), ``stock_top`` and ``part_top``.
* :func:`helix` descends on a helix at a ramp angle (arcs in the IR, so posts write G2/G3 with Z) and closes with a
  flat circle; :func:`ramp` zig-zags down along a path's first segment; :func:`entry` picks the gentlest one that
  fits (helix, else ramp, else a plunge, which the plan reports).
* :func:`lead_arc` is a tangent quarter-arc lead in or out of a contour; :func:`apply_tabs` lifts a closed path over
  holding tabs; :func:`order_nearest` and :func:`inside_first` order features.
* :func:`retract_and_move` is the safe link: up to clearance, across, down to the retract plane.

Stdlib at import; numpy and shapely inside.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Heights", "apply_tabs", "entry", "helix", "inside_first", "lead_arc", "order_nearest", "ramp",
           "retract_and_move"]


@dataclass(frozen=True)
class Heights:
    clearance: float
    retract: float
    stock_top: float
    part_top: float
    stock_bottom: float = 0.0
    part_bottom: float = 0.0

    def as_dict(self) -> dict:
        return {key: round(getattr(self, key), 4) for key in ("clearance", "retract", "stock_top", "part_top",
                                                               "stock_bottom", "part_bottom")}


def retract_and_move(builder, x: float, y: float, heights: Heights, *, down_to: float | None = None) -> None:
    """Up to clearance, rapid over (x, y), down to the retract plane (or ``down_to``, when the space below the
    retract plane is known to be clear)."""
    if builder.pos[2] < heights.clearance - 1e-9:
        builder.rapid(z=heights.clearance)
    builder.rapid(x=x, y=y)
    builder.rapid(z=max(heights.retract, down_to) if down_to is not None else heights.retract)


def helix(builder, centre, radius: float, z_from: float, z_to: float, *, angle_deg: float, f: float,
          clockwise: bool = False) -> None:
    """From ``(centre + (radius, 0), z_from)`` (rapid there first), descend on a helix whose pitch keeps the ramp at
    ``angle_deg``, in half turns, then one flat circle at ``z_to``. Ends at ``centre + (radius, 0)``."""
    cx, cy = float(centre[0]), float(centre[1])
    builder.feed(x=cx + radius, y=cy, f=f)
    builder.feed(z=z_from, f=f)
    pitch = max(1e-3, 2 * math.pi * radius * math.tan(math.radians(angle_deg)))
    depth = z_from - z_to
    halves = max(1, int(math.ceil(depth / (pitch / 2.0))))
    drop = depth / halves
    z = z_from
    for half in range(halves):
        z -= drop
        side = -1.0 if half % 2 == 0 else 1.0
        builder.arc(cx + side * radius, cy, z, centre=(cx, cy, 0.0), clockwise=clockwise, f=f)
    if halves % 2 == 1:
        builder.arc(cx + radius, cy, z_to, centre=(cx, cy, 0.0), clockwise=clockwise, f=f)
    builder.arc(cx + radius, cy, z_to, centre=(cx, cy, 0.0), clockwise=clockwise, f=f)


def ramp(builder, path, z_from: float, z_to: float, *, angle_deg: float, f: float) -> bool:
    """Zig-zag down along ``path`` itself ((N, 2) or (N, 3), from its first point) from ``z_from`` to ``z_to`` at
    ``angle_deg``: out along it for a run that keeps the ramp at that angle, back, out, ... until ``z_to``, every leg
    following the path (never a chord across a corner, which would cut into the wall it turns), ending at the path's
    first point at ``z_to``. False (and nothing added) when the path is shorter than 0.5 mm."""
    import numpy as np
    import shapely
    from shapely.ops import substring

    points = np.asarray(path, dtype=float)[:, :2]
    if len(points) < 2:
        return False
    line = shapely.LineString(points)
    run = min(float(line.length), max(1.0, (z_from - z_to) / math.tan(math.radians(angle_deg))))
    if run < 0.5:
        return False
    leg = np.asarray(substring(line, 0.0, run).coords)[:, :2]
    distance = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(leg, axis=0).T))])
    per_leg = run * math.tan(math.radians(angle_deg))
    builder.feed(x=float(leg[0, 0]), y=float(leg[0, 1]), f=f)
    builder.feed(z=z_from, f=f)
    z = z_from
    outward = True
    while z > z_to + 1e-9:
        drop = min(per_leg, z - z_to)
        order = leg if outward else leg[::-1]
        along = distance if outward else distance[-1] - distance[::-1]
        heights = z - drop * along / max(along[-1], 1e-12)
        builder.polyline(np.column_stack([order[1:], heights[1:]]), f=f)
        z -= drop
        outward = not outward
    if not outward:
        builder.polyline(np.column_stack([leg[::-1][1:], np.full(len(leg) - 1, z_to)]), f=f)
    return True


def entry(builder, region, start, z_from: float, z_to: float, *, tool_radius: float, angle_deg: float, f: float,
          plunge_f: float, path=None, clockwise: bool = False) -> str:
    """Enter material at ``start`` (x, y) from ``z_from`` down to ``z_to``: a helix when one of at least 0.25 of the
    tool radius fits inside ``region`` (where the tool centre may go) about a point near ``start``, else a ramp along
    ``path``, else a straight plunge. Returns ``helix``, ``ramp`` or ``plunge``; the tool ends at ``start``
    (helix: on its circle, then fed to ``start``).

    The caller has put the tool at or above ``z_from`` over (or next to) ``start``, where the space between is
    clear: every entry's first moves are short horizontal feeds there, then a feed down to ``z_from``."""
    import shapely

    if z_from - z_to <= 1e-9:
        builder.feed(x=start[0], y=start[1], z=z_to, f=f)
        return "none"
    for share in (0.75, 0.5, 0.25):
        radius = share * tool_radius
        centre = shapely.Point(start[0] - radius, start[1])
        if region is not None and region.buffer(-radius * 1.01).contains(centre):
            helix(builder, (centre.x, centre.y), radius, z_from, z_to, angle_deg=angle_deg, f=f, clockwise=clockwise)
            builder.feed(x=start[0], y=start[1], z=z_to, f=f)
            return "helix"
    if path is not None and ramp(builder, path, z_from, z_to, angle_deg=angle_deg, f=f):
        return "ramp"
    builder.feed(x=start[0], y=start[1], f=f)
    builder.feed(z=z_from, f=f)
    builder.plunge(z=z_to, f=plunge_f)
    return "plunge"


def lead_arc(point, direction, *, radius: float, material_on_right: bool, entering: bool = True):
    """A tangent quarter-arc lead to (``entering``) or from ``point`` along unit ``direction`` of travel, swinging in
    from the side away from the material. Returns ``(start, centre, clockwise)``: feed an arc from ``start`` about
    ``centre`` to ``point`` (entering), or from ``point`` to ``start`` (leaving, the arc reversed)."""
    px, py = float(point[0]), float(point[1])
    dx, dy = float(direction[0]), float(direction[1])
    norm = math.hypot(dx, dy) or 1.0
    dx, dy = dx / norm, dy / norm
    # Away from the material: the left of travel when the material is on the right.
    ax, ay = (-dy, dx) if material_on_right else (dy, -dx)
    centre = (px + ax * radius, py + ay * radius)
    if entering:
        start = (centre[0] - dx * radius, centre[1] - dy * radius)
    else:
        start = (centre[0] + dx * radius, centre[1] + dy * radius)
    # From the away side the arc turns toward the material: counter-clockwise when that is on the right.
    return start, centre, not material_on_right


def apply_tabs(points, *, tab_top: float, count: int, width: float, tool_diameter: float):
    """A closed path ((N, 3), first == last, at its cutting depths) lifted to ``tab_top`` over ``count`` tabs
    evenly spaced along it, each leaving ``width`` of material (so lifted over ``width + tool_diameter`` of path).
    Points are inserted at each tab's ends; the lifts are vertical."""
    import numpy as np

    points = np.asarray(points, dtype=float)
    if count <= 0 or len(points) < 3:
        return points
    seg = np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1)
    total = float(seg.sum())
    span = width + tool_diameter
    if total <= count * span * 1.5:
        return points
    cumulative = np.concatenate([[0.0], np.cumsum(seg)])
    centres = (np.arange(count) + 0.5) * total / count
    cuts = sorted({float(c) for centre in centres for c in (centre - span / 2, centre + span / 2)})
    distances = np.unique(np.concatenate([cumulative, cuts]))
    xy = np.column_stack([np.interp(distances, cumulative, points[:, i]) for i in range(3)])
    inside = np.zeros(len(distances), dtype=bool)
    for centre in centres:
        inside |= (distances >= centre - span / 2 - 1e-9) & (distances <= centre + span / 2 + 1e-9)
    out = []
    last = len(xy) - 1
    for i, (point, lifted) in enumerate(zip(xy, inside)):
        low = [point[0], point[1], point[2]]
        if not lifted:
            out.append(low)
            continue
        high = [point[0], point[1], max(point[2], tab_top)]
        # A vertical step at each end of a tab: low then high going in, high then low coming out.
        if i > 0 and not inside[i - 1]:
            out.append(low)
        out.append(high)
        if i < last and not inside[i + 1]:
            out.append(low)
    return np.asarray(out)


def order_nearest(items, start, *, key):
    """``items`` in greedy nearest-neighbour order from ``start`` (x, y); ``key(item)`` gives an item's (x, y)."""
    remaining = list(items)
    out = []
    here = (float(start[0]), float(start[1]))
    while remaining:
        best = min(range(len(remaining)), key=lambda i: math.dist(here, key(remaining[i])[:2]))
        item = remaining.pop(best)
        out.append(item)
        here = tuple(key(item)[:2])
    return out


def inside_first(polygons) -> list:
    """Polygons ordered so one inside another comes before it (cut holes before the outline that holds them),
    deepest nesting first, stable otherwise."""
    depth = []
    for i, polygon in enumerate(polygons):
        nested = sum(1 for j, other in enumerate(polygons) if j != i and other.contains(polygon.representative_point()))
        depth.append(nested)
    return [polygon for _, _, polygon in sorted(((-d, i, p) for i, (d, p) in enumerate(zip(depth, polygons))),
                                                key=lambda row: (row[0], row[1]))]
