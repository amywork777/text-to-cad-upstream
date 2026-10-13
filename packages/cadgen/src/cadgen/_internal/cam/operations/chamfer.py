"""``chamfer`` (Chamfer): break the top edges of a face's loops with a vee or chamfer tool, at a chamfer width.

What it follows: ``faces``: a flat face facing the tool names every edge of its outline and its holes (``loops``:
``all``, the default, ``outer`` or ``inner``), the air side of each (outside the outline, inside a hole); a wall (a
plane square to XY, a cylinder or cone along Z) names the top edge of the loop it stands on. Or a ``region``:
``{"polygon": [[x, y], ...], "bottom_z": z}`` whose outline is an edge at height ``bottom_z`` with the material
inside it.

``width_mm`` (required) is the chamfer's leg across the top face. The depth comes from the tool's angle: a cone of
half angle a cuts a chamfer ``width / tan(a)`` deep (a 90° vee: 45°, as deep as it is wide). ``tip_offset_mm``
(default 0.2 for a sharp tip, 0 for a tip with a flat) puts the tool's tip that much lower, so the cut is made by
the cone, not the point: the tool's centre then runs ``tip radius + tip offset x tan(a)`` off the edge on the air
side. The tool must be wide enough for the chamfer: a cone ``diameter_mm`` across holds a chamfer up to its radius
less that offset; a wider one is refused. One pass per loop, climb by default (``direction``).

The part as modelled has sharp edges there, so the chamfer cuts into it by design: the ``gouge`` check does not
judge this operation; the chamfer's width and depth are in its facts.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, choice, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation, region_polygon

__all__ = ["ChamferOp"]


class ChamferOp(Operation):
    name = "chamfer"
    plain = "Chamfer"
    family = "2.5D milling"
    machines = MILLS
    status = "full"
    keys = ("width_mm", "tip_offset_mm", "loops", "direction")
    tool_types = ("vee", "chamfer", "engraver", "spot")
    takes_faces = True
    takes_region = True
    feeds_kind = "finish"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        if not spec.faces and spec.region is None:
            raise CamJobError(f"{spec.where}: a chamfer needs the faces whose edges it breaks (\"faces\": [\"#o1.f3\"]) "
                              "or a \"region\" ({\"polygon\": [[x, y], ...], \"bottom_z\": z})")
        if spec.faces and spec.region is not None:
            raise CamJobError(f"{spec.where}: give a chamfer faces or a region, not both")
        extra = spec.extra
        if "width_mm" not in extra:
            raise CamJobError(f"{spec.where}: a chamfer needs \"width_mm\", the chamfer's width across the top face")
        tool = ctx.job.tool(spec.tool)
        params = {
            "width_mm": read_number(extra, "width_mm", spec.where),
            "tip_offset_mm": read_number(extra, "tip_offset_mm", spec.where,
                                         default=0.2 if tool.tip_diameter_mm <= 0 else 0.0, minimum=0.0),
            "loops": choice(extra.get("loops", "all"), ("all", "outer", "inner"), f"{spec.where}.loops"),
            "climb": choice(extra.get("direction", "climb"), ("climb", "conventional"), f"{spec.where}.direction")
            == "climb",
            "region": None,
        }
        half = math.radians((tool.angle_deg or 90.0) / 2.0)
        need = tool.tip_diameter_mm / 2.0 + params["tip_offset_mm"] * math.tan(half) + params["width_mm"]
        if need > tool.radius + 1e-9:
            most = tool.radius - tool.tip_diameter_mm / 2.0 - params["tip_offset_mm"] * math.tan(half)
            raise CamJobError(f"{spec.where}: {tool.id} ({tool.plain}, {tool.diameter_mm:g} mm across) chamfers at most "
                              f"{max(0.0, most):.3g} mm wide with a tip offset of {params['tip_offset_mm']:g} mm; use a "
                              "bigger tool or a narrower width_mm")
        if spec.region is not None:
            params["region"] = region_polygon(spec, where=spec.where)
            if params["region"][1] is None:
                raise CamJobError(f"{spec.where}.region needs \"bottom_z\", the height of the edge to chamfer")
        return params

    def plan(self, ctx, params):
        import numpy as np

        from cadgen._internal.cam import geom2d, linking
        from cadgen._internal.cam.operations._milling2d import Target, face_targets, lift_and_go, orient, rotate_to_nearest

        tool = ctx.tool
        tol = ctx.tolerance_mm
        heights = ctx.heights
        half = math.radians((tool.angle_deg or 90.0) / 2.0)
        width = params["width_mm"]
        tip = params["tip_offset_mm"]
        depth = width / math.tan(half)
        offset = tool.tip_diameter_mm / 2.0 + tip * math.tan(half)
        if params["region"] is not None:
            polygon, z = params["region"]
            targets = [Target(polygon=polygon, side="outside", z=z, kind="region")]
        else:
            targets = face_targets(ctx, ctx.spec.faces, where=f"{ctx.spec.where}.faces")
        rings = []
        seen = set()
        for target in targets:
            edge = target.top_z if target.kind == "wall" else target.z
            if target.kind == "under":
                raise CamJobError(f"{ctx.spec.where}.faces: {target.ref} faces away from the tool in setup "
                                  f"'{ctx.setup.id}'; chamfer its edges from a setup that faces it")
            key = (round(target.polygon.area, 3), round(target.polygon.centroid.x, 3),
                   round(target.polygon.centroid.y, 3), round(edge, 4))
            if key in seen:
                continue
            seen.add(key)
            # The tool runs on the air side: outside a face's outline, inside its holes (a wall: its own air side).
            distance = offset if target.side == "outside" else -offset
            shape = geom2d.offset(target.polygon, distance, tolerance=tol) if offset > 0 else target.polygon
            material_outer = target.side == "outside"
            for piece in geom2d.polygons_of(shape):
                if params["loops"] in ("all", "outer") or target.kind == "wall":
                    rings.append((np.asarray(piece.exterior.coords)[:, :2], material_outer, edge))
                if params["loops"] in ("all", "inner") and target.kind != "wall":
                    rings.extend((np.asarray(ring.coords)[:, :2], not material_outer, edge) for ring in piece.interiors)
        if not rings:
            raise CamJobError(f"{ctx.spec.where}: no edge to chamfer: the loops are smaller than the tool's offset")
        feeds = ctx.feeds(self.feeds_kind)
        b = ctx.builder()
        lowest = None
        ordered = linking.order_nearest(rings, b.pos, key=lambda row: tuple(row[0][0]))
        for ring, material_inside, edge in ordered:
            ring = orient(ring, material_inside=material_inside, climb=params["climb"])
            ring = rotate_to_nearest(ring, b.pos)
            z = edge - depth - tip
            if z >= heights.stock_top:
                continue
            lowest = z if lowest is None else min(lowest, z)
            lift_and_go(b, ring[0], heights)
            b.feed(z=min(heights.retract, edge + 1.0), f=feeds.feed_mm_min)
            b.plunge(z=z, f=feeds.plunge_mm_min)
            b.polyline(np.column_stack([ring[1:], np.full(len(ring) - 1, z)]), f=feeds.feed_mm_min)
            b.rapid(z=heights.retract)
        b.rapid(z=heights.clearance)
        ctx.meta.update({"loops": len(rings), "width_mm": width, "depth_mm": round(depth, 4),
                         "tip_z": round(lowest, 4) if lowest is not None else None, "no_gouge_check": True,
                         "note_level": "info",
                         "note": f"chamfers {width:g} mm wide and {depth:.3g} mm deep into the modelled sharp edges "
                                 "(not judged by the gouge check)"})
        return b.build()
