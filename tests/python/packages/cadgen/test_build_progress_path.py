"""Build coordination is keyed by the MODEL path, and readers can find it.

Locks and progress records live under the cache root's ``locks/`` tier, named by
``cadgen.catalog.coordination_scope`` (a hash of the model's resolved path). They can NOT
be keyed by the render package dir, which is content-addressed: a rebuild changes the
document's bytes and therefore its key mid-build, so a package-keyed lock is taken on an
identity the run abandons, and no reader could know the new key in advance.

The viewer's build badge is the reader that pays for a mismatch. When
``cadgen step compile`` published to ``packages/<content hash>`` while the viewer polled
``locks/<path key>``, nothing errored anywhere: the record was written, the poll found
nothing, and the overlay showed an indeterminate "Loading" bar with no phase and no
counts for the whole import.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CADGEN_PACKAGE = _REPO_ROOT / "packages" / "cadgen" / "src" / "cadgen"

# The progress-publishing entry points. Their second positional argument is the
# coordination scope, which is what both the lock and the status record are derived from.
_COORDINATION_ENTRY_POINTS = {"artifact_build", "generator_busy"}


def _coordination_scope_arguments() -> list[tuple[str, int, str]]:
    """Every ``(file, line, source)`` coordination-scope argument in cadgen."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(_CADGEN_PACKAGE.rglob("*.py")):
        if path.parent.name == "coordination":
            continue  # the primitive's own definitions and tests of them
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name not in _COORDINATION_ENTRY_POINTS or len(node.args) < 2:
                continue
            scope = node.args[1]
            found.append((
                str(path.relative_to(_REPO_ROOT)),
                scope.lineno,
                ast.get_source_segment(source, scope) or "",
            ))
    return found


class CoordinationKeyingTest(unittest.TestCase):
    def test_no_producer_coordinates_by_the_content_keyed_package_dir(self) -> None:
        arguments = _coordination_scope_arguments()
        self.assertGreaterEqual(
            len(arguments), 4, "the AST walk found no coordination call sites — it has drifted"
        )
        offenders = [
            f"{path}:{line}: {segment}"
            for path, line, segment in arguments
            if "render_package_dir" in segment
        ]
        self.assertEqual(
            [],
            offenders,
            "a build is coordinating by its render package dir, which is keyed by the "
            "document's CONTENT hash. Use cadgen.catalog.coordination_scope(entry_path): "
            "a rebuild changes the content key mid-build, so peers do not exclude each "
            "other and the viewer — which derives the record from the model path it is "
            "polling — never finds the progress record.\n" + "\n".join(offenders),
        )

    def test_every_producer_derives_its_scope_from_coordination_scope(self) -> None:
        # The positive half: not merely "not the package dir" but the ONE derivation.
        # `output_dir` names generation.py's local, itself assigned from
        # generation_runner._spec_output_dir, which is coordination_scope.
        allowed = {"coordination_scope", "output_dir", "scope"}
        for path, line, segment in _coordination_scope_arguments():
            self.assertTrue(
                any(token in segment for token in allowed),
                f"{path}:{line} coordinates on {segment!r}, which is not derived from "
                "cadgen.catalog.coordination_scope",
            )


class ImportProgressRecordTest(unittest.TestCase):
    """End to end for the user-visible path: the viewer asks cadgen to import a foreign
    STEP, and must be able to watch it happen."""

    def _foreign_step(self, directory: Path) -> Path:
        from build123d import Box, export_step

        step_path = directory / "widget.step"
        export_step(Box(12.0, 8.0, 4.0), str(step_path))
        return step_path

    def test_a_compile_publishes_progress_where_the_viewer_polls(self) -> None:
        from cadgen.catalog import coordination_scope
        from cadgen.coordination.paths import status_path

        with tempfile.TemporaryDirectory(prefix="cadprog-") as workspace:
            root = Path(workspace)
            cache_dir = root / "store"
            step_path = self._foreign_step(root)

            env = dict(os.environ)
            env["CADGEN_CACHE_DIR"] = str(cache_dir)
            # No warm daemon: the record must be published by the build itself.
            env["CADGEN_DAEMON"] = "0"
            result = subprocess.run(
                [sys.executable, "-m", "cadgen.cli", "step", "compile", str(step_path)],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            self.assertEqual(0, result.returncode, f"compile failed:\n{result.stdout}\n{result.stderr}")

            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(cache_dir)}):
                expected = status_path(coordination_scope(step_path))
            self.assertTrue(
                expected.is_file(),
                f"the import published no progress record at {expected}, the ONLY place "
                "the viewer's buildProgressSnapshot looks. Records found instead: "
                f"{[str(p) for p in cache_dir.rglob('*.generation.progress.json')]}",
            )
            # And nowhere else: a record in the packages/ tier is the content-keyed
            # producer this test exists to keep retired.
            stray = [
                str(p.relative_to(cache_dir))
                for p in cache_dir.rglob("*.generation.progress.json")
                if p != expected
            ]
            self.assertEqual([], stray, f"progress records outside the locks/ tier: {stray}")


if __name__ == "__main__":
    unittest.main()
