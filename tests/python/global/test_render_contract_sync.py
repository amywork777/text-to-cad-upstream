"""The cross-language render contract: constants that exist in BOTH the Python
producer and the JS consumer must be bumped together.

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

    def test_package_contract_constants_match_python(self) -> None:
        # The JS status authority validates packages against the SAME versions
        # the Python producer stamps (viewer/server/packageContract.mjs); a
        # one-sided bump makes every package permanently stale (or permanently
        # fresh) on one side.
        contract = ROOT / "viewer/server/packageContract.mjs"
        self.assertEqual(
            _extract(
                r"^STEP_PACKAGE_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/package_freshness.py",
            ),
            _extract(r"^export const STEP_PACKAGE_VERSION = (\d+);", contract),
            "STEP_PACKAGE_VERSION diverged between cadgen and the viewer's package contract",
        )
        self.assertEqual(
            _extract(
                r"^STEP_TOPOLOGY_SCHEMA_VERSION = (\d+)$",
                ROOT / "packages/cadgen/src/cadgen/_internal/glb_topology.py",
            ),
            _extract(r"^export const STEP_TOPOLOGY_SCHEMA_VERSION = (\d+);", contract),
            "STEP_TOPOLOGY_SCHEMA_VERSION diverged between cadgen and the viewer's package contract",
        )

    def test_status_authority_schema_gate_matches_python(self) -> None:
        # The JS status authority gates render packages on the one JS constant
        # this suite pins against Python.
        status_module = ROOT / "viewer/server/artifactStatus.mjs"
        self.assertIn(
            'import { STEP_PACKAGE_VERSION } from "./packageContract.mjs";',
            status_module.read_text(),
            "the status authority must read the schema version from the one JS "
            "constant (packageContract.mjs), which this suite pins against Python",
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
