"""``face``: take the top of the stock down flat to the part's top (or a depth), in parallel passes.

Own keys: ``depth_mm`` (how far below the stock top to face; default: down to the part's top plus the stock to
leave), ``pattern`` (``zigzag``, the default, or ``one_way``: every pass the same direction, climb), ``angle_deg``
(the passes' direction in the WCS XY plane; 0 runs along X). A ``region`` (``{"polygon": [[x, y], ...]}``, WCS)
faces only there, the tool's centre kept inside it; otherwise the passes run past the stock's edges by the tool's
radius plus 2 mm, so every pass starts and ends in air. Step down defaults to the material's; stepover to 0.7 of
the diameter.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, choice, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation, region_polygon

__all__ = ["FaceOp"]


class FaceOp(Operation):
    name = "face"
    plain = "Face"
    family = "2.5D milling"
    machines = MILLS
    status = "full"
    keys = ("depth_mm", "pattern", "angle_deg")
    tool_types = ("flat", "bull")
    takes_region = True
    feeds_kind = "face"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        extra = spec.extra
        params = {
            "depth_mm": read_number(extra, "depth_mm", spec.where),
            "pattern": choice(extra.get("pattern", "zigzag"), ("zigzag", "one_way"), f"{spec.where}.pattern"),
            "angle_deg": read_number(extra, "angle_deg", spec.where, default=0.0, minimum=-360.0, maximum=360.0),
            "region": None,
        }
        if spec.region is not None:
            params["region"] = region_polygon(spec, where=spec.where)[0]
        return params

    def plan(self, ctx, params):
        import numpy as np
        import shapely
        from shapely import affinity

        tool = ctx.tool
        r = tool.radius
        heights = ctx.heights
        top = heights.stock_top
        leave = ctx.spec.stock_to_leave_mm
        bottom = top - params["depth_mm"] if params["depth_mm"] is not None else heights.part_top + leave
        b = ctx.builder()
        if top - bottom <= 1e-6:
            ctx.meta["note"] = "the stock top is already the part top: nothing to face"
            return b.build()
        if bottom < heights.part_top + leave - 1e-6 and params["depth_mm"] is not None:
            ctx.meta["note"] = "faces below the part's top"
        stepover = ctx.stepover(0.7)
        feeds = ctx.feeds(self.feeds_kind, stepover_mm=stepover)
        stepdown = ctx.stepdown()
        levels = _levels(top, bottom, stepdown)
        stock = ctx.stock_outline
        user = params["region"]
        centres = user if user is not None else stock.buffer(r + 2.0, join_style="mitre")
        angle = params["angle_deg"]
        origin = (0.0, 0.0)
        turned = affinity.rotate(centres, -angle, origin=origin)
        x0, y0, x1, y1 = turned.bounds
        if user is None:
            count = max(1, int(math.ceil((y1 - y0 - 2 * (r + 2.0)) / stepover)) + 1)
            first, last = y0 + r + 2.0, y1 - r - 2.0
        else:
            count = max(1, int(math.ceil((y1 - y0) / stepover)) + 1)
            first, last = y0, y1
        ys = [first] if count == 1 or last <= first else list(np.linspace(first, last, count))
        passes = []
        for k, y in enumerate(ys):
            line = shapely.LineString([(x0 - 1.0, y), (x1 + 1.0, y)]).intersection(turned)
            for piece in shapely.get_parts(line):
                if piece.geom_type != "LineString" or piece.length < 1e-6:
                    continue
                coords = np.asarray(piece.coords)
                if params["pattern"] == "zigzag" and k % 2 == 1:
                    coords = coords[::-1]
                elif params["pattern"] == "one_way" and coords[0, 0] > coords[-1, 0]:
                    coords = coords[::-1]
                passes.append(np.asarray(affinity.rotate(shapely.LineString(coords), angle, origin=origin).coords))
        clear = stock.buffer(r + 0.5)
        plunges = 0
        for z in levels:
            for k, coords in enumerate(passes):
                start = coords[0]
                outside = not clear.contains(shapely.Point(start))
                previous = b.pos
                joined = (params["pattern"] == "zigzag" and k > 0 and abs(previous[2] - z) < 1e-9
                          and not clear.contains(shapely.Point(previous[:2])) and outside)
                if joined:
                    # Zig-zag: step over to the next pass in the air beyond the stock's edge.
                    b.feed(x=start[0], y=start[1], f=feeds.feed_mm_min)
                else:
                    if b.pos[2] < heights.clearance - 1e-9:
                        b.rapid(z=heights.clearance)
                    b.rapid(x=start[0], y=start[1])
                    if outside:
                        b.rapid(z=z)
                    else:
                        b.rapid(z=heights.retract)
                        b.plunge(z=z, f=feeds.plunge_mm_min)
                        plunges += 1
                for point in coords[1:]:
                    b.feed(x=point[0], y=point[1], z=z, f=feeds.feed_mm_min)
        b.rapid(z=heights.clearance)
        ctx.meta.update({"levels": len(levels), "passes": len(passes), "bottom_z": round(bottom, 4),
                         "stock_to_leave": leave})
        if plunges:
            ctx.meta["plunges"] = plunges
        return b.build()


def _levels(top: float, bottom: float, stepdown: float) -> list[float]:
    """Cut levels from just below ``top`` down to exactly ``bottom``, evenly split, none deeper than ``stepdown``."""
    from cadgen._internal.cam.job_errors import level_count

    count = level_count(top, bottom, stepdown)
    return [top - (top - bottom) * (k + 1) / count for k in range(count)]
