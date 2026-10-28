"""The protocol every analysis implements, and the dataclasses it trades in.

Stdlib only at import: numeric work lives inside each analysis's ``solve``, so
study parsing and ``cadgen fea --help`` stay instant. Units are the engine's: mm, N, MPa, tonne/mm^3, s.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol

if TYPE_CHECKING:
    import numpy as np
    from cadgen._internal.fea.materials import Material
    from cadgen._internal.fea.mesh import VolumeMesh

__all__ = [
    "Analysis", "AnalysisBase", "AnalysisResult", "CheckSpec", "FieldSpec", "Inputs", "Scaling", "SolveContext", "Tier",
    "assembly_parts", "by_severity", "finding", "xyz",
]

Tier = Literal[1, 2, 3]
#: How a check's value moves with the load multiple k the viewer's load control sets.
Scaling = Literal["linear", "inverse", "none"]



@dataclass(frozen=True)
class FieldSpec:
    name: str                 # the view's name: "von_mises", "temperature", "mode_shape"
    attribute: str            # GLB attribute: "_VON_MISES", "_TEMPERATURE"
    title: str                # extras.fields[].name: "von Mises stress"
    units: str                # "MPa", "mm", "°C", "W/m²", "", "log10 cycles"
    components: Literal[1, 3] = 1
    attribute_scale: float = 1.0   # stored value * scale = units (a vector in glTF metres: 1000)
    signed: bool = False      # min is the field's own min, not 0 (temperature)


@dataclass(frozen=True)
class CheckSpec:
    kind: str                                  # "frequency"
    keys: frozenset[str]                       # accepted keys, "kind" and "label" included
    parse: Callable[[dict, str], dict]         # (entry, where) -> normalised check; ValueError names the field
    default_label: str                         # "Vibration"
    scaling: Scaling = "linear"
    unique: bool = False                       # at most one per study (stress)


@dataclass(frozen=True)
class Inputs:
    """Base of every analysis's parsed inputs (each analysis subclasses it, frozen)."""
    face_refs: tuple[str, ...]        # every face it names; resolved before meshing
    anchor_refs: tuple[str, ...]      # faces that make the problem well posed (fixtures, fixed T, convection)
    requires_anchor: bool             # static: True; modal: False (free-free allowed); thermal: True


@dataclass
class SolveContext:
    volume: "VolumeMesh"
    materials: "tuple[Material, ...]"      # one per domain; a single part is (material,)
    ordinal_of: dict[str, int]
    log: Callable[[str], None] | None
    automatic: bool                        # the finer re-solve cadgen chose
    study: Any = None                      # the parsed study.Study (material, margin, loads as written)
    assembly: Any = None                   # run's assembly plan (parts, names, materials); None for one part
    part_name: str = ""                    # one part's name in findings (the document's stem)


@dataclass
class AnalysisResult:
    dof_locations: "np.ndarray"            # (M, 3) mm
    vertices: int
    tets: "np.ndarray"
    boundary_quadratic: "np.ndarray"       # (B, 6), or (B, 3) for linear elements
    element_dofs: "np.ndarray"
    # By FieldSpec.name: (M,) or (M, 3).
    fields: dict[str, "np.ndarray"]
    fields_by_part: dict[str, "np.ndarray"] = field(default_factory=dict)  # assembly per-part scalar
    deformation: "np.ndarray | None" = None   # (M, 3) baked into POSITION and written as _DISPLACEMENT
    scalars: dict[str, Any] = field(default_factory=dict)   # unrounded numbers its summary reads
    reactions: list[tuple[float, float, float]] = field(default_factory=list)
    applied: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dofs: int = 0
    solver: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    solved: list[Any] | None = None        # static family: checks.Solved per part (findings read them)


class Analysis(Protocol):
    name: ClassVar[str]
    tier: ClassVar[Tier]
    word: ClassVar[str]                                # "Vibration"
    study_keys: ClassVar[frozenset[str]]               # top-level keys it reads beyond the common ones
    material_needs: ClassVar[frozenset[str]]           # subset of MATERIAL_PROPERTIES (section 8)
    mesh_orders: ClassVar[tuple[int, ...]]             # (2,) by default; impact: (1,); the ladder may switch 2 -> 1
    connection_types: ClassVar[tuple[str, ...]]        # ("bonded", "free"); contact adds "contact"
    fields: ClassVar[tuple[FieldSpec, ...]]
    checks: ClassVar[tuple[CheckSpec, ...]]
    default_checks: ClassVar[tuple[dict, ...]]
    drives: ClassVar[tuple[str, ...]]                  # view drives it allows (section 6.4)
    default_controls: ClassVar[dict[str, dict]]        # what a preset may set when the view declares none

    def parse(self, document: dict) -> Inputs: ...                     # stdlib; ValueError names the field
    def solve(self, ctx: SolveContext, inputs: Inputs) -> AnalysisResult: ...
    def needs_finer(self, result: AnalysisResult, inputs: Inputs, check_results: list[dict]) -> bool: ...
    def judge(self, check: dict, index: int, ctx: SolveContext, result: AnalysisResult, inputs: Inputs) -> dict: ...
    def findings(self, ctx: SolveContext, result: AnalysisResult, inputs: Inputs,
                 check_results: list[dict], *, assembly: bool) -> list[dict]: ...
    def study_echo(self, inputs: Inputs, bare: Callable[[tuple[str, ...]], list[str]]) -> dict: ...
    def summary(self, result: AnalysisResult, inputs: Inputs, check_results: list[dict]) -> dict: ...  # rounded
    def human_lines(self, summary: dict) -> list[str]: ...
    def deformation_scale(self, result: AnalysisResult, bbox_diagonal: float, requested: float | None) -> float | None: ...


class AnalysisBase:
    """The protocol's defaults: a subclass states only what is its own.

    The finer re-solve's hooks (``refined_record``, ``merge_finer``) are the analysis's own."""

    tier: ClassVar[Tier] = 3
    material_needs: ClassVar[frozenset[str]] = frozenset()
    mesh_orders: ClassVar[tuple[int, ...]] = (2,)
    connection_types: ClassVar[tuple[str, ...]] = ("bonded", "free")
    #: What follows the document's stem in the GLB's extras name: "bracket creep".
    extras_word: ClassVar[str] = ""

    def needs_finer(self, result: AnalysisResult, inputs: Inputs, check_results: list[dict]) -> bool:
        return False

    def deformation_scale(self, result: AnalysisResult, bbox_diagonal: float, requested: float | None) -> float | None:
        return None

    def extras_name(self, stem: str) -> str:
        return f"{stem} {self.extras_word}"


def finding(severity: str, kind: str, summary: str, description: str, items=()) -> dict:
    """One entry of a study's findings."""
    return {"check": "fea", "severity": severity, "type": kind, "summary": summary, "description": description,
            "items": list(items)}


_SEVERITY = {"error": 0, "warning": 1, "info": 2}


def by_severity(found: list[dict]) -> list[dict]:
    """Findings errors first, then warnings, then notes; stable within each."""
    return sorted(found, key=lambda item: _SEVERITY[item["severity"]])


def xyz(point, digits: int = 3) -> list[float]:
    """A point as the summary writes it: ``[12.5, 0.0, 3.25]``."""
    return [round(float(c), digits) for c in point]


def assembly_parts(ctx: SolveContext) -> list[dict] | None:
    """An assembly's parts as a summary lists them (ref, name, material); None for one part."""
    if ctx.assembly is None:
        return None
    assembly = ctx.assembly
    return [{"ref": part.ref, "name": name, "material": material.name}
            for part, name, material in zip(assembly.parts, assembly.names, assembly.materials)]
