"""A GSL model as the graph of its names: what each name is made from, read from the source alone.

GSL assigns each name once (``omega-gsl.md``: "Each name is assigned once"), so a model is already a
directed acyclic graph: every top-level assignment is a node, every earlier name its expression uses is an
edge into it, and ``return`` is the output. A ``@range(lo, hi)`` name, or one given ``.min`` and ``.max``, is
an input (the field view's slider). This is the view nTop gives a notebook of blocks, each block's inputs
wired from earlier ones, drawn from the program as written, so the code stays the model and the graph is a
reading of it, never a second source.

No compiler is needed and none is run: a statement this does not recognize is left out of the graph, never
guessed at. ``gsl``'s own parse stays the authority on what the model means.

A function can return several values (``mat, col = metal.aluminum();``, the one place GSL assigns several
names at once): that call is one node with an output port per name (its ``outputs``), and an edge from it
names the output it carries (an edge's third element). A property is read like a function of its value
(``solid.dp``, ``shape.box``, a swizzle ``m.xy``): each one read is a small ``property`` node, wired from the
name it is of to every name that uses it. A property set on a shape (``bracket.color = col;``) is a
``property`` node too, marked ``set``, wired from the shape and from the value it is given; ``.min`` and
``.max`` stay a slider's range, as before.
"""

from __future__ import annotations

import re

_NAME = r"[A-Za-z_]\w*"
# Implicit in every GSL expression, never a node (the point and the time).
_IMPLICIT = {"p", "time"}
_NUMBER = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_DIRECTIVE = re.compile(rf"^\s*@({_NAME})\s*\(([^()]*)\)\s*")
_ASSIGN = re.compile(rf"^({_NAME})\s*=(?!=)\s*(.+)$", re.S)
# ``a, b, c = f(...);``: several returns of one call (the spec allows nothing else on the left of a comma).
_MULTI = re.compile(rf"^({_NAME}(?:\s*,\s*{_NAME})+)\s*,?\s*=(?!=)\s*(.+)$", re.S)
_RANGE = re.compile(rf"^({_NAME})\.(min|max)\s*=\s*(.+)$", re.S)
_SET = re.compile(rf"^({_NAME})\.({_NAME})\s*=(?!=)\s*(.+)$", re.S)
_RETURN = re.compile(r"^return\s+(.+)$", re.S)
_CALL = re.compile(rf"^({_NAME}(?:\.{_NAME})*)\s*\(")
# A name, and the first property read off it, if any (``solid.dp.x`` reads ``dp`` of ``solid``).
_REFERENCE = re.compile(rf"(?<![\w.])({_NAME})\b(?:\s*\.\s*({_NAME}))?")


def _statements(text: str) -> list[tuple[int, str]]:
    """The top-level statements, each with the line it starts on: split at ``;`` outside brackets, with
    ``//`` comments taken out."""
    statements, current, depth, line, start = [], [], 0, 1, None
    index = 0
    while index < len(text):
        char = text[index]
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            continue
        if char == "\n":
            line += 1
        if start is None and not char.isspace():
            start = line
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        if char == ";" and depth == 0:
            statements.append((start or line, "".join(current).strip()))
            current, start = [], None
        else:
            current.append(char)
        index += 1
    return [(at, statement) for at, statement in statements if statement]


def _op(expression: str) -> str:
    """What a node is made by: the call its expression is (``unionRound``, ``lattice.solidify``), a number, or
    an expression of operators."""
    expression = expression.strip()
    if _NUMBER.match(expression):
        return "number"
    called = _CALL.match(expression)
    if called and _balanced_call(expression, called.end() - 1):
        return called.group(1)
    return "expression"


def _balanced_call(expression: str, opening: int) -> bool:
    """Whether the bracket at ``opening`` closes at the expression's end: ``f(a)``, not ``f(a) + g(b)``."""
    depth = 0
    for index in range(opening, len(expression)):
        depth += expression[index] in "([{"
        depth -= expression[index] in ")]}"
        if depth == 0:
            return index == len(expression) - 1
    return False


def graph(text: str) -> dict:
    """The model's names as a graph: ``nodes`` (each ``id``, its ``kind``: ``input``, ``constant``, ``block``,
    ``property`` or ``output``, its ``op``, the ``line`` it is written on, an input's ``range``, a call's
    ``outputs`` when it returns several, and a property's ``of`` and ``set``) and ``edges`` (each
    ``[from, to]``, a name to the node whose expression uses it, with a third element, the output used, when
    ``from`` has several), in the order the model writes them."""
    nodes: dict[str, dict] = {}
    edges: list[list[str]] = []
    # Each name to the node that makes it and, for a call with several outputs, which one it is.
    source: dict[str, tuple[str, str | None]] = {}

    def edge(name: str, into: str) -> None:
        node, port = source[name]
        made = [node, into] if port is None else [node, into, port]
        if node != into and made not in edges:
            edges.append(made)

    def uses(expression: str, into: str, line: int) -> None:
        for name, prop in _REFERENCE.findall(expression):
            if name in _IMPLICIT or name not in source or name == into:
                continue
            if not prop:
                edge(name, into)
                continue
            # A property read is a function of the value it is read off: a node of its own, made once.
            key = f"{name}.{prop}"
            if key not in nodes:
                nodes[key] = {"id": key, "kind": "property", "op": prop, "of": name, "line": line}
                source[key] = (key, None)
                edge(name, key)
            edge(key, into)

    # A node is added after the property nodes its expression reads, so every node comes after what it is
    # made from (the layout lays them out in one pass, in this order).
    for line, statement in _statements(text):
        ranged = None
        while (directive := _DIRECTIVE.match(statement)) is not None:
            if directive.group(1) == "range":
                bounds = [part.strip() for part in directive.group(2).split(",")]
                if len(bounds) == 2 and all(_NUMBER.match(each) for each in bounds):
                    ranged = [float(bounds[0]), float(bounds[1])]
            line += statement[:directive.end()].count("\n")
            statement = statement[directive.end():]
        if (made := _RANGE.match(statement)) is not None and _NUMBER.match(made.group(3).strip()):
            name, side, value = made.groups()
            if name in nodes:
                bounds = nodes[name].setdefault("range", [None, None])
                bounds[0 if side == "min" else 1] = float(value)
                nodes[name]["kind"] = "input"
            continue
        if (made := _SET.match(statement)) is not None:
            name, prop, value = made.groups()
            if name in source and prop not in ("min", "max", "period"):
                key = f"{name}.{prop} ="
                edge(name, key)
                uses(value, key, line)
                nodes[key] = {"id": key, "kind": "property", "op": prop, "of": name, "set": True, "line": line}
            continue
        if (returned := _RETURN.match(statement)) is not None:
            uses(returned.group(1), "return", line)
            nodes["return"] = {"id": "return", "kind": "output", "op": "return", "line": line}
            continue
        if (several := _MULTI.match(statement)) is not None:
            names = [each.strip() for each in several.group(1).split(",")]
            key = ", ".join(names)
            uses(several.group(2), key, line)
            nodes[key] = {"id": key, "kind": "block", "op": _op(several.group(2)), "line": line, "outputs": names}
            source.update({each: (key, each) for each in names})
            continue
        if (assigned := _ASSIGN.match(statement)) is None:
            continue
        name, expression = assigned.groups()
        op = _op(expression)
        node = {"id": name, "kind": "input" if ranged else "constant" if op == "number" else "block", "op": op, "line": line}
        if ranged:
            node["range"] = ranged
        uses(expression, name, line)
        nodes[name] = node
        source[name] = (name, None)
    return {"nodes": list(nodes.values()), "edges": edges}
