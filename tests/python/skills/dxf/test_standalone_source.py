import textwrap
import unittest
from pathlib import Path

from cadgen import catalog as cad_catalog
from cadgen._internal import generation as cad_generation
from cadgen.metadata import parse_generator_metadata
from tests.python.support.tmp_root import temporary_directory

STANDALONE_DXF_SOURCE = textwrap.dedent(
    '''
    """Standalone DXF drafting source."""

    import ezdxf


    def gen_dxf():
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True)
        return doc
    '''
).strip()


def _write_standalone_source(root: Path, stem: str = "outline") -> Path:
    script_path = root / f"{stem}.py"
    script_path.write_text(STANDALONE_DXF_SOURCE + "\n")
    return script_path


class StandaloneDxfSourceTests(unittest.TestCase):
    def test_metadata_allows_gen_dxf_without_gen_step(self) -> None:
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root))
            metadata = parse_generator_metadata(script_path)

        assert metadata is not None
        self.assertTrue(metadata.has_gen_dxf)
        self.assertFalse(metadata.has_gen_step)
        self.assertIsNone(metadata.kind)

    def test_metadata_ignores_deprecated_urdf_generators(self) -> None:
        # gen_urdf()/gen_sdf() are hard-deprecated: robot descriptions are
        # authored XML artifacts, so a urdf-only file is not a CAD source.
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = Path(root) / "robot.py"
            script_path.write_text("def gen_urdf():\n    return '<robot/>'\n")
            self.assertIsNone(parse_generator_metadata(script_path))

    def test_explicit_target_resolves_dxf_only_source(self) -> None:
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root))
            source = cad_catalog.source_from_path(script_path)

            assert source is not None
            self.assertEqual("dxf", source.kind)
            self.assertIsNone(source.step_path)
            self.assertEqual(script_path.with_suffix(".dxf"), source.dxf_path)

    def test_directory_catalog_skips_plain_py_dxf_only_source(self) -> None:
        # Plain `<name>.py` drawing sources stay explicit-target-only; catalog
        # entries require the `.dxf.py` naming.
        with temporary_directory(prefix="dxf-skill") as root:
            _write_standalone_source(Path(root))
            self.assertEqual((), cad_catalog.iter_cad_sources(Path(root)))

    def test_directory_catalog_lists_dxf_generator_entry(self) -> None:
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root), stem="outline.dxf")
            sources = cad_catalog.iter_cad_sources(Path(root))

            self.assertEqual(1, len(sources))
            self.assertEqual("dxf", sources[0].kind)
            self.assertEqual(script_path, sources[0].script_path)

    def test_generate_dxf_targets_always_writes_the_sibling(self) -> None:
        # The .dxf IS the product (design/standalone-viewer.md Phase A): every run
        # writes it, no package exists, and only the output record remains under
        # __cadgen__ to make an unchanged source a no-op.
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root))

            self.assertEqual(0, cad_generation.generate_dxf_targets([str(script_path)]))

            output_path = script_path.with_suffix(".dxf")
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)
            package_dir = Path(root) / "__cadgen__" / "models" / script_path.name
            self.assertTrue((package_dir / "dxf-export.json").exists())
            self.assertFalse((package_dir / "drawing.json").exists())
            self.assertFalse((package_dir / "preview.glb").exists())

    def test_unchanged_source_is_a_no_op_and_output_is_deterministic(self) -> None:
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root))
            sibling = script_path.with_suffix(".dxf")

            cad_generation.generate_dxf_targets([str(script_path)])
            first = sibling.read_bytes()
            first_mtime = sibling.stat().st_mtime_ns

            # Unchanged source: the recorded output verifies, nothing is rewritten.
            cad_generation.generate_dxf_targets([str(script_path)])
            self.assertEqual(first_mtime, sibling.stat().st_mtime_ns)

            # Forced rebuild of identical content produces identical bytes.
            cad_generation.generate_dxf_targets([str(script_path)], force=True)
            self.assertEqual(first, sibling.read_bytes())

    def test_source_edit_regenerates_the_sibling(self) -> None:
        # The sibling is the PRODUCT now, not a detached export: an edited source
        # regenerates it on the next run (the viewer renders this file).
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root))
            sibling = script_path.with_suffix(".dxf")

            cad_generation.generate_dxf_targets([str(script_path)])
            before = sibling.read_bytes()

            script_path.write_text(
                STANDALONE_DXF_SOURCE.replace("(40, 0)", "(50, 0)").replace("(40, 20)", "(50, 20)") + "\n"
            )
            cad_generation.generate_dxf_targets([str(script_path)])
            self.assertNotEqual(before, sibling.read_bytes())

    def test_generate_dxf_targets_rejects_non_document_payload(self) -> None:
        # Fail closed: an object that only implements saveas is not a drawing and
        # must be rejected, not silently written without validation.
        with temporary_directory(prefix="dxf-skill") as root:
            script_path = Path(root) / "fake.dxf.py"
            script_path.write_text(
                "\n".join(
                    [
                        "class _FakeDxf:",
                        "    def saveas(self, output_path):",
                        "        pass",
                        "def gen_dxf():",
                        "    return {'document': _FakeDxf()}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(TypeError, "must return an ezdxf document"):
                cad_generation.generate_dxf_targets([str(script_path)])

    def test_output_record_gates_freshness_for_both_authorities(self) -> None:
        # The CLI's no-op gate and the render-side validator read the SAME record
        # (cadgen._internal.dxf_output), so they can never disagree.
        from cadgen._internal.dxf_output import dxf_output_current
        from cadgen.render_ops import validate_dxf_freshness

        with temporary_directory(prefix="dxf-skill") as root:
            script_path = _write_standalone_source(Path(root), stem="outline.dxf")
            cad_generation.generate_dxf_targets([str(script_path)])
            self.assertTrue(dxf_output_current(script_path))
            self.assertEqual((True, None), validate_dxf_freshness(root, script_path))

            script_path.write_text(STANDALONE_DXF_SOURCE.replace("(40, 0)", "(60, 0)") + "\n")
            self.assertFalse(dxf_output_current(script_path))
            self.assertEqual(
                (False, "stale_dxf_output"), validate_dxf_freshness(root, script_path)
            )


if __name__ == "__main__":
    unittest.main()
