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
PLANE_BASIS = {
    "XY": {"xAxis": [1.0, 0.0, 0.0], "yAxis": [0.0, 1.0, 0.0], "normal": [0.0, 0.0, 1.0]},
    "XZ": {"xAxis": [1.0, 0.0, 0.0], "yAxis": [0.0, 0.0, 1.0], "normal": [0.0, -1.0, 0.0]},
    "YZ": {"xAxis": [0.0, 1.0, 0.0], "yAxis": [0.0, 0.0, 1.0], "normal": [1.0, 0.0, 0.0]},
    "ZX": {"xAxis": [0.0, 0.0, 1.0], "yAxis": [1.0, 0.0, 0.0], "normal": [0.0, 1.0, 0.0]},
    "ZY": {"xAxis": [0.0, 0.0, 1.0], "yAxis": [0.0, 1.0, 0.0], "normal": [-1.0, 0.0, 0.0]},
}


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


def _numeric_tuple(node, length=None):
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values = []
    for element in node.elts:
        value, _ = _numeric_node(element)
        if value is None:
            return None
        values.append(value)
    if length is not None and len(values) != length:
        return None
    return values


def _normalize_vector(values):
    length = sum(value * value for value in values) ** 0.5
    if length <= 1e-12:
        return None
    return [value / length for value in values]


def _cross(left, right):
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _plane_from_node(node):
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Plane"
        and node.attr in PLANE_BASIS
    ):
        return {"name": f"Plane.{node.attr}", "origin": [0.0, 0.0, 0.0], **PLANE_BASIS[node.attr]}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "offset":
        base = _plane_from_node(node.func.value)
        amount, _ = _numeric_node(node.args[0]) if node.args else (None, None)
        if base and amount is not None:
            base["origin"] = [
                base["origin"][index] + base["normal"][index] * amount
                for index in range(3)
            ]
            base["name"] = f"{base['name']}.offset"
            return base
    if not isinstance(node, ast.Call) or _call_name(node) != "Plane":
        return None
    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
    origin = _numeric_tuple(keywords.get("origin"), 3) or [0.0, 0.0, 0.0]
    x_axis = _normalize_vector(_numeric_tuple(keywords.get("x_dir"), 3) or [1.0, 0.0, 0.0])
    normal = _normalize_vector(_numeric_tuple(keywords.get("z_dir"), 3) or [0.0, 0.0, 1.0])
    y_axis = _normalize_vector(_cross(normal, x_axis)) if x_axis and normal else None
    if not x_axis or not y_axis or not normal:
        return None
    return {
        "name": "Plane",
        "origin": origin,
        "xAxis": x_axis,
        "yAxis": y_axis,
        "normal": normal,
    }


def _sketch_plane(call, position):
    requested = call.args[0] if isinstance(call, ast.Call) and call.args else None
    plane = _plane_from_node(requested) if requested is not None else {
        "name": "Plane.XY",
        "origin": [0.0, 0.0, 0.0],
        **PLANE_BASIS["XY"],
    }
    if plane is None:
        return {
            "supported": False,
            "reason": "The sketch plane is dynamic and cannot be positioned safely in the viewer.",
        }
    location = list((position or {}).get("value") or [])
    location = (location + [0.0, 0.0, 0.0])[:3]
    plane["origin"] = [plane["origin"][index] + location[index] for index in range(3)]
    plane["supported"] = True
    return plane


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


def _combine_sketch_position(parent, child):
    parent_values = list((parent or {}).get("value") or [])
    child_values = list((child or {}).get("value") or [])
    length = max(len(parent_values), len(child_values), 2)
    combined = {
        "value": [
            (parent_values[index] if index < len(parent_values) else 0.0)
            + (child_values[index] if index < len(child_values) else 0.0)
            for index in range(length)
        ]
    }
    child_spans = list((child or {}).get("elementSpans") or [])
    if child_spans:
        combined["elementSpans"] = child_spans
        combined["editableValues"] = child_values
        combined["editableOffsets"] = [
            parent_values[index] if index < len(parent_values) else 0.0
            for index in range(len(child_spans))
        ]
    else:
        parent_spans = list((parent or {}).get("elementSpans") or [])
        if parent_spans:
            combined["elementSpans"] = parent_spans
            combined["editableValues"] = list((parent or {}).get("editableValues") or parent_values)
            combined["editableOffsets"] = list((parent or {}).get("editableOffsets") or [0.0] * len(parent_spans))
    return combined


def _collect_sketch_entities(statements, off, entities, position=None):
    for inner in statements:
        if isinstance(inner, ast.With):
            expression = inner.items[0].context_expr if inner.items else None
            name = _call_name(expression) if isinstance(expression, ast.Call) else None
            if name == "Locations":
                child_position = _combine_sketch_position(position, _position_from_locations(expression, off))
                _collect_sketch_entities(inner.body, off, entities, child_position)
            continue
        if not isinstance(inner, ast.Expr) or not isinstance(inner.value, ast.Call):
            continue
        op = _call_name(inner.value)
        if op in SKETCH_ENTITIES:
            values = list((position or {}).get("value") or [])
            editable_values = list((position or {}).get("editableValues") or [])
            editable_offsets = list((position or {}).get("editableOffsets") or [])
            position_spans = list((position or {}).get("elementSpans") or [])
            position_params = [
                {
                    "name": ("x", "y", "z")[index] if index < 3 else f"axis{index + 1}",
                    "value": editable_values[index],
                    "offset": editable_offsets[index] if index < len(editable_offsets) else 0.0,
                    "span": span,
                }
                for index, span in enumerate(position_spans[:2])
                if index < len(editable_values)
            ]
            entities.append({
                "op": op,
                "mode": _mode_of(inner.value),
                "position": (values + [0.0, 0.0])[:2],
                "positionParams": position_params,
                "params": _entity_parameters(op, inner.value, off),
            })


def _parse_sketch_block(statement, off, counters, position=None):
    counters["sketch"] = counters.get("sketch", 0) + 1
    entities = []
    _collect_sketch_entities(statement.body, off, entities)
    expression = statement.items[0].context_expr if statement.items else None
    return {
        "id": f"sketch-{counters['sketch']}",
        "entities": entities,
        "plane": _sketch_plane(expression, position),
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
                child_position = _combine_sketch_position(position, _position_from_locations(expression, off))
                _collect(statement.body, off, child_position, output, counters, pending_sketch)
            elif name == "BuildSketch":
                pending_sketch[0] = _parse_sketch_block(statement, off, counters, position)
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
