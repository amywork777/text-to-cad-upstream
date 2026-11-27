"""A STEP assembly made of part STEP files as they are written: each part's entities copied in once, renumbered, and
placed by an assembly usage with a transformation, as an AP214 assembly is. A faceted part (``cad gsl step``) stays
a faceted B-rep and an exact part stays the B-rep it was written as, so the assembly is the size of its parts. A
writer that takes shapes (the kernel's) writes every face again in its own form: for a faceted lattice, about six
times the bytes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["assemble"]

_ENTITY = re.compile(r"#(\d+)\s*=\s*(.*)", re.S)
_REF = re.compile(r"#(\d+)")
_QUOTED = re.compile(r"('(?:[^']|'')*')")


def _entities(path: Path) -> dict[int, str]:
    text = path.read_text(encoding="latin-1")
    try:
        data = text[text.index("DATA;") + 5:text.rindex("ENDSEC;")]
    except ValueError:
        raise ValueError(f"{path} is not a STEP file") from None
    found: dict[int, str] = {}
    for chunk in re.split(r";\s*\n(?=\s*#\d+\s*=)", data.strip().rstrip(";")):
        matched = _ENTITY.match(chunk.strip())
        if matched:
            found[int(matched.group(1))] = " ".join(matched.group(2).split())
    return found


def _refs(body: str) -> list[int]:
    return [int(n) for piece in _QUOTED.split(body)[::2] for n in _REF.findall(piece)]


def _moved(body: str, offset: int) -> str:
    """``body`` with every reference outside its strings moved by ``offset``."""
    pieces = _QUOTED.split(body)
    return "".join(piece if index % 2 else _REF.sub(lambda m: f"#{int(m.group(1)) + offset}", piece)
                   for index, piece in enumerate(pieces))


def _of(entities: dict[int, str], kind: str) -> list[int]:
    return [n for n, body in entities.items() if re.match(rf"{kind}\s*\(", body)]


def _frame(at: Any) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """A placement as its origin, z and x directions: ``(x, y, z)`` moves, a build123d ``Location`` moves and turns."""
    wrapped = getattr(at, "wrapped", None)
    if wrapped is None:
        x, y, z = (float(v) for v in at)
        return (x, y, z), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)
    from OCP.gp import gp_Dir

    transform = wrapped.Transformation()
    move = transform.TranslationPart()
    zd, xd = gp_Dir(0, 0, 1).Transformed(transform), gp_Dir(1, 0, 0).Transformed(transform)
    return (move.X(), move.Y(), move.Z()), (zd.X(), zd.Y(), zd.Z()), (xd.X(), xd.Y(), xd.Z())


def _label(text: str) -> str:
    return "".join(ch for ch in str(text) if ch.isascii() and ch.isprintable() and ch not in "'\\") or "part"


def assemble(out: Path, parts: list[tuple[Any, str, Any]], *, name: str = "assembly") -> Path:
    """Write ``parts`` (each ``(step_file, label, placement)``) as one STEP assembly at ``out``. A file given twice
    is copied in once and used twice. Each file must hold one part, not an assembly."""
    lines: list[str] = []
    next_id = 1

    def add(body: str) -> int:
        nonlocal next_id
        lines.append(f"#{next_id}={body};")
        next_id += 1
        return next_id - 1

    copied: dict[Path, tuple[int, int, int, int, int]] = {}
    placed = []
    for source, label, at in parts:
        path = Path(source).expanduser().resolve()
        if path not in copied:
            entities = _entities(path)
            definitions = _of(entities, "SHAPE_DEFINITION_REPRESENTATION")
            if len(_of(entities, "PRODUCT")) != 1 or len(definitions) != 1:
                raise ValueError(f"{path} holds an assembly or no part: give each part its own STEP file")
            shape, representation = _refs(entities[definitions[0]])[:2]
            definition = _refs(entities[shape])[0]
            product = _refs(entities[_refs(entities[definition])[0]])[0]
            entities[product] = f"PRODUCT('{_label(label)}','{_label(label)}','',(" + entities[product].rsplit("(", 1)[1]
            items = _refs(entities[representation])
            axis = next((n for n in items if entities[n].startswith("AXIS2_PLACEMENT_3D")), None)
            if axis is None:
                raise ValueError(f"{path}: its shape has no placement to move it by")
            offset = next_id - min(entities)
            for n in sorted(entities):
                lines.append(f"#{n + offset}={_moved(entities[n], offset)};")
            next_id = max(entities) + offset + 1
            context = _of(entities, "APPLICATION_CONTEXT")[0]
            copied[path] = (definition + offset, representation + offset, axis + offset, items[-1] + offset,
                            context + offset)
        placed.append((copied[path], _label(label), _frame(at)))

    first = placed[0][0]
    application, units = first[4], first[3]
    product_context = add(f"PRODUCT_CONTEXT('',#{application},'mechanical')")
    product = add(f"PRODUCT('{_label(name)}','{_label(name)}','',(#{product_context}))")
    formation = add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
    definition_context = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{application},'design')")
    top = add(f"PRODUCT_DEFINITION('design','',#{formation},#{definition_context})")
    top_shape = add(f"PRODUCT_DEFINITION_SHAPE('','',#{top})")

    def frame(origin, z, x) -> int:
        point = add("CARTESIAN_POINT('',(%.6f,%.6f,%.6f))" % origin)
        up = add("DIRECTION('',(%.9f,%.9f,%.9f))" % z)
        along = add("DIRECTION('',(%.9f,%.9f,%.9f))" % x)
        return add(f"AXIS2_PLACEMENT_3D('',#{point},#{up},#{along})")

    home = frame((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    frames = [frame(*where) for _part, _label_, where in placed]
    top_rep = add(f"SHAPE_REPRESENTATION('{_label(name)}',(#{home}," + ",".join(f"#{n}" for n in frames)
                  + f"),#{units})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{top_shape},#{top_rep})")
    for index, (((definition, representation, axis, _units, _app), label, _where), place) in enumerate(
            zip(placed, frames), 1):
        usage = add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{index}','{label}','',#{top},#{definition},$)")
        usage_shape = add(f"PRODUCT_DEFINITION_SHAPE('','',#{usage})")
        moved = add(f"ITEM_DEFINED_TRANSFORMATION('','',#{axis},#{place})")
        relation = add(f"( REPRESENTATION_RELATIONSHIP('','',#{representation},#{top_rep}) "
                       f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{moved}) SHAPE_REPRESENTATION_RELATIONSHIP() )")
        add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{relation},#{usage_shape})")
    header = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('an assembly of part files as they are'),'2;1');\n"
              f"FILE_NAME('{_label(name)}.step','',(''),(''),'cad gsl assemble','','');\n"
              "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
    out = Path(out).expanduser().absolute()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(lines) + "\nENDSEC;\nEND-ISO-10303-21;\n", encoding="latin-1")
    return out
