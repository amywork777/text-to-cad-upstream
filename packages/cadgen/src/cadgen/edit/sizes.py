"""A project's named sizes in one place, for Studio's Overview (Sizes).

A part script names its sizes at its top (``WIDTH = 40.0``). Sizes several parts share live in
``sizes.py`` beside the parts, which import them (``from sizes import WALL``): a script's imports
resolve from its own folder (``cadgen._internal.import_roots``), so the shared file sits where the
parts are. Any other module the parts import that names sizes is shared the same way.

This reads the sizes from the source without running anything, changes one that is a plain
number where it is written, and adds a shared one. A change then builds again every part that
uses the file, as edit mode's changes do (``service.py``); adding a size changes no part.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from cadgen.edit.service import _project_units, _python_files, dependents, is_part
from cadgen._internal.atomic_replace import replace_atomic

__all__ = ["SHARED_FILE", "SizesError", "add_shared", "set_size", "shared_folder", "sizes"]

SHARED_FILE = "sizes.py"
# A named size is a constant: an upper-case name at a script's top level.
_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NUMBER = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
# Unit factors the scripts name are not sizes (as edit mode's ``tracer.UNIT_NAMES``).
_UNITS = {"INCH", "INCHES", "IN", "MM", "MM_PER_IN", "MM_PER_INCH"}
_SHARED_HEADER = '"""Sizes several parts share. A part uses one by name: `from sizes import WALL`."""\n'


class SizesError(ValueError):
    """A size that cannot be read, changed or added as asked, said for the person."""


def _number(node: ast.expr) -> float | None:
    """A plain number as written (``40``, ``2.5``, ``-3``), or None."""
    sign = 1.0
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        node = node.operand
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return sign * float(node.value)
    return None


def _formula(node: ast.expr) -> bool:
    """Plain arithmetic of numbers and other sizes (``2 * WALL + 1``)."""
    for each in ast.walk(node):
        if isinstance(each, ast.Constant):
            if type(each.value) not in (int, float):
                return False
        elif not isinstance(each, (ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.operator, ast.unaryop)):
            return False
    return any(isinstance(each, ast.Name) for each in ast.walk(node))


def _named(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    """A top-level ``NAME = value`` (or ``NAME: float = value``): its name and value."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        target, value = statement.target, statement.value
    else:
        return None
    if not isinstance(target, ast.Name) or not _NAME.match(target.id) or target.id in _UNITS:
        return None
    return target.id, value


def _sizes_in(source: str) -> list[dict]:
    """A script's named sizes, top to bottom: each a number (changed here) or a formula of others."""
    lines = source.splitlines()
    found = []
    for statement in ast.parse(source).body:
        named = _named(statement)
        if named is None:
            continue
        name, value = named
        number = _number(value)
        if number is None and not _formula(value):
            continue
        rest = lines[statement.end_lineno - 1].encode("utf-8")[statement.end_col_offset :].decode("utf-8", "replace")
        note = rest.split("#", 1)[1].strip() if "#" in rest else ""
        found.append({
            "name": name,
            "line": statement.lineno,
            "text": ast.get_source_segment(source, value) or "",
            "value": number,
            # One that is worked out from others changes where those are written.
            "editable": number is not None and value.lineno == value.end_lineno,
            "note": note,
        })
    return found


def _project(folder: str) -> Path:
    root = Path(folder).expanduser()
    if not folder or not root.is_absolute() or not root.is_dir():
        raise SizesError("Sizes needs the project's folder.")
    return root.resolve()


def _inside(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise SizesError("That file is not in the project.") from None
    if path.suffix != ".py" or not path.is_file():
        raise SizesError(f"{rel} is not one of the project's scripts.")
    return path


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def shared_folder(root: Path) -> Path:
    """Where a shared size goes: beside the parts, in the folder holding the most of them (the
    shallowest when two hold as many), so they import it by name; the project's folder when it has
    none yet."""
    counts = Counter(path.parent for path in _python_files(root) if is_part(path))
    if not counts:
        return root
    most = max(counts.values())
    return min((folder for folder, count in counts.items() if count == most), key=lambda folder: (len(folder.parts), str(folder)))


def sizes(folder: str) -> dict:
    """Every named size in a project: the shared ones first (``sizes.py``, then any other module
    the parts import that names sizes), each with the parts that use it; then each part's own."""
    root = _project(folder)
    shared, parts = [], []
    for path in sorted(_python_files(root)):
        try:
            listed = _sizes_in(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        rel = _relative(root, path)
        if is_part(path):
            if listed:
                parts.append({"file": rel, "name": path.stem, "kind": "part", "sizes": listed})
            continue
        users = [part.stem for part in dependents(root, rel) if part != path]
        if listed and (users or path.name == SHARED_FILE):
            shared.append({"file": rel, "name": path.stem, "kind": "shared", "usedBy": users, "sizes": listed})
    shared.sort(key=lambda group: (group["name"] != Path(SHARED_FILE).stem, group["file"]))
    parts.sort(key=lambda group: (group["name"].lower(), group["file"]))
    return {
        "ok": True,
        "root": str(root),
        "units": _project_units(root).get("units") or "mm",
        "sharedFile": _relative(root, shared_folder(root) / SHARED_FILE),
        "groups": shared + parts,
    }


def _write(path: Path, text: str) -> None:
    """The file rewritten whole, so a build never reads it half written."""
    temporary = path.with_name(f".{path.name}.sizes")
    temporary.write_text(text, encoding="utf-8")
    replace_atomic(temporary, path)


def set_size(folder: str, rel: str, name: str, line: int, old: str, text: str) -> dict:
    """One size changed where it is written: the number on its line, the rest of the line as it
    was. ``old`` is the number as the page read it; a file changed since is refused."""
    root = _project(folder)
    path = _inside(root, rel)
    typed = text.strip()
    if not _NUMBER.match(typed):
        raise SizesError(f"{name} is a number here, like 12.5.")
    source = path.read_text(encoding="utf-8")
    for statement in ast.parse(source).body:
        named = _named(statement)
        if named is None or named[0] != name or statement.lineno != line:
            continue
        value = named[1]
        if _number(value) is None or value.lineno != value.end_lineno:
            raise SizesError(f"{name} is worked out from other sizes. Change those instead.")
        written = ast.get_source_segment(source, value)
        if written != old:
            raise SizesError(f"{name} changed since Sizes read it; it is {written} now.")
        lines = source.splitlines(keepends=True)
        raw = lines[value.lineno - 1].encode("utf-8")
        lines[value.lineno - 1] = (raw[: value.col_offset] + typed.encode("utf-8") + raw[value.end_col_offset :]).decode("utf-8")
        _write(path, "".join(lines))
        return {"ok": True, "root": str(root), "file": rel, "name": name, "text": typed,
                "parts": [part.stem for part in dependents(root, rel)]}
    raise SizesError(f"{name} is no longer on line {line} of {rel}. Open Sizes again to read it.")


def add_shared(folder: str, name: str, text: str, note: str = "") -> dict:
    """A shared size added at the end of ``sizes.py`` beside the parts (made, with a line saying
    what it is for, when there is none yet). No part uses it until one imports it."""
    root = _project(folder)
    named, typed, said = name.strip(), text.strip(), " ".join(note.split())
    if not _NAME.match(named) or named in _UNITS:
        raise SizesError("A size's name is capitals, digits and underscores, starting with a letter, like WALL_THICKNESS.")
    if not _NUMBER.match(typed):
        raise SizesError(f"{named} is a number here, like 12.5.")
    path = shared_folder(root) / SHARED_FILE
    source = path.read_text(encoding="utf-8") if path.is_file() else _SHARED_HEADER
    if any(size["name"] == named for size in _sizes_in(source)):
        raise SizesError(f"{named} is already a shared size.")
    entry = f"{named} = {typed}" + (f"  # {said}" if said else "")
    _write(path, source + ("" if source.endswith("\n") else "\n") + ("\n" if source == _SHARED_HEADER else "") + entry + "\n")
    return {"ok": True, "root": str(root), "file": _relative(root, path), "name": named, "text": typed}
