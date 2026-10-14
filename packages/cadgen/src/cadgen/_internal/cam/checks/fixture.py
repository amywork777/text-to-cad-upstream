"""``fixture``: a move takes the tool into a fixture keep-out (a vise jaw, a clamp, a tab of the table).

Each setup's fixtures are boxes in part coordinates. Every sampled position, rapids included, is tested with the
tool as a cylinder of its radius from the tip up its stickout, against each box: a point of the tool axis closer
to the box than the radius is a hit.
"""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding, xyz

__all__ = ["run"]


def run(ctx) -> list[dict]:
    import numpy as np

    out = []
    for plan in ctx.setups:
        boxes = plan.setup.fixtures
        if not boxes or plan.toolpath is None or not len(plan.toolpath):
            continue
        # Every millimetre, coarser on a path too long to hold that many samples (the 3D gouge check's budget).
        from cadgen._internal.cam.checks._gouge3d import MAX_POINTS

        step = max(1.0, float(plan.toolpath.lengths().sum()) / MAX_POINTS)
        samples = plan.toolpath.sample(max(ctx.tolerance_mm, 0.05), max_step_mm=step)
        axis = np.asarray(plan.wcs.tool_axis)
        tips = plan.wcs.from_wcs(samples.points)
        tools = {op.index: op.tool for op in ctx.ops if op.setup == plan.setup.id}
        for b, box in enumerate(boxes):
            low, high = np.asarray(box.min_mm), np.asarray(box.max_mm)
            hits: dict[int, tuple[float, int]] = {}
            for op_index, tool in tools.items():
                if tool is None:
                    continue
                mask = samples.op == op_index
                if not mask.any():
                    continue
                points = tips[mask]
                worst = np.full(len(points), np.inf)
                for h in np.linspace(0.0, max(tool.stickout_mm, tool.radius), 8):
                    probe = points + axis * h
                    gap = np.linalg.norm(np.maximum(0.0, np.maximum(low - probe, probe - high)), axis=1)
                    worst = np.minimum(worst, gap - tool.radius)
                k = int(np.argmin(worst))
                if worst[k] < -1e-6:
                    hits[op_index] = (float(-worst[k]), int(np.nonzero(mask)[0][k]))
            for op_index, (depth, row) in hits.items():
                name = box.name or f"fixture {b + 1}"
                out.append(finding(
                    "fixture", "error", "fixture",
                    f"The tool runs into {name} in setup {plan.setup.id} ({depth:.2f} mm in)",
                    "move the fixture, keep the operation away from it (a smaller region), or raise the clearance",
                    [{"setup": plan.setup.id, "operation": op_index, "fixture": name, "depth_mm": round(depth, 3),
                      "at": xyz(tips[row])}]))
    return out
