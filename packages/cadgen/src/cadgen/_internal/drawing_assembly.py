"""What an assembly drawing reads off an assembly: its parts list, and where on
each part a balloon's leader can land.

A parts list is the assembly's distinct parts, each once, with how many times it
occurs. Two occurrences are one part when they carry the same name and colour
and the same geometry: a shared prototype in the STEP or one shape object in a
live assembly, or an exact translated copy, which a boolean check confirms. A
name, a colour or a shape alone never merges two parts: a saved STEP shares one
prototype between any parts that happen to have identical geometry (a steel
spacer and a brass one), a label's detail often names a finish
(``piston_rod:chrome``), and mirror images have identical volumes. Identical
shapes under different names are kept apart and reported, so the author can
merge them with :meth:`PartsList.merge` when they are one part.

Nothing here is drawn; ``cadgen.eng_drawing`` draws the table and the balloons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

#: The fields an author may fill in on a parts-list row. Everything else on an
#: item is read off the model.
FIELDS = ("description", "part_number", "material")


@dataclass(slots=True, eq=False)
class Item:
    """One row of a parts list: a distinct part and how many the assembly holds.

    ``number`` is the item number its balloons carry. ``description`` defaults to
    the model's own name for the part made readable (``piston_rod:chrome`` reads
    ``PISTON ROD, CHROME``); ``part_number`` and ``material`` are blank unless the
    author states them, because the model does not. ``shape`` is one occurrence
    in the part's own frame, for its detail sheet; ``occurrences`` are all of
    them, placed in the assembly.
    """

    number: int
    description: str
    quantity: int
    part_number: str = ""
    material: str = ""
    labels: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    shape: Any = None
    occurrences: tuple = ()
    #: The STEP prototypes its occurrences share (empty for a live assembly).
    prototypes: tuple = ()


class PartsList:
    """An assembly's parts, numbered in the order the assembly first holds them.

    Iterate it for the items; index it by item number or by a part's name in the
    model (``parts[3]``, ``parts["coil_spring"]``). ``assembly`` is the whole
    assembly as one shape, placed, which is what the general arrangement's views
    draw. ``twins`` are pairs of item numbers whose parts have the same shape
    under different names or colours.
    """

    def __init__(self, assembly, items: Sequence[Item], twins: Sequence[tuple[int, int]] = ()) -> None:
        self.assembly = assembly
        self.items = tuple(items)
        self.twins = tuple(twins)
        #: Set once sheets are drawn from this list: its numbering is then theirs.
        self._frozen = False

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, key: int | str) -> Item:
        if isinstance(key, bool) or not isinstance(key, (int, str)):
            raise TypeError(f"a parts list is indexed by item number or part name, got {key!r}")
        if isinstance(key, int):
            if not 1 <= key <= len(self.items):
                raise KeyError(f"no item {key}: this parts list numbers 1 to {len(self.items)}")
            return self.items[key - 1]
        exact = [item for item in self.items if key in item.labels]
        named = exact or [item for item in self.items if key in {_base(label) for label in item.labels}]
        if len(named) == 1:
            return named[0]
        listing = ", ".join(f"{item.number} {item.labels[0] if item.labels else '(unnamed)'}" for item in self.items)
        if not named:
            raise KeyError(f"no part named {key!r} in this parts list; its items are {listing}")
        raise KeyError(f"{len(named)} items are named {key!r} (items "
                       f"{', '.join(str(item.number) for item in named)}); index them by number")

    def set(self, key: int | str, **fields: str) -> "PartsList":
        """State what the model cannot carry for one item: ``description``,
        ``part_number`` or ``material``. Returns the list, so calls chain."""
        unknown = sorted(set(fields) - set(FIELDS))
        if unknown:
            raise TypeError(f"parts.set() takes {', '.join(FIELDS)}; not {', '.join(unknown)}")
        item = self[key]
        for name, value in fields.items():
            if not isinstance(value, str):
                raise TypeError(f"parts.set({key!r}, {name}=...) takes a string, got {value!r}")
            setattr(item, name, value)
        return self

    def merge(self, *keys: int | str, description: str | None = None) -> "PartsList":
        """List several items as one part: the parts the model names differently
        (``mounting_eye:lower``, ``mounting_eye:upper``) that are one part. Their
        geometry must be the same: a shared prototype, or an exact translated
        copy. The first item keeps its place and takes the others' quantities;
        the items after it are numbered again. ``description`` replaces the one
        read from their labels (the segments they share)."""
        if self._frozen:
            raise ValueError("merge() renumbers the parts list, and sheets are already drawn from it; merge "
                             "before assembly_sheets() or balloons()")
        if len(keys) < 2:
            raise TypeError("merge() takes two or more items")
        chosen = []
        for key in keys:
            item = self[key]
            if any(item is other for other in chosen):
                raise ValueError(f"merge(): item {item.number} is named twice")
            chosen.append(item)
        first = min(chosen, key=lambda item: item.number)
        for other in chosen:
            if other is first:
                continue
            shared = set(first.prototypes) & set(other.prototypes)
            if not shared and not _same_part(first.shape, other.shape):
                raise ValueError(
                    f"merge(): item {other.number} ({other.description or 'unnamed'}) is not the same shape as item "
                    f"{first.number} ({first.description or 'unnamed'}); only identical parts are one part"
                )
        for other in chosen:
            if other is first:
                continue
            first.labels += other.labels
            first.refs += other.refs
            first.occurrences += other.occurrences
            first.prototypes += tuple(p for p in other.prototypes if p not in first.prototypes)
            first.quantity += other.quantity
        first.description = description if description is not None else _describe(first.labels)
        gone = {id(item) for item in chosen if item is not first}
        kept = [item for item in self.items if id(item) not in gone]
        old = {item.number: item for item in self.items}
        for number, item in enumerate(kept, start=1):
            item.number = number
        renumber = {n: item.number for n, item in old.items() if id(item) not in gone}
        self.items = tuple(kept)
        self.twins = tuple(sorted({tuple(sorted((renumber[a], renumber[b]))) for a, b in self.twins
                                   if a in renumber and b in renumber and renumber[a] != renumber[b]}))
        return self


def parts_list(source) -> PartsList:
    """The parts list of an assembly: a scene from ``cadgen.read_scene(path)``, or
    a live build123d assembly (a ``Compound`` built with ``children=``)."""
    from build123d import Compound, Location

    if hasattr(source, "leaves") and hasattr(source, "roots"):
        leaves = [(o.label or "", o.prototype_id, o.ref, o.shape()) for o in source.leaves()]
        roots = [root.shape() for root in source.roots]
        assembly = roots[0] if len(roots) == 1 else Compound(roots)
    elif getattr(source, "children", None):
        leaves = list(_walk(source, ()))
        assembly = source
    else:
        raise TypeError(
            "parts_list() reads an assembly: a scene from cadgen.read_scene(path), or a build123d Compound "
            "made with children=[...]. A single part has no parts list; draw it with Sheet.three_views()."
        )
    if not leaves:
        raise ValueError("parts_list(): the assembly holds no parts")
    groups: list[dict] = []
    for label, key, ref, world in leaves:
        local = world.located(Location())
        colour = _colour(world)
        group = None
        for g in groups:
            if g["label"] != label or g["colour"] != colour:
                continue
            if (key is not None and key in g["keys"]) or (key is None and g["local"].wrapped.IsPartner(local.wrapped)) \
                    or _same_part(g["local"], local):
                group = g
                break
        if group is None:
            groups.append({"label": label, "colour": colour, "keys": [key] if key is not None else [],
                           "local": local, "labels": [label], "refs": [ref], "placed": [world]})
        else:
            if key is not None and key not in group["keys"]:
                group["keys"].append(key)
            group["labels"].append(label)
            group["refs"].append(ref)
            group["placed"].append(world)
    twins = []
    for i, a in enumerate(groups):
        for j in range(i + 1, len(groups)):
            b = groups[j]
            if set(a["keys"]) & set(b["keys"]) or _same_part(a["local"], b["local"]):
                twins.append((i + 1, j + 1))
    return PartsList(assembly, [
        Item(number, _describe(g["labels"]), len(g["placed"]), labels=tuple(g["labels"]), refs=tuple(g["refs"]),
             shape=g["local"], occurrences=tuple(g["placed"]), prototypes=tuple(g["keys"]))
        for number, g in enumerate(groups, start=1)], twins)


def _colour(shape) -> tuple | None:
    """A shape's colour as a comparable tuple, or None when it has none."""
    colour = getattr(shape, "color", None)
    if colour is None:
        return None
    try:
        return tuple(round(float(c), 3) for c in tuple(colour))
    except TypeError:
        return (str(colour),)


def _walk(shape, path: tuple[str, ...]):
    """A live assembly's leaves, each placed where the assembly puts it."""
    for child in shape.children:
        label = child.label or ""
        if getattr(child, "children", None):
            yield from _walk(child, path + (label,))
        else:
            yield label, None, "/".join(path + (label,)), child.located(child.global_location)


def _base(label: str) -> str:
    """The part a label names, before any detail: ``mounting_eye:lower`` is a mounting eye."""
    return (label or "").split(":")[0].strip()


def _describe(labels: Sequence[str]) -> str:
    """A part's name as the parts list prints it: the label segments every
    occurrence shares, read out (``piston_rod:chrome`` -> ``PISTON ROD, CHROME``)."""
    split = [label.split(":") for label in labels if label]
    if not split:
        return ""
    common = []
    for segments in zip(*split):
        if any(s != segments[0] for s in segments):
            break
        common.append(segments[0])
    words = common or split[0]
    return ", ".join(w.replace("_", " ").strip().upper() for w in words if w.strip())


def _same_part(a, b) -> bool:
    """Whether ``b`` is an exact translated copy of ``a``: the same faces, volume
    and size, and nothing left over when one is moved onto the other."""
    from build123d import CenterOf, Location

    if not a.solids() or not b.solids() or len(a.faces()) != len(b.faces()):
        return False
    volume = a.volume
    if abs(volume - b.volume) > 1e-6 * max(volume, 1.0) or abs(a.area - b.area) > 1e-6 * max(a.area, 1.0):
        return False
    sa, sb = a.bounding_box().size, b.bounding_box().size
    if any(abs(x - y) > 1e-4 for x, y in zip(sa, sb)):
        return False
    try:
        moved = a.moved(Location(b.center(CenterOf.MASS) - a.center(CenterOf.MASS)))
        left = sum(s.volume for s in (moved - b).solids()) + sum(s.volume for s in (b - moved).solids())
    except Exception:  # noqa: BLE001 - a boolean the kernel cannot do proves nothing; list them apart
        return False
    return left <= 1e-6 * max(volume, 1.0)


#: How far apart a face's samples are, and how many one occurrence may cost.
_SAMPLE_PITCH = 4.0
_SAMPLES = 2500


def visible_point(occurrences, cast, look, *, faces: int = 40) -> tuple[float, float, float] | None:
    """A point on one of ``occurrences`` that the viewer looking along ``-look``
    sees: on a face turned toward them, with nothing of the assembly (``cast``,
    an intersector loaded with it) between. The most central such point of the
    first occurrence that shows one, so a leader lands well inside the part's
    outline rather than on its edge; None when every occurrence is hidden.
    """
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.BRepTools import BRepTools
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec

    toward = gp_Dir(*look)
    for placed in occurrences:
        found = []
        budget = _SAMPLES
        for face in sorted(placed.faces(), key=lambda f: -f.area)[:faces]:
            if budget <= 0 or len(found) >= 12:
                break
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
            inside = BRepTopAdaptor_FClass2d(face.wrapped, 1e-7)
            surface = BRepGProp_Face(face.wrapped)
            # Samples every few millimetres across the face, so a part showing only
            # a narrow band between two others still shows one.

            def at(u: float, v: float):
                point, normal = gp_Pnt(), gp_Vec()
                surface.Normal(u, v, point, normal)
                return point, normal

            um, vm = (u0 + u1) / 2, (v0 + v1) / 2
            counts = [max(3, min(21, int(at(a[0], a[1])[0].Distance(at(b[0], b[1])[0]) / _SAMPLE_PITCH) + 1))
                      for a, b in (((u0, vm), (u1, vm)), ((um, v0), (um, v1)))]
            grid = [(u0 + (u1 - u0) * (i + 0.5) / counts[0], v0 + (v1 - v0) * (j + 0.5) / counts[1])
                    for i in range(counts[0]) for j in range(counts[1])]
            # Middle first: a central point makes the better leader end.
            grid.sort(key=lambda uv: abs(uv[0] - um) / max(u1 - u0, 1e-9) + abs(uv[1] - vm) / max(v1 - v0, 1e-9))
            for u, v in grid:
                if budget <= 0 or len(found) >= 12:
                    break
                budget -= 1
                # The UV rectangle overhangs a trimmed face: a plate's centre
                # sample can sit in its bore.
                if inside.Perform(gp_Pnt2d(u, v)) != TopAbs_IN:
                    continue
                point, normal = at(u, v)
                if normal.Magnitude() < 1e-12:
                    continue
                normal.Normalize()
                if normal.X() * look[0] + normal.Y() * look[1] + normal.Z() * look[2] < 0.25:
                    continue
                start = gp_Pnt(point.X() + look[0] * 1e-3, point.Y() + look[1] * 1e-3, point.Z() + look[2] * 1e-3)
                cast.Perform(gp_Lin(start, toward), 0.0, 1e7)
                if cast.NbPnt() == 0:
                    found.append((point.X(), point.Y(), point.Z()))
        if found:
            mid = tuple(sum(p[k] for p in found) / len(found) for k in range(3))
            return min(found, key=lambda p: sum((p[k] - mid[k]) ** 2 for k in range(3)))
    return None


def spread(desired: Sequence[float], gap: float, lo: float, hi: float,
           avoid: Sequence[tuple[float, float]] = ()) -> list[float]:
    """Positions along one line, in the order of ``desired`` (sorted), each at
    least ``gap`` from the next and as near its desired place as that allows,
    within ``[lo, hi]`` when they fit there: a run of balloons that would touch
    is centred on the places it wanted rather than pushed all one way.

    No position falls inside an ``avoid`` interval while there is room outside
    them: each desired place goes to the nearest stretch of the line between
    them, and is spread within it."""
    free = [(lo, hi)]
    for a, b in sorted(avoid):
        free = [piece for x0, x1 in free for piece in ((x0, min(x1, a)), (max(x0, b), x1)) if piece[1] >= piece[0]]
    if not free or len(free) == 1:
        out = _spread(desired, gap, *(free[0] if free else (lo, hi)))
    else:
        out = []
        index = 0
        runs: list[list[float]] = [[] for _ in free]
        for y in desired:
            # The nearest stretch, never one before the last used: order is kept.
            index = min(range(index, len(free)), key=lambda k: max(free[k][0] - y, y - free[k][1], 0.0))
            runs[index].append(y)
        for (x0, x1), run in zip(free, runs):
            out.extend(_spread(run, gap, x0, x1))
    # Whatever the stretches could not hold moves on past the next one, so no two
    # end up closer than ``gap`` and none inside an avoided interval; a run that
    # still does not fit ends past ``hi``, which the caller refuses.
    placed: list[float] = []
    for y in out:
        if placed and y < placed[-1] + gap:
            y = placed[-1] + gap
        moved = True
        while moved:
            moved = False
            for a, b in avoid:
                if a < y < b:
                    y, moved = b, True
        placed.append(y)
    return placed


def _spread(desired: Sequence[float], gap: float, lo: float, hi: float) -> list[float]:
    def start(block) -> float:
        count, total = block
        return max(lo, min(total / count, hi - (count - 1) * gap))

    blocks: list[list] = []
    for y in desired:
        blocks.append([1, y])
        while len(blocks) > 1 and start(blocks[-2]) + blocks[-2][0] * gap > start(blocks[-1]) + 1e-9:
            count, total = blocks.pop()
            before = blocks[-1][0]
            # Each moved element's offset from its block's start grows by the rows above it.
            blocks[-1] = [before + count, blocks[-1][1] + total - count * before * gap]
    out: list[float] = []
    for block in blocks:
        first = start(block)
        out.extend(first + j * gap for j in range(block[0]))
    return out
