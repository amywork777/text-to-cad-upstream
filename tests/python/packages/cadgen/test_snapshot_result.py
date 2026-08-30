"""Snapshot's answer is a Result dataclass, like every other cadgen verb.

Snapshot used to hand its caller the BROWSER's return value: base64 image bytes,
viewport internals, an echoed job. `--json` was that dict with the known payload
keys filtered out, the human output was three hand-written branches, and a
Python caller had no way in at all — there was a CLI and no function.

So these cover the boundary rather than the rendering: what a SnapshotResult
carries, what `dataclasses.asdict` of it looks like on stdout, and that the
public `<format>.snapshot()` verbs exist and are the same shape. Nothing here
starts a browser.
"""

from __future__ import annotations

import io
import json
import unittest
from dataclasses import fields
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen._internal.cli_from_function import emit, result_payload  # noqa: E402
from cadgen.results import SnapshotFile, SnapshotResult, SnapshotTimings  # noqa: E402
from cadgen.snapshot_core import snapshot_result  # noqa: E402

VIEW_RESULT = {
    "ok": True,
    "mode": "view",
    "projection": "orthographic",
    "outputs": [
        {
            "path": "/tmp/review.png",
            "camera": "ISO",
            "width": 1600,
            "height": 1200,
            "mimeType": "image/png",
            "dataUrl": "data:image/png;base64,AAAA",
        }
    ],
    "warnings": ["one part had no material"],
    "timings": {"sceneBuildMs": 12.0, "renderMs": 30.0},
}


class ResultShape(unittest.TestCase):
    def test_one_file_per_written_output(self) -> None:
        result = snapshot_result(VIEW_RESULT, total_ms=42.0)
        self.assertTrue(result.ok)
        self.assertEqual([str(f.path) for f in result.files], ["/tmp/review.png"])
        self.assertEqual(result.files[0].kind, "png")
        self.assertEqual(result.files[0].view, "ISO")
        self.assertEqual(result.warnings, ("one part had no material",))
        self.assertEqual(result.timings, SnapshotTimings(job_count=1, total_ms=42.0))

    def test_the_encoding_follows_the_render_not_the_filename(self) -> None:
        """An orbit named `.png` still holds GIF bytes: the renderer's mime type
        is what actually happened, so it wins over the suffix."""
        orbit = {
            "ok": True,
            "mode": "orbit",
            "outputs": [{"path": "/tmp/turntable.png", "mimeType": "image/gif"}],
        }
        self.assertEqual(snapshot_result(orbit).files[0].kind, "gif")

    def test_a_path_less_output_is_not_a_file(self) -> None:
        # An animation's frame outputs carry no path; only what was WRITTEN counts.
        payload = {"ok": True, "outputs": [{"path": "", "mimeType": "image/png"}]}
        self.assertEqual(snapshot_result(payload).files, ())

    def test_a_multi_job_packet_flattens_into_one_answer(self) -> None:
        packet = {
            "ok": True,
            "jobs": [
                {"ok": True, "outputs": [{"path": "/tmp/a.png", "mimeType": "image/png"}]},
                {
                    "ok": True,
                    "outputs": [{"path": "/tmp/b.png", "mimeType": "image/png"}],
                    "warnings": ["clamped"],
                },
            ],
        }
        result = snapshot_result(packet, total_ms=5.0)
        self.assertEqual([str(f.path) for f in result.files], ["/tmp/a.png", "/tmp/b.png"])
        self.assertEqual(result.warnings, ("clamped",))
        self.assertEqual(result.timings.job_count, 2)

    def test_one_failed_job_fails_the_packet(self) -> None:
        packet = {"ok": True, "jobs": [{"ok": True, "outputs": []}, {"ok": False}]}
        self.assertFalse(snapshot_result(packet).ok)

    def test_list_mode_answers_with_parts_and_no_files(self) -> None:
        listing = {
            "ok": True,
            "mode": "list",
            "parts": [{"ref": "#o1.1", "name": "plate", "triangleCount": 12}],
        }
        result = snapshot_result(listing)
        self.assertEqual(result.files, ())
        self.assertEqual(result.parts[0]["ref"], "#o1.1")

    def test_an_empty_inventory_still_prints_itself(self) -> None:
        # List mode with zero parts answers `[]`, not silence.
        listing = {"ok": True, "mode": "list", "parts": []}
        self.assertEqual(snapshot_result(listing).human_lines(), ["[]"])


class JsonShape(unittest.TestCase):
    """`--json` IS `dataclasses.asdict`, so the shape is the dataclass."""

    def test_the_payload_is_exactly_the_dataclass_fields(self) -> None:
        payload = result_payload(snapshot_result(VIEW_RESULT, total_ms=42.0))
        self.assertEqual(
            sorted(payload), sorted(field.name for field in fields(SnapshotResult))
        )
        self.assertEqual(
            payload["files"],
            [{"path": "/tmp/review.png", "kind": "png", "view": "ISO"}],
        )
        self.assertEqual(payload["timings"], {"job_count": 1, "total_ms": 42.0})
        self.assertEqual(payload["parts"], [])
        self.assertEqual(payload["debug"], [])
        self.assertIs(payload["ok"], True)

    def test_no_browser_internals_survive_into_the_payload(self) -> None:
        # The dataclass has no field for them, so this cannot be forgotten the way
        # a filter over the browser dict could.
        printed = json.dumps(result_payload(snapshot_result(VIEW_RESULT)))
        for internal in ("dataUrl", "mimeType", "projection", "sceneBuildMs", "width"):
            self.assertNotIn(internal, printed)

    def test_the_cli_prints_one_compact_json_line(self) -> None:
        stdout = io.StringIO()
        code = emit(
            lambda: snapshot_result(VIEW_RESULT, total_ms=42.0),
            prog="cadgen step snapshot",
            as_json=True,
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        printed = stdout.getvalue()
        self.assertEqual(len(printed.strip().splitlines()), 1)
        self.assertNotIn(", ", printed)  # compact separators
        self.assertEqual(json.loads(printed)["files"][0]["path"], "/tmp/review.png")

    def test_the_human_form_names_the_paths_and_the_warnings(self) -> None:
        stdout = io.StringIO()
        emit(
            lambda: snapshot_result(VIEW_RESULT),
            prog="cadgen step snapshot",
            as_json=False,
            stdout=stdout,
        )
        self.assertEqual(
            stdout.getvalue().splitlines(),
            ["saved snapshot: /tmp/review.png", "warning: one part had no material"],
        )

    def test_list_mode_prints_the_inventory_and_nothing_else(self) -> None:
        listing = {"ok": True, "mode": "list", "parts": [{"ref": "#o1.1", "name": "plate"}]}
        stdout = io.StringIO()
        emit(
            lambda: snapshot_result(listing),
            prog="cadgen step snapshot",
            as_json=False,
            stdout=stdout,
        )
        self.assertEqual(
            json.loads(stdout.getvalue()), [{"ref": "#o1.1", "name": "plate"}]
        )

    def test_a_failure_is_the_schema_error_line(self) -> None:
        stdout = io.StringIO()
        code = emit(
            lambda: (_ for _ in ()).throw(RuntimeError("browser blew up")),
            prog="cadgen step snapshot",
            as_json=True,
            stdout=stdout,
        )
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(stdout.getvalue()), {"ok": False, "error": "browser blew up"}
        )

    def test_a_not_ok_result_exits_nonzero(self) -> None:
        code = emit(
            lambda: SnapshotResult(ok=False, files=(SnapshotFile(Path("/tmp/x.png"), "png"),)),
            prog="cadgen step snapshot",
            as_json=True,
            stdout=io.StringIO(),
        )
        self.assertEqual(code, 1)


class PublicVerbs(unittest.TestCase):
    """Every snapshot door has a FUNCTION as well as a command."""

    DOORS = ("step", "stl", "threemf", "glb", "dxf", "urdf", "sdf")

    def test_each_door_exports_a_snapshot_verb(self) -> None:
        import importlib

        for door in self.DOORS:
            with self.subTest(door=door):
                module = importlib.import_module(f"cadgen.{door}")
                self.assertIn("snapshot", module.__all__)
                self.assertTrue(callable(module.snapshot))

    def test_the_verbs_are_one_signature_not_seven_copies(self) -> None:
        import importlib
        import inspect as inspect_module

        signatures = {
            str(inspect_module.signature(importlib.import_module(f"cadgen.{door}").snapshot))
            for door in self.DOORS
        }
        self.assertEqual(len(signatures), 1, signatures)

    def test_a_verb_refuses_a_format_that_is_not_its_door(self) -> None:
        import tempfile

        from cadgen import stl

        with tempfile.TemporaryDirectory() as tmp:
            step_path = Path(tmp) / "part.step"
            step_path.write_text("ISO-10303-21;\n", encoding="utf-8")
            with self.assertRaises(Exception) as ctx:
                stl.snapshot(step_path, Path(tmp) / "out.png")
            self.assertIn("does not render", str(ctx.exception))

    def test_a_verb_with_no_target_says_so_rather_than_reading_stdin(self) -> None:
        from cadgen import step

        with self.assertRaises(Exception) as ctx:
            step.snapshot()
        self.assertIn("requires", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
