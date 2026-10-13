"""``gouge`` (2.5D): a cutting move takes the tool into the part beyond tolerance.

For the 2.5D milling and drilling families this compares every cutting sample with the part's section just above
the tool tip: the tool's radius at that height (a flat end mill's full radius, a cone's radius there) must stay at
least ``radius - tolerance`` from the material, and the tip must not sit inside it. Samples are grouped by height
on a 0.05 mm grid (rounded up), so a few hundred sections cover a part. The 3D milling family gets the full check
against its drop-cutter (:mod:`._gouge3d`): every feed point on or over the drop-cutter height of the tool inset by the
tolerance.
"""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding, xyz

__all__ = ["run", "FAMILIES"]

#: "Cutting" judges a router's sheet cut (its end mill); beams and wires are not mill tools and are skipped.
FAMILIES = ("2.5D milling", "Cutting")
GRID = 0.05


def run(ctx) -> list[dict]:
    import numpy as np
    import shapely

    from cadgen._internal.cam.ir import RAPID

    out = []
    tol = max(0.02, 2.0 * getattr(ctx.part, "deflection_mm", 0.01), 2.0 * ctx.tolerance_mm)
    from cadgen._internal.cam.checks._gouge3d import gouges_3d

    out.extend(gouges_3d(ctx, tol))
    for op in ctx.ops:
        tool = op.tool
        if tool is None or tool.family != "mill" or op.operation.family not in FAMILIES or op.meta.get("no_gouge_check"):
            continue
        plan = ctx.setup_plan(op.setup)
        if plan.sections is None:
            continue
        if op.end <= op.start:
            continue
        piece = plan.toolpath.slice(op.start, op.end)
        samples = piece.sample(ctx.tolerance_mm, max_step_mm=max(0.25, tool.radius / 2.0))
        cutting = (samples.kind != RAPID)
        cutting[0] = False
        points = samples.points[cutting]
        if not len(points):
            continue
        top = plan.sections.top
        keys = np.ceil((points[:, 2] + 1e-3) / GRID) * GRID
        worst, at, count = 0.0, None, 0
        for key in np.unique(keys):
            if key > top:
                continue
            group = points[keys == key]
            material = plan.sections.at(float(key))
            if material.is_empty:
                continue
            # The cutter's radius at the section's height above each tip (a cone's is smaller near its tip).
            radii = np.full(len(group), tool.radius) if tool.type == "flat" else np.array(
                [tool.radius_at(float(h)) for h in key - group[:, 2]])
            distance = shapely.distance(shapely.points(group[:, :2]), material)
            depth = radii - distance
            bad = depth > tol
            if bad.any():
                count += int(bad.sum())
                k = int(np.argmax(depth))
                if depth[k] > worst:
                    worst, at = float(depth[k]), group[k]
        if count:
            point = plan.wcs.from_wcs([at])[0]
            out.append(finding(
                "gouge", "error", "gouge_2d",
                f"{op.summary} cuts into the part: up to {worst:.2f} mm too deep at {count} point"
                f"{'s' if count > 1 else ''}",
                "this is a planning fault or a face the operation should not reach: check the faces and the stock to "
                "leave, and report it if the job is right", [{"setup": op.setup, "operation": op.index,
                                                              "depth_mm": round(worst, 3), "count": count,
                                                              "at": xyz(point)}]))
    # Lathe operations: the tool's shape swept through the half-plane against the part's turned section.
    from cadgen._internal.cam.checks._turning import gouges

    out.extend(gouges(ctx))
    return out
