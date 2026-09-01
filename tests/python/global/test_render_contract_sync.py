"""The cross-language render contract: constants that exist in BOTH the Python
producer and the JS consumer must be bumped together.

This repo has lost a cross-language mirror to a deleted check before (the
viewer scanner's package-path constants drifted silently once nothing compared
them) — these greps are the structural version of that comparison: a one-sided
bump fails CI before it can ship a viewer that cannot read what cadgen writes.

The CLIENT half of that boundary is still JS — ``packages/cadgen-js`` parses
``.surf`` in the browser — so the SURF_VERSION pin stays here. The viewer
BACKEND'S half is Python now, and is no longer a grep: its store-key constants
and path derivations are compared against cadgen's, value for value, by
``apps/viewer/tests_server/test_store_paths.py``. That is strictly stronger
than the literal scans of ``packageContract.mjs`` and ``storePaths.mjs`` that
used to live here — a grep can only say a string is present, never that the two
sides agree — and it is not a tautology, because the viewer keeps a genuinely
independent stdlib implementation so that merely VIEWING never requires cadgen.

A stronger check that runs nowhere is weaker than a grep that runs, so the last
class here pins the WIRING: ``scripts/test/test-python.sh`` must invoke the
viewer backend suite, and must invoke it with ``VIEWER_REQUIRE_CADGEN_PARITY=1``
— the flag that turns "cadgen absent, skipped" into a failure. Without both,
the equality guard executes in no automated configuration anywhere on earth:
the only other runner is the standalone viewer repo's CI, which has no cadgen
by design.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
VIEWER_APP_ROOT = ROOT / "apps/viewer"


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

    def test_sidecar_schema_matches_the_js_kinematics_loader(self) -> None:
        # The viewer BACKEND's copy of these constants is compared to cadgen's
        # by value in apps/viewer/tests_server/test_store_paths.py. What
        # remains genuinely cross-language is the CLIENT: the kinematics loader
        # runs in the browser and REFUSES any other schema, so a one-sided bump
        # makes every model's kinematics fail to load.
        sidecar_module = ROOT / "packages/cadgen/src/cadgen/_internal/source_sidecar.py"
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

    def test_the_viewer_derives_the_same_provenance_record_path_as_cadgen(self) -> None:
        # Behavioural, and now Python-to-Python: both sides must land on the
        # SAME absolute file for the same artifact. The viewer keeps its own
        # stdlib implementation so that viewing never requires cadgen, so this
        # is a real comparison of two independent derivations — it catches a
        # different hash input (resolved vs raw path), a different encoding, or
        # a join in the wrong order, none of which a constant pin can see.
        from cadgen._internal.source_sidecar import _provenance_record_path

        if str(VIEWER_APP_ROOT) not in sys.path:
            sys.path.insert(0, str(VIEWER_APP_ROOT))
        from server import store_paths

        with tempfile.TemporaryDirectory() as workspace:
            cache_dir = Path(workspace) / "store"
            artifact = Path(workspace) / "nested dir" / "wídget.step"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("ISO-10303-21;\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CADGEN_CACHE_DIR": str(cache_dir)}):
                self.assertEqual(
                    str(_provenance_record_path(artifact)),
                    store_paths.source_provenance_record_path(str(artifact)),
                    "the viewer and cadgen derive DIFFERENT provenance record "
                    "paths for the same artifact — the viewer would classify "
                    "every generated model as imported",
                )

    def test_viewer_classifier_reads_a_record_cadgen_wrote(self) -> None:
        # End to end across the PACKAGE boundary: cadgen writes the record, the
        # viewer's status authority reads it back as generated. Nothing here
        # depends on a sidecar — that is the whole point, since a plain
        # generated model writes none.
        from cadgen._internal.source_sidecar import write_source_provenance_record

        if str(VIEWER_APP_ROOT) not in sys.path:
            sys.path.insert(0, str(VIEWER_APP_ROOT))
        from server import artifact_status

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
                verdict = artifact_status.resolve_artifact_verdict(str(artifact), workspace)
            self.assertTrue(
                verdict.get("generated"),
                "the viewer read cadgen's own provenance record and still "
                f"classified the model as imported: {verdict}",
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


class TheCrossLanguageGuardsActuallyRun(unittest.TestCase):
    """The wiring, not the check.

    The viewer backend suite is the executable specification of the backend, and
    for one release cycle it ran in ZERO configurations of this repo: the JS
    runner stopped covering ``server/``, the Python runner discovered only
    ``tests/python/``, and the workflow never named it. Its only runner was a
    post-release job in another repository. This class is what makes that state
    fail the build instead of passing quietly.
    """

    RUNNER = ROOT / "scripts/test/test-python.sh"

    def setUp(self) -> None:
        self.runner_source = self.RUNNER.read_text(encoding="utf-8")

    def test_the_python_runner_runs_the_viewer_backend_suite(self) -> None:
        self.assertIn(
            "tests_server",
            self.runner_source,
            "scripts/test/test-python.sh must run apps/viewer/tests_server. It reaches "
            "every pull request from there -- through test.sh on Linux and directly in "
            "the Windows job -- and nothing else in this repo runs that suite.",
        )
        self.assertIn(
            "apps/viewer",
            self.runner_source,
            "the viewer backend arm must name apps/viewer as the directory it runs from",
        )

    def test_the_runner_demands_the_cadgen_equality_guard(self) -> None:
        self.assertIn(
            "VIEWER_REQUIRE_CADGEN_PARITY=1",
            self.runner_source,
            "without this flag AgreesWithCadgen skips wherever cadgen is absent, and the "
            "only other place the suite runs has no cadgen -- so the store-key equality "
            "guard that replaced this file's literal pins would run nowhere",
        )

    def test_the_flag_the_runner_sets_is_the_flag_the_guard_reads(self) -> None:
        # The two halves live in different trees and one of them mirrors out of
        # this repo, so a rename on either side must not silently unhook them.
        guard = (VIEWER_APP_ROOT / "tests_server/test_store_paths.py").read_text(encoding="utf-8")
        self.assertIn(
            'os.environ.get("VIEWER_REQUIRE_CADGEN_PARITY"',
            guard,
            "the viewer's equality guard no longer reads VIEWER_REQUIRE_CADGEN_PARITY; "
            "whatever replaced it must be what test-python.sh sets",
        )

    def test_an_unimportable_cadgen_fails_rather_than_skips_under_the_flag(self) -> None:
        # Behavioural, not a grep: run the guard with the flag set and cadgen
        # made unreachable, and require a FAILURE. A skip here is the whole bug.
        #
        # cadgen is installed in every interpreter that can run this file, so its
        # absence is STAGED: a shim package ahead of it on the path that refuses
        # to import. That is what a machine without cadgen looks like to the
        # guard's `import cadgen.catalog` probe.
        with tempfile.TemporaryDirectory() as shim_root:
            shim = Path(shim_root) / "cadgen"
            shim.mkdir()
            (shim / "__init__.py").write_text(
                'raise ImportError("staged absence")\n', encoding="utf-8"
            )
            env = dict(os.environ)
            env["VIEWER_REQUIRE_CADGEN_PARITY"] = "1"
            env["PYTHONPATH"] = shim_root
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "tests_server.test_store_paths.AgreesWithCadgen"],
                cwd=VIEWER_APP_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(
            completed.returncode,
            0,
            "VIEWER_REQUIRE_CADGEN_PARITY was set and cadgen was unreachable, and the "
            f"guard still passed:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn("VIEWER_REQUIRE_CADGEN_PARITY", completed.stderr)
        self.assertNotIn(
            "skipped",
            completed.stderr,
            "under the flag an absent cadgen must be a failure, never a skip",
        )


if __name__ == "__main__":
    unittest.main()
