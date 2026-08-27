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


if __name__ == "__main__":
    unittest.main()
