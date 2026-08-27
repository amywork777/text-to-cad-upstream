"""--write behavior: closure-keyed reuse, new-path copy, metadata injection
via the writer's entity-count hint, and the verbose export spans (which were
once silently orphaned — design/FEEDBACK.md item 9)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

VENV = "/Users/jakefitzgerald/robots/text-to-cad/.venv/bin/python"
REPO = Path(__file__).resolve().parents[4]


def _write_model(root: Path) -> Path:
    entry = root / "block.step.py"
    entry.write_text(textwrap.dedent("""\
        SIZE = 6.0

        def gen_step():
            from build123d.topology import Solid
            block = Solid.make_box(SIZE, SIZE, SIZE)
            block.label = "block"
            return block
        """))
    return entry


def _run(entry: Path, args: list[str], store: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "CADGEN_WARM": "0",
        "CADGEN_COMPONENT_WORKERS": "1",
        "CADGEN_STORE_DIR": str(store),
        "PYTHONPATH": str(REPO / "packages/cadgen/src"),
    })
    code = (
        "import sys\nfrom cadgen.cli import step_gen\n"
        f"sys.exit(step_gen.main({[entry.name, *args]!r}))"
    )
    return subprocess.run([VENV, "-c", code], cwd=str(entry.parent), env=env,
                          capture_output=True, text=True, timeout=600)


class StepExportReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        model_dir = root / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        self.entry = _write_model(model_dir)
        self.store = root / "store"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_repeat_write_reuses_and_edit_invalidates(self) -> None:
        first = _run(self.entry, ["--write"], self.store)
        self.assertEqual(first.returncode, 0, first.stderr[-1500:])
        step = self.entry.parent / "block.step"
        self.assertTrue(step.is_file())
        original = hashlib.sha256(step.read_bytes()).hexdigest()

        repeat = _run(self.entry, ["--write"], self.store)
        self.assertEqual(repeat.returncode, 0, repeat.stderr[-1500:])
        self.assertIn("step export is current; reusing", repeat.stderr)
        self.assertEqual(hashlib.sha256(step.read_bytes()).hexdigest(), original)

        self.entry.write_text(self.entry.read_text().replace("SIZE = 6.0", "SIZE = 7.0"))
        edited = _run(self.entry, ["--write"], self.store)
        self.assertEqual(edited.returncode, 0, edited.stderr[-1500:])
        self.assertNotIn("step export is current", edited.stderr)
        self.assertNotEqual(hashlib.sha256(step.read_bytes()).hexdigest(), original)

    def test_new_path_export_copies_verified_bytes(self) -> None:
        _run(self.entry, ["--write"], self.store)
        step = self.entry.parent / "block.step"
        copy_target = self.entry.parent / "elsewhere" / "block_copy.step"
        copied = _run(self.entry, ["--write", str(copy_target)], self.store)
        self.assertEqual(copied.returncode, 0, copied.stderr[-1500:])
        self.assertIn("step export is current; reusing", copied.stderr)
        self.assertEqual(step.read_bytes(), copy_target.read_bytes())

    def test_verbose_export_spans_fire_and_metadata_reads_back(self) -> None:
        run = _run(self.entry, ["--write", "--verbose"], self.store)
        self.assertEqual(run.returncode, 0, run.stderr[-1500:])
        for span in ("transfer XCAF to STEP model", "write STEP file",
                     "inject STEP metadata"):
            self.assertIn(span, run.stderr,
                          f"orphaned --verbose span: {span!r}")
        from cadgen._internal.step_metadata import read_text_to_cad_step_metadata

        metadata = read_text_to_cad_step_metadata(self.entry.parent / "block.step")
        self.assertEqual(metadata.get("entryKind"), "part")
        self.assertEqual(metadata.get("sourcePath"), "block.step.py")


if __name__ == "__main__":
    unittest.main()
