"""A GSL model as the graph of its names: what each name is made from, read from the source alone.

GSL assigns each name once (``omega-gsl.md``: "Each name is assigned once"), so a model is already a
directed acyclic graph: every top-level assignment is a node, every earlier name its expression uses is an
edge into it, and ``return`` is the output. A ``@range(lo, hi)`` name, or one given ``.min`` and ``.max``, is
an input (the field view's slider). This is the view nTop gives a notebook of blocks, each block's inputs
wired from earlier ones, drawn from the program as written, so the code stays the model and the graph is a
reading of it, never a second source.

No compiler is needed and none is run: a statement this does not recognize is left out of the graph, never
guessed at. ``gsl``'s own parse stays the authority on what the model means.
"""

from __future__ import annotations

import re

_NAME = r"[A-Za-z_]\w*"
# Implicit in every GSL expression, never a node (the point and the time).
_IMPLICIT = {"p", "time"}
_NUMBER = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_DIRECTIVE = re.compile(rf"^\s*@({_NAME})\s*\(([^()]*)\)\s*")
_ASSIGN = re.compile(rf"^({_NAME})\s*=\s*(.+)$", re.S)
_PROPERTY = re.compile(rf"^({_NAME})\.(min|max)\s*=\s*(.+)$", re.S)
_RETURN = re.compile(r"^return\s+(.+)$", re.S)
_CALL = re.compile(rf"^({_NAME}(?:\.{_NAME})*)\s*\(")
_REFERENCE = re.compile(rf"(?<![\w.]){_NAME}\b")


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
    """The model's names as a graph: ``nodes`` (each ``id``, its ``kind``: ``input``, ``constant``, ``block``
    or ``output``, its ``op``, the ``line`` it is written on, and an input's ``range``) and ``edges`` (each
    ``[from, to]``, a name to the node whose expression uses it), in the order the model writes them."""
    nodes: dict[str, dict] = {}
    edges: list[list[str]] = []

    def uses(expression: str, into: str) -> None:
        for name in dict.fromkeys(_REFERENCE.findall(expression)):
            if name in nodes and name != into and name not in _IMPLICIT and [name, into] not in edges:
                edges.append([name, into])

    for line, statement in _statements(text):
        ranged = None
        while (directive := _DIRECTIVE.match(statement)) is not None:
            if directive.group(1) == "range":
                bounds = [part.strip() for part in directive.group(2).split(",")]
                if len(bounds) == 2 and all(_NUMBER.match(each) for each in bounds):
                    ranged = [float(bounds[0]), float(bounds[1])]
            line += statement[:directive.end()].count("\n")
            statement = statement[directive.end():]
        if (made := _PROPERTY.match(statement)) is not None:
            name, side, value = made.groups()
            if name in nodes and _NUMBER.match(value.strip()):
                bounds = nodes[name].setdefault("range", [None, None])
                bounds[0 if side == "min" else 1] = float(value)
                nodes[name]["kind"] = "input"
            continue
        if (returned := _RETURN.match(statement)) is not None:
            nodes["return"] = {"id": "return", "kind": "output", "op": "return", "line": line}
            uses(returned.group(1), "return")
            continue
        if (assigned := _ASSIGN.match(statement)) is None:
            continue
        name, expression = assigned.groups()
        op = _op(expression)
        node = {"id": name, "kind": "input" if ranged else "constant" if op == "number" else "block", "op": op, "line": line}
        if ranged:
            node["range"] = ranged
        nodes[name] = node
        uses(expression, name)
    return {"nodes": list(nodes.values()), "edges": edges}
