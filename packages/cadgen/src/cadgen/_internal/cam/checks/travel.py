"""``travel``: a setup's toolpath spans more than the machine's travel on an axis.

Where the work offset sits on the machine is the operator's; what the program can be sure of is its own span. The
span of every move (rapids included) on X, Y and Z is compared with ``machine.travel_mm`` (a lathe: X as diameter
and Z). No travel in the job, no check.
"""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding

__all__ = ["run"]


def run(ctx) -> list[dict]:
    travel = ctx.job.machine.travel_mm
    if not travel:
        return []
    out = []
    lathe = ctx.job.machine.kind == "lathe"
    for plan in ctx.setups:
        path = plan.toolpath
        if path is None or not len(path):
            continue
        samples = path.sample(max(ctx.tolerance_mm, 0.05))
        points = samples.points
        span = points.max(axis=0) - points.min(axis=0)
        axes = (("X", 2 * float(points[:, 0].max()), travel[0]), ("Z", float(span[2]), travel[1])) if lathe and len(travel) == 2 \
            else tuple(zip("XYZ", (float(v) for v in span), travel))
        for name, needed, available in axes:
            if needed > available + 1e-6:
                out.append(finding(
                    "travel", "error", "travel",
                    f"Setup {plan.setup.id} needs {needed:.1f} mm of {name} travel; the machine has {available:g} mm",
                    "split the job into more setups, use a bigger machine, or check travel_mm",
                    [{"setup": plan.setup.id, "axis": name, "needed_mm": round(needed, 3), "travel_mm": available}]))
    return out
