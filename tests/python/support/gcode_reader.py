"""A small G-code reader for the CAM tests: parse posted text back into moves, with modal state.

Reads G0/G1/G2/G3 (I/J/K centres, incremental; G17/G18/G19), G4, G80 and the canned cycles G81/G82/G83/G73/G84/G85
(expanded the way a controller runs them: rapid over the hole at the current level, rapid to R, feed to Z in pecks
for G83/G73, back to R (G99) or the initial level (G98)), G90 only, G20/G21 (inches scaled to mm), work offsets,
F/S/T/M words, and comments in parentheses or after ``;``. :func:`sample` turns the moves into points for comparing
with the IR's own samples.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


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


def _strip(line: str) -> tuple[str, list[str]]:
    comments = re.findall(r"\(([^)]*)\)", line)
    line = re.sub(r"\([^)]*\)", "", line)
    if ";" in line:
        line, tail = line.split(";", 1)
        comments.append(tail.strip())
    return line.strip().upper(), comments


def read(text: str, start=(0.0, 0.0, 0.0)) -> Program:
    pos = list(start)
    abc = {"A": 0.0, "B": 0.0, "C": 0.0}
    motion, plane, scale, feed, retract = "G0", "G17", 1.0, 0.0, "G98"
    cycle: dict | None = None
    program = Program([], [], [], [], [], [])

    def add(kind, end, *, centre=None, number=0):
        program.moves.append(Move(kind, tuple(pos), tuple(end), feed if kind != "rapid" else 0.0, centre, plane,
                                  number, dict(abc)))
        pos[:] = end

    for number, raw in enumerate(text.splitlines(), 1):
        line, comments = _strip(raw)
        program.comments.extend(comments)
        if not line or line == "%":
            continue
        words = [(letter, float(value)) for letter, value in _WORD.findall(line)]
        gs = [v for letter, v in words if letter == "G"]
        values = {letter: v for letter, v in words if letter != "G"}
        explicit_motion = None
        for g in gs:
            code = f"G{g:g}"
            if code in ("G17", "G18", "G19"):
                plane = code
            elif code == "G20":
                scale = 25.4
            elif code == "G21":
                scale = 1.0
            elif code in ("G98", "G99"):
                retract = code
            elif code.startswith("G5") and code in ("G54", "G55", "G56", "G57", "G58", "G59"):
                program.offsets.append(code)
            elif code in ("G0", "G1", "G2", "G3", "G81", "G82", "G83", "G73", "G84", "G85"):
                explicit_motion = code
            elif code == "G80":
                cycle = None
                motion = "G80"
            elif code == "G4":
                program.moves.append(Move("dwell", tuple(pos), tuple(pos), 0.0, None, plane, number))
            elif code in ("G90", "G94", "G91.1", "G40", "G49", "G64", "G61"):
                pass
            elif code == "G91":
                raise ValueError(f"line {number}: incremental G91 is not read")
        if "F" in values:
            feed = values["F"] * scale
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
        if explicit_motion:
            motion = explicit_motion
            if motion in ("G81", "G82", "G83", "G73", "G84", "G85"):
                cycle = {"code": motion, "initial": pos[2], "R": values.get("R", 0.0) * scale,
                         "Z": values.get("Z", 0.0) * scale, "Q": values.get("Q", 0.0) * scale}
                program.cycles.append(motion)
        for axis in "ABC":
            if axis in values:
                abc[axis] = values[axis]
        has_axis = any(axis in values for axis in "XYZ")
        if "G4" in [f"G{g:g}" for g in gs]:
            continue
        if motion in ("G81", "G82", "G83", "G73", "G84", "G85") and cycle is not None and has_axis:
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
            add("feed" if cycle["code"] in ("G84", "G85") else "rapid", (x, y, back), number=number)
            continue
        if not has_axis and motion not in ("G2", "G3"):
            continue
        end = [values.get(axis, pos[i] / scale) * scale if axis in values else pos[i] for i, axis in enumerate("XYZ")]
        if motion == "G0":
            add("rapid", end, number=number)
        elif motion == "G1":
            add("feed", end, number=number)
        elif motion in ("G2", "G3"):
            u, v = {"G17": (0, 1), "G18": (2, 0), "G19": (1, 2)}[plane]
            offsets = {"G17": ("I", "J"), "G18": ("K", "I"), "G19": ("J", "K")}[plane]
            centre = list(pos)
            centre[u] = pos[u] + values.get(offsets[0], 0.0) * scale
            centre[v] = pos[v] + values.get(offsets[1], 0.0) * scale
            add("arc_cw" if motion == "G2" else "arc_ccw", end, centre=tuple(centre), number=number)
    return program


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
