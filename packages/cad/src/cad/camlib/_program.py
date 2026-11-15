"""camlib, the second planner a CAM job can name (``"planner": "camlib"``): the job's operations as camlib's, planned,
simulated against the stock and posted by camlib, and handed back in the shape :func:`cad.freecad._program.run` hands
FreeCAD's back (each operation's path commands, the posted files' text), so ``cad._internal.cam.run`` reads, checks and
writes both the same way.

SPIKE. What it does not do yet, each said where it matters:

* Posts: LinuxCNC only (``GCodeDialect.linuxcnc()``, the one controller camlib ships in its package; its GRBL, FANUC,
  Centroid and Haas posts are examples beside it, not part of ``import camlib``).
* Geometry: regions come from the part's mesh in setup coordinates, not its B-rep: a pocket's floor is its face's
  triangles projected, less every material above it; a profile's walls are the mesh's section just above their
  bottom. Arcs arrive as chords of the part's tessellation.
* Tool holders: a job names none, so each tool's holder is a cylinder twice its shank, 40 mm long, above its
  stickout, listed under ``assumed``.
* Machine: no crash model, so camlib's export gate is passed ``accept={"unchecked_machine"}`` and says so.

Moves are read back from the posted program itself (lines only: ``native_arcs`` is off), operation by operation by the
``operation`` camlib stamps on each NC line, so cad's checks run on what the machine would run.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

__all__ = ["Camlib", "CamlibMissingError", "find_camlib", "run"]

#: The posts camlib can write here: the job's post -> the dialect's factory name and the file's extension.
POSTS = {"linuxcnc": "linuxcnc"}
_OFFSETS = {f"G{54 + k}": k + 1 for k in range(6)}
#: The assumed holder, since a job names none.
HOLDER_LENGTH_MM = 40.0
CELL_MM = 0.5


class CamlibMissingError(RuntimeError):
    """camlib is not importable in this environment."""


@dataclass(frozen=True)
class Camlib:
    version: str

    @property
    def label(self) -> str:
        return f"camlib {self.version}"


def find_camlib() -> Camlib:
    try:
        import camlib  # noqa: F401
    except ImportError as exc:
        raise CamlibMissingError(
            "camlib is not installed in this environment: build it from github.com/stevecad/camlib "
            f"(`pip install <checkout>`, needs a Rust toolchain) ({exc})") from None
    from importlib.metadata import PackageNotFoundError, version

    try:
        found = version("cam-engine")
    except PackageNotFoundError:
        found = "unknown"
    return Camlib(version=found)


# --- geometry ---------------------------------------------------------------------------------------------

def _polygons(shape):
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(shape, Polygon):
        return [] if shape.is_empty else [shape]
    if isinstance(shape, MultiPolygon):
        return [p for p in shape.geoms if not p.is_empty]
    return [g for g in getattr(shape, "geoms", ()) if isinstance(g, Polygon) and not g.is_empty]


def _projected(vertices, triangles, mask):
    """The union of the XY shadows of the masked triangles (those with no shadow, walls, left out)."""
    import numpy as np
    import shapely

    tris = vertices[triangles[mask]][:, :, :2]
    if not len(tris):
        return shapely.Polygon()
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    area = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    tris = tris[area > 1e-9]
    if not len(tris):
        return shapely.Polygon()
    rings = np.concatenate([tris, tris[:, :1]], axis=1)
    return shapely.union_all(shapely.polygons(rings), grid_size=1e-6)


def _section(vertices, triangles, z):
    """The part's material in the plane at height ``z``: the mesh's section loops, even-odd."""
    import numpy as np
    import shapely
    from shapely.ops import linemerge, polygonize

    tris = np.asarray(vertices, dtype=float)[np.asarray(triangles)]
    side = tris[:, :, 2] > z
    crossing = tris[side.any(axis=1) & ~side.all(axis=1)]
    segments = []
    for tri in crossing:
        points = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            za, zb = tri[a, 2], tri[b, 2]
            if (za > z) != (zb > z):
                f = (z - za) / (zb - za)
                points.append(tuple(tri[a, :2] + f * (tri[b, :2] - tri[a, :2])))
        if len(points) == 2:
            segments.append(points)
    lines = shapely.MultiLineString(segments)
    out = shapely.Polygon()
    for loop in polygonize(linemerge(shapely.set_precision(lines, 1e-6))):
        out = out.symmetric_difference(shapely.Polygon(loop.exterior))  # each loop once: polygonize gives faces
    return out


def _component(polygon, simplify_mm):
    from camlib.planar import Boundary, Component

    polygon = shapely_orient(polygon.simplify(simplify_mm))

    def ring(coords):
        return Boundary.polygon(tuple((float(x), float(y)) for x, y in list(coords)[:-1]))

    return Component(ring(polygon.exterior.coords), holes=tuple(ring(r.coords) for r in polygon.interiors))


def shapely_orient(polygon):
    from shapely.geometry.polygon import orient

    return orient(polygon, sign=1.0)


def _region(name, shape, simplify_mm=0.002):
    from camlib.planar import PlanarRegion

    polygons = _polygons(shape.buffer(0))
    if not polygons:
        raise RuntimeError(f"{name}: no area to cut")
    return PlanarRegion(name, tuple(_component(p, simplify_mm) for p in polygons))


def _face_mask(geometry, ordinals):
    import numpy as np

    return np.isin(geometry["face_of_triangle"], list(ordinals))


def _pocket_region(name, geometry, spec):
    """A pocket's area: each floor's outline, its holes filled (what goes deeper is cleared to this floor too), less
    the shadow of every material standing above the floor (an island, an overhang the tool cannot reach under)."""
    import shapely

    vertices, triangles = geometry["vertices"], geometry["triangles"]
    floor_z = spec["final_z"]
    floors = _projected(vertices, triangles, _face_mask(geometry, spec["faces"]))
    outline = shapely.union_all([shapely.Polygon(p.exterior) for p in _polygons(floors)])
    above = vertices[triangles][:, :, 2].min(axis=1) > floor_z + 1e-3
    return _region(name, outline.difference(_projected(vertices, triangles, above)))


def _contour_region(name, geometry, spec, stock_low, stock_high):
    """A profile's walls as camlib's region and the boundaries it cuts: the part's silhouette (outside, no faces);
    else the section just above the named walls' bottom, its loops the walls touch (``outer`` outside, ``holes``
    inside, inside a stock-sized outline)."""
    import numpy as np
    import shapely

    vertices, triangles = geometry["vertices"], geometry["triangles"]
    side = spec["side"] or "outside"
    if not spec["faces"]:
        return _region(name, _projected(vertices, triangles, np.ones(len(triangles), dtype=bool))), "outer"
    mask = _face_mask(geometry, spec["faces"])
    walls = vertices[triangles[mask]]
    z = float(walls[:, :, 2].min()) + 0.05
    section = _section(vertices, triangles, z)
    touch = shapely.MultiPoint(walls.reshape(-1, 3)[:, :2]).buffer(0.05)
    if side == "outside":
        rings = [shapely.Polygon(p.exterior) for p in _polygons(section) if p.exterior.intersects(touch)]
        return _region(name, shapely.union_all(rings)), "outer"
    holes = [r for p in _polygons(section) for r in p.interiors if r.intersects(touch)]
    if not holes:
        raise RuntimeError(f"{name}: the walls it names bound no hole in the part at z {z:g}")
    pad = 50.0
    outer = shapely.box(stock_low[0] - pad, stock_low[1] - pad, stock_high[0] + pad, stock_high[1] + pad)
    return _region(name, shapely.Polygon(outer.exterior, [r.coords for r in holes])), "holes"


def _hole_centers(geometry, ordinals):
    out = []
    for ordinal in ordinals:
        points = geometry["vertices"][geometry["triangles"][_face_mask(geometry, [ordinal])]].reshape(-1, 3)
        low, high = points.min(axis=0), points.max(axis=0)
        out.append((float((low[0] + high[0]) / 2), float((low[1] + high[1]) / 2)))
    return tuple(out)


# --- the job ----------------------------------------------------------------------------------------------

def _assembly(spec):
    from camlib.tools import BallEndMill, BullEndMill, Drill, EndMill, HolderSection, ToolAssembly

    dims = dict(diameter=spec["diameter_mm"], flute_length=spec["flute_length_mm"],
                overall_length=spec["stickout_mm"] + HOLDER_LENGTH_MM)
    kind = spec["type"]
    if kind == "drill":
        cutter = Drill(spec["id"], point_angle=spec["point_angle"], **dims)
        shank = spec["diameter_mm"]
    else:
        dims.update(flutes=spec["flutes"], shank_diameter=spec["shank_diameter_mm"])
        shank = spec["shank_diameter_mm"]
        cutter = (EndMill(spec["id"], **dims) if kind == "flat" else BallEndMill(spec["id"], **dims) if kind == "ball"
                  else BullEndMill(spec["id"], corner_radius=spec["corner_radius_mm"], **dims))
    stickout = spec["stickout_mm"]
    radius = max(shank, spec["diameter_mm"])
    return ToolAssembly(spec["id"], cutter, stickout_mm=stickout, gauge_length_mm=stickout + HOLDER_LENGTH_MM,
                        holders=(HolderSection(stickout, stickout + HOLDER_LENGTH_MM, radius, radius),))


def _operation(spec, tool, number, geometry, stock_low, stock_high, plan):
    from camlib.operations import AdaptivePocket, Contour, Drilling, Facing, Pocket

    top = float(stock_high[2])
    clearance = top + plan["clearance_mm"]
    feeds = spec["feeds"]
    common = dict(spindle_rpm=feeds["rpm"], tool_number=number, length_register=number,
                  coolant=spec["coolant"] if spec["coolant"] != "off" else "off",
                  work_offset=_OFFSETS[plan["work_offset"]])
    name = f"op{spec['index']}"
    diameter = tool.cutter.diameter_mm
    kind = spec["op"]
    if kind == "face":
        return Facing(name, tool, floor_z_mm=spec["final_z"], stepdown_mm=spec["stepdown_mm"],
                      stepover_mm=spec["stepover"] * diameter, clearance_z_mm=clearance,
                      feed_mm_min=feeds["feed_mm_min"], plunge_mm_min=feeds["plunge_mm_min"], **common)
    if kind in ("pocket", "adaptive"):
        cls = Pocket if kind == "pocket" else AdaptivePocket
        return cls(name, tool, _pocket_region(name, geometry, spec), top_z_mm=top, floor_z_mm=spec["final_z"],
                   stepdown_mm=spec["stepdown_mm"], stepover_mm=spec["stepover"] * diameter, clearance_z_mm=clearance,
                   radial_allowance_mm=spec["leave_mm"], bottom_allowance_mm=spec["leave_mm"],
                   feed_mm_min=feeds["feed_mm_min"], plunge_mm_min=feeds["plunge_mm_min"], **common)
    if kind == "profile":
        region, boundaries = _contour_region(name, geometry, spec, stock_low, stock_high)
        return Contour(name, tool, region, floor_z_mm=spec["final_z"], stepdown_mm=spec["stepdown_mm"],
                       clearance_z_mm=clearance, boundaries=boundaries, radial_allowance_mm=spec["leave_mm"],
                       feed_mm_min=feeds["feed_mm_min"], plunge_mm_min=feeds["plunge_mm_min"], **common)
    if kind == "drill":
        depth = spec["final_z"]
        return Drilling(name, tool, _hole_centers(geometry, spec["faces"]), depth, clearance,
                        peck_mm=spec["peck_mm"], retract_z_mm=top + plan["retract_mm"],
                        allow_breakthrough_mm=max(0.0, float(stock_low[2]) - depth) + 1e-3,
                        feed_mm_min=feeds["feed_mm_min"], retract_feed_mm_min=feeds["feed_mm_min"], **common)
    raise RuntimeError(f"camlib: no {kind} operation here yet")


_WORD = re.compile(r"([A-Z])\s*([-+]?\d*\.?\d+)")


def _commands(lines):
    """Posted G0/G1 lines (modal) as FreeCAD-shaped path commands, feeds in mm/s as FreeCAD's are."""
    out, motion, feed = [], None, None
    for text in lines:
        code = text.split(";", 1)[0]
        code = re.sub(r"\([^)]*\)", "", code).upper()
        words = _WORD.findall(code)
        axes = {}
        for letter, value in words:
            if letter == "G" and value in ("0", "00", "1", "01"):
                motion = "G0" if float(value) == 0 else "G1"
            elif letter == "G" and value in ("2", "02", "3", "03", "81", "82", "83", "73"):
                raise RuntimeError(f"camlib posted {letter}{value}, which this spike does not read back: {text}")
            elif letter == "F":
                feed = float(value)
            elif letter in "XYZ":
                axes[letter] = float(value)
        if axes and motion:
            params = dict(axes)
            if motion == "G1" and feed is not None:
                params["F"] = feed / 60.0
            out.append([motion, params])
    return out


def _material(geometry, base_z):
    """The part as camlib's material target: its own check that no posted move cuts into it (the tessellation's
    error, 0.01 mm, declared), beside cad's gouge check. Its protected base plane is the sacrificial board's bottom
    (``base_z``), so a cut through the part is no gouge."""
    from camlib.material import Options, SurfaceTarget
    from camlib.verification import MaterialCheck
    from camlib.surface import SurfaceMesh

    vertices, triangles = geometry["vertices"], geometry["triangles"]
    surface = SurfaceMesh(tuple(tuple(map(tuple, tri)) for tri in vertices[triangles].tolist()), surface_error_mm=0.01)
    target = SurfaceTarget("part", "1", surface, base_z_mm=base_z)
    return MaterialCheck(target, options=Options(comparison_tolerance_mm=0.05, gouge_tolerance_mm=0.03))


def run(camlib: Camlib, plan: dict, geometry: dict) -> tuple[dict, dict[str, str]]:
    """Plan and post one setup: ``(report, texts)`` as FreeCAD's runner returns them, ``report["camlib"]`` holding
    camlib's own verdict (its export, its check summary, its timings)."""
    import warnings

    from camlib.export import ExportRefused
    from camlib import ToolChangeTable
    from camlib.jobs import Job, Setup
    from camlib.post import GCodeDialect, LoweringOptions, Machine, ToolSetting
    from camlib.simulation import StockSpec
    from camlib.verification import StockContactOptions, StreamChecks

    if plan["post"] not in POSTS:
        raise RuntimeError(f"camlib posts {', '.join(POSTS)} here, not {plan['post']}")
    stock_low, stock_high = plan["stock"]["min"], plan["stock"]["max"]
    assemblies = {spec["id"]: _assembly(spec) for spec in plan["tools"]}
    numbers = {spec["id"]: spec["number"] for spec in plan["tools"]}
    ops = [_operation(spec, assemblies[spec["tool"]], numbers[spec["tool"]], geometry, stock_low, stock_high, plan)
           for spec in plan["operations"]]
    index_of = {op.id: spec["index"] for op, spec in zip(ops, plan["operations"])}
    start = (0.0, 0.0, float(stock_high[2]) + plan["clearance_mm"])
    tools = tuple(assemblies[t] for t in dict.fromkeys(spec["tool"] for spec in plan["operations"]))
    machine_args = dict(
        dialect=getattr(GCodeDialect, POSTS[plan["post"]])(), output_units="mm", decimals=3,
        max_feed_mm_min=plan["machine"]["max_feed_mm_min"], max_spindle_rpm=plan["machine"]["max_rpm"],
        rapid_mm_min=plan["machine"]["rapid_mm_min"], planes=("xy", "xz", "yz"), arcs=True, helices=True,
        max_sweep_rad=math.tau, max_tool_number=99999, max_length_register=99999, tool_changes=True, flood=True,
        mist=True, tool_change_position_mode="table")
    tip_after = lambda tool: (0.0, 0.0, start[2])  # noqa: E731 - each change leaves the tip at the start: assumed
    machine = Machine("text-to-cad job machine", tuple(
        ToolSetting.for_tool(tool, number=numbers[tool.id], length_register=numbers[tool.id],
                             position_after_mm=tip_after(tool)) for tool in tools), **machine_args)
    # A cut through the part goes below the stock's bottom, which camlib refuses: its stock reaches down past the
    # deepest such cut, standing for the sacrificial board under the part (assumed).
    deepest = min([float(stock_low[2])] + [spec["final_z"] - 0.01 for spec in plan["operations"]
                                           if spec.get("final_z") is not None])
    sim_low = (stock_low[0], stock_low[1], deepest)
    setup = Setup("setup", stock=StockSpec(min_mm=tuple(sim_low), max_mm=tuple(stock_high), cell_size_mm=CELL_MM),
                  tools=tools, operations=tuple(ops), initial_position_mm=start,
                  tool_change=ToolChangeTable.from_machine(machine),
                  verification=StreamChecks(stock_contact=StockContactOptions(), material=(_material(geometry, deepest),)))
    job = Job("text-to-cad", "1", (setup,))
    started = time.perf_counter()
    lines = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with job.post("setup", machine=machine, lowering=LoweringOptions(native_arcs=False)) as stream:
            stream.wait()
            first = 1
            while page := stream.nc_lines(first, limit=256):
                lines.extend(page)
                first = page[-1]["number"] + 1
            planned_s = time.perf_counter() - started
            # camlib's gate: a definite violation refuses the program (an error here); a result it could not decide
            # on its stock grid (a drill the hole's own size, tangent to its wall) is released as a warning, since
            # cad's own gouge check decides those cells exactly.
            exported, refused, uncertain = None, None, None
            try:
                exported = stream.export(None, accept={"unchecked_machine"})
            except ExportRefused as error:
                try:
                    exported = stream.export(None, accept={"unchecked_machine", "uncertain"})
                    uncertain = str(error)
                except ExportRefused as again:
                    refused = str(again)
            status = stream.status()
    by_op: dict[int, list[str]] = {spec["index"]: [] for spec in plan["operations"]}
    for line in lines:
        index = index_of.get(line.get("operation"))
        if index is not None:
            by_op[index].append(line["text"])
    text = "\n".join(line["text"] for line in lines) + "\n"
    report = {
        "operations": [{"index": spec["index"], "commands": _commands(by_op[spec["index"]]), "held": {}}
                       for spec in plan["operations"]],
        "posts": [name for name, _ in plan["files"]],
        "camlib": {"planned_s": round(planned_s, 3), "export_refused": refused, "export_uncertain": uncertain,
                   "exported": None if exported is None else {k: v for k, v in exported.items() if k != "text"},
                   "status": status, "warnings": [str(w.message) for w in caught]},
    }
    texts = {name: text for name, _ in plan["files"]}
    return report, texts
