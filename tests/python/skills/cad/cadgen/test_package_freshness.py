import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cadgen._internal import generation
from cadgen._internal.component_package import PACKAGE_KIND
from cadgen._internal.glb_topology import read_step_topology_manifest_from_glb
from cadgen._internal.package_freshness import (
    STEP_PACKAGE_VERSION,
)
from cadgen._internal.source_hash import closure_for_files

# Sentinel for "remove this key from the descriptor entirely".
_DROP = object()


def _write_package(
    model_dir: Path, entry_name: str, descriptor: dict, *, generated: bool = False
) -> Path:
    from cadgen.catalog import render_package_dir

    entry_file = model_dir / entry_name
    if not entry_file.is_file():
        entry_file.parent.mkdir(parents=True, exist_ok=True)
        # Unique per root: content keying would collide same-bytes fixtures
        # from different cases into one store package.
        entry_file.write_text(f"ISO-10303-21;\n{entry_file.resolve()}\n")
    package_dir = render_package_dir(entry_file)
    (package_dir / "components").mkdir(parents=True, exist_ok=True)
    if "stepHash" not in descriptor:
        import hashlib

        descriptor = {**descriptor, "stepHash": hashlib.sha256(entry_file.read_bytes()).hexdigest()}
    (package_dir / "assembly.json").write_text(json.dumps(descriptor), encoding="utf-8")
    if generated:
        # The MODEL-SIDE sidecar's existence is the generated marker; the
        # descriptor is STEP-pure and never records provenance.
        Path(f"{entry_file}.source.json").write_text(
            json.dumps({"schemaVersion": 2, "sourceKind": "python"}), encoding="utf-8"
        )
    return package_dir


class DirAwareManifestReaderTests(unittest.TestCase):
    def test_package_directory_returns_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptor = {"kind": PACKAGE_KIND, "schemaVersion": 2}
            package_dir = _write_package(root, "part.step", descriptor, generated=True)
            manifest = read_step_topology_manifest_from_glb(package_dir)
            self.assertIsInstance(manifest, dict)
            self.assertEqual(manifest.get("kind"), PACKAGE_KIND)

    def test_directory_without_descriptor_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(read_step_topology_manifest_from_glb(Path(temp)))


class PackageFreshnessGateTests(unittest.TestCase):
    def _generated_spec(self, model_dir: Path) -> generation.EntrySpec:
        from cadgen.metadata import GeneratorMetadata

        script = model_dir / "part.py"
        script.write_text(
            "from cadgen import step\n@step\ndef model():\n    return None\n",
            encoding="utf-8",
        )
        metadata = GeneratorMetadata(
            script_path=script,
            kind="assembly",
            display_name=None,
            generator_names=("model",),
            has_gen_step=True,
            has_gen_dxf=False,
            mesh_tolerance=None,
            mesh_angular_tolerance=None,
            entry_function="model",
            write_target=None,
            is_decorated=True,
        )
        return generation.EntrySpec(
            source_ref="part.py",
            cad_ref="part",
            kind="assembly",
            generator_metadata=metadata,
            source_path=script,
            display_name="part",
            source="generated",
            step_path=model_dir / "part.step",
            script_path=script,
        )

    def test_assembly_glb_package_current_keys_by_entry_filename(self) -> None:
        # The package lives at __cadgen__/models/part.step: STEP models key
        # by the STEP FILE, shared by the generator entry and its output
        # (design/step-document-architecture.md).
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = self._generated_spec(root)
            package_dir = _write_package(
                root,
                "part.step",
                {
                    "kind": PACKAGE_KIND,
                    "packageSchemaVersion": STEP_PACKAGE_VERSION,
                    "components": {"abc": {
                        "surf": "components/abc.surf",
                        "brep": "components/abc.brep",
                    }},
                },
            )
            (package_dir / "components" / "abc.surf").write_bytes(b"SURF-fake")
            (package_dir / "components" / "abc.brep").write_bytes(b"BREP-fake")
            self.assertTrue(generation._assembly_glb_package_current(spec))

    def test_assembly_glb_package_current_false_when_component_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = self._generated_spec(root)
            _write_package(
                root,
                "part.step",
                {
                    "kind": PACKAGE_KIND,
                    "components": {"abc": {"glb": "components/abc.glb"}},
                },
            )
            self.assertFalse(generation._assembly_glb_package_current(spec))

    def test_package_descriptor_matches_spec_returns_none_without_package(self) -> None:
        # No package on disk: the gate must fall back to the monolith validator
        # rather than deciding freshness itself.
        with tempfile.TemporaryDirectory() as temp:
            spec = self._generated_spec(Path(temp))
            self.assertIsNone(generation._package_descriptor_matches_spec(spec))


class ProducerGateMirrorsTheViewerTests(unittest.TestCase):
    """The producer's currency predicate is the OTHER freshness authority: it decides
    whether a build no-ops. A gate the viewer makes and this one does not turns a stale
    package into a silent `ready`; a gate this one makes and the viewer does not rebuilds
    forever. These pin the schema-version and bake gates on this side."""

    def _spec(self, model_dir: Path) -> generation.EntrySpec:
        from cadgen.metadata import GeneratorMetadata

        script = model_dir / "part.py"
        script.write_text(
            "from cadgen import step\n@step\ndef model():\n    return None\n",
            encoding="utf-8",
        )
        metadata = GeneratorMetadata(
            script_path=script,
            kind="assembly",
            display_name=None,
            generator_names=("model",),
            has_gen_step=True,
            has_gen_dxf=False,
            mesh_tolerance=None,
            mesh_angular_tolerance=None,
            entry_function="model",
            write_target=None,
            is_decorated=True,
        )
        return generation.EntrySpec(
            source_ref="part.py",
            cad_ref="part",
            kind="assembly",
            generator_metadata=metadata,
            source_path=script,
            display_name="part",
            source="generated",
            # No .step on disk: this entry's artifact IS the package.
            step_path=model_dir / "part.step",
            script_path=script,
        )

    def _descriptor(self, options) -> dict:
        return {
            "kind": PACKAGE_KIND,
            "packageSchemaVersion": STEP_PACKAGE_VERSION,
            "components": {"abc": {"glb": "components/abc.glb"}},
            "mesh": {
                "linearDeflection": options.linear_deflection,
                "angularDeflection": options.angular_deflection,
                "relative": options.relative,
            },
            "edgeRendering": {"visibilityClasses": list(options.edge_visibility_classes)},
        }

    def _match(self, descriptor: dict) -> bool:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = self._spec(root)
            _write_package(root, "part.step", descriptor, generated=True)
            return generation._package_descriptor_matches_spec(spec, self.options)

    def setUp(self) -> None:
        from cadgen._internal.step_scene import SelectorOptions

        self.options = SelectorOptions()

    def test_a_well_formed_package_descriptor_is_current(self) -> None:
        self.assertTrue(self._match(self._descriptor(self.options)))

    def test_schema_gating_lives_in_the_package_key(self) -> None:
        # The store key is <hash>-v<STEP_PACKAGE_VERSION>: a version bump
        # changes the key, so an old-generation package simply stops
        # resolving. No descriptor field decides schema currency any more.
        from cadgen.catalog import package_dir_for_hash

        self.assertTrue(
            str(package_dir_for_hash("cafe")).endswith(f"cafe-v{STEP_PACKAGE_VERSION}")
        )


if __name__ == "__main__":
    unittest.main()
