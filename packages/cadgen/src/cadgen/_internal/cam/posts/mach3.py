"""``mach3``: Mach3 and Mach4 (``.tap``) for mills, 4th-axis mills, routers and plasma tables.

Every program sets ``G91.1`` (incremental arc centres): Mach3's IJ mode can be configured absolute, and an arc read
the other way is a crash. Mill and router: ``M5 M9`` and ``G53 G0 Z0`` (Z to the machine's top) then ``T M6``,
``G0 X Y`` over the first point and ``G43 H`` at a clearance Z, G2/G3, M8/M7/M9, the canned
cycles G81 G82 G83 (Q pecks back to R) G73 G84 G85 G86 G89 natively (a left-hand tap and fine boring post expanded),
dwell ``G4 P`` in seconds (``machine.dwell_ms: true`` when Mach's General Config has "G4 dwell in ms" ticked), ``M30``.
A 4th axis posts A words; a 3+2 setup turns A after each tool change, Z at the top (set the work offset on the
turned part), and the program ends with Z at the top and A back at zero (``G53 G0 A0``).
Mach has no tool centre point control, so a toolpath that turns A while cutting (a wrap) is refused: post it with
linuxcnc, fanuc or haas.

Plasma: after the work offset the torch goes up to its safe height (where it starts is unknown); then the torch is
``M3``/``M5`` with the pierce and cut heights, the pierce delay and optional torch height control codes as machine
keys (``_cutting.py`` has the sequence; THC is off by default here).
"""

from __future__ import annotations

from cadgen._internal.cam.posts._cutting import DWELL_MS, torch_off, torch_on, torch_options, torch_safe
from cadgen._internal.cam.posts._iso import CYCLES_OPTION, IsoPost
from cadgen._internal.cam.posts.base import Program, number

__all__ = ["Mach3Post"]


class Mach3Post(IsoPost):
    name = "mach3"
    kinds = ("mill", "mill4", "router", "plasma")
    extension = ".tap"
    plain = "Mach3/Mach4"
    tilt_style = "rotate"
    tcp_code = ""
    drill_codes = {"drill": "G81", "spot": "G82", "peck": "G83", "chipbreak": "G73", "tap": "G84", "bore": "G85",
                   "ream": "G85", "bore_stop": "G86", "bore_dwell": "G89"}
    left_tap_code = ""
    mill_tool_home = ("G53 G0 Z0",)
    mill_end_home = ("G53 G0 Z0",)
    index_home_lines = ("G53 G0 Z0",)
    rotary_home_style = "g53"
    options = {"cycles": CYCLES_OPTION, **torch_options(False), "dwell_ms": DWELL_MS}

    def begin(self, program: Program) -> None:
        super().begin(program)
        self._plasma = program.machine.kind == "plasma"
        self._beam = False
        if self._plasma:
            self.linear_axes = "XY"
            self.rotary_axes = ""

    def dwell_word(self, seconds: float) -> str:
        if self.option(self._program, "dwell_ms"):
            return f"P{int(round(seconds * 1000))}"
        return f"P{number(seconds, 3)}"

    def preamble(self, program: Program) -> list[str]:
        if self._plasma:
            return ["G21 G90 G94 G17 G40", "G91.1"]
        return ["G21 G90 G94 G17 G40 G49 G80", "G91.1"]

    def footer(self, program: Program) -> list[str]:
        if self._plasma:
            return (torch_off(self, program) if self._beam else []) + ["M30"]
        return super().footer(program)

    def on_setup(self, data: dict, program: Program) -> list[str]:
        lines = super().on_setup(data, program)
        return lines + torch_safe(self, program) if self._plasma else lines

    def on_tool(self, data: dict, program: Program, first: bool) -> list[str]:
        if self._plasma:
            return [self.comment(f"Torch: {self.tool_label(program.tools[data['tool']])}")]
        return super().on_tool(data, program, first)

    def on_spindle(self, data: dict, program: Program) -> list[str]:
        return [] if self._plasma else super().on_spindle(data, program)

    def on_coolant(self, data: dict, program: Program) -> list[str]:
        return [] if self._plasma else super().on_coolant(data, program)

    def emits_cycle(self, data: dict) -> bool:
        return not getattr(self, "_plasma", False) and super().emits_cycle(data)

    def modal_reset(self, kind: str) -> tuple[str, ...]:
        if kind == "beam":
            return ("motion", "f", "z")
        return super().modal_reset(kind)

    def on_beam(self, data: dict, program: Program) -> list[str]:
        if not self._plasma:
            return super().on_beam(data, program)
        if data.get("on"):
            self._beam = True
            return torch_on(self, data, program)
        if not self._beam:
            return []
        self._beam = False
        return torch_off(self, program)
