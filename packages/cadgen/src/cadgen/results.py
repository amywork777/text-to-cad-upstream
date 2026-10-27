"""What the robot validators and the ``fea`` verbs return: the JSON line protocol, typed.

Every ``validate`` verb (``cadgen.urdf``, ``cadgen.sdf``, ``cadgen.srdf``) and every ``cadgen.fea``
verb answers with one of these frozen dataclasses rather than a loose dict, so the library call and the generated
CLI carry the SAME shape -- ``--json`` is just ``dataclasses.asdict`` of the value the
library already returned.

Stdlib only, on purpose: importing a result type must never pull in the CAD kernel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "FeaFace",
    "FeaFacesResult",
    "FeaPair",
    "FeaPart",
    "FeaPartsResult",
    "FeaResult",
    "ManufacturingCheckResult",
    "ValidationIssue",
    "ValidationResult",
]


def _display(path: Path | None) -> str:
    """Cwd-relative where that is meaningful, else as given. Messages only."""
    if path is None:
        return "-"
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except (OSError, ValueError):
        return str(path)


@dataclass(frozen=True)
class ValidationIssue:
    """One conformance finding against a robot description.

    ``code`` and ``hint`` carry what the checkers already produce: the skills
    teach fixing findings BY CODE, so dropping the code at the result boundary
    would make the typed result less useful than the dict it replaced.
    """

    severity: str  # "error" | "warning" | "info"
    message: str
    #: The offending element or reference, when the checker knows it.
    element: str | None = None
    #: The checker's stable identifier for this class of finding.
    code: str | None = None
    #: How to fix it, when the checker has something specific to say.
    hint: str | None = None

    def human_line(self) -> str:
        code = f"{self.code}" if self.code else ""
        element = f" at {self.element}" if self.element else ""
        hint = f" Hint: {self.hint}" if self.hint else ""
        return f"{self.severity}: {code}{element}: {self.message}{hint}"


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of one ``validate`` verb."""

    ok: bool
    path: Path
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    #: One line describing what was validated (link/joint counts and so on).
    #: Empty when the document did not parse far enough to describe.
    summary: str = ""

    def human_lines(self) -> list[str]:
        lines = [issue.human_line() for issue in self.issues]
        if self.ok:
            lines.append(self.summary or f"OK {_display(self.path)}")
        else:
            blocking = sum(1 for issue in self.issues if issue.severity == "error")
            lines.append(f"FAILED {_display(self.path)}: {blocking or len(self.issues)} blocking finding(s)")
        return lines


@dataclass(frozen=True)
class FeaFace:
    """One B-rep face of a part, as ``cadgen fea faces`` lists it: the selector a
    study names it by, and enough geometry to pick it from a description."""

    #: The face's ref (``bracket/face 17``), as the viewer copies it.
    ref: str
    area_mm2: float
    #: Centre of mass, mm.
    center_mm: tuple[float, float, float]
    #: ``plane``, ``cylinder``, ``torus``, ... (the underlying surface type).
    surface: str
    #: Unit normal for a plane, else ``None``.
    normal: tuple[float, float, float] | None
    #: ``plane, normal -Z, largest`` -- words an agent can match to a request.
    hint: str


@dataclass(frozen=True)
class FeaFacesResult:
    """The outcome of ``cadgen fea faces``: the faces of one part occurrence."""

    ok: bool
    document: Path
    occurrence: str
    faces: tuple[FeaFace, ...] = ()

    def human_lines(self) -> list[str]:
        lines = [f"{self.occurrence} in {_display(self.document)}: {len(self.faces)} faces"]
        for face in self.faces:
            c = face.center_mm
            lines.append(
                f"  {face.ref:<10} {face.area_mm2:>10.2f} mm^2  at ({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f})  {face.hint}"
            )
        return lines


def _stress_lines(s: dict, safety_factor_text) -> list[str]:
    """The stress lines of a result: one scope per line (the part, then the assembly, then each part)."""
    def factor(value):
        return "n/a" if value is None else safety_factor_text(value)

    if not s.get("weakest_part"):
        return [
            f"max von Mises {s.get('max_von_mises_MPa')} MPa (Gauss {s.get('max_von_mises_gauss_MPa')} MPa), "
            f"yield {s.get('yield_MPa')} MPa, safety factor {factor(s.get('safety_factor'))}"
        ]
    lines = [
        f"weakest part '{s['weakest_part']}': peak {s.get('weakest_part_peak_MPa')} MPa, "
        f"yield {s.get('yield_MPa')} MPa, safety factor {factor(s.get('safety_factor'))}",
        f"assembly peak von Mises {s.get('max_von_mises_MPa')} MPa (Gauss {s.get('max_von_mises_gauss_MPa')} MPa)",
    ]
    for part in s.get("parts", []):
        lines.append(
            f"  '{part['name']}' ({part['material']}): peak {part['peak_MPa']} MPa, yield {part['yield_MPa']} MPa, "
            f"safety factor {factor(part['safety_factor'])}, moves up to {part['max_displacement_mm']} mm"
        )
    return lines


#: Units on a log scale: a check in one says how far over or under its limit it is, not a ratio of the two.
LOG_UNITS = ("dB", "dBA", "dB(A)")


def _check_lines(s: dict) -> list[str]:
    """One line per check the study asked for: what it measured against its limit, and whether it passes.

    A level on a log scale (dB) is judged by its difference from the limit ("4 dB over the 80 dB limit"):
    the ratio of two decibel numbers means nothing.
    """
    def unit(check: dict) -> str:  # " MPa", or nothing for a unitless check (a safety factor)
        return f" {check['unit']}" if check["unit"] else ""

    def line(check: dict) -> str:
        if check["unit"] in LOG_UNITS:
            gap = round(float(check["value"]) - float(check["limit"]), 2)
            where = "at" if gap == 0 else f"{abs(gap):g}{unit(check)} {'over' if gap > 0 else 'under'}"
            return (f"check '{check['label']}': {check['value']:g}{unit(check)}, {where} the {check['limit']:g}{unit(check)} "
                    f"limit, {check['status']}")
        if check.get("kind") == "frequency" and check["unit"] == "Hz":
            return _frequency_line(check)
        if check.get("kind") == "stability":
            return _stability_line(check)
        # A share under 1 % reads "0.00×" to two places: say it is under 1 % of the limit instead.
        share = "under 1% of it" if 0 <= check["ratio"] < 0.01 else f"{check['ratio']:.2f}× it"
        return (f"check '{check['label']}': {check['value']:g}{unit(check)} against a {check['limit']:g}{unit(check)} limit, "
                f"{share}, {check['status']}")

    return [line(check) for check in s.get("checks", [])]


def _stability_line(check: dict) -> str:
    """A rotor's stability by its smallest log decrement against the least it needs:
    "log decrement 0.000552 (1st backward whirl at 8,000 rpm), under the 0.1 it needs, close".

    A log decrement is a least-allowed value, not a limit to stay under: its ratio (the verdict meter's place) is
    no "times the limit" a person reads, so the line says the two numbers and which side it is on.
    """
    need = float(check["limit"])
    head = f"check '{check['label']}': "
    if check.get("undamped"):
        return f"{head}no damping modelled, so no whirl grows or dies away (it needs a log decrement of {need:g}), {check['status']}"
    if check.get("mode") is None:
        return f"{head}no whirl in the speed range, {check['status']}"
    from cadgen._internal.fea.analyses.rotordynamics import rpm_text, whirl_words  # stdlib only

    value = float(check["value"])
    where = "under" if value < need else "at" if value == need else "over"
    return (f"{head}log decrement {value:.3g} ({whirl_words(check)} at {rpm_text(check['rpm'])}), {where} the {need:g} it needs, "
            f"{check['status']}")


def _frequency_line(check: dict) -> str:
    """A frequency check by its distance from the limit, in hertz: "127 Hz, 27 Hz above the 100 Hz minimum".

    A minimum and a band to keep clear of are not ratios a person reads: the margin in hertz is.
    Every number keeps the measured frequency's three significant figures.
    """
    value = float(check["value"])
    decimals = max(0, 2 - math.floor(math.log10(abs(value)))) if value else 0

    def num(number: float) -> str:
        return f"{round(float(number), decimals):g}"

    def hz(number: float) -> str:
        return f"{num(number)} Hz"

    mode = f"mode {check['mode']} at " if check.get("mode") is not None and check.get("avoid_Hz") else ""
    if band := check.get("avoid_Hz"):
        low, high = (float(edge) for edge in band)
        if low <= value <= high:
            where = f"inside the {num(low)}–{hz(high)} band to avoid"
        else:
            side, edge = ("below", low) if value < low else ("above", high)
            where = f"{hz(abs(value - edge))} {side} the {num(low)}–{hz(high)} band to avoid"
    else:
        limit = float(check["limit"])
        gap = value - limit
        where = (f"at the {hz(limit)} minimum" if round(gap, decimals) == 0
                 else f"{hz(abs(gap))} {'above' if gap > 0 else 'below'} the {hz(limit)} minimum")
    return f"check '{check['label']}': {mode}{hz(value)}, {where}, {check['status']}"


@dataclass(frozen=True)
class FeaResult:
    """The outcome of ``cadgen fea solve``: where the results went, and the numbers.

    ``summary`` carries the answer an engineer asks for first (static: max von Mises, nodal and Gauss-point, the
    safety factor, max displacement, the applied-versus-reaction balance) and each check judged (``checks``);
    another ``analysis`` writes its own summary and CLI lines. ``findings`` is what an engineer would say about it,
    errors first, in the KiCad findings' shape; each may carry what it ``measured`` against its limit and the ``fix``
    that makes it pass. ``verdict`` reads them as a CI check does (``cadgen._internal.checklist``), and the lines end
    with them as a checklist. The JSON sidecar holds this whole result plus the study. ``ok`` says the study was
    solved, nothing more: a part that fails every check is still ``ok``.
    """

    ok: bool
    document: Path
    occurrence: str
    #: ``None`` when the study stopped before the solve (``ok`` is false; ``findings`` say why).
    glb: Path | None
    sidecar: Path | None
    vtu: Path | None = None
    summary: dict = field(default_factory=dict)
    mesh: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    findings: tuple[dict, ...] = ()
    #: The analysis that was run (``static`` unless the study named another).
    analysis: str = "static"
    #: The fit-the-budget ladder's steps, in order (``rung``, ``words``, ``accuracy``, ...); empty when none was taken.
    fit: tuple[dict, ...] = ()
    #: The findings read as a CI check reads them, the sidecar's ``verdict`` too: ``status`` ``ready`` (no error) or
    #: ``fix``, the ``headline`` ("Ready to cast · solid in 41 s", "1 to fix · shrinkage hot spot"), and how many
    #: ``errors``, ``warnings`` and ``passed`` checks.
    verdict: dict = field(default_factory=dict)

    def human_lines(self) -> list[str]:
        from cadgen._internal.fea.checks import safety_factor_text  # stdlib only; kept out of module import time

        if not self.ok:
            return [f"not solved: {_display(self.document)}"] + [f"{finding['severity']}: {finding['summary']}" for finding in self.findings]
        s = self.summary
        size = f"{self.mesh.get('elements')} tets, {self.mesh.get('dofs')} DOF, {self.mesh.get('size_mm')} mm elements"
        vtu = f", VTU: {_display(self.vtu)}" if self.vtu else ""
        if self.analysis == "static":
            # Which solver ran: CalculiX when it is installed ("calculix 2.23 (C3D10)"), else the built-in one.
            solver = f"; solver {self.mesh['solver']}" if self.mesh.get("solver") else ""
            lines = [
                f"solved {self.occurrence} of {_display(self.document)}: {size}{solver}",
                *_stress_lines(s, safety_factor_text),
                *_check_lines(s),
                f"max displacement {s.get('max_displacement_mm')} mm at {s.get('max_displacement_at_mm')}",
                f"applied {s.get('applied_force_N')} N, reactions {s.get('reaction_force_N')} N",
                f"wrote GLB: {_display(self.glb)} (deformation x{s.get('deformation_scale')}), sidecar: {_display(self.sidecar)}{vtu}",
            ]
        else:  # another analysis says its own lines (``Analysis.human_lines``)
            from cadgen._internal.fea.analyses import get_analysis  # stdlib only

            lines = [
                f"solved {self.occurrence} of {_display(self.document)} ({self.analysis}): {size}",
                *get_analysis(self.analysis).human_lines(s),
                *_check_lines(s),
                f"wrote GLB: {_display(self.glb)}, sidecar: {_display(self.sidecar)}{vtu}",
            ]
        # One line per fit-the-budget step: what was adapted, and what it may have cost.
        lines += [f"adapted: {step['words']}" + (f" ({step['accuracy']})" if step.get("accuracy") else "") for step in self.fit]
        lines += [f"{finding['severity']}: {finding['summary']}" for finding in self.findings]
        lines += [f"warning: {warning}" for warning in self.warnings]
        from cadgen._internal.checklist import checklist_lines  # stdlib only

        return lines + checklist_lines(self.findings, self.verdict)


@dataclass(frozen=True)
class ManufacturingCheckResult:
    """The outcome of ``cadgen manufacturing check``: the verdict, what was written, and the numbers.

    ``process`` is what the study checked (``casting``, ``molding``, ...). ``verdict`` reads the findings as a CI check
    does: ``status`` ``ready`` (no error) or ``fix``, the ``headline`` ("Ready to cast · solid in 41 s", "1 to fix ·
    shrinkage hot spot"), and how many ``errors``, ``warnings`` and ``passed`` checks. ``findings`` are the process's
    checks, in the KiCad/FEA/CAM shape (``check`` the process, ``severity``, ``type``, ``summary``, ``description``,
    ``items``), each with what it ``measured`` against its limit and the ``fix`` that makes it pass; the run's own
    (``check`` ``fea``) say what it adapted or where it stopped. ``gate_failed`` is true when the verdict fails
    ``fail_on``: the CLI then exits 3, as a failing CI check does; ``ok`` says only that the check ran. ``summary`` is
    the process's numbers, ``limits`` what the simulation leaves out (quote them with its numbers), ``fit`` what the
    run adapted to fit its budget (``rung``, ``words``, ``accuracy``). The sidecar holds all of it and the study.
    """

    ok: bool
    document: Path
    occurrence: str
    process: str
    glb: Path | None
    sidecar: Path | None
    summary: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    findings: tuple[dict, ...] = ()
    gate_failed: bool = False
    #: The severity the caller fails on (``error``, ``warning``), or ``None`` for no gate.
    fail_on: str | None = None
    fit: tuple[dict, ...] = ()
    limits: tuple[str, ...] = ()
    mesh: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def human_lines(self) -> list[str]:
        from cadgen._internal.checklist import checklist_lines  # stdlib only
        from cadgen._internal.manufacturing.processes import REGISTRY, get_process  # stdlib only

        size = f"{self.mesh.get('elements')} tets, {self.mesh.get('size_mm')} mm elements"
        lines = [
            f"checked {self.occurrence} of {_display(self.document)} ({self.process}): {size}",
            *get_process(self.process).human_lines(self.summary),
            f"wrote GLB: {_display(self.glb)}, sidecar: {_display(self.sidecar)}",
        ]
        lines += [f"{REGISTRY[self.process].status}: {limit}" for limit in self.limits]
        lines += [f"adapted: {step['words']}" + (f" ({step['accuracy']})" if step.get("accuracy") else "") for step in self.fit]
        lines += [f"{finding['severity']}: {finding['summary']}" for finding in self.findings]
        lines += [f"warning: {warning}" for warning in self.warnings]
        return lines + checklist_lines(self.findings, self.verdict, fail_on=self.fail_on)


@dataclass(frozen=True)
class FeaPart:
    """One part of an assembly, as ``cadgen fea parts`` lists it."""

    #: The part occurrence's ref (``arm``), or the document's name for an assembly.
    ref: str
    name: str
    volume_mm3: float


@dataclass(frozen=True)
class FeaPair:
    """Two parts that touch or nearly touch, and what a study does with them by default."""

    #: The part names, the smaller part (the one attached) first.
    between: tuple[str, str]
    refs: tuple[str, str]
    #: The area the two faces share, mm^2.
    area_mm2: float
    #: The gap between the faces, mm (0 = touching).
    gap_mm: float
    #: ``bonded`` (glued into one body), ``not_connected`` (too far apart to bond) or
    #: ``overlapping`` (the solids share volume, so the pair is not bonded).
    type: str
    #: The volume the two solids share, mm^3 (``overlapping`` only).
    overlap_mm3: float = 0.0
    #: How deep the solids overlap, mm, for an interference within the tolerance: ``bonded``, the glue closes it.
    interference_mm: float = 0.0


@dataclass(frozen=True)
class FeaPartsResult:
    """The outcome of ``cadgen fea parts``: the parts of an assembly and its touching pairs."""

    ok: bool
    document: Path
    contact_tolerance_mm: float
    parts: tuple[FeaPart, ...] = ()
    pairs: tuple[FeaPair, ...] = ()

    def human_lines(self) -> list[str]:
        overlapping = sum(1 for pair in self.pairs if pair.type == "overlapping")
        near = sum(1 for pair in self.pairs if pair.type == "not_connected")
        touching = (
            f"{len(self.pairs) - overlapping - near} touching pairs"
            + (f", {near} near {'miss' if near == 1 else 'misses'}" if near else "")
            + (f", {overlapping} overlapping" if overlapping else "")
        )
        lines = [f"{_display(self.document)}: {len(self.parts)} parts, {touching}"]
        for part in self.parts:
            lines.append(f"  {part.ref:<8} {part.name}  {part.volume_mm3:.4g} mm^3")
        for pair in self.pairs:
            a, b = pair.between
            if pair.type == "overlapping":
                lines.append(f"{a} ↔ {b} · overlapping · {pair.overlap_mm3:.4g} mm³")
            elif pair.type == "bonded":
                gap = f" · gap {pair.gap_mm:.3g} mm" if pair.gap_mm else ""
                gap += f" · interference {pair.interference_mm:.2g} mm" if pair.interference_mm else ""
                lines.append(f"{a} ↔ {b} · {pair.area_mm2:.4g} mm²{gap} · bonded")
            else:
                lines.append(f"{a} ↔ {b} · gap {pair.gap_mm:.3g} mm · not connected")
        return lines
