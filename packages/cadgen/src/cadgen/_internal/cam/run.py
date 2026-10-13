"""What the ``cadgen.cam`` verbs do, end to end: :func:`list_features` and :func:`plan_job`.

``plan_job`` is the pipeline: parse the job (and every operation's own keys, before anything heavy) -> read the part
-> build the stock -> per setup: its WCS, heights and sections, then each operation planned in order with the tool
change, spindle and coolant events around it -> simulate the stock -> run the checks -> the verdict -> post each
setup and write the GLB, to temporary names renamed into place only when everything is written. A job that cannot
run (:class:`CamJobError`) answers ``ok: false`` with one error finding and leaves no result GLB and no posted file
at the names it would have written.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

from cadgen._internal.cam.checks.base import finding
from cadgen._internal.cam.job_errors import CamJobError
from cadgen.cli_logging import CliLogger
from cadgen.results import CamFeaturesResult, CamPlanResult

__all__ = ["headline", "list_features", "parse_operations", "plan_job", "plan_setups"]


def job_finding(message: str) -> dict:
    """A job that cannot run, as the one error finding its result carries."""
    return finding("job", "error", "job", message, "the job was refused before anything was planned; nothing was "
                   "written. Change the job (or the --occurrence) as the summary says and plan again")


def list_features(target: Path, *, occurrence: str | None = None) -> CamFeaturesResult:
    from cadgen._internal.cam.features import read_features
    from cadgen._internal.cam.part import read_part

    try:
        part = read_part(Path(target), occurrence=occurrence)
    except CamJobError as exc:
        return CamFeaturesResult(ok=False, document=Path(target), findings=(job_finding(str(exc)),))
    reading = read_features(part)
    low, high = part.bbox
    bbox = {"min": [round(float(v), 4) + 0.0 for v in low], "max": [round(float(v), 4) + 0.0 for v in high],
            "size": [round(float(b - a), 4) + 0.0 for a, b in zip(low, high)]}
    return CamFeaturesResult(ok=True, document=Path(target), occurrence=part.occurrence, bbox_mm=bbox,
                             faces=tuple(reading["faces"]), holes=tuple(reading["holes"]),
                             floors=tuple(reading["floors"]), profiles=tuple(reading["profiles"]))


# --- plan ------------------------------------------------------------------------------------------------

def _duration_words(seconds: float) -> str:
    if seconds < 60:
        return f"{max(1, round(seconds))} s"
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min"
    hours, rest = divmod(seconds, 3600)
    return f"{int(hours)} h {round(rest / 60)} min"


def headline(errors: int, seconds: float, tools: int) -> str:
    """``Ready to cut · 42 min · 3 tools`` or ``2 to fix · 42 min · 3 tools``."""
    head = "Ready to cut" if errors == 0 else f"{errors} to fix"
    return f"{head} · {_duration_words(seconds)} · {tools} tool{'s' if tools != 1 else ''}"


def _output_paths(document: Path, out_dir: Path | None, job, extension: str) -> tuple[Path, dict[str, Path]]:
    folder = Path(out_dir) if out_dir is not None else document.parent
    stem = document.stem
    return folder / f"{stem}.cam.glb", {setup.id: folder / f"{stem}.{setup.id}{extension}" for setup in job.setups}


def _remove_stale(paths) -> None:
    for path in paths:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass


def _refused(document: Path, message: str, timings: dict, stale=()) -> CamPlanResult:
    _remove_stale(stale)
    return CamPlanResult(ok=False, document=document, findings=(job_finding(message),), timings=timings)


def _relative(target: Path, start: Path) -> str:
    try:
        return Path(os.path.relpath(Path(target).resolve(), Path(start).resolve())).as_posix()
    except ValueError:  # another drive on Windows
        return Path(target).resolve().as_posix()


def plan_job(target: Path, *, job, out_dir: Path | None = None, verbose: bool = False) -> CamPlanResult:
    from cadgen._internal.cam import posts as post_registry
    from cadgen._internal.cam.job import parse_job

    logger = CliLogger("cam", verbose=verbose)
    document = Path(target)
    timings: dict[str, float] = {}
    started = time.perf_counter()
    stale: tuple = ()
    try:
        parsed = parse_job(job)
        entry = post_registry.entry_for(parsed.machine.post, parsed.machine.kind)
        glb_path, post_paths = _output_paths(document, out_dir, parsed, entry.extension)
        stale = (glb_path, *post_paths.values())
        operations = parse_operations(parsed)
        post = post_registry.get_post(parsed.machine.post, parsed.machine.kind)
        timings["parse_s"] = round(time.perf_counter() - started, 4)
        return _plan(document, parsed, operations, post, glb_path, post_paths, logger, timings, started)
    except CamJobError as exc:
        timings["total_s"] = round(time.perf_counter() - started, 4)
        logger.debug(f"refused: {exc}")
        return _refused(document, str(exc), timings, stale)


def _plan(document, parsed, operations, post, glb_path, post_paths, logger, timings, started) -> CamPlanResult:
    from cadgen import __version__
    from cadgen._internal.cam import fit
    from cadgen._internal.cam.checks import run_checks
    from cadgen._internal.cam.checks.base import CheckContext
    from cadgen._internal.cam.outputs import line_segments, write_glb
    from cadgen._internal.cam.part import read_part
    from cadgen._internal.cam.posts.base import Program
    from cadgen._internal.cam.stock import build_stock, create_stock_sim

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 4)
        return now

    machine = parsed.machine
    tools = {tool.id: tool for tool in parsed.tools}
    tolerance = parsed.tolerance_mm
    budget = fit.Budget()
    adapted: list[dict] = []
    warnings: list[str] = []
    mark = time.perf_counter()
    with logger.timed("read part"):
        part = read_part(document, sheet_thickness_mm=parsed.stock.thickness_mm)
        stock = build_stock(parsed.stock, part, base_dir=parsed.base_dir)
    mark = lap("part_s", mark)
    logger.debug(f"part {part.occurrence or document.name}: {len(part.triangles)} triangles; stock {stock.kind}")

    setup_plans, op_plans, notes = plan_setups(parsed, operations, part, stock, logger)
    warnings += notes
    mark = lap("plan_s", mark)

    # Times: program time runs on across setups.
    clock = 0.0
    by_index = {op.index: op for op in op_plans}
    for plan in setup_plans:
        plan.t0 = clock
        plan.time_s = plan.toolpath.time_s(machine)
        for op_range in plan.toolpath.ops:
            op = by_index[op_range.index]
            t0, t1 = plan.toolpath.op_times(machine)[op_range.index]
            op.t0, op.t1, op.time_s = clock + t0, clock + t1, t1 - t0
            op.start, op.end = op_range.start, op_range.end
        clock += plan.time_s
    duration = clock

    # Simulate.
    cell, steps = fit.stock_cell(stock, parsed.tools, budget)
    adapted += steps
    sim, steps = create_stock_sim(machine.kind, stock, part, cell_mm=cell, tolerance_mm=tolerance)
    adapted += steps
    length = float(sum(plan.toolpath.lengths().sum() for plan in setup_plans))
    step, steps = fit.sim_step(length, cell, budget)
    adapted += steps
    if hasattr(sim, "step"):
        sim.step = step
    reports = {}
    removed_before = sim.volume()
    with logger.timed("simulate"):
        for plan in setup_plans:
            report = sim.cut(plan.toolpath, tools, plan.wcs)
            reports[plan.setup.id] = report
            if report.skipped and not any(a.get("setup") == plan.setup.id for a in adapted):
                adapted.append({"step": "stock_sim", "setup": plan.setup.id, "words": report.skipped})
    mark = lap("simulate_s", mark)

    ctx = CheckContext(job=parsed, part=part, stock=stock, sim=sim, sim_reports=reports, setups=setup_plans,
                       ops=op_plans, tolerance_mm=tolerance, logger=logger)
    with logger.timed("checks"):
        findings, ran, skipped = run_checks(ctx)
    for op in op_plans:
        if op.meta.get("plunges"):
            warnings.append(f"{op.summary}: plunged straight in {op.meta['plunges']} time(s); the tool must cut at "
                            "its centre (most end mills do; check yours)")
        if op.meta.get("note"):
            warnings.append(f"{op.summary}: {op.meta['note']}")
    mark = lap("checks_s", mark)

    errors = sum(1 for f in findings if f["severity"] == "error")
    warn_count = sum(1 for f in findings if f["severity"] == "warning")
    used_tools = sorted({op.tool.id for op in op_plans if op.tool is not None})
    lite = [{"operation": op.index, "op": op.operation.name, "limits": list(op.operation.limits)}
            for op in op_plans if op.operation.status == "lite"]
    verdict = {"status": "ready" if errors == 0 else "fix", "headline": headline(errors, duration, len(used_tools)),
               "errors": errors, "warnings": warn_count, "duration_s": round(duration, 2), "tools": len(used_tools)}
    if lite:
        verdict["lite"] = lite

    # Post every setup, then the GLB: all to temporary names first.
    rendered = {}
    for k, plan in enumerate(setup_plans):
        program = Program(setup=plan.setup, wcs=plan.wcs, toolpath=plan.toolpath, tools=tools, machine=machine,
                          version=__version__, part=document.name, job_name=parsed.name,
                          material=parsed.material.plain, tolerance_mm=tolerance, clearance_z=plan.heights.clearance,
                          setup_index=k, setup_count=len(setup_plans),
                          notes=tuple(f"lite {entry['op']}: {limit}" for entry in lite for limit in entry["limits"]
                                      if by_index[entry["operation"]].setup == plan.setup.id))
        rendered[plan.setup.id] = post.render(program)
    mark = lap("post_s", mark)

    glb_dir = glb_path.parent
    operations_out = []
    setups_out = []
    for plan in setup_plans:
        ops = []
        for op in [o for o in op_plans if o.setup == plan.setup.id]:
            row = {
                "index": op.index, "setup": op.setup, "op": op.operation.name, "plain": op.operation.plain,
                "family": op.operation.family, "status": op.operation.status,
                "tool": op.tool.id if op.tool else None, "tool_plain": op.tool.plain if op.tool else "",
                "tool_diameter_mm": op.tool.diameter_mm if op.tool else None,
                "rpm": op.feeds.rpm if op.feeds else None, "feed_mm_min": op.feeds.feed_mm_min if op.feeds else None,
                "plunge_mm_min": op.feeds.plunge_mm_min if op.feeds else None,
                "time_s": round(op.time_s, 2), "t0": round(op.t0, 3), "t1": round(op.t1, 3),
                "summary": op.summary + f", {_duration_words(op.time_s)}", "limits": list(op.operation.limits),
                "moves": op.end - op.start,
            }
            if op.spec.faces:
                row["faces"] = list(op.spec.faces)
            if op.spec.name:
                row["name"] = op.spec.name
            if op.feeds is not None and op.feeds.clamped:
                row["clamped"] = list(op.feeds.clamped)
            facts = {k: v for k, v in op.meta.items() if k in ("levels", "passes", "entries", "plunges", "floor_z",
                                                                  "bottom_z", "note", "stock_to_leave")}
            if facts:
                row["facts"] = facts
            ops.append(row)
        operations_out.extend(ops)
        setups_out.append({
            "id": plan.setup.id, "plain": plan.setup.plain, "index": plan.setup.index,
            "orientation": plan.setup.orientation, "wcs": plan.setup.wcs,
            "origin_part_mm": plan.wcs.origin_part_mm, "matrix": plan.wcs.matrix(), "heights": plan.heights.as_dict(),
            "time_s": round(plan.time_s, 2), "t0": round(plan.t0, 3), "t1": round(plan.t0 + plan.time_s, 3),
            "post": _relative(post_paths[plan.setup.id], glb_dir), "operations": ops,
        })
    posts_out = [{"setup": setup_id, "file": str(post_paths[setup_id]), "post": post.name} for setup_id in rendered]
    removed = removed_before - sim.volume()
    cam = {
        "schema": 1, "generator": "cadgen cam", "document": _relative(document, glb_dir),
        "occurrence": part.occurrence, "units": "mm", "verdict": verdict, "machine": machine.as_dict(),
        "material": parsed.material.name, "material_plain": parsed.material.plain, "stock": stock.as_dict(),
        "tools": [tools[t].as_dict() for t in sorted(tools, key=lambda t: tools[t].number)],
        "setups": setups_out, "findings": findings, "adapted": adapted,
        "posts": [{"setup": p["setup"], "file": _relative(Path(p["file"]), glb_dir), "post": p["post"]}
                  for p in posts_out],
        "duration_s": round(duration, 3), "removed_mm3": round(removed, 2),
        "checks": {"ran": ran, "skipped": skipped},
        "safety": "Generated by cadgen; not proven on a machine. Air-cut or single-block it first, and check the work "
                  "offset and every tool length.",
    }
    # Lines for the GLB, in part coordinates on the program clock.
    def segments_at(chord: float) -> int:
        return sum(len(plan.toolpath.sample(chord).points) for plan in setup_plans)

    chord, stride, steps = fit.display_chord(segments_at, tolerance, budget)
    adapted += steps
    cam["adapted"] = adapted
    lines = []
    for plan in setup_plans:
        samples = plan.toolpath.sample(chord, machine=machine)
        samples = dataclasses.replace(samples, points=plan.wcs.from_wcs(samples.points))
        lines += line_segments(samples, setup=plan.setup.id, t_offset=plan.t0, stride=stride)

    temporaries = []
    try:
        suffix = f".tmp-{os.getpid()}"
        glb_tmp = glb_path.with_name(f".{glb_path.name}{suffix}")
        temporaries.append((glb_tmp, glb_path))
        write_glb(glb_tmp, part_mesh=(part.vertices, part.triangles), stock_mesh=sim.mesh(), lines=lines, cam=cam,
                  name=f"{document.stem} cam")
        for setup_id, text in rendered.items():
            final = post_paths[setup_id]
            tmp = final.with_name(f".{final.name}{suffix}")
            temporaries.append((tmp, final))
            tmp.write_text(text, encoding="utf-8", newline="\n")
        for tmp, final in temporaries:
            os.replace(tmp, final)
    except BaseException:
        for tmp, _ in temporaries:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        raise
    lap("write_s", mark)
    timings["total_s"] = round(time.perf_counter() - started, 4)
    logger.debug(f"planned in {timings['total_s']:.2f} s")
    summary = {"duration_s": round(duration, 2), "tools": used_tools, "setups": len(setup_plans),
               "operations": len(op_plans), "machine": machine.kind, "post": post.name,
               "material": parsed.material.name, "stock_cell_mm": round(cell, 4), "removed_mm3": round(removed, 2),
               "checks_ran": ran, "checks_skipped": skipped}
    return CamPlanResult(ok=True, document=document, glb=glb_path, posts=tuple(posts_out), verdict=verdict,
                         summary=summary, operations=tuple(operations_out), findings=tuple(findings),
                         adapted=tuple(adapted), warnings=tuple(warnings), timings=timings)


def parse_operations(parsed) -> dict:
    """Every operation's class and parsed params, by ``(setup id, index)``; refuses before anything heavy runs."""
    from cadgen._internal.cam.operations import get_operation
    from cadgen._internal.cam.operations.base import ParseContext

    operations = {}
    for setup in parsed.setups:
        for spec in setup.operations:
            operation = get_operation(spec.op, spec.where)
            operations[(setup.id, spec.index)] = (operation, operation.parse(spec, ParseContext(parsed, setup)))
    return operations


def plan_setups(parsed, operations, part, stock, logger=None):
    """Plan every setup: ``(setup plans, op plans, warnings)``. Each setup plan carries its WCS toolpath with the
    setup, tool, spindle and coolant events and one op range per operation; op plans carry their feeds, meta and
    summary (times are filled in by the caller)."""
    from cadgen._internal.cam.checks.base import OpPlan, SetupPlan
    from cadgen._internal.cam.geom2d import Sections
    from cadgen._internal.cam.ir import Event, OpRange, Toolpath, ToolpathBuilder, concat
    from cadgen._internal.cam.linking import Heights
    from cadgen._internal.cam.operations.base import PlanContext
    from cadgen._internal.cam.wcs import build_wcs

    logger = logger or CliLogger("cam")
    machine = parsed.machine
    tools = {tool.id: tool for tool in parsed.tools}
    tolerance = parsed.tolerance_mm
    warnings: list[str] = []
    setup_plans: list[SetupPlan] = []
    op_plans: list[OpPlan] = []
    index = 0
    for setup in parsed.setups:
        wcs = build_wcs(setup, stock_points=stock.vertices, part_points=part.vertices)
        part_w = wcs.to_wcs(part.vertices)
        stock_w = wcs.to_wcs(stock.vertices)
        top = float(stock_w[:, 2].max())
        heights = Heights(clearance=top + setup.clearance_mm, retract=top + setup.retract_mm, stock_top=top,
                          part_top=float(part_w[:, 2].max()), stock_bottom=float(stock_w[:, 2].min()),
                          part_bottom=float(part_w[:, 2].min()))
        sections = Sections(part_w, part.triangles)
        plan = SetupPlan(setup=setup, wcs=wcs, heights=heights, sections=sections)
        position = (0.0, 0.0, heights.clearance)
        pieces = []
        current = {"tool": None, "rpm": None, "coolant": "off"}
        for spec in setup.operations:
            operation, params = operations[(setup.id, spec.index)]

            tool = tools.get(spec.tool) if spec.tool else None
            ctx = PlanContext(job=parsed, setup=setup, wcs=wcs, heights=heights, part=part, stock=stock,
                              sections=sections, spec=spec, index=index, tool=tool, start=position,
                              tolerance_mm=tolerance, log=logger.debug)
            with logger.timed(f"plan {setup.id} {spec.index + 1}. {spec.op}"):
                path = operation.plan(ctx, params)
            path = path.with_op(index)
            events = []
            feeds = ctx.chosen_feeds[0] if ctx.chosen_feeds else None
            if tool is not None and tool.id != current["tool"]:
                events.append(("tool", {"tool": tool.id, "number": tool.number, "plain": tool.plain}))
                current["tool"], current["rpm"] = tool.id, None
            if feeds is not None and machine.kind not in ("laser", "plasma", "waterjet", "wire_edm") \
                    and feeds.rpm != current["rpm"]:
                events.append(("spindle", {"rpm": feeds.rpm, "dir": "cw"}))
                current["rpm"] = feeds.rpm
            coolant = spec.coolant or parsed.coolant
            if coolant != current["coolant"]:
                events.append(("coolant", {"mode": coolant}))
                current["coolant"] = coolant
            # Every operation ends at the clearance height, so the next one starts safe.
            tail = ToolpathBuilder(path.positions()[-1], op=index)
            if tail.pos[2] < heights.clearance - 1e-9:
                tail.rapid(z=heights.clearance)
            tail_path = tail.build()
            joined = concat([path, tail_path])
            wrapped = Toolpath(joined.moves, [Event(0, kind, data) for kind, data in events] + list(joined.events),
                               [OpRange(index, setup.id, spec.op, operation.plain, spec.tool, 0, len(joined.moves),
                                        dict(ctx.meta))], start=position, rotary=joined.rotary, lathe=joined.lathe)
            pieces.append(wrapped)
            position = tuple(float(v) for v in wrapped.positions()[-1])
            op_plans.append(OpPlan(index=index, setup=setup.id, spec=spec, operation=operation, tool=tool, feeds=feeds,
                                   params=params, meta=dict(ctx.meta), summary=operation.summary(ctx, params)))
            index += 1
        joined = concat(pieces, start=(0.0, 0.0, heights.clearance))
        end_events = [Event(len(joined.moves), "coolant", {"mode": "off"})] if current["coolant"] != "off" else []
        plan.toolpath = Toolpath(joined.moves, [Event(0, "setup", {"id": setup.id, "wcs": setup.wcs,
                                                                     "plain": setup.plain,
                                                                     "rotary": dict(wcs.rotary_deg)})]
                                 + list(joined.events) + end_events, joined.ops, start=joined.start,
                                 rotary=joined.rotary, lathe=joined.lathe)
        if sections.open_pieces:
            warnings.append(f"setup {setup.id}: {sections.open_pieces} part section(s) did not close; the part's "
                            "tessellation may have a crack there")
        setup_plans.append(plan)
    return setup_plans, op_plans, warnings
