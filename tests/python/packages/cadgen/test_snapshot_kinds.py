"""One snapshot implementation, one front door per FORMAT — so the door is what has to
be right.

Sharing the CLI makes every door mechanically capable of rendering every format. The
kind gate is the only thing left keeping `step snapshot` from quietly rendering a robot,
so these tests cover the gate rather than the rendering: what each door enables, that an
input it does not enable is refused BY NAME with somewhere to go, and that the refusal
happens before anything is built.

The mesh formats are the newest doors. `cadgen step snapshot` used to render `.stl`,
`.3mf` and `.glb` as well as STEP, which made one door the door for four formats; the
mesh arm moved to `cadgen stl|3mf|glb snapshot` unchanged. That cutover is what the
`MeshDoorSplit` cases pin: the STEP door refuses a mesh and says where it went, and each
mesh door takes its own format and nothing else.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen.cli.snapshot import ALL_KINDS  # noqa: E402
from cadgen.cli.snapshot import DOOR_KINDS as DECLARED_DOOR_KINDS  # noqa: E402
from cadgen.snapshot_cli import (  # noqa: E402
    KIND_RESOLVERS,
    SnapshotError,
    enabled_kinds,
    help_text,
    input_kind,
    resolve_render_job_packet,
)

# What each door declares. Written out rather than imported so a door that quietly
# widens its inputs fails HERE rather than shipping; the declaration itself is
# checked against this below.
DOOR_KINDS = {
    "step": ("step", "stp"),
    "stl": ("stl",),
    "3mf": ("3mf",),
    "glb": ("glb",),
    "dxf": ("dxf",),
    "urdf": ("urdf",),
    "srdf": ("srdf",),
    "sdf": ("sdf",),
}

MESH_DOORS = ("stl", "3mf", "glb")


class InputKindTests(unittest.TestCase):
    def test_compound_suffixes_are_not_read_as_their_last_one(self):
        # Path.suffix sees only `.py`, which would misread this one.
        self.assertEqual("dxf", input_kind(Path("panel.dxf.py")))
        # Suffix retirement: a plain .py classifies as python; dxf-ness comes from metadata.
        self.assertEqual("python", input_kind(Path("panel.py")))
        # A plain `.py` IS a STEP generator, which is why the two need telling apart.
        self.assertEqual("python", input_kind(Path("bracket.py")))

    def test_every_kind_it_names_has_a_resolver_or_is_a_generator(self):
        for sample in ("a.step", "a.stp", "a.glb", "a.stl", "a.3mf",
                       "a.urdf", "a.srdf", "a.sdf", "a.dxf"):
            kind = input_kind(Path(sample))
            self.assertTrue(kind, f"{sample} resolved to no kind")
            self.assertIn(kind, set(KIND_RESOLVERS) | {"python", "dxf"}, sample)


class EnabledKindsTests(unittest.TestCase):
    def test_the_declaration_is_what_this_file_says_it_is(self):
        self.assertEqual(DOOR_KINDS, DECLARED_DOOR_KINDS)

    def test_the_polymorphic_door_is_every_door_at_once(self):
        # `cadgen snapshot` routes by suffix, so it must be the union: a kind
        # reachable through no door at all would be unrenderable.
        self.assertEqual(
            {kind for kinds in DOOR_KINDS.values() for kind in kinds}, set(ALL_KINDS)
        )

    def test_enabling_step_enables_its_generator(self):
        # `.py` resolves as `python` before it collapses to `step`, so a door that
        # named only "step" would reject its own generators.
        self.assertIn("python", enabled_kinds(("step",)))

    def test_a_door_gets_only_what_it_declares(self):
        self.assertEqual({"dxf"}, set(enabled_kinds(DOOR_KINDS["dxf"])))
        self.assertEqual({"urdf"}, set(enabled_kinds(DOOR_KINDS["urdf"])))
        self.assertEqual({"stl"}, set(enabled_kinds(DOOR_KINDS["stl"])))

    def test_an_unknown_kind_is_a_programming_error(self):
        with self.assertRaises(SnapshotError):
            enabled_kinds(("gcode",))


class _Gate(unittest.TestCase):
    """Shared refusal helper. Not a case of its own — subclasses are the tests."""

    def _reject(self, door: str, filename: str, body: str = "x"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "models").mkdir()
            (root / "models" / filename).write_text(body, encoding="utf-8")
            with self.assertRaises(SnapshotError) as ctx:
                resolve_render_job_packet(
                    {"input": f"models/{filename}", "outputs": [{"path": "tmp/o.png"}]},
                    cwd=root,
                    kinds=enabled_kinds(DOOR_KINDS[door]),
                )
            return str(ctx.exception)


class KindGateTests(_Gate):
    def test_each_door_refuses_the_others_formats(self):
        cases = [
            ("step", "arm.urdf"),
            ("step", "panel.dxf"),
            ("dxf", "part.step"),
            ("urdf", "panel.dxf"),
            ("sdf", "part.step"),
            ("stl", "part.step"),
            ("glb", "mesh.stl"),
        ]
        for door, filename in cases:
            with self.subTest(door=door, filename=filename):
                message = self._reject(door, filename)
                self.assertIn("does not render", message)

    def test_a_refusal_never_points_at_another_skill(self):
        # Skills install independently, so naming one assumes something we cannot know.
        # A sibling cadgen COMMAND is a different matter -- see MeshDoorSplit below.
        for door, filename in (("step", "arm.urdf"), ("dxf", "part.step")):
            with self.subTest(door=door):
                message = self._reject(door, filename)
                for other in ("cad skill", "dxf skill", "urdf skill", "sdf skill"):
                    self.assertNotIn(other, message, message)

    def test_the_refusal_lists_what_this_door_does_take(self):
        # A bare "no" makes the reader go read the source; the accepted set is the answer.
        message = self._reject("step", "arm.urdf")
        self.assertIn(".step", message)
        self.assertIn(".stp", message)

    def test_a_step_generator_is_gated_as_step_not_as_python(self):
        # `.py` is rewritten to its logical `.step` path. Gating after that rewrite
        # would report a path the caller never named.
        message = self._reject("urdf", "bracket.py", body="def model(): ...")
        self.assertIn("bracket.py", message)


class MeshDoorSplit(_Gate):
    """`cadgen step snapshot` accepts ONLY STEP; meshes have doors of their own.

    The STEP door rendered meshes until this split, so its refusal has to TEACH
    rather than just refuse: a caller arriving with a `.stl` is following
    instructions that used to be right.
    """

    def test_the_step_door_refuses_every_mesh_format(self):
        for fmt, filename in (("stl", "part.stl"), ("3mf", "part.3mf"), ("glb", "part.glb")):
            with self.subTest(format=fmt):
                message = self._reject("step", filename)
                self.assertIn("does not render", message)
                self.assertIn(f"cadgen {fmt} snapshot", message)

    def test_a_mesh_door_takes_its_own_format_and_no_other(self):
        for fmt in MESH_DOORS:
            with self.subTest(format=fmt):
                self.assertEqual({fmt}, set(enabled_kinds(DOOR_KINDS[fmt])))

    def test_each_mesh_door_is_a_registered_command(self):
        from cadgen import cli

        for fmt in MESH_DOORS:
            with self.subTest(format=fmt):
                self.assertIn(f"{fmt} snapshot", cli._COMMANDS)

    def test_a_mesh_door_advertises_its_own_format_only(self):
        for fmt in MESH_DOORS:
            with self.subTest(format=fmt):
                text = help_text(kinds=enabled_kinds(DOOR_KINDS[fmt]))
                self.assertIn(f".{fmt}", text)
                for absent in (".step", ".urdf", "--params", "--focus", "--display"):
                    self.assertNotIn(absent, text, f"{absent} is not a mesh door's business")


class GeneratedHelpTests(unittest.TestCase):
    def test_help_describes_only_this_door(self):
        dxf_help = help_text(kinds=enabled_kinds(DOOR_KINDS["dxf"]))
        self.assertIn(".dxf", dxf_help)
        for absent in (".step", ".urdf", "--params", "--focus"):
            self.assertNotIn(absent, dxf_help, f"{absent} is not this door's business")

    def test_step_only_options_appear_for_the_step_door(self):
        step_help = help_text(kinds=enabled_kinds(DOOR_KINDS["step"]))
        for present in ("--params", "--focus", "section", "--view-labels"):
            self.assertIn(present, step_help)

    def test_theme_is_one_option_everywhere(self):
        for door, kinds in DOOR_KINDS.items():
            with self.subTest(door=door):
                text = help_text(kinds=enabled_kinds(kinds))
                self.assertIn("--theme", text)
                self.assertNotIn("--appearance", text)

    def test_display_is_offered_only_where_it_does_something(self):
        # Display settings ARE STEP topology settings -- mode, clip, exploded and edges all
        # need occurrences and CAD edges -- and every non-STEP resolver rejected all four.
        # Advertising the flag everywhere meant advertising an option that only errors.
        self.assertIn("--display", help_text(kinds=enabled_kinds(DOOR_KINDS["step"])))
        for door in ("stl", "3mf", "glb", "dxf", "urdf", "srdf", "sdf"):
            with self.subTest(door=door):
                self.assertNotIn("--display", help_text(kinds=enabled_kinds(DOOR_KINDS[door])))


if __name__ == "__main__":
    unittest.main()
