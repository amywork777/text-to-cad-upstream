"""A small G-code reader for the CAM tests: parse posted text back into moves, with modal state.

Reads G0/G1/G2/G3 (I/J/K centres, incremental; G17/G18/G19), G4, G80 and the canned cycles G81/G82/G83/G73/G84/G85
(and G74/G86/G89/G76 on a mill: their motion is G84's or G85's), G33.1 rigid tapping (feed in, feed back), expanded
the way a controller runs them: rapid over the hole at the current level, rapid to R, feed to Z in pecks for
G83/G73, back to R (G99) or the initial level (G98). G90 only (``G91`` is refused unless the block homes with G28),
G20/G21 (inches scaled to mm), work offsets, F/S/T/M words, and comments in parentheses or after ``;``.

The dialect bits the posts write are read too, backwards compatibly: A/B/C words (a rotary-only line is a move of its
own), ``G28``/``G30`` homes and ``G53`` machine-coordinate moves (recorded in ``homes``, no motion: the IR has
none), ``G92`` (sets the position), tool length and
TCP words (``G43``, ``G43.4``, ``G234``: ``tcp``), tilted planes (``G68.2``: ``tilt``; ``G254``: ``dwo``), wire taper
and compensation (``G51``/``G52``: ``taper``; ``G41``/``G42``: ``comp``; ``U V`` on a move: ``uv``), feed per
revolution (``G95``, or the lathe's ``G99``: ``Move.per_rev``) and an inline laser power ``S`` (``Move.s``).

``read(text, lathe=True)`` reads a lathe program: X is a diameter (``diameter=True``, the default; LinuxCNC's
``G7``/``G8`` switch it) and comes back as the radius the IR stores, I stays a radius, G98/G99 are feed per minute and
per revolution, and the threading and roughing cycles are read: ``G76`` (Fanuc's two blocks, Haas's one block,
LinuxCNC's one block) into ``threads`` (and the final pass at the root as moves), ``G71`` (Fanuc's two blocks or
Haas's one) into ``roughs`` with its profile blocks, which are skipped as motion (the tool ends where it started).
:func:`sample` turns the moves into points for comparing with the IR's own samples.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_DRILL = ("G81", "G82", "G83", "G73", "G84", "G85", "G74", "G86", "G89")
_IGNORED = ("G90", "G94", "G91.1", "G40", "G49", "G64", "G61", "G43", "G53.1", "G69", "G255", "G187", "G7", "G8",
            "G96", "G97", "G50", "G80")


@dataclass
class Move:
    kind: str                        # rapid | feed | arc_cw | arc_ccw | dwell
    start: tuple
    end: tuple
    feed: float = 0.0
    centre: tuple | None = None
    plane: str = "G17"
    line: int = 0
    abc: dict = field(default_factory=dict)
    per_rev: bool = False
    uv: tuple | None = None
    s: float | None = None


@dataclass
class Program:
    moves: list
    tools: list
    spindle: list                    # (rpm, M3/M4/M5)
    coolant: list
    offsets: list
    comments: list
    stops: int = 0
    cycles: list = field(default_factory=list)
    homes: int = 0
    tcp: list = field(default_factory=list)
    tilt: list = field(default_factory=list)
    dwo: int = 0
    taper: list = field(default_factory=list)
    comp: list = field(default_factory=list)
    threads: list = field(default_factory=list)
    roughs: list = field(default_factory=list)
    g92: list = field(default_factory=list)


def _strip(line: str) -> tuple[str, list[str]]:
    comments = re.findall(r"\(([^)]*)\)", line)
    line = re.sub(r"\([^)]*\)", "", line)
    if ";" in line:
        line, tail = line.split(";", 1)
        comments.append(tail.strip())
    return line.strip().upper(), comments


def read(text: str, start=(0.0, 0.0, 0.0), *, lathe: bool = False, diameter: bool = True) -> Program:
    pos = list(start)
    abc = {"A": 0.0, "B": 0.0, "C": 0.0}
    motion, plane, scale, feed, retract = "G0", "G18" if lathe else "G17", 1.0, 0.0, "G98"
    per_rev = False
    cycle: dict | None = None
    thread_first: dict | None = None
    rough_first: dict | None = None
    profile: dict | None = None
    program = Program([], [], [], [], [], [])

    def x_value(value: float) -> float:
        return value / 2.0 if lathe and diameter else value

    def add(kind, end, *, centre=None, number=0, uv=None, s=None):
        program.moves.append(Move(kind, tuple(pos), tuple(end), feed if kind not in ("rapid", "dwell") else 0.0,
                                  centre, plane, number, dict(abc), per_rev and kind != "rapid", uv, s))
        pos[:] = end

    for number, raw in enumerate(text.splitlines(), 1):
        line, comments = _strip(raw)
        program.comments.extend(comments)
        if not line or line == "%":
            continue
        words = [(letter, float(value)) for letter, value in _WORD.findall(line)]
        gs = [f"G{v:g}" for letter, v in words if letter == "G"]
        values = {letter: v for letter, v in words if letter != "G"}
        if profile is not None:
            # Inside a G71's profile blocks: read the points, do not move.
            last = profile["points"][-1] if profile["points"] else (pos[0], pos[2])
            point = (x_value(values["X"]) * scale if "X" in values else last[0],
                     values["Z"] * scale if "Z" in values else last[1])
            profile["points"].append(point)
            if values.get("N") == profile["nf"]:
                program.roughs[-1]["profile"] = profile["points"]
                profile = None
            continue
        explicit_motion = None
        homing = "G28" in gs or "G30" in gs or "G53" in gs
        for code in gs:
            if code in ("G17", "G18", "G19"):
                plane = code
            elif code == "G20":
                scale = 25.4
            elif code == "G21":
                scale = 1.0
            elif code in ("G98", "G99"):
                if lathe:
                    per_rev = code == "G99"
                else:
                    retract = code
            elif code == "G95":
                per_rev = True
            elif code == "G94":
                per_rev = False
            elif code in ("G7", "G8"):
                diameter = code == "G7"
            elif code in ("G54", "G55", "G56", "G57", "G58", "G59"):
                program.offsets.append(code)
            elif code in ("G0", "G1", "G2", "G3", "G33.1") or (code in _DRILL and not lathe) or (
                    code == "G76" and not lathe):
                explicit_motion = code
            elif code == "G80":
                cycle = None
                motion = "G80"
            elif code == "G4":
                program.moves.append(Move("dwell", tuple(pos), tuple(pos), 0.0, None, plane, number))
            elif code in ("G43.4", "G234"):
                program.tcp.append(code)
            elif code == "G68.2":
                program.tilt.append({k: values.get(k, 0.0) for k in "XYZIJK"})
            elif code == "G254":
                program.dwo += 1
            elif code in ("G51", "G52", "G50") and not lathe and "S" not in values:
                program.taper.append((code, values.get("A", 0.0)))
            elif code in ("G41", "G42"):
                program.comp.append((code, values.get("D")))
            elif code in ("G28", "G30", "G53"):
                program.homes += 1
            elif code == "G92":
                pos[0] = values.get("X", pos[0] / scale) * scale
                pos[1] = values.get("Y", pos[1] / scale) * scale
                program.g92.append((pos[0], pos[1]))
            elif code == "G91":
                if not homing:
                    raise ValueError(f"line {number}: incremental G91 is not read")
            elif code in _IGNORED or code in ("G51", "G52", "G50", "G76", "G71", "G70"):
                pass
        if "F" in values:
            feed = values["F"] * (1.0 if per_rev else scale)
        if "T" in values:
            program.tools.append(int(values["T"]))
        if "S" in values or any(letter == "M" and v in (3, 4, 5) for letter, v in words):
            for letter, v in words:
                if letter == "M" and v in (3, 4, 5):
                    program.spindle.append((values.get("S"), f"M{v:g}"))
        for letter, v in words:
            if letter == "M" and v in (7, 8, 9):
                program.coolant.append(f"M{v:g}")
            if letter == "M" and v in (0, 1):
                program.stops += 1
        if homing or "G92" in gs or "G4" in gs or "G68.2" in gs:
            continue
        if lathe and "G76" in gs:
            _thread(program, values, pos, add, number, thread_first, x_value, scale)
            thread_first = None if ("X" in values or "Z" in values) else dict(values)
            continue
        if lathe and "G71" in gs:
            if "P" not in values:
                rough_first = dict(values)
                continue
            depth = values.get("D", (rough_first or {}).get("U", 0.0))
            program.roughs.append({"ns": values["P"], "nf": values["Q"], "depth": depth * scale,
                                   "u": values.get("U", 0.0), "w": values.get("W", 0.0), "start": (pos[0], pos[2]),
                                   "profile": []})
            program.cycles.append("G71")
            profile = {"nf": values["Q"], "points": []}
            rough_first = None
            continue
        if lathe and "G70" in gs:
            continue
        if explicit_motion:
            motion = explicit_motion
            if motion in _DRILL or motion == "G76":
                cycle = {"code": motion, "initial": pos[2], "R": values.get("R", 0.0) * scale,
                         "Z": values.get("Z", 0.0) * scale, "Q": values.get("Q", 0.0) * scale}
                program.cycles.append(motion)
        for axis in "ABC":
            if axis in values:
                abc[axis] = values[axis]
        has_axis = any(axis in values for axis in "XYZ")
        has_rotary = any(axis in values for axis in "ABC")
        uv = (values.get("U", 0.0) * scale, values.get("V", 0.0) * scale) if ("U" in values or "V" in values) \
            and not lathe else None
        if motion == "G33.1" and "Z" in values:
            top = pos[2]
            add("feed", (pos[0], pos[1], values["Z"] * scale), number=number)
            add("feed", (pos[0], pos[1], top), number=number)
            program.cycles.append("G33.1")
            continue
        if (motion in _DRILL or motion == "G76") and cycle is not None and has_axis:
            if explicit_motion is None:
                cycle["R"] = values.get("R", cycle["R"] / scale) * scale
            x = values.get("X", pos[0] / scale) * scale
            y = values.get("Y", pos[1] / scale) * scale
            if "Z" in values:
                cycle["Z"] = values["Z"] * scale
            level = pos[2]
            add("rapid", (x, y, level), number=number)
            add("rapid", (x, y, cycle["R"]), number=number)
            if cycle["code"] in ("G83", "G73") and cycle["Q"] > 0:
                depth = cycle["R"]
                while depth > cycle["Z"] + 1e-9:
                    depth = max(cycle["Z"], depth - cycle["Q"])
                    add("feed", (x, y, depth), number=number)
                    if depth > cycle["Z"] + 1e-9:
                        if cycle["code"] == "G83":
                            # Full retract to R, then rapid back to just over the last depth.
                            add("rapid", (x, y, cycle["R"]), number=number)
                            add("rapid", (x, y, depth + 0.5), number=number)
                        else:
                            add("rapid", (x, y, depth + 0.2), number=number)
            else:
                add("feed", (x, y, cycle["Z"]), number=number)
            back = cycle["initial"] if retract == "G98" else cycle["R"]
            add("feed" if cycle["code"] in ("G84", "G74", "G85", "G89") else "rapid", (x, y, back), number=number)
            continue
        if not has_axis and not has_rotary and uv is None and motion not in ("G2", "G3"):
            continue
        end = list(pos)
        for i, axis in enumerate("XYZ"):
            if axis in values:
                end[i] = (x_value(values[axis]) if i == 0 else values[axis]) * scale
        s = values.get("S") if motion in ("G0", "G1", "G2", "G3") else None
        if motion == "G0":
            add("rapid", end, number=number, uv=uv, s=s)
        elif motion == "G1":
            add("feed", end, number=number, uv=uv, s=s)
        elif motion in ("G2", "G3"):
            u, v = {"G17": (0, 1), "G18": (2, 0), "G19": (1, 2)}[plane]
            offsets = {"G17": ("I", "J"), "G18": ("K", "I"), "G19": ("J", "K")}[plane]
            centre = list(pos)
            centre[u] = pos[u] + values.get(offsets[0], 0.0) * scale
            centre[v] = pos[v] + values.get(offsets[1], 0.0) * scale
            add("arc_cw" if motion == "G2" else "arc_ccw", end, centre=tuple(centre), number=number, uv=uv, s=s)
    return program


def _thread(program, values, pos, add, number, first, x_value, scale) -> None:
    """A lathe G76: record it and add its final pass at the root (rapid in, feed along, rapid out and back)."""
    if "X" not in values and "Z" not in values:
        return                                    # Fanuc's first block: passes, angle, minimum depth
    if "I" in values and "K" in values and "X" not in values:     # LinuxCNC: drive line here, I crest offset, K depth
        crest = pos[0] + x_value(values["I"]) * scale
        depth = x_value(values["K"]) * scale
        root = crest - depth if values["I"] < 0 else crest + depth
        pitch = values["P"] * scale
        dialect = "linuxcnc"
    else:                                         # Fanuc's second block or Haas's one block: X is the root
        root = x_value(values["X"]) * scale
        depth = (values["K"] if "K" in values else values.get("P", 0.0) / 1000.0) * scale
        pitch = values["F"] * scale
        dialect = "haas" if "D" in values else "fanuc"
    z_end = values["Z"] * scale
    clear, z_start = pos[0], pos[2]
    program.threads.append({"dialect": dialect, "root": root, "depth": depth, "pitch": pitch, "z_end": z_end,
                            "x_clear": clear, "z_start": z_start, "first": dict(first or {})})
    program.cycles.append("G76")
    add("rapid", (root, pos[1], z_start), number=number)
    add("feed", (root, pos[1], z_end), number=number)
    add("rapid", (clear, pos[1], z_end), number=number)
    add("rapid", (clear, pos[1], z_start), number=number)


def sample(program: Program, chord: float = 0.005, max_step: float | None = None):
    """(points (N, 3), kinds) along every move; arcs split within ``chord``, lines into pieces no longer than
    ``max_step`` when one is given."""
    import numpy as np

    points, kinds = [], []
    for move in program.moves:
        if move.kind == "dwell":
            continue
        if move.kind in ("arc_cw", "arc_ccw"):
            u, v, w = {"G17": (0, 1, 2), "G18": (2, 0, 1), "G19": (1, 2, 0)}[move.plane]
            c = move.centre
            a0 = math.atan2(move.start[v] - c[v], move.start[u] - c[u])
            a1 = math.atan2(move.end[v] - c[v], move.end[u] - c[u])
            radius = math.hypot(move.start[u] - c[u], move.start[v] - c[v])
            sweep = a1 - a0
            if move.kind == "arc_cw":
                while sweep >= -1e-9:
                    sweep -= 2 * math.pi
            else:
                while sweep <= 1e-9:
                    sweep += 2 * math.pi
            step = 2 * math.acos(max(-1.0, 1 - chord / radius)) if radius > chord else math.pi / 2
            count = max(2, int(math.ceil(abs(sweep) / step)))
            if max_step:
                length = math.hypot(radius * abs(sweep), move.end[w] - move.start[w])
                count = max(count, int(math.ceil(length / max_step)))
            for k in range(1, count + 1):
                angle = a0 + sweep * k / count
                p = [0.0, 0.0, 0.0]
                p[u] = c[u] + radius * math.cos(angle)
                p[v] = c[v] + radius * math.sin(angle)
                p[w] = move.start[w] + (move.end[w] - move.start[w]) * k / count
                points.append(p)
                kinds.append(move.kind)
        else:
            length = math.dist(move.start, move.end)
            count = max(1, int(math.ceil(length / max_step))) if max_step else 1
            for k in range(1, count + 1):
                points.append([a + (b - a) * k / count for a, b in zip(move.start, move.end)])
                kinds.append(move.kind)
    return np.asarray(points, dtype=float), kinds


def posted_text(result, setup: str | None = None) -> str:
    """Every file a ``cam.plan`` result posted for ``setup`` (default: the first setup), joined in program order: a
    post that writes one file per tool (GRBL) splits a setup, and the files read back as one program."""
    from pathlib import Path

    setup = setup if setup is not None else result.posts[0]["setup"]
    return "".join(Path(p["file"]).read_text(encoding="utf-8") for p in result.posts if p["setup"] == setup)
