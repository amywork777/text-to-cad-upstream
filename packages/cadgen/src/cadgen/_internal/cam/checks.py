"""The checks: what cadgen stands behind in a plan, before and after FreeCAD plans it.

FreeCAD plans what it is asked to and checks nothing against the part: asked to pocket a floor that lies under an
overhang, it cuts through the overhang. So every plan is checked here, and a plan with an error posts no G-code:

* before FreeCAD runs, :func:`reach`: every face an operation names can be seen from the setup's side (rays from the
  face straight up the tool's axis leave the part), every hole it drills opens toward the tool, and no cut goes
  deeper below the stock top than the tool's flutes;
* after, :func:`check_moves` on each setup's moves (:mod:`toolpath`, setup coordinates, the tool down -Z):
  ``gouge``, a move whose tool (its real profile: flat, ball, bull nose or drill point) comes into the part, tested
  against the part's height seen from above on a grid finer than the tool; ``rapid_into_stock``, a rapid into stock no
  move before it has cut (the stock lowered along each cutting move, in program order); ``empty_operation``, an operation FreeCAD planned no cut for; ``travel``, a setup whose
  moves span more than the machine travels.

The height grid sees the part from above, so it is exact for a part machined from one side and conservative for an
undercut (a tool under an overhang is a hit). A finding is the KiCad/FEA shape (``check``, ``severity``, ``type``,
``summary``, ``description``, ``items``). Stdlib at import; numpy inside.
"""

from __future__ import annotations

import math

__all__ = ["CHECKS", "by_severity", "check_moves", "finding", "reach"]

#: Each check and the finding types it raises.
CHECKS = {
    "job": ("job", "freecad", "internal_error"),
    "reach": ("unreachable", "too_deep", "not_facing", "drill_size"),
    "gouge": ("gouge",),
    "rapid_into_stock": ("rapid_into_stock",),
    "empty_operation": ("empty_operation",),
    "travel": ("travel",),
    "limits": ("clamped",),
}
_SEVERITY = {"error": 0, "warning": 1, "info": 2}
#: How far a move may come into the part before it is a gouge (mm): the tessellation's and the grid's own error.
GOUGE_TOLERANCE_MM = 0.02
#: How far a rapid may be below the stock top before it is a hit (mm).
RAPID_TOLERANCE_MM = 0.05
#: The most cells the height grid holds: a part over a metre wide checks on a coarser grid, never a full memory.
MAX_CELLS = 16_000_000


def finding(check: str, severity: str, kind: str, summary: str, description: str = "", items=()) -> dict:
    if kind not in CHECKS[check] or severity not in _SEVERITY:
        raise ValueError(f"finding {check}/{kind} ({severity}) is not one cadgen raises")
    return {"check": check, "severity": severity, "type": kind, "summary": summary, "description": description,
            "items": list(items)}


def by_severity(found) -> list[dict]:
    """Errors first, then warnings, then notes; stable within each."""
    return sorted(found, key=lambda item: _SEVERITY[item["severity"]])


def _xyz(point) -> list[float]:
    return [round(float(c), 3) + 0.0 for c in point]


def _rays_blocked(vertices, triangles, origins):
    """For each origin, whether a ray from it straight up (+Z) meets the mesh."""
    import numpy as np

    tri = np.asarray(vertices, dtype=float)[np.asarray(triangles)]
    out = np.zeros(len(origins), dtype=bool)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    keep = np.abs(det) > 1e-12
    a, b, c, det = a[keep], b[keep], c[keep], det[keep]
    for k, (x, y, z) in enumerate(origins):
        w1 = ((x - a[:, 0]) * (c[:, 1] - a[:, 1]) - (y - a[:, 1]) * (c[:, 0] - a[:, 0])) / det
        w2 = ((b[:, 0] - a[:, 0]) * (y - a[:, 1]) - (b[:, 1] - a[:, 1]) * (x - a[:, 0])) / det
        inside = (w1 >= -1e-9) & (w2 >= -1e-9) & (w1 + w2 <= 1 + 1e-9)
        at = a[:, 2] + w1 * (b[:, 2] - a[:, 2]) + w2 * (c[:, 2] - a[:, 2])
        out[k] = bool(np.any(inside & (at > z + 1e-6)))
    return out


def _face_points(vertices, triangles, mine, step: float, most: int = 2000):
    """Points spread over the triangles ``mine`` selects, about ``step`` apart (at most ``most``), just above them."""
    import numpy as np

    tri = np.asarray(vertices, dtype=float)[np.asarray(triangles)[mine]]
    points = []
    for a, b, c in tri:
        n = max(1, int(math.ceil(max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b)) / step)))
        for i in range(n + 1):
            for j in range(n + 1 - i):
                w1, w2 = (i + 1 / 3) / (n + 1), (j + 1 / 3) / (n + 1)
                points.append(a + w1 * (b - a) + w2 * (c - a))
    points = np.asarray(points).reshape(-1, 3)
    if len(points) > most:
        points = points[np.linspace(0, len(points) - 1, most).astype(int)]
    return points + [0.0, 0.0, 1e-3]


def reach(op, faces, holes, mesh, face_of_triangle, tool, stock_top: float, depth_z: float | None) -> list[dict]:
    """The reach findings of one operation, in setup coordinates (``mesh``: the part's ``(vertices, triangles)``
    there; ``faces``: the :class:`FaceInfo` of each face it names, their normals turned into the setup; ``holes``: the
    feature reader's hole for each drilled face, its ``reach`` turned into the setup's words)."""
    import numpy as np

    found = []
    vertices, triangles = mesh
    for info in faces:
        where = {"operation": op.index, "face": info.ref}
        if op.op == "drill":
            hole = holes.get(info.ref)
            if hole is None:
                found.append(finding("reach", "error", "not_facing", f"{op.where}: {info.ref} is not a hole wall",
                                     "drill names the walls of holes, as cadgen cam features lists them",
                                     [where]))
            elif "+Z" not in hole["reach"]:
                found.append(finding("reach", "error", "unreachable",
                                     f"{op.where}: the hole {info.ref} does not open toward the tool in this setup",
                                     "drill it from a setup the hole opens toward (its reach: "
                                     f"{', '.join(hole['reach']) or 'none'})", [where]))
            elif abs(tool.diameter_mm - hole["diameter_mm"]) > 0.01:
                larger = tool.diameter_mm > hole["diameter_mm"]
                found.append(finding(
                    "reach", "error" if larger else "warning", "drill_size",
                    f"{op.where}: the hole {info.ref} is Ø{hole['diameter_mm']:g} and {tool.id} is a "
                    f"Ø{tool.diameter_mm:g} drill", "a drill larger than its hole cuts into the part: drill it with "
                    "one its size" if larger else "it leaves the hole under size: open it out after (a pocket, or "
                    "a drill its size), or drill it with one its size", [where]))
            continue
        normal = info.normal
        if op.op in ("pocket", "adaptive", "face") and (normal is None or normal[2] < 1 - 1e-6):
            found.append(finding("reach", "error", "not_facing",
                                 f"{op.where}: {info.ref} is not a flat face looking up at the tool in this setup",
                                 f"{op.op} names the floors it clears down to, flat and facing the tool", [where]))
            continue
        origins = _face_points(vertices, triangles, face_of_triangle == info.ordinal, max(0.25, tool.radius / 2))
        if not len(origins):
            continue
        blocked = _rays_blocked(vertices, triangles, origins)
        if blocked.any():
            share = blocked.mean()
            found.append(finding(
                "reach", "error", "unreachable",
                f"{op.where}: {share:.0%} of {info.ref} is under the part, seen from the tool's side",
                "a tool coming straight down cannot get under what overhangs it: it would cut through it. Machine "
                "that face from a setup that sees it, or name the faces the tool can reach",
                [dict(where, at=_xyz(origins[int(np.argmax(blocked))]))]))
    if depth_z is not None and stock_top - depth_z > tool.flute_length_mm + 1e-6:
        found.append(finding(
            "reach", "error", "too_deep",
            f"{op.where}: the cut goes {stock_top - depth_z:.2f} mm below the stock top, past {tool.id}'s "
            f"{tool.flute_length_mm:g} mm of flutes",
            "use a tool with longer flutes (state its flute_length_mm), or cut less deep from this side",
            [{"operation": op.index}]))
    return found


def _profile_height(tool, d):
    """The tool's lower surface above its tip at radial distance ``d`` (an array within its radius)."""
    import numpy as np

    r = tool.radius
    if tool.type == "ball":
        return r - np.sqrt(np.maximum(0.0, r * r - d * d))
    if tool.type == "bull":
        rc = tool.corner_radius_mm
        out = np.maximum(0.0, d - (r - rc))
        return rc - np.sqrt(np.maximum(0.0, rc * rc - out * out))
    if tool.type == "drill":
        return d / math.tan(math.radians(tool.point_angle / 2.0))
    return np.zeros_like(d)


def _height_grid(vertices, triangles, low, high, cell: float):
    """The part's highest point over each cell centre (``-inf`` where it has none), and the grid's origin."""
    import numpy as np

    nx = max(1, int(math.ceil((high[0] - low[0]) / cell)))
    ny = max(1, int(math.ceil((high[1] - low[1]) / cell)))
    top = np.full((nx, ny), -np.inf)
    tri = np.asarray(vertices, dtype=float)[np.asarray(triangles)]
    e1, e2 = tri[:, 1, :2] - tri[:, 0, :2], tri[:, 2, :2] - tri[:, 0, :2]
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    keep = np.abs(det) > 1e-12
    tri, det = tri[keep], det[keep]
    lo = np.maximum(np.floor((tri[:, :, :2].min(axis=1) - low[:2]) / cell - 0.5).astype(int), 0)
    hi = np.minimum(np.ceil((tri[:, :, :2].max(axis=1) - low[:2]) / cell - 0.5).astype(int), [nx - 1, ny - 1])
    for t in range(len(tri)):
        (i0, j0), (i1, j1) = lo[t], hi[t]
        if i1 < i0 or j1 < j0:
            continue
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        px, py = low[0] + (ii + 0.5) * cell, low[1] + (jj + 0.5) * cell
        a, b, c = tri[t]
        w1 = ((px - a[0]) * (c[1] - a[1]) - (py - a[1]) * (c[0] - a[0])) / det[t]
        w2 = ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])) / det[t]
        inside = (w1 >= -1e-9) & (w2 >= -1e-9) & (w1 + w2 <= 1 + 1e-9)
        if inside.any():
            z = a[2] + w1 * (b[2] - a[2]) + w2 * (c[2] - a[2])
            np.maximum.at(top, (ii[inside], jj[inside]), z[inside])
    return top


def _dense(points, step: float):
    """The polyline through ``points`` with no gap over ``step``: each segment split evenly."""
    import numpy as np

    if len(points) < 2:
        return points
    gaps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    counts = np.maximum(1, np.ceil(gaps / step).astype(int))
    pieces = [points[:1]]
    for k, n in enumerate(counts):
        f = (np.arange(1, n + 1) / n)[:, None]
        pieces.append(points[k] + f * (points[k + 1] - points[k]))
    return np.vstack(pieces)


def _gouges(moves, select, tool, grid, low, cell: float):
    """The first sample of the moves ``select`` picks whose tool comes into the part, and how far: ``(point, depth)``
    or None."""
    import numpy as np

    keep = np.nonzero(select)[0]
    if not len(keep):
        return None
    worst = None
    # Each run of selected samples is one polyline; a move's start is the sample before it.
    runs = np.split(keep, np.nonzero(np.diff(keep) > 1)[0] + 1)
    nx, ny = grid.shape
    for run in runs:
        start = max(run[0] - 1, 0)
        points = _dense(moves.points[start:run[-1] + 1], cell)
        for chunk in range(0, len(points), 2000):
            here = points[chunk:chunk + 2000]
            i, j, height, inside = _disk(tool, cell, here, low)
            # Each cell centre's distance is from the tool's axis itself, not from the cell the axis is in; a cell at
            # the tool's very edge is the tessellation's to decide, not a gouge.
            d = np.hypot(low[0] + (i + 0.5) * cell - here[:, :1], low[1] + (j + 0.5) * cell - here[:, 1:2])
            inside &= (i >= 0) & (i < nx) & (j >= 0) & (j < ny) & (d <= tool.radius - GOUGE_TOLERANCE_MM)
            depth = np.where(inside, grid[np.clip(i, 0, nx - 1), np.clip(j, 0, ny - 1)] - height, -np.inf).max(axis=1)
            k = int(np.argmax(depth))
            if depth[k] > GOUGE_TOLERANCE_MM and (worst is None or depth[k] > worst[1]):
                worst = (here[k], float(depth[k]))
    return worst


def _disk(tool, cell: float, here, low):
    """For points ``here`` (P, 3): the grid cells under the tool's end and the tool's lower surface over each,
    ``(i, j, height, inside)`` each (P, K): ``inside`` the cells within the tool's radius."""
    import numpy as np

    span = int(math.ceil(tool.radius / cell)) + 1
    offsets = np.arange(-span, span + 1)
    di, dj = (a.ravel() for a in np.meshgrid(offsets, offsets, indexing="ij"))
    i = np.floor((here[:, :1] - low[0]) / cell).astype(int) + di[None, :]
    j = np.floor((here[:, 1:2] - low[1]) / cell).astype(int) + dj[None, :]
    d = np.hypot(low[0] + (i + 0.5) * cell - here[:, :1], low[1] + (j + 0.5) * cell - here[:, 1:2])
    inside = d <= tool.radius
    return i, j, here[:, 2:3] + _profile_height(tool, np.minimum(d, tool.radius)), inside


def _rapid_into_stock(moves, operations, tools, stock_low, stock_high, low, shape, cell: float):
    """The first rapid that runs into stock no move before it has cut: ``(operation, point, depth)`` or None.

    The stock is a height on the grid, its top to start with; each cutting move lowers it to the tool's lower surface
    along its way, in program order, so a rapid inside a pocket already cleared (FreeCAD's adaptive links passes so)
    is not a hit, and one through material is."""
    import numpy as np

    nx, ny = shape
    xs = low[0] + (np.arange(nx) + 0.5) * cell
    ys = low[1] + (np.arange(ny) + 0.5) * cell
    over = ((xs >= stock_low[0])[:, None] & (xs <= stock_high[0])[:, None]
            & (ys >= stock_low[1])[None, :] & (ys <= stock_high[1])[None, :])
    stock = np.where(over, float(stock_high[2]), -np.inf)
    tool_of = {op.index: tools[op.tool] for op in operations}
    # Runs of moves of one kind and one operation, each move by the sample it ends at.
    ends = np.arange(1, len(moves.points))
    change = (moves.rapid[2:] != moves.rapid[1:-1]) | (moves.op[2:] != moves.op[1:-1])
    for run in np.split(ends, np.nonzero(change)[0] + 1):
        if not len(run):
            continue
        tool = tool_of.get(int(moves.op[run[0]]))
        if tool is None:
            continue
        points = _dense(moves.points[run[0] - 1:run[-1] + 1], cell)
        for chunk in range(0, len(points), 2000):
            here = points[chunk:chunk + 2000]
            i, j, height, inside = _disk(tool, cell, here, low)
            inside &= (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
            ii, jj = np.clip(i, 0, nx - 1), np.clip(j, 0, ny - 1)
            if moves.rapid[run[0]]:
                depth = np.where(inside, stock[ii, jj] - height, -np.inf).max(axis=1)
                k = int(np.argmax(depth))
                if depth[k] > RAPID_TOLERANCE_MM:
                    return int(moves.op[run[0]]), here[k], float(depth[k])
            else:
                np.minimum.at(stock, (ii[inside], jj[inside]), height[inside])
    return None


def check_moves(setup_id: str, moves, operations, tools, mesh, stock_low, stock_high, machine) -> list[dict]:
    """The findings of one setup's moves (setup coordinates): ``operations`` its :class:`Operation` list, ``mesh``
    the part's ``(vertices, triangles)`` there, the stock's box from ``stock_low`` to ``stock_high``."""
    import numpy as np

    found = []
    vertices, triangles = mesh
    moving = np.concatenate([[False], np.any(np.diff(moves.points, axis=0) != 0, axis=1)])
    for op in operations:
        mine = moves.op == op.index
        if not np.any(mine & moving & ~moves.rapid):
            found.append(finding("empty_operation", "error", "empty_operation",
                                 f"{op.where}: FreeCAD planned no cut for this {op.op}",
                                 "the faces it names give it nothing to cut with this tool: check the faces "
                                 "(cadgen cam features) and that the tool fits them", [{"operation": op.index}]))
    path_low = np.minimum(moves.points.min(axis=0), np.asarray(vertices).min(axis=0))
    path_high = np.maximum(moves.points.max(axis=0), np.asarray(vertices).max(axis=0))
    smallest = min(tools[op.tool].radius for op in operations)
    cell = max(0.05, min(0.5, smallest / 4.0))
    margin = max(tools[op.tool].radius for op in operations) + cell
    low, high = path_low - margin, path_high + margin
    area = (high[0] - low[0]) * (high[1] - low[1])
    if area / cell ** 2 > MAX_CELLS:
        cell = math.sqrt(area / MAX_CELLS)
    grid = _height_grid(vertices, triangles, low, high, cell)
    for op in operations:
        mine = moves.op == op.index
        hit = _gouges(moves, mine, tools[op.tool], grid, low, cell)
        if hit is not None:
            point, depth = hit
            found.append(finding(
                "gouge", "error", "gouge",
                f"{op.where}: the tool comes {depth:.2f} mm into the part",
                "FreeCAD's path for this operation runs the tool into the part (often under an overhang it was "
                "not told about): name only faces the tool can reach, or use a smaller tool",
                [{"setup": setup_id, "operation": op.index, "at": _xyz(point)}]))
    hit = _rapid_into_stock(moves, operations, tools, stock_low, stock_high, low, grid.shape, cell)
    if hit is not None:
        k, point, depth = hit
        found.append(finding("rapid_into_stock", "error", "rapid_into_stock",
                             f"setup {setup_id}: a rapid runs {depth:.2f} mm into stock not yet cut",
                             "a rapid at full speed through material breaks the tool: raise retract_mm, or cut that "
                             "material first", [{"setup": setup_id, "operation": k, "at": _xyz(point)}]))
    if machine.travel_mm is not None:
        span = moves.points.max(axis=0) - moves.points.min(axis=0)
        over = [f"{axis} {s:.1f} mm of {t:g}" for axis, s, t in zip("XYZ", span, machine.travel_mm) if s > t + 1e-6]
        if over:
            found.append(finding("travel", "error", "travel",
                                 f"setup {setup_id}: the moves span more than the machine travels ({', '.join(over)})",
                                 "the part does not fit this machine in this setup", [{"setup": setup_id}]))
    return found
