"""``rapid_into_stock``: a rapid move passes through material that was not cut yet (the simulator's finding)."""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding, xyz

__all__ = ["run"]


def run(ctx) -> list[dict]:
    out = []
    names = {op.index: op for op in ctx.ops}
    for setup_id, report in ctx.sim_reports.items():
        for hit in report.rapid_hits:
            op = names.get(hit["op"])
            what = op.summary if op is not None else f"operation {hit['op'] + 1}"
            out.append(finding(
                "rapid_into_stock", "error", "rapid_into_stock",
                f"A rapid crashes into the stock in {what}: it dips {hit['depth_mm']:.2f} mm into uncut material",
                "raise the clearance or retract height (clearance_mm, retract_mm), or reorder the operations so the "
                "material is cut first",
                [{"setup": setup_id, "operation": hit["op"], "move": hit["move"], "count": hit["count"],
                  "depth_mm": hit["depth_mm"], "at": xyz(hit["at"])}]))
    return out
