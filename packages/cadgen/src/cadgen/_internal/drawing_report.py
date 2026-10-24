"""What a drawing leaves unstated, read off the part and checked against what its
sheets state, and the general notes a part's own geometry makes true.

Part of :mod:`cadgen.eng_drawing`; nothing here imports the kernel or ezdxf at
module scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cadgen._internal.drawing_annotation import hole_callout_text, _hole_spec, _looks_into, _slot_spec
from cadgen._internal.drawing_base import _fmt, _shown, _where
from cadgen._internal.drawing_features import Slot


@dataclass
class _Facts:
    """What a drawing's sheets state, gathered as they render, for the report of
    what they leave unstated: a record per part drawn (keyed by its shape), one
    per parts list (keyed by the list), and one per sheet, for its stage."""

    parts: dict = field(default_factory=dict)
    lists: dict = field(default_factory=dict)
    sheets: list = field(default_factory=list)

    def of_list(self, parts) -> dict:
        """The record of one parts list: the items its tables list and its balloons key."""
        return self.lists.setdefault(id(parts), {"parts": parts, "listed": set(), "ballooned": set()})


def _merge_facts(into: _Facts, more: _Facts) -> None:
    """Fold one sheet's facts into the drawing's: a part shown on two sheets is
    stated by both."""
    into.sheets.extend(more.sheets)
    for mine, theirs in ((into.parts, more.parts), (into.lists, more.lists)):
        for key, record in theirs.items():
            if key not in mine:
                mine[key] = record
                continue
            for name, value in record.items():
                if isinstance(value, set):
                    mine[key][name] |= value
                elif isinstance(value, list):
                    mine[key][name].extend(value)


def _member_key(feature) -> tuple:
    """One hole or slot, by what it is and where it opens."""
    return (feature.signature(), tuple(round(c, 4) for c in feature.mouth))


def _feature_key(feature) -> tuple:
    """Holes or slots one callout covers: the same kind, opening the same way. A
    plain through hole or slot reads the same from either end; a blind or
    opened-out one made from the other face is a different callout, in the other
    view."""
    from cadgen._internal.drawing_features import _canonical

    plain = feature.thru and not any(getattr(feature, name, None)
                                     for name in ("cbore", "csk", "far_cbore", "far_csk"))
    direction = _canonical(feature.axis, (0.0, 0.0, 0.0))[0] if plain else feature.axis
    return (feature.signature(), tuple(round(c, 4) for c in direction))


def _whose(record: dict, records: list) -> str:
    """On a drawing of several parts, the sheet a report line is about."""
    return f"sheet {record['sheet'][0]} ({record['sheet'][1]}): " if len(records) > 1 else ""


def _unstated(facts: _Facts) -> list[str]:
    """What the drawing leaves out that a shop needs to make the part.

    Read off the part, not guessed at: every kind of hole it has, its overall
    size along each axis, and every turned diameter, each checked against what
    the sheets call out or measure. A drawing is allowed to be unfinished; it
    is not allowed to look finished when it is not, so each line names the call
    that states the missing fact.
    """
    from cadgen._internal.drawing_features import (
        holes as find_holes, revolved, slots as find_slots, turned_diameters,
    )

    lines: list[str] = []
    records = list(facts.parts.values())
    for record in records:
        shape, views = record["shape"], record["views"]
        # On a drawing of several parts, each line says whose sheet it is about.
        whose = _whose(record, records)
        kinds: dict[tuple, list] = {}
        # An assembly's holes and diameters are its parts', stated on their sheets.
        features = [] if record.get("assembly") else [*find_holes(shape), *find_slots(shape)]
        for feature in features:
            kinds.setdefault(_feature_key(feature), []).append(feature)
        for key, members in kinds.items():
            # Each one, not each kind: a detail's callout covers what its circle
            # holds, and the identical holes outside it are still unstated.
            members = [m for m in members if _member_key(m) not in record["called"]]
            if not members:
                continue
            feature = members[0]
            is_slot = isinstance(feature, Slot)
            text = _shown(hole_callout_text(_slot_spec(feature, len(members)) if is_slot
                                            else _hole_spec(feature, len(members))))
            where = next((name for name, look in views if _looks_into(feature, look)), None)
            verb = "slot" if is_slot else "hole"
            fix = (f"{where}.{verb}({_where(feature.mouth)}) states it, or {where}.holes() calls out every hole "
                   f"and slot the {where} view looks down." if where else
                   f"No view on the drawing looks into it; add the view that looks down the {verb}.")
            lines.append(f"incomplete: {whose}{text} is not called out. {fix}")
        size = shape.bounding_box().size
        turned = [] if record.get("assembly") else turned_diameters(shape)
        whole = None if record.get("assembly") else revolved(shape)
        # A stated diameter of the part's largest turned surface states its width
        # across that axis too: a shaft's ⌀30 is its size in Y and in Z, and a
        # cone's widest circle is a spring seat's.
        across = [d for d in [*turned, *([whole.diameter] if whole else [])]
                  if any(abs(v - d) <= 0.01 for v in record["values"])]
        for axis, extent in enumerate((size.X, size.Y, size.Z)):
            if any(a == axis and abs(v - extent) <= 0.01 for a, v in record["axes"]):
                continue
            if any(abs(d - extent) <= 0.01 for d in across):
                continue
            where = next((name for name, look in views if abs(look[axis]) < 1e-9), None)
            fix = f"{where}.overall() states it." if where else "No view on the drawing shows that direction."
            lines.append(f"incomplete: {whose}the overall size along {'XYZ'[axis]} ({_fmt(extent)}) is not "
                         f"dimensioned. {fix}")
        for diameter in turned:
            if any(abs(v - diameter) <= 0.01 for v in record["values"]):
                continue
            lines.append(
                f"incomplete: {whose}the turned diameter ⌀{_fmt(diameter)} is not dimensioned. Dimension it across "
                f"its profile with text=\"%%c<>\", or diameter(..., size={_fmt(diameter)}) where it is seen as a "
                "circle."
            )
    for record in records:
        if record.get("assembly"):
            continue
        whose = _whose(record, records)
        lines.extend(_unstated_edges(record, whose))
    for entry in facts.lists.values():
        parts, listed, keyed = entry["parts"], entry["listed"], entry["ballooned"]
        if not listed:
            lines.append("incomplete: balloons key a parts list that no sheet draws; sheet.parts_list(parts) draws "
                         "it above the title block.")
            continue
        missing = [n for n in range(1, len(parts) + 1) if n not in listed]
        if missing:
            lines.append(f"incomplete: the parts list leaves out item{'s' if len(missing) > 1 else ''} "
                         f"{', '.join(map(str, missing))}; draw the rest with parts_list(parts, first=...) on a "
                         "further sheet.")
        for a, b in parts.twins:
            lines.append(f"note: items {a} and {b} ({parts[a].description or 'unnamed'} and "
                         f"{parts[b].description or 'unnamed'}) are the same shape under different names; "
                         f"parts.merge({a}, {b}) lists them as one part, if they are one.")
        for item in parts:
            if item.number in listed and item.number not in keyed:
                lines.append(
                    f"incomplete: item {item.number} ({item.description or 'unnamed'}) has no balloon: no ballooned "
                    "view shows any of it unhidden. balloons() on a view from a side where it shows keys it."
                )
    for record in facts.sheets:
        lines.extend(_unstated_for_stage(record, _whose(record, facts.sheets)))
    return lines


def _unstated_for_stage(record: dict, whose: str) -> list[str]:
    """What a part's sheet leaves out that its stage asks it to define. A concept
    is a drawing to talk over and asks nothing; a prototype states a general
    tolerance and the material; production leaves nothing undefined."""
    stage = record["stage"]
    if stage not in ("prototype", "production") or not record["part"]:
        return []
    lines = []
    if stage == "prototype":
        if not record["general"]:
            lines.append(f"incomplete: {whose}a prototype drawing states a general tolerance for what it does not "
                         "tolerance one by one; Sheet(general_tolerance=...) or general_profile= states it.")
        if not record["material"]:
            lines.append(f"incomplete: {whose}a prototype drawing states the material; Sheet(material=...).")
        return lines
    if not record["datums"]:
        lines.append(f"incomplete: {whose}a production drawing locates its features from datums, and no datum is "
                     "marked; view.datum(\"A\", point) on the face the part locates on defines one.")
    if not record["general"]:
        lines.append(f"incomplete: {whose}a production drawing leaves no surface undefined, and no general profile "
                     "or general tolerance covers what it does not dimension one by one; "
                     "Sheet(general_profile=Frame(\"surface_profile\", ...)) or general_tolerance= covers it.")
    if not (record["material"] and record["spec"]):
        lines.append(f"incomplete: {whose}a production drawing states the material and its spec; "
                     "Sheet(material=..., spec=...).")
    if not record["finish"]:
        lines.append(f"incomplete: {whose}a production drawing states the finish, or that there is none; "
                     "Sheet(finish=...).")
    if not record["keyed"]:
        lines.append(f"note: {whose}a production drawing marks its key characteristics, and no feature is marked "
                     f"{record['mark']}; key=True on the dimension or callout of a feature whose variation affects "
                     "fit, function or safety marks it, if any is one.")
    return lines


def geometry_notes(part) -> list[str]:
    """The general notes the part's own geometry makes true, for
    ``Sheet(notes=...)``. A note that governs unspecified edges -- ``FILLETS R3
    UNLESS OTHERWISE SPECIFIED.`` -- asks the shop to treat every such edge drawn
    without a callout that way, so it is written only when the part leaves no
    edge of its kind sharp: every inside corner a fillet (the commonest radius
    is the note's), or every outside edge rounded (``ROUNDS``) or chamfered
    (``CHAMFERS 1 × 45°``), whichever is commoner. Blends and chamfers of other
    sizes still need stating, and the completeness report says which. A part
    with sharp edges of both kinds gets no notes."""
    from collections import Counter

    from cadgen._internal.drawing_features import blends, chamfers, sharp_edges

    found = blends(part)
    bevels = [c for c in chamfers(part) if c.symmetric]
    outside, inside = sharp_edges(part)
    notes = []
    fillets = Counter(round(b.radius, 3) for b in found if b.concave)
    if fillets and not inside:
        notes.append(f"FILLETS R{_fmt(_commonest(fillets))} UNLESS OTHERWISE SPECIFIED.")
    rounds = Counter(round(b.radius, 3) for b in found if not b.concave)
    sizes = Counter(round(c.legs[0], 3) for c in bevels)
    if not outside and (rounds or sizes):
        if sum(rounds.values()) >= sum(sizes.values()):
            notes.append(f"ROUNDS R{_fmt(_commonest(rounds))} UNLESS OTHERWISE SPECIFIED.")
        else:
            notes.append(f"CHAMFERS {_fmt(_commonest(sizes))} × 45° UNLESS OTHERWISE SPECIFIED.")
    return notes


def _commonest(counts) -> float:
    """The most frequent value; the larger of a tie."""
    return max(counts, key=lambda value: (counts[value], value))


def _unstated_edges(record: dict, whose: str) -> list[str]:
    """The blends and chamfers a part's sheets leave unstated. A blend is stated by
    a note naming its radius and kind (FILLETS for inside corners, ROUNDS for
    outside edges, RADII for either) or by a ``radius()`` callout of its size; a
    chamfer by a note giving its size (``1 × 45°``, or ``1 × 2`` for unequal
    legs)."""
    from cadgen._internal.drawing_features import blends, chamfers

    notes = [note.upper() for note in record.get("notes", ())]
    lines = []
    groups: dict[tuple, int] = {}
    for blend in blends(record["shape"]):
        key = (round(blend.radius, 3), blend.concave)
        groups[key] = groups.get(key, 0) + 1
    for (radius, concave), count in sorted(groups.items()):
        word = "FILLET" if concave else "ROUND"
        mark = re.compile(rf"\bR{re.escape(_fmt(radius))}(?!\.?\d)")  # R0.8 is not R0.85
        named = any(mark.search(note) and (word in note or "RADII" in note) for note in notes)
        if named or radius in record.get("radii", ()):
            continue
        plural = count > 1
        lines.append(
            f"incomplete: {whose}{count} {word.lower()}{'s' if plural else ''} R{_fmt(radius)} "
            f"{'are' if plural else 'is'} not stated. radius(...) states one where a view shows it as an arc, "
            "or geometry_notes(part) gives a general note when the part's edges make one true."
        )
    bevels: dict[tuple, int] = {}
    for chamfer in chamfers(record["shape"]):
        key = tuple(sorted((round(chamfer.legs[0], 3), round(chamfer.legs[1], 3))))
        bevels[key] = bevels.get(key, 0) + 1
    for (a, b), count in sorted(bevels.items()):
        size = f"{_fmt(a)} × 45°" if abs(a - b) < 1e-3 else f"{_fmt(a)} × {_fmt(b)}"
        second = "45°" if abs(a - b) < 1e-3 else re.escape(_fmt(b))
        mark = re.compile(rf"(?<![\d.]){re.escape(_fmt(a))} ?[×X] ?{second}")
        if any(mark.search(note) for note in notes):
            continue
        plural = count > 1
        lines.append(
            f"incomplete: {whose}{count} chamfer{'s' if plural else ''} {size} {'are' if plural else 'is'} not "
            f"stated. A note giving its size states it (\"CHAMFER {size}\"), or geometry_notes(part) gives a "
            "general note when the part's edges make one true."
        )
    return lines
