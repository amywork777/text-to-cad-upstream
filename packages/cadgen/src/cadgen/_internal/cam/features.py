"""The machining reading of a part: what ``cadgen cam features`` lists and what operations look up.

:func:`read_features` returns ``{"faces", "holes", "floors", "profiles"}`` (lists of dicts, the shapes
:class:`~cadgen.results.CamFeaturesResult` documents):

* every face, with a plain ``reading`` ("flat floor at Z 12, facing +Z", "hole wall Ø5 along Z");
* holes: the hole-wall cylinders grouped by axis line and radius, then split where material stands between them
  along the axis (a split cylinder is one hole; two blind holes either side of a web are two), with their diameter,
  depth, axis (pointing out of the opening), opening centre and whether they go through; whether an end is open is
  asked of the exact solid (OCCT's classifier), off the axis so a drill point's cone reads as a bottom;
* floors: the flat faces square to an axis, with ``kind`` top, floor, bottom or underside, and for a +Z floor below
  the top its pocket: the walls around it, their depth and the islands inside it;
* a DXF's profiles: outline size, area and holes (a round hole with its diameter).

:func:`holes` is the grouping alone, for the drilling operations. Stdlib at import; numpy and OCP inside.
"""

from __future__ import annotations

import math

__all__ = ["axis_word", "holes", "read_features"]

_AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
_COS5 = math.cos(math.radians(5.0))


def _g(value: float, digits: int = 3) -> str:
    return f"{round(float(value), digits):g}"


def axis_word(vector) -> str | None:
    """``+Z``, ``-X``, ... when ``vector`` is within 5° of an axis, else ``None``."""
    for name, axis in _AXES.items():
        dot = sum(a * b for a, b in zip(vector, axis))
        if dot > _COS5:
            return f"+{name}"
        if dot < -_COS5:
            return f"-{name}"
    return None


def _vec(vector) -> str:
    return "(" + ", ".join(f"{v:.2f}" for v in vector) + ")"


def holes(part) -> list[dict]:
    """The part's holes: hole-wall cylinders grouped by axis line and radius, split at webs (:func:`_clusters`)."""
    import numpy as np

    groups: list[dict] = []
    for info in part.faces.values():
        if info.surface != "cylinder" or not info.hole:
            continue
        d = np.asarray(info.axis, dtype=float)
        p = np.asarray(info.axis_point, dtype=float)
        for group in groups:
            gd, gp = group["d"], group["p"]
            if (abs(abs(float(gd @ d)) - 1.0) < 1e-6 and abs(group["r"] - info.radius_mm) < 1e-4
                    and np.linalg.norm(np.cross(p - gp, gd)) < 1e-4):
                group["faces"].append(info)
                break
        else:
            groups.append({"d": d / np.linalg.norm(d), "p": p, "r": float(info.radius_mm), "faces": [info]})
    out = []
    triangles = np.asarray(part.triangles)
    owners = np.asarray(part.face_of_triangle)
    vertices = np.asarray(part.vertices)
    touch = max(1e-3, 2.0 * float(getattr(part, "deflection_mm", 0.01)))
    for group in groups:
        d, p, r = group["d"], group["p"], group["r"]
        side = np.cross(d, [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0])
        side = side / np.linalg.norm(side)
        for faces, t_low, t_high in _clusters(part, group["faces"], d, p, r, side, triangles, owners, vertices, touch):
            out.append(_hole(part, faces, d, p, r, side, t_low, t_high))
    out.sort(key=lambda hole: int(hole["faces"][0].rsplit("f", 1)[1]))
    return out


def _clusters(part, faces, d, p, r, side, triangles, owners, vertices, touch):
    """One axis-and-radius group split into holes, ``[(faces, t_low, t_high)]`` along the axis: faces whose spans
    touch are one hole (a split cylinder), and so are spans with air between them (a slot or a cavity the hole
    crosses); material between two spans (a web) makes two holes, so blind holes from both sides of a wall are
    never read as one through hole. The gap is judged at its middle, on the axis and at 0.7 r round it."""
    import numpy as np

    spans = []
    for info in faces:
        used = np.unique(triangles[owners == info.ordinal])
        t = (vertices[used] - p) @ d
        spans.append((float(t.min()), float(t.max()), info))
    spans.sort(key=lambda span: span[0])
    across = np.cross(d, side)
    clusters: list[list] = []
    for low, high, info in spans:
        if clusters and low > clusters[-1][2] + touch:
            centre = p + d * (0.5 * (clusters[-1][2] + low))
            probes = [centre] + [centre + sign * 0.7 * r * axis for axis in (side, across) for sign in (1.0, -1.0)]
            if bool(np.any(part.classify(np.asarray(probes)))):
                clusters.append([[info], low, high])
                continue
        if clusters:
            clusters[-1][0].append(info)
            clusters[-1][2] = max(clusters[-1][2], high)
        else:
            clusters.append([[info], low, high])
    return [(cluster[0], cluster[1], cluster[2]) for cluster in clusters]


def _hole(part, faces, d, p, r, side, t_low, t_high) -> dict:
    """One hole's entry: whether each end is open asked of the exact solid, its axis pointing out of the opening."""
    import numpy as np

    # Off the axis at 0.7 r and 0.3 r beyond each end: a drill point's cone is air on the axis but material there.
    offset = side * 0.7 * r
    reach = max(0.05, 0.3 * r)
    probes = np.array([p + d * (t_high + reach) + offset, p + d * (t_low - reach) + offset])
    closed_high, closed_low = (bool(v) for v in part.classify(probes))
    through = not closed_high and not closed_low
    if through:
        # Point the axis the way a tool comes in: toward +Z, else +X, else +Y.
        reference = np.asarray(_AXES["Z"])
        for axis in (_AXES["Z"], _AXES["X"], _AXES["Y"]):
            if abs(float(np.asarray(axis) @ d)) > 1e-6:
                reference = np.asarray(axis)
                break
        direction = d if float(reference @ d) > 0 else -d
    else:
        direction = d if closed_low else -d
    opening_t = t_high if float(direction @ d) > 0 else t_low
    bottom_t = t_low if float(direction @ d) > 0 else t_high
    opening = p + d * opening_t
    bottom = p + d * bottom_t
    depth = t_high - t_low
    word = axis_word(direction) or _vec(direction)
    refs = sorted((info.ref for info in faces), key=lambda ref: int(ref.rsplit("f", 1)[1]))
    return {
        "faces": refs, "diameter_mm": round(2 * r, 4), "depth_mm": round(depth, 4),
        "axis": [round(float(v), 6) + 0.0 for v in direction], "axis_word": word,
        "center_mm": [round(float(v), 4) + 0.0 for v in opening],
        "bottom_mm": [round(float(v), 4) + 0.0 for v in bottom], "through": through,
        "reading": f"Ø{_g(2 * r)} x {_g(depth)} {'through' if through else 'deep, blind'} along {word} "
                   f"at {_vec(opening).replace('.00', '')}",
    }


def _pocket(part, ordinal: int, z: float) -> dict | None:
    """The walls around a +Z floor below the top, their height, and the islands inside it."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    shape = part.shape.wrapped
    ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
    floor = part.ocp_face(ordinal)
    walls: set[int] = set()
    explorer = TopExp_Explorer(floor, TopAbs_EDGE)
    while explorer.More():
        faces = ancestors.FindFromKey(explorer.Current())
        for neighbour in faces:
            index = part._face_map.FindIndex(neighbour)
            if index and index != ordinal:
                info = part.faces[index]
                vertical = (info.normal is not None and abs(info.normal[2]) < 0.1) or (
                    info.axis is not None and axis_word(info.axis) in ("+Z", "-Z"))
                if vertical and info.bounds and info.bounds[1][2] > z + 1e-6:
                    walls.add(index)
        explorer.Next()
    if not walls:
        return None
    # An inner wire is an island when the faces along it rise above the floor; a deeper step's walls go down.
    from OCP.BRepTools import BRepTools

    outer = BRepTools.OuterWire_s(floor)
    islands = 0
    wires = TopExp_Explorer(floor, TopAbs_WIRE)
    while wires.More():
        wire = wires.Current()
        if not wire.IsSame(outer):
            edges = TopExp_Explorer(wire, TopAbs_EDGE)
            rises = False
            while edges.More() and not rises:
                for neighbour in ancestors.FindFromKey(edges.Current()):
                    index = part._face_map.FindIndex(neighbour)
                    bounds = part.faces[index].bounds if index and index != ordinal else None
                    rises = rises or bool(bounds and bounds[1][2] > z + 1e-6)
                edges.Next()
            islands += rises
        wires.Next()
    top = max(part.faces[w].bounds[1][2] for w in walls)
    return {"walls": [part.faces[w].ref for w in sorted(walls)], "depth_mm": round(top - z, 4),
            "islands": islands}


def read_features(part) -> dict:
    import numpy as np

    if part.kind == "dxf":
        return {"faces": [], "holes": [], "floors": [], "profiles": _profiles(part)}
    low, high = (np.asarray(v) for v in part.bbox)
    faces, floors = [], []
    for ordinal, info in sorted(part.faces.items()):
        entry = {"ref": info.ref, "surface": info.surface, "area_mm2": round(info.area_mm2, 3),
                 "center_mm": [round(v, 4) + 0.0 for v in info.center_mm]}
        if info.surface == "plane":
            entry["normal"] = list(info.normal)
            word = axis_word(info.normal)
            if word:
                index = "XYZ".index(word[1])
                at = info.center_mm[index]
                entry[f"{word[1].lower()}_mm"] = round(at, 4) + 0.0
                if word[1] == "Z":
                    if word[0] == "+":
                        kind = "top" if abs(at - high[2]) < 1e-3 else "floor"
                    else:
                        kind = "bottom" if abs(at - low[2]) < 1e-3 else "underside"
                    floor = {"ref": info.ref, "z_mm": round(at, 4) + 0.0, "normal": word, "kind": kind,
                             "area_mm2": round(info.area_mm2, 3)}
                    reading = f"flat {kind} at Z {_g(at)}, facing {word}"
                    if kind == "floor":
                        pocket = _pocket(part, ordinal, at)
                        if pocket:
                            floor["pocket"] = pocket
                            islands = pocket["islands"]
                            reading += (f" (a pocket floor {_g(pocket['depth_mm'])} mm down"
                                        + (f", {islands} island{'s' if islands > 1 else ''}" if islands else "") + ")")
                    floors.append(floor)
                else:
                    reading = f"flat wall at {word[1]} {_g(at)}, facing {word}"
            else:
                reading = f"flat, tilted, facing {_vec(info.normal)}"
        elif info.surface == "cylinder":
            word = axis_word(info.axis) or _vec(info.axis)
            entry.update({"axis": list(info.axis), "diameter_mm": round(2 * info.radius_mm, 4), "hole": info.hole})
            reading = (f"hole wall Ø{_g(2 * info.radius_mm)} along {word.lstrip('+-')}" if info.hole
                       else f"round wall Ø{_g(2 * info.radius_mm)} along {word.lstrip('+-')} (outside)")
        elif info.surface == "cone":
            word = axis_word(info.axis) or _vec(info.axis)
            entry["axis"] = list(info.axis)
            reading = f"cone along {word.lstrip('+-')} (a chamfer, countersink or drill point)"
        else:
            reading = f"curved ({info.surface})"
        entry["reading"] = f"{reading}, {_g(info.area_mm2, 1)} mm²"
        faces.append(entry)
    return {"faces": faces, "holes": holes(part), "floors": floors, "profiles": []}


def _profiles(part) -> list[dict]:
    import numpy as np

    out = []
    for index, polygon in enumerate(part.profiles):
        x0, y0, x1, y1 = polygon.bounds
        hole_list = []
        for ring in polygon.interiors:
            coords = np.asarray(ring.coords)[:-1]
            centre = coords.mean(axis=0)
            radii = np.linalg.norm(coords - centre, axis=1)
            round_ = len(coords) >= 8 and float(radii.max() - radii.min()) <= max(0.02, 0.01 * radii.mean())
            hole_list.append({"center_mm": [round(float(v), 4) for v in centre],
                              "diameter_mm": round(2 * float(radii.mean()), 4) if round_ else None})
        sizes = [h["diameter_mm"] for h in hole_list if h["diameter_mm"]]
        reading = f"outline {_g(x1 - x0)} x {_g(y1 - y0)} mm, {_g(polygon.area, 1)} mm²"
        if hole_list:
            reading += f", {len(hole_list)} hole{'s' if len(hole_list) > 1 else ''}"
            if sizes:
                reading += " (" + ", ".join(f"Ø{_g(s)}" for s in sorted(set(sizes))) + ")"
        out.append({"index": index, "area_mm2": round(polygon.area, 3),
                    "bounds_mm": [round(v, 4) for v in (x0, y0, x1, y1)], "holes": hole_list, "reading": reading})
    return out
