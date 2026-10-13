"""``material_left``: stock still standing above the part after every operation, beyond the stock to leave."""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding, xyz

__all__ = ["run"]

#: Less than this is the grid's own noise along walls.
MIN_VOLUME_MM3 = 1.0


def run(ctx) -> list[dict]:
    if ctx.sim is None:
        return []
    leave = max((op.spec.stock_to_leave_mm for op in ctx.ops), default=0.0)
    left = ctx.sim.material_left(ctx.part, stock_to_leave_mm=leave, tolerance_mm=ctx.tolerance_mm)
    if left is None or left.volume_mm3 < MIN_VOLUME_MM3:
        return []
    return [finding(
        "material_left", "warning", "material_left",
        f"Material left on the part: {left.volume_mm3:.0f} mm³ over {left.area_mm2:.0f} mm², up to {left.max_mm:.2f} mm "
        f"proud" + (f" (stock to leave {leave:g} mm)" if leave else ""),
        "add an operation (face, a smaller tool, rest machining) where it is, or accept it",
        [{"volume_mm3": round(left.volume_mm3, 2), "area_mm2": round(left.area_mm2, 2), "max_mm": round(left.max_mm, 3),
          "at": xyz(left.at) if left.at else None,
          "bounds_mm": [xyz(left.bounds_min), xyz(left.bounds_max)] if left.bounds_min else None}])]
