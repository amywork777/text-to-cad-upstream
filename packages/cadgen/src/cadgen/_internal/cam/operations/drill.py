"""``drill``: drill, peck, chip-break, tap, ream, bore or spot a set of holes along the setup's Z, in canned cycles.

Which holes (exactly one of):

* ``faces``: hole walls (``#o1.fN`` cylinders; either half of a split hole names it). Each hole's axis must be the
  setup's Z (a through hole either way); one that is not is refused naming the setup, or the orientation, that
  would reach it.
* ``holes``: ``"all"`` (every hole this setup can reach; the ones along other axes are left and counted in the
  op's note) or ``{"diameter_mm": 5, "tolerance_mm": 0.05}``.
* ``points``: ``[[x, y], ...]`` in the setup's WCS, with ``depth_mm`` (below each hole's top) and an optional
  ``top_z`` (default: the part's top there, else the stock's).

``cycle`` (default by tool: a drill or flat end mill ``drill``, or ``peck`` when the deepest hole is three diameters or
more; a spot or chamfer tool ``spot``; a tap ``tap``; a reamer ``ream``; a boring bar ``bore``):

=============  =========  ===================================================================================
``drill``      G81        feed to depth, rapid out
``dwell``      G82        feed to depth, dwell ``dwell_s`` (default 0.5), rapid out
``peck``       G83        pecks of ``peck_mm`` (default one diameter), back to R after each (clears chips)
``chipbreak``  G73        pecks of ``peck_mm`` (default half a diameter), back ``retract_mm`` (0.2) after each
``tap``        G84 / G74  feed at rpm x the tap's pitch, reverse, feed out; a left-hand tap (``hand: left``) G74
``ream``       G85        feed in, feed out
``bore``       G85 / G89 / G86 / G76 by ``bore_mode``: ``feed`` (feed out), ``dwell`` (dwell, feed out), ``stop``
                          (spindle stop, rapid out), ``fine`` (oriented stop, shift ``shift_mm`` off the wall,
                          rapid out)
``spot``       G81 / G82  a short spot: the cone as wide as the hole (or ``depth_mm``), ``dwell_s`` optional
=============  =========  ===================================================================================

Depth: a through hole goes ``breakthrough_mm`` (default 1) past its exit with the full diameter, so the tip goes
the point's length further; a blind hole stops its tip on the floor (``depth_to: "tip"``) or its full diameter
there (``"shoulder"``; the default when the model draws a drill point below the floor). A tap stops a pitch above a
blind hole's floor and runs three pitches of lead past a through hole's exit. ``depth_mm`` overrides any of it.

Each hole is fed from its R plane (the setup's ``retract_mm`` over the hole's top; holes at the part's top start
from over the stock); between holes the tool returns to R when every link at that height clears the part
(``return_to``: ``auto``, ``r_plane``, ``initial``), else to the initial level over the stock. Holes are visited
nearest-first, then improved by 2-opt (``order``: ``shortest``, or ``given``); runs of holes with one depth and
one R plane are one cycle event, so posts emit G8x blocks or the expansion.

Its own findings (warnings): a tool more than ``size_tolerance_mm`` (default 0.05) off the hole's diameter, a tap
whose pitch is not its thread's or whose hole is not drawn for it.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, check_keys, choice, number_list, read_number
from cadgen._internal.cam.operations import MILLS
from cadgen._internal.cam.operations.base import Operation

__all__ = ["CYCLES", "DrillOp"]

#: Each cycle the job names: the tools it cuts with, its feeds kind, and its plain word.
CYCLES: dict[str, dict] = {
    "drill": {"tools": ("drill", "flat", "spot"), "feeds": "drill", "word": "Drill"},
    "dwell": {"tools": ("drill", "flat", "spot"), "feeds": "drill", "word": "Drill (dwell)"},
    "peck": {"tools": ("drill", "flat"), "feeds": "drill", "word": "Peck drill"},
    "chipbreak": {"tools": ("drill", "flat"), "feeds": "drill", "word": "Chip-break drill"},
    "tap": {"tools": ("tap",), "feeds": "tap", "word": "Tap"},
    "ream": {"tools": ("reamer",), "feeds": "ream", "word": "Ream"},
    "bore": {"tools": ("boring",), "feeds": "bore", "word": "Bore"},
    "spot": {"tools": ("spot", "drill", "chamfer"), "feeds": "spot", "word": "Spot"},
}
_DEFAULT_CYCLE = {"drill": "drill", "flat": "drill", "spot": "spot", "chamfer": "spot", "tap": "tap",
                  "reamer": "ream", "boring": "bore"}
BORE_MODES = ("feed", "dwell", "stop", "fine")
#: The IR cycle a bore mode posts as (ir.py: G85, G89, G86, G76).
_BORE_IR = {"feed": "bore", "dwell": "bore_dwell", "stop": "bore_stop", "fine": "fine_bore"}
#: How far a G83 peck comes back down short of the last depth before feeding on (mm).
PECK_CLEARANCE = 0.5


class DrillOp(Operation):
    name = "drill"
    plain = "Drill"
    family = "2.5D milling"
    machines = MILLS
    status = "full"
    keys = ("cycle", "holes", "points", "depth_mm", "top_z", "depth_to", "breakthrough_mm", "peck_mm", "retract_mm",
            "dwell_s", "bore_mode", "shift_mm", "return_to", "order", "size_tolerance_mm")
    tool_types = ("drill", "flat", "spot", "chamfer", "tap", "reamer", "boring")
    takes_faces = True
    feeds_kind = "drill"

    def parse(self, spec, ctx):
        super().parse(spec, ctx)
        where = spec.where
        extra = spec.extra
        tool = ctx.job.tool(spec.tool)
        chosen = [key for key, given in (("faces", bool(spec.faces)), ("holes", "holes" in extra),
                                         ("points", "points" in extra)) if given]
        if len(chosen) != 1:
            raise CamJobError(f"{where}: a drill names its holes one way: \"faces\" (hole walls), \"holes\" (\"all\" or "
                              "{\"diameter_mm\": 5}) or \"points\" ([[x, y], ...] with \"depth_mm\")"
                              + (f"; it has {' and '.join(chosen)}" if chosen else ""))
        cycle = choice(extra["cycle"], tuple(CYCLES), f"{where}.cycle") if "cycle" in extra else None
        if cycle is None and "peck_mm" in extra and tool.type in ("drill", "flat"):
            cycle = "peck"
        if cycle is not None and tool.type not in CYCLES[cycle]["tools"]:
            raise CamJobError(f"{where}: a {cycle} cycle cuts with a {' or '.join(CYCLES[cycle]['tools'])}; {tool.id} "
                              f"is a {tool.type}" + (f" (its cycle is {_DEFAULT_CYCLE[tool.type]})"
                                                     if tool.type in _DEFAULT_CYCLE else ""))
        known = cycle or _DEFAULT_CYCLE[tool.type]

        def only(key: str, cycles: tuple[str, ...]) -> None:
            if key in extra and known not in cycles:
                raise CamJobError(f"{where}.{key} is for the {' and '.join(cycles)} cycle{'s' if len(cycles) > 1 else ''}; "
                                  f"this one is {known}")

        only("peck_mm", ("peck", "chipbreak"))
        only("retract_mm", ("chipbreak",))
        only("dwell_s", ("dwell", "spot", "tap", "bore"))
        only("bore_mode", ("bore",))
        only("shift_mm", ("bore",))
        params = {
            "cycle": cycle,
            "faces": tuple(spec.faces),
            "holes": None,
            "points": None,
            "depth_mm": read_number(extra, "depth_mm", where),
            "top_z": read_number(extra, "top_z", where, minimum=-1e6),
            "depth_to": choice(extra["depth_to"], ("tip", "shoulder"), f"{where}.depth_to") if "depth_to" in extra
            else None,
            "breakthrough_mm": read_number(extra, "breakthrough_mm", where, default=1.0, minimum=0.0),
            "peck_mm": read_number(extra, "peck_mm", where),
            "retract_mm": read_number(extra, "retract_mm", where, default=0.2),
            "dwell_s": read_number(extra, "dwell_s", where, minimum=0.0),
            "bore_mode": choice(extra.get("bore_mode", "feed"), BORE_MODES, f"{where}.bore_mode"),
            "shift_mm": read_number(extra, "shift_mm", where, default=0.1),
            "return_to": choice(extra.get("return_to", "auto"), ("auto", "r_plane", "initial"), f"{where}.return_to"),
            "order": choice(extra.get("order", "shortest"), ("shortest", "given"), f"{where}.order"),
            "size_tolerance_mm": read_number(extra, "size_tolerance_mm", where, default=0.05),
        }
        if "shift_mm" in extra and params["bore_mode"] != "fine":
            raise CamJobError(f"{where}.shift_mm is for \"bore_mode\": \"fine\" (G76); this bore is {params['bore_mode']}")
        if "holes" in extra:
            params["holes"] = _holes_selector(extra["holes"], f"{where}.holes")
        if "points" in extra:
            raw = extra["points"]
            if not isinstance(raw, list) or not raw:
                raise CamJobError(f"{where}.points must be a list of [x, y] hole centres in the setup's WCS, like "
                                  "[[10, 5], [20, 5]]")
            params["points"] = tuple(number_list(p, f"{where}.points[{i}]", length=2) for i, p in enumerate(raw))
            if params["depth_mm"] is None and known != "spot":
                raise CamJobError(f"{where}: drilling at points needs \"depth_mm\", how deep below each hole's top "
                                  "(add \"top_z\" when the top is not the part's surface there)")
        elif params["top_z"] is not None:
            raise CamJobError(f"{where}.top_z is for holes given as points; holes from faces know their top")
        if known == "tap":
            if spec.feed is not None:
                raise CamJobError(f"{where}: a tap feeds at exactly rpm x pitch ({tool.id}: {tool.pitch_mm:g} mm a "
                                  "turn); set \"speed\" (rpm) instead of \"feed\"")
            if params["depth_to"] is not None:
                raise CamJobError(f"{where}.depth_to does not apply to a tap: it stops a pitch above a blind hole's "
                                  "floor; give depth_mm to tap to another depth")
        if known in ("tap", "ream", "bore") and params["depth_to"] == "shoulder":
            params["depth_to"] = "tip"
        return params

    # --- planning ------------------------------------------------------------------------------------------

    def plan(self, ctx, params):
        import numpy as np

        from cadgen._internal.cam import drilling, linking

        tool = ctx.tool
        where = ctx.spec.where
        heights = ctx.heights
        b = ctx.builder()
        notes: list[str] = []
        if params["faces"]:
            holes = drilling.holes_from_faces(ctx, params["faces"], where)
        elif params["holes"] is not None:
            holes, elsewhere = drilling.holes_matching(ctx, params["holes"], where)
            if elsewhere:
                notes.append(f"{elsewhere} matching hole{'s' if elsewhere > 1 else ''} along another axis "
                             "left for a setup that faces it")
        else:
            holes = drilling.holes_from_points(ctx, params["points"], params["top_z"])
        cycle = params["cycle"] or _DEFAULT_CYCLE[tool.type]
        if params["cycle"] is None and cycle == "drill" and tool.type in ("drill", "flat"):
            deepest = max((h.depth or params["depth_mm"] or 0.0) for h in holes)
            if deepest >= 3.0 * tool.diameter_mm - 1e-9:
                cycle = "peck"
        feeds = ctx.feeds(CYCLES[cycle]["feeds"])
        tip = drilling.tip_length(tool)
        gap = ctx.setup.retract_mm
        initial = heights.retract
        rows = []
        for hole in holes:
            bottom = self._bottom(tool, cycle, hole, params, tip)
            if hole.top >= heights.part_top - 1e-6:
                r_plane = max(hole.top + gap, initial)
            else:
                r_plane = hole.top + gap
            rows.append((hole, bottom, min(r_plane, initial)))
        # Order: nearest first then 2-opt, from where the tool is.
        if params["order"] == "shortest" and len(rows) > 1:
            order, _ = drilling.order_shortest([(h.x, h.y) for h, _, _ in rows], ctx.start[:2])
            rows = [rows[k] for k in order]
        # Runs of one depth and one R plane are one cycle.
        groups: list[list] = []
        for row in rows:
            key = (round(row[1], 6), round(row[2], 6))
            if groups and (round(groups[-1][0][1], 6), round(groups[-1][0][2], 6)) == key:
                groups[-1].append(row)
            else:
                groups.append([row])
        ir_cycle = _BORE_IR[params["bore_mode"]] if cycle == "bore" else "spot" if cycle == "dwell" else cycle
        dwell = params["dwell_s"]
        if cycle == "dwell" and dwell is None:
            dwell = 0.5
        if cycle == "bore" and params["bore_mode"] == "dwell" and dwell is None:
            dwell = 0.5
        peck = params["peck_mm"] or (tool.diameter_mm if cycle == "peck" else 0.5 * tool.diameter_mm)
        left = tool.type == "tap" and getattr(tool, "hand", "right") == "left"
        if left:
            ctx.meta["spindle_dir"] = "ccw"
        returns = {"r": 0, "initial": 0}
        first = True
        for group in groups:
            hole0 = group[0][0]
            if first:
                linking.retract_and_move(b, hole0.x, hole0.y, heights)
                first = False
            else:
                if b.pos[2] < initial - 1e-9:
                    b.rapid(z=initial)
                b.rapid(x=hole0.x, y=hole0.y)
            r_plane, bottom = group[0][2], group[0][1]
            back = self._return_to(ctx, params["return_to"], group, r_plane, initial)
            returns[back] += 1
            data = {"cycle": ir_cycle, "holes": [[round(h.x, 6), round(h.y, 6), round(h.top, 6)] for h, _, _ in group],
                    "z_bottom": round(bottom, 6), "r_plane": round(r_plane, 6), "retract": back,
                    "initial_z": round(initial, 6), "feed": feeds.feed_mm_min, "rpm": feeds.rpm}
            if cycle in ("peck", "chipbreak"):
                data["peck_mm"] = round(peck, 6)
            if cycle == "chipbreak":
                data["retract_mm"] = params["retract_mm"]
            if dwell:
                data["dwell_s"] = dwell
            if cycle == "tap":
                data["pitch_mm"] = tool.pitch_mm
                if left:
                    data["left_hand"] = True
            if ir_cycle == "fine_bore":
                data["shift_mm"] = params["shift_mm"]
            handle = b.begin_cycle(**data)
            for hole, _, _ in group:
                self._expand(b, cycle, ir_cycle, hole.x, hole.y, bottom, r_plane, initial, back, feeds, peck,
                             params["retract_mm"], dwell, left)
            b.end_cycle(handle)
        if b.pos[2] < heights.clearance - 1e-9:
            b.rapid(z=heights.clearance)

        ctx.meta.update({
            "cycle": cycle, "hole_count": len(rows), "bottom_z": round(min(r[1] for r in rows), 4),
            "holes": [{"at": [round(h.x, 4), round(h.y, 4)], "top_z": round(h.top, 4), "bottom_z": round(z, 4),
                       "r_plane": round(r, 4), "diameter_mm": h.diameter, "through": h.through,
                       "faces": list(h.faces)} for h, z, r in rows],
            "returns": returns,
        })
        if tool.type == "tap":
            # The thread is meant to cut into the wall: the 2.5D gouge check would read it as a gouge.
            ctx.meta["no_gouge_check"] = True
        notes += self._post_notes(ctx, ir_cycle)
        findings = self._findings(ctx, cycle, rows, params)
        if findings:
            ctx.meta["findings"] = findings
        if notes:
            ctx.meta["note"] = "; ".join(notes)
        return b.build()

    def _bottom(self, tool, cycle: str, hole, params, tip: float) -> float:
        """The tool tip's lowest z for ``hole`` (WCS)."""
        from cadgen._internal.cam import drilling

        depth = params["depth_mm"]
        if cycle == "spot":
            if depth is None:
                target = min(hole.diameter, tool.diameter_mm) if hole.diameter else 0.5 * tool.diameter_mm
                depth = drilling.spot_depth(tool, target)
            return hole.top - depth
        if cycle == "tap":
            if depth is not None:
                return hole.top - depth
            if hole.through:
                return hole.bottom - params["breakthrough_mm"] - tip
            return hole.bottom + tool.pitch_mm
        point = tip if cycle not in ("ream", "bore") else 0.0
        if depth is not None:
            return hole.top - depth - (point if params["depth_to"] == "shoulder" else 0.0)
        if hole.through:
            return hole.bottom - params["breakthrough_mm"] - point
        depth_to = params["depth_to"] or ("shoulder" if hole.point_drawn else "tip")
        return hole.bottom - (point if depth_to == "shoulder" else 0.0)

    def _return_to(self, ctx, mode: str, group, r_plane: float, initial: float) -> str:
        """``r`` (G99) or ``initial`` (G98) for one cycle: R when every link at R clears the part (``auto``)."""
        if mode == "r_plane":
            return "r"
        if mode == "initial" or r_plane >= initial - 1e-9 or len(group) == 1:
            return "initial"
        import shapely

        material = ctx.sections.at(r_plane)
        if material.is_empty:
            return "r"
        reach = ctx.tool.radius + 0.5
        for (a, _, _), (c, _, _) in zip(group, group[1:]):
            link = shapely.LineString([(a.x, a.y), (c.x, c.y)]).buffer(reach)
            if link.intersects(material):
                return "initial"
        return "r"

    @staticmethod
    def _expand(b, cycle, ir_cycle, x, y, bottom, r_plane, initial, back, feeds, peck, retract, dwell, left) -> None:
        """One hole's cycle as plain moves, the way the controller runs it, from the current level."""
        f = feeds.feed_mm_min
        rpm = feeds.rpm
        b.rapid(x=x, y=y)
        b.rapid(z=r_plane)
        if cycle in ("peck", "chipbreak"):
            depth = r_plane
            while depth > bottom + 1e-9:
                if depth < r_plane - 1e-9:
                    if cycle == "peck":
                        b.rapid(z=r_plane)
                        b.rapid(z=min(r_plane, depth + PECK_CLEARANCE))
                    else:
                        b.rapid(z=min(r_plane, depth + retract))
                depth = max(bottom, depth - peck)
                b.plunge(z=depth, f=f)
        else:
            b.plunge(z=bottom, f=f)
        if dwell:
            b.dwell(dwell)
        if cycle == "tap":
            b.event("spindle", rpm=rpm, dir="cw" if left else "ccw")
            b.feed(z=r_plane, f=f)
            b.event("spindle", rpm=rpm, dir="ccw" if left else "cw")
        elif ir_cycle in ("bore_stop", "fine_bore"):
            b.event("spindle", dir="off")
            b.rapid(z=r_plane)
            b.event("spindle", rpm=rpm, dir="cw")
        elif ir_cycle in ("ream", "bore", "bore_dwell"):
            b.feed(z=r_plane, f=f)
        else:
            b.rapid(z=r_plane)
        if back == "initial":
            b.rapid(z=initial)

    def _post_notes(self, ctx, ir_cycle: str) -> list[str]:
        """What a post without this canned cycle does instead (it posts the expansion)."""
        from cadgen._internal.cam import posts

        try:
            post = posts.get_post(ctx.machine.post, ctx.machine.kind)
        except CamJobError:
            return []
        data = {"cycle": ir_cycle}
        native = post.emits_cycle(data) if hasattr(post, "emits_cycle") else ir_cycle in post.canned_cycles
        if native:
            return []
        if ir_cycle == "tap":
            return [f"the {post.name} post has no tapping cycle: the tap is posted as moves (feed in at rpm x pitch, "
                    "spindle reverse, feed out), which needs a reversible spindle and a floating tap holder"]
        if ir_cycle == "fine_bore":
            return [f"the {post.name} post has no fine-boring cycle (G76): it is posted as feed in, spindle stop and "
                    "rapid out without the oriented shift, so the bar can mark the wall on the way out"]
        return []

    def _findings(self, ctx, cycle: str, rows, params) -> list[dict]:
        from cadgen._internal.cam import drilling
        from cadgen._internal.cam.checks.base import finding, xyz

        tool = ctx.tool
        out = []

        def item(hole, **numbers):
            at = ctx.wcs.from_wcs([[hole.x, hole.y, hole.top]])[0]
            return {"setup": ctx.setup.id, "operation": ctx.index, "faces": list(hole.faces), "at": xyz(at), **numbers}

        if cycle in ("drill", "dwell", "peck", "chipbreak", "ream", "bore"):
            tolerance = params["size_tolerance_mm"]
            by_size: dict[float, list] = {}
            for hole, _, _ in rows:
                if hole.diameter is not None and abs(tool.diameter_mm - hole.diameter) > tolerance + 1e-9:
                    by_size.setdefault(round(hole.diameter, 4), []).append(hole)
            for size, holes in sorted(by_size.items()):
                over = tool.diameter_mm - size
                count = f"{len(holes)} hole{'s' if len(holes) > 1 else ''}"
                if over > 0:
                    summary = (f"{tool.id} ({tool.plain}) is {abs(over):.3g} mm bigger than the Ø{size:g} of {count}: "
                               "it cuts them oversize")
                    advice = "use a tool the hole's size, or drill a smaller hole first and finish it with a reamer"
                else:
                    summary = (f"{tool.id} ({tool.plain}) is {abs(over):.3g} mm smaller than the Ø{size:g} of {count}: "
                               "it leaves them undersize")
                    advice = ("open them to size with a bigger drill, a reamer, a boring bar or helix_bore; if a smaller "
                              "drill is intended (a pilot, or the tap drill of a thread drawn at its size), keep it")
                    coarse, fine = drilling.METRIC_THREADS.get(round(size, 3), (None, ()))
                    for pitch in (p for p in (coarse, *fine) if p):
                        if abs(tool.diameter_mm - (size - pitch)) <= 0.1:
                            summary += f" ({tool.diameter_mm:g} mm is the tap drill for M{size:g}x{pitch:g})"
                            break
                out.append(finding("drill", "warning", "hole_size", summary, advice,
                                   [item(h, hole_diameter_mm=h.diameter, tool_diameter_mm=tool.diameter_mm)
                                    for h in holes]))
        if cycle == "tap":
            problems: dict[str, list] = {}
            for hole, _, _ in rows:
                for sentence in drilling.tap_problems(tool, hole.diameter):
                    problems.setdefault(sentence, []).append(hole)
            for sentence, holes in problems.items():
                out.append(finding("drill", "warning", "tap_thread", sentence,
                                   "check the tap against the thread the drawing calls for, and the hole it goes in",
                                   [item(h, hole_diameter_mm=h.diameter, pitch_mm=tool.pitch_mm) for h in holes]))
        return out

    def summary(self, ctx, params) -> str:
        cycle = ctx.meta.get("cycle") or params["cycle"] or _DEFAULT_CYCLE.get(ctx.tool.type, "drill")
        count = ctx.meta.get("hole_count", 0)
        name = f" ({ctx.spec.name})" if ctx.spec.name else ""
        return (f"{CYCLES[cycle]['word']}{name} {count} hole{'s' if count != 1 else ''} with {ctx.tool.id} "
                f"{ctx.tool.plain}")


def _holes_selector(raw, where: str):
    if raw == "all":
        return "all"
    if isinstance(raw, dict):
        check_keys(raw, ("diameter_mm", "tolerance_mm"), where)
        if "diameter_mm" not in raw:
            raise CamJobError(f"{where} needs \"diameter_mm\" (the holes' size) or is \"all\"")
        return {"diameter_mm": read_number(raw, "diameter_mm", where),
                "tolerance_mm": read_number(raw, "tolerance_mm", where, default=0.05, minimum=0.0)}
    raise CamJobError(f"{where} is \"all\" or {{\"diameter_mm\": 5, \"tolerance_mm\": 0.05}}, not {raw!r}")
