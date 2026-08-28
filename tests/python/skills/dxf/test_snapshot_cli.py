import importlib.util
import subprocess
import sys
import unittest

from cadgen.assets import browser_runtime_dir
from pathlib import Path
from unittest import mock

from tests.python.support.paths import add_repo_path, repo_path

add_repo_path("skills/dxf/scripts")
add_repo_path("packages/cadgen/src")

# The CLI is shared (cadgen.snapshot_cli); this skill's entrypoint declares that it accepts
# drawings and where its runtime lives. What is DXF-specific -- resolving a .dxf or a
# gen_dxf() source to its built package -- is what these tests cover.
import cadgen.snapshot_cli as snapshot

# Loaded BY PATH, not by module name: every skill names its entry package `snapshot`, so
# `import snapshot.__main__` resolves to whichever skill's scripts dir landed on sys.path
# first. With the CAD snapshot tests in the same process that is CAD's, and this test then
# silently asserts against the wrong skill's kinds.
_dxf_entry_spec = importlib.util.spec_from_file_location(
    "dxf_skill_snapshot_entry",
    Path(repo_path("skills/dxf/scripts/snapshot/__main__.py")),
)
dxf_snapshot_entry = importlib.util.module_from_spec(_dxf_entry_spec)
_dxf_entry_spec.loader.exec_module(dxf_snapshot_entry)


class DxfSnapshotCliTests(unittest.TestCase):
    """A drawing snapshot is an on-demand mesh of the .dxf, then a mesh render.

    The render half is shared with the CAD skill; what is DXF-specific — meshing
    the drawing through the bundled dxf-mesh.mjs one-shot (no package, matching
    the viewer's client-side parse) — is what these tests cover.
    """

    def test_meshes_the_dxf_on_demand(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dxf = Path(tmp) / "x.dxf"
            dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")

            def fake_run(cmd, **kwargs):
                out = Path(cmd[cmd.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"glTF")
                return mock.Mock(returncode=0, stdout='{"ok": true, "path": "%s"}' % out, stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                resolved = snapshot.drawing_mesh_path(dxf, force=False)
            self.assertTrue(str(resolved).endswith(".glb"))
            self.assertTrue(resolved.is_file())

    def test_a_generator_is_made_current_first_and_force_reaches_gen(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            py = Path(tmp) / "x.dxf.py"
            py.write_text("def gen_dxf():\n    raise NotImplementedError\n")
            sibling = Path(tmp) / "x.dxf"

            def fake_gen(source, *, force=False):
                fake_gen.forced = force
                sibling.write_text("0\nEOF\n")
                return sibling

            def fake_run(cmd, **kwargs):
                out = Path(cmd[cmd.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"glTF")
                return mock.Mock(returncode=0, stdout='{"ok": true}', stderr="")

            with mock.patch.object(snapshot, "generate_dxf_for_snapshot", side_effect=fake_gen) as gen:
                with mock.patch("subprocess.run", side_effect=fake_run):
                    snapshot.drawing_mesh_path(py, force=True)
            self.assertTrue(gen.call_args.kwargs["force"])

    def test_a_mesh_failure_is_an_error_not_a_blank_image(self) -> None:
        # The one-shot's error (a drawing with nothing renderable at all —
        # dimensioned drawings render as line work since FEEDBACK 14) is relayed
        # verbatim instead of rendering nothing.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dxf = Path(tmp) / "x.dxf"
            dxf.write_text("0\nEOF\n")
            failed = mock.Mock(returncode=1, stdout='{"ok": false, "error": "no cut geometry"}', stderr="")
            with mock.patch("subprocess.run", return_value=failed):
                with self.assertRaisesRegex(snapshot.SnapshotError, "no cut geometry"):
                    snapshot.drawing_mesh_path(dxf, force=False)

    def test_rejects_a_non_drawing_input(self) -> None:
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.drawing_mesh_path(Path("/models/part.step"), force=False)

    def test_reports_a_missing_input(self) -> None:
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.drawing_mesh_path(Path("/models/definitely-absent.dxf"), force=False)

    def test_section_mode_is_rejected_for_a_drawing(self) -> None:
        # Drawings have no CAD topology, so section has nothing to work with. The shared
        # CLI accepts the flag for every skill and refuses it per KIND at resolve time,
        # which is what keeps the message specific instead of "invalid choice".
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a.dxf").write_text("0\nSECTION\n", encoding="utf-8")
            with self.assertRaisesRegex(snapshot.SnapshotError, "section mode requires STEP topology"):
                snapshot.resolve_render_job_packet(
                    {"input": "a.dxf", "mode": "section", "outputs": [{"path": "a.png"}]},
                    cwd=root,
                    kinds=snapshot.enabled_kinds(dxf_snapshot_entry.KINDS),
                )

    def test_scripts_snapshot_directory_invokes_cli(self) -> None:
        skill_root = repo_path("skills/dxf")
        result = subprocess.run(
            [sys.executable, "scripts/snapshot", "--help"],
            cwd=skill_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("Usage:", result.stdout)
        self.assertIn(".dxf", result.stdout)

    def test_runtime_is_bundled_beside_the_cli(self) -> None:
        # The skill must carry its own render runtime: it may not reach into the CAD
        # skill's copy, and a published skill ships no node_modules.
        runtime = browser_runtime_dir()
        self.assertTrue((Path(runtime) / "render.html").is_file())
        self.assertTrue((Path(runtime) / "snapshot-render.js").is_file())


if __name__ == "__main__":
    unittest.main()
