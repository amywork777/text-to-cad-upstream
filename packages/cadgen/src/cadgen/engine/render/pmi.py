"""PMI over a still: an engine document's manufacturing annotations (``structure["pmi"]``, which
``cadgen.engine.pmi`` writes into the document and serves with it) painted over the finished
picture as the CAD Viewer draws them over its page.

A port, operation for operation, of the viewer's own: what a callout says (``@text-to-cad/core``'s
``lib/xbf/xbfPmi.js``, ``readXbfPmi`` and ``pmiCallout``), where it stands in the model
(``lib/xbf/xbfPmiLayout.js``, ``pmiConstruction``, from a face's nodes and surface as
``lib/xbf/xbfEntities.js`` reads them off the part's mesh buffer, the one the viewer reads), and how
it is drawn (``@text-to-cad/ui``'s ``renderers/xbf/pmi/PmiOverlay.jsx`` and ``PmiLabel.jsx``: the
label a few words at the UI's size in a ruled box, a leader to its feature with an arrow (a datum's
on its filled triangle), a distance's dimension and extension lines). One golden made by the
viewer's own code (``lib/xbf/__fixtures__/pmi_plate/constructions.json``) holds both to one layout.

A reference is resolved as the engine resolves one (``refs.resolve_structure``); one the engine
found broken (``missing``, ``ambiguous``, ``invalid``) is drawn where its code placed it, dashed in
its status colour with an open ring where it was anchored, its nominal ``?``. A leader or extension
line whose start the model hides from the camera is faint, its marker hollow. Only the supported
subset is drawn: distance, diameter, datum, flatness and position; anything else is counted, not
drawn. Everything in the scene's coordinates (the document's millimetres), at rest: a still drawn
exploded or posed draws none (``snapshot.py`` refuses asking for it).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

KINDS = ("dimension", "datum", "geometric_tolerance")
DIMENSION_TYPES = ("distance", "diameter")
CHARACTERISTICS = ("flatness", "position")
STATUSES = ("ok", "ambiguous", "missing", "invalid")
MINUS = "−"

# ---- the words (xbfPmi.js) ------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _status(value: Any) -> str:
    return value if value in STATUSES else "missing"


def _tolerance(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict) or value.get("type") != "plus_minus":
        return None
    upper, lower = _finite(value.get("upper")), _finite(value.get("lower"))
    return None if upper is None or lower is None else {"upper": upper, "lower": lower}


def read(structure: dict[str, Any]) -> list[dict[str, Any]]:
    """The document's PMI as the viewer reads it (``readXbfPmi``): each entry with what its kind
    carries, a field missing or of the wrong type read as nothing, and whether it is drawn."""
    found, seen = [], set()
    for index, item in enumerate(structure.get("pmi") or []):
        if not isinstance(item, dict):
            continue
        ident = _text(item.get("id")) or f"#{index + 1}"
        if ident in seen:
            ident = f"{ident}#{index + 1}"
        seen.add(ident)
        refs = []
        for ref in item.get("refs") or []:
            written = _text((ref or {}).get("written")) or _text((ref or {}).get("ref"))
            refs.append({"role": _text(ref.get("role")) or "feature", "ref": _text(ref.get("ref")) or written,
                         "written": written, "status": _status(ref.get("status"))})
        dimension = item.get("dimension") if isinstance(item.get("dimension"), dict) else None
        gdt = item.get("geometric_tolerance") if isinstance(item.get("geometric_tolerance"), dict) else None
        presentation = item.get("presentation") if isinstance(item.get("presentation"), dict) else None
        point3 = lambda value: [float(v) for v in value] if isinstance(value, list) and len(value) == 3 and all(_finite(v) is not None for v in value) else None  # noqa: E731
        entry = {
            "id": ident, "kind": _text(item.get("kind")), "status": _status(item.get("status")), "problem": _text(item.get("problem")),
            "part": item.get("part") if isinstance(item.get("part"), int) and not isinstance(item.get("part"), bool) else None, "refs": refs,
            "dimension": {"type": _text(dimension.get("type")), "nominal": _finite((dimension.get("nominal") or {}).get("value")),
                          "tolerance": _tolerance(dimension.get("tolerance"))} if dimension else None,
            "datum": {"letter": _text(item["datum"].get("letter"))} if isinstance(item.get("datum"), dict) and _text(item["datum"].get("letter")) else None,
            "tolerance": {"characteristic": _text(gdt.get("characteristic")), "value": _finite(gdt.get("value")),
                          "zone": _text(gdt.get("zone")) or None,
                          "datums": [d for d in (gdt.get("datums") or []) if isinstance(d, str) and d]} if gdt else None,
            "presentation": {"anchor": point3(presentation.get("anchor")), "offset": point3(presentation.get("offset"))}
            if presentation and point3(presentation.get("anchor")) and point3(presentation.get("offset")) else None,
        }
        entry["supported"] = _supported(entry)
        found.append(entry)
    return found


def _supported(entry: dict[str, Any]) -> bool:
    kind = entry["kind"]
    if kind == "dimension":
        dimension = entry["dimension"] or {}
        return dimension.get("type") in DIMENSION_TYPES and (dimension.get("nominal") is not None or entry["status"] != "ok")
    if kind == "datum":
        return entry["datum"] is not None
    if kind == "geometric_tolerance":
        tolerance = entry["tolerance"] or {}
        return tolerance.get("characteristic") in CHARACTERISTICS and tolerance.get("value") is not None
    return False


def _fixed(value: float, places: int) -> str:
    # JavaScript's toFixed: the nearer of the two, the larger on a tie (Python's rounds half to even).
    scaled = abs(value) * 10 ** places
    whole = math.floor(scaled + 0.5)
    text = str(whole).rjust(places + 1, "0")
    return f"{text[:-places]}.{text[-places:]}" if places else text


def decimals(value: float) -> int:
    fixed = _fixed(value, 4).rstrip("0")
    dot = fixed.find(".")
    return 0 if dot < 0 or dot == len(fixed) - 1 else len(fixed) - dot - 1


def number(value: float, places: int | None = None) -> str:
    """``pmiNumber``: at ``places`` decimals (what the value needs, up to four), a true minus sign."""
    places = decimals(value) if places is None else places
    fixed = _fixed(value, places)
    return fixed if float(fixed) == 0 else f"{MINUS if value < 0 else ''}{fixed}"


def tolerance_text(tolerance: dict[str, float] | None) -> dict[str, Any] | None:
    """``pmiToleranceText``: ``±0.2`` the same both ways, else each deviation signed, a zero bare."""
    if not tolerance:
        return None
    upper, lower = tolerance["upper"], tolerance["lower"]
    places = max(decimals(upper), decimals(lower))
    if upper > 0 and abs(upper + lower) < 1e-12:
        return {"symmetric": True, "text": f"±{number(upper, places)}", "places": places}
    signed = lambda value: "0" if value == 0 else (f"+{number(value, places)}" if value > 0 else number(value, places))  # noqa: E731
    return {"symmetric": False, "upper": signed(upper), "lower": signed(lower), "text": f"{signed(upper)}/{signed(lower)}", "places": places}


def callout(entry: dict[str, Any]) -> dict[str, Any]:
    """``pmiCallout``: what a callout says, in the pieces its label draws."""
    if entry["kind"] == "dimension":
        tolerance = tolerance_text(entry["dimension"]["tolerance"])
        nominal = entry["dimension"]["nominal"]
        shown = "?" if nominal is None else number(nominal, max(tolerance["places"], 0) if tolerance else min(decimals(nominal), 2))
        return {"kind": "dimension", "diameter": entry["dimension"]["type"] == "diameter", "nominal": shown, "tolerance": tolerance}
    if entry["kind"] == "datum":
        return {"kind": "datum", "letter": entry["datum"]["letter"]}
    tolerance = entry["tolerance"]
    return {"kind": "frame", "characteristic": tolerance["characteristic"], "diameter": tolerance["zone"] == "diameter",
            "value": number(tolerance["value"]), "datums": list(tolerance["datums"])}


# ---- a face, from its part's mesh (xbfEntities.js) ------------------------------------------

PLANE_NORMAL = 1e-6
SQUARE = 1e-4
RADIAL = 1e-3
ROUND = 1e-3


def _dot(a: Any, b: Any) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Any, b: Any) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _add(a: Any, b: Any) -> list[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _scale(a: Any, k: float) -> list[float]:
    return [a[0] * k, a[1] * k, a[2] * k]


def _cross(a: Any, b: Any) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _length(a: Any) -> float:
    return math.hypot(a[0], a[1], a[2])


def _unit(a: Any) -> list[float] | None:
    size = _length(a)
    return _scale(a, 1 / size) if size > 1e-12 else None


def face_nodes(mesh: Any, ordinal: int) -> tuple[list[list[float]], list[list[float]]] | None:
    """``xbfFaceNodes``: a face's nodes and their normals, each node once, in the order its
    triangles first name them; None for no such face."""
    rows = np.nonzero(np.asarray(mesh.faces)[:, 0] == ordinal)[0] if len(mesh.faces) else []
    if not len(rows):
        return None
    _ordinal, first, count = (int(v) for v in mesh.faces[rows[0]])
    seen, points, normals = set(), [], []
    for node in mesh.indices[first:first + count]:
        node = int(node)
        if node in seen:
            continue
        seen.add(node)
        points.append([float(v) for v in mesh.positions[node]])
        normals.append([float(v) for v in mesh.normals[node]])
    return points, normals


def _solve3(m: list[float], b: list[float]) -> list[float] | None:
    a, bb, c, d, e, f, g, h, i = m
    det = a * (e * i - f * h) - bb * (d * i - f * g) + c * (d * h - e * g)
    size = max(abs(v) for v in m)
    if not abs(det) > size * size * size * 1e-9:
        return None
    inverse = [e * i - f * h, c * h - bb * i, bb * f - c * e, f * g - d * i, a * i - c * g, c * d - a * f, d * h - e * g,
               bb * g - a * h, a * e - bb * d]
    return [(inverse[row * 3] * b[0] + inverse[row * 3 + 1] * b[1] + inverse[row * 3 + 2] * b[2]) / det for row in range(3)]


def _meeting_point(points: list[list[float]], directions: list[list[float]], keep: list[float] | None = None) -> list[float] | None:
    m, b = [0.0] * 9, [0.0, 0.0, 0.0]
    for point, d in zip(points, directions):
        for row in range(3):
            for column in range(3):
                projector = (1 if row == column else 0) - d[row] * d[column]
                m[row * 3 + column] += projector
                b[row] += projector * point[column]
    if keep:
        for row in range(3):
            for column in range(3):
                m[row * 3 + column] += keep[row] * keep[column]
    return _solve3(m, b)


def _round_about(points: list[list[float]], normals: list[list[float]], center: list[float], off: float) -> float | None:
    radii = [_length(_sub(point, center)) for point in points]
    radius = sum(radii) / len(radii)
    if not radius > off:
        return None
    if any(abs(value - radius) > max(radius * ROUND, off) for value in radii):
        return None
    radial = all(_length(_cross(_scale(_sub(point, center), 1 / radii[i]), normals[i])) <= RADIAL for i, point in enumerate(points))
    return radius if radial else None


def face_surface(mesh: Any, ordinal: int) -> dict[str, Any] | None:
    """``xbfFaceSurface``, the readings a callout stands on: a plane (``normal``, ``origin``) or a
    cylinder (``axis``, ``origin``, ``radius``); ``{"type": "surface"}`` for anything else."""
    nodes = face_nodes(mesh, ordinal)
    if not nodes or len(nodes[0]) < 3:
        return None
    points = nodes[0]
    normals = [_unit(normal) or [0.0, 0.0, 0.0] for normal in nodes[1]]
    count = len(points)
    total = [0.0, 0.0, 0.0]
    for point in points:
        total = _add(total, point)
    middle = _scale(total, 1 / count)
    span = max(_length(_sub(point, middle)) for point in points)
    far = max(max(abs(point[0]), abs(point[1]), abs(point[2])) for point in points)
    off = max(span * 1e-4, far * 4e-6, 1e-7)
    first = normals[0]
    if all(_dot(normal, first) >= 1 - PLANE_NORMAL for normal in normals) and all(abs(_dot(_sub(p, middle), first)) <= off for p in points):
        return {"type": "plane", "normal": first, "origin": middle}
    across = first
    for normal in normals:
        if abs(_dot(normal, first)) < abs(_dot(across, first)):
            across = normal
    axis = _unit(_cross(first, across))
    if axis and _length(_cross(first, across)) > 1e-3 and all(abs(_dot(normal, axis)) <= SQUARE for normal in normals):
        flat = lambda point: _sub(point, _scale(axis, _dot(point, axis)))  # noqa: E731
        directions = [_unit(flat(normal)) or normal for normal in normals]
        center = _meeting_point([flat(p) for p in points], directions, axis)
        radius = center and _round_about([flat(p) for p in points], directions, center, off)
        if radius:
            return {"type": "cylinder", "axis": axis, "origin": _add(center, _scale(axis, _dot(middle, axis))), "radius": radius}
    return {"type": "surface"}


def _place_point(m: list[float], p: Any) -> list[float]:
    return [m[row] * p[0] + m[4 + row] * p[1] + m[8 + row] * p[2] + m[12 + row] for row in range(3)]


def _place_direction(m: list[float], d: Any) -> list[float]:
    return _unit([m[row] * d[0] + m[4 + row] * d[1] + m[8 + row] * d[2] for row in range(3)]) or list(d)


def element(mesh: Any, ordinal: int, matrix: list[float]) -> dict[str, Any] | None:
    """A face where its instance stands (``elementGeometry(id, { points: true })``): its surface
    and its nodes, placed by the instance's matrix (column-major, the structure's)."""
    surface = face_surface(mesh, ordinal)
    nodes = face_nodes(mesh, ordinal)
    if surface is None or nodes is None:
        return None
    if surface["type"] == "plane":
        placed = {"type": "plane", "normal": _place_direction(matrix, surface["normal"]), "origin": _place_point(matrix, surface["origin"])}
    elif surface["type"] == "cylinder":
        placed = {"type": "cylinder", "axis": _place_direction(matrix, surface["axis"]), "origin": _place_point(matrix, surface["origin"]),
                  "radius": surface["radius"]}
    else:
        placed = {"type": surface["type"]}
    return {"surface": placed, "points": [_place_point(matrix, point) for point in nodes[0]]}


# ---- where it stands (xbfPmiLayout.js) ------------------------------------------------------

SPREAD = math.pi / 4.5
REACH_SHARE, REACH_MIN = 0.18, 4.0


def _across(v: Any, n: Any) -> list[float]:
    return _sub(v, _scale(n, _dot(v, n)))


def _turned(v: Any, n: Any, angle: float) -> list[float]:
    return _add(_add(_scale(v, math.cos(angle)), _scale(_cross(n, v), math.sin(angle))), _scale(n, _dot(n, v) * (1 - math.cos(angle))))


def _any_perpendicular(n: Any) -> list[float] | None:
    return _unit(_cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else _cross(n, [0, 1, 0]))


def reach(bounds: tuple[Any, Any] | None) -> float:
    diagonal = _length(_sub(bounds[1], bounds[0])) if bounds else 0.0
    return max(REACH_MIN, diagonal * REACH_SHARE)


def feature_point(geometry: dict[str, Any] | None, centre: Any = (0, 0, 0)) -> list[float] | None:
    """``pmiFeaturePoint``: a node of the face nearest its nodes' middle; a cylinder's rim node at
    its axis's far end, the one farthest out from the model's middle."""
    points = (geometry or {}).get("points") or []
    if not points:
        origin = ((geometry or {}).get("surface") or {}).get("origin")
        return list(origin) if origin else None
    surface = geometry.get("surface") or {}
    if surface.get("type") == "cylinder" and surface.get("axis"):
        axis = surface["axis"]
        far = max(_dot(point, axis) for point in points)
        rim = [point for point in points if _dot(point, axis) > far - 1e-6 * max(1, abs(far))]
        best = rim[0]
        for point in rim:
            if _length(_sub(point, centre)) > _length(_sub(best, centre)) + 1e-9:
                best = point
        return list(best)
    total = [0.0, 0.0, 0.0]
    for point in points:
        total = _add(total, point)
    middle = _scale(total, 1 / len(points))
    best = points[0]
    for point in points:
        if _length(_sub(point, middle)) < _length(_sub(best, middle)) - 1e-9:
            best = point
    return list(best)


def _edge_point(geometry: dict[str, Any], centre: Any, n: Any) -> list[float] | None:
    points = geometry.get("points") or []
    if not points:
        origin = (geometry.get("surface") or {}).get("origin")
        return list(origin) if origin else None
    out = lambda point: _length(_across(_sub(point, centre), n))  # noqa: E731
    best = points[0]
    for point in points:
        if out(point) > out(best) + 1e-9:
            best = point
    return list(best)


def _outward(geometry: dict[str, Any] | None) -> list[float] | None:
    surface = (geometry or {}).get("surface") or {}
    if surface.get("type") == "plane" and surface.get("normal"):
        return _unit(surface["normal"])
    if surface.get("type") == "cylinder" and surface.get("axis"):
        return _unit(surface["axis"])
    return None


def construction(entry: dict[str, Any], geometry: dict[str, Any], bounds: tuple[Any, Any] | None, turn: int = 0) -> dict[str, Any] | None:
    """``pmiConstruction``: the scene points a callout is drawn from -- its anchor, its label, a
    distance's dimension and extension lines -- or None where it can be drawn nowhere."""
    centre = _scale(_add(bounds[0], bounds[1]), 0.5) if bounds else [0.0, 0.0, 0.0]
    far = reach(bounds)
    given = entry["presentation"]
    at = {"anchor": list(given["anchor"]), "offset": list(given["offset"])} if given else None
    placed = "given" if given else "default"
    broken = lambda: {"anchor": at["anchor"], "label": _add(at["anchor"], at["offset"]), "dimension": None, "presentation": at,  # noqa: E731
                      "placed": placed, "broken": True} if at else None
    if entry["kind"] == "dimension" and entry["dimension"]["type"] == "distance":
        source, target = geometry.get("from"), geometry.get("to")
        n = _outward(source)
        if not source or not target or not n or (target.get("surface") or {}).get("type") != "plane" or source["surface"].get("type") != "plane":
            return broken()
        level = lambda point: _dot(point, n)  # noqa: E731
        anchor = at["anchor"] if at else _edge_point(source, centre, n)
        if at:
            offset = at["offset"]
        else:
            away = _unit(_across(_sub(anchor, centre), n)) or _any_perpendicular(n)
            side = _turned(away, n, turn * SPREAD)
            offset = _add(_scale(n, (level(target["surface"]["origin"]) - level(anchor)) / 2), _scale(side, far * 0.5))
        label = _add(anchor, offset)
        on_plane = lambda point, face: _sub(point, _scale(n, level(point) - level(face["surface"]["origin"])))  # noqa: E731
        on_from, on_to = on_plane(label, source), on_plane(label, target)
        return {"anchor": anchor, "label": label, "dimension": {"from": on_from, "to": on_to,
                "extensions": [[on_plane(anchor, source), on_from], [on_plane(anchor, target), on_to]]},
                "presentation": {"anchor": anchor, "offset": offset}, "placed": placed}
    feature = geometry.get("feature")
    out = _outward(feature)
    if not feature or not out:
        return broken()
    anchor = at["anchor"] if at else feature_point(feature, centre)
    if at:
        offset = at["offset"]
    else:
        away = _unit(_across(_sub(anchor, centre), out)) or _any_perpendicular(out)
        side = _turned(away, out, turn * SPREAD)
        offset = _add(_scale(out, far), _scale(side, far * 0.6))
    return {"anchor": anchor, "label": _add(anchor, offset), "dimension": None, "presentation": {"anchor": anchor, "offset": offset},
            "placed": placed}


def to_scene(presentation: dict[str, Any] | None, matrix: list[float] | None) -> dict[str, Any] | None:
    """``pmiPresentationToScene``: a placement in its part's frame where the part stands."""
    if not presentation or not matrix:
        return presentation
    return {"anchor": _place_point(matrix, presentation["anchor"]),
            "offset": [matrix[row] * presentation["offset"][0] + matrix[4 + row] * presentation["offset"][1]
                       + matrix[8 + row] * presentation["offset"][2] for row in range(3)]}


def constructions(structure: dict[str, Any], meshes: dict[str, Any], bounds: tuple[Any, Any] | None) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Every supported entry with its construction (``useXbfPmi``'s): its references resolved as
    the engine resolves them, each that names one face of a part taken from that part's mesh, its
    placement taken from its part's frame, and each later annotation of a feature turned from the
    one before it."""
    from cadgen.engine import refs as grammar

    prototypes, instances = structure["prototypes"], structure["instances"]
    found, turns = [], {}
    for entry in read(structure):
        if not entry["supported"]:
            continue
        geometry, firsts = {}, []
        for at, ref in enumerate(entry["refs"]):
            face = None
            if ref["status"] == "ok":
                try:
                    hits = grammar.resolve_structure(structure, ref["ref"])
                except Exception:  # noqa: BLE001 -- a ref the page cannot find names nothing here either
                    hits = []
                if len(hits) == 1 and hits[0].kind == "face":
                    instance = hits[0].node.payload["instance"]
                    prototype = prototypes[hits[0].node.payload["prototype"]]
                    face = element(meshes[prototype["key"]], int(hits[0].ordinal), instances[instance]["matrix"])
                    if at == 0:  # what a feature's turns count by: the first reference's element, as the viewer counts
                        firsts.append(f"i{instance}/face/{hits[0].ordinal}")
            geometry[ref["role"]] = face
        frame = next((item["matrix"] for item in instances if item.get("prototype") == entry["part"]), None) if entry["part"] is not None else None
        placed = {**entry, "presentation": to_scene(entry["presentation"], frame)}
        first = firsts[0] if firsts else entry["id"]
        turn = turns.get(first, 0)
        turns[first] = turn + 1
        found.append((entry, construction(placed, geometry, bounds, turn)))
    return found


# ---- drawn over the picture (PmiOverlay.jsx, PmiLabel.jsx) ----------------------------------

# Ink on paper, the light theme's: the foreground on the background, as a label reads over any
# part. A document's picture is drawn on the light look's backdrop whatever its appearance (which
# only a drawing's paper takes), so its callouts are the light theme's too.
INK = (10, 10, 10)
PAPER = (255, 255, 255)
PAPER_ALPHA, BORDER_ALPHA, RULE_ALPHA, LEADER_ALPHA, BEHIND_ALPHA = 0.95, 0.6, 0.4, 0.85, 0.3
# A reference the engine could not stand the annotation on: it names nothing, or a face it cannot
# stand on (failed, red), or several (a warning, amber).
STATUS_COLOR = {"missing": (239, 68, 68), "invalid": (239, 68, 68), "ambiguous": (245, 158, 11)}
ARROW, ARROW_HALF, DATUM = 7.0, 2.6, 6.0
DASH, GAP = 4.0, 3.0
LABEL_CLEAR = 6.0
LABEL_MARGIN = 4.0
GAP_PX = 3.0
# The label: 11 px words (``text-tiny``) on 16 px lines, a 1 px rule and 1 px inside it, cells 4 px in.
TEXT, SMALL, ROW, PAD, GLYPH = (400, 11), (400, 10), 16.0, 4.0, 12.0


def _glyph(painter: Any, name: str, x: float, middle: float, color: Any, alpha: float) -> None:
    """A GD&T symbol on the 24-unit grid the viewer's are drawn on (``pmiGlyphs.jsx``), 12 px."""
    k = GLYPH / 24
    at = lambda u, v: (x + u * k, middle - GLYPH / 2 + v * k)  # noqa: E731
    width = 2 * k
    if name == "diameter":
        painter.disc(at(12, 12), 6.5 * k, color, ring=width, alpha=alpha)
        painter.line(at(5.5, 18.5), at(18.5, 5.5), width, color, alpha)
    elif name == "flatness":
        corners = [at(3.5, 17), at(8, 7), at(20.5, 7), at(16, 17)]
        for index, corner in enumerate(corners):
            painter.line(corner, corners[(index + 1) % 4], width, color, alpha)
    elif name == "position":
        painter.disc(at(12, 12), 5.5 * k, color, ring=width, alpha=alpha)
        painter.line(at(12, 3), at(12, 21), width, color, alpha)
        painter.line(at(3, 12), at(21, 12), width, color, alpha)


def _words(painter: Any, text: str, face: Any, x: float, middle: float, color: Any) -> None:
    """Words with their em box's middle on ``middle``, starting at ``x`` (viewer pixels)."""
    from cadgen.engine.render.text import coverage

    scale = painter.scale
    top = (middle - face.size / 2) * scale
    left = x * scale
    box = (int(max(math.floor(left - 2), 0)), int(max(math.floor(top - 4), 0)))
    size = (min(int(math.ceil(face.width(text) * scale)) + 5, painter.width - box[0]),
            min(int(math.ceil(face.size * scale)) + 9, painter.height - box[1]))
    if size[0] <= 0 or size[1] <= 0:
        return
    cover = coverage([text], face, size, (left - box[0], top - box[1]), 0, scale=scale)
    painter.coverage((slice(box[1], box[1] + size[1]), slice(box[0], box[0] + size[0])), cover, color)


def _cells(said: dict[str, Any]) -> list[dict[str, Any]]:
    """A label's cells, each ``{glyphs, words, small}``: what ``PmiLabel`` lays out in a row."""
    from cadgen.engine.render.text import face

    words, small = face(*TEXT), face(*SMALL)
    if said["kind"] == "dimension":
        cell = {"glyphs": ["diameter"] if said["diameter"] else [], "words": said["nominal"], "small": None}
        tolerance = said["tolerance"]
        if tolerance and tolerance["symmetric"]:
            cell["words"] += f" {tolerance['text']}"
        elif tolerance:
            cell["small"] = (tolerance["upper"], tolerance["lower"])
        cells = [cell]
    elif said["kind"] == "datum":
        cells = [{"glyphs": [], "words": said["letter"], "small": None, "min": 20.0}]
    else:
        cells = [{"glyphs": [said["characteristic"]], "words": "", "small": None},
                 {"glyphs": ["diameter"] if said["diameter"] else [], "words": said["value"], "small": None},
                 *({"glyphs": [], "words": datum, "small": None} for datum in said["datums"])]
    for cell in cells:
        width = PAD * 2 + len(cell["glyphs"]) * (GLYPH + 1) + (words.width(cell["words"]) if cell["words"] else 0)
        if cell["small"]:
            width += 2 + max(small.width(cell["small"][0]), small.width(cell["small"][1]))
        cell["width"] = max(width, cell.get("min", 0.0))
    return cells


def _label(painter: Any, said: dict[str, Any], box: dict[str, float], ink: Any, paper: Any, border: Any, dashed: bool) -> None:
    from cadgen.engine.render.text import face

    words, small = face(*TEXT), face(*SMALL)
    x, y, w, h = box["x"] - box["w"] / 2, box["y"] - box["h"] / 2, box["w"], box["h"]
    painter.rounded_box(x, y, w, h, 2.0, paper, PAPER_ALPHA)
    if dashed:
        _dashed_box(painter, x, y, w, h, border)
    else:
        painter.rounded_box(x, y, w, h, 2.0, border, BORDER_ALPHA if border == ink else 1.0, stroke=1.0)
    at = x
    for index, cell in enumerate(box["cells"]):
        if index:
            painter.line((at, y + 1), (at, y + h - 1), 1.0, ink, RULE_ALPHA)
        # A datum's letter centred in its box (``min-w-5``); every other cell's content 4 px in.
        content = len(cell["glyphs"]) * (GLYPH + 1) + (words.width(cell["words"]) if cell["words"] else 0)
        start = at + (cell["width"] - content) / 2 if cell.get("min") else at + PAD
        for glyph in cell["glyphs"]:
            _glyph(painter, glyph, start, box["y"], ink, 1.0)
            start += GLYPH + 1
        if cell["words"]:
            _words(painter, cell["words"], words, start, box["y"], ink)
            start += words.width(cell["words"])
        if cell["small"]:
            _words(painter, cell["small"][0], small, start + 2, box["y"] - 5.6, ink)
            _words(painter, cell["small"][1], small, start + 2, box["y"] + 5.6, ink)
        at += cell["width"]


def _dashed(painter: Any, a: Any, b: Any, width: float, color: Any, alpha: float) -> None:
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if not length:
        return
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    at = 0.0
    while at < length:
        end = min(at + DASH, length)
        painter.line((a[0] + ux * at, a[1] + uy * at), (a[0] + ux * end, a[1] + uy * end), width, color, alpha)
        at = end + GAP


def _dashed_box(painter: Any, x: float, y: float, w: float, h: float, color: Any) -> None:
    for a, b in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
        _dashed(painter, a, b, 1.0, color, 1.0)


def _arrow(painter: Any, tip: Any, toward: Any, color: Any, alpha: float, hollow: bool = False) -> None:
    angle = math.atan2(tip[1] - toward[1], tip[0] - toward[0])
    c, s = math.cos(angle), math.sin(angle)
    p = (tip[0] - ARROW * c + ARROW_HALF * s, tip[1] - ARROW * s - ARROW_HALF * c)
    q = (tip[0] - ARROW * c - ARROW_HALF * s, tip[1] - ARROW * s + ARROW_HALF * c)
    if hollow:
        for a, b in ((tip, p), (p, q), (q, tip)):
            painter.line(a, b, 1.0, color, alpha)
    else:
        painter.triangle(tip, p, q, color, alpha)


def _datum_triangle(painter: Any, base: Any, toward: Any, color: Any, alpha: float, hollow: bool = False) -> None:
    angle = math.atan2(toward[1] - base[1], toward[0] - base[0])
    along, side = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
    corners = [(base[0] + side[0] * DATUM, base[1] + side[1] * DATUM), (base[0] - side[0] * DATUM, base[1] - side[1] * DATUM),
               (base[0] + along[0] * DATUM * 1.4, base[1] + along[1] * DATUM * 1.4)]
    if hollow:
        for index, corner in enumerate(corners):
            painter.line(corner, corners[(index + 1) % 3], 1.0, color, alpha)
    else:
        painter.triangle(*corners, color, alpha)


def _box_edge(start: Any, box: dict[str, float]) -> tuple[float, float]:
    dx, dy = start[0] - box["x"], start[1] - box["y"]
    if not dx and not dy:
        return box["x"], box["y"]
    s = min(box["w"] / 2 / abs(dx or 1e-9), box["h"] / 2 / abs(dy or 1e-9), 1)
    return box["x"] + dx * s, box["y"] + dy * s


def separate(boxes: list[dict[str, Any]]) -> None:
    """``separateLabels``: a label the code never placed that covers one before it steps below it, a
    few pixels clear; one the code placed stays, and the others keep clear of it (in place)."""
    overlaps = lambda a, b: abs(a["x"] - b["x"]) * 2 < a["w"] + b["w"] and abs(a["y"] - b["y"]) * 2 < a["h"] + b["h"]  # noqa: E731
    fixed = [box for box in boxes if not box["movable"]]
    placed: list[dict[str, Any]] = []
    for box in boxes:
        if box["movable"]:
            for _ in range(len(boxes) + 1):
                hit = next((other for other in [*fixed, *placed] if other is not box and overlaps(box, other)), None)
                if hit is None:
                    break
                box["y"] = hit["y"] + (hit["h"] + box["h"]) / 2 + GAP_PX
        placed.append(box)


class Hidden:
    """Whether the model hides a point from the camera (``pmiHidden.js``): a ray from the eye
    through the point meets a shown part's triangle nearer than the point by more than ``tolerance``."""

    def __init__(self, scene: Any, tolerance: float) -> None:
        triangles = []
        for index, instance in enumerate(scene.structure["instances"]):
            if index in scene.hidden:
                continue
            mesh = scene.meshes[scene.prototypes[instance["prototype"]]["key"]]
            if not len(mesh.indices):
                continue
            corners = np.asarray(mesh.positions, np.float64)[np.asarray(mesh.indices).reshape(-1, 3)]
            matrix = scene.matrices[index]
            triangles.append(corners @ matrix[:3, :3].T + matrix[:3, 3])
        self.triangles = np.concatenate(triangles) if triangles else np.zeros((0, 3, 3))
        camera = scene.camera or {}
        self.eye = np.asarray(camera.get("eye", (0, 0, 1)), float)
        target = np.asarray(camera.get("target", (0, 0, 0)), float)
        self.direction = (target - self.eye) / (np.linalg.norm(target - self.eye) or 1.0)
        self.perspective = camera.get("projection") == "perspective"
        self.tolerance = tolerance

    def __call__(self, point: Any) -> bool:
        if not len(self.triangles):
            return False
        point = np.asarray(point, float)
        if self.perspective:
            direction = (point - self.eye) / (np.linalg.norm(point - self.eye) or 1.0)
            origin = self.eye
        else:
            direction = self.direction
            origin = point - direction * 1e6
        a, b, c = self.triangles[:, 0], self.triangles[:, 1], self.triangles[:, 2]
        e1, e2 = b - a, c - a
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        t0 = origin - a
        u = np.einsum("ij,ij->i", t0, p) * inv
        q = np.cross(t0, e1)
        v = (q @ direction) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 0)
        if not hit.any():
            return False
        return bool(t[hit].min() < float((point - origin) @ direction) - self.tolerance)


def paint(frame: np.ndarray, drawn: list[tuple[dict[str, Any], dict[str, Any]]], project: Any, hidden: Any) -> None:
    """The callouts painted over ``frame`` (sRGB bytes, (h, w, 3), in place), as the viewer's
    overlay paints its canvas and lays its labels: ``drawn`` each entry with its construction,
    ``project`` world points to output pixels, ``hidden`` whether the model hides a world point."""
    from cadgen.engine.render.overlay import REFERENCE_HEIGHT, Painter

    height = frame.shape[0]
    scale = height / REFERENCE_HEIGHT
    painter = Painter(frame, scale)
    ink, paper = INK, PAPER
    to_px = lambda point: tuple(v / scale for v in project(np.array([point], float))[0])  # noqa: E731
    boxes = []
    for entry, made in drawn:
        if made is None:
            continue
        said = callout(entry)
        cells = _cells(said)
        label = to_px(made["label"])
        box = {"x": label[0], "y": label[1], "w": sum(cell["width"] for cell in cells), "h": ROW + 4, "cells": cells,
               "movable": made["placed"] == "default" and not made["dimension"], "entry": entry, "made": made, "said": said}
        dimension = made["dimension"]
        if dimension:
            # A distance's words beside its dimension line, out from the part, clear of it.
            a, b, anchor = to_px(dimension["from"]), to_px(dimension["to"]), to_px(made["anchor"])
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            span = math.hypot(b[0] - a[0], b[1] - a[1])
            along = ((b[0] - a[0]) / span, (b[1] - a[1]) / span) if span > 1e-6 else (0.0, 0.0)
            out = (mid[0] - anchor[0], mid[1] - anchor[1])
            share = out[0] * along[0] + out[1] * along[1]
            out = (out[0] - along[0] * share, out[1] - along[1] * share)
            size = math.hypot(*out)
            if size < 1:
                out, size = (-(b[1] - a[1]), b[0] - a[0]), math.hypot(b[1] - a[1], b[0] - a[0]) or 1.0
            out = (out[0] / size, out[1] / size)
            far = abs(out[0]) * box["w"] / 2 + abs(out[1]) * box["h"] / 2 + LABEL_CLEAR
            box["x"], box["y"] = mid[0] + out[0] * far, mid[1] + out[1] * far
        boxes.append(box)
    separate(boxes)
    # Every label inside the picture, 4 px in, as Measure's are kept (its leader follows it): a still
    # has no edge to pan past.
    bounds = (frame.shape[1] / scale, height / scale)
    for box in boxes:
        box["x"] = min(max(box["x"], box["w"] / 2 + LABEL_MARGIN), max(box["w"] / 2 + LABEL_MARGIN, bounds[0] - box["w"] / 2 - LABEL_MARGIN))
        box["y"] = min(max(box["y"], box["h"] / 2 + LABEL_MARGIN), max(box["h"] / 2 + LABEL_MARGIN, bounds[1] - box["h"] / 2 - LABEL_MARGIN))
    for box in boxes:
        entry, made, said = box["entry"], box["made"], box["said"]
        broken = entry["status"] != "ok"
        color = STATUS_COLOR.get(entry["status"], ink) if broken else ink
        line = (lambda a, b, alpha: _dashed(painter, a, b, 1.0, color, alpha)) if broken else (lambda a, b, alpha: painter.line(a, b, 1.0, color, alpha))
        dimension = made["dimension"]
        if dimension:
            ends = [to_px(dimension["from"]), to_px(dimension["to"])]
            for (start, end) in dimension["extensions"]:
                line(to_px(start), to_px(end), LEADER_ALPHA * (BEHIND_ALPHA if hidden(start) else 1.0))
            line(ends[0], ends[1], LEADER_ALPHA)
            length = math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1])
            if length >= ARROW * 2.5:
                _arrow(painter, ends[0], ends[1], color, LEADER_ALPHA)
                _arrow(painter, ends[1], ends[0], color, LEADER_ALPHA)
            elif length > 1e-6:
                ux, uy = (ends[1][0] - ends[0][0]) / length, (ends[1][1] - ends[0][1]) / length
                before = (ends[0][0] - ux * ARROW * 2, ends[0][1] - uy * ARROW * 2)
                after = (ends[1][0] + ux * ARROW * 2, ends[1][1] + uy * ARROW * 2)
                line(before, ends[0], LEADER_ALPHA)
                line(ends[1], after, LEADER_ALPHA)
                _arrow(painter, ends[0], before, color, LEADER_ALPHA)
                _arrow(painter, ends[1], after, color, LEADER_ALPHA)
        elif made["anchor"] is not None:
            anchor = to_px(made["anchor"])
            end = _box_edge(anchor, box)
            behind = not made.get("broken") and hidden(made["anchor"])
            alpha = LEADER_ALPHA * (BEHIND_ALPHA if behind else 1.0)
            line(anchor, end, alpha)
            if made.get("broken"):
                painter.disc(anchor, ARROW_HALF + 1, color, ring=1.0, alpha=alpha)
            elif entry["kind"] == "datum":
                _datum_triangle(painter, anchor, end, color, alpha, hollow=behind)
            else:
                _arrow(painter, anchor, end, color, alpha, hollow=behind)
        _label(painter, said, box, ink, paper, color if broken else ink, broken)
