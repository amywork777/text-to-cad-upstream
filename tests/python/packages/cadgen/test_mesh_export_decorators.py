"""@stl/@glb/@threemf: declared mesh exports produced by the model run.

The decorators are metadata-attachers lowered into EntrySpec.mesh_exports;
production runs through the ONE mesh engine `cadgen step export` uses, gated
by the shared content-keyed ledger. Contracts pinned here: stacking order is
behavior-neutral (AST scanning sees the whole decorator list), duplicates and
@dxf misuse fail loudly, bare declarations land beside the STEP artifact,
script runs produce/heal declared exports without rebuilding the model, and
the CLI front door byte-matches and shares the ledger.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

REPO = Path(__file__).resolve().parents[4]
PYTHON = sys.executable

MODEL = textwrap.dedent("""\
    from cadgen import build123d as bd
    from cadgen import glb, step, stl, threemf


    @step(write="../STEP/widget.step")
    @stl(write="../STL/widget.stl")
    @glb
    @threemf(write="../3MF/widget.3mf", mesh_tolerance=5e-3)
    def widget(size: float = 12.0):
        body = bd.Box(size, size / 2, 3)
        body -= bd.Pos(0, 0, 0) * bd.Cylinder(2, 10)
        return body
    """)


class MeshExportMetadataTest(unittest.TestCase):
    def _parse(self, body: str):
        from cadgen.metadata import parse_generator_metadata

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "model.py"
            script.write_text(body)
            return parse_generator_metadata(script)

    def test_declarations_parse_and_order_is_neutral(self) -> None:
        below = self._parse(MODEL)
        above = self._parse(
            MODEL.replace(
                '@step(write="../STEP/widget.step")\n@stl(write="../STL/widget.stl")',
                '@stl(write="../STL/widget.stl")\n@step(write="../STEP/widget.step")',
            )
        )
        for metadata in (below, above):
            declared = {d.fmt: d for d in metadata.mesh_exports}
            self.assertEqual(set(declared), {"stl", "glb", "3mf"})
            self.assertEqual(declared["stl"].write, "../STL/widget.stl")
            self.assertIsNone(declared["glb"].write)
            self.assertEqual(declared["3mf"].mesh_tolerance, 5e-3)

    def test_variants_parse_but_ambiguous_duplicates_fail(self) -> None:
        # Same format at DISTINCT targets is a variant, not a duplicate.
        variants = self._parse(textwrap.dedent("""\
            from cadgen import step, stl

            @step(kind="part")
            @stl(write="a_draft.stl", mesh_tolerance=8e-3)
            @stl(write="a_print.stl", mesh_tolerance=4e-4)
            def part():
                return None
            """))
        self.assertEqual([d.write for d in variants.mesh_exports],
                         ["a_draft.stl", "a_print.stl"])
        # Two bare declarations collide at the sibling default.
        with self.assertRaises(ValueError):
            self._parse(MODEL.replace("@glb\n", "@glb\n@glb\n"))
        # Two identical write= targets collide outright.
        with self.assertRaises(ValueError):
            self._parse(MODEL.replace(
                '@stl(write="../STL/widget.stl")',
                '@stl(write="../STL/widget.stl")\n@stl(write="../STL/widget.stl")',
            ))

    def test_dxf_misuse_fails(self) -> None:
        with self.assertRaises(ValueError):
            self._parse(textwrap.dedent("""\
                from cadgen import dxf, stl

                @dxf
                @stl
                def drawing():
                    import ezdxf
                    return ezdxf.new()
                """))

    def test_runtime_decorators_converge_both_orders(self) -> None:
        from cadgen.authoring import step as step_deco, stl as stl_deco

        def below(size: float = 1.0):
            return None

        from cadgen.authoring import _REGISTRY, registered_model

        this_file = Path(__file__).resolve()
        self.addCleanup(_REGISTRY.pop, this_file, None)

        stl_deco(write="a.stl")(below)
        step_deco(below)
        model = registered_model(this_file)
        self.assertIsNotNone(model)
        self.assertEqual({d.fmt for d in model.mesh_exports}, {"stl"})

        # One model per file is a hard rule; clear the entry to model the
        # above-@step order as if in a fresh file.
        _REGISTRY.pop(this_file, None)

        def above(size: float = 1.0):
            return None

        step_deco(above)
        stl_deco(write="b.stl")(above)
        model = registered_model(this_file)
        self.assertEqual({d.fmt for d in model.mesh_exports}, {"stl"})


class MeshExportProductionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mesh-export-decl-")
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name).resolve()
        (self.project / "src").mkdir()
        (self.project / "src" / "widget.py").write_text(MODEL)
        self.env = dict(os.environ)
        self.env.update({
            "CADGEN_DAEMON": "0",
            "CADGEN_COMPONENT_WORKERS": "1",
            "CADGEN_CACHE_DIR": str(self.project / "store"),
            "PYTHONPATH": str(REPO / "packages/cadgen/src"),
        })

    def _run(self, *argv: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [PYTHON, *argv], cwd=str(self.project), env=self.env,
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def test_script_run_produces_heals_and_matches_cli(self) -> None:
        first = self._run("src/widget.py")
        for rel in ("STEP/widget.step", "STL/widget.stl", "STEP/widget.glb", "3MF/widget.3mf"):
            self.assertTrue((self.project / rel).is_file(), rel)
        self.assertIn("wrote STL", first.stdout)

        # True no-op: nothing rewritten.
        second = self._run("src/widget.py")
        self.assertNotIn("wrote", second.stdout)

        # Healing is per-export: delete one, only it comes back.
        (self.project / "STL" / "widget.stl").unlink()
        heal = self._run("src/widget.py")
        self.assertIn("wrote STL", heal.stdout)
        self.assertNotIn("wrote GLB", heal.stdout)

        # CLI parity: bare --stl targets the DECLARED path and the shared
        # ledger makes it a no-op; an explicit out is byte-identical.
        export = "from cadgen.cli.step_export import main; raise SystemExit(main())"
        skip = self._run("-c", export, "src/widget.py", "--stl", "--verbose")
        self.assertNotIn("tessellate", skip.stderr + skip.stdout)
        explicit = self.project / "parity.stl"
        self._run("-c", export, "src/widget.py", "--stl", str(explicit))
        self.assertEqual(
            explicit.read_bytes(),
            (self.project / "STL" / "widget.stl").read_bytes(),
            "CLI and script-produced STL must be byte-identical",
        )


if __name__ == "__main__":
    unittest.main()
