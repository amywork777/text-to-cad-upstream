"""Edit mode on a file with Windows line endings (CRLF), as git checks one out on Windows: a command,
its undo and a refused line keep the file's own bytes, the editor does not then refuse its own next
edit as a file "changed since the editor read it", and Sizes keeps CRLF too (amywork777/studio#12).

The files are written with CRLF on every OS, so this runs the Windows case on Linux and macOS too.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.packages.cad.test_edit_commands import BLOCK, BLOCK_TOP_EDGES, Commands
from tests.python.packages.cad.test_edit_commands import setUpModule as _engine_of_its_own


def setUpModule():
    _engine_of_its_own()


def crlf_project(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cadgen-edit-crlf-"))
    (root / ".git").mkdir()
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(textwrap.dedent(text).lstrip().replace("\n", "\r\n").encode("utf-8"))
    return root


class WindowsLineEndings(Commands):
    def open_crlf(self, files: dict[str, str], step: str):
        root = crlf_project(files)
        self.addCleanup(shutil.rmtree, root, True)
        file = str(root / step)
        state = self.service.state(file)
        self.assertTrue(state["ok"], state.get("error"))
        return root, file, state

    def assertAllCrlf(self, data: bytes):
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""), data.decode("utf-8"))

    def test_a_command_writes_crlf_and_undo_and_redo_put_back_the_exact_bytes(self):
        root, file, state = self.open_crlf(BLOCK, "block.step")
        script = root / "block.py"
        before = script.read_bytes()
        made = self.command(file, state, "chamfer", BLOCK_TOP_EDGES[:1], {"distance": ".5"})
        self.assertTrue(made["ok"], made.get("error"))
        after = script.read_bytes()
        self.assertIn(b"chamfer(", after)
        self.assertAllCrlf(after)
        undone = self.service.change({"file": file, "splice": made["change"]["undo"], "files": made["files"]})
        self.assertTrue(undone["ok"], undone.get("error"))
        self.assertEqual(script.read_bytes(), before)
        redone = self.service.change({"file": file, "splice": made["change"]["redo"], "files": undone["files"]})
        self.assertTrue(redone["ok"], redone.get("error"))
        self.assertEqual(script.read_bytes(), after)

    def test_a_refused_line_leaves_the_bytes_and_the_next_edit_is_not_refused_as_changed(self):
        root, file, state = self.open_crlf(BLOCK, "block.step")
        script = root / "block.py"
        before = script.read_bytes()
        refused = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "6"})
        self.assertFalse(refused["ok"])
        self.assertIn("smaller radius", refused["error"])
        self.assertEqual(script.read_bytes(), before)
        made = self.command(file, state, "fillet", BLOCK_TOP_EDGES, {"radius": "1"})
        self.assertTrue(made["ok"], made.get("error"))
        self.assertAllCrlf(script.read_bytes())


class SizesOnCrlf(unittest.TestCase):
    """Sizes changes a number and adds a shared size in place, the file's CRLF kept."""

    def test_a_size_changed_and_one_added_keep_crlf(self):
        from unittest import mock

        from cad.edit import sizes

        root = crlf_project({"cad/bracket.py": "from sizes import WALL\n\nWIDTH = 40.0  # across\n\n@model\ndef bracket():\n    return WIDTH\n",
                             "cad/sizes.py": '"""Shared."""\nWALL = 2\n'})
        self.addCleanup(shutil.rmtree, root, True)
        records = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, records, True)
        with mock.patch.dict(os.environ, {"STUDIO_PROJECTS_DIR": records}):
            sizes.set_size(str(root), "cad/bracket.py", "WIDTH", 3, "40.0", "45")
            sizes.add_shared(str(root), "BOLT_D", "3")
        bracket = (root / "cad/bracket.py").read_bytes()
        self.assertIn(b"WIDTH = 45  # across\r\n", bracket)
        self.assertNotIn(b"\n", bracket.replace(b"\r\n", b""))
        self.assertEqual((root / "cad/sizes.py").read_bytes(), b'"""Shared."""\r\nWALL = 2\r\nBOLT_D = 3\r\n')


if __name__ == "__main__":
    unittest.main()
