"""The cross-language render contract: constants that exist in BOTH the Python
producer and the JS consumer must be bumped together.

This repo has lost a cross-language mirror to a deleted check before (the
viewer scanner's package-path constants drifted silently once nothing compared
them) — these greps are the structural version of that comparison: a one-sided
bump fails CI before it can ship a viewer that cannot read what cadgen writes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
STORE_PATHS_JS = ROOT / "apps/viewer/server/storePaths.mjs"


def _extract(pattern: str, path: Path, flags: int = re.MULTILINE) -> str:
    match = re.search(pattern, path.read_text(), flags)
    assert match, f"{pattern!r} not found in {path}"
    return match.group(1)


class RenderContractSyncTest(unittest.TestCase):
    def test_surf_version_matches_between_python_and_js(self) -> None:
        python_version = _extract(
            r"^SURF_VERSION = (\d+)$",
            ROOT / "packages/cadgen/src/cadgen/_internal/surface_extract.py",
        )
        js_version = _extract(
            r"^export const SURF_VERSION = (\d+);$",
            ROOT / "packages/cadgen-js/src/lib/surf/container.js",
        )
        self.assertEqual(
            python_version,
            js_version,
            "SURF_VERSION diverged between the Python extractor and the JS "
            "surf parser — bump both together (and CACHE_SCHEMA_VERSION with "
            "them; a .surf the client cannot parse renders nothing).",
        )

    def test_package_contract_constants_match_python(self) -> None:
        # Both languages resolve store keys with the SAME cache-scheme number
        # (apps/viewer/server/packageContract.mjs mirrors cache_schema.py); a
        # one-sided bump strands one side in the old key generation.
        contract = ROOT / "apps/viewer/server/packageContract.mjs"
        self.assertEqual(
            _extract(
                r"^CACHE_SCHEMA_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/cache_schema.py",
            ),
            _extract(r"^export const CACHE_SCHEMA_VERSION = (\d+);", contract),
            "CACHE_SCHEMA_VERSION diverged between cadgen and the viewer's package contract",
        )
        sidecar_module = ROOT / "packages/cadgen/src/cadgen/_internal/source_sidecar.py"
        self.assertEqual(
            _extract(r'^SOURCE_SIDECAR_SUFFIX = "([^"]+)"$', sidecar_module),
            _extract(r'^export const SOURCE_SIDECAR_SUFFIX = "([^"]+)";', contract),
            "SOURCE_SIDECAR_SUFFIX diverged between cadgen and the viewer's package "
            "contract — the model-side sidecar's existence IS the "
            "generated-vs-imported marker on both freshness authorities",
        )
        self.assertEqual(
            _extract(r"^SOURCE_SIDECAR_SCHEMA_VERSION = (\d+)$", sidecar_module),
            _extract(r"^export const SOURCE_SIDECAR_SCHEMA_VERSION = (\d+);", contract),
            "SOURCE_SIDECAR_SCHEMA_VERSION diverged between cadgen and the viewer's package contract",
        )
        self.assertEqual(
            _extract(r"^SOURCE_SIDECAR_SCHEMA_VERSION = (\d+)$", sidecar_module),
            _extract(
                r"^export const SOURCE_SIDECAR_SCHEMA_VERSION = (\d+);",
                ROOT / "packages/cadgen-js/src/common/kinematicsModule.js",
            ),
            "SOURCE_SIDECAR_SCHEMA_VERSION diverged between cadgen and the JS "
            "kinematics loader — the loader REFUSES any other schema, so a "
            "one-sided bump makes every model's kinematics fail to load",
        )

    def test_provenance_record_constants_match_python(self) -> None:
        # The records tier is where generated-vs-imported actually lives at
        # sidecar schema 5: a PLAIN generated model writes no sidecar, so the
        # viewer's classifier reads <cache>/records/<pathKey>.source.json. Three
        # literals have to agree across the languages, and each of them is the
        # kind that fails SILENTLY — a wrong dir name or a wrong truncation
        # length just never finds a record, and every generated model quietly
        # reads as imported.
        contract = ROOT / "apps/viewer/server/packageContract.mjs"
        cache_paths_module = ROOT / "packages/cadgen/src/cadgen/_internal/cache_paths.py"
        self.assertEqual(
            _extract(
                r'def records_dir\(\).*?return cache_root\(\) / "([^"]+)"',
                cache_paths_module,
                re.DOTALL,
            ),
            _extract(r'^export const RECORDS_DIR_NAME = "([^"]+)";', contract),
            "the records tier's directory name diverged between cadgen's "
            "cache_paths.records_dir and the viewer's package contract",
        )
        self.assertEqual(
            _extract(
                r'f"\{artifact_path_key\(Path\(step_path\)\)\}([^"]+)"',
                ROOT / "packages/cadgen/src/cadgen/_internal/source_sidecar.py",
            ),
            _extract(r'^export const PROVENANCE_RECORD_SUFFIX = "([^"]+)";', contract),
            "the provenance record's filename suffix diverged between cadgen's "
            "_provenance_record_path and the viewer's package contract",
        )
        self.assertEqual(
            _extract(
                r"hexdigest\(\)\[:(\d+)\]",
                ROOT / "packages/cadgen/src/cadgen/catalog.py",
            ),
            _extract(r"^export const ARTIFACT_PATH_KEY_LENGTH = (\d+);", contract),
            "artifact_path_key's truncation length diverged between cadgen and "
            "the viewer's package contract",
        )

    def test_provenance_record_path_derivation_matches_python(self) -> None:
        # Behavioural, not just grep: both sides must land on the SAME absolute
        # file for the same artifact. This catches everything the literal pins
        # above cannot — a different hash input (resolved vs raw path), a
        # different encoding, a join in the wrong order.
        from cadgen._internal.source_sidecar import _provenance_record_path

        with tempfile.TemporaryDirectory() as workspace:
            cache_dir = Path(workspace) / "store"
            artifact = Path(workspace) / "nested dir" / "wídget.step"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("ISO-10303-21;\n", encoding="utf-8")

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in {"CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"}
            }
            env["CADGEN_CACHE_DIR"] = str(cache_dir)
            from cadgen._internal.node_runtime import cad_node_executable

            module_url = STORE_PATHS_JS.resolve().as_uri()
            script = (
                f"import({module_url!r}).then(m => process.stdout.write("
                f"m.sourceProvenanceRecordPath({str(artifact)!r})))"
            )
            result = subprocess.run(
                [str(cad_node_executable()), "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(cache_dir)}):
                python_path = str(_provenance_record_path(artifact))
            self.assertEqual(
                python_path,
                result.stdout.strip(),
                "the viewer and cadgen derive DIFFERENT provenance record paths "
                "for the same artifact — the viewer would classify every "
                "generated model as imported",
            )

    def test_viewer_reads_the_progress_record_a_live_build_publishes(self) -> None:
        # THE equality the build badge depends on: the file a producer publishes its
        # progress into and the file the viewer polls must be one file. They are derived
        # on opposite sides of the language boundary — cadgen from
        # coordination.paths.status_path(coordination_scope(model)), the viewer from
        # storePaths.coordinationScope(model) — from the MODEL path, never the package
        # dir, because a rebuild changes the content key mid-build.
        #
        # When they disagreed the whole chain still worked and the user saw nothing: the
        # record was written (to the packages/ tier, under the content hash), the reader
        # looked (in the locks/ tier, under the path key), found nothing every poll, and
        # the overlay fell back to an indeterminate bar with no phase and no counts. So
        # this asks the REAL reader for the record a REAL producer is holding open.
        from cadgen.catalog import coordination_scope
        from cadgen.coordination import PHASE_COMPONENTS, STEP_PACKAGE, artifact_build

        with tempfile.TemporaryDirectory() as workspace:
            cache_dir = Path(workspace) / "store"
            artifact = Path(workspace) / "nested dir" / "wídget.step"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("ISO-10303-21;\n", encoding="utf-8")

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in {"CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"}
            }
            env["CADGEN_CACHE_DIR"] = str(cache_dir)
            from cadgen._internal.node_runtime import cad_node_executable

            module_url = (ROOT / "apps/viewer/server/cadgenOps.mjs").resolve().as_uri()
            script = (
                f"import({module_url!r}).then(m => process.stdout.write(JSON.stringify("
                f"m.buildProgressSnapshot({str(artifact)!r}))))"
            )
            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(cache_dir)}):
                with artifact_build(STEP_PACKAGE, coordination_scope(artifact)) as run:
                    run.phase(PHASE_COMPONENTS, total=37, detail="c0ffee")
                    run.advance(3)
                    # Read from OUTSIDE the process holding the lock, exactly as the
                    # viewer's poll does.
                    result = subprocess.run(
                        [str(cad_node_executable()), "--input-type=module", "-e", script],
                        capture_output=True,
                        text=True,
                        env=env,
                        check=True,
                    )

            snapshot = json.loads(result.stdout.strip() or "null")
            self.assertIsNotNone(
                snapshot,
                "the viewer found NO progress record for a build that is holding the "
                "model's lock and publishing phases — the producer and the reader are "
                "deriving different paths, so every poll answers a bare "
                '{"state":"generating"} with no bar',
            )
            self.assertTrue(snapshot["writing"])
            self.assertTrue(snapshot["runId"], "a live record must name its run")
            self.assertEqual(snapshot["progress"]["phase"], PHASE_COMPONENTS)
            self.assertEqual(snapshot["progress"]["total"], 37)
            self.assertEqual(snapshot["progress"]["done"], 3)
            self.assertEqual(snapshot["progress"]["detail"], "c0ffee")

    def test_viewer_classifier_reads_a_record_cadgen_wrote(self) -> None:
        # End to end across the language boundary: cadgen writes the record,
        # the viewer's status authority reads it back as generated. Nothing here
        # depends on a sidecar — that is the whole point.
        from cadgen._internal.source_sidecar import write_source_provenance_record

        with tempfile.TemporaryDirectory() as workspace:
            cache_dir = Path(workspace) / "store"
            artifact = Path(workspace) / "plate.step"
            artifact.write_text("ISO-10303-21;\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(cache_dir)}):
                write_source_provenance_record(
                    artifact,
                    {"sourceKind": "python", "sourcePath": "src/plate.py"},
                )
            self.assertFalse(
                artifact.with_name(f"{artifact.name}.json").exists(),
                "fixture must be a PLAIN generated model (no sidecar)",
            )

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in {"CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"}
            }
            env["CADGEN_CACHE_DIR"] = str(cache_dir)
            from cadgen._internal.node_runtime import cad_node_executable

            module_url = (ROOT / "apps/viewer/server/artifactStatus.mjs").resolve().as_uri()
            script = (
                f"import({module_url!r}).then(m => process.stdout.write(JSON.stringify("
                f"m.resolveArtifactVerdict({str(artifact)!r}, {workspace!r}))))"
            )
            result = subprocess.run(
                [str(cad_node_executable()), "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            verdict = json.loads(result.stdout.strip())
            self.assertTrue(
                verdict.get("generated"),
                "the viewer read cadgen's own provenance record and still "
                f"classified the model as imported: {verdict}",
            )

    def test_store_key_salt_reads_the_one_js_constant(self) -> None:
        # Schema gating lives in the package KEY: storePaths.mjs salts the
        # store key with the one JS constant this suite pins against Python.
        # A package that resolves at all is current-scheme by construction.
        # Matches either import shape (one name on a line, or a braced list) so
        # adding a second mirrored constant does not read as a broken contract.
        self.assertRegex(
            STORE_PATHS_JS.read_text(),
            r"import \{[^}]*\bCACHE_SCHEMA_VERSION\b[^}]*\} from \"\./packageContract\.mjs\";",
            "the store key salt must read the cache-scheme version from the one "
            "JS constant (packageContract.mjs), which this suite pins against Python",
        )

    def test_component_blob_format_is_pinned_not_current(self) -> None:
        # Component blobs are content-addressed: their serialized bytes ARE the
        # cid. A floating BinTools_FormatVersion_CURRENT would let an OCP
        # upgrade silently re-serialize every blob and re-key every cid; the
        # write site must name an explicit version so a format bump is a
        # deliberate act, not a dependency-update side effect.
        source = (ROOT / "packages/cadgen/src/cadgen/_internal/component_package.py").read_text()
        writes = source.count("BinTools.Write_s(")
        self.assertGreaterEqual(writes, 1, "the component blob write site moved; update this test")
        self.assertNotIn(
            "BinTools_FormatVersion.BinTools_FormatVersion_CURRENT",
            source,
            "component blobs must be written with a PINNED BinTools format "
            "version (see _shape_brep_bytes), never _CURRENT",
        )


if __name__ == "__main__":
    unittest.main()
