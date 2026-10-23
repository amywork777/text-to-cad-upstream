"""The semantic PMI of an AP242 STEP file, read without OCCT: a report of what the file says.

    python -m cadgen._internal.ap242_pmi_report FILE.step [--parser builtin|steputils] [--schema MIM_LF.exp]

This is a reader of its own, sharing no code with cadgen's engine or OCCT's STEP translator: it
parses the Part 21 file (its own tokenizer, or the third-party ``steputils`` parser) and walks
AP242's PMI entities as ISO 10303-242 and the CAx-IF Recommended Practices for PMI define them:

- dimensions: ``DIMENSIONAL_SIZE`` / ``DIMENSIONAL_LOCATION``, their nominal from the
  ``DIMENSIONAL_CHARACTERISTIC_REPRESENTATION``'s ``SHAPE_DIMENSION_REPRESENTATION``, its
  descriptive notes (a basic dimension's ``'theoretical'``), and their
  ``PLUS_MINUS_TOLERANCE``'s ``TOLERANCE_VALUE`` (lower, upper);
- datums: ``DATUM`` (its identification), the ``DATUM_FEATURE`` a ``SHAPE_ASPECT_RELATIONSHIP``
  ties to it;
- geometric tolerances: any ``*_TOLERANCE`` entity (simple or complex), its magnitude, its
  ``DATUM_SYSTEM``'s compartments in order, its ``TOLERANCE_ZONE``'s form;
- each annotation's geometry: the ``GEOMETRIC_ITEM_SPECIFIC_USAGE`` of its shape aspect, the
  ``ADVANCED_FACE`` it identifies (its name), and that face's surface: a ``PLANE`` (origin,
  normal) or a ``CYLINDRICAL_SURFACE`` (radius);
- every measure's unit, from its unit entity (``SI_UNIT(.MILLI.,.METRE.)`` is mm).

It also says what is malformed for a strict reader: a measure written untyped where AP242's
``measure_value`` select needs its type, a reference to no record, and -- given AP242's EXPRESS
long form (``--schema``) -- any entity of the PMI graph whose attribute count is not its
schema's. The report is JSON on stdout; it is what ``test_pmi`` checks the engine's export with.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- the file as records ---------------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    id: int


@dataclass(frozen=True)
class Enum:
    name: str


@dataclass(frozen=True)
class Typed:
    type: str
    value: Any


UNSET = None
DERIVED = "*"


def _tokens(text: str):
    at, end = 0, len(text)
    while at < end:
        char = text[at]
        if char.isspace():
            at += 1
        elif char == "'":
            close = at + 1
            while True:
                close = text.index("'", close)
                if close + 1 < end and text[close + 1] == "'":
                    close += 2
                    continue
                break
            yield ("str", text[at + 1:close].replace("''", "'"))
            at = close + 1
        elif char == "#":
            match = re.compile(r"#(\d+)").match(text, at)
            yield ("ref", int(match.group(1)))
            at = match.end()
        elif char == ".":
            match = re.compile(r"\.([A-Z_][A-Z0-9_]*)\.").match(text, at)
            if match:
                yield ("enum", match.group(1))
                at = match.end()
            else:
                match = re.compile(r"[-+]?\.?\d[\d.]*(?:[eE][-+]?\d+)?").match(text, at)
                yield ("num", match.group(0))
                at = match.end()
        elif char in "-+0123456789":
            match = re.compile(r"[-+]?\d+(\.\d*)?([eE][-+]?\d+)?").match(text, at)
            yield ("num", match.group(0))
            at = match.end()
        elif char in "(),=;$*":
            yield (char, char)
            at += 1
        elif char == '"':
            close = text.index('"', at + 1)
            yield ("binary", text[at + 1:close])
            at = close + 1
        else:
            match = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(text, at)
            if not match:
                raise ValueError(f"unexpected {text[at:at + 20]!r}")
            yield ("kw", match.group(0).upper())
            at = match.end()


def _number(text: str) -> Any:
    return float(text) if any(c in text for c in ".eE") else int(text)


def _parameters(tokens: list, at: int) -> tuple[list, int]:
    """A parenthesised parameter list from ``tokens[at]`` (its ``(``): its values and the end."""
    assert tokens[at][0] == "(", tokens[at]
    at += 1
    values: list = []
    if tokens[at][0] == ")":
        return values, at + 1
    while True:
        kind, value = tokens[at]
        if kind == "(":
            inner, at = _parameters(tokens, at)
            values.append(tuple(inner))
        elif kind == "kw":
            inner, at = _parameters(tokens, at + 1)
            values.append(Typed(value, inner[0] if len(inner) == 1 else tuple(inner)))
        else:
            values.append({"str": lambda v: v, "ref": Ref, "enum": Enum, "num": _number, "binary": lambda v: v,
                           "$": lambda v: UNSET, "*": lambda v: DERIVED}[kind](value))
            at += 1
        kind = tokens[at][0]
        at += 1
        if kind == ")":
            return values, at
        assert kind == ",", tokens[at - 1]


def parse_builtin(text: str) -> dict[int, list[tuple[str, list]]]:
    """Every record of a Part 21 file's DATA section: its partial entities, each its type and
    parameters (one for a simple record, several for a complex one)."""
    body = text[text.index("DATA;") + 5:text.index("ENDSEC;", text.index("DATA;"))]
    records: dict[int, list[tuple[str, list]]] = {}
    for statement in _statements(body):
        tokens = list(_tokens(statement))
        assert tokens[0][0] == "ref" and tokens[1][0] == "=", statement[:60]
        number, at = tokens[0][1], 2
        if tokens[at][0] == "(":
            parts, at = [], at + 1
            while tokens[at][0] != ")":
                name = tokens[at][1]
                values, at = _parameters(tokens, at + 1)
                parts.append((name, values))
            records[number] = parts
        else:
            values, _end = _parameters(tokens, at + 1)
            records[number] = [(tokens[at][1], values)]
    return records


def _statements(body: str):
    """The DATA section's statements, each up to its ``;`` outside a string."""
    start, at, quoted = 0, 0, False
    while at < len(body):
        char = body[at]
        if char == "'":
            quoted = not quoted
        elif char == ";" and not quoted:
            statement = body[start:at].strip()
            if statement:
                yield statement
            start = at + 1
        at += 1


def parse_steputils(path: Path) -> dict[int, list[tuple[str, list]]]:
    """The same records, parsed by the third-party ``steputils`` (pure Python, no OCCT)."""
    from steputils import p21  # pyrefly: ignore[missing-import] - optional, a second parser to compare with

    def value(item: Any) -> Any:
        name = type(item).__name__
        if name == "Reference":
            return Ref(int(str(item)[1:]))
        if name == "Enumeration":
            return Enum(str(item).strip("."))
        if name == "UnsetParameter":
            return UNSET
        if name == "TypedParameter":
            return Typed(str(item.type_name).upper(), value(item.param))
        if isinstance(item, tuple):
            return tuple(value(inner) for inner in item)
        if isinstance(item, str) and str(item) == "*":
            return DERIVED
        return item

    data = p21.readfile(str(path)).data[0]
    records: dict[int, list[tuple[str, list]]] = {}
    for ref, instance in data.instances.items():
        number = int(str(ref)[1:])
        if type(instance).__name__ == "ComplexEntityInstance":
            records[number] = [(entity.name.upper(), [value(p) for p in entity.params]) for entity in instance.entities]
        else:
            records[number] = [(instance.entity.name.upper(), [value(p) for p in instance.entity.params])]
    return records


# --- the report --------------------------------------------------------------------------------


class Report:
    def __init__(self, records: dict[int, list[tuple[str, list]]]) -> None:
        self.records = records
        self.problems: list[str] = []
        self.referrers: dict[int, list[int]] = {}
        for number, parts in records.items():
            for _type, values in parts:
                for ref in _refs(values):
                    self.referrers.setdefault(ref, []).append(number)
                    if ref not in records:
                        self.problems.append(f"#{number} refers to #{ref}, which is no record")
        self.graph: set[int] = set()

    def types(self, number: int) -> list[str]:
        return [name for name, _values in self.records.get(number, [])]

    def part(self, number: int, name: str) -> list:
        for found, values in self.records[number]:
            if found == name:
                return values
        raise KeyError(f"#{number} is no {name}: {self.types(number)}")

    def of_type(self, name: str) -> list[int]:
        return sorted(number for number, parts in self.records.items() if any(found == name for found, _ in parts))

    def referring(self, number: int, name: str) -> list[int]:
        return sorted(n for n in self.referrers.get(number, []) if name in self.types(n))

    def note(self, *numbers: int) -> None:
        self.graph.update(numbers)

    # Units and measures.
    def unit(self, number: int) -> str:
        self.note(number)
        parts = dict(self.records[number])
        if "SI_UNIT" in parts:
            prefix, name = parts["SI_UNIT"]
            prefix = prefix.name if isinstance(prefix, Enum) else None
            base = name.name
            symbol = {"METRE": "m", "RADIAN": "rad", "STERADIAN": "sr"}.get(base, base.lower())
            prefixes = {"MILLI": "m", "CENTI": "c", "MICRO": "u", "KILO": "k", None: ""}
            return (prefixes[prefix] if prefix in prefixes else prefix.lower()) + symbol
        if "CONVERSION_BASED_UNIT" in parts:
            return parts["CONVERSION_BASED_UNIT"][0]
        return "+".join(parts)

    def measure(self, number: int) -> dict[str, Any]:
        """A measure-with-unit record: its value, unit, and the type it is written with."""
        self.note(number)
        values = None
        for name, given in self.records[number]:
            if name in ("MEASURE_WITH_UNIT", "LENGTH_MEASURE_WITH_UNIT", "PLANE_ANGLE_MEASURE_WITH_UNIT") and given:
                values = given
        if values is None:
            raise KeyError(f"#{number} holds no measure: {self.types(number)}")
        component, unit = values[0], values[1]
        typed = isinstance(component, Typed)
        if not typed:
            self.problems.append(f"#{number}: {self.types(number)} holds an untyped measure value ({component}); "
                                 "AP242's measure_value is a select and needs its type (LENGTH_MEASURE(...))")
        return {"value": float(component.value if typed else component), "unit": self.unit(unit.id),
                "type": component.type if typed else None}

    # Geometry.
    def face(self, aspect: int) -> dict[str, Any] | None:
        """What a shape aspect identifies: its usage's face, named, with its surface."""
        usages = self.referring(aspect, "GEOMETRIC_ITEM_SPECIFIC_USAGE")
        if len(usages) != 1:
            self.problems.append(f"#{aspect}: {len(usages)} GEOMETRIC_ITEM_SPECIFIC_USAGE (one is expected)")
            return None
        usage = self.part(usages[0], "GEOMETRIC_ITEM_SPECIFIC_USAGE")
        item = usage[4].id
        self.note(usages[0], item)
        if "ADVANCED_FACE" not in self.types(item):
            return {"item": self.types(item)}
        name, _bounds, geometry, same_sense = self.part(item, "ADVANCED_FACE")
        return {"face": f"#{item}", "name": name, "surface": self.surface(geometry.id),
                "same_sense": same_sense.name if isinstance(same_sense, Enum) else same_sense}

    def surface(self, number: int) -> dict[str, Any]:
        kind = self.types(number)[0]
        values = self.part(number, kind)
        if kind == "PLANE":
            origin, normal = self.placement(values[1].id)
            return {"type": "plane", "origin": origin, "normal": normal}
        if kind == "CYLINDRICAL_SURFACE":
            origin, axis = self.placement(values[1].id)
            return {"type": "cylinder", "radius": float(values[2]), "origin": origin, "axis": axis}
        return {"type": kind.lower()}

    def placement(self, number: int) -> tuple[list[float], list[float]]:
        values = self.part(number, "AXIS2_PLACEMENT_3D")
        origin = [float(v) for v in self.part(values[1].id, "CARTESIAN_POINT")[1]]
        axis = [float(v) for v in self.part(values[2].id, "DIRECTION")[1]] if values[2] is not UNSET else [0.0, 0.0, 1.0]
        return origin, axis

    # PMI.
    def dimensions(self) -> list[dict[str, Any]]:
        found = []
        for kind in ("DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION"):
            for number in self.of_type(kind):
                self.note(number)
                values = self.part(number, kind)
                entry: dict[str, Any] = {"record": f"#{number}", "entity": kind}
                if kind == "DIMENSIONAL_SIZE":
                    entry["name"] = values[1]
                    entry["features"] = [self.face_of_aspect(values[0].id)]
                else:
                    entry["name"] = values[0]
                    entry["features"] = [self.face_of_aspect(values[2].id), self.face_of_aspect(values[3].id)]
                entry["nominal"] = self.nominal(number)
                entry["notes"] = self.notes(number)
                entry["tolerance"] = self.plus_minus(number)
                found.append(entry)
        return found

    def face_of_aspect(self, aspect: int) -> dict[str, Any] | None:
        self.note(aspect)
        return self.face(aspect)

    def nominal(self, dimension: int) -> dict[str, Any] | None:
        for holder in self.referring(dimension, "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION"):
            self.note(holder)
            representation = self.part(holder, "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION")[1].id
            self.note(representation)
            items = self.part(representation, "SHAPE_DIMENSION_REPRESENTATION")[1]
            for item in items:
                if "DESCRIPTIVE_REPRESENTATION_ITEM" in self.types(item.id):
                    continue  # a note (``notes``), not the value
                measure = self.measure(item.id)
                names = [values[0] for name, values in self.records[item.id] if name == "REPRESENTATION_ITEM"]
                measure["role"] = names[0] if names else None
                return measure
        return None

    def notes(self, dimension: int) -> list[list[str]]:
        """A dimension's descriptive items, [name, description] each: CAx-IF's dimension modifiers
        (5.3), ``['dimensional note', 'theoretical']`` for a basic dimension."""
        found = []
        for holder in self.referring(dimension, "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION"):
            representation = self.part(holder, "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION")[1].id
            for item in self.part(representation, "SHAPE_DIMENSION_REPRESENTATION")[1]:
                if "DESCRIPTIVE_REPRESENTATION_ITEM" in self.types(item.id):
                    self.note(item.id)
                    name, description = self.part(item.id, "DESCRIPTIVE_REPRESENTATION_ITEM")
                    found.append([name, description])
        return found

    def plus_minus(self, dimension: int) -> dict[str, Any] | None:
        for holder in self.referring(dimension, "PLUS_MINUS_TOLERANCE"):
            self.note(holder)
            tolerance_value = self.part(holder, "PLUS_MINUS_TOLERANCE")[0].id
            self.note(tolerance_value)
            lower, upper = self.part(tolerance_value, "TOLERANCE_VALUE")
            low, high = self.measure(lower.id), self.measure(upper.id)
            if low['unit'] != high['unit']:
                self.problems.append(f"#{tolerance_value}: lower/upper tolerance units differ ({low['unit']} / {high['unit']}); values are not normalized")
            return {"lower": low["value"], "upper": high["value"], "unit": high["unit"],
                    "types": [low["type"], high["type"]]}
        return None

    def datums(self) -> list[dict[str, Any]]:
        found = []
        for number in self.of_type("DATUM"):
            self.note(number)
            values = self.part(number, "DATUM")
            features = []
            for relation in self.referring(number, "SHAPE_ASPECT_RELATIONSHIP"):
                self.note(relation)
                relating = self.part(relation, "SHAPE_ASPECT_RELATIONSHIP")[2].id
                if "DATUM_FEATURE" in self.types(relating):
                    self.note(relating)
                    features.append(self.face(relating))
            found.append({"record": f"#{number}", "identification": values[4], "features": features})
        return found

    def tolerances(self) -> list[dict[str, Any]]:
        found = []
        for number, parts in sorted(self.records.items()):
            names = [name for name, _ in parts]
            kinds = [name for name in names if name.endswith("_TOLERANCE") and name not in
                     ("PLUS_MINUS_TOLERANCE", "GEOMETRIC_TOLERANCE")]
            if not kinds:
                if any(name.startswith('GEOMETRIC_TOLERANCE') for name in names):
                    self.problems.append(f"#{number}: geometric tolerance has no supported characteristic")
                continue
            self.note(number)
            supported = {kinds[0], 'GEOMETRIC_TOLERANCE', 'GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE'}
            for name in names:
                if name not in supported:
                    self.problems.append(f"#{number}: {name} semantics are not verified by this reader")
            base = dict(parts).get("GEOMETRIC_TOLERANCE") or dict(parts)[kinds[0]]
            magnitude, aspect = base[2], base[3]
            entry: dict[str, Any] = {"record": f"#{number}", "entity": kinds[0],
                                     "magnitude": self.measure(magnitude.id), "datums": [], "zone": None}
            self.note(aspect.id)
            entry["features"] = [self.face(aspect.id)]
            reference = dict(parts).get("GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE")
            if reference:
                for system in reference[0]:
                    self.note(system.id)
                    compartments = self.part(system.id, "DATUM_SYSTEM")[4]
                    for compartment in compartments:
                        self.note(compartment.id)
                        base_datum = self.part(compartment.id, "DATUM_REFERENCE_COMPARTMENT")[4]
                        if isinstance(base_datum, Ref):
                            entry["datums"].append(self.part(base_datum.id, "DATUM")[4])
                        else:
                            entry["datums"].append(str(base_datum))
            for zone in self.referring(number, "TOLERANCE_ZONE"):
                self.note(zone)
                form = self.part(zone, "TOLERANCE_ZONE")[5].id
                self.note(form)
                entry["zone"] = self.part(form, "TOLERANCE_ZONE_FORM")[0]
                for definition in self.referrers.get(zone, []):
                    self.note(definition)
                    entry.setdefault("zone_definitions", []).append(self.types(definition))
            found.append(entry)
        return found

    def schema_check(self, schema: Path) -> None:
        """Every record of the PMI graph against AP242's EXPRESS long form: its entity declared, its
        explicit attribute count (with its supertypes' for a simple record) the schema's."""
        declared = _express(schema.read_text(encoding="utf-8", errors="replace"))
        for number in sorted(self.graph):
            parts = self.records[number]
            for name, values in parts:
                if name not in declared:
                    self.problems.append(f"#{number}: {name} is not an entity of {schema.name}")
                    continue
                wanted = _count(declared, name, inherited=len(parts) == 1)
                if wanted != len(values):
                    self.problems.append(f"#{number}: {name} has {len(values)} attribute(s); {schema.name} declares "
                                         f"{wanted}")
        orphans = [n for n in self.graph if not self.referrers.get(n) and not any(
            t in ("DIMENSIONAL_CHARACTERISTIC_REPRESENTATION", "PLUS_MINUS_TOLERANCE", "GEOMETRIC_ITEM_SPECIFIC_USAGE",
                  "SHAPE_ASPECT_RELATIONSHIP", "TOLERANCE_ZONE") or t.endswith(("_TOLERANCE", "_ZONE_DEFINITION"))
            for t in self.types(n))]
        for number in sorted(set(orphans)):
            self.problems.append(f"#{number}: {self.types(number)} is referred to by nothing")


def _refs(values: Any):
    if isinstance(values, Ref):
        yield values.id
    elif isinstance(values, Typed):
        yield from _refs(values.value)
    elif isinstance(values, (list, tuple)):
        for value in values:
            yield from _refs(value)


def _express(text: str) -> dict[str, tuple[list[str], int]]:
    """Each entity's supertypes and its count of explicit attributes (redeclarations not counted)."""
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S)
    found: dict[str, tuple[list[str], int]] = {}
    for match in re.finditer(r"\bENTITY\s+(\w+)(.*?)\bEND_ENTITY\s*;", text, flags=re.S | re.I):
        name, body = match.group(1).upper(), match.group(2)
        supertypes = []
        head = re.match(r"(.*?);", body, flags=re.S)
        header = head.group(1) if head else ""
        sub = re.search(r"SUBTYPE\s+OF\s*\(([^)]*)\)", header, flags=re.I)
        if sub:
            supertypes = [item.strip().upper() for item in sub.group(1).split(",")]
        attributes = body[head.end():] if head else body
        attributes = re.split(r"\b(DERIVE|INVERSE|UNIQUE|WHERE)\b", attributes, maxsplit=1, flags=re.I)[0]
        count = 0
        for statement in attributes.split(";"):
            statement = statement.strip()
            if ":" not in statement or statement.upper().startswith("SELF\\"):
                continue
            names = statement.split(":", 1)[0]
            count += len([item for item in names.split(",") if item.strip()])
        found[name] = (supertypes, count)
    return found


def _count(declared: dict[str, tuple[list[str], int]], name: str, inherited: bool) -> int:
    supertypes, own = declared[name]
    if not inherited:
        return own
    seen: set[str] = set()

    def total(entity: str) -> int:
        if entity in seen or entity not in declared:
            return 0
        seen.add(entity)
        parents, count = declared[entity]
        return count + sum(total(parent) for parent in parents)

    return total(name)


def report(path: Path, parser: str = "builtin", schema: Path | None = None) -> dict[str, Any]:
    records = parse_steputils(path) if parser == "steputils" else parse_builtin(path.read_text(encoding="utf-8"))
    found = Report(records)
    header = path.read_text(encoding="utf-8").split("DATA;", 1)[0]
    schema_name = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", header)
    result = {"file": path.name, "parser": parser, "schema": schema_name.group(1) if schema_name else None,
              "dimensions": found.dimensions(), "datums": found.datums(), "tolerances": found.tolerances()}
    # Include unannotated geometry: another part can reuse an annotated face's name.
    face_names = Counter(found.part(number, 'ADVANCED_FACE')[0] for number in found.of_type('ADVANCED_FACE'))
    result['ambiguousFaceNames'] = sorted(name for name, count in face_names.items() if count > 1)
    if schema is not None:
        found.schema_check(schema)
    result["problems"] = sorted(set(found.problems))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", type=Path)
    parser.add_argument("--parser", choices=("builtin", "steputils"), default="builtin")
    parser.add_argument("--schema", type=Path, help="AP242's EXPRESS long form, to check attribute counts")
    args = parser.parse_args(argv)
    json.dump(report(args.step, args.parser, args.schema), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
