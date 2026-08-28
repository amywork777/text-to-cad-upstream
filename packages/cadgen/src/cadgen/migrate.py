"""``python -m cadgen.migrate <file...>`` — the legacy-generator codemod.

Rewrites a retired ``gen_step()``/``gen_dxf()`` magic-name generator into a
library-first model script (design/library-first-generation.md):

1. ``def gen_step():`` becomes a ``@step``-decorated function named after the
   file (``def gen_dxf():`` becomes ``@dxf``); ``from cadgen import step`` is
   added.
2. Top-level ``from build123d import A, B`` / ``import build123d [as x]``
   imports become the lazy idiom ``from cadgen import build123d as bd``, and
   every use of the imported names is rewritten to ``bd.``-attribute style —
   so re-running a current model never pays the ~2.5s kernel import.
3. ``<name>.step.py`` / ``<name>.dxf.py`` files are renamed to plain
   ``<name>.py`` (the suffix convention is retired).

The rewrite is deliberately conservative: files it cannot transform safely are
reported and left untouched. Always verify a migrated model by rebuilding it
and comparing the package's component content hashes against the
pre-migration package — content addressing makes "same geometry" checkable.

stdlib only. Callers own git operations; this edits files in place.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

LEGACY_NAMES = {"gen_step": "step", "gen_dxf": "dxf"}


class MigrationError(RuntimeError):
    pass


def _model_name_for(path: Path) -> str:
    stem = path.name
    for suffix in (".step.py", ".stp.py", ".dxf.py", ".py"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    name = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in stem)
    if not name or name[0].isdigit():
        name = f"model_{name}"
    return name


def _collect_build123d_imports(tree: ast.Module) -> tuple[list[ast.stmt], dict[str, str]]:
    """(import statements to replace, local name -> bd attribute expression)."""
    statements: list[ast.stmt] = []
    renames: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "build123d" and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    raise MigrationError("star import from build123d cannot be migrated mechanically")
                renames[alias.asname or alias.name] = f"bd.{alias.name}"
            statements.append(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "build123d":
                    renames[alias.asname or "build123d"] = "bd"
                    statements.append(node)
                elif alias.name.startswith("build123d."):
                    raise MigrationError(f"import {alias.name} cannot be migrated mechanically")
    return statements, renames


class _NameUses(ast.NodeVisitor):
    """Source spans of every use of the renamed build123d names.

    Scope-naive by design: model scripts that locally shadow a CAD class name
    are rare enough that the hash-verification gate is the honest backstop.
    Excludes attribute names and keywords (only ast.Name loads/stores match).
    """

    def __init__(self, renames: dict[str, str]) -> None:
        self.renames = renames
        self.spans: list[tuple[int, int, int, str]] = []  # line, col, end_col, new

    def visit_Name(self, node: ast.Name) -> None:
        replacement = self.renames.get(node.id)
        if replacement is not None:
            self.spans.append((node.lineno, node.col_offset, node.end_col_offset, replacement))
        self.generic_visit(node)


def migrate_source(text: str, *, model_name: str) -> str:
    tree = ast.parse(text)
    legacy = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LEGACY_NAMES
    ]
    if not legacy:
        raise MigrationError("no gen_step()/gen_dxf() found")
    if len(legacy) > 1:
        raise MigrationError("defines both gen_step() and gen_dxf(); split it first")
    generator = legacy[0]
    decorator = LEGACY_NAMES[generator.name]

    import_statements, renames = _collect_build123d_imports(tree)
    uses = _NameUses(renames)
    # Only rewrite uses OUTSIDE the replaced import statements themselves.
    import_lines = set()
    for statement in import_statements:
        import_lines.update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
    uses.visit(tree)

    lines = text.splitlines(keepends=True)

    def replace_span(line: int, col: int, end_col: int, new: str) -> None:
        row = lines[line - 1]
        lines[line - 1] = row[:col] + new + row[end_col:]

    # Apply name rewrites bottom-up so earlier offsets stay valid.
    for line, col, end_col, new in sorted(uses.spans, reverse=True):
        if line in import_lines:
            continue
        replace_span(line, col, end_col, new)

    # Replace the build123d import statements (first becomes the bd idiom).
    replaced_first = False
    for statement in sorted(import_statements, key=lambda s: s.lineno, reverse=True):
        start, end = statement.lineno - 1, (statement.end_lineno or statement.lineno) - 1
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        replacement_lines = []
        if not replaced_first:
            replacement_lines = [f"{indent}from cadgen import build123d as bd\n"]
            replaced_first = True
        lines[start : end + 1] = replacement_lines

    # Rename the generator and decorate it (re-locate after the line surgery).
    renamed = False
    for index, row in enumerate(lines):
        stripped = row.lstrip()
        if stripped.startswith(f"def {generator.name}("):
            indent = row[: len(row) - len(stripped)]
            lines[index] = row.replace(f"def {generator.name}(", f"def {model_name}(", 1)
            lines.insert(index, f"{indent}@{decorator}\n")
            renamed = True
            break
    if not renamed:
        raise MigrationError(f"could not locate def {generator.name}( for rewrite")

    # Rewrite internal references to the old name (composition callers do this
    # across modules too — those are their own migrations).
    body = "".join(lines)
    body = body.replace(f"{generator.name}()", f"{model_name}()")

    # Imports for the decorator, after __future__ if present.
    import_line = f"from cadgen import {decorator}\n"
    if import_line not in body:
        out = body.splitlines(keepends=True)
        insert_at = 0
        for index, row in enumerate(out):
            if row.startswith("from __future__"):
                insert_at = index + 1
        out.insert(insert_at, import_line)
        body = "".join(out)

    ast.parse(body)  # the rewrite must at least still parse
    return body


def migrate_file(path: Path, *, rename: bool = True) -> Path:
    resolved = path.resolve()
    model_name = _model_name_for(resolved)
    migrated = migrate_source(resolved.read_text(), model_name=model_name)
    target = resolved
    lowered = resolved.name.lower()
    if rename:
        for suffix in (".step.py", ".stp.py", ".dxf.py"):
            if lowered.endswith(suffix):
                target = resolved.with_name(resolved.name[: -len(suffix)] + ".py")
                if target.exists():
                    raise MigrationError(f"rename target already exists: {target}")
                break
    target.write_text(migrated)
    if target != resolved:
        resolved.unlink()
    return target


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    rename = True
    if "--no-rename" in arguments:
        rename = False
        arguments.remove("--no-rename")
    if not arguments or any(argument.startswith("-") for argument in arguments):
        print("usage: python -m cadgen.migrate [--no-rename] <legacy-generator.py> ...", file=sys.stderr)
        return 2
    failures = 0
    for argument in arguments:
        path = Path(argument)
        try:
            target = migrate_file(path, rename=rename)
        except (OSError, SyntaxError, MigrationError) as exc:
            failures += 1
            print(f"SKIP {path}: {exc}", file=sys.stderr)
            continue
        print(f"migrated {path} -> {target}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
