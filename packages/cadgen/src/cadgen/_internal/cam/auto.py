"""A job's operations written from the part's features, for a job that names none (no ``"setups"``).

One setup from the top (+Z, zero at the stock's top centre), in the order a machinist runs it:

* face the top, when the stock stands over it;
* each pocket floor, one operation per depth;
* each through hole no drill makes: an inside profile round its wall;
* each through opening that is not a hole (a slot, a window): an inside profile round its walls;
* each hole a drill makes, one operation per depth;
* the outline, cut 0.5 mm past the part's bottom to free it.

A tool fits a feature when it is no wider than 0.8 of the feature's tightest inside corner or narrowest width (0.6 of
a bore's diameter, so the profile has room). The job's own tools are used when it lists them; else cadgen proposes the
fewest standard sizes that fit, each operation getting the largest the feature takes, and lists them as assumed. A
feature nothing fits, or that the top cannot reach (an underside, a side hole), and the chamfers a flat end mill
cannot cut, are returned as warnings: the plan says what it left.

Each operation is named for what it cuts ("2 slots 5.5 x 15.5", "Drill 4 holes Ø3.4"), and the completed job is the
record the person edits and plans again. Stdlib at import; numpy inside.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cadgen._internal.cam.checks import finding
from cadgen._internal.cam.features import _rays_clear, axis_word, openings

__all__ = ["complete_job"]

#: The end mill sizes cadgen proposes (mm), largest first, and the largest drill.
MILLS_MM = (12.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.5, 1.0)
LARGEST_DRILL_MM = 13.0
#: How far past the part's bottom a through cut goes, into a sacrificial plate under the stock (mm).
THROUGH_MM = 0.5
#: A tool's share of the feature it cuts: of a corner's diameter or a width, and of a bore's diameter.
CORNER_SHARE = 0.8
BORE_SHARE = 0.6
#: A drill matches a hole within this (mm), and pecks one diameter at a time past this many diameters deep.
DRILL_MATCH_MM = 0.05
PECK_DEPTHS = 2.0
#: The flutes cadgen proposes: three diameters, or as long as the deepest cut asks, up to six (a long-reach cutter).
FLUTES_D, LONGEST_FLUTES_D = 3.0, 6.0


def _g(value: float) -> str:
    return f"{round(float(value), 2):g}"


@dataclass
class _Cut:
    """One operation before its tool is chosen: what it cuts, the widest tool that fits (``largest``) and how far
    below the stock's top it cuts (``depth``), which the tool's flutes must reach."""

    op: str
    order: int
    largest: float
    depth: float = 0.0
    faces: list[str] = field(default_factory=list)
    what: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    drill_mm: float | None = None
    #: Roomy cuts (the top, the outline, a bore) take a tool already chosen when it is near their largest.
    roomy: bool = False


def _extent(infos) -> tuple[float, float]:
    """The smaller and larger XY size of the faces' bounds."""
    lows = [info.bounds[0] for info in infos if info.bounds]
    highs = [info.bounds[1] for info in infos if info.bounds]
    if not lows:
        return 0.0, 0.0
    sizes = sorted(max(h[k] for h in highs) - min(lo[k] for lo in lows) for k in (0, 1))
    return sizes[0], sizes[1]


def _tightest(infos, width: float) -> float:
    """The widest tool the walls take: CORNER_SHARE of the tightest inside corner's diameter or of the width."""
    corners = [2 * info.radius_mm for info in infos if info.surface == "cylinder" and info.hole]
    return CORNER_SHARE * min([*corners, width] if width > 0 else corners or [0.0])


def _open_above(part, info) -> bool:
    """Whether the tool comes down onto the face from above: a straight way up from some of it, not under a roof."""
    import numpy as np

    mine = np.nonzero(np.asarray(part.face_of_triangle) == info.ordinal)[0]
    corners = np.asarray(part.vertices)[np.asarray(part.triangles)[mine[:: max(1, len(mine) // 8)]]]
    return any(_rays_clear(part, [point + [0.0, 0.0, 0.01]], (0.0, 0.0, 1.0)) for point in corners.mean(axis=1))


def _vertical(info) -> bool:
    return (info.normal is not None and abs(info.normal[2]) < 1e-3) or (
        info.axis is not None and axis_word(info.axis) in ("+Z", "-Z"))


def _cuts(part, reading, margin_z: float, drills: list[float] | None) -> tuple[list[_Cut], list[dict]]:
    """What the part needs cut from the top, and the warnings for what it cannot be. ``drills``: the job's drill
    diameters, or None when cadgen proposes the tools."""
    info_of = {info.ref: info for info in part.faces.values()}
    cuts: dict[tuple, _Cut] = {}
    left: list[str] = []

    def add(key, cut: _Cut, faces, what: str) -> None:
        """One feature into the operation ``key`` names: its faces, its words, and the tool it allows."""
        kept = cuts.setdefault(key, cut)
        kept.faces += [ref for ref in faces if ref not in kept.faces]
        kept.what.append(what)
        kept.largest = min(kept.largest, cut.largest)
        kept.depth = max(kept.depth, cut.depth)

    top = part.bbox[1][2] + margin_z
    through = top - part.bbox[0][2] + THROUGH_MM
    if margin_z > 0:
        cuts[("face",)] = _Cut("face", 0, MILLS_MM[0], margin_z, what=["the top"], roomy=True)
    in_hole: set[str] = set()
    # A hole's flat faces are its own: the pocket loop below clears only a blind hole's floor no drill makes.
    pocketed: set[str] = set()
    for hole in reading["holes"]:
        in_hole.update(hole["faces"])
        diameter, depth = hole["diameter_mm"], hole["depth_mm"]
        if hole.get("axis_word") not in ("+Z", "-Z") or "+Z" not in hole["reach"]:
            left.append(f"a Ø{_g(diameter)} hole the top does not reach ({hole['reading']})")
            continue
        drill = _drill_for(diameter, drills)
        walls = [ref for ref in hole["faces"] if info_of[ref].surface == "cylinder"
                 and abs(2 * info_of[ref].radius_mm - diameter) < 1e-3]
        counterbore = hole.get("counterbore")
        if counterbore:
            # Round its wall, down to its shoulder: the path sweeps the ring round the hole, which the hole takes.
            size = counterbore["diameter_mm"]
            cb_walls = [ref for ref in hole["faces"] if info_of[ref].surface == "cylinder"
                        and abs(2 * info_of[ref].radius_mm - size) < 1e-3]
            add(("counterbore", round(counterbore["depth_mm"], 3)),
                _Cut("profile", 2, BORE_SHARE * size, top - (hole["center_mm"][2] - counterbore["depth_mm"]),
                     params={"side": "inside"}, roomy=True), cb_walls,
                f"counterbore Ø{_g(size)} x {_g(counterbore['depth_mm'])} deep")
        if drill is not None:
            # Holes that end at one height drill as one operation, whatever height each opens at.
            end = min(hole["center_mm"][2], hole["bottom_mm"][2])
            key = ("drill", drill, round(end, 3), hole["through"])
            # As deep as it is drilled: from the stock's top, through the stock over the part.
            peck = drill if top - end > PECK_DEPTHS * drill else None
            params = {"through_mm": THROUGH_MM if hole["through"] else 0.0, **({"peck_mm": peck} if peck else {})}
            cut = _Cut("drill", 4, drill, drill_mm=drill, params=params)
            add(key, cut, walls[:1], f"Ø{_g(diameter)}" + ("" if hole["through"] else f" x {_g(depth)} deep"))
        elif hole["through"]:
            add(("bore",), _Cut("profile", 2, BORE_SHARE * diameter, through, params={"side": "inside",
                                                                            "through_mm": THROUGH_MM}, roomy=True),
                walls, f"bore Ø{_g(diameter)}")
        else:
            # A blind hole no drill makes is cleared as the pocket its floor is.
            planes = [ref for ref in hole["faces"] if info_of[ref].surface == "plane"]
            if planes:
                pocketed.add(min(planes, key=lambda ref: info_of[ref].center_mm[2]))
    for floor in reading["floors"]:
        pocket = floor.get("pocket")
        if floor["kind"] == "underside":
            left.append(f"the underside at Z {_g(floor['z_mm'])}, which faces down: it needs a setup from below")
        if floor["kind"] != "floor" or not pocket or (floor["ref"] in in_hole and floor["ref"] not in pocketed):
            continue
        if not _open_above(part, info_of[floor["ref"]]):
            left.append(f"the floor at Z {_g(floor['z_mm'])}, under the part: it needs a setup from another side")
            continue
        walls = [info_of[ref] for ref in pocket["walls"]]
        narrow, _ = _extent([info_of[floor["ref"]], *walls])
        largest = _tightest(walls, narrow)
        key = ("pocket", round(floor["z_mm"], 3))
        add(key, _Cut("pocket", 1, largest, top - floor["z_mm"]), [floor["ref"]],
            f"pocket {_g(pocket['depth_mm'])} mm deep")
    for floor in reading["floors"]:
        if floor["kind"] != "bottom":
            continue
        for loop in openings(part, part.face(floor["ref"]).ordinal):
            refs = [part.faces[k].ref for k in loop]
            if all(ref in in_hole for ref in refs):
                continue
            walls = [part.faces[k] for k in loop if _vertical(part.faces[k])]
            narrow, long = _extent(walls)
            largest = _tightest(walls, narrow)
            corners = {round(2 * info.radius_mm, 3) for info in walls if info.surface == "cylinder" and info.hole}
            word = "slot" if len(corners) == 1 and next(iter(corners)) - narrow < 1e-3 else "opening"
            add(("opening",), _Cut("profile", 3, largest, through, params={"side": "inside",
                                                                           "through_mm": THROUGH_MM}),
                [info.ref for info in walls], f"{word} {_g(narrow)} x {_g(long)}")
    # Round the outside and over the top nothing narrows the cut: the largest cutter, or one near it.
    cuts[("outline",)] = _Cut("profile", 9, MILLS_MM[0], through, params={"side": "outside", "through_mm": THROUGH_MM},
                              what=["the outline"], roomy=True)
    chamfers = sum(1 for info in part.faces.values() if info.surface == "cone" and info.ref not in in_hole
                   or info.surface == "plane" and info.normal is not None and axis_word(info.normal) is None)
    warnings = []
    if chamfers:
        warnings.append(finding("auto", "warning", "not_planned",
                                f"{chamfers} chamfer face{'s' if chamfers > 1 else ''} not cut: flat end mills leave "
                                "those edges square",
                                "break the edges by hand, or add a chamfer operation of the shop's own"))
    warnings += [finding("auto", "warning", "not_planned", f"not cut: {what}",
                         "machine it in a second setup, or by hand, and say so in the job's write-up")
                 for what in left]
    return list(cuts.values()), warnings


def _drill_for(diameter: float, drills: list[float] | None) -> float | None:
    """The drill that makes a hole: one of the job's, or (proposing) the hole's size to 0.1 mm up to the largest."""
    if drills is not None:
        return next((d for d in drills if abs(d - diameter) <= DRILL_MATCH_MM), None)
    size = round(diameter, 1)
    return size if abs(size - diameter) <= DRILL_MATCH_MM and size <= LARGEST_DRILL_MM else None


def _choose(cuts: list[_Cut], mills: dict[float, float] | None) -> tuple[dict[int, float], list[float], list[_Cut]]:
    """Each milling cut's tool diameter (by position), the mill sizes used, and the cuts nothing fits. ``mills``: the
    job's flat end mills, diameter to flute length, or None to propose standard sizes (flutes up to
    LONGEST_FLUTES_D diameters). The cuts the part's shape limits choose first, largest first; a cut takes a size
    already chosen when it is at least half the largest it fits, else the largest that fits, so a few tools cut
    everything and none is far smaller than its cut allows."""
    chosen: list[float] = []
    out: dict[int, float] = {}
    unfit: list[_Cut] = []
    sizes = sorted(mills, reverse=True) if mills is not None else list(MILLS_MM)

    def reaches(d: float, cut: _Cut) -> bool:
        flutes = mills[d] if mills is not None else LONGEST_FLUTES_D * d
        return d <= cut.largest + 1e-9 and flutes >= cut.depth - 1e-9

    order = sorted((k for k, cut in enumerate(cuts) if cut.op != "drill"),
                   key=lambda k: (cuts[k].roomy, -cuts[k].largest))
    for k in order:
        cut = cuts[k]
        fits = [d for d in chosen if d >= cut.largest / 2 and reaches(d, cut)]
        if fits:
            out[k] = max(fits)
            continue
        size = next((d for d in sizes if reaches(d, cut)), None)
        if size is None:
            unfit.append(cut)
            continue
        out[k] = size
        chosen.append(size)
    return out, sorted(set(out.values()), reverse=True), unfit


def _name(cut: _Cut) -> str:
    """``Face the top``, ``Drill 4 holes Ø3.4``, ``Bore Ø22.2``, ``2 slots 5.5 x 15.5 and counterbore Ø6 x 3 deep``:
    each kind of feature counted, its sizes after."""
    if cut.op == "face":
        return "Face the top"
    if cut.params.get("side") == "outside":
        return "Cut the outline free"
    if cut.op == "drill":
        n = len(cut.what)
        return f"Drill {n} hole{'s' if n > 1 else ''} " + _joined(cut.what)
    kinds: dict[str, list[str]] = {}
    for what in cut.what:
        kind, size = what.split(" ", 1)
        kinds.setdefault(kind, []).append(size)
    words = " and ".join(f"{len(sizes)} {kind}s {_joined(sizes)}" if len(sizes) > 1 else f"{kind} {sizes[0]}"
                         for kind, sizes in kinds.items())
    return words[0].upper() + words[1:]


def _joined(words: list[str]) -> str:
    unique = list(dict.fromkeys(words))
    return unique[0] if len(unique) == 1 else ", ".join(unique[:-1]) + " and " + unique[-1]


def complete_job(raw: dict, parsed, part, reading) -> tuple[dict, list[dict]]:
    """The job with its operations (and, when it lists none, its tools) written from the part's features, and the
    warnings for what it leaves. ``parsed`` is the job read without setups (its machine, material, stock, tools)."""
    tools = list(parsed.tools.values())
    given = bool(tools)
    drills = sorted(t.diameter_mm for t in tools if t.type == "drill") if given else None
    mills = {}
    for tool in sorted(tools, key=lambda t: -t.flute_length_mm):
        if tool.type in ("flat", "bull"):
            mills.setdefault(tool.diameter_mm, tool.flute_length_mm)
    cuts, warnings = _cuts(part, reading, parsed.stock.margin_mm[2], drills)
    sizes, used, unfit = _choose(cuts, mills if given else None)
    for cut in unfit:
        warnings.append(finding("auto", "warning", "not_planned", f"not cut: {_joined(cut.what)}, which needs a flat "
                                f"end mill of {_g(cut.largest)} mm or less with {_g(cut.depth)} mm of flutes",
                                "add one to the job's tools and plan again"
                                if given else "cut it by hand, or with a smaller tool of the shop's own"))
    if given:
        id_of = {}
        for tool in tools:
            if tool.type in ("flat", "bull"):
                id_of.setdefault(("mill", tool.diameter_mm), tool.id)
            elif tool.type == "drill":
                id_of.setdefault(("drill", tool.diameter_mm), tool.id)
        new_tools = None
    else:
        drill_sizes = sorted({cut.drill_mm for cut in cuts if cut.op == "drill"})
        new_tools, id_of = [], {}
        for d in used:
            id_of[("mill", d)] = f"T{len(new_tools) + 1}"
            deepest = max(cuts[k].depth for k, size in sizes.items() if size == d)
            entry = {"id": id_of[("mill", d)], "type": "flat", "diameter_mm": d,
                     "name": f"{_g(d)} mm flat end mill, proposed"}
            if deepest > FLUTES_D * d:
                entry["flute_length_mm"] = float(-(-deepest // 1))     # a long-reach cutter, whole mm
            new_tools.append(entry)
        for d in drill_sizes:
            id_of[("drill", d)] = f"T{len(new_tools) + 1}"
            new_tools.append({"id": id_of[("drill", d)], "type": "drill", "diameter_mm": d,
                              "name": f"{_g(d)} mm drill, proposed"})
    planned = []
    for k, cut in enumerate(cuts):
        if cut.op == "drill":
            tool = id_of[("drill", cut.drill_mm)]
            size = cut.drill_mm
        elif k in sizes:
            tool, size = id_of[("mill", sizes[k])], sizes[k]
        else:
            continue
        entry = {"op": cut.op, "tool": tool, "name": _name(cut)}
        if cut.faces:
            entry["faces"] = cut.faces
        entry.update(cut.params)
        planned.append((cut.order, size, k, entry))
    # Face first and the outline last; between them the milling grouped by tool, largest first, then the drilling.
    planned.sort(key=lambda p: (p[0] != 0, p[0] == 9, p[0] == 4, -p[1], p[0], p[2]))
    operations = [p[3] for p in planned]
    job = dict(raw)
    if new_tools is not None:
        job["tools"] = new_tools
    job["setups"] = [{"id": "top", "orientation": "+Z", "origin": "stock-top-center", "operations": operations}]
    return job, warnings
