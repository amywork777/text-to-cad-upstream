"""Sketch mode's tools that change what is drawn, as SolidWorks' Sketch tab names them: Sketch
Fillet, Offset Entities, Mirror Entities, Trim Entities and Convert Entities, each written as lines
of the sketch's block (``sketching.py`` writes the strokes, relations and dimensions).

- A fillet is one line, ``sketch1.fillet(line1, line2, 3)``: the corner keeps its virtual sharp.
- An offset is the offset curves, drawn where the offset puts them, and the one relation that
  holds them there, ``sketch1.offset_entities([line9, ...], [line1, ...], 2)``.
- A mirror is the mirrored curves and the relations a CAD tool gives them: each new point
  ``symmetric`` to its own about the line, a point on the line shared, an arc or a circle
  ``equal`` to its own.
- A trim cuts a curve back to where other curves cross it: an end moved, a line or an arc split in
  two, or a circle made an arc, each new end kept on the curve it was cut at.
- A convert is one line, ``converted1 = sketch1.convert(<edges>)``: the model's edges, by
  build123d's selectors on the body, projected onto the sketch and held On Edge there.

Everything is worked out from the sketch as it last solved (its state); the tracer runs the
block again, and takes back any relation a tool wrote that the sketch did not need.
"""

from __future__ import annotations

import ast
import math

from cadgen.edit.sketching import (
    GEOMETRY,
    Names,
    SketchEditError,
    TextEdits,
    _call_of,
    _construction_edits,
    _keyword,
    _segment,
    _typed,
    _Vars,
    find_block,
    number,
)

# How near, as a share of the sketch's size, two places are one.
_NEAR = 1e-6


class _Shape:
    """The sketch's solved places: each point's, and each drawn curve's (a fillet's arc aside)."""

    def __init__(self, state: dict):
        self.points = {point["id"]: (float(point["x"]), float(point["y"])) for point in state.get("points", [])}
        self.curves = {curve["id"]: curve for curve in state.get("curves", []) if not curve.get("derived")}
        self.scale = max([1.0, *(abs(c) for place in self.points.values() for c in place)])
        self.tolerance = _NEAR * self.scale * 10

    def at(self, point: str) -> tuple[float, float]:
        return self.points[point]

    def curve(self, name: str) -> dict:
        curve = self.curves.get(name)
        if curve is None:
            raise SketchEditError(f"{name} is no longer in the sketch. Look again.")
        return curve

    def near(self, a, b) -> bool:
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= self.tolerance


def _place(point) -> str:
    return f"({number(point[0])}, {number(point[1])})"


def _built(curve: dict) -> str:
    return ", construction=True" if curve.get("construction") else ""


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _scale(a, s):
    return (a[0] * s, a[1] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _unit(a):
    length = math.hypot(a[0], a[1]) or 1.0
    return (a[0] / length, a[1] / length)


def _append(text: str, block, written: list[str]) -> str:
    edits = TextEdits(text)
    edits.insert_after(block.last_line, [f"{block.indent}{each}" for each in written])
    return edits.apply()


# ---------------------------------------------------------------------------------------------
# Sketch Fillet.


def fillet(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """A corner rounded: picked as the point where two lines meet (``corner``) or as the two lines
    (``lines``), with a ``radius`` as typed (a number, or a size's name)."""
    block = find_block(text, line, path)
    names = Names(block, state)
    a, b = _corner_lines(state, op, "round")
    return _append(text, block, [f"{block.var}.fillet({names.curve(a)}, {names.curve(b)}, {_typed(op.get('radius'))})"])


def chamfer(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """A corner cut at equal distances: picked as a corner or as two lines, as a fillet is, with a
    ``distance`` as typed."""
    block = find_block(text, line, path)
    names = Names(block, state)
    a, b = _corner_lines(state, op, "cut")
    return _append(text, block, [f"{block.var}.chamfer({names.curve(a)}, {names.curve(b)}, {_typed(op.get('distance'))})"])


def _corner_lines(state: dict, op: dict, verb: str) -> tuple[str, str]:
    """The two lines a corner tool takes: those meeting at the point picked (``corner``), or the
    two lines picked (``lines``), which must meet at an end."""
    shape = _Shape(state)
    lines = [name for name, curve in shape.curves.items() if curve["kind"] == "line"]
    tool = "fillet rounds" if verb == "round" else "chamfer cuts"
    if op.get("corner"):
        corner = str(op["corner"])
        meeting = [name for name in lines if corner in (shape.curves[name]["start"], shape.curves[name]["end"])]
        if len(meeting) != 2:
            raise SketchEditError(f"{corner} is not a corner where two lines meet. Click a corner, or two lines that meet.")
        return meeting[0], meeting[1]
    picked = [str(name) for name in op.get("lines") or []]
    if len(picked) != 2 or not all(name in lines for name in picked):
        raise SketchEditError(f"A sketch {tool} the corner of two lines. Click a corner, or two lines that meet.")
    a, b = picked
    if not {shape.curves[a]["start"], shape.curves[a]["end"]} & {shape.curves[b]["start"], shape.curves[b]["end"]}:
        raise SketchEditError(f"{a} and {b} do not meet at an end, so there is no corner to {verb}.")
    return a, b


# ---------------------------------------------------------------------------------------------
# Offset Entities.


class _Joints:
    """Which of the sketch's points are one place: the same point, a coincident pair of points,
    or points solved to one place."""

    def __init__(self, shape: _Shape, state: dict):
        self.parent: dict[str, str] = {}
        for relation in state.get("relations", []):
            refs = relation.get("refs") or []
            if relation.get("kind") == "coincident" and len(refs) == 2 and all(ref in shape.points for ref in refs):
                self.join(*refs)
        ids = list(shape.points)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if shape.near(shape.points[a], shape.points[b]):
                    self.join(a, b)

    def root(self, point: str) -> str:
        while self.parent.get(point, point) != point:
            point = self.parent[point]
        return point

    def join(self, a: str, b: str) -> None:
        ra, rb = self.root(a), self.root(b)
        if ra != rb:
            self.parent[rb] = ra


def _chain(shape: _Shape, state: dict, items: list[str]) -> tuple[list[tuple[str, bool]], bool]:
    """The picked lines and arcs in order end to end, each with whether it is followed from its
    start (``forward``), and whether the chain closes."""
    joints = _Joints(shape, state)
    ends = {name: (joints.root(shape.curves[name]["start"]), joints.root(shape.curves[name]["end"])) for name in items}
    meeting: dict[str, list[str]] = {}
    for name, (a, b) in ends.items():
        meeting.setdefault(a, []).append(name)
        meeting.setdefault(b, []).append(name)
    if any(len(curves) > 2 for curves in meeting.values()):
        raise SketchEditError("Those entities branch. Offset Entities takes one chain of lines and arcs at a time.")
    loose = [node for node, curves in meeting.items() if len(curves) == 1]
    first = next((curves[0] for node, curves in meeting.items() if node in loose), items[0])
    at = ends[first][0] if not loose or ends[first][0] in loose else ends[first][1]
    order, unused = [], list(items)
    curve = first
    while curve is not None:
        unused.remove(curve)
        forward = ends[curve][0] == at
        order.append((curve, forward))
        at = ends[curve][1] if forward else ends[curve][0]
        curve = next((each for each in meeting.get(at, []) if each in unused), None)
    if unused:
        raise SketchEditError("Those entities are not one chain. Offset Entities takes one connected chain at a time.")
    return order, not loose


def _arc_turn(curve: dict, forward: bool) -> float:
    """Which way a chain follows an arc: 1 counterclockwise, -1 clockwise."""
    turn = -1.0 if curve.get("clockwise") else 1.0
    return turn if forward else -turn


def _meet(first: dict, second: dict, near) -> tuple[float, float] | None:
    """Where two offset curves cross (each a line through two places, or a circle), nearest ``near``."""
    if first["kind"] == "line" and second["kind"] == "line":
        p, d = first["p"], _sub(first["q"], first["p"])
        q, e = second["p"], _sub(second["q"], second["p"])
        across = _cross(d, e)
        if abs(across) < 1e-12:
            return None
        t = _cross(_sub(q, p), e) / across
        return _add(p, _scale(d, t))
    if first["kind"] == "line" or second["kind"] == "line":
        line, circle = (first, second) if first["kind"] == "line" else (second, first)
        found = _line_circle(line["p"], line["q"], circle["c"], circle["r"])
    else:
        found = _circle_circle(first["c"], first["r"], second["c"], second["r"])
    return min(found, key=lambda point: math.hypot(point[0] - near[0], point[1] - near[1])) if found else None


def _line_circle(p, q, c, r):
    """Where the line through ``p`` and ``q`` crosses a circle: as parameters along it, places."""
    d = _sub(q, p)
    f = _sub(p, c)
    a, b, k = _dot(d, d), 2 * _dot(f, d), _dot(f, f) - r * r
    disc = b * b - 4 * a * k
    if a < 1e-24 or disc < -1e-12 * max(1.0, b * b):
        return []
    root = math.sqrt(max(0.0, disc))
    return [_add(p, _scale(d, t)) for t in sorted({(-b - root) / (2 * a), (-b + root) / (2 * a)})]


def _circle_circle(c1, r1, c2, r2):
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < 1e-12 or d > r1 + r2 + 1e-12 or d < abs(r1 - r2) - 1e-12:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    m = _add(c1, _scale(_sub(c2, c1), a / d))
    n = (-(c2[1] - c1[1]) / d, (c2[0] - c1[0]) / d)
    return [_add(m, _scale(n, h)), _add(m, _scale(n, -h))] if h > 1e-12 else [m]


def offset(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """The picked entities offset by ``distance`` (typed), as Offset Entities offsets them: a chain
    of lines and arcs, or a circle, outward when it closes (the other way when ``reverse``), to its
    left as it runs when it is open. Each corner of the offset is where its two curves meet."""
    block = find_block(text, line, path)
    names = Names(block, state)
    shape = _Shape(state)
    items = list(dict.fromkeys(str(item) for item in op.get("items") or [] if str(item) in shape.curves))
    if not items:
        raise SketchEditError("Select a line, an arc or a circle to offset.")
    typed = _typed(op.get("distance"))
    try:
        distance = float(op.get("value") if op.get("value") is not None else typed)
    except (TypeError, ValueError):
        raise SketchEditError("Type the offset as a number.") from None
    if distance <= 0:
        raise SketchEditError("An offset must be more than zero.")
    flip = -1.0 if op.get("reverse") else 1.0
    s = block.var
    vars_ = _Vars(block, state)
    own = op.get("construction")

    def built(curve: dict) -> str:
        # Offset geometry made construction or not when asked, else as its base is.
        return _built(curve) if own is None else (", construction=True" if own else "")
    circles = [name for name in items if shape.curves[name]["kind"] == "circle"]
    if circles:
        if len(items) != 1:
            raise SketchEditError("Offset a circle on its own, or one chain of lines and arcs.")
        curve = shape.curves[circles[0]]
        radius = float(curve["radius"]) + flip * distance
        if radius <= shape.tolerance:
            raise SketchEditError(f"An offset of {number(distance)} is more than {curve['id']}'s radius.")
        var = vars_.next("Circle")
        return _offset_written(text, block, names, items, op, [f"{var} = {s}.circle({names.point(curve['center'])}, {number(radius)}{built(curve)})",
                                     f"{s}.offset_entities({var}, {names.curve(curve['id'])}, {typed})"])
    order, closed = _chain(shape, state, items)

    # Each piece where the offset puts it, followed the way the chain runs.
    def ends_of(name: str, forward: bool):
        curve = shape.curves[name]
        a, b = shape.at(curve["start"]), shape.at(curve["end"])
        return (a, b) if forward else (b, a)

    if closed:
        polygon = []
        for name, forward in order:
            curve = shape.curves[name]
            a, b = ends_of(name, forward)
            if curve["kind"] == "arc":
                c = shape.at(curve["center"])
                a0 = math.atan2(a[1] - c[1], a[0] - c[0])
                sweep = (math.atan2(b[1] - c[1], b[0] - c[0]) - a0) * 1.0
                turn = _arc_turn(curve, forward)
                sweep = sweep % (2 * math.pi) if turn > 0 else -((-sweep) % (2 * math.pi))
                polygon += [_add(c, _scale((math.cos(a0 + sweep * i / 8), math.sin(a0 + sweep * i / 8)), float(curve["radius"]))) for i in range(8)]
            else:
                polygon.append(a)
        area = 0.5 * sum(_cross(p, q) for p, q in zip(polygon, polygon[1:] + polygon[:1]))
        side = (-1.0 if area > 0 else 1.0) * flip  # outward: right of a counterclockwise chain
    elif len(order) == 1 and shape.curves[order[0][0]]["kind"] == "arc":
        curve = shape.curves[order[0][0]]
        side = (-1.0 if not curve.get("clockwise") else 1.0) * flip  # an arc alone: bigger
        order = [(order[0][0], True)]
    else:
        side = flip
    pieces = []
    for name, forward in order:
        curve = shape.curves[name]
        a, b = ends_of(name, forward)
        if curve["kind"] == "line":
            d = _unit(_sub(b, a))
            n = (-d[1] * side * distance, d[0] * side * distance)
            pieces.append({"name": name, "kind": "line", "forward": forward, "p": _add(a, n), "q": _add(b, n), "d": d})
        else:
            c = shape.at(curve["center"])
            r = float(curve["radius"])
            # To the left of a counterclockwise run is toward the center.
            radius = r - side * distance * _arc_turn(curve, forward)
            if radius <= shape.tolerance:
                raise SketchEditError(f"An offset of {number(distance)} is more than {name}'s radius.")
            grow = radius / r
            pieces.append({"name": name, "kind": "arc", "forward": forward, "c": c, "r": radius,
                           "p": _add(c, _scale(_sub(a, c), grow)), "q": _add(c, _scale(_sub(b, c), grow))})
    # The corners: where each piece meets the next, where they are not tangent already.
    joints = len(pieces) if closed else len(pieces) - 1
    for index in range(joints):
        here, there = pieces[index], pieces[(index + 1) % len(pieces)]
        if shape.near(here["q"], there["p"]):
            there["p"] = here["q"]
            continue
        met = _meet(here, there, _scale(_add(here["q"], there["p"]), 0.5))
        if met is None:
            raise SketchEditError(f"The offsets of {here['name']} and {there['name']} do not meet. Try a smaller offset.")
        here["q"] = there["p"] = met
    for piece in pieces:
        if piece["kind"] == "line" and _dot(_sub(piece["q"], piece["p"]), piece["d"]) <= shape.tolerance:
            raise SketchEditError(f"An offset of {number(distance)} is more than {piece['name']} can take. Try a smaller one.")
    # Written in each source's own direction, each corner shared by the pieces that meet there.
    written, made, codes = [], [], {}

    def point_code(place, var, role):
        key = (round(place[0] / shape.tolerance), round(place[1] / shape.tolerance))
        if key in codes:
            return codes[key]
        codes[key] = f"{var}.{role}"
        return _place(place)

    for piece in pieces:
        curve = shape.curves[piece["name"]]
        start, end = (piece["p"], piece["q"]) if piece["forward"] else (piece["q"], piece["p"])
        if curve["kind"] == "line":
            var = vars_.next("Line")
            written.append(f"{var} = {s}.line({point_code(start, var, 'start')}, {point_code(end, var, 'end')}{built(curve)})")
        else:
            var = vars_.next("Arc")
            turn = ", clockwise=True" if curve.get("clockwise") else ""
            written.append(f"{var} = {s}.arc({names.point(curve['center'])}, {point_code(start, var, 'start')}, "
                           f"{point_code(end, var, 'end')}{turn}{built(curve)})")
        made.append(var)
    sources = [names.curve(piece["name"]) for piece in pieces]
    if len(made) == 1:
        written.append(f"{s}.offset_entities({made[0]}, {sources[0]}, {typed})")
    else:
        written.append(f"{s}.offset_entities([{', '.join(made)}], [{', '.join(sources)}], {typed})")
    return _offset_written(text, block, names, items, op, written)


def _offset_written(text: str, block, names, items: list[str], op: dict, written: list[str]) -> str:
    """The offset written after the sketch's last line, its base geometry made construction first when
    ``base`` asks, as Offset Entities' Construction geometry options make it."""
    edits = TextEdits(text)
    if op.get("base"):
        _construction_edits(block, names, edits, items, True)
    edits.insert_after(block.last_line, [f"{block.indent}{each}" for each in written])
    return edits.apply()


# ---------------------------------------------------------------------------------------------
# Mirror Entities.


def mirror(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """The picked entities mirrored about a line (``about``: a centerline, usually), as Mirror
    Entities copies them: each new point symmetric to its own, a point on the line shared rather
    than copied, each arc and circle equal to its own, and a fillet between two mirrored lines
    mirrored too."""
    block = find_block(text, line, path)
    names = Names(block, state)
    shape = _Shape(state)
    about = str(op.get("about") or "")
    axis = shape.curves.get(about)
    if axis is None or axis["kind"] != "line":
        raise SketchEditError("Mirror about a line: a centerline, usually.")
    items = [str(item) for item in op.get("items") or [] if str(item) != about]
    curves = [name for name in items if name in shape.curves]
    loose = [name for name in items if name in shape.points and name != "Origin"
             and not any(name in (shape.curves[c].get("start"), shape.curves[c].get("end"), shape.curves[c].get("center")) for c in curves)]
    if not curves and not loose:
        raise SketchEditError("Select the entities to mirror, then the line to mirror about.")
    a, b = shape.at(axis["start"]), shape.at(axis["end"])
    d = _unit(_sub(b, a))

    def reflected(place):
        foot = _add(a, _scale(d, _dot(_sub(place, a), d)))
        return _sub(_scale(foot, 2), place)

    def on_axis(place):
        return abs(_cross(d, _sub(place, a))) <= shape.tolerance

    s = block.var
    vars_ = _Vars(block, state)
    axis_code = names.curve(about)
    written, relations = [], []
    mirrored: dict[str, str] = {}  # a point, to the code of its mirror once written
    symmetric: list[str] = []  # the points whose mirrors are held symmetric, in order

    def point_of(point: str, var: str, role: str, held: bool) -> str:
        """A point's mirror as the new entity names it: the point itself on the line, the mirror
        another new entity has already, or a place written here."""
        place = shape.at(point)
        if on_axis(place):
            code = names.point(point)
            if code is None:
                raise SketchEditError(f"{point} has no name in the script, so edit mode cannot mirror what meets it. Ask the agent.")
            return code
        if point in mirrored:
            if held and point not in symmetric:
                symmetric.append(point)
            return mirrored[point]
        mirrored[point] = f"{var}.{role}"
        if held:
            symmetric.append(point)
        return _place(reflected(place))

    def own_mirror(curve: dict) -> bool:
        """A curve the line mirrors onto itself: a line along it, a circle or an arc centered on it
        and turned across it alike."""
        if curve["kind"] == "line":
            return on_axis(shape.at(curve["start"])) and on_axis(shape.at(curve["end"]))
        if not on_axis(shape.at(curve["center"])):
            return False
        return curve["kind"] == "circle" or shape.near(reflected(shape.at(curve["start"])), shape.at(curve["end"]))

    made: dict[str, str] = {}
    for name in curves:
        curve = shape.curves[name]
        kind = curve["kind"]
        if own_mirror(curve):
            continue
        if kind == "line":
            var = vars_.next("Line")
            written.append(f"{var} = {s}.line({point_of(curve['start'], var, 'start', True)}, {point_of(curve['end'], var, 'end', True)}{_built(curve)})")
        elif kind == "circle":
            var = vars_.next("Circle")
            written.append(f"{var} = {s}.circle({point_of(curve['center'], var, 'center', True)}, {number(curve['radius'])}{_built(curve)})")
            relations.append(f"{s}.equal({var}, {names.curve(name)})")
        else:
            var = vars_.next("Arc")
            # A mirror turns the other way: from the mirror of its end to the mirror of its start.
            turn = ", clockwise=True" if curve.get("clockwise") else ""
            center = point_of(curve["center"], var, "center", False)
            written.append(f"{var} = {s}.arc({center}, {point_of(curve['end'], var, 'start', True)}, "
                           f"{point_of(curve['start'], var, 'end', True)}{turn}{_built(curve)})")
            relations.append(f"{s}.equal({var}, {names.curve(name)})")
        made[name] = var
    for name in loose:
        var = vars_.next("Point")
        place = reflected(shape.at(name))
        written.append(f"{var} = {s}.point({number(place[0])}, {number(place[1])})")
        mirrored[name] = var
        symmetric.append(name)
    if not made and not loose:
        raise SketchEditError(f"What is selected lies on {about}, so it is its own mirror.")
    for point in symmetric:
        relations.append(f"{s}.symmetric({names.point(point)}, {mirrored[point]}, {axis_code})")
    # A fillet or a chamfer between two mirrored lines, mirrored with the same size.
    for dimension in state.get("dimensions", []):
        refs = dimension.get("refs") or []
        if dimension.get("kind") in ("fillet", "chamfer") and len(refs) == 2 and all(ref in made for ref in refs):
            statement = names.statement_of(dimension["id"])
            call = _call_of(statement.statement, s) if statement is not None else None
            if call is not None and len(call.args) == 3:
                relations.append(f"{s}.{dimension['kind']}({made[refs[0]]}, {made[refs[1]]}, {_segment(text, call.args[2])})")
    return _append(text, block, written + relations)


# ---------------------------------------------------------------------------------------------
# Convert Entities.


def convert(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """Edges of the model brought into the sketch, as Convert Entities brings them: ``edges`` is
    their selector on the body where the sketch is made (the tracer writes it, on the part as its
    script makes it there), written as one line, ``converted1 = sketch2.convert(<edges>)``, whose
    curves stay on the model's edges as it changes."""
    block = find_block(text, line, path)
    edges = str(op.get("edges") or "").strip()
    if not edges:
        raise SketchEditError("Select edges or a face on the model to convert.")
    var = _Vars(block, state).next("Converted")
    built = ", construction=True" if op.get("construction") else ""
    return _append(text, block, [f"{var} = {block.var}.convert({edges}{built})"])


# ---------------------------------------------------------------------------------------------
# Trim Entities.


class _Round:
    """An arc or a circle of the solved sketch, for finding where along it a place is: from its
    start, the way it turns, in radians (a circle from its right, counterclockwise)."""

    def __init__(self, shape: _Shape, curve: dict):
        self.c = shape.at(curve["center"])
        if curve["kind"] == "circle":
            self.r, self.a0, self.turn, self.sweep = float(curve["radius"]), 0.0, 1.0, 2 * math.pi
        else:
            s, e = shape.at(curve["start"]), shape.at(curve["end"])
            self.r = math.hypot(s[0] - self.c[0], s[1] - self.c[1])
            self.a0 = math.atan2(s[1] - self.c[1], s[0] - self.c[0])
            self.turn = -1.0 if curve.get("clockwise") else 1.0
            a1 = math.atan2(e[1] - self.c[1], e[0] - self.c[0])
            self.sweep = ((a1 - self.a0) * self.turn) % (2 * math.pi) or 2 * math.pi

    def along(self, place) -> float:
        angle = math.atan2(place[1] - self.c[1], place[0] - self.c[0])
        return ((angle - self.a0) * self.turn) % (2 * math.pi)

    def place(self, along: float):
        angle = self.a0 + self.turn * along
        return (self.c[0] + self.r * math.cos(angle), self.c[1] + self.r * math.sin(angle))


def _on(shape: _Shape, curve: dict, place, inclusive: bool = True) -> float | None:
    """Where along a curve a place is (a line from 0 to 1, an arc in radians from its start), or
    None when the place is off it."""
    if curve["kind"] == "line":
        a, b = shape.at(curve["start"]), shape.at(curve["end"])
        d = _sub(b, a)
        length = math.hypot(*d)
        t = _dot(_sub(place, a), d) / (length * length or 1.0)
        slack = shape.tolerance / (length or 1.0)
        if inclusive:
            return t if -slack <= t <= 1 + slack else None
        return t if slack < t < 1 - slack else None
    round_ = _Round(shape, curve)
    along = round_.along(place)
    slack = shape.tolerance / (round_.r or 1.0)
    if curve["kind"] == "circle":
        return along
    if along > 2 * math.pi - slack:
        along -= 2 * math.pi
    if inclusive:
        return along if -slack <= along <= round_.sweep + slack else None
    return along if slack < along < round_.sweep - slack else None


def _meetings(shape: _Shape, curve: dict, other: dict):
    """Where two curves of the sketch meet, each as drawn (a line's ends, an arc's sweep)."""
    def full(item):
        if item["kind"] == "line":
            return {"kind": "line", "p": shape.at(item["start"]), "q": shape.at(item["end"])}
        round_ = _Round(shape, item)
        return {"kind": "circle", "c": round_.c, "r": round_.r}

    first, second = full(curve), full(other)
    if first["kind"] == "line" and second["kind"] == "line":
        met = _meet(first, second, first["p"])
        found = [met] if met is not None else []
    elif first["kind"] == "line" or second["kind"] == "line":
        line, circle = (first, second) if first["kind"] == "line" else (second, first)
        found = _line_circle(line["p"], line["q"], circle["c"], circle["r"])
    else:
        found = _circle_circle(first["c"], first["r"], second["c"], second["r"])
    return [place for place in found if _on(shape, curve, place) is not None and _on(shape, other, place) is not None]


class _Trim:
    """One trim's changes to the text: the trimmed curve's ends moved or the curve taken out, the
    statements after it that named a point it no longer has pointed where that point went, and
    what is written after the block (new curves, the statements moved after them, new relations)."""

    def __init__(self, text: str, block, names: Names, shape: _Shape, state: dict, name: str):
        self.text, self.block, self.names, self.shape, self.state = text, block, names, shape, state
        self.name = name
        self.curve = shape.curve(name)
        self.made = names.statement_of(name)
        self.code = names.curve(name)
        self.index = names.made_by[name]
        self.call = _call_of(self.made.statement, block.var)
        self.edits = TextEdits(text)
        self.written: list[str] = []  # new curves, after the block
        self.later: list[str] = []  # new relations, after the moved statements
        self.moves: dict[int, list] = {}  # statements written again after the new curves: their swaps
        self.dropped: set[int] = set()
        self.vars = _Vars(block, state)

    def references(self, role: str | None):
        """Each later statement naming the trimmed curve (``role`` None) or one of its points, with
        the nodes that name it."""
        found = []
        for index in range(self.index + 1, self.block.end + 1):
            statement = self.block.body[index]
            values = {id(node.value) for node in ast.walk(statement) if isinstance(node, ast.Attribute)}
            nodes = [node for node in ast.walk(statement)
                     if (role is None and isinstance(node, (ast.Name, ast.Subscript)) and id(node) not in values
                         and _segment(self.text, node) == self.code)
                     or (role is not None and isinstance(node, ast.Attribute) and node.attr == role
                         and _segment(self.text, node.value) == self.code)]
            if nodes:
                found.append((index, nodes))
        return found

    def move(self, index: int, swaps: list) -> None:
        self.moves.setdefault(index, []).extend(swaps)

    def drop(self, index: int) -> None:
        self.dropped.add(index)

    def gone(self, index: int) -> bool:
        return index in self.dropped or index in self.moves

    def point_code(self, point: str, before: int | None = None) -> str | None:
        """A code for a point from a statement that stays (before ``before``), not the trimmed curve's."""
        for at, code in self.names.point_code.get(point, []):
            if (before is None or at < before) and at != self.index and not self.gone(at):
                return code
        return None

    def rehome(self, role: str, point: str, keeps: str | None, shared: str | None) -> str | None:
        """The trimmed curve's ``role`` point is no longer its own: each later statement that named
        it so names it where it now is. ``shared`` is its code when the curve only shared it (from
        a curve before); ``keeps`` the code of a new curve that takes it (a split's second piece).
        A curve drawn from it keeps it where it is: the first such takes it as its own place, and
        the rest share that. A relation on it moves after ``keeps``, or goes when there is none.
        Returns the point's code for what is written after the block, or None."""
        owner = shared
        place = _place(self.shape.at(point))
        for index, nodes in self.references(role):
            if self.gone(index):
                continue
            if owner is not None:
                for node in nodes:
                    self.edits.replace_node(node, owner)
                continue
            made = self.names.made[index - self.block.start - 1]
            if made.method in GEOMETRY:
                for node in nodes:
                    self.edits.replace_node(node, place)
                owner = next((code for at, code in self.names.point_code.get(point, []) if at == index), None)
                continue
            if keeps is not None:
                self.move(index, [(node, keeps) for node in nodes])
            else:
                self.drop(index)
        return owner

    def end_at(self, role: str, crossing: dict, *, own: bool, var: str | None = None) -> str:
        """The code a new end at a crossing is written as, with what keeps it there: a point already
        at the crossing (an end of the curve that crosses), shared where it can be named; else the
        place, held on that curve. ``own``: the trimmed curve's end, in its own statement (a point
        named only after it cannot be shared); else the end of ``var``, a new curve."""
        s = self.block.var
        target = f"{self.code}.{role}" if own else f"{var}.{role}"
        point = crossing.get("point")
        if point:
            for relation in self.state.get("relations", []):
                # A point that was on the trimmed curve is its end now, held there already.
                if relation.get("kind") == "coincident" and relation.get("refs") == [point, self.name]:
                    at = self.names.made_by.get(relation["id"])
                    if at is not None and at != self.index:
                        self.drop(at)
            code = self.point_code(point, before=self.index if own else None)
            if code is not None:
                return code
            other = self.point_code(point)
            if other is not None:
                self.later.append(f"{s}.coincident({target}, {other})")
                return _place(crossing["place"])
        held = next((self.names.curve_code[c] for c in crossing["curves"] if c in self.names.curve_code), None)
        if held is None:
            raise SketchEditError(f"{crossing['curves'][0]} has no name in the script, so edit mode cannot keep a trimmed end on it. Ask the agent.")
        self.later.append(f"{s}.coincident({target}, {held})")
        return _place(crossing["place"])

    def rewritten(self, index: int, swaps: list) -> str:
        """A statement's own text with nodes put as other code, to write it after the block."""
        statement = self.block.body[index]
        lines = self.text.splitlines(keepends=True)[statement.lineno - 1:statement.end_lineno]
        encoded = [line.encode("utf-8") for line in lines]
        seen = set()
        for node, code in sorted(swaps, key=lambda swap: (swap[0].lineno, swap[0].col_offset), reverse=True):
            if id(node) in seen:
                continue
            seen.add(id(node))
            row, end_row = node.lineno - statement.lineno, node.end_lineno - statement.lineno
            head, tail = encoded[row][:node.col_offset], encoded[end_row][node.end_col_offset:]
            encoded[row:end_row + 1] = [head + code.encode("utf-8") + tail]
        return " ".join(line.strip() for line in b"".join(encoded).decode("utf-8").splitlines()).strip()

    def apply(self) -> str:
        moved = [self.rewritten(index, swaps) for index, swaps in sorted(self.moves.items()) if index not in self.dropped]
        for index in sorted(set(self.moves) | self.dropped):
            statement = self.block.body[index]
            self.edits.remove_lines(statement.lineno, statement.end_lineno)
        self.edits.insert_after(self.block.last_line, [f"{self.block.indent}{each}" for each in self.written + moved + self.later])
        return self.edits.apply()


def _argument(call: ast.Call, method: str, role: str):
    roles = {"line": ("start", "end"), "arc": ("center", "start", "end"), "circle": ("center",)}[method]
    return call.args[roles.index(role)] if role in roles and roles.index(role) < len(call.args) else None


def _invalidated(trim: _Trim, kinds: tuple[str, ...]):
    """The trimmed curve's relations a trim makes wrong: its length, a midpoint on it, an equal
    length; each statement's index and the relation."""
    out = []
    for item in [*trim.state.get("relations", []), *trim.state.get("dimensions", [])]:
        if trim.name not in (item.get("refs") or []) or item.get("kind") not in kinds:
            continue
        if item["kind"] == "equal" and trim.curve["kind"] != "line":
            continue
        at = trim.names.made_by.get(item["id"])
        if at is not None and at != trim.index:
            out.append((at, item))
    return out


def trim(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """The piece of a curve where it was clicked (``at``) cut away up to the curves that cross it
    either side, as Trim Entities' power trim cuts it: an end moved back to a crossing, a line or
    an arc split in two, a circle made an arc; or the whole curve deleted when nothing crosses it.
    Each new end is kept on the curve it was cut at, and a split's two pieces stay in line."""
    from cadgen.edit.sketching import delete

    block = find_block(text, line, path)
    names = Names(block, state)
    shape = _Shape(state)
    name = str(op.get("curve") or "")
    curve = shape.curve(name)
    try:
        click = (float(op["at"][0]), float(op["at"][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        raise SketchEditError("Click the part of a curve to trim.") from None
    made = names.statement_of(name)
    if made is not None and made.method == "convert":
        raise SketchEditError(f"{name} is converted from the model and stays on its edge, so it is not trimmed. "
                              "Delete it, or draw the shape you want over it.")
    if made is None or made.method not in ("line", "arc", "circle") or not isinstance(made.statement, ast.Assign):
        method = (made.method or "shape").replace("_", " ") if made is not None else "shape"
        raise SketchEditError(f"{name} is part of a {method}, which edit mode trims only once it is written as its own lines. "
                              "Ask the agent to write it out.")
    # Where other curves cross it (or end on it), merged where several meet at one place, each
    # with a point already there: an end of a curve that crosses.
    crossings: list[dict] = []
    for other, item in shape.curves.items():
        if other == name:
            continue
        for place in _meetings(shape, curve, item):
            along = _on(shape, curve, place, inclusive=curve["kind"] == "circle")
            if along is None:
                continue
            same = next((each for each in crossings if shape.near(each["place"], place)), None)
            if same is None:
                crossings.append({"along": along, "place": place, "curves": [other], "point": None})
            elif other not in same["curves"]:
                same["curves"].append(other)
    for crossing in crossings:
        crossing["point"] = next((point for c in crossing["curves"] for role in ("start", "end")
                                  if (point := shape.curves[c].get(role)) and shape.near(shape.at(point), crossing["place"])), None)
    if not crossings or (curve["kind"] == "circle" and len(crossings) < 2):
        return delete(text, line, state, [name], path)
    crossings.sort(key=lambda each: each["along"])
    trim_ = _Trim(text, block, names, shape, state, name)
    s = block.var
    built = _built(curve)

    if curve["kind"] == "circle":
        # The circle becomes the arc that is left: from the crossing after the gap clicked, round
        # to the one before it.
        clicked = _Round(shape, curve).along(click)
        count = len(crossings)
        k = next((i for i in range(count - 1) if crossings[i]["along"] <= clicked < crossings[i + 1]["along"]), count - 1)
        before, after = crossings[k], crossings[(k + 1) % count]
        argument = _argument(trim_.call, "circle", "center")
        var = trim_.vars.next("Arc")
        shared = None if isinstance(argument, ast.Tuple) else _segment(text, argument)
        center = trim_.rehome("center", curve["center"], f"{var}.center", shared) or _place(shape.at(curve["center"]))
        trim_.drop(trim_.index)
        start = trim_.end_at("start", after, own=False, var=var)
        end = trim_.end_at("end", before, own=False, var=var)
        trim_.written.append(f"{var} = {s}.arc({center}, {start}, {end}{built})")
        # What held the circle holds the arc.
        for index, nodes in trim_.references(None):
            if index not in trim_.dropped:
                trim_.move(index, [(node, var) for node in nodes])
        return trim_.apply()

    method = curve["kind"]
    if method == "line":
        a, b = shape.at(curve["start"]), shape.at(curve["end"])
        d = _sub(b, a)
        length, clicked = 1.0, max(0.0, min(1.0, _dot(_sub(click, a), d) / (_dot(d, d) or 1.0)))
    else:
        round_ = _Round(shape, curve)
        length = round_.sweep
        clicked = round_.along(click)
        if clicked > length:
            # Off the arc: whichever end it is nearer.
            clicked = length if clicked - length < 2 * math.pi - clicked else 0.0
    inner = [each for each in crossings if 0 < each["along"] < length]
    if not inner:
        return delete(text, line, state, [name], path)
    low = max((each for each in inner if each["along"] < clicked), key=lambda each: each["along"], default=None)
    high = min((each for each in inner if each["along"] > clicked), key=lambda each: each["along"], default=None)
    split = low is not None and high is not None
    var = trim_.vars.next("Line" if method == "line" else "Arc") if split else None
    # What a trim makes wrong: the curve's length (a split keeps it as its far ends' distance), a
    # midpoint on it, a length equal to another's.
    for at, item in _invalidated(trim_, ("length", "midpoint", "equal")):
        if item["kind"] == "length" and split and method == "line":
            value = _call_of(names.made[at - block.start - 1].statement, s).args[-1]
            trim_.later.append(f"{s}.distance({trim_.code}.start, {var}.end, {_segment(text, value)})")
        trim_.drop(at)
    if not split:
        # One end cut back to the nearest crossing.
        role, crossing = ("start", high) if low is None else ("end", low)
        argument = _argument(trim_.call, method, role)
        shared = None if isinstance(argument, ast.Tuple) else _segment(text, argument)
        trim_.rehome(role, curve[role], None, shared)
        trim_.edits.replace_node(argument, trim_.end_at(role, crossing, own=True))
        return trim_.apply()
    # Split: the curve keeps its start, up to the crossing before the click; a new piece runs from
    # the crossing after it to the curve's end; the two kept in line.
    argument = _argument(trim_.call, method, "end")
    shared = None if isinstance(argument, ast.Tuple) else _segment(text, argument)
    end_code = trim_.rehome("end", curve["end"], f"{var}.end", shared) or _place(shape.at(curve["end"]))
    trim_.edits.replace_node(argument, trim_.end_at("end", low, own=True))
    start = trim_.end_at("start", high, own=False, var=var)
    if method == "line":
        trim_.written.append(f"{var} = {s}.line({start}, {end_code}{built})")
        trim_.later += [f"{s}.parallel({var}, {trim_.code})", f"{s}.coincident({var}.start, {trim_.code})"]
    else:
        turn = ", clockwise=True" if curve.get("clockwise") else ""
        trim_.written.append(f"{var} = {s}.arc({trim_.code}.center, {start}, {end_code}{turn}{built})")
        trim_.later.append(f"{s}.equal({var}, {trim_.code})")
    return trim_.apply()


# ---------------------------------------------------------------------------------------------
# Extend Entities.


def _ahead(shape: _Shape, start, end, item: dict) -> list:
    """Where the line from ``start`` through ``end``, run on as far as it goes, meets a curve as it is drawn."""
    if item["kind"] == "line":
        met = _meet({"kind": "line", "p": start, "q": end}, {"kind": "line", "p": shape.at(item["start"]), "q": shape.at(item["end"])}, end)
        found = [met] if met is not None else []
    else:
        round_ = _Round(shape, item)
        found = _line_circle(start, end, round_.c, round_.r)
    return [place for place in found if _on(shape, item, place) is not None]


def extend(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """A line's end, the one nearer the click (``at``), run on to the first curve it meets past it,
    as Extend Entities extends one, and kept on that curve. An end another curve shares stays: it
    would pull that curve with it."""
    block = find_block(text, line, path)
    names = Names(block, state)
    shape = _Shape(state)
    name = str(op.get("curve") or "")
    curve = shape.curve(name)
    try:
        click = (float(op["at"][0]), float(op["at"][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        raise SketchEditError("Click a line near the end to extend.") from None
    made = names.statement_of(name)
    if curve["kind"] == "arc" and made is not None and made.method == "arc" and isinstance(made.statement, ast.Assign):
        return _extend_arc(text, block, names, shape, state, name, curve, click)
    if curve["kind"] != "line" or made is None or made.method != "line" or not isinstance(made.statement, ast.Assign):
        raise SketchEditError(f"Extend Entities runs a line or an arc on. {name} is not one drawn on its own, so it is not extended.")
    a, b = shape.at(curve["start"]), shape.at(curve["end"])
    role, (end, start) = ("end", (b, a)) if math.dist(click, b) <= math.dist(click, a) else ("start", (a, b))
    point = curve[role]
    joined = [other for other, item in shape.curves.items() if other != name and point in (item.get("start"), item.get("end"), item.get("center"))]
    if joined:
        raise SketchEditError(f"{name}'s {role} is joined to {joined[0]}, so it is not extended. Trim or move it instead.")
    way = _sub(end, start)
    reach = _dot(way, way) or 1.0
    nearest = None
    for other, item in shape.curves.items():
        if other == name:
            continue
        for place in _ahead(shape, start, end, item):
            t = _dot(_sub(place, start), way) / reach
            if t > 1 + shape.tolerance / math.sqrt(reach) and (nearest is None or t < nearest[0]):
                nearest = (t, place, other)
    if nearest is None:
        raise SketchEditError(f"Nothing lies ahead of {name}'s {role} to extend it to.")
    _, place, target = nearest
    trim_ = _Trim(text, block, names, shape, state, name)
    # What a longer line makes wrong: its length, a midpoint on it, a length equal to another's.
    for at, _item in _invalidated(trim_, ("length", "midpoint", "equal")):
        trim_.drop(at)
    argument = _argument(trim_.call, "line", role)
    shared = None if isinstance(argument, ast.Tuple) else _segment(text, argument)
    trim_.rehome(role, point, None, shared)
    ends = [each for each in (shape.curves[target].get("start"), shape.curves[target].get("end")) if each and shape.near(shape.at(each), place)]
    trim_.edits.replace_node(argument, trim_.end_at(role, {"place": place, "curves": [target], "point": ends[0] if ends else None}, own=True))
    return trim_.apply()


def _extend_arc(text: str, block, names: Names, shape: _Shape, state: dict, name: str, curve: dict, click) -> str:
    """An arc's end, the one nearer the click, run on round its circle the way it turns to the first
    curve it meets, as Extend Entities extends an arc, and kept on that curve."""
    round_ = _Round(shape, curve)
    a, b = shape.at(curve["start"]), shape.at(curve["end"])
    role = "end" if math.dist(click, b) <= math.dist(click, a) else "start"
    point = curve[role]
    joined = [other for other, item in shape.curves.items() if other != name and point in (item.get("start"), item.get("end"), item.get("center"))]
    if joined:
        raise SketchEditError(f"{name}'s {role} is joined to {joined[0]}, so it is not extended. Trim or move it instead.")
    # Round from the end the way the arc turns, or back from its start; never as far as the arc itself.
    gap = 2 * math.pi - round_.sweep
    nearest = None
    for other, item in shape.curves.items():
        if other == name or item["kind"] not in ("line", "arc", "circle"):
            continue
        if item["kind"] == "line":
            found = _line_circle(shape.at(item["start"]), shape.at(item["end"]), round_.c, round_.r)
        else:
            other_round = _Round(shape, item)
            found = _circle_circle(round_.c, round_.r, other_round.c, other_round.r)
        for place in found:
            if _on(shape, item, place) is None:
                continue
            along = round_.along(place)
            run = along - round_.sweep if role == "end" else (2 * math.pi - along) % (2 * math.pi)
            if shape.tolerance / round_.r < run < gap - shape.tolerance / round_.r and (nearest is None or run < nearest[0]):
                nearest = (run, place, other)
    if nearest is None:
        raise SketchEditError(f"Nothing lies round {name}'s circle past its {role} to extend it to.")
    _, place, target = nearest
    trim_ = _Trim(text, block, names, shape, state, name)
    for at, _item in _invalidated(trim_, ("midpoint", "angle")):
        trim_.drop(at)
    argument = _argument(trim_.call, "arc", role)
    shared = None if isinstance(argument, ast.Tuple) else _segment(text, argument)
    trim_.rehome(role, point, None, shared)
    ends = [each for each in (shape.curves[target].get("start"), shape.curves[target].get("end")) if each and shape.near(shape.at(each), place)]
    trim_.edits.replace_node(argument, trim_.end_at(role, {"place": place, "curves": [target], "point": ends[0] if ends else None}, own=True))
    return trim_.apply()


# ---------------------------------------------------------------------------------------------
# Linear and Circular Sketch Pattern.


def pattern(text: str, line: int, state: dict, op: dict, path: str = "<sketch>") -> str:
    """Entities copied as a CAD tool's sketch patterns copy them, one line for all the copies:
    ``items`` (curves and points of the sketch), ``count`` instances in all; ``type`` linear (each
    ``spacing`` on along ``angle`` degrees, or along the line ``along``) or circular (turned about
    the point ``center``, the sketch's origin when none, over ``angle`` degrees):
    ``pattern1 = sketch1.linear_pattern([circle1], 0, 10, 4)``."""
    block = find_block(text, line, path)
    names = Names(block, state)
    s = block.var
    items = [str(item) for item in op.get("items") or []]
    if not items:
        raise SketchEditError("Select the entities to pattern.")
    codes = [names.item(item) for item in items]
    try:
        count = int(str(op.get("count") or "").strip())
    except ValueError:
        count = 0
    if not 2 <= count <= 100:
        raise SketchEditError("A pattern has 2 to 100 instances.")
    var = _Vars(block, state).next("Pattern")
    listed = f"[{', '.join(codes)}]"
    if str(op.get("type") or "linear") == "circular":
        center = names.item(str(op["center"])) if op.get("center") else f"{s}.origin"
        angle = _typed(op.get("angle") or "360")
        return _append(text, block, [f"{var} = {s}.circular_pattern({listed}, {center}, {count}, {angle})"])
    along = names.curve(str(op["along"])) if op.get("along") else _typed(op.get("angle") or "0")
    return _append(text, block, [f"{var} = {s}.linear_pattern({listed}, {along}, {_typed(op.get('spacing'))}, {count})"])
