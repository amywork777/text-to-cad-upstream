"""Drawings, as SolidWorks' Make Drawing from Part makes one and its Sheet Properties change it.

A part's drawing is an engineering drawing script beside the part (``cadgen.eng_drawing``):
``<name>_drawing.py``, which calls the part's model (``part().shape``: the engine's document of it)
and lays out its views on a sheet, so the drawing follows the part. One made before parts were
models reads the part's STEP, and is found by it as ever. Make Drawing writes one from the template (top, front and right views
in third angle and an isometric, each with its overall size), and the drawing panel changes its
sheet: the size, the scale, the title block's fields, and whether the isometric is drawn. Each
change runs the script, which writes the drawing's PDF.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

# The title block's fields the panel edits, in the order a Sheet is written with them.
FIELDS = ("title", "part_number", "material", "revision", "author")
SIZES = ("A4", "A3", "A2", "A1", "A0")
_SKIPPED = {".venv", "venv", "node_modules", "tmp", ".git", "__pycache__", "_runtime", "dist", "build"}


class DrawingError(Exception):
    """A drawing change that cannot be made, said to the engineer."""


# This runs in the viewer's server, which never loads the CAD kernel: its own small helpers, not `commands`'.
def _call_name(node) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None


def _number(value: float) -> str:
    value = round(float(value), 6)
    return str(int(value)) if value.is_integer() else f"{value:.6f}".rstrip("0").rstrip(".")


def find(root: Path, step: Path) -> Path | None:
    """The project's drawing of a part (``step``: its script, or the STEP a drawing reads):
    ``<name>_drawing.py`` beside the part's model, else an engineering drawing script anywhere in
    the project that imports the part's script or reads its STEP."""
    name = step.stem
    imports = re.compile(rf"^\s*(?:from\s+(?:\.\s*)?{re.escape(name)}\s+import|import\s+{re.escape(name)}\b)", re.M)
    # Drawing scripts are named for what they draw: those first, the one named for this part first of all.
    named = [path for path in _scripts(root) if path.name.endswith("_drawing.py")]
    candidates = sorted(named, key=lambda path: path.name != f"{name}_drawing.py")
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "eng_drawing" in text and (f"{name}.step" in text or imports.search(text)):
            return path
    return None


def _scripts(root: Path):
    for folder, folders, files in os.walk(root):
        folders[:] = [each for each in folders if each not in _SKIPPED and not each.startswith(".")]
        for file in files:
            if file.endswith(".py"):
                yield Path(folder) / file


def template(name: str, step: Path, script: Path, *, material: str = "", units: str = "mm") -> str:
    """A drawing script for the part named ``name``, from the engineering drawing skill's template.
    ``step`` is the part's script, whose model it calls (``part().shape``), or a STEP, which it
    reads (``read_step``)."""
    source = Path(step)
    if source.suffix.lower() == ".py":
        from cadgen.edit.service import model_of

        found = model_of(source.read_text(encoding="utf-8"))
        if found is None:
            raise DrawingError(f"{source.name} declares no model to draw.")
        if source.resolve().parent != Path(script).resolve().parent:
            raise DrawingError(f"A drawing goes beside its part: {source.name} is in another folder.")
        # Beside it, the part's script imports by its name, as `python <drawing>.py` runs it.
        head = f"from cadgen.eng_drawing import Sheet, eng_drawing\n\nfrom {source.stem} import {found[0]}"
        return _template(name, head, f"{found[0]}().shape", material=material, units=units)
    reading = os.path.relpath(source.resolve(), Path(script).parent.resolve()).replace(os.sep, "/")
    head = "from pathlib import Path\n\nfrom cadgen import read_step\nfrom cadgen.eng_drawing import Sheet, eng_drawing"
    return _template(name, head, f'read_step(Path(__file__).parent / "{reading}")', material=material, units=units)


def _template(name: str, head: str, reads: str, *, material: str, units: str) -> str:
    function = f"{re.sub(r'[^0-9a-zA-Z_]', '_', name)}_drawing"
    title = name.replace("_", " ").upper()
    fields = [f'title="{title}"', f'part_number="{title.replace(" ", "-")}"']
    if material:
        fields.append(f'material="{material.upper()}"')
    fields += ['revision="A"', *([f'units="{units}"'] if units == "in" else [])]
    return f'''{head}


@eng_drawing(out="{function}.pdf")
def {function}():
    part = {reads}
    sheet = Sheet("A3", {", ".join(fields)})
    # Third angle, placed from the part's size; iso=True adds the isometric.
    top, front, right, iso = sheet.three_views(part, iso=True)
    top.overall()
    front.overall()
    return sheet


if __name__ == "__main__":
    {function}()
'''


def _sheet_call(tree: ast.Module) -> ast.Call:
    found = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) == "Sheet"]
    if len(found) != 1:
        raise DrawingError("The drawing's script makes more than one sheet, or none. Ask the agent to change it.")
    return found[0]


def _views_statement(tree: ast.Module):
    """``top, front, right[, iso] = sheet.three_views(part[, iso=True])``."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple)
                and _call_name(node.value) == "three_views"):
            return node
    return None


def read(text: str) -> dict:
    """The sheet as the panel opens on it: its size, scale (as ``1:2``), title block fields and
    whether the isometric is drawn; and the PDF it writes (``out``)."""
    tree = ast.parse(text)
    call = _sheet_call(tree)
    values = {"size": "A3", "scale": "1:1", **dict.fromkeys(FIELDS, "")}
    if call.args and isinstance(call.args[0], ast.Constant):
        values["size"] = str(call.args[0].value)
    for keyword in call.keywords:
        if keyword.arg in ("size", *FIELDS) and isinstance(keyword.value, ast.Constant):
            values[keyword.arg] = str(keyword.value.value)
        elif keyword.arg == "scale" and isinstance(keyword.value, ast.Constant):
            values["scale"] = _ratio(float(keyword.value.value))
    statement = _views_statement(tree)
    values["iso"] = bool(statement and any(keyword.arg == "iso" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                                           for keyword in statement.value.keywords))
    out = next((keyword.value.value for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) == "eng_drawing"
                for keyword in node.keywords if keyword.arg == "out" and isinstance(keyword.value, ast.Constant)), None)
    values["out"] = out
    return values


def _ratio(scale: float) -> str:
    """A drawing scale as a sheet prints it: 0.5 is 1:2, 2 is 2:1."""
    if scale >= 1:
        return f"{_number(scale)}:1"
    return f"1:{_number(round(1 / scale, 6))}"


def _scale(typed: str) -> float:
    text = str(typed or "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", text)
    try:
        value = float(match.group(1)) / float(match.group(2)) if match else float(text)
    except (ValueError, ZeroDivisionError):
        raise DrawingError("A scale is written 1:2, 2:1, or as a number.") from None
    if not value > 0:
        raise DrawingError("A scale is more than zero.")
    return value


def change(text: str, sheet: dict) -> tuple[str, str]:
    """The script with its sheet set as ``sheet`` says (any of size, scale, the title block's
    fields, ``iso``), and what changed, in words."""
    tree = ast.parse(text)
    call = _sheet_call(tree)
    was = read(text)
    size = str(sheet.get("size") or was["size"]).upper()
    if size not in SIZES:
        raise DrawingError(f"A sheet is {', '.join(SIZES)}.")
    kept = [keyword for keyword in call.keywords if keyword.arg not in ("size", "scale", *FIELDS)]
    written = [f'"{size}"']
    for field in FIELDS:
        value = str(sheet.get(field, was[field]) or "").strip()
        if '"' in value or "\n" in value:
            raise DrawingError("A title block field is one line, without double quotes.")
        if value:
            written.append(f'{field}="{value}"')
    scale = _scale(sheet.get("scale") or was["scale"])
    if abs(scale - 1) > 1e-12:
        written.append(f"scale={_number(round(scale, 6))}")
    written += [ast.get_source_segment(text, keyword) for keyword in kept]
    swaps: list[tuple[int, int, str]] = []  # whole lines put as one: (first, last, the line)
    lines = text.splitlines()
    head = f"{ast.get_source_segment(text, call.func)}({', '.join(written)})"
    prefix = lines[call.lineno - 1].encode("utf-8")[:call.col_offset].decode("utf-8")
    suffix = lines[call.end_lineno - 1].encode("utf-8")[call.end_col_offset:].decode("utf-8")
    swaps.append((call.lineno, call.end_lineno, f"{prefix}{head}{suffix}"))
    iso = sheet.get("iso")
    statement = _views_statement(tree)
    if iso is not None and statement is not None and bool(iso) != was["iso"]:
        targets = [element.id for element in statement.targets[0].elts if isinstance(element, ast.Name)][:3]
        shape = ast.get_source_segment(text, statement.value.args[0]) if statement.value.args else "part"
        owner = ast.get_source_segment(text, statement.value.func.value) if isinstance(statement.value.func, ast.Attribute) else "sheet"
        line = (f"{', '.join(targets + ['iso'])} = {owner}.three_views({shape}, iso=True)" if iso
                else f"{', '.join(targets)} = {owner}.three_views({shape})")
        swaps.append((statement.lineno, statement.end_lineno, f"{' ' * statement.col_offset}{line}"))
    for first, last, line in sorted(swaps, reverse=True):
        lines[first - 1:last] = [line]
    made = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    now = read(made)
    said = [f"{key.replace('_', ' ')} {now[key]}" for key in ("size", "scale", *FIELDS) if now[key] != was[key]]
    if now["iso"] != was["iso"]:
        said.append("the isometric drawn" if now["iso"] else "the isometric taken off")
    return made, ", ".join(said) or "nothing"


def build(script: Path, timeout: float = 240.0) -> Path:
    """The drawing's script run, as its ``__main__`` runs it: the PDF it wrote."""
    environment = {**os.environ, "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR") or str(Path(os.environ.get("TMPDIR", "/tmp")) / "cadgen-mpl")}
    try:
        ran = subprocess.run([sys.executable, str(script)], cwd=str(script.parent), capture_output=True, text=True, timeout=timeout,
                             env=environment, check=False)
    except subprocess.TimeoutExpired:
        raise DrawingError("The drawing took too long to draw. Ask the agent to look at it.") from None
    wrote = re.findall(r"^wrote (.+?\.pdf) \(", ran.stdout, flags=re.MULTILINE)
    if ran.returncode != 0 or not wrote:
        last = (ran.stderr or ran.stdout).strip().splitlines()
        raise DrawingError(f"The drawing did not draw: {last[-1] if last else 'it wrote no PDF'}")
    return Path(wrote[-1])
