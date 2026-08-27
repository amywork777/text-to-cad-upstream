"""Cross-implementation extractor conformance (design/standalone-viewer.md).

Two extractors produce `.surf` render views: the native one
(cadgen/_internal/surface_extract.py, in-process at generation time) and the
WASM twin (viewer/server/import/surfExtractTwin.mjs, the standalone viewer's
foreign-STEP import). They are deliberately duplicated logic; THIS SUITE is the
sync contract. Every blob in models/conformance (curated to cover every surface
kind plus the known traps — see its manifest.json) is extracted by BOTH and
compared geometrically by the client's own evaluator
(viewer/server/import/compareSurf.mjs): structure and classification must match
exactly, geometry within tolerance. Byte identity is NOT required — the kernels
differ (OCP 7.9 vs WASM ~7.6) and GeomConvert output legitimately varies; the
trims it cuts must not.

Skipped (not failed) when the WASM kernel is not installed: opencascade.js is a
viewer npm dependency, absent in minimal CI slices. The viewer's own CI slice
runs `npm --prefix viewer install`, so the suite is live wherever the twin is.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CORPUS = ROOT / "models" / "conformance"
VIEWER = ROOT / "viewer"
NODE_TIMEOUT_S = 300


def _wasm_kernel_available() -> bool:
    return (VIEWER / "node_modules" / "opencascade.js" / "dist" / "opencascade.full.wasm").is_file()


def _run_node(script: str, args: list[str]) -> dict:
    proc = subprocess.run(
        ["node", str(VIEWER / "server" / "import" / script), *args],
        cwd=VIEWER,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
    )
    for line in reversed(proc.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)
    raise AssertionError(
        f"{script} produced no JSON (exit {proc.returncode}): {proc.stderr[-500:]}"
    )


@unittest.skipUnless(_wasm_kernel_available(), "opencascade.js is not installed under viewer/")
class SurfExtractorConformanceTest(unittest.TestCase):
    maxDiff = None

    def test_every_corpus_blob_extracts_identically(self) -> None:
        from cadgen._internal.component_package import _build123d_shape_from_brep_bytes
        from cadgen._internal.surface_extract import extract_surface_component

        manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
        blobs = [CORPUS / entry["file"] for entry in manifest["components"]]
        self.assertGreaterEqual(len(blobs), 10, "the corpus shrank; keep every kind covered")

        with tempfile.TemporaryDirectory(prefix="surf-conformance") as tmp:
            for blob in blobs:
                with self.subTest(blob=blob.name):
                    shape = _build123d_shape_from_brep_bytes(blob.read_bytes())
                    native_path = Path(tmp) / f"{blob.stem}.native.surf"
                    native_path.write_bytes(extract_surface_component(shape.wrapped))

                    twin_path = Path(tmp) / f"{blob.stem}.twin.surf"
                    extracted = _run_node(
                        "extractCli.mjs",
                        ["--brep", str(blob), "--out", str(twin_path)],
                    )
                    self.assertTrue(
                        extracted.get("ok"),
                        f"twin extraction failed: {extracted.get('error')}",
                    )

                    compared = _run_node(
                        "compareSurf.mjs",
                        ["--a", str(native_path), "--b", str(twin_path)],
                    )
                    self.assertTrue(
                        compared.get("ok"),
                        "conformance failure:\n" + "\n".join(compared.get("problems") or []),
                    )


if __name__ == "__main__":
    unittest.main()
