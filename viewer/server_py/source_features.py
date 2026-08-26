"""Parse editable build123d features from a ``.step.py`` source file.

This module is deliberately source-only: it imports neither build123d nor OCP and
does not generate geometry.  Numeric spans are codepoint offsets so the viewer can
hold edits as drafts and send precise replacements when the user chooses Apply.
"""

from __future__ import annotations

import ast

POSITIONAL_NAMES = {
    "Box": ["length", "width", "height"],
    "Cylinder": ["radius", "height"],
    "Sphere": ["radius"],
    "Hole": ["radius", "depth"],
}
SELECTOR_FIRST = {"fillet": ["radius"], "chamfer": ["length"]}
RECOGNIZED = set(POSITIONAL_NAMES) | set(SELECTOR_FIRST)
CONSUMERS = {"extrude": ["amount"], "revolve": []}
SKETCH_ENTITIES = {"Rectangle": ["width", "height"], "Circle": ["radius"]}


def _make_offset(source: str):
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def off(lineno: int, col_byte: int) -> int:
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        col = len(line.encode("utf-8")[:col_byte].decode("utf-8")) if col_byte else 0
        return starts[lineno - 1] + col

    return off


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _numeric_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value), node
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    ):
        value = float(node.operand.value)
        return (-value if isinstance(node.op, ast.USub) else value), node
    return None, None


def _constant_parameter(name, value_node, off):
    value, span_node = _numeric_node(value_node)
    if value is None:
        return None
    return {
        "name": name,
        "value": value,
        "span": [
            off(span_node.lineno, span_node.col_offset),
            off(span_node.end_lineno, span_node.end_col_offset),
        ],
    }


def _parameters_for_call(op, call, off):
    params = []
    if op in SELECTOR_FIRST:
        numeric_args = [arg for arg in call.args if _numeric_node(arg)[0] is not None]
        positional = zip(SELECTOR_FIRST[op], numeric_args)
    else:
        schema = POSITIONAL_NAMES.get(op, [])
        positional = (
            (schema[index] if index < len(schema) else f"arg{index}", arg)
            for index, arg in enumerate(call.args)
        )
    for name, node in positional:
        param = _constant_parameter(name, node, off)
        if param:
            params.append(param)
    for keyword in call.keywords:
        if keyword.arg is None:
            continue
        param = _constant_parameter(keyword.arg, keyword.value, off)
        if param:
            params.append(param)
    return params


def _position_from_locations(call, off):
    if not call.args or not isinstance(call.args[0], ast.Tuple):
        return None
    values = []
    spans = []
    for element in call.args[0].elts:
        value, span_node = _numeric_node(element)
        if value is None:
            return None
        values.append(value)
        spans.append([
            off(span_node.lineno, span_node.col_offset),
            off(span_node.end_lineno, span_node.end_col_offset),
        ])
    tuple_node = call.args[0]
    return {
        "value": values,
        "span": [off(tuple_node.lineno, tuple_node.col_offset), off(tuple_node.end_lineno, tuple_node.end_col_offset)],
        "elementSpans": spans,
    }


def _statement_span(node, off):
    return [off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)]


def _mode_of(call):
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Attribute) and keyword.value.attr == "SUBTRACT":
            return "subtract"
    return "add"


def _entity_parameters(op, call, off):
    params = []
    schema = SKETCH_ENTITIES[op]
    for index, node in enumerate(call.args):
        name = schema[index] if index < len(schema) else f"arg{index}"
        param = _constant_parameter(name, node, off)
        if param:
            params.append(param)
    for keyword in call.keywords:
        if keyword.arg in (None, "mode"):
            continue
        param = _constant_parameter(keyword.arg, keyword.value, off)
        if param:
            params.append(param)
    return params


def _parse_sketch_block(statement, off, counters):
    counters["sketch"] = counters.get("sketch", 0) + 1
    entities = []
    for inner in statement.body:
        if not isinstance(inner, ast.Expr) or not isinstance(inner.value, ast.Call):
            continue
        op = _call_name(inner.value)
        if op in SKETCH_ENTITIES:
            entities.append({
                "op": op,
                "mode": _mode_of(inner.value),
                "params": _entity_parameters(op, inner.value, off),
            })
    return {
        "id": f"sketch-{counters['sketch']}",
        "entities": entities,
        "stmtSpan": _statement_span(statement, off),
    }


def _consumer_parameters(op, call, off):
    params = []
    numeric_args = [arg for arg in call.args if _numeric_node(arg)[0] is not None]
    for name, node in zip(CONSUMERS[op], numeric_args):
        param = _constant_parameter(name, node, off)
        if param:
            params.append(param)
    for keyword in call.keywords:
        if keyword.arg in (None, "mode"):
            continue
        param = _constant_parameter(keyword.arg, keyword.value, off)
        if param:
            params.append(param)
    return params


def _find_build_part(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            expression = item.context_expr
            if isinstance(expression, ast.Call) and _call_name(expression) == "BuildPart":
                variable = item.optional_vars.id if isinstance(item.optional_vars, ast.Name) else None
                return node, variable
    return None, None


def _collect(statements, off, position, output, counters, pending_sketch):
    for statement in statements:
        if isinstance(statement, ast.With):
            expression = statement.items[0].context_expr if statement.items else None
            name = _call_name(expression) if isinstance(expression, ast.Call) else None
            if name == "Locations":
                _collect(statement.body, off, _position_from_locations(expression, off), output, counters, pending_sketch)
            elif name == "BuildSketch":
                pending_sketch[0] = _parse_sketch_block(statement, off, counters)
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        op = _call_name(statement.value)
        if op in CONSUMERS:
            if pending_sketch[0] is None:
                continue
            counters[op] = counters.get(op, 0) + 1
            output.append({
                "id": f"{op}-{counters[op]}",
                "op": op,
                "mode": _mode_of(statement.value),
                "params": _consumer_parameters(op, statement.value, off),
                "position": position,
                "stmtSpan": _statement_span(statement, off),
                "sketch": pending_sketch[0],
            })
            pending_sketch[0] = None
        elif op in RECOGNIZED:
            counters[op] = counters.get(op, 0) + 1
            output.append({
                "id": f"{op.lower()}-{counters[op]}",
                "op": op,
                "params": _parameters_for_call(op, statement.value, off),
                "position": position,
                "stmtSpan": _statement_span(statement, off),
            })


def parse_source_features(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"ok": False, "error": f"{exc.msg} (line {exc.lineno})"}
    off = _make_offset(source)
    build_part, variable = _find_build_part(tree)
    if build_part is None:
        return {"ok": True, "buildPartVar": None, "features": []}
    features = []
    _collect(build_part.body, off, None, features, {}, [None])
    return {"ok": True, "buildPartVar": variable, "features": features}
