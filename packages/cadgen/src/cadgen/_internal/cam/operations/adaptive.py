"""``adaptive`` (Adaptive clear, lite): clear a pocket or an open area at a capped tool engagement, level by level.

Name what to clear as a pocket does: its floor faces (``faces``; naming the deepest floor of a stepped pocket clears
the steps above it too) or a ``region`` (``{"polygon": [[x, y], ...], "bottom_z": z}``, WCS). The region at each
level is the empty space there (the stock's outline minus the part's section grown by the stock to leave) that
holds a named floor, so an open side clears out to the stock's edge.

How it clears each connected piece of a level (in tool-centre space: where the tool's centre may go, the piece
shrunk by the tool radius):

* it enters by a helix at the piece's most open point (the centre of its largest inscribed circle; radius up to
  ``0.75`` of the tool radius at ``ramp_angle_deg``, default 3), or, where the piece is too narrow for that, a ramp
  along the piece's outline (else a plunge, counted);
* it then grows the cleared area outward in steps of the stepover: each new boundary is the cleared area offset by
  the stepover and clipped to the piece, so no point of a new pass is more than one stepover from material already
  cut. That caps the radial engagement at the stepover everywhere, walls included, unlike offset rings, which load
  the tool fully in corners and where rings collapse. Only the stretches of each boundary that reach new material
  are cut (climb by default: ``direction``), joined by feeds through cleared space or a lift when the way is not
  clear.

Defaults: stepover 0.15 of the diameter (at most 0.5: ``stepover`` above that is refused), step down twice the
material's (deep and light, as adaptive clearing runs), within the flutes. What the radius cannot reach goes to the
``corner_radius`` check as in a pocket. Its limits are in :attr:`AdaptiveOp.limits`.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, choice, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation, region_polygon

__all__ = ["AdaptiveOp"]


class AdaptiveOp(Operation):
    name = "adaptive"
    plain = "Adaptive clear"
    family = "2.5D milling"
    machines = MILLS
    status = "lite"
    limits = (
        "Engagement is capped by growing the cleared area one stepover at a time, not by a true medial-axis "
        "adaptive solver: the radial step never exceeds the stepover, but a pass wrapping round a small cleared area "
        "cuts more per millimetre (up to about twice the stepover's worth on the first ring round an entry).",
        "No trochoidal slotting: a piece too narrow for a helix entry is entered by a ramp along its outline, cut "
        "at full width there.",
        "No rest material from an earlier operation is used: every level is cleared from its own entry.",
    )
    keys = ("direction", "ramp_angle_deg")
    tool_types = ("flat", "bull")
    takes_faces = True
    takes_region = True
    feeds_kind = "rough"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        if not spec.faces and spec.region is None:
            raise CamJobError(f"{spec.where}: an adaptive clear needs its floor faces (\"faces\": [\"#o1.f12\"]) or a "
                              "\"region\" ({\"polygon\": [[x, y], ...], \"bottom_z\": z})")
        if spec.faces and spec.region is not None:
            raise CamJobError(f"{spec.where}: give an adaptive clear faces or a region, not both")
        tool = ctx.job.tool(spec.tool)
        stepover = spec.stepover_mm if spec.stepover_mm is not None else (
            (spec.stepover if spec.stepover is not None else 0.15) * tool.diameter_mm)
        if stepover > 0.5 * tool.diameter_mm + 1e-9:
            raise CamJobError(f"{spec.where}: an adaptive clear's stepover is its engagement; keep it at most half the "
                              f"tool's diameter ({0.5 * tool.diameter_mm:g} mm), 0.1 to 0.2 is usual")
        extra = spec.extra
        params = {
            "climb": choice(extra.get("direction", "climb"), ("climb", "conventional"), f"{spec.where}.direction")
            == "climb",
            "ramp_angle_deg": read_number(extra, "ramp_angle_deg", spec.where, default=3.0, maximum=45.0),
            "region": None,
        }
        if spec.region is not None:
            params["region"] = region_polygon(spec, where=spec.where)
            if params["region"][1] is None:
                raise CamJobError(f"{spec.where}.region needs \"bottom_z\", the floor's height in the setup's WCS")
        return params

    def plan(self, ctx, params):
        import shapely

        from cadgen._internal.cam import geom2d, linking
        from cadgen._internal.cam.feeds import default_stepdown
        from cadgen._internal.cam.operations._milling2d import unreachable_in
        from cadgen._internal.cam.operations.pocket import _levels as pocket_levels

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
            raise CamJobError(f"{ctx.spec.where}: the floor is at or above the stock top in setup '{ctx.setup.id}'; "
                              "nothing to clear")
        stepover = ctx.stepover(0.15)
        feeds = ctx.feeds(self.feeds_kind, stepover_mm=stepover)
        stepdown = ctx.spec.stepdown_mm if ctx.spec.stepdown_mm is not None else min(
            tool.flute_length_mm or math.inf, 2.0 * default_stepdown(ctx.material, tool))
        levels = pocket_levels(ctx, top, bottom, stepdown, leave)
        mouth_z = min(heights.part_top, top) - 1e-3
        seeds = [shapely.Polygon(p.exterior).buffer(-min(0.05, r / 4)) if not p.is_empty else p for _, p in floors]
        seeds = [s if not s.is_empty else p for s, (_, p) in zip(seeds, floors)]
        b = ctx.builder()
        state = {"entries": {"helix": 0, "ramp": 0, "plunge": 0}, "passes": 0, "lifts": 0, "narrow": 0}
        unreachable: list[dict] = []
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
            unreachable_in(region, r, z, tol, unreachable)
            area = geom2d.offset(region, -r, tolerance=tol, radius=r)
            pieces = geom2d.polygons_of(area)
            ctx.say(f"adaptive level z {z:.3f}: region {region.area:.1f} mm², {len(pieces)} piece(s)")
            pieces = linking.order_nearest(pieces, b.pos, key=lambda p: (p.centroid.x, p.centroid.y))
            for piece in pieces:
                self._clear(ctx, params, b, piece, z, z_prev, previous_area, stepover, feeds, state)
                b.rapid(z=min(heights.retract, z + 1.0))
            previous_area = area
            z_prev = z
        b.rapid(z=heights.clearance)
        entries = {k: v for k, v in state["entries"].items() if v}
        ctx.meta.update({"levels": len(levels), "entries": entries, "passes": state["passes"],
                         "unreachable": unreachable, "stock_to_leave": leave, "floor_z": round(bottom, 4),
                         "stepover_mm": round(stepover, 4), "stepdown_mm": round(stepdown, 4)})
        if state["entries"]["plunge"]:
            ctx.meta["plunges"] = state["entries"]["plunge"]
        if state["narrow"]:
            ctx.meta["note"] = (f"{state['narrow']} piece(s) too narrow for a helix entry were ramped in along their "
                                "outline at full width")
        return b.build()

    def _clear(self, ctx, params, b, piece, z, z_prev, previous_area, stepover, feeds, state) -> None:
        """Clear one connected piece (tool-centre space) at level ``z``."""
        import numpy as np
        import shapely

        from cadgen._internal.cam import geom2d, linking
        from cadgen._internal.cam.operations._milling2d import ramp_along, rotate_to_nearest

        tool = ctx.tool
        r = tool.radius
        tol = ctx.tolerance_mm
        heights = ctx.heights
        climb = params["climb"]
        circle = shapely.maximum_inscribed_circle(piece, tolerance=max(tol, 0.01))
        coords = np.asarray(circle.coords)
        centre = coords[0]
        inscribed = float(np.hypot(*(coords[1] - coords[0]))) if len(coords) > 1 else 0.0
        helix_r = min(0.75 * r, 0.9 * inscribed)
        start = (float(centre[0]) + helix_r, float(centre[1]))
        cleared_above = previous_area is not None and previous_area.buffer(1e-6).contains(shapely.Point(start))
        z_from = z_prev if cleared_above else heights.stock_top
        if helix_r >= 0.1 * r:
            self._go(b, start, z_from, heights)
            linking.helix(b, (float(centre[0]), float(centre[1])), helix_r, z_from, z, angle_deg=params["ramp_angle_deg"],
                          f=feeds.ramp_mm_min, clockwise=not climb)
            state["entries"]["helix"] += 1
            cleared = shapely.Point(centre).buffer(helix_r, quad_segs=geom2d.quad_segs(max(helix_r, tol), tol))
            cleared = cleared.intersection(piece)
        else:
            state["narrow"] += 1
            ring = geom2d.rings(piece, climb=climb)[0]
            ring = rotate_to_nearest(ring, b.pos)
            first = (float(ring[0][0]), float(ring[0][1]))
            self._go(b, first, z_from, heights)
            if ramp_along(b, ring, z_from, z, angle_deg=params["ramp_angle_deg"], f=feeds.ramp_mm_min):
                state["entries"]["ramp"] += 1
            else:
                b.feed(z=z_from, f=feeds.ramp_mm_min)
                b.plunge(z=z, f=feeds.plunge_mm_min)
                state["entries"]["plunge"] += 1
            b.polyline(np.column_stack([ring[1:], np.full(len(ring) - 1, z)]), f=feeds.feed_mm_min)
            cleared = piece.intersection(shapely.LineString(ring).buffer(min(stepover, r) * 0.5))
        eps = max(3.0 * tol, 0.05 * stepover)
        for _ in range(20000):
            grown = geom2d.offset(cleared, stepover, tolerance=tol).intersection(piece)
            grown = shapely.union_all([p for p in geom2d.polygons_of(grown) if p.intersects(cleared)])
            grown = grown.simplify(tol * 0.5).intersection(piece)
            if grown.is_empty or grown.difference(cleared).area < 1e-3:
                break
            for ring in geom2d.rings(grown, climb=climb):
                self._cut_new(b, ring, cleared, grown, z, eps, stepover, feeds, heights, previous_area, z_prev, state)
            cleared = shapely.union_all([cleared, grown])

    @staticmethod
    def _go(b, start, z_from, heights) -> None:
        """Over ``start`` by the clearance plane, down to the retract plane, then to 1 mm over ``z_from``."""
        if b.pos[2] < heights.retract - 1e-9:
            b.rapid(z=heights.retract)
        if (abs(b.pos[0] - start[0]) > 1e-9) or (abs(b.pos[1] - start[1]) > 1e-9):
            if b.pos[2] < heights.clearance - 1e-9:
                b.rapid(z=heights.clearance)
            b.rapid(x=start[0], y=start[1])
        b.rapid(z=heights.retract)
        if z_from + 1.0 < heights.retract:
            b.rapid(z=z_from + 1.0)

    @staticmethod
    def _cut_new(b, ring, cleared, grown, z, eps, stepover, feeds, heights, previous_area, z_prev, state) -> None:
        """Cut the stretches of ``ring`` (a boundary of ``grown``) that lie off ``cleared``: new material."""
        import numpy as np
        import shapely

        from cadgen._internal.cam.operations._milling2d import link

        line = shapely.segmentize(shapely.LineString(ring), max(0.05, stepover / 2.0))
        points = np.asarray(line.coords)[:-1]
        if len(points) < 3:
            return
        distance = shapely.distance(shapely.points(points), cleared)
        new = distance > eps
        if not new.any():
            return
        n = len(points)
        runs = []
        if new.all():
            # A ring wholly in new material (the first round an entry): spiral out onto it from the cleared edge
            # over its first stretch, so the engagement grows from nothing, then go once round it at full width.
            k = int(np.argmin(np.hypot(points[:, 0] - b.pos[0], points[:, 1] - b.pos[1])))
            loop = np.vstack([points[k:], points[:k], points[k:k + 1]])
            along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(loop, axis=0).T))])
            stretch = min(along[-1] / 4.0, max(3.0 * stepover, along[-1] / 8.0))
            q = max(1, int(np.searchsorted(along, stretch)))
            edge = cleared.boundary
            spiral = []
            for i in range(q + 1):
                t = along[i] / along[q]
                on_edge = edge.interpolate(edge.project(shapely.Point(loop[i])))
                spiral.append((1.0 - t) * np.array([on_edge.x, on_edge.y]) + t * loop[i])
            runs.append(np.vstack([np.asarray(spiral), loop[q + 1:], loop[1:q + 1]]))
        else:
            # Circular runs of new points, each widened by one point at either end so it starts and ends on cleared.
            first = int(np.argmin(new))         # a cleared point to start the walk from
            order = np.roll(np.arange(n), -first)
            current: list[int] = []
            for index in order:
                if new[index]:
                    if not current:
                        current.append((index - 1) % n)
                    current.append(index)
                elif current:
                    current.append(index)
                    runs.append(points[current])
                    current = []
            if current:
                current.append(order[0])
                runs.append(points[current])
        safe = cleared.buffer(eps)
        band = grown.buffer(1e-6)
        for run in runs:
            target = (float(run[0][0]), float(run[0][1]))
            step = shapely.LineString([b.pos[:2], target])
            if abs(b.pos[2] - z) < 1e-9 and step.length <= 1.5 * stepover and step.within(band):
                # A step of at most a stepover into the new band (onto the first ring round an entry).
                b.feed(x=target[0], y=target[1], z=z, f=feeds.ramp_mm_min)
            elif link(b, target, z, clear=safe, heights=heights, f=feeds.feed_mm_min, above=previous_area,
                      z_above=z_prev) == "lift":
                state["lifts"] += 1
            b.polyline(np.column_stack([run[1:], np.full(len(run) - 1, z)]), f=feeds.feed_mm_min)
            state["passes"] += 1
