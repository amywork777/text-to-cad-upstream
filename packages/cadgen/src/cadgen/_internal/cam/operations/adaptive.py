"""``adaptive`` (Adaptive clear, lite): clear a pocket or an open area at a capped tool engagement, level by level,
cutting only where material stands.

Name what to clear as a pocket does: its floor faces (``faces``; naming the deepest floor of a stepped pocket clears
the steps above it too) or a ``region`` (``{"polygon": [[x, y], ...], "bottom_z": z}``, WCS). The region at each
level is the empty space there (the stock's outline minus the part's section grown by the stock to leave) that holds
a named floor, so an open side clears out to the stock's edge. It is cleared from the inside out: coming into an open
side from the air beside the stock would cut it from the outside in, a tool's radius of passes longer round every
open side.

Each level is cleared by the shared engine (:mod:`cadgen._internal.cam.operations._adaptive`) against the stock as
it stands before the operation (every earlier operation and setup replayed on the heightfield simulator): what an
earlier operation cut is air, a level with nothing left in the region is skipped, and the cleared area grows from the
air into the material one stepover at a time, so the radial engagement never exceeds the stepover and the passes stay
where there is material to cut. Where a level has no air (a closed pocket's first level in solid stock), it is entered
by a helix at its most open point, else a ramp along the outline. A setup the simulator does not cover (a tilted one)
is cleared against the whole stock.

Defaults: stepover 0.15 of the diameter (at most 0.5: ``stepover`` above that is refused), step down twice the
material's (deep and light, as adaptive clearing runs), within the flutes. What the radius cannot reach goes to the
``corner_radius`` check as in a pocket; what it cuts at full width (round a piece too narrow for a helix) goes to
``meta["full_slot_mm"]``. A level the tool does not fit in at all is refused (``tool_too_large``), as is one the part
fills (``too_deep``) and a floor at or above the stock top (``empty_operation``). ``meta["air_fraction"]`` is the
share of the cutting path that removes nothing (:mod:`cadgen._internal.cam.air`). Its limits are in
:attr:`AdaptiveOp.limits`.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, PlanError, choice, read_number
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
        "The stock as it stands is read on the simulator's grid (a third of the tool's radius, 0.2 to 1 mm), grown "
        "by a cell to be safe: the first pass beside what an earlier operation cut can run up to about a cell in air.",
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

        from cadgen._internal.cam import geom2d
        from cadgen._internal.cam.air import air_report
        from cadgen._internal.cam.feeds import default_stepdown
        from cadgen._internal.cam.milling3d import StockNow
        from cadgen._internal.cam.operations._adaptive import Clearing
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
            raise PlanError("empty_operation", f"{ctx.spec.where}: the floor (Z {bottom:.3f}) is at or above the stock "
                            f"top in setup '{ctx.setup.id}', so there is nothing to clear")
        stepover = ctx.stepover(0.15)
        feeds = ctx.feeds(self.feeds_kind, stepover_mm=stepover)
        stepdown = ctx.spec.stepdown_mm if ctx.spec.stepdown_mm is not None else min(
            tool.flute_length_mm or math.inf, 2.0 * default_stepdown(ctx.material, tool))
        levels = pocket_levels(ctx, top, bottom, stepdown, leave)
        mouth_z = min(heights.part_top, top) - 1e-3
        seeds = [shapely.Polygon(p.exterior).buffer(-min(0.05, r / 4)) if not p.is_empty else p for _, p in floors]
        seeds = [s if not s.is_empty else p for s, (_, p) in zip(seeds, floors)]
        # The stock as it stands, on a grid fine enough for the tool (a tenth of its radius, 0.1 to 0.5 mm).
        stock_now = StockNow(ctx, cell=min(0.5, max(0.1, r / 10.0)))
        clearing = Clearing(ctx, ctx.builder(), stepover=stepover, feeds=feeds, climb=params["climb"],
                            ramp_angle_deg=params["ramp_angle_deg"])
        unreachable: list[dict] = []
        previous_area = None
        z_prev = top
        cut_levels = 0
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
            if region.is_empty or region.area < 1e-6:
                raise PlanError("too_deep", f"{ctx.spec.where}: the part fills the area to clear at Z {z:.3f} in setup "
                                f"'{ctx.setup.id}'; clearing it would cut into the part")
            unreachable_in(region, r, z, tol, unreachable)
            area = geom2d.offset(region, -r, tolerance=tol, radius=r)
            if area.is_empty or area.area < 1e-9:
                raise PlanError("tool_too_large", f"{ctx.spec.where}: {tool.id} ({tool.plain}) does not fit in the "
                                f"area to clear at Z {z:.3f} (narrower than the tool there), so it cannot clear it "
                                f"down to its floor at Z {bottom:.3f}; use a smaller tool")
            standing = stock_now.standing(z)
            if standing is None:
                standing = stock
            # The part itself, and the stock to leave on it, are not this level's to cut.
            part_here = sections.at(min(z, mouth_z))
            if not part_here.is_empty:
                standing = standing.difference(geom2d.offset(part_here, leave + stock_now.cell, tolerance=tol))
            ctx.say(f"adaptive level z {z:.3f}: region {region.area:.1f} mm²")
            if clearing.level(area, standing, z, z_prev, previous_area):
                cut_levels += 1
            previous_area = area
            z_prev = z
        b = clearing.b
        b.rapid(z=heights.clearance)
        state = clearing.state
        ctx.meta.update({"levels": cut_levels, "unreachable": unreachable, "stock_to_leave": leave,
                         "floor_z": round(bottom, 4), "stepover_mm": round(stepover, 4),
                         "stepdown_mm": round(stepdown, 4), **clearing.meta()})
        if state["entries"]["plunge"]:
            ctx.meta["plunges"] = state["entries"]["plunge"]
        if state["narrow"]:
            ctx.meta["note"] = (f"{state['narrow']} piece(s) too narrow for a helix entry were ramped in along their "
                                "outline at full width")
        if not cut_levels:
            ctx.meta["note"] = "nothing left to clear: the stock as it stands is already clear down to the floor"
        path = b.build()
        ctx.meta.update(air_report(ctx, path, stock_now=stock_now))
        return path
