"""The dxf skill's documentation is executed, not just proofread.

A skill is consumed by an agent that copies what it reads. Documentation that
has drifted from the contract is therefore not a cosmetic problem: it is a
generator of broken drawings, and the drift is invisible to every other test in
the suite. So the code blocks in `skills/dxf/SKILL.md` and
`skills/dxf/references/generator-templates.md` are extracted and RUN here, and
the CLI forms those files document are run too.

Blocks fall into two kinds and are checked accordingly:

* **complete models** — every import present, no ``<placeholder>`` — are written
  to a temp project and built, and must produce a `.dxf` the drawing checks pass.
* **fragments and templates** — a bracket's multi-plane selection, a workflow
  skeleton with TODO markers — cannot run, so they are parsed and required to
  declare a ``@dxf`` entry. Syntax and contract shape, which is what a reader
  copies out of them.

Also pinned here: the retired-contract teaching error points at `SKILL.md`, so
`SKILL.md` must teach the contract that replaced it and not the one it removed.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path, repo_path

CADGEN_SRC = add_repo_path("packages/cadgen/src")

SKILL = repo_path("skills/dxf/SKILL.md")
TEMPLATES = repo_path("skills/dxf/references/generator-templates.md")
PROJECT_TEMPLATE = repo_path("skills/cad-project/references/project-template.md")
EXEMPLAR_DRAWING = repo_path("models/projects/demo-plate/src/plate_drawing.py")

_PYTHON_BLOCK = re.compile(r"```python\n(.*?)```", re.S)
# A model the reader could paste somewhere else needs this to exist first.
_BRACKET_MODEL = '''from cadgen import build123d as bd
from cadgen import step


@step(kind="part")
def bracket(thickness: float = 3.0):
    with bd.BuildSketch() as profile:
        bd.Rectangle(40, 25)
        with bd.Locations((-14, 0), (14, 0)):
            bd.Circle(2.5, mode=bd.Mode.SUBTRACT)
    return bd.extrude(profile.sketch, amount=thickness)
'''


def _python_blocks(path: Path) -> list[str]:
    # Dedented: a block nested inside a numbered list is indented in the source,
    # and a reader copying it out un-indents it without thinking about it.
    return [textwrap.dedent(block) for block in _PYTHON_BLOCK.findall(path.read_text(encoding="utf-8"))]


_PLACEHOLDER = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")


def _fill_placeholders(source: str) -> str:
    """`<name>` markers become a valid identifier so a template still PARSES.

    Substituting rather than skipping: the structure a reader copies out of a
    template is exactly what should be checked, and `<name>` is the only thing
    stopping it from being Python.
    """
    return _PLACEHOLDER.sub(lambda match: f"{match.group(1)}_here", source)


def _declares_a_dxf_model(source: str) -> bool:
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.FunctionDef)
        and any(
            (isinstance(d, ast.Name) and d.id == "dxf")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dxf")
            or (isinstance(d, ast.Attribute) and d.attr == "dxf")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "dxf")
            for d in node.decorator_list
        )
        for node in ast.walk(tree)
    )


def _is_runnable_model(source: str) -> bool:
    if "<" in source and ">" in source:  # a template's <name> markers
        return False
    if "@dxf" not in source or "from cadgen import" not in source:
        return False
    return "def " in source


class _DrawingHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dxf-docs-")
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name).resolve()
        (self.project / "bracket.py").write_text(_BRACKET_MODEL, encoding="utf-8")
        self.environment = dict(os.environ)
        self.environment.update(
            {
                # A warm worker would serve another checkout's code.
                "CADGEN_DAEMON": "0",
                "CADGEN_COMPONENT_WORKERS": "1",
                "CADGEN_CACHE_DIR": str(self.project / "store"),
                "PYTHONPATH": str(CADGEN_SRC),
            }
        )

    def run_drawing(self, *argv: str, expect_success: bool = True) -> subprocess.CompletedProcess:
        completed = subprocess.run(
            [sys.executable, *argv],
            cwd=str(self.project),
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if expect_success:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed


class DocumentedModelsBuild(_DrawingHarness):
    def test_every_complete_documented_model_builds(self) -> None:
        sources = [
            (path.name, index, block)
            for path in (SKILL, TEMPLATES)
            for index, block in enumerate(_python_blocks(path))
            if _is_runnable_model(block)
        ]
        self.assertGreaterEqual(len(sources), 3, "the docs should carry runnable examples")
        for name, index, block in sources:
            with self.subTest(document=name, block=index):
                model = self.project / f"documented_{name.replace('.', '_')}_{index}.py"
                model.write_text(block, encoding="utf-8")
                self.run_drawing(model.name)
                drawing = model.with_suffix(".dxf")
                self.assertTrue(drawing.is_file(), f"{model.name} wrote no drawing")
                self.assertGreater(drawing.stat().st_size, 0)

    def test_templates_and_fragments_parse_and_declare_a_dxf_entry(self) -> None:
        blocks = [
            block
            for block in _python_blocks(TEMPLATES)
            if "@dxf" in block and not _is_runnable_model(block)
        ]
        self.assertGreaterEqual(len(blocks), 2, "the templates should carry skeletons too")
        for index, block in enumerate(blocks):
            with self.subTest(block=index):
                filled = _fill_placeholders(block)
                ast.parse(filled)  # a template a reader copies must at least be Python
                self.assertTrue(_declares_a_dxf_model(filled))


class DocumentedCommandForms(_DrawingHarness):
    """Each command form SKILL.md documents, actually run."""

    DRAWING = textwrap.dedent(
        """\
        from cadgen import build123d as bd
        from cadgen import dxf


        @dxf
        def gasket(hole_d: float = 4.5):
            with bd.BuildSketch() as cut:
                bd.Rectangle(60, 40)
                bd.Circle(hole_d / 2, mode=bd.Mode.SUBTRACT)
            return cut.sketch
        """
    )

    def setUp(self) -> None:
        super().setUp()
        (self.project / "gasket.py").write_text(self.DRAWING, encoding="utf-8")
        (self.project / "panel.py").write_text(
            self.DRAWING.replace("def gasket", "def panel"), encoding="utf-8"
        )

    def test_a_bare_run_writes_the_sibling(self) -> None:
        self.run_drawing("gasket.py")
        self.assertTrue((self.project / "gasket.dxf").is_file())

    def test_an_unchanged_source_is_a_no_op(self) -> None:
        self.run_drawing("gasket.py")
        before = (self.project / "gasket.dxf").stat().st_mtime_ns
        self.run_drawing("gasket.py")
        self.assertEqual(before, (self.project / "gasket.dxf").stat().st_mtime_ns)

    def test_force_rebuilds_to_identical_bytes(self) -> None:
        self.run_drawing("gasket.py")
        first = (self.project / "gasket.dxf").read_bytes()
        self.run_drawing("gasket.py", "--force")
        self.assertEqual(first, (self.project / "gasket.dxf").read_bytes())

    def test_output_flag_renames_the_drawing(self) -> None:
        self.run_drawing("gasket.py", "-o", "out/custom.dxf")
        self.assertTrue((self.project / "out" / "custom.dxf").is_file())

    def test_the_named_door_builds_the_same_file_as_the_script_door(self) -> None:
        """`cadgen dxf build` and `python drawing.py` are one build, two doors.

        Documented as identical, so the drawings they write must actually be
        byte-identical — the property that would quietly break if either door
        acquired its own serialization path.
        """
        self.run_drawing("gasket.py")
        by_script = (self.project / "gasket.dxf").read_bytes()
        (self.project / "gasket.dxf").unlink()
        self.run_drawing("-m", "cadgen.cli", "dxf", "build", "gasket.py")
        self.assertEqual(by_script, (self.project / "gasket.dxf").read_bytes())

    def test_no_undocumented_or_missing_flags(self) -> None:
        """SKILL.md's flag list is what the parser accepts, exactly.

        Caught the drift this test was written for: the skill still advertised
        `--validate` and `SOURCE.py=OUTPUT.dxf` pairs, both of which belonged to
        the retired `dxf gen` CLI and had been failing with argparse's usage
        message since generation moved into the decorator.
        """
        usage = self.run_drawing("gasket.py", "--help").stdout
        documented = set(re.findall(r"`(--[a-z-]+)", SKILL.read_text(encoding="utf-8")))
        model_flags = {flag for flag in documented if flag in {"--force", "--verbose", "--json", "--lock-timeout"}}
        for flag in model_flags:
            self.assertIn(flag, usage, f"SKILL.md documents {flag}, the parser does not accept it")
        for retired in ("--validate",):
            self.assertNotIn(retired, usage)
            self.assertNotIn(f"`{retired}`", SKILL.read_text(encoding="utf-8"))

    def test_post_hoc_validation_runs_the_documented_way(self) -> None:
        self.run_drawing("gasket.py")
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys\n"
                "from cadgen.drawing_checks import validate_dxf_file\n"
                "print([f.render() for f in validate_dxf_file(sys.argv[1])])",
                str(self.project / "gasket.dxf"),
            ],
            cwd=str(self.project),
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "[]", "a generated drawing must validate clean")

    def test_the_retired_contract_fails_and_says_what_to_do(self) -> None:
        (self.project / "legacy.py").write_text(
            textwrap.dedent(
                """\
                import ezdxf

                from cadgen import dxf


                @dxf
                def legacy():
                    document = ezdxf.new()
                    document.modelspace().add_circle((0, 0), 5)
                    return {"document": document}
                """
            ),
            encoding="utf-8",
        )
        completed = self.run_drawing("legacy.py", expect_success=False)
        self.assertNotEqual(completed.returncode, 0)
        output = completed.stdout + completed.stderr
        self.assertIn("That contract is removed", output)
        self.assertIn("skills/dxf/SKILL.md", output)
        self.assertFalse((self.project / "legacy.dxf").exists())


class DocumentationTeachesTheNewContract(unittest.TestCase):
    def test_the_skill_teaches_the_current_return_contract(self) -> None:
        """The teaching error sends authors HERE, so this file has to answer."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("returns build123d 2D geometry", text)
        self.assertIn("read_step", text)
        self.assertNotIn('{"document"', text)
        self.assertNotIn("ezdxf.new(", text)

    def test_the_templates_teach_the_current_return_contract(self) -> None:
        text = TEMPLATES.read_text(encoding="utf-8")
        self.assertNotIn('{"document"', text)
        self.assertNotIn("ezdxf.new(", text)
        self.assertNotIn("union_projected_faces", text)
        self.assertNotIn("add_shapely_geometry", text)

    def test_the_skill_teaches_the_exact_snapshot_output_rule(self) -> None:
        """The snapshot section's whole job here is the output contract.

        A drawing review is render -> Read -> edit -> render, and the reader needs
        to know that the second render replaces the file the first one wrote. The
        section used to have to teach the opposite (the written name was not the
        name passed), so this pins the replacement rather than leaving the section
        free to drift back into teaching what to KNOW instead of what to do.
        """
        text = SKILL.read_text(encoding="utf-8")
        snapshot_section = text[text.index("cadgen dxf snapshot` renders") :]
        self.assertIn("written exactly as given", snapshot_section)
        self.assertIn("current working directory", snapshot_section)
        self.assertIn("missing file", snapshot_section)
        # The generate-a-name case is the only surviving read-the-printed-path case.
        self.assertIn("--output tmp/", snapshot_section)

    def test_documented_snapshot_forms_name_a_file(self) -> None:
        """`cadgen dxf snapshot --input X --output Y` — the Y in every documented
        form is a file the reader can open by that name afterwards."""
        forms = [
            line.strip()
            for line in SKILL.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("cadgen dxf snapshot") and "--output" in line
        ]
        self.assertGreaterEqual(len(forms), 2)
        for form in forms:
            with self.subTest(form=form):
                tokens = form.split()
                value = tokens[tokens.index("--output") + 1]
                self.assertTrue(Path(value).suffix, f"`--output {value}` names no file")
                self.assertFalse(value.endswith(("/", "\\")))

    def test_the_project_template_matches_its_exemplar(self) -> None:
        """cad-project's template and models/projects/demo-plate are the same
        drawing shown twice; a reader who copies one and inspects the other must
        not find two different contracts."""
        block = re.search(
            r"## `src/plate_drawing\.py`\n\n```python\n(.*?)```",
            PROJECT_TEMPLATE.read_text(encoding="utf-8"),
            re.S,
        )
        self.assertIsNotNone(block, "the template lost its drawing example")
        self.assertEqual(
            block.group(1).strip(),
            EXEMPLAR_DRAWING.read_text(encoding="utf-8").strip(),
        )


if __name__ == "__main__":
    unittest.main()
