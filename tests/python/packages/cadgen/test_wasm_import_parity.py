"""Import-pipeline parity: the WASM STEP import must package like the native one.

The extractor conformance suite (test_surf_extractor_conformance) fences the
GEOMETRY duplication; this suite fences the rest of the duplicated import
pipeline — XCAF walk, entry-kind inference, occurrence composition, descriptor
glue (design/standalone-viewer.md Phase C). It imports the same fixture STEP
through both producers and asserts:

- descriptor parity: occurrence ids/names/transforms/colors, assembly tree,
  entryKind, mesh block (adaptive resolution + hints), stepHash, edgeRendering,
  capabilities, bbox, stats, key set;
- component-sharing pattern parity (same dedup, cid VALUES may differ — the two
  kernels serialize BREP differently, and that byte divergence is by design);
- geometric parity: every occurrence-paired component pair conformant under the
  same evaluator the conformance suite uses (compareSurf.mjs);
- cross-kernel blob interop: OCP reads every WASM-written <cid>.brep.
"""

from __future__ import annotations

import io
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VIEWER = ROOT / "viewer"
FIXTURE = ROOT / "models" / "step" / "parts" / "cam_follower_roller.step"
NODE_TIMEOUT_S = 600


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


def _rounded(values: list[float], digits: int) -> tuple[float, ...]:
    return tuple(round(float(value), digits) for value in values)


@unittest.skipUnless(_wasm_kernel_available(), "opencascade.js is not installed under viewer/")
class WasmImportParityTest(unittest.TestCase):
    maxDiff = None

    def test_wasm_import_matches_native_import(self) -> None:
        from cadgen.step_artifact_cli import build_step_artifact

        with tempfile.TemporaryDirectory(prefix="wasm-import-parity") as tmp:
            tmp_path = Path(tmp).resolve()
            native_root = tmp_path / "native"
            wasm_root = tmp_path / "wasm"
            for root in (native_root, wasm_root):
                root.mkdir()
                (root / FIXTURE.name).write_bytes(FIXTURE.read_bytes())

            # force=True: the corpus fixture is itself a cadgen-generated file
            # (embedded identity metadata), which the generated-step guard
            # otherwise refuses to import — this test WANTS the import path.
            build_step_artifact(repo_root=native_root, step=native_root / FIXTURE.name, force=True)
            imported = _run_node("importCli.mjs", [
                "--step", str(wasm_root / FIXTURE.name),
                "--package-dir", str(wasm_root / "__cadgen__" / "models" / FIXTURE.name),
            ])
            self.assertTrue(imported.get("ok"), f"WASM import failed: {imported.get('error')}")

            native_dir = native_root / "__cadgen__" / "models" / FIXTURE.name
            wasm_dir = wasm_root / "__cadgen__" / "models" / FIXTURE.name
            native = json.loads((native_dir / "assembly.json").read_text())
            wasm = json.loads((wasm_dir / "assembly.json").read_text())

            self.assertEqual(sorted(native), sorted(wasm), "descriptor key sets differ")
            for key in ("entryKind", "sourceKind", "kind", "packageSchemaVersion",
                        "schemaVersion", "profile", "rootName", "units", "stepPath",
                        "stepHash", "edgeRendering", "capabilities", "assemblyMates",
                        "stats"):
                self.assertEqual(native.get(key), wasm.get(key), f"descriptor {key} differs")

            # Mesh block: the adaptive resolver is duplicated; values must agree
            # (hints hold floats — compare rounded).
            self.assertEqual(native["mesh"]["linearDeflection"], wasm["mesh"]["linearDeflection"])
            self.assertEqual(native["mesh"]["angularDeflection"], wasm["mesh"]["angularDeflection"])
            self.assertEqual(native["mesh"]["relative"], wasm["mesh"]["relative"])
            native_res = dict(native["mesh"]["resolution"])
            wasm_res = dict(wasm["mesh"]["resolution"])
            native_hints = native_res.pop("hints")
            wasm_hints = wasm_res.pop("hints")
            self.assertEqual(native_res, wasm_res)
            self.assertEqual(sorted(native_hints), sorted(wasm_hints))
            for key, native_value in native_hints.items():
                wasm_value = wasm_hints[key]
                if isinstance(native_value, (int, float)) and isinstance(wasm_value, (int, float)):
                    self.assertTrue(
                        math.isclose(float(native_value), float(wasm_value), rel_tol=1e-6, abs_tol=2e-3),
                        f"hint {key}: {native_value} vs {wasm_value}",
                    )
                else:
                    self.assertEqual(native_value, wasm_value, f"hint {key} differs")

            for axis in ("min", "max"):
                self.assertEqual(
                    _rounded(native["bbox"][axis], 6), _rounded(wasm["bbox"][axis], 6),
                    f"bbox {axis} differs")

            # Occurrences: ids, names, transforms, colors — and the component
            # dedup pattern, though the cid values legitimately differ.
            self.assertEqual(len(native["occurrences"]), len(wasm["occurrences"]))
            def share_pattern(descriptor: dict) -> list[int]:
                order: dict[str, int] = {}
                return [order.setdefault(occ["component"], len(order))
                        for occ in descriptor["occurrences"]]
            self.assertEqual(share_pattern(native), share_pattern(wasm))
            component_pairs: dict[tuple[str, str], str] = {}
            for native_occ, wasm_occ in zip(native["occurrences"], wasm["occurrences"]):
                self.assertEqual(native_occ["id"], wasm_occ["id"])
                self.assertEqual(native_occ["name"], wasm_occ["name"])
                self.assertEqual(
                    _rounded(native_occ["transform"], 6), _rounded(wasm_occ["transform"], 6),
                    f"occurrence {native_occ['id']} transform differs")
                self.assertEqual(
                    _rounded(native_occ.get("color") or [], 4),
                    _rounded(wasm_occ.get("color") or [], 4),
                    f"occurrence {native_occ['id']} color differs")
                component_pairs[(native_occ["component"], wasm_occ["component"])] = native_occ["id"]
            self.assertEqual(native.get("assembly"), wasm.get("assembly"))

            # Geometric parity + blob interop per paired component.
            from OCP.BinTools import BinTools
            from OCP.TopoDS import TopoDS_Shape

            for (native_cid, wasm_cid), occurrence_id in component_pairs.items():
                with self.subTest(occurrence=occurrence_id):
                    compared = _run_node("compareSurf.mjs", [
                        "--a", str(native_dir / "components" / f"{native_cid}.surf"),
                        "--b", str(wasm_dir / "components" / f"{wasm_cid}.surf"),
                    ])
                    self.assertTrue(
                        compared.get("ok"),
                        "component conformance failure:\n"
                        + "\n".join(compared.get("problems") or []),
                    )
                    payload = (wasm_dir / "components" / f"{wasm_cid}.brep").read_bytes()
                    shape = TopoDS_Shape()
                    BinTools.Read_s(shape, io.BytesIO(payload))
                    self.assertFalse(shape.IsNull(), "OCP could not read the WASM-written blob")

            # The inspect CLI resolves selector refs against the JS-built
            # package — including a FACE ref, which forces the lazy topology
            # build to run on WASM-written blobs. Target resolution is
            # cwd-relative, exactly as the CLI runs it.
            import os

            from cadgen.cli.step_inspect.inspect import inspect_cad_refs

            first_occurrence = wasm["occurrences"][0]["id"]
            previous_cwd = os.getcwd()
            os.chdir(wasm_root)
            try:
                resolved = inspect_cad_refs(
                    FIXTURE.name, f"#{first_occurrence}.f1", detail=True)
            finally:
                os.chdir(previous_cwd)
            self.assertFalse(resolved.get("errors"), f"inspect refs failed: {resolved.get('errors')}")
            selections = resolved["tokens"][0]["selections"]
            self.assertEqual(selections[0]["status"], "resolved")
            self.assertEqual(selections[0]["selectorType"], "face")


if __name__ == "__main__":
    unittest.main()
