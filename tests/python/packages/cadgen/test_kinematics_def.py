"""cadgen.kinematics: the typed-mates declaration vocabulary.

Everything checkable without geometry is checked at decoration time and pinned
here: the closed key vocabulary, constructor-only entries, unique DOF names,
the FK-tree rules (one parent per occurrence, no cycles — closed loops are an
explicit deferral), coupling targets, pose presets over declared DOFs, and the
bake-pose selector. Axis selector refs resolve at build time and are only
syntax here.
"""

from __future__ import annotations

import unittest

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen.kinematics import (  # noqa: E402
    couple,
    cylindrical,
    normalize_bake_pose,
    normalize_kinematics,
    revolute,
    slider,
)


def _arm_block(**overrides):
    block = {
        "mates": [
            revolute("elbow", parent="#upper_arm", child="#forearm",
                     axis="#forearm.pivot_bore", limits=(0, 150)),
            slider("extend", parent="#rail", child="#carriage",
                   axis="#rail.f2", limits=(0, 80)),
        ],
        "couplings": [couple("curl", {"elbow": 0.5, "extend": 10})],
        "poses": {"open": {"elbow": 40}, "closed": {"elbow": 0, "extend": 0}},
    }
    block.update(overrides)
    return block


class ConstructorTests(unittest.TestCase):
    def test_a_mate_serializes_its_declaration(self) -> None:
        mate = revolute("elbow", parent="#upper_arm", child="#forearm",
                        axis="#forearm.pivot_bore", limits=(0, 150))
        self.assertEqual(mate.kind, "revolute")
        self.assertEqual(mate.axis, {"ref": "#forearm.pivot_bore"})
        self.assertEqual(mate.limits, {"value": [0.0, 150.0]})
        self.assertEqual(mate.dof_ids(), ("elbow",))

    def test_default_is_a_teaching_error(self) -> None:
        # Zero IS the artifact as written; a "default" slider value would
        # displace geometry the moment a panel opened.
        with self.assertRaisesRegex(ValueError, "default= was dropped"):
            revolute("elbow", parent="#a", child="#b", axis="#b.f1",
                     limits=(0, 150), default=90)

    def test_literal_axes_take_origin_and_direction(self) -> None:
        mate = slider("lift", parent="#base", child="#mast",
                      origin=(0, 0, 5), direction=(0, 0, 1), limits=(0, 100))
        self.assertEqual(mate.axis, {"origin": [0.0, 0.0, 5.0], "dir": [0.0, 0.0, 1.0]})
        with self.assertRaisesRegex(ValueError, "both axis= .* and origin="):
            slider("l2", parent="#a", child="#b", axis="#a.f1",
                   origin=(0, 0, 0), direction=(0, 0, 1), limits=(0, 1))
        with self.assertRaisesRegex(ValueError, "direction must be non-zero"):
            slider("l3", parent="#a", child="#b", origin=(0, 0, 0),
                   direction=(0, 0, 0), limits=(0, 1))

    def test_cylindrical_declares_two_sub_dofs(self) -> None:
        mate = cylindrical("lead", parent="#housing", child="#screw", axis="#screw.f1",
                           limits={"turn": (0, 3600), "travel": (0, 40)})
        self.assertEqual(mate.dof_ids(), ("lead.turn", "lead.travel"))
        with self.assertRaisesRegex(ValueError, "limits must be a dict over its sub-DOFs"):
            cylindrical("bad", parent="#a", child="#b", axis="#b.f1", limits=(0, 1))

    def test_refs_axes_limits_and_defaults_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "parent must be an occurrence ref"):
            revolute("j", parent="upper_arm", child="#forearm", axis="#a.f1", limits=(0, 1))
        with self.assertRaisesRegex(ValueError, "needs an axis"):
            revolute("j", parent="#a", child="#b", limits=(0, 1))
        with self.assertRaisesRegex(ValueError, "hi > lo"):
            revolute("j", parent="#a", child="#b", axis="#b.f1", limits=(5, 5))
        with self.assertRaisesRegex(ValueError, "needs limits"):
            revolute("j", parent="#a", child="#b", axis="#b.f1")
        with self.assertRaisesRegex(ValueError, "without dots"):
            revolute("el.bow", parent="#a", child="#b", axis="#b.f1", limits=(0, 1))

    def test_couple_is_data_only(self) -> None:
        coupling = couple("curl", {"mcp": 50, "pip": 70}, limits=(0, 2))
        self.assertEqual(coupling.gears, {"mcp": 50.0, "pip": 70.0})
        self.assertEqual(coupling.limits, [0.0, 2.0])
        with self.assertRaisesRegex(ValueError, "non-empty dict"):
            couple("curl", {})
        with self.assertRaisesRegex(ValueError, "must be a number"):
            couple("curl", {"mcp": lambda t: t})


class NormalizeTests(unittest.TestCase):
    def test_a_full_declaration_normalizes_to_the_sidecar_shape(self) -> None:
        defn = normalize_kinematics(_arm_block(), where="@step")
        self.assertEqual(
            [m["name"] for m in defn.block["mates"]], ["elbow", "extend"]
        )
        self.assertEqual(defn.block["mates"][0]["axis"], {"ref": "#forearm.pivot_bore"})
        self.assertEqual(defn.block["couplings"][0]["gears"], {"elbow": 0.5, "extend": 10.0})
        self.assertEqual(defn.block["poses"]["open"], {"elbow": 40.0})
        self.assertEqual(defn.dof_ids(), ("elbow", "extend", "curl"))

    def test_the_key_vocabulary_is_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown key.*animation is its own @step kwarg"):
            normalize_kinematics(_arm_block(animation="x.js"), where="@step")
        with self.assertRaisesRegex(ValueError, "must be a dict"):
            normalize_kinematics([revolute("j", parent="#a", child="#b", axis="#b.f1", limits=(0, 1))], where="@step")

    def test_entries_must_come_from_the_constructors(self) -> None:
        with self.assertRaisesRegex(ValueError, "built by\\s+cadgen.revolute"):
            normalize_kinematics({"mates": [{"name": "elbow", "kind": "revolute"}]}, where="@step")
        with self.assertRaisesRegex(ValueError, "built by cadgen.couple"):
            normalize_kinematics(_arm_block(couplings=[{"name": "curl"}]), where="@step")

    def test_dof_names_are_unique_across_mates_and_couplings(self) -> None:
        dup = _arm_block()
        dup["mates"].append(revolute("elbow", parent="#a", child="#b", axis="#b.f1", limits=(0, 1)))
        with self.assertRaisesRegex(ValueError, "duplicate mate/DOF name 'elbow'"):
            normalize_kinematics(dup, where="@step")
        with self.assertRaisesRegex(ValueError, "collides with a mate name"):
            normalize_kinematics(_arm_block(couplings=[couple("elbow", {"extend": 1})]), where="@step")

    def test_the_mate_graph_is_a_tree(self) -> None:
        two_parents = {
            "mates": [
                revolute("a", parent="#base", child="#arm", axis="#arm.f1", limits=(0, 1)),
                slider("b", parent="#rail", child="#arm", axis="#rail.f1", limits=(0, 1)),
            ]
        }
        with self.assertRaisesRegex(ValueError, "more than one parent mate.*closed loops"):
            normalize_kinematics(two_parents, where="@step")
        cycle = {
            "mates": [
                revolute("a", parent="#x", child="#y", axis="#y.f1", limits=(0, 1)),
                revolute("b", parent="#y", child="#x", axis="#x.f1", limits=(0, 1)),
            ]
        }
        with self.assertRaisesRegex(ValueError, "cycle.*closed-loop"):
            normalize_kinematics(cycle, where="@step")
        with self.assertRaisesRegex(ValueError, "mates '#x' to itself"):
            normalize_kinematics(
                {"mates": [revolute("a", parent="#x", child="#x", axis="#x.f1", limits=(0, 1))]},
                where="@step",
            )

    def test_couplings_gear_declared_mate_dofs_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "gears unknown DOF 'wrist'"):
            normalize_kinematics(_arm_block(couplings=[couple("curl", {"wrist": 1})]), where="@step")

    def test_poses_name_declared_dofs_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown DOF 'wrist'"):
            normalize_kinematics(_arm_block(poses={"broken": {"wrist": 5}}), where="@step")

    def test_an_empty_declaration_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "declares no mates"):
            normalize_kinematics({"poses": {}}, where="@step")


class BakePoseTests(unittest.TestCase):
    def test_a_preset_name_resolves_to_its_values(self) -> None:
        defn = normalize_kinematics(_arm_block(), where="@stl")
        self.assertEqual(normalize_bake_pose("open", defn, where="@stl"), {"elbow": 40.0})

    def test_a_value_dict_is_validated_against_declared_dofs(self) -> None:
        defn = normalize_kinematics(_arm_block(), where="@stl")
        self.assertEqual(
            normalize_bake_pose({"elbow": 90, "curl": 0.5}, defn, where="@stl"),
            {"elbow": 90.0, "curl": 0.5},
        )
        with self.assertRaisesRegex(ValueError, "unknown DOF 'wrist'"):
            normalize_bake_pose({"wrist": 1}, defn, where="@stl")

    def test_an_unknown_preset_teaches_the_declared_ones(self) -> None:
        defn = normalize_kinematics(_arm_block(), where="@glb")
        with self.assertRaisesRegex(ValueError, "not a declared preset; poses: closed, open"):
            normalize_bake_pose("wide", defn, where="@glb")

    def test_pose_without_kinematics_teaches_independence(self) -> None:
        with self.assertRaisesRegex(ValueError, "SAME decorator"):
            normalize_bake_pose("open", None, where="@stl")


if __name__ == "__main__":
    unittest.main()
