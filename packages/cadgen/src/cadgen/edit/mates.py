"""Mates, as SolidWorks' Mate places the parts of an assembly (`cadgen.mates`).

Two faces, edges or vertices are picked on two parts: the first part stays, the second moves to
it. The mate is written in the assembly's script into the moved part's ``mate`` call, on what was
picked (found again by selector each run), so it holds as the parts change and a part's mates are
solved together::

    mate(pin_part,
         Coincident(pin_part.faces().sort_by(Axis.Z)[0], base_part.faces().sort_by(Axis.Z)[-1]),
         Concentric(pin_part.faces().filter_by(GeomType.CYLINDER)[0], base_part.faces().filter_by(GeomType.CYLINDER)[0]))

A part's ``mate`` call comes after the calls of the parts it is mated to, so it follows them. The
design tree lists the mates under Mates by type and count (Coincident1, Concentric1), and a mate's
Delete takes it out of its call. Mates written as build123d joint pairs (``RigidJoint("coincident1",
...)`` and ``connect_to``) are listed and taken out too.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from cadgen.edit import commands

TYPES = {"coincident": "Coincident", "concentric": "Concentric", "distance": "Distance", "parallel": "Parallel",
         "perpendicular": "Perpendicular", "angle": "Angle", "tangent": "Tangent", "lock": "Lock"}
_NAMES = set(TYPES.values())
# The labels of mates written as joint pairs.
_LABEL = re.compile(r"^(coincident|concentric|distance)(\d+)$")


class MateError(Exception):
    """A mate that cannot be made, said to the engineer."""


def assembly_of(tree: ast.Module):
    """The assembly's function, its ``return Compound(children=[...])`` and that list."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Return) and commands._call_name(statement.value) == "Compound":
                call = statement.value
                children = next((keyword.value for keyword in call.keywords if keyword.arg == "children"), call.args[0] if call.args else None)
                if isinstance(children, ast.List):
                    return node, statement, children
    raise MateError("Mates place the parts an assembly returns as Compound(children=[...]). Ask the agent to write it that way.")


def _occurrence(selector, children=()) -> int | None:
    """Which part of the assembly a selector names, from 0: the part its owner is labelled as
    (``pin/face 3``: the child labelled ``pin``; ``pin.2/face 3`` the second of them), as the viewer
    names a pick, or its place in 0.7's spelling (``o1.2.f3``: the second)."""
    text = str(selector or "")
    match = re.match(r"^o\d+\.(\d+)\.", text)
    if match:
        return int(match.group(1)) - 1
    owned = re.match(r"^(.+)/(?:face|edge)\s*\d+$", text)
    if not owned:
        return None
    segment = owned.group(1).split("/")[-1]
    numbered = re.match(r"^(.*)\.([1-9]\d*)$", segment)
    label, nth = (numbered.group(1), int(numbered.group(2))) if numbered else (segment, 1)
    label = label.strip('"')
    found = [index for index, child in enumerate(children) if getattr(child, "label", None) == label]
    if not found and numbered:
        found, nth = [index for index, child in enumerate(children) if getattr(child, "label", None) == segment], 1
    return found[nth - 1] if len(found) >= nth else None


def _picked(children: list, item: dict, scale: float) -> tuple[int, str, int]:
    """Which part a pick is on, and which face or edge of it: (part, kind, number)."""
    kind, _number = commands.selector_ordinal(item.get("selector"))
    if kind is None:
        raise MateError("Pick faces or edges on the parts to mate.")
    tolerance = 1e-4 + 1e-6 * scale
    found = []
    for index, child in enumerate(children):
        topology = commands.Topology(child, kind)
        for candidate in range(1, len(topology) + 1):
            if commands._distance(topology.describe(candidate), item, tolerance) is not None:
                found.append((index, candidate))
                break
    if not found:
        raise MateError("A pick is not on the assembly as it is now. Wait for it to update, then pick it again.")
    hint = _occurrence(item.get("selector"), children)
    index, number = next((each for each in found if each[0] == hint), found[0])
    return index, kind, number


def _mate_calls(function) -> list[tuple[ast.stmt, ast.Call, str]]:
    """The function's ``mate(<part>, ...)`` statements, in order, with the part each places."""
    found = []
    for statement in function.body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if commands._call_name(call) == "mate" and isinstance(call.func, ast.Name) and call.args and isinstance(call.args[0], ast.Name):
            found.append((statement, call, call.args[0].id))
    return found


def _mated_to(constraint: ast.Call) -> str | None:
    """The part a mate holds its part against: the name its second item's selector starts from
    (``base_part`` of ``base_part.faces().sort_by(Axis.Z)[-1]``)."""
    if len(constraint.args) < 2:
        return None
    node = constraint.args[1]
    while not isinstance(node, ast.Name):
        if isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            return None
    return node.id


def _made_by(function, components) -> dict:
    """Each name the assembly gives a part, to the part function that made it."""
    made_by = {}
    for statement in function.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            called = [commands._call_name(node) for node in ast.walk(statement.value) if isinstance(node, ast.Call)]
            part = next((name for name in called if name in components), None)
            if part:
                made_by[statement.targets[0].id] = part
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Tuple) \
                and isinstance(statement.value, ast.Tuple):
            for target, value in zip(statement.targets[0].elts, statement.value.elts):
                called = [commands._call_name(node) for node in ast.walk(value) if isinstance(node, ast.Call)]
                part = next((name for name in called if name in components), None)
                if part and isinstance(target, ast.Name):
                    made_by[target.id] = part
    return made_by


def _listed(function, components=()) -> list[dict]:
    """Every mate in the assembly, in order: a ``mate`` call's each, by its type and count, and a
    joint pair's, by its label; with where it is written."""
    made_by = _made_by(function, components)
    counts: dict[str, int] = {}
    found = []
    for statement in function.body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if commands._call_name(call) == "mate" and isinstance(call.func, ast.Name) and call.args and isinstance(call.args[0], ast.Name):
            moving = call.args[0].id
            for index, constraint in enumerate(call.args[1:], 1):
                kind = commands._call_name(constraint)
                if kind not in _NAMES:
                    continue
                counts[kind] = counts.get(kind, 0) + 1
                name = f"{kind}{counts[kind]}"
                fixed = _mated_to(constraint)
                found.append({"name": name, "label": name, "type": kind.lower(), "parts": [made_by.get(fixed, fixed), made_by.get(moving, moving)],
                              "line": statement.lineno, "statement": statement, "call": call, "index": index})
            continue
        # A joint pair's connection: `base_part.joints["coincident1"].connect_to(pin_part.joints["coincident1"])`.
        if commands._call_name(call) != "connect_to" or not isinstance(call.func, ast.Attribute):
            continue
        fixed, moving = _joint_of(call.func.value), (_joint_of(call.args[0]) if call.args else None)
        if fixed is None or moving is None or fixed[1] != moving[1] or not _LABEL.match(fixed[1]):
            continue
        kind, number = _LABEL.match(fixed[1]).groups()
        found.append({"name": f"{TYPES[kind]}{number}", "label": fixed[1], "type": kind, "parts": [made_by.get(fixed[0], fixed[0]),
                      made_by.get(moving[0], moving[0])], "line": statement.lineno})
    return found


def read(text: str, components=()) -> list[dict]:
    """The mates in an assembly's script, for the design tree: name, label (what Delete takes), type,
    the parts (the one it holds against, then the one it moves) and line."""
    try:
        function, _returned, _children = assembly_of(ast.parse(text))
    except (SyntaxError, MateError):
        return []
    return [{key: value for key, value in each.items() if key not in ("statement", "call", "index")} for each in _listed(function, components)]


def _joint_of(node) -> tuple[str, str] | None:
    """``base_part.joints["coincident1"]`` as (part, label)."""
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "joints"
            and isinstance(node.value.value, ast.Name) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
        return node.value.value.id, node.slice.value
    return None


def delete(text: str, label: str) -> str:
    """The script with a mate taken out: out of its part's ``mate`` call (the call with it when it
    was the last), or a joint pair's two joints and connection. Its part keeps its other mates."""
    tree = ast.parse(text)
    function, _returned, _children = assembly_of(tree)
    listed = next((each for each in _listed(function) if each["label"] == label), None)
    if listed is None:
        raise MateError(f"{label} is no longer in the assembly. Look again.")
    lines = text.splitlines(keepends=True)
    if "call" in listed:
        call, statement = listed["call"], listed["statement"]
        kept = [ast.get_source_segment(text, each) for each in call.args[1:] if each is not call.args[listed["index"]]]
        if not kept:
            del lines[statement.lineno - 1:statement.end_lineno]
            return "".join(lines)
        indent = " " * statement.col_offset
        lines[statement.lineno - 1:statement.end_lineno] = [_written(indent, call.args[0].id, kept)]
        return "".join(lines)
    gone = [statement for statement in function.body if isinstance(statement, ast.Expr)
            and label in {node.value for node in ast.walk(statement) if isinstance(node, ast.Constant) and isinstance(node.value, str)}]
    for statement in sorted(gone, key=lambda each: each.lineno, reverse=True):
        del lines[statement.lineno - 1:statement.end_lineno]
    return "".join(lines)


def _written(indent: str, part: str, constraints: list[str]) -> str:
    """A part's ``mate`` call as the script writes it: its mates one to a line under it when there are several."""
    if len(constraints) == 1:
        return f"{indent}mate({part}, {constraints[0]})\n"
    under = indent + " " * len("mate(")
    return f"{indent}mate({part},\n" + ",\n".join(f"{under}{each}" for each in constraints) + ")\n"


def change(text: str, assembly, spec: dict, units: str, components: list[str]) -> tuple[str, int, str]:
    """The script with a mate added to the moved part's ``mate`` call (a new call when it has none):
    ``spec`` has its ``type``, the two picks (``selection``, the second's part moved to the
    first's), a Distance's ``distance`` in the part's units, an Angle's ``angle`` in degrees, and
    ``flip``. ``components`` are the part functions the assembly calls, in order. Returns the text,
    the line of the part's ``mate`` call, and what it did, in words."""
    from cadgen import mates as engine

    kind = str(spec.get("type") or "").lower()
    if kind not in TYPES:
        raise MateError(f"A mate is {', '.join(TYPES.values())}.")
    picks = [item for item in spec.get("selection") or [] if isinstance(item, dict)]
    if len(picks) != 2:
        raise MateError("Pick a face, an edge or a vertex on each of two parts.")
    tree = ast.parse(text)
    function, returned, listed = assembly_of(tree)
    children = list(getattr(assembly, "children", []) or [])
    if len(children) != len(listed.elts):
        raise MateError("The assembly's parts are not the ones its Compound lists. Ask the agent to list them there.")
    scale = assembly.bounding_box().diagonal or 1.0
    (first, first_kind, first_number), (second, second_kind, second_number) = (_picked(children, item, scale) for item in picks)
    if first == second:
        raise MateError("Pick the faces or edges on two different parts.")
    fixed_item = commands.Topology(children[first], first_kind).item(first_number)
    moving_item = commands.Topology(children[second], second_kind).item(second_number)
    flip = spec.get("flip") in (True, "true", "1", 1)
    values: list[float] = []
    try:
        if kind == "distance":
            values = [float(str(spec.get("distance") or "").strip())]
        elif kind == "angle":
            values = [float(str(spec.get("angle") or "").strip())]
    except ValueError:
        raise MateError(f"Type the {'distance' if kind == 'distance' else 'angle'} as a number.") from None
    unit = 25.4 if units == "in" else 1.0
    try:
        # The mate made of what was picked, as the script will make it: it says what it cannot take.
        made = getattr(engine, TYPES[kind])(moving_item, fixed_item, *[values[0] * unit] if kind == "distance" else values,
                                            **({"flip": True} if flip and kind not in ("perpendicular", "angle", "lock") else {}))
    except engine.MateError as error:
        raise MateError(str(error)) from None
    del made
    # The parts named in the script: each in the Compound as a name, or given one before the return.
    module, named_import = commands.build123d_names(tree)
    names = commands.Names(module or "")
    edits = commands.Edits(text)
    indent = " " * returned.col_offset
    lines: list[str] = []
    variables = []
    for index in (first, second):
        element = listed.elts[index]
        if isinstance(element, ast.Name):
            variables.append(element.id)
            continue
        wanted = components[index] if index < len(components) else f"part{index + 1}"
        var = commands.fresh_name(tree, f"{wanted}_part")
        while var in variables:
            var = commands.fresh_name(tree, f"{var}_2")
        lines.append(f"{indent}{var} = {ast.get_source_segment(text, element)}")
        edits.put(element.lineno, element.col_offset, var, until=element.end_col_offset)
        variables.append(var)
    fixed_var, moving_var = variables
    fixed_code = commands.Selections(children[first], fixed_var, names).write(first_kind, [first_number], one=True)
    moving_code = commands.Selections(children[second], moving_var, names).write(second_kind, [second_number], one=True)
    written = [moving_code, fixed_code]
    if kind == "distance":
        written.append(_Lengths(tree, units).length(values[0]))
    elif kind == "angle":
        written.append(commands._number(values[0], False))
    if flip and kind not in ("perpendicular", "angle", "lock"):
        written.append("flip=True")
    constraint = f"{TYPES[kind]}({', '.join(written)})"
    calls = _mate_calls(function)
    own = next(((statement, call) for statement, call, part in calls if part == moving_var), None)
    holds = next(((statement, call) for statement, call, part in calls if part == fixed_var), None)
    if holds is not None and any(_mated_to(each) == moving_var for each in holds[1].args[1:]):
        raise MateError(f"{components[first] if first < len(components) else 'That part'} is mated to "
                        f"{components[second] if second < len(components) else 'this one'} already: mates hold one part against another, "
                        "one way. Pick the faces the other way round.")
    if own is not None:
        statement, call = own
        kept = [ast.get_source_segment(text, each) for each in call.args[1:]] + [constraint]
        new_call = _written(" " * statement.col_offset, moving_var, kept).rstrip("\n").split("\n")
        if holds is not None and holds[0].lineno > statement.lineno:
            # Its mates now hold it against a part placed after it: its call goes after that part's.
            edits.swap(statement.lineno, statement.end_lineno, [])
            edits.after(holds[0].end_lineno, new_call)
        else:
            edits.swap(statement.lineno, statement.end_lineno, new_call)
    else:
        # A new call: after the call of the part it is held against, and before the calls of the parts held against it.
        later = [statement for statement, call, part in calls if any(_mated_to(each) == moving_var for each in call.args[1:])]
        where = (later[0].lineno - 1) if later else returned.lineno - 1
        if holds is not None and later and holds[0].lineno > later[0].lineno:
            raise MateError("Those parts are mated in a ring. Take a mate out first.")
        edits.after(where, lines + [f"{indent}mate({moving_var}, {constraint})"])
    commands._imports(edits, _Tree(tree), module, named_import, names)
    made_text = _imported(edits.apply(), [TYPES[kind], "mate"])
    # The new mate is its part's call's last: its name as the tree counts it, and the call's line.
    function = assembly_of(ast.parse(made_text))[0]
    statement, call, _part = next(each for each in _mate_calls(function) if each[2] == moving_var)
    at = statement.lineno
    name = next(each["name"] for each in _listed(function) if each.get("call") is not None and each["statement"].lineno == at
                and each["index"] == len(call.args) - 1)
    mover = components[second] if second < len(components) else "a part"
    holder = components[first] if first < len(components) else "a part"
    words = {"coincident": "on", "concentric": "on one axis with", "distance": f"{commands._number(values[0], False) if values else ''} "
             f"{units or 'mm'} from", "parallel": "parallel to", "perpendicular": "square to",
             "angle": f"at {commands._number(values[0], False) if values else ''} degrees to", "tangent": "tangent to",
             "lock": "locked to"}[kind]
    return made_text, at, f"{name}: {mover} {words} {holder}"


def _imported(text: str, wanted: list[str]) -> str:
    """The script with ``from cadgen.mates import ...`` naming each of ``wanted``."""
    tree = ast.parse(text)
    have = next((node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "cadgen.mates"), None)
    lines = text.splitlines(keepends=True)
    if have is not None:
        present = {alias.asname or alias.name for alias in have.names}
        missing = [name for name in wanted if name not in present]
        if not missing:
            return text
        names = sorted({alias.name for alias in have.names} | set(missing))
        lines[have.lineno - 1:have.end_lineno] = [f"from cadgen.mates import {', '.join(names)}\n"]
        return "".join(lines)
    last = max((node.end_lineno for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))), default=0)
    lines.insert(last, f"from cadgen.mates import {', '.join(sorted(set(wanted)))}\n")
    return "".join(lines)


class _Tree:
    """What ``commands._imports`` reads of a file: its parsed tree."""

    def __init__(self, tree: ast.Module):
        self.tree = tree


class _Lengths:
    """Lengths in the part's units, as its other lines write them: ``.5*INCH`` in an inch part."""

    def __init__(self, tree: ast.Module, units: str):
        self.units = units
        self.unit = commands.unit_name(tree) if units == "in" else None

    def length(self, value: float) -> str:
        value = round(value, 6)
        if self.units == "in":
            return f"{commands._number(value, False)}*{self.unit}" if self.unit else commands._number(value * 25.4, False)
        return commands._number(value, False)


def _step_function(text: str) -> str | None:
    """The name of the function a part's script makes its part with: its model (``@model``, or any
    of the engine's file decorators: ``service.model_of``)."""
    from cadgen.edit.service import model_of

    found = model_of(text)
    return found[0] if found else None


def parts_of(root, assembly) -> list[str]:
    """The project's part scripts another assembly can insert: each with a model's function,
    the assembly itself left out, as project-relative paths."""
    from cadgen.edit.service import _python_files, is_part

    return [path.relative_to(root).as_posix() for path in _python_files(root) if path != assembly and is_part(path)]


def insert(text: str, assembly, part, root) -> tuple[str, int, str]:
    """Insert Components, as SolidWorks' adds a part to an assembly: ``part``'s script imported in
    the assembly's (its folder put on the import path when no part of it is already imported from
    there) and its model's shape (``part().shape``) added to the children the assembly returns, where it is made,
    for its mates to place. A part already in it is not inserted again: the design tree lists each
    part's model once."""
    tree = ast.parse(text)
    function, returned, listed = assembly_of(tree)
    made = _step_function(part.read_text(encoding="utf-8"))
    if made is None:
        raise MateError(f"{part.name} makes no part (a function marked @model). Pick a part's script.")
    module = part.stem
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and not node.level]
    found = next((node for node in imports if node.module == module), None)
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    names = {alias.asname or alias.name for node in imports for alias in node.names}
    if found is not None and not any(alias.name == made for alias in found.names):
        raise MateError(f"{module} is imported here already, for something else. Ask the agent to insert it.")
    if found is None and made in names:
        raise MateError(f"{made} is a name this assembly uses already. Ask the agent to insert {part.name}.")
    # Where the assembly's parts are imported from: the folders their modules are in.
    from cadgen.edit.service import _python_files

    modules = {node.module for node in imports}
    folders = {Path(assembly).parent} | {path.parent for path in _python_files(root) if path.stem in modules}
    added = []
    if found is None:
        if part.parent not in folders:
            relative = Path(os.path.relpath(part.parent, Path(assembly).parent)).as_posix()
            # Each `..` a parent of the assembly's folder; then the folders down to the part's.
            ups = len([piece for piece in relative.split("/") if piece == ".."])
            down = [piece for piece in relative.split("/") if piece not in ("..", ".")]
            base = "Path(__file__).resolve().parent" if ups == 0 else f"Path(__file__).resolve().parents[{ups}]"
            where = " / ".join([base, *[f'"{piece}"' for piece in down]])
            if not any(isinstance(node, ast.Import) and any(alias.name == "sys" for alias in node.names) for node in tree.body):
                added.append("import sys")
            if not any(isinstance(node, ast.ImportFrom) and node.module == "pathlib" and any(alias.name == "Path" for alias in node.names)
                       for node in tree.body):
                added.append("from pathlib import Path")
            added.append(f"sys.path.insert(0, str({where}))")
        added.append(f"from {module} import {made}")
    if any(isinstance(node, ast.Call) and commands._call_name(node) == made for node in ast.walk(function)):
        raise MateError(f"{made} is in this assembly already. Ask the agent for another of it.")
    # A model's call is its document; the assembly composes its shape (the engine's `child().shape`).
    child = f"{made}().shape"
    # The child goes last in the list, on the list's line or the line of its last element.
    end = listed.elts[-1] if listed.elts else None
    row, col = (end.end_lineno, end.end_col_offset) if end is not None else (listed.lineno, listed.col_offset + 1)
    piece = f", {child}" if end is not None else child
    lines[row - 1] = lines[row - 1][:col] + piece + lines[row - 1][col:]
    if added:
        last = max((node.end_lineno for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                    or (isinstance(node, ast.Expr) and "sys.path" in ast.unparse(node))), default=0)
        lines[last:last] = [each + newline for each in added]
    return "".join(lines), row + len(added), f"inserted {made}"
