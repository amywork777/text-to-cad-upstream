"""``pocket``: clear a pocket down to its floors by offsetting its outline inward, level by level.

Name the pocket by its floor faces (``faces``: flat faces facing the tool; naming the deepest floor of a stepped
pocket clears the steps above it too) or by a ``region`` (``{"polygon": [[x, y], ...], "bottom_z": z}``, WCS).

How it plans, at each level from the stock top down (step down, plus every upward-facing flat of the part in
between, so steps and floors are reached exactly):

* the region to clear is the empty space at that height (the stock's outline minus the part's section grown by the
  stock to leave) that holds a named floor; above the part's top it is the pocket's mouth, so the stock above the
  pocket is cleared and the rest of the top is left to ``face``;
* the tool centre stays inside that region shrunk by the tool's radius; rings offset inward by the stepover are cut
  from the innermost out, the last one along the walls, oriented for climb (``direction``: ``climb`` or
  ``conventional``); islands are walked round the same way;
* each region at each level is entered by a helix (``entry``: ``helix``, the default, ``ramp`` or ``plunge``) at
  ``ramp_angle_deg`` (default 3), falling back to a ramp along the first ring, then to a plunge (counted in the
  op's meta);
* moves between rings stay down when the straight link lies inside the region, else lift to the retract plane.

What the tool's radius cannot reach (inside corners, gaps narrower than the tool) is recorded per floor level in
``meta["unreachable"]`` for the ``corner_radius`` check.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, choice, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation, region_polygon

__all__ = ["PocketOp"]


class PocketOp(Operation):
    name = "pocket"
    plain = "Pocket"
    family = "2.5D milling"
    machines = MILLS
    status = "full"
    keys = ("entry", "ramp_angle_deg", "direction")
    tool_types = ("flat", "bull", "ball")
    takes_faces = True
    takes_region = True
    feeds_kind = "rough"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        if not spec.faces and spec.region is None:
            raise CamJobError(f"{spec.where}: a pocket needs its floor faces (\"faces\": [\"#o1.f12\"]) or a "
                              "\"region\" ({\"polygon\": [[x, y], ...], \"bottom_z\": z})")
        if spec.faces and spec.region is not None:
            raise CamJobError(f"{spec.where}: give a pocket faces or a region, not both")
        extra = spec.extra
        params = {
            "entry": choice(extra.get("entry", "helix"), ("helix", "ramp", "plunge"), f"{spec.where}.entry"),
            "ramp_angle_deg": read_number(extra, "ramp_angle_deg", spec.where, default=3.0, maximum=45.0),
            "climb": choice(extra.get("direction", "climb"), ("climb", "conventional"), f"{spec.where}.direction")
            == "climb",
            "region": None,
        }
        if spec.region is not None:
            params["region"] = region_polygon(spec, where=spec.where)
            if params["region"][1] is None:
                raise CamJobError(f"{spec.where}.region needs \"bottom_z\", the pocket's floor height in the setup's WCS")
        return params

    def plan(self, ctx, params):
        import numpy as np
        import shapely

        from cadgen._internal.cam import geom2d, linking

        tool = ctx.tool
        r = tool.radius
        tol = ctx.tolerance_mm
        heights = ctx.heights
        leave = ctx.spec.stock_to_leave_mm
        sections = ctx.sections
        stock = ctx.stock_outline
        if params["region"] is not None:
            polygon, bottom_z = params["region"]
            floors = [(bottom_z, polygon)]
        else:
            floors = [ctx.floor(ref) for ref in ctx.spec.faces]
        bottom = min(z for z, _ in floors) + leave
        top = heights.stock_top
        if bottom >= top - 1e-6:
            raise CamJobError(f"{ctx.spec.where}: the pocket's floor is at or above the stock top in setup "
                              f"'{ctx.setup.id}'; nothing to clear")
        stepover = ctx.stepover(0.4)
        feeds = ctx.feeds(self.feeds_kind, stepover_mm=stepover)
        stepdown = ctx.stepdown()
        levels = _levels(ctx, top, bottom, stepdown, leave)
        mouth_z = min(heights.part_top, top) - 1e-3
        seeds = [shapely.Polygon(p.exterior).buffer(-min(0.05, r / 4)) if not p.is_empty else p for _, p in floors]
        seeds = [s if not s.is_empty else p for s, (_, p) in zip(seeds, floors)]
        b = ctx.builder()
        entries = {"helix": 0, "ramp": 0, "plunge": 0, "none": 0}
        unreachable = []
        previous_area = None
        z_prev = top
        for z in levels:
            if params["region"] is not None:
                polygon, _ = params["region"]
                material = sections.at(min(z, mouth_z)) if z < heights.part_top else shapely.Polygon()
                region = polygon.difference(geom2d.offset(material, leave, tolerance=tol) if leave else material)
            else:
                material = sections.at(min(z, mouth_z))
                grown = geom2d.offset(material, leave, tolerance=tol) if leave > 0 else material
                empty = stock.difference(grown)
                region = shapely.union_all([piece for piece in geom2d.polygons_of(empty)
                                            if any(piece.intersects(seed) for seed in seeds)])
            area = geom2d.offset(region, -r, tolerance=tol, radius=r)
            # What the radius cannot reach, once per spot (the same corner at every level is one corner).
            reached = geom2d.offset(area, r, tolerance=tol)
            for piece in geom2d.polygons_of(region.difference(reached).buffer(-1e-4).buffer(1e-4)):
                if piece.area > 1e-3:
                    c = piece.representative_point()
                    same = next((u for u in unreachable if math.hypot(u["at"][0] - c.x, u["at"][1] - c.y) < 0.5), None)
                    if same is None:
                        unreachable.append({"area_mm2": float(piece.area), "at": [c.x, c.y, z], "z": z})
                    elif piece.area > same["area_mm2"]:
                        same.update(area_mm2=float(piece.area), at=[c.x, c.y, z], z=z)
            pieces = geom2d.polygons_of(area)
            ctx.say(f"pocket level z {z:.3f}: region {region.area:.1f} mm², {len(pieces)} piece(s)")
            pieces = linking.order_nearest(pieces, b.pos, key=lambda p: (p.centroid.x, p.centroid.y))
            for piece in pieces:
                rings = _rings_inside_out(piece, stepover, tol, params["climb"])
                if not rings:
                    continue
                first = rings[0]
                start = _nearest_vertex(first, b.pos)
                ring = _rotate_to(first, start)
                # Over the start: stay low when the way there is open at this level, else go round by the retract plane.
                cleared_above = previous_area is not None and previous_area.contains(shapely.Point(start))
                z_from = z_prev if cleared_above else top
                _travel(b, start, z_from, heights, previous_area, z_prev)
                kind = linking.entry(
                    b, piece if params["entry"] == "helix" else None, start, z_from, z,
                    tool_radius=r, angle_deg=params["ramp_angle_deg"], f=feeds.ramp_mm_min,
                    plunge_f=feeds.plunge_mm_min, path=ring if params["entry"] != "plunge" else None,
                    clockwise=not params["climb"])
                entries[kind] = entries.get(kind, 0) + 1
                for k, coords in enumerate(rings):
                    if k:
                        start = _nearest_vertex(coords, b.pos)
                        coords = _rotate_to(coords, start)
                        link = shapely.LineString([b.pos[:2], start])
                        if link.length > 1e-9 and not link.within(piece.buffer(1e-6)):
                            # Round an island or a narrows: up to the retract plane, over, and back down (to 1 mm
                            # over this level's material where the column above is cleared), then plunge.
                            b.rapid(z=heights.retract)
                            b.rapid(x=start[0], y=start[1])
                            if previous_area is not None and previous_area.contains(shapely.Point(start)):
                                b.rapid(z=z_prev + 1.0)
                            b.plunge(z=z, f=feeds.plunge_mm_min)
                        else:
                            b.feed(x=start[0], y=start[1], z=z, f=feeds.feed_mm_min)
                    points = np.column_stack([coords, np.full(len(coords), z)])
                    b.polyline(points[1:], f=feeds.feed_mm_min)
                b.rapid(z=min(heights.retract, z + 1.0))
            previous_area = area
            z_prev = z
        b.rapid(z=heights.clearance)
        ctx.meta.update({"levels": len(levels), "entries": {k: v for k, v in entries.items() if v},
                         "unreachable": unreachable, "stock_to_leave": leave, "floor_z": round(bottom, 4)})
        if entries.get("plunge"):
            ctx.meta["plunges"] = entries["plunge"]
        return b.build()


def _levels(ctx, top: float, bottom: float, stepdown: float, leave: float) -> list[float]:
    """Even step-downs from the top to the floor, plus every upward-facing flat of the part between them."""
    import numpy as np

    count = max(1, int(math.ceil((top - bottom) / stepdown - 1e-9)))
    levels = {round(top - (top - bottom) * (k + 1) / count, 6) for k in range(count)}
    for info in ctx.part.faces.values():
        if info.surface != "plane" or info.normal is None:
            continue
        normal = ctx.wcs.vectors_to_wcs([info.normal])[0]
        if normal[2] < 1.0 - 1e-6:
            continue
        z = float(ctx.wcs.to_wcs([info.center_mm])[0][2]) + leave
        if bottom - 1e-6 <= z < top - 1e-6:
            levels.add(round(z, 6))
    ordered = sorted(levels, reverse=True)
    # Merge levels closer than a hundredth of a millimetre.
    out = []
    for z in ordered:
        if not out or out[-1] - z > 0.01:
            out.append(z)
    if abs(out[-1] - bottom) > 1e-6:
        out.append(bottom)
    return [float(z) for z in np.asarray(out)]


def _rings_inside_out(piece, stepover: float, tolerance: float, climb: bool):
    """The rings that clear ``piece`` (where the tool centre may go): offsets by the stepover, innermost first,
    each as an (N, 2) closed array oriented for climb or conventional."""
    from cadgen._internal.cam import geom2d

    offsets = [piece]
    while True:
        inner = geom2d.offset(offsets[-1], -stepover, tolerance=tolerance)
        if inner.is_empty or inner.area < 1e-6:
            break
        offsets.append(inner)
        if len(offsets) > 2000:
            break
    rings = []
    for shape in reversed(offsets):
        rings.extend(geom2d.rings(shape, climb=climb))
    return rings


def _nearest_vertex(ring, position):
    import numpy as np

    ring = np.asarray(ring)
    k = int(np.argmin(np.hypot(ring[:-1, 0] - position[0], ring[:-1, 1] - position[1])))
    return (float(ring[k, 0]), float(ring[k, 1]))


def _rotate_to(ring, start):
    """A closed ring re-started at its vertex ``start``."""
    import numpy as np

    ring = np.asarray(ring)[:-1]
    k = int(np.argmin(np.hypot(ring[:, 0] - start[0], ring[:, 1] - start[1])))
    turned = np.vstack([ring[k:], ring[:k]])
    return np.vstack([turned, turned[:1]])


def _travel(b, start, z_from, heights, previous_area, z_prev) -> None:
    """To over ``start``: by the clearance plane, then down to the retract plane, then (when the column below is
    already cleared) down to 1 mm over the material."""
    if b.pos[2] < heights.retract - 1e-9:
        b.rapid(z=heights.retract)
    if (b.pos[0], b.pos[1]) != start:
        if b.pos[2] < heights.clearance - 1e-9:
            b.rapid(z=heights.clearance)
        b.rapid(x=start[0], y=start[1])
    b.rapid(z=heights.retract)
    if z_from + 1.0 < heights.retract:
        b.rapid(z=z_from + 1.0)
