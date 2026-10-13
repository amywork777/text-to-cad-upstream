"""What the ISO-style posts share (``linuxcnc``, ``fanuc``, ``haas``, ``mach3``) and the checks every post past GRBL
runs before it writes a line.

:class:`CheckedPost` refuses, in one plain sentence, a toolpath its machine cannot run: an event the machine kind has
no hardware for (a beam on a mill, a spindle on a plasma table, coolant on a wire EDM), a rotary axis the machine
does not have, a lathe move off the XZ plane. Its comments are plain ASCII (old controls reject anything else).

:class:`IsoPost` is one RS-274 dialect with switches the four controllers set:

- mills: work offset, tool change (``T M6`` and ``G43 H`` with a clearance Z), spindle, coolant, the drilling
  cycles natively (G81 G82 G83 G73 G84/G74 G85 G86 G89 G76, the set each controller has; the rest post expanded),
  arcs fitted in XY.
- ``mill4``/``mill5``: rotary words on the moves. A 3+2 setup (the setup event's ``rotary``) turns the table after the
  tool change, then posts 3-axis in the tilted frame: plain rotation (LinuxCNC, Mach3: set the work offset on the
  rotated part), ``G68.2``/``G53.1`` (Fanuc: tilted working plane), or ``G254`` (Haas: dynamic work offset). Moves
  whose rotary positions change while cutting are simultaneous: tool length is posted as TCP (``G43.4``, Haas
  ``G234``) and arcs are not fitted.
- lathe: ``XZ`` words (X a diameter in diameter mode), G18 arcs with I/K (I a radius), the controller's tool word
  (``T0101``, ``T101``, ``T1 M6``), constant surface speed with its clamp, feed per revolution where the spindle event
  asks, the threading cycle natively and the roughing cycle natively only with ``machine.cycles: true``.

``machine.cycles``: left out, drilling and threading cycles post natively and lathe roughing posts expanded;
``true`` posts every cycle the controller has natively; ``false`` posts every cycle expanded (the IR's own moves).
Stdlib at import; numpy inside.
"""

from __future__ import annotations

import math

from cadgen._internal.cam.job_errors import CamJobError
from cadgen._internal.cam.posts.base import Post, Program, number

__all__ = ["CheckedPost", "IsoPost", "ascii_text", "euler_zxz", "is_simultaneous"]

MILL_KINDS = ("mill", "mill4", "mill5", "router")
CUTTING_KINDS = ("laser", "plasma", "waterjet", "wire_edm")
_POSITION = ("motion", "x", "y", "z", "a", "b", "c")

#: The event kinds each machine kind can run (anything else is refused with a sentence).
_EVENTS = {
    **{kind: {"setup", "tool", "spindle", "coolant", "cycle", "stop", "comment"} for kind in (*MILL_KINDS, "lathe")},
    **{kind: {"setup", "tool", "beam", "coolant", "cycle", "stop", "comment"}
       for kind in ("laser", "plasma", "waterjet")},
    "wire_edm": {"setup", "tool", "beam", "coolant", "stop", "comment"},
}

CYCLES_OPTION = {"type": "bool", "default": None,
                 "help": "true posts every canned cycle the controller has, false posts every cycle as plain moves; "
                         "left out, drilling and threading are cycles and lathe roughing is plain moves"}


def ascii_text(text: str) -> str:
    """``text`` with the few non-ASCII signs cadgen writes spelled out, then anything else non-ASCII dropped."""
    for sign, word in (("°", " deg"), ("Ø", "D"), ("ø", "D"), ("×", "x"), ("·", "-"), ("—", "-"), ("–", "-"),
                       ("µ", "u")):
        text = text.replace(sign, word)
    return text.encode("ascii", "ignore").decode("ascii")


def is_simultaneous(path) -> bool:
    """True when rotary positions change along cutting moves (not just a rapid index between cuts)."""
    import numpy as np

    from cadgen._internal.cam.ir import DWELL, RAPID

    moves = path.moves
    if not len(moves) or not path.rotary:
        return False
    abc = np.column_stack([moves["a"], moves["b"], moves["c"]])
    before = np.vstack([abc[:1], abc[:-1]])
    cutting = (moves["kind"] != RAPID) & (moves["kind"] != DWELL)
    return bool(np.any(cutting & (np.abs(abc - before).max(axis=1) > 1e-9)))


def euler_zxz(rotation) -> tuple[float, float, float]:
    """Fanuc G68.2 angles (I, J, K: about Z, then the new X, then the new Z, degrees) of the tilted frame whose axes,
    written in part coordinates, are the rows of ``rotation`` (``wcs.WCS.rotation``)."""
    m = [[rotation[j][i] for j in range(3)] for i in range(3)]          # columns = the frame's axes
    beta = math.acos(max(-1.0, min(1.0, m[2][2])))
    if abs(math.sin(beta)) > 1e-9:
        alpha = math.atan2(m[0][2], -m[1][2])
        gamma = math.atan2(m[2][0], m[2][1])
    else:
        alpha, gamma = math.atan2(m[1][0], m[0][0]), 0.0

    def wrap(angle: float) -> float:
        angle = math.degrees(angle) % 360.0
        return angle - 360.0 if angle > 180.0 + 1e-9 else angle

    # Two triples give the same frame: (a, b, g) and (a + 180, -b, g + 180). Post the one that turns least about
    # the final Z, then about the first.
    first = (wrap(alpha), math.degrees(beta), wrap(gamma))
    second = (wrap(alpha + math.pi), -math.degrees(beta), wrap(gamma + math.pi))
    best = min((first, second), key=lambda t: (round(abs(t[2]), 6), round(abs(t[0]), 6)))
    return tuple(round(v, 6) + 0.0 for v in best)


class CheckedPost(Post):
    """A post that refuses what its machine cannot run, writes ASCII comments and knows its machine."""

    #: Upper-case every comment (older Fanuc-style controls reject lower case).
    upper_comments = False

    def comment(self, text: str) -> str:
        text = ascii_text(text)
        return super().comment(text.upper() if self.upper_comments else text)

    def rotary_letters(self, machine) -> str:
        """The rotary axes the machine has: ``""``, ``A``, ``AC`` or ``BC``."""
        return "".join(axis for axis in machine.axes if axis in "ABC")

    def check(self, program: Program) -> None:
        machine = program.machine
        kind = machine.kind
        path = program.toolpath
        where = f"setup {program.setup.id}"
        if kind not in self.kinds:
            raise CamJobError(f"machine.post: the {self.name} post does not serve a {kind}; it serves "
                              f"{', '.join(self.kinds)}")
        allowed = _EVENTS[kind]
        for event in path.events:
            data = event.data
            if event.kind not in allowed:
                raise CamJobError(self._refusal(event.kind, kind, where))
            wet = event.kind == "coolant" and data.get("mode", "off") != "off"
            if wet and kind in ("plasma", "waterjet", "wire_edm"):
                raise CamJobError(f"{where}: a {kind} has no coolant to switch to {data.get('mode')}; set the "
                                  "operation's coolant (or the job's) to off")
            if event.kind == "coolant" and kind == "laser" and data.get("mode", "off") == "flood":
                raise CamJobError(f"{where}: a laser has air assist, not flood coolant; use coolant air or off")
        letters = self.rotary_letters(machine)
        for axis in path.rotary:
            if axis.upper() not in letters:
                raise CamJobError(f"{where}: the toolpath turns the {axis.upper()} axis, which this {kind} does not "
                                  f"have (its axes are {machine.axes}); use a mill4 or mill5 with that axis, or a "
                                  "fixed orientation")
        for event in path.events:
            if event.kind == "setup":
                for axis, value in (event.data.get("rotary") or {}).items():
                    if value and axis.upper() not in letters:
                        raise CamJobError(f"{where}: the setup tilts the {axis.upper()} axis, which this {kind} does "
                                          f"not have (its axes are {machine.axes}); tilt only "
                                          f"{', '.join(letters) or 'nothing (use +Z, -Z, ... and refixture)'}")
        if kind == "lathe" and len(path.moves):
            import numpy as np

            off = np.abs(path.moves["y"]).max()
            if off > 1e-6:
                raise CamJobError(f"{where}: the lathe toolpath moves off the XZ plane (Y {off:.3g} mm); a lathe "
                                  "toolpath stores the radius in X and the axial position in Z only")

    @staticmethod
    def _refusal(event: str, kind: str, where: str) -> str:
        if event == "beam":
            return (f"{where}: the toolpath switches a beam on, and a {kind} has no beam; cut it on a laser, plasma "
                    "or waterjet machine (machine.kind)")
        if event == "spindle":
            return (f"{where}: the toolpath starts a spindle, and a {kind} has none; use a milling or turning "
                    "machine for that operation (machine.kind)")
        if event == "cycle":
            return f"{where}: a {kind} cannot run a drilling cycle; drill the holes on a mill (machine.kind)"
        return f"{where}: a {kind} cannot run a {event} event"


class IsoPost(CheckedPost):
    """The RS-274 dialect the ISO posts share; each controller sets the switches below."""

    accepts_arcs = True
    tool_changer = True
    #: Dimension words always carry a decimal point (``X10.``): a Fanuc-style control reads ``X10`` as 10 microns.
    decimal_point = False
    #: ``%`` and an ``O`` number around the program.
    program_wrap = False
    o_digits = 4
    #: Lines before ``T M6`` on a mill (Fanuc: home Z), and before the program end.
    mill_tool_home: tuple[str, ...] = ()
    mill_end_home: tuple[str, ...] = ()
    #: How a 3+2 setup is posted: ``rotate`` (turn the table, set the work offset there), ``g68_2``, ``dwo``.
    tilt_style = "rotate"
    #: The TCP word for simultaneous multi-axis, or "" when the controller has none.
    tcp_code = "G43.4"
    #: Drilling cycles this controller has: cycle name -> G code.
    drill_codes = {"drill": "G81", "spot": "G82", "peck": "G83", "chipbreak": "G73", "tap": "G84", "bore": "G85",
                   "ream": "G85", "bore_stop": "G86", "bore_dwell": "G89", "fine_bore": "G76"}
    left_tap_code = "G74"
    #: Fanuc rigid tapping: ``M29 S`` before G84.
    rigid_tap_m29 = False
    #: Lathe: feed per minute / per revolution words, the threading dialect, native G71, the tool word.
    lathe_feed_codes = ("G94", "G95")
    thread_style = "fanuc"
    native_rough = True
    lathe_home: tuple[str, ...] = ()
    #: Dwell words in integer milliseconds (Fanuc, Haas) instead of seconds.
    dwell_ms = False

    options = {"cycles": CYCLES_OPTION}

    # --- the render, with this controller's state ---------------------------------------------------------

    def render(self, program: Program) -> str:
        self.begin(program)
        self.check(program)
        text = super().render(program)
        if self.program_wrap:
            number_ = int(self.option(program, "program_number")) if "program_number" in self.options else 1000
            if number_ >= 10 ** self.o_digits:
                raise CamJobError(f"machine.program_number must be at most {10 ** self.o_digits - 1} for a "
                                  f"{self.plain} O number")
            title = self.comment(f"{program.job_name or program.part or 'part'} {program.setup.id}")
            text = f"%\nO{number_:0{self.o_digits}d} {title}\n{text}%\n"
        return text

    def begin(self, program: Program) -> None:
        machine = program.machine
        path = program.toolpath
        self._program = program
        self._lathe = machine.kind == "lathe" or bool(getattr(path, "lathe", False))
        self._simultaneous = is_simultaneous(path)
        self._has_tools = any(e.kind == "tool" for e in path.events)
        self._tilt: dict = {}
        self._tilt_active = False
        self._tcp_active = False
        self._rpm = 0.0
        self._per_rev = False
        self._coolant = "off"
        self._block = 100
        self._tool_id = None
        self.rotary_axes = self.rotary_letters(machine)
        tilted = any(e.kind == "setup" and any((e.data.get("rotary") or {}).values()) for e in path.events)
        if tilted and not self._simultaneous and self.tilt_style in ("g68_2", "dwo"):
            # The tilted plane turns the table; rotary words on the moves (the same angles) would fight it.
            self.rotary_axes = ""
        if self._lathe:
            self.linear_axes = "XZ"
            self.arc_planes = frozenset({1})
            self.fit_arcs_to_lines = False
        else:
            self.linear_axes = "XYZ"
            self.arc_planes = frozenset({0})
            self.fit_arcs_to_lines = not self._simultaneous

    def diameter(self) -> bool:
        return self._lathe and bool(getattr(self._program.machine, "diameter_mode", True))

    # --- number formats -----------------------------------------------------------------------------------

    def num(self, value: float) -> str:
        text = number(value, self.decimals)
        return text + "." if self.decimal_point and "." not in text else text

    def axis_value(self, axis: str, value: float) -> float:
        return 2.0 * value if axis == "x" and self.diameter() else value

    def feed_word(self, feed: float) -> str:
        if self._per_rev and self._rpm > 0:
            text = number(feed / self._rpm, 4)
            return text + "." if self.decimal_point and "." not in text else text
        return self.num(round(feed, 1))

    def dwell_word(self, seconds: float) -> str:
        return f"P{int(round(seconds * 1000))}" if self.dwell_ms else f"P{number(seconds, 3)}"

    def modal_reset(self, kind: str) -> tuple[str, ...]:
        if kind in ("tool", "setup"):
            return _POSITION
        if kind == "spindle" and self._lathe:
            return ("f",)
        return ()

    # --- header, preamble, footer -------------------------------------------------------------------------

    def header(self, program: Program) -> list[str]:
        lines = super().header(program)
        notes = []
        if self._lathe:
            notes.append("X words are diameters." if self.diameter() else
                         "X words are radii: the control's diameter programming must be off.")
        tilt = next((e.data.get("rotary") for e in program.toolpath.events
                     if e.kind == "setup" and e.data.get("rotary")), None)
        if tilt and not self._simultaneous:
            notes.append(self.tilt_note(program, tilt))
        if self._simultaneous:
            axes = "".join(sorted(a.upper() for a in program.toolpath.rotary))
            notes.append(f"Simultaneous {axes} with tool centre point control ({self.tcp_code}): X Y Z are the tool "
                         f"tip in {program.setup.wcs} at rotary zero.")
        return lines + [self.comment(note) for note in notes]

    def tilt_note(self, program: Program, tilt: dict) -> str:
        words = " ".join(f"{k.upper()}{number(v)}" for k, v in sorted(tilt.items()) if v)
        if self.tilt_style == "g68_2":
            return (f"3+2 {words} by G68.2: {program.setup.wcs} is this setup's origin on the part with the table at "
                    "rotary zero.")
        if self.tilt_style == "dwo":
            return (f"3+2 {words} by dynamic work offset G254: {program.setup.wcs} is this setup's origin on the part "
                    "with the table at rotary zero; the machine's rotary centre settings must be set.")
        return (f"3+2: the table turns to {words} after each tool change; set {program.setup.wcs} on the turned part "
                "at this setup's origin.")

    def preamble(self, program: Program) -> list[str]:
        if self._lathe:
            return ["G21", f"G0 G18 G40 G80 G90 {self.lathe_feed_codes[0]}"]
        return ["G21", "G0 G17 G40 G49 G80 G90 G94"]

    def footer(self, program: Program) -> list[str]:
        lines = ["M5", "M9"]
        lines += self.cancel_tilt()
        if self._tcp_active:
            lines.append("G49")
            self._tcp_active = False
        lines += list(self.lathe_home if self._lathe else self.mill_end_home)
        return lines + ["M30"]

    # --- setups, tools, spindle, coolant ------------------------------------------------------------------

    def on_setup(self, data: dict, program: Program) -> list[str]:
        lines = [data.get("wcs", "G54")]
        self._tilt = {k.lower(): float(v) for k, v in (data.get("rotary") or {}).items() if v}
        if self._tilt and not self._simultaneous and not self._has_tools:
            lines += self.tilt_lines(program)
        return lines

    def tilt_lines(self, program: Program) -> list[str]:
        """Turn the table to the setup's 3+2 position and enter the tilted frame."""
        words = " ".join(f"{k.upper()}{self.num(v)}" for k, v in sorted(self._tilt.items()))
        self._tilt_active = True
        if self.tilt_style == "g68_2":
            i, j, k = euler_zxz(program.wcs.rotation)
            zero = self.num(0.0)
            return [f"G68.2 X{zero} Y{zero} Z{zero} I{self.num(i)} J{self.num(j)} K{self.num(k)}", "G53.1"]
        if self.tilt_style == "dwo":
            return [f"G0 {words}", "G254"]
        return [f"G0 {words}"]

    def cancel_tilt(self) -> list[str]:
        if not self._tilt_active:
            return []
        self._tilt_active = False
        return {"g68_2": ["G69"], "dwo": ["G255"]}.get(self.tilt_style, [])

    def on_tool(self, data: dict, program: Program, first: bool) -> list[str]:
        tool = program.tools[data["tool"]]
        n = tool.number
        self._tool_id = tool.id
        lines = self.cancel_tilt()
        if self._tcp_active:
            lines.append("G49")
            self._tcp_active = False
        lines.append(self.comment(self.tool_label(tool)))
        if self._lathe:
            return lines + list(self.lathe_home) + self.lathe_tool_words(n)
        lines += list(self.mill_tool_home) + [f"T{n} M6"]
        if self._tilt and not self._simultaneous:
            lines += self.tilt_lines(program)
        if self._simultaneous and self.tcp_code:
            self._tcp_active = True
            return lines + [f"{self.tcp_code} H{n}"]
        return lines + [f"G0 G43 Z{self.num(program.clearance_z)} H{n}"]

    def lathe_tool_words(self, n: int) -> list[str]:
        return [f"T{n:02d}{n:02d}"]

    def on_spindle(self, data: dict, program: Program) -> list[str]:
        if data.get("dir") == "off":
            return ["M5"]
        rpm = int(round(float(data["rpm"])))
        self._rpm = float(data["rpm"])
        m = "M4" if data.get("dir") == "ccw" else "M3"
        if not self._lathe:
            return [f"S{rpm} {m}"]
        lines = []
        per_rev = bool(data.get("feed_per_rev"))
        if per_rev != self._per_rev:
            lines.append(self.lathe_feed_codes[1 if per_rev else 0])
            self._per_rev = per_rev
        css = data.get("css_m_min")
        if css:
            clamp = int(round(float(data.get("max_rpm") or program.machine.max_rpm or rpm)))
            return lines + self.css_words(float(css), clamp, m)
        return lines + [f"G97 S{rpm} {m}"]

    def css_words(self, css: float, clamp: int, m: str) -> list[str]:
        return [f"G50 S{clamp}", f"G96 S{int(round(css))} {m}"]

    def on_coolant(self, data: dict, program: Program) -> list[str]:
        mode = data.get("mode", "off")
        self._coolant = mode
        return [{"flood": "M8", "mist": "M7", "air": "M7", "off": "M9"}[mode]]

    def on_beam(self, data: dict, program: Program) -> list[str]:   # refused by check() first
        raise CamJobError(self._refusal("beam", program.machine.kind, f"setup {program.setup.id}"))

    # --- canned cycles ------------------------------------------------------------------------------------

    def emits_cycle(self, data: dict) -> bool:
        """Post this cycle natively. Outside a render (an operation asking what a post does with a cycle, with
        ``{"cycle": name}`` only) it answers for the machine kind's defaults with every key present."""
        program = getattr(self, "_program", None)
        cycles = self.option(program, "cycles") if program is not None else None
        if cycles is False:
            return False
        name = data.get("cycle")
        if program is None:
            data = {**data, "holes": [], "z_bottom": 0.0, "r_plane": 0.0, "feed": 0.0, "peck_mm": 1.0}
        if program is not None and self._lathe:
            if name == "thread":
                return self.can_thread(data)
            if name == "turn_rough":
                return cycles is True and self.native_rough and len(data.get("profile") or ()) >= 2 and all(
                    key in data for key in ("depth_mm", "x_start", "z_start", "feed"))
            return False
        if name not in self.drill_codes or not all(key in data for key in ("holes", "z_bottom", "r_plane", "feed")):
            return False
        if name == "tap" and self.left_hand(data) and not self.left_tap_code:
            return False
        return not (name in ("peck", "chipbreak") and not data.get("peck_mm"))

    def can_thread(self, data: dict) -> bool:
        needed = ("z_start", "z_end", "x_clear", "x_crest", "depth_mm", "pitch_mm")
        return all(key in data for key in needed) and int(round(float(data.get("angle_deg", 60)))) in (
            0, 29, 30, 55, 60, 80)

    def left_hand(self, data: dict) -> bool:
        tool = self._program.tools.get(self._tool_id) if getattr(self, "_tool_id", None) else None
        return bool(data.get("left_hand")) or getattr(tool, "hand", "") == "left"

    def cycle_lines(self, data: dict, state: dict) -> list[str]:
        if self._lathe:
            return self.thread_lines(data) if data["cycle"] == "thread" else self.rough_lines(data)
        return self.drill_lines(data)

    def drill_lines(self, data: dict) -> list[str]:
        name = data["cycle"]
        code = self.left_tap_code if name == "tap" and self.left_hand(data) else self.drill_codes[name]
        if name == "spot" and not data.get("dwell_s"):
            code = self.drill_codes["drill"]                 # a spot without a dwell is a plain drill cycle
        holes = data["holes"]
        lines = [self.comment(f"{name} cycle, {len(holes)} hole{'s' if len(holes) != 1 else ''}")]
        if code in ("G84", "G74") and self.rigid_tap_m29:
            lines.append(f"M29 S{int(round(self._rpm))}")
        retract = "G98" if data.get("retract", "r") == "initial" else "G99"
        for k, hole in enumerate(holes):
            words = [f"X{self.num(hole[0])}", f"Y{self.num(hole[1])}"]
            if k == 0:
                words = [retract, code] + words + [f"Z{self.num(data['z_bottom'])}", f"R{self.num(data['r_plane'])}"]
                if name in ("peck", "chipbreak"):
                    words.append(f"Q{self.num(data['peck_mm'])}")
                if name == "fine_bore":
                    words.append(f"Q{self.num(float(data.get('shift_mm', 0.1)))}")
                if name in ("spot", "tap", "bore_dwell", "fine_bore") and data.get("dwell_s"):
                    words.append(self.dwell_word(float(data["dwell_s"])))
                words.append(f"F{self.num(round(float(data['feed']), 1))}")
            lines.append(" ".join(words))
        lines.append("G80")
        return lines

    @staticmethod
    def thread_angle(data: dict) -> int:
        """The tip angle word: the thread's angle for flank infeed, 0 for a straight radial infeed."""
        if float(data.get("infeed_deg", 29.5)) == 0.0:
            return 0
        return int(round(float(data.get("angle_deg", 60))))

    def root_radius(self, data: dict) -> float:
        external = data.get("external", True)
        depth = float(data["depth_mm"])
        return float(data["x_crest"]) - depth if external else float(data["x_crest"]) + depth

    def thread_lines(self, data: dict) -> list[str]:
        """Fanuc's two-block G76 (P: spring passes, chamfer, tip angle; Q/P/Q in microns, no decimal point)."""
        depth = float(data["depth_mm"])
        first = float(data.get("first_depth_mm") or max(depth / 3.0, 0.05))
        minimum = float(data.get("min_depth_mm") or 0.05)
        spring = int(data.get("spring_passes", 1))
        angle = self.thread_angle(data)
        taper = -float(data.get("taper_mm", 0.0))            # Fanuc R: start radius minus end radius
        x = self.num(self.axis_value("x", self.root_radius(data)))
        second = f"G76 X{x} Z{self.num(float(data['z_end']))}"
        if abs(taper) > 1e-9:
            second += f" R{self.num(taper)}"
        second += f" P{int(round(depth * 1000))} Q{int(round(first * 1000))} F{self.num(float(data['pitch_mm']))}"
        return [self.comment(f"thread, pitch {number(float(data['pitch_mm']))} mm"),
                f"G76 P{spring:02d}00{angle:02d} Q{int(round(minimum * 1000))} "
                f"R{self.num(float(data.get('finish_mm', 0.0)))}",
                second]

    def rough_lines(self, data: dict) -> list[str]:
        """Fanuc's two-block G71 and the profile between its P and Q blocks."""
        ns, nf, profile = self.profile_blocks(data)
        u, w = self.allowances(data)
        return [self.comment("roughing cycle"), f"G71 U{self.num(float(data['depth_mm']))} "
                f"R{self.num(float(data.get('retract_mm', 0.5)))}",
                f"G71 P{ns} Q{nf} U{self.num(u)} W{self.num(w)} F{self.feed_word(float(data['feed']))}"] + profile

    def allowances(self, data: dict) -> tuple[float, float]:
        u = self.axis_value("x", float(data.get("allowance_x_mm", 0.0)))
        if not data.get("external", True):
            u = -u
        return u, float(data.get("allowance_z_mm", 0.0))

    def profile_blocks(self, data: dict) -> tuple[int, int, list[str]]:
        points = [(float(x), float(z)) for x, z in data["profile"]]
        ns = self._block
        lines = [f"N{ns} G0 X{self.num(self.axis_value('x', points[0][0]))}"]
        if abs(points[0][1] - float(data["z_start"])) > 1e-9:
            lines.append(f"G1 Z{self.num(points[0][1])}")
        last = points[0]
        for x, z in points[1:]:
            words = []
            if abs(x - last[0]) > 1e-9:
                words.append(f"X{self.num(self.axis_value('x', x))}")
            if abs(z - last[1]) > 1e-9:
                words.append(f"Z{self.num(z)}")
            if words:
                lines.append("G1 " + " ".join(words))
            last = (x, z)
        nf = ns + 10 * (len(lines) - 1)
        if len(lines) > 1:
            lines[-1] = f"N{nf} {lines[-1]}"
        self._block = nf + 10
        return ns, nf, lines
