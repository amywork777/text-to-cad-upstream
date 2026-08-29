"""cadgen.pose(): the closed declarative vocabulary, and its descriptor emission.

Validation is the contract: a pose typo must fail at decoration time with an
error naming the offender — never silently do nothing at render time. The
end-to-end half pins the transport: the block lands in assembly.json as
`pose`, the escape-hatch module is copied content-addressed into components/,
and the retired `.params.js` envelope field is a teaching error.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen.posedef import pose  # noqa: E402
from tests.python.support.cad_test_roots import IsolatedCadRoots  # noqa: E402

PARAMS = {"drive": {"type": "number", "min": 0, "max": 360, "default": 0}}
FEATURES = {"wheel": {"names": ["wheel"]}}
JOINTS = [{"id": "spin", "feature": "wheel", "kind": "rotate", "axis": [0, 0, 1]}]


class PoseValidationTests(unittest.TestCase):
    def _fails(self, message_fragment: str, **kwargs) -> None:
        with self.assertRaises(ValueError) as caught:
            pose(**kwargs)
        self.assertIn(message_fragment, str(caught.exception))

    def test_empty_pose_is_rejected(self) -> None:
        self._fails("declares nothing")

    def test_unknown_driver_kind_is_a_closed_vocabulary_error(self) -> None:
        self._fails(
            "closed vocabulary",
            params=PARAMS,
            features=FEATURES,
            drivers=[{"kind": "waypointPath", "param": "drive"}],
        )

    def test_unknown_fields_are_errors(self) -> None:
        self._fails(
            "unknown field",
            params={"drive": {"type": "number", "speed": 3}},
        )

    def test_driver_references_must_resolve(self) -> None:
        self._fails(
            "unknown param",
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS,
            drivers=[{"kind": "joint", "joint": "spin", "param": "missing"}],
        )
        self._fails(
            "unknown feature",
            params=PARAMS,
            features=FEATURES,
            drivers=[{"kind": "translate", "feature": "nope", "param": "drive", "direction": [1, 0, 0]}],
        )
        self._fails(
            "unknown joint",
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS,
            drivers=[{"kind": "joint", "joint": "nope", "param": "drive"}],
        )

    def test_one_joint_per_feature_and_ordered_ratio_sources(self) -> None:
        self._fails(
            "more than one joint",
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS + [{"id": "spin2", "feature": "wheel", "kind": "rotate"}],
        )
        self._fails(
            "must be declared before",
            params=PARAMS,
            features={"a": {"names": ["a"]}, "b": {"names": ["b"]}},
            joints=[
                {"id": "j1", "feature": "a", "kind": "rotate"},
                {"id": "j2", "feature": "b", "kind": "rotate"},
            ],
            drivers=[{"kind": "ratio", "joint": "j1", "source": "j2", "ratio": 2.0}],
        )

    def test_windows_easings_and_enum_options_are_checked(self) -> None:
        self._fails(
            "window must have end > start",
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS,
            drivers=[{"kind": "joint", "joint": "spin", "param": "drive", "window": [1, 1]}],
        )
        self._fails(
            "easing",
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS,
            drivers=[{"kind": "joint", "joint": "spin", "param": "drive", "easing": "bouncy"}],
        )
        self._fails("enum and must declare", params={"mode": {"type": "enum"}})

    def test_animation_keys_must_ascend_within_unit_time(self) -> None:
        self._fails(
            "strictly ascending",
            params=PARAMS,
            animations={
                "sweep": {
                    "duration": 2,
                    "tracks": [{"param": "drive", "keys": [{"t": 0.5, "value": 0}, {"t": 0.5, "value": 1}]}],
                }
            },
        )

    def test_style_driver_needs_exactly_one_of_style_or_palettes(self) -> None:
        self._fails(
            "exactly one of",
            params=PARAMS,
            features=FEATURES,
            drivers=[{"kind": "style", "target": "wheel", "param": "drive"}],
        )
        self._fails(
            "needs a param",
            params=PARAMS,
            features=FEATURES,
            drivers=[{"kind": "style", "target": "wheel", "style": {"opacity": {"from": 1, "to": 0}}}],
        )

    def test_normalization_shape(self) -> None:
        block = pose(
            params=PARAMS,
            features=FEATURES,
            joints=JOINTS,
            drivers=[{"kind": "joint", "joint": "spin", "param": "drive", "scale": 2}],
            animations={
                "sweep": {
                    "duration": 4,
                    "tracks": [{"param": "drive", "keys": [{"t": 0, "value": 0}, {"t": 1, "value": 360}]}],
                }
            },
        ).block
        self.assertEqual(block["schemaVersion"], 1)
        self.assertEqual(block["drivers"][0], {
            "kind": "joint", "joint": "spin", "param": "drive", "scale": 2.0, "offset": 0.0,
        })
        self.assertTrue(block["animations"]["sweep"]["loop"])
        self.assertEqual(block["joints"][0]["axis"], [0.0, 0.0, 1.0])


POSED_MODEL = """
from cadgen import pose, step
from cadgen import build123d as bd

@step(pose=pose(
    params={"lift": {"type": "number", "min": 0, "max": 10, "default": 0, "unit": "mm"}},
    features={"body": {"names": ["body"]}},
    drivers=[{"kind": "translate", "feature": "body", "param": "lift",
              "direction": [0, 0, 1], "distance": 1.0}],
    animations={"bounce": {"duration": 2, "loop": True, "tracks": [
        {"param": "lift", "keys": [{"t": 0, "value": 0}, {"t": 1, "value": 10, "easing": "sine"}]}]}},
    {module}
))
def model():
    return bd.Box(4.0, 4.0, 4.0)
"""

LEGACY_ENVELOPE_MODEL = """
from cadgen import step
from cadgen import build123d as bd

@step
def model():
    return {"shape": bd.Box(4.0, 4.0, 4.0), "params": "model.params.js"}
"""


class PoseEmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._roots = IsolatedCadRoots(self, prefix="cadpose-")
        self._tempdir = self._roots.temporary_cad_directory(prefix="tmp-cadpose-")
        self.root = Path(self._tempdir.name)

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def _build(self, script: Path) -> int:
        from cadgen.catalog import StepImportOptions
        from cadgen.generation import generate_step_targets

        out = script.with_suffix(".step")
        return generate_step_targets(
            [f"{script}={out.as_posix()}"],
            step_options=StepImportOptions(),
            force=True,
            verbose=False,
        )

    def _descriptor(self, script: Path) -> dict:
        package = script.parent / "__cadgen__" / "models" / f"{script.stem}.step"
        return json.loads((package / "assembly.json").read_text())

    def test_pose_block_lands_in_the_descriptor(self) -> None:
        script = self.root / "widget.py"
        script.write_text(POSED_MODEL.replace("{module}", ""), encoding="utf-8")
        self.assertEqual(0, self._build(script))
        descriptor = self._descriptor(script)
        block = descriptor.get("pose")
        self.assertIsInstance(block, dict)
        self.assertEqual(block["schemaVersion"], 1)
        self.assertIn("lift", block["params"])
        self.assertEqual(block["drivers"][0]["kind"], "translate")
        self.assertIn("bounce", block["animations"])
        self.assertNotIn("paramsPath", descriptor)

    def test_hatch_module_is_copied_content_addressed(self) -> None:
        script = self.root / "gadget.py"
        hatch = self.root / "_pose" / "gadget_extras.js"
        hatch.parent.mkdir()
        hatch.write_text("export function update() {}\n", encoding="utf-8")
        script.write_text(
            POSED_MODEL.replace("{module}", 'module="_pose/gadget_extras.js",'),
            encoding="utf-8",
        )
        self.assertEqual(0, self._build(script))
        descriptor = self._descriptor(script)
        ref = descriptor["pose"]["module"]
        self.assertRegex(ref, r"^components/[0-9a-f]{12}\.pose\.js$")
        copied = script.parent / "__cadgen__" / "models" / f"{script.stem}.step" / ref
        self.assertEqual(copied.read_text(), hatch.read_text())

    def test_missing_hatch_module_fails_the_build(self) -> None:
        script = self.root / "broken.py"
        script.write_text(
            POSED_MODEL.replace("{module}", 'module="nope.js",'), encoding="utf-8"
        )
        with self.assertRaises(FileNotFoundError) as caught:
            self._build(script)
        self.assertIn("pose module not found", str(caught.exception))

    def test_legacy_envelope_params_is_a_teaching_error(self) -> None:
        script = self.root / "legacy.py"
        (self.root / "model.params.js").write_text("export default {}\n", encoding="utf-8")
        script.write_text(LEGACY_ENVELOPE_MODEL, encoding="utf-8")
        with self.assertRaises(TypeError) as caught:
            self._build(script)
        self.assertIn("@step(pose=...)", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
