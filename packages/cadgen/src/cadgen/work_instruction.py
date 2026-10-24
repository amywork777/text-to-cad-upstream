"""Work instructions: ``@work_instruction``, :class:`Instruction` and the process records.

A work instruction is the HOW of one build: the steps a technician follows to put
one specific assembly together, in order, with the values each step needs. An
engineering drawing states the finished state; a process specification states
the company's rules for a kind of work (fastening, bonding, curing, layup,
machining) across every part. A work instruction applies those rules to one
assembly, so the technician holds exactly the steps for this build and not a
hundred pages of spec.

Every value a step prints -- a torque, an adhesive's mix ratio and pot life, a
cure cycle, a ply schedule, a feed and speed -- names where it came from: a
section of a process spec the user supplied (:class:`Spec`), a callout on the
assembly drawing (:class:`Drawing`), or something the user said
(:class:`Stated`). Nothing here has a default value for any of them. A value
nobody stated prints as a captioned blank, ``NOT STATED``, and the run lists it,
so a draft says exactly what engineering still owes the floor. A released
instruction (``status="released"``) refuses to be written with one.

Usage::

    import cadgen
    from pathlib import Path
    from cadgen.work_instruction import work_instruction, Instruction, Spec, Drawing, Torque

    FASTENING = Spec("PS-2001", "Threaded fastener installation", revision="D")
    DWG = Drawing("DWG-1042", revision="B")

    @work_instruction(out="../PDF/bracket_assembly_wi.pdf")
    def bracket_assembly_wi():
        wi = Instruction(Path(__file__).parent / "../STEP/bracket_assembly.step",
                         title="BRACKET ASSEMBLY", number="WI-1042", revision="A", drawing=DWG)
        wi.step("Place the base plate on the fixture", install=["base_plate"])
        wi.step("Fasten the bracket to the base plate", install=["bracket"]).fasten(
            "NAS1352-3-8P screw", qty=4,
            torque=Torque(20, 25, "in-lbf", per=FASTENING.at("4.2, Table 3")))
        return wi

    if __name__ == "__main__":
        bracket_assembly_wi()

Running the script writes one PDF at ``out``: a cover page (documents, parts,
materials, open items) and a page per step, each with a picture of the assembly
as it stands after that step -- parts installed earlier in grey, the step's own
parts tinted, parts still to come left out -- and the fill-ins the floor records
(lot numbers, mix and cure times, stamps).

Like ``@eng_drawing`` this is a document over a document, with no public function
and no CLI: the script is the program. Import discipline: nothing here pulls in
matplotlib or the CAD kernel at module scope.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "work_instruction", "Instruction", "Step",
    "Spec", "Drawing", "Stated", "Source",
    "Torque", "Material", "Adhesive", "Layup", "Cure", "Machining",
    "TORQUE_UNITS", "CAMERAS", "PAGE_SIZES", "STATUSES",
]

TORQUE_UNITS = ("in-lbf", "ft-lbf", "N-m")
CAMERAS = ("iso", "front", "back", "left", "right", "top", "bottom")
PAGE_SIZES = ("A4", "LETTER")
STATUSES = ("draft", "released")
NOT_STATED = "NOT STATED"


def _text(name: str, value, *, required: bool = True) -> str | None:
    """A printed field: a non-blank string, or None where the field may be absent."""
    if value is None:
        if required:
            raise TypeError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{name} must not be blank: leave it out (None) to print it as {NOT_STATED}")
    return value


def _one_of(name: str, value, allowed: Sequence[str]) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")
    return value


# --- where a value comes from ------------------------------------------------


@dataclass(frozen=True)
class Source:
    """Where one value comes from. Made by :meth:`Spec.at`, :meth:`Drawing.at` or
    :class:`Stated`, never directly: ``kind`` is ``spec``, ``drawing`` or ``stated``."""

    kind: str
    document: str
    where: str = ""
    title: str = ""

    def cite(self) -> str:
        if self.kind == "stated":
            return self.document
        return f"{self.document} {self.where}".strip() if self.kind == "spec" else \
            f"{self.document}, {self.where} (drawing callout)"


@dataclass(frozen=True)
class Spec:
    """A company process specification as the user supplied it: its number, title
    and revision. ``spec.at("4.2, Table 3")`` is a :class:`Source` naming the
    section a value was read from."""

    number: str
    title: str
    revision: str

    def __post_init__(self) -> None:
        for name in ("number", "title", "revision"):
            object.__setattr__(self, name, _text(f"Spec {name}", getattr(self, name)))

    @property
    def name(self) -> str:
        return f"{self.number} Rev {self.revision}"

    def at(self, section: str) -> Source:
        return Source("spec", self.name, f"§{_text('Spec.at section', section)}", self.title)


@dataclass(frozen=True)
class Drawing:
    """The assembly drawing. ``drawing.at("note 4")`` is a :class:`Source` for a
    value a drawing callout states -- a deviation from the general spec."""

    number: str
    revision: str
    title: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "number", _text("Drawing number", self.number))
        object.__setattr__(self, "revision", _text("Drawing revision", self.revision))
        object.__setattr__(self, "title", _text("Drawing title", self.title or None, required=False) or "")

    @property
    def name(self) -> str:
        return f"{self.number} Rev {self.revision}"

    def at(self, callout: str) -> Source:
        return Source("drawing", self.name, _text("Drawing.at callout", callout), self.title)


def Stated(by: str, *, on: str) -> Source:  # noqa: N802 - reads as the record it makes
    """A value the user stated themself: who said it and the date (``on``, as
    written, e.g. ``"2026-10-23"``). Use it only for what the person actually
    said; a value read from a document cites that document instead."""
    return Source("stated", f"stated by {_text('Stated by', by)}, {_text('Stated on', on)}")


def _source(owner: str, per) -> Source:
    if not isinstance(per, Source):
        raise TypeError(
            f"{owner} needs per=: where the value comes from -- Spec(...).at(section), "
            "Drawing(...).at(callout) or Stated(by, on=date). A value with no source is not written down."
        )
    return per


# --- process records ---------------------------------------------------------


@dataclass(frozen=True)
class Torque:
    """A torque, ``Torque(20, 25, "in-lbf", per=...)`` for a range or
    ``Torque(30, unit="N-m", per=...)`` for one value. The unit is one of
    :data:`TORQUE_UNITS`; nothing is converted."""

    low: float
    high: float | None = None
    unit: str = ""
    per: Source | None = None

    def __post_init__(self) -> None:
        for name in ("low", "high"):
            value = getattr(self, name)
            if value is None and name == "high":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Torque {name} must be a positive number, got {value!r}")
        if self.high is not None and self.high < self.low:
            raise ValueError(f"Torque high ({self.high}) is below low ({self.low})")
        _one_of("Torque unit", self.unit, TORQUE_UNITS)
        _source("Torque", self.per)

    def text(self) -> str:
        span = _num(self.low) if self.high is None or self.high == self.low else f"{_num(self.low)}–{_num(self.high)}"
        return f"{span} {self.unit}"


def _num(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class _Record:
    """A process record: its fields are printed strings, a required one left out
    prints as NOT STATED. Subclasses name REQUIRED and OPTIONAL."""

    REQUIRED = ()
    OPTIONAL = ()

    def __post_init__(self) -> None:
        kind = type(self).__name__
        object.__setattr__(self, "name", _text(f"{kind} name", self.name))
        for key in self.REQUIRED + self.OPTIONAL:
            object.__setattr__(self, key, _text(f"{kind} {key}", getattr(self, key), required=False))
        _source(kind, self.per)

    def fields(self) -> list[tuple[str, str | None]]:
        """(caption, value) pairs to print; a required field's None is NOT STATED."""
        rows = [(key.replace("_", " "), getattr(self, key)) for key in self.REQUIRED]
        rows += [(key.replace("_", " "), getattr(self, key)) for key in self.OPTIONAL if getattr(self, key)]
        return rows

    def missing(self) -> list[str]:
        return [key.replace("_", " ") for key in self.REQUIRED if getattr(self, key) is None]


@dataclass(frozen=True)
class Material(_Record):
    """A consumable a step uses with no process record of its own: a
    threadlocker, a sealant, a primer. ``note`` is how it is applied, as stated."""

    name: str
    per: Source | None = None
    note: str | None = None
    OPTIONAL = ("note",)


@dataclass(frozen=True)
class Adhesive(_Record):
    """A bonding process record: surface prep, mixing, pot life and cure, each as
    the spec or datasheet states it."""

    name: str
    prep: str | None = None
    mix: str | None = None
    pot_life: str | None = None
    cure: str | None = None
    per: Source | None = None
    REQUIRED = ("prep", "mix", "pot_life", "cure")


@dataclass(frozen=True)
class Layup(_Record):
    """A composite layup: the material and the ply schedule, and debulking where
    the spec calls for it."""

    name: str
    plies: str | None = None
    debulk: str | None = None
    per: Source | None = None
    REQUIRED = ("plies",)
    OPTIONAL = ("debulk",)


@dataclass(frozen=True)
class Cure(_Record):
    """A cure cycle: ramp, hold, pressure and cool-down as the spec states them."""

    name: str
    cycle: str | None = None
    per: Source | None = None
    REQUIRED = ("cycle",)


@dataclass(frozen=True)
class Machining(_Record):
    """A machining operation's cutting data: tool, speed and feed, with coolant
    where the spec states it."""

    name: str
    tool: str | None = None
    speed: str | None = None
    feed: str | None = None
    coolant: str | None = None
    per: Source | None = None
    REQUIRED = ("tool", "speed", "feed")
    OPTIONAL = ("coolant",)


# --- steps -------------------------------------------------------------------

# What the floor writes down for each kind of operation: blanks to fill in, not
# values anyone owes. A NOT STATED field is engineering's; these are the technician's.
RECORDS = {
    "fasten": ("Torque wrench ID", "Cal due"),
    "bond": ("Adhesive lot", "Expiry", "Mixed at", "Pot life ends", "Cure start", "Cure end"),
    "layup": ("Material lot", "Out-time"),
    "cure": ("Oven / autoclave ID", "Start", "End", "Chart no."),
    "machine": ("Machine ID",),
}


@dataclass
class _Op:
    kind: str
    lines: list[tuple[str, str | None, Source | None]]  # (caption, value or None = NOT STATED, source)
    missing: list[str] = field(default_factory=list)
    surfaces: tuple[tuple[str, str], ...] = ()  # (face ref, the leaf occurrence it is on)


class Step:
    """One step: a title, the parts it installs, and its operations in order.
    Made by :meth:`Instruction.step`; every method returns the step, so they chain."""

    def __init__(self, instruction: "Instruction", number: int, title: str, install: tuple[str, ...],
                 camera: str | None, picture: bool) -> None:
        self._instruction = instruction
        self.number = number
        self.title = title
        self.install = install
        self.camera = camera
        self.picture = picture
        self.ops: list[_Op] = []
        self.hold = False

    def _add(self, op: _Op) -> "Step":
        self.ops.append(op)
        return self

    def instruct(self, text: str) -> "Step":
        """A plain instruction, in the words the user gave."""
        return self._add(_Op("instruct", [("", _text("instruct text", text), None)]))

    def fasten(self, hardware: str, *, qty: int | None = None, torque: Torque | None = None,
               locking: Material | None = None, sequence: str | None = None) -> "Step":
        """Install threaded hardware. ``torque=None`` prints NOT STATED: a threaded
        joint with no stated torque is an open item, not a default."""
        hardware = _text("fasten hardware", hardware)
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, int) or qty < 1):
            raise ValueError(f"fasten qty must be a positive integer, got {qty!r}")
        if torque is not None and not isinstance(torque, Torque):
            raise TypeError("fasten torque= takes a Torque(...)")
        if locking is not None and not isinstance(locking, Material):
            raise TypeError("fasten locking= takes a Material(...)")
        lines = [("Hardware", f"{hardware}{f', qty {qty}' if qty else ''}", None),
                 ("Torque", torque.text() if torque else None, torque.per if torque else None)]
        if locking is not None:
            self._instruction._use(locking)
            lines.append(("Locking", locking.name + (f" -- {locking.note}" if locking.note else ""), locking.per))
        if sequence is not None:
            lines.append(("Sequence", _text("fasten sequence", sequence), None))
        return self._add(_Op("fasten", lines, missing=[] if torque else ["torque"]))

    def _record(self, kind: str, record, cls, label: str, surfaces=()) -> "Step":
        if record is None:
            return self._add(_Op(kind, [(label, None, None)], missing=[label.lower()],
                                 surfaces=self._faces(surfaces)))
        if not isinstance(record, cls):
            raise TypeError(f"{kind}() takes a {cls.__name__}(...) or None, got {type(record).__name__}")
        lines = [(label, record.name, record.per)]
        lines += [(caption.capitalize(), value, record.per if value else None) for caption, value in record.fields()]
        if kind in ("bond", "layup"):  # a consumable the kit list carries; a cure or a cut is not
            self._instruction._use(record)
        return self._add(_Op(kind, lines, missing=record.missing(), surfaces=self._faces(surfaces)))

    def bond(self, adhesive: Adhesive | None, *, surfaces: Iterable[str] = ()) -> "Step":
        """Bond with an adhesive. ``surfaces`` are face refs (``#o1.2.f3``) marked
        on the step's picture; ``None`` for the adhesive prints NOT STATED."""
        return self._record("bond", adhesive, Adhesive, "Adhesive", surfaces)

    def layup(self, layup: Layup | None) -> "Step":
        return self._record("layup", layup, Layup, "Material")

    def cure(self, cure: Cure | None) -> "Step":
        return self._record("cure", cure, Cure, "Cure")

    def machine(self, machining: Machining | None, *, surfaces: Iterable[str] = ()) -> "Step":
        return self._record("machine", machining, Machining, "Operation", surfaces)

    def apply(self, material: Material, *, surfaces: Iterable[str] = ()) -> "Step":
        """Apply a consumable (sealant, primer, threadlocker) with no record of its own."""
        if not isinstance(material, Material):
            raise TypeError("apply() takes a Material(...)")
        self._instruction._use(material)
        lines = [("Apply", material.name, material.per)]
        if material.note:
            lines.append(("How", material.note, material.per))
        return self._add(_Op("apply", lines, surfaces=self._faces(surfaces)))

    def _faces(self, refs) -> tuple[tuple[str, str], ...]:
        """Each surface ref resolved on the assembly to exactly one face."""
        if isinstance(refs, (str, bytes)):
            raise TypeError(f"surfaces takes a sequence of face refs, not one string: surfaces=({refs!r},)")
        out = []
        for ref in refs:
            ref = _text("surface ref", ref)
            try:
                found = self._instruction.scene.resolve(ref)
            except Exception as exc:  # noqa: BLE001 - re-raised naming the step
                raise ValueError(f"step {self.number}: {ref} is not on {self._instruction.step_path.name}: {exc}") from exc
            if len(found) != 1 or found[0].kind != "face":
                raise ValueError(f"step {self.number}: surfaces takes face refs such as '#o1.2.f3'; "
                                 f"{ref} names {len(found)} {found[0].kind if found else 'entity'}(s)")
            out.append((found[0].ref, found[0].occurrence_ref))
        return tuple(out)

    def inspect(self, text: str, *, per: Source | None = None) -> "Step":
        """An inspection hold point: the step is not complete until an inspector stamps it."""
        if per is not None:
            _source("inspect", per)
        self.hold = True
        return self._add(_Op("inspect", [("Inspect", _text("inspect text", text), per)]))


class Instruction:
    """The work instruction for one assembly STEP.

    ``status`` is ``draft`` (the default: every page says DRAFT, and NOT STATED
    values and parts no step installs are listed) or ``released`` (either one is
    refused). ``size`` is one of :data:`PAGE_SIZES`, ``camera`` one of
    :data:`CAMERAS` for every step's picture (a step may name its own).
    ``pictures=False`` writes the document with no pictures and needs no browser.
    """

    def __init__(self, step_path: str | Path, *, title: str, number: str, revision: str,
                 part_number: str = "", drawing: Drawing | None = None, author: str = "",
                 status: str = "draft", size: str = "A4", camera: str = "iso", pictures: bool = True) -> None:
        self.step_path = Path(step_path).resolve()
        if self.step_path.suffix.lower() not in (".step", ".stp"):
            raise ValueError(f"Instruction takes an assembly .step, got {str(step_path)!r}")
        if not self.step_path.is_file():
            raise FileNotFoundError(f"no STEP at {self.step_path}: run the assembly's model first")
        self.title = _text("title", title)
        self.number = _text("number", number)
        self.revision = _text("revision", revision)
        self.part_number = _text("part_number", part_number or None, required=False) or ""
        self.author = _text("author", author or None, required=False) or ""
        if drawing is not None and not isinstance(drawing, Drawing):
            raise TypeError("drawing= takes a Drawing(number, revision=...)")
        self.drawing = drawing
        self.status = _one_of("status", status, STATUSES)
        self.size = _one_of("size", size, PAGE_SIZES)
        self.camera = _one_of("camera", camera, CAMERAS)
        self.pictures = bool(pictures)
        self.steps: list[Step] = []
        self.materials: list[_Record] = []
        self._scene = None
        self._installed: dict[str, int] = {}
        self.scene  # read now: a single part, or a file that is no assembly, is refused before any step

    @property
    def scene(self):
        if self._scene is None:
            from cadgen.step_scene import read_scene

            self._scene = read_scene(self.step_path)
            if len(list(self._scene.leaves())) < 2:
                raise TypeError(f"{self.step_path.name} is a single part: a work instruction is for an assembly")
        return self._scene

    def leaves(self) -> list:
        return list(self.scene.leaves())

    def _leaf_refs(self, key: str) -> list[str]:
        """The leaf occurrences a part name or occurrence ref installs."""
        key = _text("install ref", key)
        leaves = self.leaves()
        by_ref = {leaf.ref: leaf for leaf in leaves}
        if key in by_ref:
            return [key]
        if key.startswith("#o"):
            under = [leaf.ref for leaf in leaves if leaf.ref.startswith(key + ".")]
            if under:
                return under
        else:
            named = [leaf.ref for leaf in leaves if leaf.label == key or (leaf.label or "").split(":")[0] == key]
            if named:
                return named
            try:  # a subassembly's label, or a numbered alias of a shared one
                found = self.scene.resolve(key)
            except Exception:  # noqa: BLE001 - not a name the assembly has; refused below with the list
                found = ()
            under = [leaf.ref for sel in found if sel.kind == "occurrence"
                     for leaf in leaves if leaf.ref == sel.ref or leaf.ref.startswith(sel.ref + ".")]
            if under:
                return under
        listing = ", ".join(f"{leaf.ref} {leaf.label or '(unnamed)'}" for leaf in leaves)
        raise KeyError(f"{key!r} is not a part of {self.step_path.name}; its parts are: {listing}")

    def step(self, title: str, *, install: Iterable[str] = (), camera: str | None = None,
             picture: bool = True) -> Step:
        """Add the next step. ``install`` names the parts this step puts in place
        (labels, or occurrence refs such as ``#o1.2``; a label several parts share
        installs every one of them). A part is installed by one step only."""
        if isinstance(install, (str, bytes)):
            raise TypeError(f"install takes a sequence of part names or refs, not one string: install=({install!r},)")
        number = len(self.steps) + 1
        refs: list[str] = []
        for key in install:
            for ref in self._leaf_refs(key):
                if ref in self._installed:
                    raise ValueError(f"step {number} installs {key!r} ({ref}), which step {self._installed[ref]} already installs")
                if ref not in refs:
                    refs.append(ref)
        for ref in refs:
            self._installed[ref] = number
        step = Step(self, number, _text("step title", title), tuple(refs),
                    None if camera is None else _one_of("camera", camera, CAMERAS), bool(picture))
        self.steps.append(step)
        return step

    def _use(self, record) -> None:
        if record not in self.materials:
            self.materials.append(record)

    def open_items(self) -> list[str]:
        """Everything engineering still owes: each NOT STATED value, and each part no step installs."""
        items = []
        for step in self.steps:
            for op in step.ops:
                items += [f"step {step.number} ({op.kind}): {name} not stated" for name in op.missing]
        for leaf in self.leaves():
            if leaf.ref not in self._installed:
                items.append(f"{leaf.ref} {leaf.label or '(unnamed)'}: no step installs it")
        return items

    def documents(self) -> list[tuple[str, str]]:
        """(document, title) for the drawing and every spec a value cites, in first-cited order."""
        seen: dict[str, str] = {}
        if self.drawing is not None:
            seen[self.drawing.name] = self.drawing.title or "Assembly drawing"
        for step in self.steps:
            for op in step.ops:
                for _caption, _value, source in op.lines:
                    if source is not None and source.kind in ("spec", "drawing"):
                        seen.setdefault(source.document, source.title)
        return list(seen.items())


# --- the decorator -----------------------------------------------------------


def work_instruction(func: Callable[..., Any] | None = None, *, out: str | Path | None = None):
    """Declare a work instruction. The function returns an :class:`Instruction`;
    calling it (the script's ``__main__`` does) writes one PDF at ``out``, prints
    every open item, and returns the path written.

    ``out`` is required and relative paths resolve against the script.
    """

    def apply(fn: Callable[..., Any]) -> Callable[..., Any]:
        import inspect

        if out is None:
            raise ValueError(
                f"@work_instruction {fn.__name__} needs out=<path>.pdf: the instruction is that PDF, "
                "and cadgen does not choose where it lands."
            )
        target_spec = Path(out)
        if target_spec.suffix.lower() != ".pdf":
            raise ValueError(f"@work_instruction out= must name a .pdf, got {out!r}")
        script = Path(inspect.getsourcefile(fn) or inspect.getfile(fn)).resolve()

        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> list[Path]:
            wi = fn(*args, **kwargs)
            if not isinstance(wi, Instruction):
                raise TypeError(f"@work_instruction {fn.__name__} must return an Instruction")
            if not wi.steps:
                raise ValueError(f"@work_instruction {fn.__name__} has no steps")
            items = wi.open_items()
            if wi.status == "released" and items:
                raise ValueError(
                    f"@work_instruction {fn.__name__} is released with {len(items)} open item(s); "
                    "state them or keep it a draft:\n  " + "\n  ".join(items)
                )
            from cadgen._internal.work_instruction_pages import write_pdf

            target = target_spec if target_spec.is_absolute() else (script.parent / target_spec).resolve()
            pages = write_pdf(wi, target, open_items=items)
            for item in items:
                print(f"{fn.__name__}: open item: {item}")
            print(f"wrote {target} ({pages} page{'s' if pages != 1 else ''})")
            return [target]

        run.__cadgen_work_instruction__ = True  # type: ignore[attr-defined]
        return run

    return apply(func) if func is not None else apply
