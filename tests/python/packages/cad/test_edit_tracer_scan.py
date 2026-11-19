"""Which files are the project's own, as the edit tracer judges them (``tracer._inside``), and that it
judges each once.

Each trace asks it of every module loaded (some thousands: build123d, the kernel, numpy...) twice, and
of every frame that makes a build123d operation; the answer resolves the file on disk, which on
Windows opens it. Asked afresh every time, that was most of every request: ~1.5 s each on a Windows
runner, and ``test_edit_commands.py``, 353 requests, ran 290-850 s and into its 600 s per-file guard,
read as a hang. A second scan of the same modules resolves nothing.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class ProjectFiles(unittest.TestCase):
    def setUp(self):
        from cad.edit import tracer

        self.tracer = tracer
        self.root = Path(tempfile.mkdtemp(prefix="cadgen-edit-scan-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("part.py", "lib/helper.py", ".venv/lib/thing.py", "vendor/site-packages/pkg.py"):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text("", encoding="utf-8")
        patch = mock.patch.object(tracer, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_projects_files_are_its_own_and_none_other(self):
        inside = self.tracer._inside
        self.assertTrue(inside(str(self.root / "part.py")))
        self.assertTrue(inside(str(self.root / "lib" / "helper.py")))
        self.assertFalse(inside(str(self.root / ".venv" / "lib" / "thing.py")))
        self.assertFalse(inside(str(self.root / "vendor" / "site-packages" / "pkg.py")))
        self.assertFalse(inside(self.tracer.__file__))
        self.assertFalse(inside(unittest.__file__))
        # Kept by the project too: the same file is no other project's.
        other = Path(tempfile.mkdtemp(prefix="cadgen-edit-scan-other-")).resolve()
        self.addCleanup(shutil.rmtree, other, True)
        with mock.patch.object(self.tracer, "ROOT", other):
            self.assertFalse(inside(str(self.root / "part.py")))
        self.assertTrue(inside(str(self.root / "part.py")))

    def test_a_scan_of_the_loaded_modules_resolves_each_file_once(self):
        files = [module.__file__ for module in list(sys.modules.values()) if getattr(module, "__file__", None)]
        self.assertGreater(len(files), 200)  # the tracer's imports: build123d, the kernel, cadgen
        for path in files:
            self.tracer._inside(path)
        real = os.path.realpath
        with mock.patch("os.path.realpath", side_effect=real) as resolved:
            for path in files:
                self.tracer._inside(path)
        self.assertEqual(resolved.call_count, 0)


if __name__ == "__main__":
    unittest.main()
