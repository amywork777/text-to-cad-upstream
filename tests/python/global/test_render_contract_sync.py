"""The cross-language render contract: constants that exist in BOTH the Python
producer and the JS consumer/producer must be bumped together, and the blob
serialization the standalone viewer's WASM kernel reads must stay pinned.

This repo has lost a cross-language mirror to a deleted check before (the
viewer scanner's package-path constants drifted silently once nothing compared
them) — these greps are the structural version of that comparison: a one-sided
bump fails CI before it can ship a viewer that cannot read what cadgen writes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _extract(pattern: str, path: Path) -> str:
    match = re.search(pattern, path.read_text(), re.MULTILINE)
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
            ROOT / "packages/cadjs/src/lib/surf/container.js",
        )
        self.assertEqual(
            python_version,
            js_version,
            "SURF_VERSION diverged between the Python extractor and the JS "
            "surf parser — bump both together (and STEP_PACKAGE_VERSION with "
            "them; a .surf the client cannot parse renders nothing).",
        )

    def test_wasm_import_twin_constants_match_python(self) -> None:
        # The WASM STEP import (viewer/server/import/stepImport.mjs) writes the
        # SAME package format cadgen does, so every mirrored constant must move
        # in lockstep: a one-sided bump ships a JS-built package the Python
        # freshness gates call stale forever (or vice versa).
        twin = ROOT / "viewer/server/import/stepImport.mjs"
        self.assertEqual(
            _extract(
                r"^STEP_PACKAGE_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/package_freshness.py",
            ),
            _extract(r"^export const STEP_PACKAGE_VERSION = (\d+);", twin),
            "STEP_PACKAGE_VERSION diverged between cadgen and the WASM import twin",
        )
        self.assertEqual(
            _extract(
                r"^STEP_TOPOLOGY_SCHEMA_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/glb_topology.py",
            ),
            _extract(r"^export const STEP_TOPOLOGY_SCHEMA_VERSION = (\d+);", twin),
            "STEP_TOPOLOGY_SCHEMA_VERSION diverged between cadgen and the WASM import twin",
        )
        glb_topology = ROOT / "packages/cadgen/src/cadgen/_internal/glb_topology.py"
        for python_pattern, js_pattern, label in (
            (r'^STEP_TOPOLOGY_EDGE_CLASSIFICATION_ALGORITHM = "([^"]+)"',
             r'^const EDGE_CLASSIFICATION_ALGORITHM = "([^"]+)";', "edge classification algorithm"),
            (r'^STEP_TOPOLOGY_SURFACE_EDGE_ALGORITHM = "([^"]+)"',
             r'^const SURFACE_EDGE_ALGORITHM = "([^"]+)";', "surface edge algorithm"),
            (r"^STEP_TOPOLOGY_EDGE_ANGULAR_TOLERANCE_DEG = (\d+)",
             r"^const EDGE_ANGULAR_TOLERANCE_DEG = (\d+);", "edge angular tolerance"),
            (r"^STEP_TOPOLOGY_EDGE_SAMPLE_COUNT = (\d+)",
             r"^const EDGE_SAMPLE_COUNT = (\d+);", "edge sample count"),
        ):
            self.assertEqual(
                _extract(python_pattern, glb_topology),
                _extract(js_pattern, twin),
                f"{label} diverged between cadgen and the WASM import twin",
            )

    def test_status_authority_mirrors_match_python(self) -> None:
        # Freshness verdicts live in ONE place (viewer/server/artifactStatus.mjs);
        # the constants it mirrors from cadgen must move in lockstep, and the
        # canonical bake hash must be byte-identical across the two languages —
        # a divergence makes every implicit package permanently stale (or
        # permanently fresh) on one side.
        import json
        import subprocess

        status_module = ROOT / "viewer/server/artifactStatus.mjs"
        self.assertEqual(
            _extract(
                r"^IMPLICIT_PACKAGE_SCHEMA_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/implicit_package.py",
            ),
            _extract(r"^export const IMPLICIT_PACKAGE_SCHEMA_VERSION = (\d+);", status_module),
            "IMPLICIT_PACKAGE_SCHEMA_VERSION diverged between cadgen and the JS status authority",
        )
        import sys
        sys.path.insert(0, str(ROOT / "packages/cadgen/src"))
        try:
            from cadgen._internal.implicit_package import implicit_bake_settings
            from cadgen._internal.package_freshness import canonical_bake_hash

            python_hash = canonical_bake_hash(implicit_bake_settings())
        finally:
            sys.path.pop(0)
        node = subprocess.run(
            ["node", "--input-type=module", "-e",
             "import { pathToFileURL } from 'node:url';"
             "const m = await import(pathToFileURL(process.argv[1]).href);"
             "process.stdout.write(JSON.stringify(m.canonicalBakeHash(m.IMPLICIT_BAKE_SETTINGS)));",
             str(status_module)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, node.returncode, node.stderr[-300:])
        self.assertEqual(
            python_hash,
            json.loads(node.stdout),
            "canonical bake hash diverged: implicit packages would read stale on one side forever",
        )

    def test_component_blob_format_is_pinned_not_current(self) -> None:
        # The standalone viewer's WASM OCCT trails OCP's version. A floating
        # BinTools_FormatVersion_CURRENT would let an OCP upgrade silently emit
        # blobs the WASM reader rejects; the write site must name an explicit
        # version (bumping it re-keys every cid, so it is a deliberate act).
        source = (ROOT / "packages/cadgen/src/cadgen/_internal/component_package.py").read_text()
        writes = source.count("BinTools.Write_s(")
        self.assertGreaterEqual(writes, 1, "the component blob write site moved; update this test")
        self.assertNotIn(
            "BinTools_FormatVersion.BinTools_FormatVersion_CURRENT",
            source,
            "component blobs must be written with a PINNED BinTools format "
            "version (see _shape_brep_bytes), never _CURRENT",
        )
        # The JS producer writes blobs too (WASM import); the same pin applies,
        # and both write sites must name the SAME version.
        twin_source = (ROOT / "viewer/server/import/stepImport.mjs").read_text()
        self.assertNotIn("BinTools_FormatVersion_CURRENT", twin_source)
        python_pin = re.search(r"BinTools_FormatVersion\.(BinTools_FormatVersion_VERSION_\d+)", source)
        twin_pin = re.search(r"BinTools_FormatVersion\.(BinTools_FormatVersion_VERSION_\d+)", twin_source)
        assert python_pin and twin_pin, "a blob write site lost its explicit format pin"
        self.assertEqual(python_pin.group(1), twin_pin.group(1))


if __name__ == "__main__":
    unittest.main()
