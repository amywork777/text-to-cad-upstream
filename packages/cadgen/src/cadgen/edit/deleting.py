"""A feature taken out of a part's script, as SolidWorks' Delete takes one out of the design tree,
or set aside in it, as Suppress does.

The lines that make the feature go. A line that changes the body in place (`part += ...`,
`tray = bd.fillet(tray.edges(), ...)`) goes whole, so the body reads as it did before it. A boolean
that starts a name of its own keeps the name, as the body it was made from (`tray = outer - cavity`
becomes `tray = outer`), so the features after it still read. The sketch a feature was made from
stays, as SolidWorks keeps an absorbed sketch; a sketch of its own goes with its lines.

A line whose name a later line still uses is not taken out: the tracer finds the features those
lines make, its child features, and takes them out with it once the engineer confirms, as
SolidWorks' Confirm Delete does (`tracer._children`). A boolean or an in-place change whose body
goes with it then goes whole. The tracer runs the part again, and puts the script back if it no
longer builds (`tracer.py`).

Suppress takes the same lines out of the part, but keeps them in the script as comments under a
line that says what they are, so Unsuppress puts them back exactly:

    # Suppressed (Cut-Extrude, 2 lines):
    # cavity = Pos(0, 0, 2) * Box(36, 16, 10)
    # tray = outer - cavity
    tray = outer  # Cut-Extrude suppressed

The count says which comments are the feature's, so a comment of the engineer's after them stays
theirs. A boolean that starts a name keeps the name as Delete keeps it, on a line of its own after
them that says so.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from cadgen.edit.sketching import SketchEditError, TextEdits, find_block


class DeleteError(ValueError):
    """Why a feature is not taken out, in an engineer's words. ``dependents``: the name it makes
    and the lines that still use it, for the viewer to say as the features they are."""

    def __init__(self, message: str, dependents: dict | None = None):
        super().__init__(message)
        self.dependents = dependents


# The line a suppressed feature's lines follow: its kind as the design tree names it, and how many.
SUPPRESSED = re.compile(r"^(?P<indent>[ \t]*)# Suppressed \((?P<kind>[^(),\r\n]+), (?P<count>\d+) lines?\):[ \t]*$")
# A boolean's operators: a cut, a join, an intersect.
_BOOLEANS = (ast.Sub, ast.Add, ast.BitAnd)
_COMPOUND = (ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith, ast.Try)


@dataclass
class _Plan:
    edits: TextEdits
    # Statements taken out whole; booleans kept as one operand (statement, the operand kept).
    removed: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    # The names nothing left makes.
    gone: set = field(default_factory=set)


def _function_at(tree: ast.Module, line: int):
    function = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= line <= node.end_lineno:
            if function is None or node.lineno > function.lineno:
                function = node
    return function


def _simple(statement: ast.stmt) -> list:
    """The plain statements a statement is: itself, or those inside a loop, a condition or a with."""
    if not isinstance(statement, _COMPOUND):
        return [statement]
    inner = []
    for name in ("body", "orelse", "finalbody"):
        for each in getattr(statement, name, None) or []:
            inner += _simple(each)
    for handler in getattr(statement, "handlers", None) or []:
        for each in handler.body:
            inner += _simple(each)
    return inner


def _names(node: ast.AST, ctx=ast.Load) -> set:
    return {each.id for each in ast.walk(node) if isinstance(each, ast.Name) and isinstance(each.ctx, ctx)}


def _module_names(tree: ast.Module) -> set:
    """The names a module makes at its own level: its imports, sizes, functions and classes."""
    names = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(statement.name)
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in statement.names}
        elif isinstance(statement, ast.Assign):
            names |= set().union(*(_names(target, ast.Store) for target in statement.targets))
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            names |= _names(statement.target, ast.Store)
    return names


def _remove(plan: _Plan, body: list, statement: ast.stmt, title: str, verb: str = "remove") -> None:
    for other in body:
        if other is not statement and other.lineno <= statement.end_lineno and statement.lineno <= other.end_lineno:
            raise DeleteError(f"{title} shares its line with another statement. Ask the agent to {verb} it.")
    plan.edits.remove_lines(statement.lineno, statement.end_lineno)
    plan.removed.append(statement)
    plan.gone |= _names(statement, ast.Store)


def _take(plan: _Plan, body: list, statement: ast.stmt, lines: set, title: str, text: str, verb: str = "remove") -> None:
    """One statement of the feature taken out, or a boolean kept as the body it was made from."""
    if isinstance(statement, _COMPOUND):
        # A loop or a condition goes whole only when every line in it is the feature's.
        if not all(any(each.lineno <= line <= each.end_lineno for line in lines) for each in _simple(statement)):
            raise DeleteError(f"{title} is made in a loop or a condition with other lines. Ask the agent to {verb} it.")
        _remove(plan, body, statement, title, verb)
        return
    if isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
        made = statement.target.id not in plan.gone
        _remove(plan, body, statement, title, verb)
        if made:
            plan.gone.discard(statement.target.id)  # the body it changed is still made before it
        return
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        name, value = statement.targets[0].id, statement.value
        if name in _names(value):
            # The name changed in place (`tray = bd.fillet(tray.edges(), ...)`): it reads as before,
            # unless what made it goes too.
            made = name not in plan.gone
            _remove(plan, body, statement, title, verb)
            if made:
                plan.gone.discard(name)
            return
        if isinstance(value, ast.BinOp) and isinstance(value.op, _BOOLEANS):
            # A boolean that starts a name keeps the name, as the body it was made from: a cut's
            # left side, or the side of a join this feature did not make.
            kept = value.left
            if not isinstance(value.op, ast.Sub) and _names(value.left) & plan.gone and not _names(value.right) & plan.gone:
                kept = value.right
            if _names(kept) & plan.gone:
                # What it was made from goes too (its child features deleted with it): it goes whole.
                _remove(plan, body, statement, title, verb)
                return
            plan.edits.replace_node(value, ast.get_source_segment(text, kept) or "")
            plan.kept.append((statement, kept))
            dropped = value.right if kept is value.left else value.left
            plan.gone |= _names(dropped, ast.Store)  # a `name := ...` in the side that went
            return
        _remove(plan, body, statement, title, verb)
        return
    if isinstance(statement, ast.Expr):
        _remove(plan, body, statement, title, verb)
        return
    raise DeleteError(f"{title} is made by a line edit mode cannot take out. Ask the agent to {verb} it.")


def _check_uses(plan: _Plan, scope: ast.AST, tree: ast.Module, title: str, verb: str = "remove") -> None:
    """Refuses when a line left still uses a name only the feature made."""
    if not plan.gone:
        return
    skip = {id(node) for statement in plan.removed for node in ast.walk(statement)}
    for statement, kept in plan.kept:
        skip |= {id(node) for node in ast.walk(statement.value)} - {id(node) for node in ast.walk(kept)}
    # Where each name is still made: the module's names and the function's arguments from the start.
    made: dict[str, list[int]] = {}
    if scope is not tree:
        # A name the function assigns is its own throughout it, whatever the module calls so; one only
        # the feature assigned would read the module's after it went, which is not what it read.
        local = {node.id for node in ast.walk(scope) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        for name in _module_names(tree) - local:
            made.setdefault(name, []).append(0)
        for argument in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]:
            made.setdefault(argument.arg, []).append(0)
    uses: dict[str, list[int]] = {}
    for node in ast.walk(scope):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            made.setdefault(node.id, []).append(node.lineno)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in plan.gone:
            uses.setdefault(node.id, []).append(node.lineno)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in plan.gone:
            uses.setdefault(node.target.id, []).append(node.lineno)  # `x += ...` reads x first
    for name in sorted(uses):
        unmade = sorted({line for line in uses[name] if not any(at < line for at in made.get(name, []))})
        if unmade:
            said = f"line {unmade[0]}" if len(unmade) == 1 else f"lines {', '.join(map(str, unmade))}"
            first = "Delete" if verb == "remove" else verb.capitalize()
            raise DeleteError(f"{title} makes {name}, which {said} still use{'s' if len(unmade) == 1 else ''}. "
                              f"{first} what uses it first, or ask the agent.", {"name": name, "lines": unmade})


def _plan(text: str, lines: list[int], title: str, path: str, verb: str):
    """What taking the feature made on ``lines`` out does: its statements, in order, and the plan."""
    if not lines:
        raise DeleteError(f"{title} is not made on a line of the script. Ask the agent to {verb} it.")
    tree = ast.parse(text, path)
    function = _function_at(tree, min(lines))
    body = function.body if function is not None else tree.body
    chosen = {}
    for line in sorted(set(lines)):
        index = next((at for at, statement in enumerate(body) if statement.lineno <= line <= statement.end_lineno), None)
        if index is None:
            raise DeleteError(f"{title} is not made in the function that makes the part. Ask the agent to {verb} it.")
        chosen[index] = body[index]
    plan = _Plan(TextEdits(text))
    for index in sorted(chosen):
        _take(plan, body, chosen[index], set(lines), title, text, verb)
    _check_uses(plan, function or tree, tree, title, verb)
    return body, [chosen[index] for index in sorted(chosen)], plan


def delete(text: str, lines: list[int], title: str, path: str = "<part>") -> tuple[str, int]:
    """``text`` with the feature made on ``lines`` taken out, and the first line that changed."""
    _, statements, plan = _plan(text, lines, title, path, "remove")
    return plan.edits.apply(), statements[0].lineno


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def suppress(text: str, lines: list[int], title: str, kind: str, path: str = "<part>") -> tuple[str, int]:
    """``text`` with the feature made on ``lines`` set aside as comments (see the module's notes),
    and the line that says so. Its lines are one run, at the function's own indent."""
    body, statements, plan = _plan(text, lines, title, path, "suppress")
    first, last = statements[0].lineno, statements[-1].end_lineno
    if any(first <= other.lineno <= last and not any(other is each for each in statements) for other in body):
        raise DeleteError(f"{title} is made on lines with others between them. Ask the agent to suppress it.")
    source = text.splitlines(keepends=True)
    head = source[first - 1]
    indent = head[:len(head) - len(head.lstrip(" \t"))]
    block = [f"{indent}# Suppressed ({kind}, {last - first + 1} line{'' if first == last else 's'}):"]
    for line in source[first - 1:last]:
        bare = line.rstrip("\r\n")
        if not bare.strip():
            block.append(f"{indent}#")
        elif bare.startswith(indent):
            block.append(f"{indent}# {bare[len(indent):]}")
        else:
            raise DeleteError(f"{title} is written across lines edit mode cannot set aside. Ask the agent to suppress it.")
    for statement, kept in plan.kept:
        operand = ast.get_source_segment(text, kept) or ""
        if "\n" in operand:
            raise DeleteError(f"{title} is written across lines edit mode cannot set aside. Ask the agent to suppress it.")
        block.append(f"{indent}{statement.targets[0].id} = {operand}  # {kind} suppressed")
    newline = _newline(text)
    if source and not source[-1].endswith(("\n", "\r")):
        source[-1] += newline
    return "".join(source[:first - 1] + [each + newline for each in block] + source[last:]), first


def suppressed_span(lines: list[str], line: int):
    """The suppressed feature whose line is ``line`` (from 1) of ``lines``: its kind, indent, the
    lines it set aside as they read, and the last line of it (its stand-in lines too); or None."""
    marker = SUPPRESSED.match(lines[line - 1].rstrip("\r\n")) if 0 < line <= len(lines) else None
    if marker is None:
        return None
    indent, kind, count = marker["indent"], marker["kind"], int(marker["count"])
    code = []
    for at in range(line, line + count):
        bare = lines[at].rstrip("\r\n") if at < len(lines) else None
        if bare == f"{indent}#":
            code.append("")
        elif bare is not None and bare.startswith(f"{indent}# "):
            code.append(indent + bare[len(indent) + 2:])
        else:
            return None
    last = line + count
    while last < len(lines) and lines[last].startswith(indent) and lines[last].rstrip("\r\n").endswith(f"  # {kind} suppressed"):
        last += 1
    return {"kind": kind, "indent": indent, "code": code, "last": last}


def unsuppress(text: str, line: int, title: str) -> tuple[str, int]:
    """``text`` with the feature suppressed at ``line`` put back as it was."""
    source = text.splitlines(keepends=True)
    span = suppressed_span(source, line)
    if span is None:
        raise DeleteError(f"{title} is no longer set aside in the script as edit mode left it. Ask the agent to put it back.")
    newline = _newline(text)
    new = "".join(source[:line - 1] + [each + newline for each in span["code"]] + source[span["last"]:])
    try:
        ast.parse(new)
    except SyntaxError:
        raise DeleteError(f"{title}'s lines no longer read as Python. Ask the agent to put it back.") from None
    return new, line


def delete_suppressed(text: str, line: int, title: str) -> tuple[str, int]:
    """``text`` without the feature suppressed at ``line``: its lines go, and a name it kept stays
    as the body it was made from, as Delete leaves it."""
    source = text.splitlines(keepends=True)
    span = suppressed_span(source, line)
    if span is None:
        raise DeleteError(f"{title} is no longer set aside in the script as edit mode left it. Ask the agent to remove it.")
    count = len(span["code"])
    kept = [each.replace(f"  # {span['kind']} suppressed", "", 1) for each in source[line + count:span["last"]]]
    return "".join(source[:line - 1] + kept + source[span["last"]:]), line


def delete_sketch(text: str, line: int, title: str, path: str = "<part>") -> tuple[str, int]:
    """``text`` without the sketch made at ``line``: its `Sketch(...)` line and every line of its
    block that draws on it, relates or dimensions it."""
    try:
        block = find_block(text, line, path)
    except SketchEditError as error:
        raise DeleteError(str(error)) from None
    plan = _Plan(TextEdits(text))
    for index, statement in enumerate(block.statements):
        if index == 0 or block.var in _names(statement):
            _remove(plan, block.body, statement, title)
    _check_uses(plan, block.function or block.tree, block.tree, title)
    return plan.edits.apply(), block.first_line



def _changed(statement: ast.stmt) -> set:
    """The names a statement changes in place: `x += 1`, `x = x + 1`, `x = fillet(x.edges(), 1)`."""
    if isinstance(statement, _COMPOUND):
        return set().union(*(_changed(each) for each in _simple(statement)))
    if isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
        return {statement.target.id}
    if isinstance(statement, ast.Assign):
        return set().union(*(_names(target, ast.Store) for target in statement.targets)) & _names(statement.value)
    return set()


def _reads(statement: ast.stmt) -> set:
    """The names a statement reads, `x += 1`'s x among them."""
    return _names(statement) | {node.target.id for node in ast.walk(statement)
                                if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)}


def _made(statement: ast.stmt) -> set:
    """The names a statement makes new: those it assigns that it does not change in place."""
    if isinstance(statement, _COMPOUND):
        return set().union(*(_made(each) for each in _simple(statement)))
    return _names(statement, ast.Store) - _changed(statement)


def move(text: str, lines: list[int], title: str, to: int | None, path: str = "<part>") -> tuple[str, int]:
    """``text`` with the feature made on ``lines`` moved, as SolidWorks' design tree reorders a
    feature dragged to another place: its statements cut and written again just above line ``to``
    (None: at the end, before the part is returned), and the line it now starts on. Refused when it
    would come before a line that makes a name it reads, or after one that reads a name it makes."""
    if not lines:
        raise DeleteError(f"{title} is not made on a line of the script. Ask the agent to move it.")
    tree = ast.parse(text, path)
    function = _function_at(tree, min(lines))
    body = function.body if function is not None else tree.body
    at = lambda line: next((index for index, statement in enumerate(body) if statement.lineno <= line <= statement.end_lineno), None)
    found = {at(line) for line in lines}
    if None in found:
        raise DeleteError(f"{title} is not made in the function that makes the part. Ask the agent to move it.")
    moving = sorted(found)
    for index in moving:
        statement = body[index]
        if any(other is not statement and other.lineno <= statement.end_lineno and statement.lineno <= other.end_lineno for other in body):
            raise DeleteError(f"{title} shares its line with another statement. Ask the agent to move it.")
    if to is None:
        # The end: before the part is returned.
        to = body[-1].lineno if isinstance(body[-1], ast.Return) else body[-1].end_lineno + 1
    # The statements from `to` on: where it goes among them.
    place = next((index for index, statement in enumerate(body) if statement.lineno >= to), len(body))
    if moving[0] <= place <= moving[-1] + 1:
        if moving == list(range(moving[0], moving[-1] + 1)):
            raise DeleteError(f"{title} is there already.")
        raise DeleteError(f"{title} is made on lines with others between them. Ask the agent to move it.")
    statements = [body[index] for index in moving]
    jumped = body[place:moving[0]] if place < moving[0] else body[moving[-1] + 1:place]
    # Moved past a line, it may not come before what makes a name it reads, nor after what reads a
    # name it makes; and a body one of them changes in place the other may only change in place too
    # (a hole and a fillet on the part swap; a fillet on the post does not go past the post's join).
    first, then = (statements, jumped) if place < moving[0] else (jumped, statements)
    for early in first:
        for late in then:
            made = sorted(_made(late) & _reads(early))
            if made:
                line = (late if late in jumped else early).lineno
                raise DeleteError(f"{title} {'uses' if early in statements else 'makes'} {made[0]}, which line {line} "
                                  f"{'makes' if early in statements else 'uses'}. It cannot go {'above' if early in statements else 'below'} that line.")
    for mine in statements:
        for other in jumped:
            shared = sorted((_changed(mine) & (_reads(other) - _changed(other))) | (_changed(other) & (_reads(mine) - _changed(mine))))
            if shared:
                raise DeleteError(f"{title} and line {other.lineno} both use {shared[0]}, and one changes it, so they cannot change places.")
    source = text.splitlines(keepends=True)
    newline = _newline(text)
    if source and not source[-1].endswith(("\n", "\r")):
        source[-1] += newline
    block = [line for statement in statements for line in source[statement.lineno - 1:statement.end_lineno]]
    spans = {line for statement in statements for line in range(statement.lineno, statement.end_lineno + 1)}
    kept = [(number, line) for number, line in enumerate(source, 1) if number not in spans]
    head = [line for number, line in kept if number < to]
    tail = [line for number, line in kept if number >= to]
    return "".join(head + block + tail), len(head) + 1
