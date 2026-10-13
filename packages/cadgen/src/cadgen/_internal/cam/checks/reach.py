"""``reach``: the cut goes deeper than the tool's flutes (the shank rubs the walls) or its stickout (the holder hits).

The depth is the simulator's: the deepest the tool tip sat below material within reach of its side (the walls next
to the tool, not the stock top far away), per operation, so a stepped pocket is judged step by step. A setup the
simulator skipped falls back to the setup's stock top minus the operation's lowest cutting move (conservative).
A holder wider than the cut is judged by ``holder_collision``, not here.
"""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding, xyz

__all__ = ["run"]


def _fallback_depth(ctx, op) -> tuple[float, list | None]:
    import numpy as np

    from cadgen._internal.cam.ir import RAPID

    plan = ctx.setup_plan(op.setup)
    path = plan.toolpath
    rows = path.moves[(path.moves["op"] == op.index) & (path.moves["kind"] != RAPID)]
    if not len(rows):
        return 0.0, None
    k = int(np.argmin(rows["z"]))
    point = plan.wcs.from_wcs([[rows["x"][k], rows["y"][k], rows["z"][k]]])[0]
    return float(plan.heights.stock_top - rows["z"][k]), list(point)


def run(ctx) -> list[dict]:
    out = []
    tol = max(0.05, ctx.tolerance_mm)
    for op in ctx.ops:
        tool = op.tool
        if tool is None or tool.family != "mill":
            continue
        report = ctx.sim_reports.get(op.setup)
        entry = report.depth_by_op.get(op.index) if report is not None else None
        if entry is not None:
            depth, at = entry["depth_mm"], entry["at"]
        else:
            depth, at = _fallback_depth(ctx, op)
        if depth <= tool.flute_length_mm + tol:
            continue
        item = {"setup": op.setup, "operation": op.index, "depth_mm": round(depth, 3),
                "flute_length_mm": tool.flute_length_mm, "stickout_mm": tool.stickout_mm,
                "at": xyz(at) if at is not None else None}
        if depth > tool.stickout_mm + tol:
            out.append(finding(
                "reach", "error", "reach_holder",
                f"Tool too short for this cut: {op.summary or op.spec.op} goes {depth:.1f} mm deep but {tool.id} "
                f"({tool.plain}) sticks out only {tool.stickout_mm:g} mm, so the holder hits",
                "use a longer tool or more stickout (stickout_mm), or cut less deep from this side", [item]))
        else:
            out.append(finding(
                "reach", "error", "reach_flutes",
                f"Tool flutes too short for this cut: {op.summary or op.spec.op} goes {depth:.1f} mm deep but "
                f"{tool.id}'s flutes are {tool.flute_length_mm:g} mm long, so the shank rubs the walls",
                "use a tool with longer flutes (flute_length_mm), or machine the rest from the other side", [item]))
    return out
