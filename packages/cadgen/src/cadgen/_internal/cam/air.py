"""How much of an operation's path cuts nothing: the share of its cutting moves (feeds, plunges, arcs) along which
the tool removes no material.

The material is the stock as it stood before the operation (:class:`~cadgen._internal.cam.milling3d.StockNow`, every
earlier operation replayed) and as the operation's own earlier moves leave it. It is held as a grid of the stock's top
in the setup's WCS, cells a twelfth of the tool's radius; the path is walked and the tool's lower surface
(:meth:`~cadgen._internal.cam.tools.Tool.height_at`) stamped on the grid each time it has gone a cell further (a
stretch of finely pointed path is one stamp, so a step too short to reach a new cell is not taken for air). A stretch
whose stamp lowers no cell by more than a hair (the tolerance, at least 0.01 mm) cut air. Where the setup is not simulated
(a tilted one), the stock is taken whole, at its top over its outline.

:func:`air_report` gives ``{"air_fraction", "air_mm", "cut_mm"}``: the clearing operations record it in their
``meta`` (it is the number adaptive clearing is built to keep low), and the tests read it.
"""

from __future__ import annotations

import math

__all__ = ["air_report"]

#: The finest grid the report builds: a path over a larger area takes coarser cells.
MAX_CELLS = 4_000_000
#: The most stamps it makes: a longer path is stamped further apart (the report is coarser, never slow).
MAX_STAMPS = 400_000


def air_report(ctx, toolpath, *, stock_now=None, detail: bool = False) -> dict:
    """``{"air_fraction", "air_mm", "cut_mm"}`` of ``toolpath`` (WCS, ``ctx.tool``'s): the cutting length that removed
    nothing over all the cutting length, both in mm. ``detail`` adds ``samples`` and ``air`` (a boolean per sample:
    the step that ends there cut nothing), for a test to see where."""
    import numpy as np
    import shapely

    from cadgen._internal.cam.ir import DWELL, RAPID
    from cadgen._internal.cam.milling3d import StockNow

    tool = ctx.tool
    r = tool.radius
    tol = max(0.01, ctx.tolerance_mm)
    samples = toolpath.sample(chord_mm=tol, max_step_mm=max(0.02, r / 12.0))
    points = samples.points
    cutting = (samples.kind != RAPID) & (samples.kind != DWELL) & (samples.move >= 0)
    empty = {"air_fraction": 0.0, "air_mm": 0.0, "cut_mm": 0.0}
    if not cutting.any():
        return dict(empty, samples=samples, air=np.zeros(len(points), dtype=bool)) if detail else empty
    lengths = np.zeros(len(points))
    lengths[1:] = np.linalg.norm(np.diff(points, axis=0), axis=1)
    low = points[cutting, :2].min(axis=0) - r
    high = points[cutting, :2].max(axis=0) + r
    cell = max(r / 12.0, math.sqrt(float(np.prod(high - low)) / MAX_CELLS), 1e-3)
    spacing = max(cell, float(lengths[cutting].sum()) / MAX_STAMPS)
    k = int(math.ceil(r / cell))
    nx = int(math.ceil((high[0] - low[0]) / cell)) + 2 * k + 1
    ny = int(math.ceil((high[1] - low[1]) / cell)) + 2 * k + 1
    x0, y0 = low[0] - k * cell, low[1] - k * cell
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    stock = stock_now if stock_now is not None else StockNow(ctx)
    # The simulator's cells reach up to a cell past the stock's edge: none stands outside its outline.
    inside = shapely.contains_xy(ctx.stock_outline, gx.ravel(), gy.ravel())
    tops = stock.surface_at(np.column_stack([gx.ravel(), gy.ravel()])) if stock.sim is not None else None
    if tops is None:
        tops = np.full(len(inside), ctx.heights.stock_top)
    tops = np.where(inside, tops, -np.inf).astype(float)
    # The part's own material is not the operation's to cut: a tool brushing a wall the grid rounds into it is not
    # cutting.
    part_face = stock.part_surface_at(np.column_stack([gx.ravel(), gy.ravel()])) if stock.sim is not None else None
    if part_face is None:
        part_face = np.full(len(tops), -np.inf)
    # The tool's footprint as flat offsets into the grid, each with the height of the tool's lower surface there.
    di, dj = np.meshgrid(np.arange(-k, k + 1), np.arange(-k, k + 1), indexing="ij")
    distance = np.hypot(di, dj) * cell
    inside = distance <= r
    offsets = (di[inside] * ny + dj[inside]).astype(np.int64)
    lift = np.asarray(tool.height_at(distance[inside]), dtype=float)
    air = cut = 0.0
    flags = np.zeros(len(points), dtype=bool)
    pending: list[int] = []     # the samples since the last stamp
    travelled = 0.0
    indices = np.nonzero(cutting)[0]
    for n, index in enumerate(indices):
        pending.append(int(index))
        travelled += lengths[index]
        last = n + 1 == len(indices) or indices[n + 1] != index + 1
        if travelled < spacing and not last:
            continue
        x, y, z = points[index]
        base = int((x - x0) // cell) * ny + int((y - y0) // cell)
        cells = base + offsets
        floor = z + lift
        standing = tops[cells]
        over = (standing > floor + tol) & (part_face[cells] <= floor + tol)
        if over.any():
            tops[cells[over]] = floor[over]
            cut += travelled
        else:
            air += travelled
            flags[pending] = True
        pending, travelled = [], 0.0
    total = air + cut
    out = dict(empty) if total <= 0.0 else {"air_fraction": round(float(air / total), 4),
                                            "air_mm": round(float(air), 1), "cut_mm": round(float(cut), 1)}
    if detail:
        out.update(samples=samples, air=flags)
    return out
