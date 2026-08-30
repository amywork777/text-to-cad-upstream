"""``write=`` became ``out=``, and the old name teaches rather than crashes.

The artifact destination used to have two names for one concept: the
decorators said ``write=`` while the door functions said ``out=``
(``stl.build(target, out=...)``) and the generated CLIs said ``OUT``. The
rename is a HARD cutover — ``write=`` is gone, not deprecated — so both
entrances to a model script must name the replacement:

- the RUNTIME decorators (``@step``/``@dxf``/``@stl``/``@glb``/``@threemf``),
  which a stale script hits when it is executed, and
- the AST parser (``parse_generator_metadata``), which a stale script hits
  when the catalog or a door reads it WITHOUT executing it.

A bare ``TypeError: unexpected keyword argument 'write'`` would leave the
reader to guess; these pin that they do not get one.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen.authoring import dxf, glb, step, stl, threemf  # noqa: E402
from cadgen.metadata import parse_generator_metadata  # noqa: E402

MODEL_DECORATORS = (("step", step), ("dxf", dxf))
MESH_DECORATORS = (("stl", stl), ("glb", glb), ("threemf", threemf))


def _parse(body: str):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "model.py"
        script.write_text(textwrap.dedent(body))
        return parse_generator_metadata(script)


class RenamedWriteKwargTest(unittest.TestCase):
    def _assert_teaches(self, message: str, deco_name: str) -> None:
        self.assertIn("write= was renamed to out=", message)
        self.assertIn(f"@{deco_name}", message)
        # The message must point at the concept, not just the spelling: one
        # name across the decorator, the doors, and the CLIs.
        self.assertIn("out=", message)
        self.assertIn("OUT positional", message)

    def test_runtime_model_decorators_name_out(self) -> None:
        for deco_name, decorator in MODEL_DECORATORS:
            with self.subTest(decorator=deco_name):
                with self.assertRaises(TypeError) as caught:
                    decorator(write=f"../OUT/widget.{deco_name}")
                self._assert_teaches(str(caught.exception), deco_name)
                self.assertIn("widget", str(caught.exception))

    def test_runtime_mesh_decorators_name_out(self) -> None:
        for deco_name, decorator in MESH_DECORATORS:
            with self.subTest(decorator=deco_name):
                with self.assertRaises(TypeError) as caught:
                    decorator(write="../STL/widget.stl")
                self._assert_teaches(str(caught.exception), deco_name)

    def test_runtime_still_rejects_genuinely_unknown_kwargs(self) -> None:
        """The teaching path must not swallow every typo into one message."""
        with self.assertRaises(TypeError) as caught:
            step(nonsense=1)
        self.assertIn("unexpected keyword argument", str(caught.exception))
        self.assertNotIn("renamed", str(caught.exception))

    def test_parsed_model_decorator_names_out(self) -> None:
        for deco_name in ("step", "dxf"):
            with self.subTest(decorator=deco_name):
                with self.assertRaises(ValueError) as caught:
                    _parse(f"""\
                        from cadgen import {deco_name}

                        @{deco_name}(write="../OUT/widget.{deco_name}")
                        def widget(size: float = 1.0):
                            return None
                        """)
                self._assert_teaches(str(caught.exception), deco_name)
                self.assertIn("widget", str(caught.exception))

    def test_parsed_mesh_decorator_names_out(self) -> None:
        for deco_name in ("stl", "glb", "threemf"):
            with self.subTest(decorator=deco_name):
                with self.assertRaises(ValueError) as caught:
                    _parse(f"""\
                        from cadgen import step, {deco_name}

                        @step(kind="part")
                        @{deco_name}(write="../MESH/widget.stl")
                        def widget(size: float = 1.0):
                            return None
                        """)
                self._assert_teaches(str(caught.exception), deco_name)

    def test_out_is_the_working_name(self) -> None:
        """The other half of the cutover: out= parses everywhere write= did."""
        metadata = _parse("""\
            from cadgen import glb, step, stl

            @step(out="../STEP/widget.step", kind="part")
            @stl(out="../STL/widget.stl")
            @glb
            def widget(size: float = 1.0):
                return None
            """)
        self.assertEqual(metadata.out_target, "../STEP/widget.step")
        self.assertEqual(
            {d.fmt: d.out for d in metadata.mesh_exports},
            {"stl": "../STL/widget.stl", "glb": None},
        )


if __name__ == "__main__":
    unittest.main()
