"""``drill``: drill, peck, chip-break, tap, ream, bore or spot a set of holes along the setup's Z, in canned cycles.

Which holes (exactly one of):

* ``faces``: any face of a hole (``#o1.fN``: a wall, either half of a split one, its counterbore's wall or
  shoulder, its countersink, its floor). Each hole's axis must be the setup's Z (a through hole either way); one
  that is not is refused naming the setup, or the orientation, that would reach it. One along the setup's Z whose
  opening the part covers (a hole in the floor of a cave, under its roof) cannot be planned (``unreachable``).
* ``holes``: ``"all"`` (every hole this setup can reach; the ones along other axes, and the covered ones, are left
  and counted in the op's note) or ``{"diameter_mm": 5, "tolerance_mm": 0.05}``.
* ``points``: ``[[x, y], ...]`` in the setup's WCS, with ``depth_mm`` (below each hole's top) and an optional
  ``top_z`` (default: the part's top there, else the stock's).

A hole opens where it opens on the part: a counterbored or countersunk hole's top is the top of its counterbore or
countersink (``cadgen cam features``), so its R plane is over the part, never down in the counterbore.

``cycle`` (default by tool: a drill or flat end mill ``drill``, or ``peck`` when the deepest hole is three diameters or
more; a spot or chamfer tool ``spot``; a tap ``tap``; a reamer ``ream``; a boring bar ``bore``):

=============  =========  ===================================================================================
``drill``      G81        feed to depth, rapid out
``dwell``      G82        feed to depth, dwell ``dwell_s`` (default 0.5), rapid out
``peck``       G83        pecks of ``peck_mm`` (default one diameter), back to R after each (clears chips)
``chipbreak``  G73        pecks of ``peck_mm`` (default half a diameter), back ``retract_mm`` (0.2) after each
``tap``        G84 / G74  feed at rpm x the tap's pitch, reverse, feed out; a left-hand tap (``hand: left``) G74
``ream``       G85 / G89  feed in, feed out; with ``dwell_s`` a dwell at the bottom (G89)
``bore``       G85 / G89 / G86 / G76 by ``bore_mode``: ``feed`` (feed out), ``dwell`` (dwell, feed out), ``stop``
                          (spindle stop, rapid out), ``fine`` (oriented stop, shift ``shift_mm`` (0.1) off the wall
                          along ``shift_xy`` ([1, 0], the setup's plane, made a unit vector), rapid out, shift back)
``spot``       G82        a short spot, ``dwell_s`` (default 0.2) at the bottom: the cone ``spot_diameter_mm`` wide
                          (default the hole's countersink, else its diameter; for points half the tool's), or
                          ``depth_mm`` deep
=============  =========  ===================================================================================

Depth: a through hole goes ``breakthrough_mm`` (default 1) past its exit with the full diameter, so the tip goes
the point's length further; a blind hole stops its tip on the floor (``depth_to: "tip"``) or its full diameter
there (``"shoulder"``; the default when the model draws a drill point below the floor). A blind hole's deepest
point (the tip of its drawn point, else its floor) is a hard floor: a tool whose point is longer than the drawn one
stops its tip there, and a ``depth_mm`` past it is refused (``too_deep``). A tap stops a pitch above a blind hole's
floor and runs three pitches of lead past a through hole's exit. ``depth_mm`` overrides any of it.

Each hole is fed from its R plane (the setup's ``retract_mm`` over the hole's top; holes at the part's top start
from over the stock); between holes the tool returns to R when every link at that height clears the part
(``return_to``: ``auto``, ``r_plane``, ``initial``), else to the initial level over the stock. Holes are visited
nearest-first, then improved by 2-opt (``order``: ``shortest``, or ``given``); runs of holes with one depth and
one R plane are one cycle event, so posts emit G8x blocks or the expansion.

What it refuses to plan (:class:`~cadgen._internal.cam.job_errors.PlanError`, an error finding on the operation): a
named hole the tool is bigger than (a drill, reamer, boring bar or flat more than ``size_tolerance_mm`` over its
diameter, a tap whose tap drill is more than 0.15 mm over it: ``tool_too_large``), a spot wider than the spot drill
(``tool_too_small``), a covered hole (``unreachable``), a depth past a blind hole's bottom (``too_deep``) and a fine
bore's shift of a hole's radius or more (``gouge``). ``holes`` leaves the holes the tool does not suit out, says so
in the note, and is ``empty_operation`` when none is left.

Its own findings (warnings): a tool more than ``size_tolerance_mm`` (default 0.05) under the hole's diameter
(``hole_size``), a tap whose pitch is not its thread's or whose hole is not drawn for it (``tap_thread``), a blind
hole whose floor the tool's full diameter does not reach (a flat floor or a short drawn point, ``hole_floor``).
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError, PlanError, check_keys, choice, number_list, read_number
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
#: A spot's pause at the bottom when the job gives none (s): it cleans up the cone (G82).
SPOT_DWELL_S = 0.2
#: How far under a tap's tap drill (its size less one pitch) a hole may be drawn, mm: tap drill charts round (M8's
#: 6.8 for 8 - 1.25).
TAP_SIZE_TOLERANCE = 0.15


class DrillOp(Operation):
    name = "drill"
    plain = "Drill"
    family = "2.5D milling"
    machines = MILLS
    status = "full"
    keys = ("cycle", "holes", "points", "depth_mm", "top_z", "depth_to", "breakthrough_mm", "peck_mm", "retract_mm",
            "dwell_s", "bore_mode", "shift_mm", "shift_xy", "spot_diameter_mm", "return_to", "order",
            "size_tolerance_mm")
    common_keys = ("feed", "speed")
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
            raise CamJobError(f"{where}: a drill names its holes one way: \"faces\" (hole walls), \"holes\" "
                              "(\"all\" or {\"diameter_mm\": 5}) or \"points\" ([[x, y], ...] with \"depth_mm\")"
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
                plural = "s" if len(cycles) > 1 else ""
                raise CamJobError(f"{where}.{key} is for the {' and '.join(cycles)} cycle{plural}; this one is {known}")

        only("peck_mm", ("peck", "chipbreak"))
        only("retract_mm", ("chipbreak",))
        only("dwell_s", ("dwell", "spot", "tap", "ream", "bore"))
        only("bore_mode", ("bore",))
        only("shift_mm", ("bore",))
        only("shift_xy", ("bore",))
        only("spot_diameter_mm", ("spot",))
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
            "shift_xy": _shift_xy(extra["shift_xy"], f"{where}.shift_xy") if "shift_xy" in extra else (1.0, 0.0),
            "spot_diameter_mm": read_number(extra, "spot_diameter_mm", where),
            "return_to": choice(extra.get("return_to", "auto"), ("auto", "r_plane", "initial"), f"{where}.return_to"),
            "order": choice(extra.get("order", "shortest"), ("shortest", "given"), f"{where}.order"),
            "size_tolerance_mm": read_number(extra, "size_tolerance_mm", where, default=0.05),
        }
        for key in ("shift_mm", "shift_xy"):
            if key in extra and params["bore_mode"] != "fine":
                raise CamJobError(f"{where}.{key} is for \"bore_mode\": \"fine\" (G76); this bore is "
                                  f"{params['bore_mode']}")
        spot = params["spot_diameter_mm"]
        if spot is not None:
            if params["depth_mm"] is not None:
                raise CamJobError(f"{where}: give spot_diameter_mm (how wide the spot is at the hole's top) or "
                                  "depth_mm (how deep below it), not both")
            if spot > tool.diameter_mm + 1e-9:
                raise CamJobError(f"{where}.spot_diameter_mm: a Ø{spot:g} spot is wider than {tool.id} "
                                  f"({tool.plain}, Ø{tool.diameter_mm:g}) can make; use a spot of "
                                  f"Ø{tool.diameter_mm:g} or less, or a bigger spot drill")
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
        cycle = params["cycle"] or _DEFAULT_CYCLE[tool.type]
        if params["faces"]:
            holes = drilling.holes_from_faces(ctx, params["faces"], where)
            for hole in holes:
                why = self._unsuited(tool, cycle, hole, params)
                if why is not None:
                    raise PlanError(why[0], f"{where}.faces: {hole.label} {why[1]}")
        elif params["holes"] is not None:
            holes, elsewhere, covered = drilling.holes_matching(ctx, params["holes"], where)
            if elsewhere:
                notes.append(f"{elsewhere} matching hole{'s' if elsewhere > 1 else ''} along another axis "
                             "left for a setup that faces it")
            if covered:
                notes.append(f"{covered} matching hole{'s' if covered > 1 else ''} along this setup's Z left out: the "
                             f"part covers {'their openings' if covered > 1 else 'its opening'}, so no tool reaches "
                             f"{'them' if covered > 1 else 'it'} from here")
            suited, unsuited = [], {}
            for hole in holes:
                why = self._unsuited(tool, cycle, hole, params)
                if why is None:
                    suited.append(hole)
                else:
                    unsuited.setdefault(why[2], []).append(hole)
            for reason, left in unsuited.items():
                sizes = ", ".join(sorted({f"Ø{h.diameter:g}" for h in left}))
                notes.append(f"{len(left)} matching hole{'s' if len(left) > 1 else ''} ({sizes}) left out: {reason}")
            if not suited:
                reasons = "; ".join(f"{len(left)} ({', '.join(sorted({f'Ø{h.diameter:g}' for h in left}))}): {reason}"
                                    for reason, left in unsuited.items())
                raise PlanError("empty_operation", f"{where}.holes: none of the {len(holes)} matching holes this setup "
                                f"reaches suits {tool.id} ({tool.plain}): {reasons}")
            holes = suited
        else:
            holes = drilling.holes_from_points(ctx, params["points"], params["top_z"])
        if params["cycle"] is None and cycle == "drill" and tool.type in ("drill", "flat"):
            deepest = max((h.depth or params["depth_mm"] or 0.0) for h in holes)
            if deepest >= 3.0 * tool.diameter_mm - 1e-9:
                cycle = "peck"
        feeds = ctx.feeds(CYCLES[cycle]["feeds"])
        tip = drilling.tip_length(tool)
        gap = ctx.setup.retract_mm
        initial = heights.retract
        rows = []
        short_of_floor: list[tuple] = []
        for hole in holes:
            bottom, short = self._bottom(tool, cycle, hole, params, tip, where)
            if short is not None:
                short_of_floor.append((hole, short))
            if hole.top >= heights.part_top - 1e-6:
                r_plane = max(hole.top + gap, initial)
            else:
                r_plane = hole.top + gap
            rows.append((hole, bottom, min(r_plane, initial)))
        if cycle == "bore" and params["bore_mode"] == "fine":
            for hole in holes:
                if hole.diameter is not None and params["shift_mm"] >= hole.diameter / 2.0 - 1e-9:
                    raise PlanError("gouge", f"{where}.shift_mm: {params['shift_mm']:g} mm is at least the radius "
                                    f"of {hole.label} (Ø{hole.diameter:g}), so the bar's back runs into the far wall "
                                    "as it shifts; shift it a little more than the bar's clearance in the hole "
                                    "(0.1 mm, say)")
        # Order: nearest first then 2-opt, from where the tool is.
        if params["order"] == "shortest" and len(rows) > 1:
            order, _ = drilling.order_shortest([(h.x, h.y) for h, _, _ in rows], ctx.start[:2],
                                               max_two_opt=drilling.MAX_TWO_OPT)
            if len(rows) > drilling.MAX_TWO_OPT:
                notes.append(f"{len(rows)} holes ordered nearest-first only (2-opt runs up to "
                             f"{drilling.MAX_TWO_OPT} holes)")
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
        if cycle == "spot" and dwell is None:
            dwell = SPOT_DWELL_S
        if cycle == "ream" and dwell:
            ir_cycle = "bore_dwell"            # G89: feed in, dwell, feed out
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
            shift = None
            if ir_cycle == "fine_bore":
                data["shift_mm"] = params["shift_mm"]
                data["shift_xy"] = [round(v, 9) + 0.0 for v in params["shift_xy"]]
                shift = (params["shift_mm"] * params["shift_xy"][0], params["shift_mm"] * params["shift_xy"][1])
            handle = b.begin_cycle(**data)
            for hole, _, _ in group:
                self._expand(b, cycle, ir_cycle, hole.x, hole.y, bottom, r_plane, initial, back, feeds, peck,
                             params["retract_mm"], dwell, left, shift)
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
        solid = self._points_in_solid(ctx, [row for row in rows if row[0].diameter is None])
        if solid:
            # The job asked for these holes where the model has none: said once, loudly, not as a gouge per point.
            ctx.meta["no_gouge_check"] = True
        notes += self._post_notes(ctx, ir_cycle)
        findings = self._findings(ctx, cycle, rows, params)
        findings += self._floor_findings(ctx, short_of_floor, tip)
        if solid:
            from cadgen._internal.cam.checks.base import finding, xyz

            findings.append(finding(
                "drill", "warning", "no_hole_in_model",
                f"{len(solid)} of the points drill{'s' if len(solid) == 1 else ''} where the model has no hole, so the "
                "part as modelled is cut there", "add the holes to the model, or check the points (setup WCS mm)",
                [{"setup": ctx.setup.id, "operation": ctx.index,
                  "at": xyz(ctx.wcs.from_wcs([[h.x, h.y, h.top]])[0])} for h in solid]))
        if findings:
            ctx.meta["findings"] = findings
        if notes:
            ctx.meta["note"] = "; ".join(notes)
        return b.build()

    @staticmethod
    def _points_in_solid(ctx, rows) -> list:
        """The point holes whose axis runs through the part's material just under their top."""
        if not rows:
            return []
        import shapely

        out = []
        for hole, bottom, _ in rows:
            z = hole.top - min(0.25, max(1e-3, (hole.top - bottom) / 2.0))
            material = ctx.sections.at(z)
            if not material.is_empty and material.contains(shapely.Point(hole.x, hole.y)):
                out.append(hole)
        return out

    @staticmethod
    def _unsuited(tool, cycle: str, hole, params) -> tuple[str, str, str] | None:
        """Why ``tool`` cannot cut ``hole`` in ``cycle``: ``(PlanError kind, sentence after the hole's name, the
        reason as a note says it)``, or None. A drill, reamer or boring bar bigger than its hole (past
        ``size_tolerance_mm``) cuts the part; a tap a tap drill too big for the hole; a spot drill a spot it cannot
        make. Smaller tools are warnings (:meth:`_findings`)."""
        if hole.diameter is None:
            return None
        if cycle == "spot":
            if params["depth_mm"] is not None or params["spot_diameter_mm"] is not None:
                return None
            want, what = (hole.countersink, "its countersink") if hole.countersink else (hole.diameter, "its diameter")
            if want > tool.diameter_mm + 1e-9:
                return ("tool_too_small",
                        f"wants a Ø{want:g} spot ({what}), wider than {tool.id} ({tool.plain}) can make; give "
                        f"\"spot_diameter_mm\" (Ø{tool.diameter_mm:g} or less) or \"depth_mm\", or use a bigger spot "
                        "drill",
                        f"{tool.id} cannot make a spot as wide as them")
            return None
        if cycle == "tap":
            drill = tool.diameter_mm - tool.pitch_mm
            if hole.diameter < drill - TAP_SIZE_TOLERANCE - 1e-9:
                return ("tool_too_large",
                        f"is a Ø{hole.diameter:g} hole, {drill - hole.diameter:.3g} mm under {tool.id}'s "
                        f"({tool.plain}) Ø{drill:g} tap drill: the tap would cut the hole's wall away as it goes (or "
                        "break); drill it to the tap drill first, or use the tap its size is drawn for",
                        f"they are smaller than {tool.id}'s Ø{drill:g} tap drill")
            return None
        over = tool.diameter_mm - hole.diameter
        if over > params["size_tolerance_mm"] + 1e-9:
            return ("tool_too_large",
                    f"is a Ø{hole.diameter:g} hole and {tool.id} ({tool.plain}) is {over:.3g} mm bigger, so it would "
                    f"cut the part round it; use a tool the hole's size (within size_tolerance_mm, "
                    f"{params['size_tolerance_mm']:g} mm), or a smaller one and finish it with a reamer or boring bar",
                    f"{tool.id} is bigger than they are")
        return None

    def _bottom(self, tool, cycle: str, hole, params, tip: float, where: str) -> tuple[float, float | None]:
        """The tool tip's lowest z for ``hole`` (WCS), and how far short of a blind hole's floor the tool's full
        diameter ends when it cannot reach it (or None). A blind hole's drawn point (or its flat floor) is a hard
        floor: the tip never goes below the hole's deepest point, and ``depth_mm`` past it is refused."""
        from cadgen._internal.cam import drilling

        depth = params["depth_mm"]
        deepest = hole.deepest
        if cycle == "spot":
            if depth is None:
                if params["spot_diameter_mm"] is not None:
                    target = params["spot_diameter_mm"]
                elif hole.diameter:
                    target = hole.countersink or hole.diameter
                else:
                    target = 0.5 * tool.diameter_mm
                depth = drilling.spot_depth(tool, target)
            if deepest is not None and hole.top - depth < deepest - 1e-6:
                raise PlanError("too_deep", f"{where}: the spot at {hole.label} goes {depth:.3g} mm deep, past the "
                                f"bottom of the hole ({hole.top - deepest:.3g} mm deep); give a smaller "
                                "\"spot_diameter_mm\" or \"depth_mm\"")
            return hole.top - depth, None
        if cycle == "tap":
            if depth is not None:
                if deepest is not None and hole.top - depth < deepest - 1e-6:
                    raise PlanError("too_deep", f"{where}.depth_mm: {depth:g} mm is deeper than {hole.label}, a "
                                    f"blind hole {hole.top - deepest:.3g} mm deep; tap to {hole.depth:.3g} mm or less")
                return hole.top - depth, None
            if hole.through:
                return hole.bottom - params["breakthrough_mm"] - tip, None
            return hole.bottom + tool.pitch_mm, None
        point = tip if cycle not in ("ream", "bore") else 0.0
        shoulder = params["depth_to"] == "shoulder"
        if depth is not None:
            if deepest is not None:
                limit, what = (hole.bottom, "its full diameter") if shoulder else (deepest, "the tool's tip")
                if hole.top - depth < limit - 1e-6:
                    raise PlanError("too_deep", f"{where}.depth_mm: {depth:g} mm puts {what} below the bottom of "
                                    f"{hole.label}, a blind hole {hole.top - limit:.3g} mm deep there; give a "
                                    f"depth_mm of {hole.top - limit:.3g} or less")
            bottom = hole.top - depth - (point if shoulder else 0.0)
            if deepest is not None and bottom < deepest - 1e-9:
                return deepest, deepest + point - hole.bottom
            return bottom, None
        if hole.through:
            return hole.bottom - params["breakthrough_mm"] - point, None
        depth_to = params["depth_to"] or ("shoulder" if hole.point_drawn else "tip")
        bottom = hole.bottom - (point if depth_to == "shoulder" else 0.0)
        bottom = max(bottom, deepest)
        # Where the full diameter ends: short of the floor when the point stops it (a flat floor, a short point).
        short = bottom + point - hole.bottom
        return bottom, (short if short > 1e-6 else None)

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
    def _expand(b, cycle, ir_cycle, x, y, bottom, r_plane, initial, back, feeds, peck, retract, dwell, left,
                shift=None) -> None:
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
        elif ir_cycle == "fine_bore":
            # Oriented stop, the bar shifted off the wall along shift_xy, out, back on the hole's axis.
            b.event("spindle", dir="off", orient=True)
            b.rapid(x=x + shift[0], y=y + shift[1])
            b.rapid(z=r_plane)
            b.rapid(x=x, y=y)
            b.event("spindle", rpm=rpm, dir="cw")
        elif ir_cycle == "bore_stop":
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
        # A tap the post cannot cycle is its refusal (no_post_support), and so is a fine bore on a controller that
        # cannot orient its spindle: those need no note.
        if ir_cycle == "fine_bore":
            return [f"the {post.name} post has no fine-boring cycle (G76) for this shift: it is posted as feed in, an "
                    "oriented spindle stop (M19), the shift off the wall, rapid out and back"]
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
            # A tool bigger than its hole never gets here: it is refused (:meth:`_unsuited`).
            for hole, _, _ in rows:
                if hole.diameter is not None and hole.diameter - tool.diameter_mm > tolerance + 1e-9:
                    by_size.setdefault(round(hole.diameter, 4), []).append(hole)
            for size, holes in sorted(by_size.items()):
                under = size - tool.diameter_mm
                count = f"{len(holes)} hole{'s' if len(holes) > 1 else ''}"
                summary = (f"{tool.id} ({tool.plain}) is {under:.3g} mm smaller than the Ø{size:g} of "
                           f"{count}: it leaves them undersize")
                advice = ("open them to size with a bigger drill, a reamer, a boring bar or helix_bore; if a "
                          "smaller drill is intended (a pilot, or the tap drill of a thread drawn at its size), "
                          "keep it")
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

    def _floor_findings(self, ctx, short_of_floor, tip: float) -> list[dict]:
        """A warning for the blind holes whose floor the tool's full diameter does not reach: a flat floor, or a
        drawn point shorter than the tool's, stops the tip at the hole's deepest point."""
        if not short_of_floor:
            return []
        from cadgen._internal.cam.checks.base import finding, xyz

        tool = ctx.tool
        groups: dict[tuple, list] = {}
        for hole, short in short_of_floor:
            groups.setdefault((round(short, 4), round(hole.point_mm, 4)), []).append(hole)
        out = []
        for (short, point), holes in groups.items():
            count = f"{len(holes)} blind hole{'s' if len(holes) > 1 else ''}"
            what = "a flat floor" if point <= 0 else f"a {point:.3g} mm drawn point"
            out.append(finding(
                "drill", "warning", "hole_floor",
                f"{tool.id}'s full diameter stops {short:.3g} mm short of the floor of {count}",
                f"the hole{'s have' if len(holes) > 1 else ' has'} {what} and {tool.id}'s point is {tip:.3g} mm "
                "long; its tip goes no deeper than the hole, so the corner of the floor is left. Finish it with a "
                "flat end mill or a boring bar if it matters",
                [{"setup": ctx.setup.id, "operation": ctx.index, "faces": list(h.faces),
                  "at": xyz(ctx.wcs.from_wcs([[h.x, h.y, h.top]])[0]), "short_mm": round(short, 4)} for h in holes]))
        return out

    def summary(self, ctx, params) -> str:
        cycle = ctx.meta.get("cycle") or params["cycle"] or _DEFAULT_CYCLE.get(ctx.tool.type, "drill")
        count = ctx.meta.get("hole_count", 0)
        name = f" ({ctx.spec.name})" if ctx.spec.name else ""
        return (f"{CYCLES[cycle]['word']}{name} {count} hole{'s' if count != 1 else ''} with {ctx.tool.id} "
                f"{ctx.tool.plain}")


def _shift_xy(raw, where: str) -> tuple[float, float]:
    """The way a fine bore's bar moves off the wall, ``[x, y]`` in the setup's plane, as a unit vector."""
    x, y = number_list(raw, where, length=2)
    length = math.hypot(x, y)
    if length < 1e-9:
        raise CamJobError(f"{where} is the way the bar moves off the wall, [x, y] in the setup's plane like [1, 0] "
                          "(away from the bar's cutting edge once the spindle is oriented); [0, 0] is no way")
    return (x / length, y / length)


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
