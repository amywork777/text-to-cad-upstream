"""Tools: the closed tool vocabulary, each tool's cutter profile, and its holder.

A tool is a frozen :class:`Tool` parsed from one entry of the job's ``tools`` list (:func:`parse_tool`). Its
geometry is a cutter profile about the tool axis, measured from the tip:

* :meth:`Tool.radius_at` ``(h)``: the cutting radius at height ``h`` mm above the tip (flutes only).
* :meth:`Tool.height_at` ``(d)``: the height of the cutter's lower surface at radial distance ``d`` from the axis
  (``inf`` beyond the radius), vectorised over numpy arrays. Drop-cutter and the stock simulators stamp with it.
* :attr:`Tool.holder`: the shank and holder above the flutes, for the reach and collision checks.

Families: ``mill`` (flat, ball, bull, vee, chamfer, drill, spot, tap, reamer, boring, thread_mill, slot,
engraver), ``lathe`` (turn, groove, thread, partoff) and ``cutting`` (beam, wire). A lathe tool's profile is its
nose radius (for the radial simulator); a beam's or a wire's is half its kerf or diameter.

Stdlib at import; numpy inside :meth:`Tool.height_at` when it is handed an array.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from cadgen._internal.cam.job_errors import CamJobError, check_keys, choice, read_number

__all__ = ["Holder", "TOOL_TYPES", "Tool", "parse_tool"]

#: Every tool type: its family and the keys only it takes (beyond :data:`COMMON_KEYS`). A required key is listed in
#: ``required``; the rest have defaults (:func:`parse_tool`).
TOOL_TYPES: dict[str, dict] = {
    "flat": {"family": "mill", "keys": (), "required": ("diameter_mm",), "plain": "flat"},
    "ball": {"family": "mill", "keys": (), "required": ("diameter_mm",), "plain": "ball"},
    "bull": {"family": "mill", "keys": ("corner_radius_mm",), "required": ("diameter_mm", "corner_radius_mm"),
             "plain": "bull nose"},
    "vee": {"family": "mill", "keys": ("angle_deg", "tip_diameter_mm"), "required": ("diameter_mm", "angle_deg"),
            "plain": "vee"},
    "chamfer": {"family": "mill", "keys": ("angle_deg", "tip_diameter_mm"), "required": ("diameter_mm",),
                "plain": "chamfer mill"},
    "drill": {"family": "mill", "keys": ("point_angle",), "required": ("diameter_mm",), "plain": "drill"},
    "spot": {"family": "mill", "keys": ("angle_deg",), "required": ("diameter_mm",), "plain": "spot drill"},
    "tap": {"family": "mill", "keys": ("pitch_mm",), "required": ("diameter_mm", "pitch_mm"), "plain": "tap"},
    "reamer": {"family": "mill", "keys": (), "required": ("diameter_mm",), "plain": "reamer"},
    "boring": {"family": "mill", "keys": (), "required": ("diameter_mm",), "plain": "boring bar"},
    "thread_mill": {"family": "mill", "keys": ("pitch_mm",), "required": ("diameter_mm", "pitch_mm"),
                    "plain": "thread mill"},
    "slot": {"family": "mill", "keys": ("width_mm",), "required": ("diameter_mm", "width_mm"), "plain": "slot cutter"},
    "engraver": {"family": "mill", "keys": ("angle_deg", "tip_diameter_mm"), "required": ("diameter_mm",),
                 "plain": "engraver"},
    "turn": {"family": "lathe", "keys": ("insert", "nose_radius_mm", "side"), "required": (), "plain": "turning tool"},
    "groove": {"family": "lathe", "keys": ("width_mm", "nose_radius_mm", "side"), "required": ("width_mm",),
               "plain": "grooving tool"},
    "thread": {"family": "lathe", "keys": ("pitch_mm", "side"), "required": ("pitch_mm",), "plain": "threading tool"},
    "partoff": {"family": "lathe", "keys": ("width_mm",), "required": ("width_mm",), "plain": "part-off blade"},
    "beam": {"family": "cutting", "keys": ("kerf_mm",), "required": ("kerf_mm",), "plain": "beam"},
    "wire": {"family": "cutting", "keys": (), "required": ("diameter_mm",), "plain": "wire"},
}

#: Keys every tool may carry. ``number`` is the T number posted (default: the digits of ``id``, else its position).
COMMON_KEYS = ("id", "type", "number", "name", "diameter_mm", "flutes", "flute_length_mm", "stickout_mm",
               "holder_diameter_mm", "holder_length_mm", "shank_diameter_mm", "material")
TOOL_MATERIALS = ("carbide", "hss")
INSERTS = ("C", "D", "V", "W")
SIDES = ("left", "right", "neutral")


@dataclass(frozen=True)
class Holder:
    """The non-cutting part above the flutes: a shank to ``stickout_mm`` above the tip, then a holder cylinder."""

    shank_diameter_mm: float
    stickout_mm: float
    holder_diameter_mm: float | None
    holder_length_mm: float


@dataclass(frozen=True)
class Tool:
    id: str
    type: str
    number: int
    diameter_mm: float = 0.0
    flutes: int = 2
    flute_length_mm: float = 0.0
    stickout_mm: float = 0.0
    holder_diameter_mm: float | None = None
    holder_length_mm: float = 40.0
    shank_diameter_mm: float = 0.0
    material: str = "carbide"
    name: str = ""
    corner_radius_mm: float = 0.0
    #: Included angle of a vee, chamfer, spot or engraver (degrees).
    angle_deg: float = 0.0
    tip_diameter_mm: float = 0.0
    point_angle: float = 118.0
    pitch_mm: float = 0.0
    width_mm: float = 0.0
    insert: str = ""
    nose_radius_mm: float = 0.0
    side: str = ""
    kerf_mm: float = 0.0

    @property
    def family(self) -> str:
        return TOOL_TYPES[self.type]["family"]

    @property
    def radius(self) -> float:
        """The cutting radius (half the kerf for a beam)."""
        if self.type == "beam":
            return self.kerf_mm / 2.0
        return self.diameter_mm / 2.0

    @property
    def plain(self) -> str:
        """The viewer's words for it: ``6 mm flat``, ``90° vee``, ``M6x1 tap``, ``0.2 mm beam``."""
        word = TOOL_TYPES[self.type]["plain"]
        if self.type in ("vee", "engraver") and self.angle_deg:
            return f"{_num(self.angle_deg)}° {word}"
        if self.type == "tap":
            return f"M{_num(self.diameter_mm)}x{_num(self.pitch_mm)} tap"
        if self.type == "beam":
            return f"{_num(self.kerf_mm)} mm kerf beam"
        if self.type in ("groove", "partoff"):
            return f"{_num(self.width_mm)} mm {word}"
        if self.family == "lathe":
            return word if not self.insert else f"{self.insert} insert {word}"
        if self.type == "bull":
            return f"{_num(self.diameter_mm)} mm R{_num(self.corner_radius_mm)} bull nose"
        return f"{_num(self.diameter_mm)} mm {word}"

    @property
    def holder(self) -> Holder:
        return Holder(self.shank_diameter_mm or self.diameter_mm, self.stickout_mm, self.holder_diameter_mm,
                      self.holder_length_mm)

    def _half_angle(self) -> float:
        angle = self.angle_deg or (self.point_angle if self.type == "drill" else 90.0)
        return math.radians(angle / 2.0)

    def radius_at(self, h: float) -> float:
        """The cutting radius ``h`` mm above the tip; 0 below the tip, the full radius above the profile's top."""
        r = self.radius
        if h < 0:
            return 0.0
        kind = self.type
        if kind == "ball":
            return math.sqrt(max(0.0, r * r - (r - h) ** 2)) if h < r else r
        if kind == "bull":
            rc = min(self.corner_radius_mm, r)
            return (r - rc) + (math.sqrt(max(0.0, rc * rc - (rc - h) ** 2)) if h < rc else rc)
        if kind in ("vee", "chamfer", "engraver", "spot", "drill"):
            tip = self.tip_diameter_mm / 2.0
            return min(r, tip + h * math.tan(self._half_angle()))
        return r

    def height_at(self, d):
        """The lower surface's height above the tip at radial distance ``d`` (a float or a numpy array); ``inf``
        beyond the radius. Flat: 0. Ball: ``r - sqrt(r² - d²)``. Bull: flat to ``r - rc``, then the corner arc.
        Cone (vee, chamfer, engraver, spot, drill): ``(d - tip) / tan(half angle)``."""
        if not hasattr(d, "shape"):
            import numpy as np

            return float(self.height_at(np.asarray([d], dtype=float))[0])
        import numpy as np

        d = np.abs(np.asarray(d, dtype=float))
        r = self.radius
        kind = self.type
        out = np.full(d.shape, np.inf)
        inside = d <= r + 1e-12
        di = np.minimum(d[inside], r)
        if kind == "ball":
            out[inside] = r - np.sqrt(np.maximum(0.0, r * r - di * di))
        elif kind == "bull":
            rc = min(self.corner_radius_mm, r)
            flat = r - rc
            dd = np.maximum(0.0, di - flat)
            out[inside] = rc - np.sqrt(np.maximum(0.0, rc * rc - dd * dd))
        elif kind in ("vee", "chamfer", "engraver", "spot", "drill"):
            tip = self.tip_diameter_mm / 2.0
            out[inside] = np.maximum(0.0, di - tip) / math.tan(self._half_angle())
        else:
            out[inside] = 0.0
        return out

    def as_dict(self) -> dict:
        """The tool as the GLB's extras and the Results carry it: every set field, plus ``plain``."""
        out = {key: value for key, value in asdict(self).items() if value not in (0.0, "", None)}
        out.update({"id": self.id, "type": self.type, "number": self.number, "plain": self.plain})
        return out


def _num(value: float) -> str:
    return f"{value:g}"


def parse_tool(raw: object, position: int) -> Tool:
    """One entry of ``tools``: closed keys per type, defaults filled in, teaching errors naming the allowed set."""
    where = f"tools[{position}]"
    if not isinstance(raw, dict):
        raise CamJobError(f"{where} must be an object like {{\"id\": \"T1\", \"type\": \"flat\", \"diameter_mm\": 6}}")
    kind = choice(raw.get("type"), tuple(TOOL_TYPES), f"{where}.type")
    spec = TOOL_TYPES[kind]
    check_keys(raw, (*COMMON_KEYS, *spec["keys"]), where, hint=f"a {kind} tool")
    tool_id = raw.get("id")
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise CamJobError(f"{where} needs an \"id\" (a short name the operations use, like \"T1\")")
    for key in spec["required"]:
        if key not in raw:
            raise CamJobError(f"{where} ({tool_id}, a {kind} tool) needs \"{key}\"")
    digits = "".join(ch for ch in tool_id if ch.isdigit())
    t_number = raw.get("number")
    if t_number is None:
        t_number = int(digits) if digits else position + 1
    elif isinstance(t_number, bool) or not isinstance(t_number, int) or t_number < 0:
        raise CamJobError(f"{where}.number must be a whole number, 0 or more (the T number posted)")
    diameter = read_number(raw, "diameter_mm", where, default=0.0)
    if spec["family"] == "mill" and diameter <= 0:
        raise CamJobError(f"{where}.diameter_mm must be more than 0")
    flutes = raw.get("flutes", 1 if kind in ("vee", "engraver", "spot", "boring", "reamer") else 2)
    if isinstance(flutes, bool) or not isinstance(flutes, int) or flutes < 1:
        raise CamJobError(f"{where}.flutes must be a whole number of at least 1")
    # Defaults from catalogue tools: a jobber drill's flutes run about ten diameters, a reamer's six, a spot
    # drill's one; an end mill's about three.
    flute_factor = {"drill": 10.0, "reamer": 6.0, "spot": 1.0, "tap": 3.0, "boring": 4.0}.get(kind, 3.0)
    flute_length = read_number(raw, "flute_length_mm", where, default=max(flute_factor * diameter, 1.0))
    stickout = read_number(raw, "stickout_mm", where, default=max(flute_length * 1.25, flute_length + 5.0))
    if stickout < flute_length:
        raise CamJobError(f"{where}: stickout_mm ({stickout:g}) is shorter than flute_length_mm ({flute_length:g}); "
                          "the stickout is the length out of the holder, flutes included")
    angle_default = {"chamfer": 90.0, "spot": 90.0, "engraver": 30.0}.get(kind, 0.0)
    tool = Tool(
        id=tool_id, type=kind, number=t_number, diameter_mm=diameter, flutes=flutes,
        flute_length_mm=flute_length, stickout_mm=stickout,
        holder_diameter_mm=read_number(raw, "holder_diameter_mm", where, default=None),
        holder_length_mm=read_number(raw, "holder_length_mm", where, default=40.0),
        shank_diameter_mm=read_number(raw, "shank_diameter_mm", where, default=diameter),
        material=choice(raw.get("material", "carbide"), TOOL_MATERIALS, f"{where}.material"),
        name=str(raw.get("name", "")),
        corner_radius_mm=read_number(raw, "corner_radius_mm", where, default=0.0),
        angle_deg=read_number(raw, "angle_deg", where, default=angle_default),
        tip_diameter_mm=read_number(raw, "tip_diameter_mm", where, default=0.0, minimum=0.0),
        point_angle=read_number(raw, "point_angle", where, default=118.0),
        pitch_mm=read_number(raw, "pitch_mm", where, default=0.0),
        width_mm=read_number(raw, "width_mm", where, default=0.0),
        insert=choice(raw["insert"], INSERTS, f"{where}.insert") if "insert" in raw else "",
        nose_radius_mm=read_number(raw, "nose_radius_mm", where, default=0.4 if kind == "turn" else 0.0, minimum=0.0),
        side=choice(raw["side"], SIDES, f"{where}.side") if "side" in raw else "",
        kerf_mm=read_number(raw, "kerf_mm", where, default=0.0),
    )
    if kind == "bull" and tool.corner_radius_mm > tool.radius:
        raise CamJobError(f"{where}: corner_radius_mm ({tool.corner_radius_mm:g}) is more than the tool's radius")
    if kind in ("vee", "chamfer", "engraver", "spot") and not 0 < tool.angle_deg < 180:
        raise CamJobError(f"{where}.angle_deg is the included angle and must be between 0 and 180")
    if kind == "drill" and not 60 <= tool.point_angle <= 180:
        raise CamJobError(f"{where}.point_angle must be between 60 and 180 degrees (118 or 135 for most drills)")
    if tool.tip_diameter_mm >= max(tool.diameter_mm, 1e-9) and kind in ("vee", "chamfer", "engraver"):
        raise CamJobError(f"{where}: tip_diameter_mm must be less than diameter_mm")
    return tool
