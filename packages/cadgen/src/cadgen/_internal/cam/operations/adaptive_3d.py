"""``adaptive_3d`` (3D adaptive clear, lite): rough the stock down round the part's 3D shape in z levels at a capped
tool engagement, cutting only where material stands.

Keys: ``bottom_z`` (the lowest level, WCS; default the part's bottom, or the region's ``bottom_z``),
``ramp_angle_deg`` (helix entries, default 3), ``direction`` (``climb``, the default, or ``conventional``); and the
shared ``stepdown_mm`` (default twice the material's, within the flutes: deep and light), ``stepover`` (default 0.15
of the diameter, at most 0.5), ``stock_to_leave_mm`` and ``region`` (``{"polygon": [[x, y], ...], "bottom_z": z}``:
the tool centre kept inside it).

The levels are ``rough``'s: even step-downs from the stock top, plus every upward-facing flat of the part plus the
stock to leave, so flats are left exactly that thick. At each level the tool centre keeps its radius plus the stock to
leave off everything of the part above the level (its silhouette, :class:`~cadgen._internal.cam.milling3d.Silhouettes`)
and may go out into the air round the stock. The shared engine (:mod:`cadgen._internal.cam.operations._adaptive`)
clears that against the stock as it stands before the operation: what an earlier operation or setup cut is air, a
level with nothing left is skipped, an open side is come into from the air beside the stock and a closed cavity by a
helix, and the cleared area grows one stepover at a time, so the radial engagement never exceeds the stepover.

On slopes the levels leave steps up to the step-down tall (deeper than ``rough``'s): finish with ``parallel`` or
``waterline``, or rest machining. A bull tool is kept off the part by its full radius at every level (safe, a little
more material left on slopes). ``meta["air_fraction"]`` is the share of the cutting path that removes nothing.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, PlanError, choice, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation, region_polygon

__all__ = ["Adaptive3dOp"]


class Adaptive3dOp(Operation):
    name = "adaptive_3d"
    plain = "3D adaptive clear"
    family = "3D milling"
    machines = MILLS
    status = "lite"
    limits = (
        "Engagement is capped by growing the cleared area one stepover at a time, not by a true medial-axis "
        "adaptive solver: the radial step never exceeds the stepover, but a pass wrapping round a small cleared area "
        "cuts more per millimetre (up to about twice the stepover's worth on the first ring round an entry).",
        "No trochoidal slotting: a piece too narrow for a helix entry is entered by a ramp along its outline, cut "
        "at full width there.",
        "Z levels only: steps on slopes are left as tall as the step-down, with no finer intermediate levels.",
    )
    keys = ("bottom_z", "ramp_angle_deg", "direction")
    tool_types = ("flat", "bull")
    takes_region = True
    feeds_kind = "rough"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        tool = ctx.job.tool(spec.tool)
        stepover = spec.stepover_mm if spec.stepover_mm is not None else (
            (spec.stepover if spec.stepover is not None else 0.15) * tool.diameter_mm)
        if stepover > 0.5 * tool.diameter_mm + 1e-9:
            raise CamJobError(f"{spec.where}: an adaptive clear's stepover is its engagement; keep it at most half the "
                              f"tool's diameter ({0.5 * tool.diameter_mm:g} mm), 0.1 to 0.2 is usual")
        extra = spec.extra
        params = {
            "bottom_z": read_number(extra, "bottom_z", spec.where, minimum=-1e6) if "bottom_z" in extra else None,
            "ramp_angle_deg": read_number(extra, "ramp_angle_deg", spec.where, default=3.0, maximum=45.0),
            "climb": choice(extra.get("direction", "climb"), ("climb", "conventional"), f"{spec.where}.direction")
            == "climb",
            "region": region_polygon(spec, where=spec.where) if spec.region is not None else None,
        }
        return params

    def plan(self, ctx, params):
        import shapely

        from cadgen._internal.cam import geom2d
        from cadgen._internal.cam.air import air_report
        from cadgen._internal.cam.feeds import default_stepdown
        from cadgen._internal.cam.milling3d import Silhouettes, StockNow
        from cadgen._internal.cam.operations._adaptive import Clearing
        from cadgen._internal.cam.operations.pocket import _levels

        tool = ctx.tool
        r = tool.radius
        tol = ctx.tolerance_mm
        heights = ctx.heights
        leave = ctx.spec.stock_to_leave_mm
        top = heights.stock_top
        user_region, region_bottom = params["region"] if params["region"] is not None else (None, None)
        bottom = params["bottom_z"] if params["bottom_z"] is not None else (
            region_bottom if region_bottom is not None else max(heights.part_bottom, heights.stock_bottom))
        if bottom >= top - 1e-6:
            raise PlanError("empty_operation", f"{ctx.spec.where}: the lowest level (Z {bottom:.3f}) is at or above "
                            f"the stock top in setup '{ctx.setup.id}', so there is nothing to clear")
        stepover = ctx.stepover(0.15)
        feeds = ctx.feeds(self.feeds_kind, stepover_mm=stepover)
        stepdown = ctx.spec.stepdown_mm if ctx.spec.stepdown_mm is not None else min(
            tool.flute_length_mm or math.inf, 2.0 * default_stepdown(ctx.material, tool))
        levels = _levels(ctx, top, bottom, stepdown, leave)
        stock = ctx.stock_outline
        # The stock as it stands, on a grid fine enough for the tool (a tenth of its radius, 0.1 to 0.5 mm).
        stock_now = StockNow(ctx, cell=min(0.5, max(0.1, r / 10.0)))
        # Out past the stock far enough that the tool's centre stands where its circle touches nothing.
        outer = stock.buffer(r + 1.0 + stock_now.cell)
        vertices, triangles = ctx.mesh
        silhouettes = Silhouettes(vertices, triangles, ctx.sections)
        clearing = Clearing(ctx, ctx.builder(), stepover=stepover, feeds=feeds, climb=params["climb"],
                            ramp_angle_deg=params["ramp_angle_deg"])
        previous_area = None
        z_prev = top
        cut_levels = 0
        for z in levels:
            material = silhouettes.above(z - leave)
            keep_off = geom2d.offset(material, r + leave, tolerance=tol, radius=r + leave) if not material.is_empty \
                else shapely.Polygon()
            area = outer.difference(keep_off)
            if user_region is not None:
                area = area.intersection(user_region)
            standing = stock_now.standing(z)
            if standing is None:
                standing = stock
            part_here = ctx.sections.at(z)
            if not part_here.is_empty:
                standing = standing.difference(geom2d.offset(part_here, leave + stock_now.cell, tolerance=tol))
            ctx.say(f"adaptive_3d level z {z:.3f}")
            if not area.is_empty and clearing.level(area, standing, z, z_prev, previous_area):
                cut_levels += 1
            previous_area = area
            z_prev = z
        b = clearing.b
        b.rapid(z=heights.clearance)
        state = clearing.state
        ctx.meta.update({"levels": cut_levels, "stock_to_leave": leave, "floor_z": round(bottom, 4),
                         "stepover_mm": round(stepover, 4), "stepdown_mm": round(stepdown, 4), **clearing.meta()})
        if state["entries"]["plunge"]:
            ctx.meta["plunges"] = state["entries"]["plunge"]
        if state["narrow"]:
            ctx.meta["note"] = (f"{state['narrow']} piece(s) too narrow for a helix entry were ramped in along their "
                                "outline at full width")
        if not cut_levels:
            ctx.meta["note"] = "nothing left to clear: the stock as it stands is already clear down to the lowest level"
        path = b.build()
        ctx.meta.update(air_report(ctx, path, stock_now=stock_now))
        return path
