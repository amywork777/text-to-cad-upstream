"""Parse and validate a CAM job: a closed vocabulary (law 9), frozen dataclasses, one-sentence teaching errors.

The job (spec section 3) is JSON: a file path, inline JSON text, or a dict from a library caller. :func:`parse_job`
returns a :class:`Job`::

    Job(machine: Machine, material: Material, stock: StockSpec, tools: tuple[Tool, ...],
        setups: tuple[Setup, ...], tolerance_mm: float, coolant: str, name: str)

Each :class:`Setup` carries its operations as :class:`OpSpec`: the keys every operation shares, parsed here, and the
operation's own keys left in ``extra`` for the operation's ``parse`` (``operations/base.py``) to validate against
its own closed set. What needs the part (that a face exists, that it is flat) is checked later, against the part.

Every refusal is a :class:`~cadgen._internal.cam.job_errors.CamJobError` naming the path into the job
(``setups[0].operations[2].tool``), what is wrong and the allowed set. Stdlib only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from cadgen._internal.cam import posts as post_registry
from cadgen._internal.cam.job_errors import CamJobError, check_keys, choice, number_list, read_number
from cadgen._internal.cam.operations import entry_for as operation_entry
from cadgen._internal.cam.tools import Tool, parse_tool

__all__ = ["CamJobError", "Fixture", "Job", "Machine", "Material", "OpSpec", "Setup", "StockSpec", "load_job",
           "parse_job", "MACHINE_KINDS", "ORIENTATIONS", "ORIGINS", "COOLANTS"]

MACHINE_KINDS = ("mill", "mill4", "mill5", "lathe", "laser", "plasma", "waterjet", "router", "wire_edm")
#: mill5 kinematics: an A+C trunnion table, or a B+C head over a C table.
KINEMATICS = ("ac_trunnion", "bc_head")
ORIENTATIONS = ("+Z", "-Z", "+X", "-X", "+Y", "-Y")
ORIGINS = ("stock-top-center", "stock-top-corner", "part-top-center")
COOLANTS = ("off", "flood", "mist", "air")
STOCK_KINDS = ("box", "cylinder", "sheet", "from_step")
WORK_OFFSETS = ("G54", "G55", "G56", "G57", "G58", "G59")

JOB_KEYS = ("name", "machine", "material", "stock", "tools", "setups", "tolerance_mm", "coolant")
MACHINE_KEYS = ("kind", "post", "name", "travel_mm", "max_rpm", "max_feed_mm_min", "rapid_mm_min", "tool_change_s",
                "kinematics", "rotary_limits_deg", "diameter_mode", "power_w", "laser_source", "amps", "abrasive")
#: The cutting machines' own keys and the kind each belongs to (their cutting speeds scale with them: feeds.cut_feeds).
CUTTING_MACHINE_KEYS = {"power_w": ("laser",), "laser_source": ("laser",), "amps": ("plasma",),
                        "abrasive": ("waterjet",)}
LASER_SOURCES = ("fiber", "co2", "diode")
MATERIAL_KEYS = ("name", "surface_m_min", "sfm", "chipload_mm", "drill_mm_per_rev", "stepdown_fraction")
SETUP_KEYS = ("id", "name", "orientation", "origin", "fixture", "operations", "wcs", "clearance_mm", "retract_mm")
#: Keys every operation takes; an operation adds its own (its reference page), validated by its ``parse``.
OP_COMMON_KEYS = ("op", "tool", "faces", "region", "feed", "speed", "stepdown_mm", "stepover", "stepover_mm",
                  "stock_to_leave_mm", "coolant", "name")

#: Defaults per machine kind: rapid traverse (mm/min) and tool change time (s), the cycle-time model's inputs.
_RAPID = {"mill": 5000.0, "mill4": 5000.0, "mill5": 8000.0, "router": 10000.0, "lathe": 6000.0, "laser": 12000.0,
          "plasma": 15000.0, "waterjet": 8000.0, "wire_edm": 1000.0}
_TOOL_CHANGE = {"mill": 10.0, "mill4": 10.0, "mill5": 8.0, "router": 30.0, "lathe": 3.0, "laser": 0.0, "plasma": 0.0,
                "waterjet": 0.0, "wire_edm": 60.0}


@dataclass(frozen=True)
class Machine:
    kind: str
    post: str
    name: str = ""
    #: Axis travel in mm: [x, y, z] (a lathe: [x, z]); ``None`` when the job names none (no travel check).
    travel_mm: tuple[float, ...] | None = None
    max_rpm: float | None = None
    max_feed_mm_min: float | None = None
    rapid_mm_min: float = 5000.0
    tool_change_s: float = 10.0
    kinematics: str | None = None
    rotary_limits_deg: dict = field(default_factory=dict)
    #: A lathe's X words are diameters (true) or radii.
    diameter_mode: bool = True
    #: Cutting machines: a laser's power (W) and source (fiber, co2, diode), a plasma's current (A), whether a
    #: waterjet adds abrasive. ``None`` takes the cutting table's reference machine (feeds.cut_feeds).
    power_w: float | None = None
    laser_source: str | None = None
    amps: float | None = None
    abrasive: bool = True

    @property
    def axes(self) -> str:
        """The axes the machine has: ``XYZ``, ``XYZA``, ``XYZAC``/``XYZBC``, ``XZ`` (lathe), ``XY`` (cutting),
        ``XYUV`` (wire EDM)."""
        return {"mill": "XYZ", "router": "XYZ", "mill4": "XYZA", "lathe": "XZ", "laser": "XY", "plasma": "XY",
                "waterjet": "XY", "wire_edm": "XYUV"}.get(self.kind) or (
            "XYZBC" if self.kinematics == "bc_head" else "XYZAC")

    def as_dict(self) -> dict:
        out = {"kind": self.kind, "post": self.post, "axes": self.axes, "rapid_mm_min": self.rapid_mm_min,
               "tool_change_s": self.tool_change_s}
        for key in ("name", "travel_mm", "max_rpm", "max_feed_mm_min", "kinematics"):
            value = getattr(self, key)
            if value not in (None, ""):
                out[key] = list(value) if isinstance(value, tuple) else value
        if self.rotary_limits_deg:
            out["rotary_limits_deg"] = {k: list(v) for k, v in self.rotary_limits_deg.items()}
        if self.kind == "lathe":
            out["diameter_mode"] = self.diameter_mode
        for key in ("power_w", "laser_source", "amps"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.kind == "waterjet":
            out["abrasive"] = self.abrasive
        return out


@dataclass(frozen=True)
class Material:
    """A feeds-table material (``table`` true) or the job's own numbers."""

    name: str
    plain: str
    table: bool
    surface_m_min: float | None = None
    chipload_mm: float | None = None
    drill_mm_per_rev: float | None = None
    stepdown_fraction: float | None = None


@dataclass(frozen=True)
class StockSpec:
    kind: str
    #: Box/sheet: added on each side, ``(x-, x+, y-, y+, z-, z+)`` in mm. A box's z margin goes on top only unless
    #: six numbers are given.
    margin_mm: tuple[float, ...] = (0.0,) * 6
    size_mm: tuple[float, float, float] | None = None
    diameter_mm: float | None = None
    length_mm: float | None = None
    axis: str = "z"
    thickness_mm: float | None = None
    path: str | None = None

    def as_dict(self) -> dict:
        out = {"kind": self.kind}
        for key in ("margin_mm", "size_mm", "diameter_mm", "length_mm", "thickness_mm", "path"):
            value = getattr(self, key)
            if value is not None:
                out[key] = list(value) if isinstance(value, tuple) else value
        if self.kind == "cylinder":
            out["axis"] = self.axis
        return out


@dataclass(frozen=True)
class Fixture:
    """A box keep-out in part coordinates (mm): nothing may move into it."""

    min_mm: tuple[float, float, float]
    max_mm: tuple[float, float, float]
    name: str = ""


@dataclass(frozen=True)
class OpSpec:
    """One operation as the job wrote it: the shared keys parsed, the operation's own keys in ``extra``."""

    op: str
    where: str                    # "setups[0].operations[2]", for the operation's own teaching errors
    index: int                    # its position in the setup
    tool: str | None = None
    faces: tuple[str, ...] = ()
    region: object = None         # the raw value; the operation parses it
    feed: float | None = None     # mm/min override
    speed: float | None = None    # rpm override
    stepdown_mm: float | None = None
    stepover: float | None = None       # a fraction of the tool diameter
    stepover_mm: float | None = None
    stock_to_leave_mm: float = 0.0
    coolant: str | None = None
    name: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Setup:
    id: str
    plain: str
    #: ``+Z`` .. ``-Y``, or a 3+2 tilt ``{"a_deg": .., "c_deg": ..}`` (a dict).
    orientation: object
    #: One of :data:`ORIGINS`, or ``{"xyz": [x, y, z]}`` in part mm.
    origin: object
    operations: tuple[OpSpec, ...]
    wcs: str = "G54"
    clearance_mm: float = 5.0
    retract_mm: float = 2.0
    fixtures: tuple[Fixture, ...] = ()
    index: int = 0

    @property
    def tilted(self) -> bool:
        return isinstance(self.orientation, dict)


@dataclass(frozen=True)
class Job:
    machine: Machine
    material: Material
    stock: StockSpec
    tools: tuple[Tool, ...]
    setups: tuple[Setup, ...]
    tolerance_mm: float = 0.01
    coolant: str = "off"
    name: str = ""
    #: The folder relative paths in the job (``stock.path``) resolve against.
    base_dir: Path | None = None

    def tool(self, tool_id: str) -> Tool:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        raise CamJobError(f"no tool '{tool_id}'; the tools are {', '.join(t.id for t in self.tools)}")


def load_job(job: str | dict | None) -> tuple[dict, Path | None]:
    """The job as a dict, and the folder a job file sits in: a dict as given, inline JSON text, or a path."""
    if job is None:
        raise CamJobError("a plan needs a job: pass --job job.cam.json, or inline JSON like "
                          "'{\"machine\": {\"kind\": \"mill\"}, \"material\": \"aluminum-6061\", ...}'")
    if isinstance(job, dict):
        return job, None
    if not isinstance(job, str):
        raise CamJobError(f"the job must be JSON text, a path to a JSON file, or a dict, not {type(job).__name__}")
    text = job.strip()
    base = None
    if not text.startswith("{"):
        path = Path(text).expanduser()
        if not path.is_file():
            raise CamJobError(f"no job file at {path}; pass a JSON file path or inline JSON")
        text, base = path.read_text(encoding="utf-8"), path.resolve().parent
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CamJobError(f"the job is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from None
    if not isinstance(raw, dict):
        raise CamJobError("the job must be a JSON object with machine, material, stock, tools and setups")
    return raw, base


def parse_job(job: str | dict | None) -> Job:
    raw, base = load_job(job)
    check_keys(raw, JOB_KEYS, "job")
    for key in ("machine", "material", "stock", "tools", "setups"):
        if key not in raw:
            raise CamJobError(f"the job needs \"{key}\"; a job names {', '.join(JOB_KEYS[1:6])}")
    machine = _machine(raw["machine"])
    material = _material(raw["material"])
    stock = _stock(raw["stock"], machine.kind)
    tools_raw = raw["tools"]
    if not isinstance(tools_raw, list) or not tools_raw:
        raise CamJobError("tools must be a non-empty list, like [{\"id\": \"T1\", \"type\": \"flat\", \"diameter_mm\": 6}]")
    tools = tuple(parse_tool(entry, i) for i, entry in enumerate(tools_raw))
    seen: dict[str, int] = {}
    numbers: dict[int, str] = {}
    for tool in tools:
        if tool.id in seen:
            raise CamJobError(f"two tools are called '{tool.id}'; every tool id must be different")
        seen[tool.id] = tool.number
        if tool.number in numbers:
            raise CamJobError(f"tools '{numbers[tool.number]}' and '{tool.id}' both post as T{tool.number}; "
                              "give one a different \"number\"")
        numbers[tool.number] = tool.id
    coolant = choice(raw.get("coolant", "off"), COOLANTS, "coolant")
    setups_raw = raw["setups"]
    if not isinstance(setups_raw, list) or not setups_raw:
        raise CamJobError("setups must be a non-empty list, like [{\"id\": \"top\", \"orientation\": \"+Z\", "
                          "\"operations\": [...]}]")
    setups = tuple(_setup(entry, i, machine, {t.id: t for t in tools}) for i, entry in enumerate(setups_raw))
    ids = [s.id for s in setups]
    if len(set(ids)) != len(ids):
        raise CamJobError(f"setup ids must be different (they name the posted files); got {', '.join(ids)}")
    tolerance = read_number(raw, "tolerance_mm", "job", default=0.01, minimum=0.001, maximum=1.0)
    name = raw.get("name", "")
    if not isinstance(name, str):
        raise CamJobError("job.name must be text")
    return Job(machine=machine, material=material, stock=stock, tools=tools, setups=setups, tolerance_mm=tolerance,
               coolant=coolant, name=name, base_dir=base)


def _machine(raw: object) -> Machine:
    if not isinstance(raw, dict):
        raise CamJobError("machine must be an object like {\"kind\": \"mill\", \"post\": \"grbl\"}")
    check_keys(raw, MACHINE_KEYS, "machine")
    kind = choice(raw.get("kind"), MACHINE_KINDS, "machine.kind")
    post = raw.get("post", post_registry.DEFAULT_POST[kind])
    post_registry.entry_for(post, kind)
    travel = None
    if "travel_mm" in raw:
        travel = number_list(raw["travel_mm"], "machine.travel_mm", length=(2, 3), positive=True)
    kinematics = None
    if "kinematics" in raw:
        if kind != "mill5":
            raise CamJobError("machine.kinematics is for a mill5 (a five-axis mill); remove it for a " + kind)
        kinematics = choice(raw["kinematics"], KINEMATICS, "machine.kinematics")
    elif kind == "mill5":
        kinematics = "ac_trunnion"
    limits = {}
    if "rotary_limits_deg" in raw:
        value = raw["rotary_limits_deg"]
        if not isinstance(value, dict):
            raise CamJobError("machine.rotary_limits_deg must be an object like {\"a\": [-120, 120]}")
        check_keys(value, ("a", "b", "c"), "machine.rotary_limits_deg")
        limits = {axis: number_list(v, f"machine.rotary_limits_deg.{axis}", length=2) for axis, v in value.items()}
    diameter_mode = raw.get("diameter_mode", True)
    if not isinstance(diameter_mode, bool):
        raise CamJobError("machine.diameter_mode must be true or false")
    name = raw.get("name", "")
    if not isinstance(name, str):
        raise CamJobError("machine.name must be text")
    cutting = _cutting_keys(raw, kind)
    return Machine(**cutting,
        kind=kind, post=post, name=name, travel_mm=travel,
        max_rpm=read_number(raw, "max_rpm", "machine"),
        max_feed_mm_min=read_number(raw, "max_feed_mm_min", "machine"),
        rapid_mm_min=read_number(raw, "rapid_mm_min", "machine", default=_RAPID[kind]),
        tool_change_s=read_number(raw, "tool_change_s", "machine", default=_TOOL_CHANGE[kind], minimum=0.0),
        kinematics=kinematics, rotary_limits_deg=limits, diameter_mode=diameter_mode,
    )


def _cutting_keys(raw: dict, kind: str) -> dict:
    """A cutting machine's own keys (:data:`CUTTING_MACHINE_KEYS`), each refused on a machine it does not fit."""
    out: dict = {}
    for key, kinds in CUTTING_MACHINE_KEYS.items():
        if key not in raw:
            continue
        if kind not in kinds:
            raise CamJobError(f"machine.{key} is a {' or '.join(kinds)}'s setting; remove it for a {kind}")
    if "power_w" in raw:
        out["power_w"] = read_number(raw, "power_w", "machine", maximum=100000.0)
    if "laser_source" in raw:
        out["laser_source"] = choice(raw["laser_source"], LASER_SOURCES, "machine.laser_source")
    if "amps" in raw:
        out["amps"] = read_number(raw, "amps", "machine", minimum=10.0, maximum=400.0)
    if "abrasive" in raw:
        if not isinstance(raw["abrasive"], bool):
            raise CamJobError("machine.abrasive must be true (an abrasive jet, for metal and stone) or false (pure "
                              "water, for foam, rubber and soft plastics)")
        out["abrasive"] = raw["abrasive"]
    return out


def _material(raw: object) -> Material:
    from cadgen._internal.cam.feeds import MATERIALS

    if isinstance(raw, str):
        entry = MATERIALS.get(raw)
        if entry is None:
            choice(raw, tuple(MATERIALS), "material")
        return Material(name=raw, plain=entry["plain"], table=True)
    if not isinstance(raw, dict):
        raise CamJobError(f"material must be a name ({', '.join(MATERIALS)}) or an object with "
                          "surface_m_min (or sfm) and chipload_mm")
    check_keys(raw, MATERIAL_KEYS, "material")
    if ("surface_m_min" in raw) == ("sfm" in raw):
        raise CamJobError("material needs one surface speed: surface_m_min (metres a minute) or sfm (feet a minute)")
    if "chipload_mm" not in raw:
        raise CamJobError("material needs chipload_mm, the chip load per tooth used for every milling tool")
    speed = read_number(raw, "surface_m_min", "material") if "surface_m_min" in raw else (
        read_number(raw, "sfm", "material") * 0.3048)
    name = raw.get("name", "custom")
    if not isinstance(name, str):
        raise CamJobError("material.name must be text")
    return Material(name=name, plain=name, table=False, surface_m_min=speed,
                    chipload_mm=read_number(raw, "chipload_mm", "material"),
                    drill_mm_per_rev=read_number(raw, "drill_mm_per_rev", "material"),
                    stepdown_fraction=read_number(raw, "stepdown_fraction", "material", maximum=4.0))


def _margins(value: object, where: str, *, box: bool) -> tuple[float, ...]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < 0:
            raise CamJobError(f"{where} must not be negative")
        m = float(value)
        return (m, m, m, m, 0.0 if box else m, m) if box else (m, m, m, m, 0.0, 0.0)
    numbers = number_list(value, where, length=(2, 3, 6))
    if any(v < 0 for v in numbers):
        raise CamJobError(f"{where} must not be negative")
    if len(numbers) == 6:
        return numbers
    if len(numbers) == 2:
        x, y = numbers
        return (x, x, y, y, 0.0, 0.0)
    x, y, z = numbers
    return (x, x, y, y, 0.0, z)


def _stock(raw: object, kind: str) -> StockSpec:
    if not isinstance(raw, dict):
        raise CamJobError("stock must be an object like {\"kind\": \"box\", \"margin_mm\": [2, 2, 1]}")
    stock_kind = choice(raw.get("kind"), STOCK_KINDS, "stock.kind")
    allowed = {"box": ("kind", "margin_mm", "size_mm"),
               "cylinder": ("kind", "diameter_mm", "length_mm", "axis", "margin_mm"),
               "sheet": ("kind", "thickness_mm", "margin_mm"),
               "from_step": ("kind", "path")}[stock_kind]
    check_keys(raw, allowed, "stock", hint=f"{stock_kind} stock")
    if stock_kind == "box":
        if "margin_mm" in raw and "size_mm" in raw:
            raise CamJobError("stock: give margin_mm or size_mm, not both")
        size = number_list(raw["size_mm"], "stock.size_mm", length=3, positive=True) if "size_mm" in raw else None
        margins = _margins(raw.get("margin_mm", 0.0), "stock.margin_mm", box=True)
        return StockSpec(kind="box", margin_mm=margins, size_mm=size)
    if stock_kind == "cylinder":
        margin = read_number(raw, "margin_mm", "stock", default=0.0, minimum=0.0)
        return StockSpec(kind="cylinder", margin_mm=(margin,) * 6,
                         diameter_mm=read_number(raw, "diameter_mm", "stock"),
                         length_mm=read_number(raw, "length_mm", "stock"),
                         axis=choice(raw.get("axis", "z"), ("x", "y", "z"), "stock.axis"))
    if stock_kind == "sheet":
        margins = _margins(raw.get("margin_mm", 0.0), "stock.margin_mm", box=False)
        return StockSpec(kind="sheet", margin_mm=margins, thickness_mm=read_number(raw, "thickness_mm", "stock"))
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise CamJobError("stock.path names the stock's STEP (a casting, a blank), relative to the job file or the part")
    return StockSpec(kind="from_step", path=path)


_REF = re.compile(r"^(?:[^#\s]*)#o[\w.]+\.f\d+$|^#f\d+$")


def _setup(raw: object, index: int, machine: Machine, tools: dict[str, Tool]) -> Setup:
    where = f"setups[{index}]"
    if not isinstance(raw, dict):
        raise CamJobError(f"{where} must be an object with an id, an orientation and operations")
    check_keys(raw, SETUP_KEYS, where)
    setup_id = raw.get("id", f"setup{index + 1}")
    if not isinstance(setup_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", setup_id):
        raise CamJobError(f"{where}.id must be a short name of letters, digits, - or _ (it names the posted file), "
                          f"not {setup_id!r}")
    orientation = raw.get("orientation", "+Z")
    if isinstance(orientation, dict):
        check_keys(orientation, ("a_deg", "b_deg", "c_deg"), f"{where}.orientation")
        if machine.kind not in ("mill4", "mill5"):
            raise CamJobError(f"{where}.orientation tilts the part (3+2), which needs a mill4 or mill5; this machine is "
                              f"a {machine.kind}. Use +Z, -Z, +X, -X, +Y or -Y and refixture by hand")
        for axis in ("a_deg", "b_deg", "c_deg"):
            read_number(orientation, axis, f"{where}.orientation", default=0.0, minimum=-360.0, maximum=360.0)
        if "b_deg" in orientation and machine.kinematics != "bc_head":
            raise CamJobError(f"{where}.orientation: b_deg needs a mill5 with kinematics bc_head; use a_deg and c_deg")
        orientation = {k: float(v) for k, v in orientation.items()}
    else:
        orientation = choice(orientation, ORIENTATIONS, f"{where}.orientation")
    origin = raw.get("origin", "stock-top-center")
    if isinstance(origin, dict):
        check_keys(origin, ("xyz",), f"{where}.origin")
        origin = {"xyz": number_list(origin.get("xyz"), f"{where}.origin.xyz", length=3)}
    else:
        origin = choice(origin, ORIGINS, f"{where}.origin")
    wcs = choice(raw.get("wcs", WORK_OFFSETS[min(index, 5)]), WORK_OFFSETS, f"{where}.wcs")
    fixtures_raw = raw.get("fixture", [])
    if isinstance(fixtures_raw, dict):
        fixtures_raw = [fixtures_raw]
    if not isinstance(fixtures_raw, list):
        raise CamJobError(f"{where}.fixture must be a box {{\"min_mm\": [x, y, z], \"max_mm\": [x, y, z]}} or a list")
    fixtures = []
    for i, box in enumerate(fixtures_raw):
        at = f"{where}.fixture[{i}]"
        if not isinstance(box, dict):
            raise CamJobError(f"{at} must be {{\"min_mm\": [x, y, z], \"max_mm\": [x, y, z]}} in part coordinates")
        check_keys(box, ("min_mm", "max_mm", "name"), at)
        low = number_list(box.get("min_mm"), f"{at}.min_mm", length=3)
        high = number_list(box.get("max_mm"), f"{at}.max_mm", length=3)
        if any(h <= lo for lo, h in zip(low, high)):
            raise CamJobError(f"{at}: max_mm must be more than min_mm on every axis")
        fixtures.append(Fixture(low, high, str(box.get("name", ""))))
    ops_raw = raw.get("operations")
    if not isinstance(ops_raw, list) or not ops_raw:
        raise CamJobError(f"{where}.operations must be a non-empty list, like [{{\"op\": \"face\", \"tool\": \"T1\"}}]")
    operations = tuple(_operation(op, f"{where}.operations[{i}]", i, machine, tools) for i, op in enumerate(ops_raw))
    plain = raw.get("name") or _plain_orientation(orientation)
    if not isinstance(plain, str):
        raise CamJobError(f"{where}.name must be text")
    return Setup(
        id=setup_id, plain=plain, orientation=orientation, origin=origin, operations=operations, wcs=wcs,
        clearance_mm=read_number(raw, "clearance_mm", where, default=5.0),
        retract_mm=read_number(raw, "retract_mm", where, default=2.0),
        fixtures=tuple(fixtures), index=index,
    )


def _plain_orientation(orientation: object) -> str:
    if isinstance(orientation, dict):
        return "Tilted " + " ".join(f"{k[0].upper()}{v:g}°" for k, v in orientation.items() if v)
    return {"+Z": "Top", "-Z": "Bottom", "+X": "Right", "-X": "Left", "+Y": "Back", "-Y": "Front"}[orientation]


def _operation(raw: object, where: str, index: int, machine: Machine, tools: dict[str, Tool]) -> OpSpec:
    if not isinstance(raw, dict):
        raise CamJobError(f"{where} must be an object like {{\"op\": \"pocket\", \"tool\": \"T1\", \"faces\": [\"#o1.f12\"]}}")
    if "op" not in raw:
        raise CamJobError(f"{where} needs \"op\", the operation's name")
    entry = operation_entry(raw["op"], f"{where}.op")
    if machine.kind not in entry.machines:
        raise CamJobError(f"{where}: a {machine.kind} cannot {entry.plain.lower()} ('{entry.name}' runs on "
                          f"{', '.join(entry.machines)}); change the machine or the operation")
    tool = raw.get("tool")
    if tool is not None:
        if not isinstance(tool, str) or tool not in tools:
            raise CamJobError(f"{where}.tool is {tool!r}, which is not in tools; the tools are {', '.join(tools)}")
    faces = raw.get("faces", [])
    if isinstance(faces, str):
        faces = [faces]
    if not isinstance(faces, list) or not all(isinstance(face, str) and _REF.match(face) for face in faces):
        raise CamJobError(f"{where}.faces must be a list of face refs like \"#o1.f12\" (cadgen cam features lists "
                          f"them), not {raw.get('faces')!r}")
    stepover = read_number(raw, "stepover", where, maximum=1.0)
    stepover_mm = read_number(raw, "stepover_mm", where)
    if stepover is not None and stepover_mm is not None:
        raise CamJobError(f"{where}: give stepover (a fraction of the tool diameter) or stepover_mm, not both")
    name = raw.get("name", "")
    if not isinstance(name, str):
        raise CamJobError(f"{where}.name must be text")
    return OpSpec(
        op=entry.name, where=where, index=index, tool=tool, faces=tuple(faces), region=raw.get("region"),
        feed=read_number(raw, "feed", where), speed=read_number(raw, "speed", where),
        stepdown_mm=read_number(raw, "stepdown_mm", where), stepover=stepover, stepover_mm=stepover_mm,
        stock_to_leave_mm=read_number(raw, "stock_to_leave_mm", where, default=0.0, minimum=0.0),
        coolant=choice(raw["coolant"], COOLANTS, f"{where}.coolant") if "coolant" in raw else None,
        name=name, extra={key: value for key, value in raw.items() if key not in OP_COMMON_KEYS},
    )
