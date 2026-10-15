"""Casting (lite): a casting freezing in its mould, from the pour to fully solid.

The study names the ``alloy`` (:data:`cadgen._internal.fea.foundry.ALLOYS`) and the ``process`` (``sand``,
``investment``, ``permanent_mold``, ``die``), which sets the mould: its temperature, the pour's superheat, and its heat
transfer coefficient h on every outer face (a sand or investment mould's falls as it heats, e / √(π t); a metal
mould's is constant). ``pour_temperature_C``, ``mold_temperature_C`` and ``h_W_m2K`` override them. ``feeders`` are
the faces metal feeds from (gates, risers, a sprue's contact): insulated unless an entry gives ``h_W_m2K``, or held at
``held_C`` while the rest freezes. ``fill_time_s`` is how long the mould takes to fill (estimated from the mass when
left out), ``duration_s`` how long to follow it (until fully solid when left out).

The cavity starts full at the pour temperature; the enthalpy march (:mod:`cadgen._internal.fea.solidification`)
runs on linear tets. It writes the time to fully solid at every node (the default view: the last to freeze is
hottest), temperature and liquid fraction per frame, the Niyama value G / √(cooling rate) near the end of
solidification, and the cooling rate there. Its findings are the founder's: isolated hot spots (shrinkage
porosity), low Niyama, sections that freeze before the mould fills (misrun, cold shut), and Chvorinov's rule as a
hand check of the total time. There are no view checks: a casting's verdict is its findings. Stdlib only at import.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from cadgen._internal.fea.analyses import kinds
from cadgen._internal.fea.analyses.base import (
    AnalysisBase, AnalysisResult, FieldSpec, Inputs, Series, SeriesFrame, SolveContext, finding, frame_attributes,
    max_frames, xyz,
)

__all__ = ["CastingAnalysis", "CastingInputs", "Feeder", "LIMITS"]

LIMITS = (
    "The cavity starts full at the pour temperature: filling is not simulated, and a thin section far from the gate "
    "cools as the metal flows to it, sooner than this says.",
    "The mould is a heat transfer coefficient to its temperature on every face (a sand or investment mould's falls as "
    "it heats), not meshed: its corners and cores do not heat up faster than its flat walls.",
    "No shrinkage-driven flow, gas porosity or microstructure; constant properties, and the liquid fraction falls "
    "straight from liquidus to solidus.",
    "Niyama marks where shrinkage porosity is likely, not how much; a named feeder is taken to stay liquid until the "
    "casting is solid.",
)
#: A section that freezes within this many times the fill time is close: metal stops flowing before it is solid.
MISRUN_CLOSE = 3.0
#: A hot spot must stay liquid this share of the total freezing time after it is cut off, and hold this share of the
#: casting's volume, to be one (shorter or smaller pockets are the mesh's ripples).
POCKET_LIFE, POCKET_VOLUME = 0.03, 0.002
#: Chvorinov's rule and the simulation disagree past this factor: a warning.
HAND_FACTOR = 3.0
#: Hot spots named, at most.
MOST_POCKETS = 5
FEEDER_KEYS = {"faces", "h_W_m2K", "held_C"}
NIYAMA_UNITS = "(°C·s)^½/mm"


@dataclass(frozen=True)
class Feeder:
    faces: tuple[str, ...]
    #: Its heat transfer coefficient to the mould temperature, W/(m² K): 0 (insulated) unless the study gives one.
    h: float = 0.0
    #: Held at this temperature while the rest freezes; ``None`` for not held.
    held_C: float | None = None


@dataclass(frozen=True)
class CastingInputs(Inputs):
    alloy: Any = None
    process: Any = None
    pour_C: float = 0.0
    mold_C: float = 0.0
    #: The study's own constant h, W/(m² K); ``None`` for the process's mould.
    h: float | None = None
    feeders: tuple[Feeder, ...] = ()
    #: The study's fill time, s; ``None`` to estimate it.
    fill_s: float | None = None
    duration_s: float | None = None

    def h_of(self) -> Callable[[float, float], float]:
        """The mould's mean coefficient over a step, W/(m² K)."""
        from cadgen._internal.fea.foundry import mould_h

        if self.h is not None:
            return lambda t0, t1, h=self.h: h
        process = self.process
        return lambda t0, t1: mould_h(process.h, process.effusivity, t0, t1)

    def mould_words(self) -> str:
        """"a sand mould at 25 °C, h falling as it heats (e = 1000 W s^½/(m² K))"."""
        words = f"{self.process.words} at {self.mold_C:g} °C"
        if self.h is not None:
            return f"{words}, h = {self.h:g} W/(m² K) (the study's)"
        if self.process.effusivity is not None:
            return f"{words}, h falling as it heats (e = {self.process.effusivity:g} W s^½/(m² K))"
        return f"{words}, h = {self.process.h:g} W/(m² K)"


def _parse_feeders(document: dict, alloy) -> tuple[Feeder, ...]:
    feeders = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(kinds.entries(document, "feeders", '{"faces": ["#o1.f12"]}')):
        where = f"feeders[{index}]"
        kinds.known(entry, FEEDER_KEYS, where, "a feeder takes faces, and h_W_m2K (its coefficient to the mould; "
                    "insulated, 0, when left out) or held_C (held hot while the rest freezes)")
        faces = kinds.faces(entry, where=where)
        for ref in faces:
            if ref in seen:
                raise ValueError(f"{where}: {ref} is already a feeder in feeders[{seen[ref]}]; name each face once")
            seen[ref] = index
        if "h_W_m2K" in entry and "held_C" in entry:
            raise ValueError(f"{where}: give h_W_m2K or held_C, not both")
        h = 0.0
        if "h_W_m2K" in entry:
            h = kinds.number(entry["h_W_m2K"], where=f"{where}.h_W_m2K")
            if h < 0:
                raise ValueError(f"{where}.h_W_m2K: zero (insulated) or more, got {h:g}")
        held = None
        if "held_C" in entry:
            held = kinds.number(entry["held_C"], where=f"{where}.held_C")
            if held <= alloy.solidus:
                raise ValueError(f"{where}.held_C: {held:g} °C is not above the solidus of {alloy.name} "
                                 f"({alloy.solidus:g} °C): a feeder held there is solid")
        feeders.append(Feeder(faces, h, held))
    return tuple(feeders)


def time_words(seconds: float) -> str:
    from cadgen._internal.fea.analyses.thermal_transient import time_label

    return time_label(seconds)


class CastingAnalysis(AnalysisBase):
    name: ClassVar[str] = "casting"
    word: ClassVar[str] = "Casting"
    extras_word: ClassVar[str] = "casting"
    limits: ClassVar[tuple[str, ...]] = LIMITS
    study_keys: ClassVar[frozenset[str]] = frozenset({
        "alloy", "process", "pour_temperature_C", "mold_temperature_C", "h_W_m2K", "feeders", "fill_time_s",
        "duration_s",
    })
    #: The metal is the study's ``alloy`` (its own table), never a ``material``.
    material_required: ClassVar[bool] = False
    #: Linear tets: their lumped capacity is positive, which the enthalpy march needs.
    mesh_orders: ClassVar[tuple[int, ...]] = (1,)
    fields: ClassVar[tuple[FieldSpec, ...]] = (
        FieldSpec("solidification_time", "_SOLIDIFICATION_TIME", "time to solid", "s", signed=True),
        FieldSpec("temperature", "_TEMPERATURE", "temperature", "°C", signed=True, per_frame=True),
        FieldSpec("liquid_fraction", "_LIQUID_FRACTION", "liquid fraction", "", per_frame=True),
        FieldSpec("niyama", "_NIYAMA", "Niyama criterion", NIYAMA_UNITS),
        FieldSpec("cooling_rate", "_COOLING_RATE", "cooling rate near the solidus", "°C/s"),
    )
    checks: ClassVar[tuple] = ()
    default_checks: ClassVar[tuple[dict, ...]] = ()
    drives: ClassVar[tuple[str, ...]] = ("field", "frame", "threshold")
    default_controls: ClassVar[dict[str, dict]] = {
        "field": {"drives": "field", "type": "enum",
                  "options": ["solidification_time", "temperature", "liquid_fraction", "niyama", "cooling_rate"]},
        "frame": {"drives": "frame", "type": "number", "min": 0.0, "max": None},
    }
    ladder: ClassVar[tuple[str, ...]] = ("iterative", "defeature")
    noun: ClassVar[str] = "this pour"

    # -- parse ---------------------------------------------------------------------------------------

    def parse(self, document: dict) -> CastingInputs:
        from cadgen._internal.fea.foundry import ALLOYS, PROCESSES, lookup_alloy, lookup_process

        if "material" in document:
            raise ValueError(f"study.material: a casting study names its metal with 'alloy', one of {', '.join(ALLOYS)}")
        for key in ("parts", "connections"):
            if key in document:
                raise ValueError(f"study.{key}: a casting study solves one part, the casting; solve one occurrence "
                                 "with --occurrence")
        if "alloy" not in document:
            raise ValueError(f"study.alloy: the casting alloy, one of {', '.join(ALLOYS)}")
        alloy = lookup_alloy(document["alloy"])
        if "process" not in document:
            raise ValueError(f"study.process: how it is cast, one of {', '.join(PROCESSES)}")
        process = lookup_process(document["process"])
        pour = alloy.liquidus + process.superheat_C
        if "pour_temperature_C" in document:
            pour = kinds.number(document["pour_temperature_C"], where="pour_temperature_C")
            if pour <= alloy.liquidus:
                raise ValueError(f"pour_temperature_C: {pour:g} °C is not above the liquidus of {alloy.name} "
                                 f"({alloy.liquidus:g} °C): it would not pour")
        mould = process.mold_C
        if "mold_temperature_C" in document:
            mould = kinds.number(document["mold_temperature_C"], where="mold_temperature_C")
            if mould >= alloy.solidus:
                raise ValueError(f"mold_temperature_C: {mould:g} °C is not below the solidus of {alloy.name} "
                                 f"({alloy.solidus:g} °C): the casting would never freeze")
        elif mould >= alloy.solidus:
            raise ValueError(f"mold_temperature_C: the {process.key} preset's mould ({mould:g} °C) is not below the "
                             f"solidus of {alloy.name} ({alloy.solidus:g} °C); give the mould's own preheat")
        h = None
        if "h_W_m2K" in document:
            h = kinds.number(document["h_W_m2K"], where="h_W_m2K", positive=True)
        feeders = _parse_feeders(document, alloy)
        fill = None
        if "fill_time_s" in document:
            fill = kinds.number(document["fill_time_s"], where="fill_time_s", positive=True)
        duration = None
        if "duration_s" in document:
            duration = kinds.number(document["duration_s"], where="duration_s", positive=True)
        refs = tuple(dict.fromkeys(ref for feeder in feeders for ref in feeder.faces))
        return CastingInputs(refs, (), False, alloy=alloy, process=process, pour_C=pour, mold_C=mould, h=h,
                             feeders=feeders, fill_s=fill, duration_s=duration)

    # -- the ladder ----------------------------------------------------------------------------------

    def estimate(self, ctx: SolveContext, inputs: CastingInputs):
        """A temperature problem solved a few thousand times: about a hundred steps of a few Newton passes, each
        a dozen preconditioned CG iterations (measured on cubes from sand to die)."""
        from cadgen._internal.fea.analyses.thermal import ladder_estimate

        return ladder_estimate(ctx, steps=4000, frames=2 * max_frames(ctx))

    def apply(self, rung, ctx: SolveContext, inputs: CastingInputs):
        from cadgen._internal.fea import fit

        return fit.apply_generic(rung, self, ctx, inputs)

    # -- solve ---------------------------------------------------------------------------------------

    def solve(self, ctx: SolveContext, inputs: CastingInputs) -> AnalysisResult:
        import time

        import numpy as np

        from cadgen._internal.fea import foundry, solidification, timestep
        from cadgen._internal.fea.analyses.thermal import plan_solver, space_result
        from cadgen._internal.fea.analyses.thermal_transient import time_label
        from cadgen._internal.fea.operators import DIRECT_SOLVE_BELOW

        if ctx.assembly is not None:
            raise ValueError("casting: the document holds several parts; a casting study solves one, so name it with "
                             "--occurrence")
        space, volume = ctx.space, ctx.volume
        if space.order != 1:
            raise ValueError("casting: solved on linear tets (mesh.order 1)")
        alloy = inputs.alloy
        started = time.perf_counter()
        ordinals = np.asarray(volume.boundary_ordinal)
        feeder_ordinals = {ctx.ordinal_of[ref] for feeder in inputs.feeders for ref in feeder.faces}
        mould_rows = ~np.isin(ordinals, list(feeder_ordinals))
        h_of = inputs.h_of()
        films = [solidification.Film(space.facets_of_rows(mould_rows), inputs.mold_C, h_of)] if mould_rows.any() else []
        held_dofs, held_after, held_C = [], [], None
        triangles = np.asarray(space.boundary_quadratic)[:, :3]
        for feeder in inputs.feeders:
            rows = np.isin(ordinals, [ctx.ordinal_of[ref] for ref in feeder.faces])
            if feeder.held_C is not None:
                held_dofs.append(np.unique(triangles[rows]))
                held_after.append(solidification.Film(space.facets_of_rows(rows), inputs.mold_C, h_of))
                held_C = feeder.held_C if held_C is None else max(held_C, feeder.held_C)
            elif feeder.h > 0:
                films.append(solidification.Film(space.facets_of_rows(rows), inputs.mold_C,
                                                 lambda t0, t1, h=feeder.h: h))
        held = None
        if held_dofs:
            held = solidification.Held(np.unique(np.concatenate(held_dofs)), float(held_C), held_after)
        nodes = space.dof_locations
        m = solidification.node_volumes(space)
        part_volume = float(m.sum())
        corners = nodes[triangles]
        areas = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)
        cooled = mould_rows.copy()
        for feeder in inputs.feeders:
            if feeder.held_C is None and feeder.h > 0:
                cooled |= np.isin(ordinals, [ctx.ordinal_of[ref] for ref in feeder.faces])
        modulus = part_volume / max(float(areas[cooled].sum()), 1e-12)
        hand = foundry.chvorinov(alloy, inputs.process, pour_C=inputs.pour_C, mold_C=inputs.mold_C, h=inputs.h,
                                 modulus_mm=modulus)
        timings = {"assemble_s": time.perf_counter() - started}
        started = time.perf_counter()
        iterative = plan_solver(ctx) is not None or len(nodes) >= DIRECT_SOLVE_BELOW
        run = solidification.march(
            space, alloy, pour_C=inputs.pour_C, films=films, held=held, first_step_s=hand["estimate_s"] / 1000.0,
            hand_s=hand["estimate_s"], end_s=inputs.duration_s, span_C=inputs.pour_C - inputs.mold_C,
            frames=max_frames(ctx), iterative=iterative, log=ctx.log, limit_s=timestep.time_limit(ctx),
        )
        timings["solve_s"] = time.perf_counter() - started
        if ctx.log:
            ctx.log(f"followed the freezing for {run.end_s:.4g} s in {run.steps} steps in {timings['solve_s']:.1f}s")
        started = time.perf_counter()
        enthalpy = solidification.Enthalpy.of(alloy)
        freeze = run.freeze_s
        feeder_nodes = np.zeros(len(nodes), dtype=bool)
        feeder_rows = np.isin(ordinals, list(feeder_ordinals))
        feeder_nodes[np.unique(triangles[feeder_rows])] = True
        graph = solidification.mesh_graph(space)
        total = float(freeze.max())
        found = solidification.pockets(freeze, graph, m, feeder_nodes, min_life_s=POCKET_LIFE * total,
                                       min_volume_mm3=POCKET_VOLUME * part_volume)
        cut = solidification.sections(space, freeze)
        rows_of = solidification.boundary_facet_rows(space)
        timings["post_s"] = time.perf_counter() - started
        niyama = run.niyama.copy()
        computed = np.isfinite(niyama)
        niyama[~computed] = float(niyama[computed].max()) if computed.any() else 0.0
        rate = np.where(np.isfinite(run.cooling_rate), run.cooling_rate, 0.0)
        temperatures = [state for _, state in run.frames]
        liquids = [enthalpy.liquid(state) for state in temperatures]
        still_liquid = [i for i, state in enumerate(temperatures) if float(state.max()) > enthalpy.solidus]
        default = still_liquid[-1] if still_liquid else 0
        series = Series(kind="time", unit="s", default=default, frames=[
            SeriesFrame(value=round(t, 9), label=time_label(t),
                        attributes=frame_attributes({"temperature": "_TEMPERATURE", "liquid_fraction": "_LIQUID_FRACTION"}, i))
            for i, (t, _) in enumerate(run.frames)
        ])
        mass_kg = alloy.density * part_volume * 1000.0
        fill = inputs.fill_s if inputs.fill_s is not None else inputs.process.fill_estimate(mass_kg)
        warnings = []
        if run.stopped_at is not None:
            warnings.append(timestep.stopped_sentence(time_label(run.stopped_at), "fully solid", timestep.time_limit(ctx)))
        if run.cut_short:
            warnings.append(run.cut_short[0].upper() + run.cut_short[1:])
        result = space_result(
            space,
            {"solidification_time": freeze, "temperature": temperatures[0], "liquid_fraction": liquids[0],
             "niyama": niyama, "cooling_rate": rate},
            series=series, frame_fields={"temperature": temperatures, "liquid_fraction": liquids},
            curves={"liquid_percent": {"x": [round(t, 9) for t in run.curve_t], "x_unit": "s",
                                       "y": [round(v, 6) for v in run.curve_liquid], "y_unit": "%"}},
            solver=run.solver, timings=timings, warnings=list(warnings),
            scalars={"run": run, "pockets": found, "sections": cut, "section_rows": rows_of, "hand": hand,
                     "fill_s": fill, "fill_estimated": inputs.fill_s is None, "mass_kg": mass_kg,
                     "volume_mm3": part_volume, "modulus_mm": modulus, "node_volumes": m, "feeder_nodes": feeder_nodes,
                     "niyama_computed": computed, "graph": graph, "analysis_warnings": warnings},
        )
        return result

    # -- findings ------------------------------------------------------------------------------------

    def findings(self, ctx: SolveContext, result: AnalysisResult, inputs: CastingInputs,
                 check_results: list[dict], *, assembly: bool) -> list[dict]:
        from cadgen._internal.fea.timestep import stopped_finding

        s = result.scalars
        run = s["run"]
        found = []
        if run.stopped_at is not None:
            found.append(stopped_finding(s["analysis_warnings"][0]))
        if run.cut_short:
            found.append(finding("warning", "not_solid", f"Not fully solid at the end: {run.cut_short}",
                                 "the time to solid of the points still liquid is the end of the run, a lower bound"))
        found += self._misrun(ctx, result, inputs)
        found += self._hot_spots(result, inputs)
        found += self._niyama(result, inputs)
        found.append(self._hand_check(result, inputs))
        if not inputs.feeders:
            found.append(finding("info", "no_feeder", "No feeder named: every region that freezes last reads as unfed; "
                                 "name the gate or riser faces as feeders to judge the feeding",
                                 "feeders are the faces metal feeds from while the casting freezes"))
        if inputs.alloy.pure:
            found.append(finding("info", "pure_metal", f"{inputs.alloy.name} freezes at one temperature; it is solved "
                                 "over a one-degree range, and the Niyama value means little for it",
                                 "a pure metal shrinks into a pipe or a centreline cavity where it freezes last: read "
                                 "the hot spots"))
        return found

    def _misrun(self, ctx: SolveContext, result: AnalysisResult, inputs: CastingInputs) -> list[dict]:
        import numpy as np

        s = result.scalars
        cut, rows_of, fill = s["sections"], s["section_rows"], s["fill_s"]
        measured = cut.measured & (cut.thickness > 0)
        if not measured.any():
            return []
        fill_words = (f"about {time_words(fill)}, estimated from its {s['mass_kg'] * 1000:.3g} g"
                      if s["fill_estimated"] else f"{time_words(fill)}, the study's fill_time_s")

        def where(index: int) -> dict:
            row = int(rows_of[index])
            ordinal = int(ctx.volume.boundary_ordinal[row]) if row >= 0 else None
            face = ctx.volume.faces.get(ordinal) if ordinal is not None else None
            return {"text": f"a {cut.thickness[index]:.2g} mm section", "ref": face.ref if face else None,
                    "at": xyz(cut.middle[index])}

        for severity, kind, limit in (("error", "misrun", fill), ("warning", "misrun_risk", MISRUN_CLOSE * fill)):
            risky = np.flatnonzero(measured & (cut.freeze_s < limit))
            if len(risky):
                thinnest = int(risky[np.argmin(cut.thickness[risky])])
                section = f"A {cut.thickness[thinnest]:.2g} mm section at {xyz(cut.middle[thinnest])} mm"
                if kind == "misrun":
                    summary = (f"{section} is solid through at {time_words(cut.freeze_s[thinnest])}, before the mould "
                               f"fills ({fill_words}): a misrun or cold shut is likely there; thicken it, gate closer to "
                               "it, pour hotter or preheat the mould")
                else:
                    summary = (f"{section} is solid through at {time_words(cut.freeze_s[thinnest])}, within "
                               f"{MISRUN_CLOSE:g} times the fill time ({fill_words}): metal stops flowing before it is "
                               "solid, so it may not fill")
                faces = len({int(rows_of[i]) for i in risky})
                return [finding(severity, kind, summary,
                                f"{faces} surface triangle{'s' if faces != 1 else ''}' sections freeze that soon; the "
                                "cavity started full, so the real front, cooling as it flows, freezes sooner still",
                                [where(thinnest)])]
        thinnest = int(np.flatnonzero(measured)[np.argmin(cut.thickness[measured])])
        return [finding("info", "thinnest_section",
                        f"The thinnest section, {cut.thickness[thinnest]:.2g} mm, is solid through at "
                        f"{time_words(cut.freeze_s[thinnest])}, well after the mould fills ({fill_words})",
                        "each face's section is measured along its inward normal; its time is when its middle froze",
                        [where(thinnest)])]

    def _hot_spots(self, result: AnalysisResult, inputs: CastingInputs) -> list[dict]:
        s = result.scalars
        found = []
        nodes = result.dof_locations
        for pocket in s["pockets"][:MOST_POCKETS]:
            size = (6.0 * pocket.volume_mm3 / math.pi) ** (1.0 / 3.0)
            item = {"text": "freezes last here", "ref": None, "at": xyz(nodes[pocket.peak])}
            if pocket.unfed:
                summary = (f"Freezes last at {xyz(nodes[pocket.peak])} mm ({time_words(pocket.freeze_s)}) with no feeder: "
                           f"shrinkage porosity collects there, about {pocket.volume_mm3:.3g} mm³ of metal freezing in "
                           f"its last tenth (a {size:.2g} mm ball); feed it, a riser or the gate on it")
                detail = "the study names no feeder, so nothing feeds the region that freezes last"
            else:
                summary = (f"An isolated hot spot at {xyz(nodes[pocket.peak])} mm: cut off from every feeder at "
                           f"{time_words(pocket.cut_s)} with {pocket.volume_mm3:.3g} mm³ still liquid (a {size:.2g} mm "
                           f"ball), solid at {time_words(pocket.freeze_s)}: shrinkage porosity is likely; feed it, or "
                           "thin it or chill it so it freezes toward a feeder")
                detail = ("it freezes after everything around it, and the metal between it and every feeder froze "
                          "first")
            found.append(finding("warning", "shrinkage_hot_spot", summary, detail, [item]))
        return found

    def _niyama(self, result: AnalysisResult, inputs: CastingInputs) -> list[dict]:
        import numpy as np

        s = result.scalars
        alloy = inputs.alloy
        if alloy.pure:
            return []
        niyama, computed, m = result.fields["niyama"], s["niyama_computed"], s["node_volumes"]
        # Near a feeder the low values are the feeder's own: one ring of nodes around its faces is left out.
        indptr, indices = s["graph"]
        near = s["feeder_nodes"].copy()
        for node in np.flatnonzero(s["feeder_nodes"]):
            near[indices[indptr[node]:indptr[node + 1]]] = True
        judged = computed & ~near
        if not judged.any():
            return []
        lowest = int(np.flatnonzero(judged)[np.argmin(niyama[judged])])
        item = [{"text": "the lowest Niyama", "ref": None, "at": xyz(result.dof_locations[lowest])}]
        if alloy.niyama is None:
            return [finding("info", "niyama_no_threshold",
                            f"No critical Niyama value is published for {alloy.name}: the lowest, "
                            f"{niyama[lowest]:.2g} {NIYAMA_UNITS}, is at {xyz(result.dof_locations[lowest])} mm; compare "
                            "the field with a casting of this alloy known to be sound", "Niyama = G / √(cooling rate) "
                            "near the end of freezing; low where the last liquid is fed by no temperature gradient",
                            item)]
        low = judged & (niyama < alloy.niyama)
        if not low.any():
            return []
        share = float(m[low].sum()) / float(m.sum())
        return [finding("warning", "low_niyama",
                        f"Niyama is under {alloy.niyama:g} {NIYAMA_UNITS} (porosity likely in {alloy.name}) over "
                        f"{share:.1%} of the casting, lowest {niyama[lowest]:.2g} at {xyz(result.dof_locations[lowest])} mm",
                        "Niyama marks where shrinkage porosity is likely, not how much; it is lowest where the casting "
                        "freezes last, so read it with the hot spots", item)]

    def _hand_check(self, result: AnalysisResult, inputs: CastingInputs) -> dict:
        s = result.scalars
        hand, total = s["hand"], float(result.fields["solidification_time"].max())
        ratio = total / hand["estimate_s"] if hand["estimate_s"] > 0 else math.inf
        rule = (f"Chvorinov's rule (B = {hand['B_s_per_mm2']:.3g} s/mm²)" if "B_s_per_mm2" in hand
                else "Chvorinov's rule with the mould contact in series")
        summary = (f"{rule}: {time_words(hand['estimate_s'])} for its V/A of {hand['modulus_mm']:.3g} mm; the "
                   f"simulation's last point freezes at {time_words(total)} ({ratio:.2g} times)")
        if 1.0 / HAND_FACTOR <= ratio <= HAND_FACTOR:
            return finding("info", "hand_check", summary, "a hand estimate from the whole casting's modulus; a thick "
                           "section in a thin part freezes later than the part's average says")
        return finding("warning", "hand_check_far", summary + f": more than {HAND_FACTOR:g} times apart; check the "
                       "alloy, the process and h, and that the part's thick section is not far thicker than its average",
                       "a hand estimate from the whole casting's modulus")

    # -- what is written -----------------------------------------------------------------------------

    def summary(self, result: AnalysisResult, inputs: CastingInputs, check_results: list[dict]) -> dict:
        import numpy as np

        s = result.scalars
        run, cut = s["run"], s["sections"]
        freeze = result.fields["solidification_time"]
        last = int(freeze.argmax())
        measured = cut.measured & (cut.thickness > 0)
        thinnest = int(np.flatnonzero(measured)[np.argmin(cut.thickness[measured])]) if measured.any() else None
        released = run.energy_start - run.energy_end
        computed = s["niyama_computed"]
        summary = {
            "solidification_time_s": round(float(freeze.max()), 6),
            "last_to_freeze_at_mm": xyz(result.dof_locations[last]),
            "first_solid_s": round(float(freeze.min()), 6),
            "fully_solid": bool(run.solid),
            "end_s": round(run.end_s, 6),
            "alloy": inputs.alloy.name,
            "process": inputs.process.key,
            "pour_temperature_C": round(inputs.pour_C, 4),
            "mold_temperature_C": round(inputs.mold_C, 4),
            "mould": inputs.mould_words(),
            "volume_mm3": round(s["volume_mm3"], 4),
            "mass_g": round(s["mass_kg"] * 1000.0, 4),
            "modulus_mm": round(s["modulus_mm"], 4),
            "hand_check": {key: (round(value, 6) if isinstance(value, float) else value) for key, value in s["hand"].items()},
            "fill_time_s": round(s["fill_s"], 6),
            "fill_time_estimated": s["fill_estimated"],
            "hot_spots": [{"at_mm": xyz(result.dof_locations[p.peak]), "freezes_at_s": round(p.freeze_s, 6),
                           "cut_off_at_s": round(p.cut_s, 6), "volume_mm3": round(p.volume_mm3, 4), "unfed": p.unfed}
                          for p in s["pockets"]],
            "thinnest_section_mm": round(float(cut.thickness[thinnest]), 4) if thinnest is not None else None,
            "thinnest_section_solid_s": round(float(cut.freeze_s[thinnest]), 6) if thinnest is not None else None,
            "min_niyama": round(float(result.fields["niyama"][computed].min()), 6) if computed.any() else None,
            "niyama_critical": inputs.alloy.niyama,
            "heat_to_mould_J": round(run.heat_out / 1000.0, 6),
            "heat_from_held_feeders_J": round(run.heat_in / 1000.0, 6),
            "heat_released_J": round(released / 1000.0, 6),
            "energy_balance": round(abs(released - (run.heat_out - run.heat_in)) / max(abs(released), 1e-12), 9),
            "steps": run.steps,
            "smallest_step_s": round(run.smallest_step, 9),
            "largest_step_s": round(run.largest_step, 9),
            "frames": len(run.frames),
            "checks": check_results,
        }
        if run.stopped_at is not None:
            summary["stopped_at_s"] = round(run.stopped_at, 9)
        return summary

    def field_ranges(self, summary: dict, result: AnalysisResult) -> dict[str, tuple[float, float]]:
        fields, frames = result.fields, result.frame_fields

        def span(values) -> tuple[float, float]:
            return float(values.min()), float(values.max())

        return {
            "solidification_time": span(fields["solidification_time"]),
            "temperature": (min(float(t.min()) for t in frames["temperature"]), max(float(t.max()) for t in frames["temperature"])),
            "liquid_fraction": (0.0, 1.0),
            "niyama": span(fields["niyama"]),
            "cooling_rate": span(fields["cooling_rate"]),
        }

    def extras_head(self, summary: dict) -> dict:
        return {}

    def extras_assembly(self, summary: dict) -> dict:
        return {}

    def study_echo(self, inputs: CastingInputs, bare: Callable[[tuple[str, ...]], list[str]]) -> dict:
        echo = {
            # The viewer's "Made of" reads the material's name: the alloy is the casting's material.
            "material": {"name": inputs.alloy.name},
            "alloy": inputs.alloy.as_dict(),
            "process": inputs.process.key,
            "pour_temperature_C": inputs.pour_C,
            "mold_temperature_C": inputs.mold_C,
            "feeders": [{"faces": bare(feeder.faces),
                         **({"held_C": feeder.held_C} if feeder.held_C is not None else {"h_W_m2K": feeder.h})}
                        for feeder in inputs.feeders],
        }
        if inputs.h is not None:
            echo["h_W_m2K"] = inputs.h
        elif inputs.process.effusivity is not None:
            echo["mold_effusivity"] = inputs.process.effusivity
        else:
            echo["h_W_m2K"] = inputs.process.h
        if inputs.fill_s is not None:
            echo["fill_time_s"] = inputs.fill_s
        if inputs.duration_s is not None:
            echo["duration_s"] = inputs.duration_s
        return echo

    def human_lines(self, summary: dict) -> list[str]:
        lines = [
            f"solid in {time_words(summary['solidification_time_s'])}; the last to freeze at "
            f"{summary['last_to_freeze_at_mm']} mm",
            f"{summary['alloy']} poured at {summary['pour_temperature_C']:g} °C into {summary['mould']}",
            f"Chvorinov's rule: {time_words(summary['hand_check']['estimate_s'])} for V/A {summary['modulus_mm']:g} mm",
        ]
        hot = summary["hot_spots"]
        thinnest = summary["thinnest_section_mm"]
        fill = (f"about {time_words(summary['fill_time_s'])} (estimated)" if summary["fill_time_estimated"]
                else time_words(summary["fill_time_s"]))
        lines.append(f"{len(hot)} hot spot{'s' if len(hot) != 1 else ''}" + (
            f"; thinnest section {thinnest:g} mm, solid through at {time_words(summary['thinnest_section_solid_s'])}"
            if thinnest is not None else "") + f"; the mould fills in {fill}")
        return lines
