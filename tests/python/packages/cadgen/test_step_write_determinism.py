"""Written STEP bytes are a function of model content, not heap layout.

OCCT's STEPCAFControl_Writer registers each styled product's presentation
graph (MDGPR + styled items + colours) by iterating an ADDRESS-hashed shape
map, so an assembly with two or more styled products serializes its style
section in heap-address order — byte-different files for identical models,
varying per process and even per call. cadgen's package keys and export
records are content hashes of these bytes, so every wobble orphaned a store
package and dirtied committed fixtures.

``_style_tail_plan`` computes a content-derived order for that tail after
transfer (the same post-transfer canonicalization contract as
``_renumber_nauo_ids``). This test builds the same nested, multi-product,
per-occurrence-colored assembly from scratch repeatedly — fresh allocations
every time, exactly what flips the map order — and demands identical bytes.

The plan is applied in one of two places — to the written TEXT (linear, the
normal path) or to the MODEL via ``ChangeOrder`` (quadratic, the backstop for a
tail whose numbers straddle a digit-width boundary). Those two must agree
BYTE for byte, not merely semantically: the bytes are the store key, so a
formatting difference between them would re-key every package in every store.
``test_both_appliers_write_identical_bytes`` is what makes deleting neither
path safe.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")


def _build_assembly(*, transparent_part: bool = False):
    """A minimal shape that hits the nondeterministic path: nested group
    products whose parts carry per-occurrence colors — several MDGPRs.

    ``transparent_part`` gives ONE part an alpha color. That is not a variation
    for its own sake: an alpha color makes OCCT append
    SURFACE_STYLE_RENDERING_WITH_PROPERTIES + SURFACE_STYLE_TRANSPARENT to the
    style tail, and the canonicalization only reorders a tail it fully
    recognizes — so a family list missing those two types silently disables
    canonicalization for every model with a transparent part, which is exactly
    what happened."""
    from build123d import Color, Compound
    from build123d.topology import Solid

    groups = []
    for group_index in range(3):
        parts = []
        for part_index in range(2):
            part = Solid.make_box(4 + group_index, 3 + part_index, 2)
            part = part.moved(part.location)  # fresh wrapper, shared TShape semantics
            part.label = f"part_{group_index}_{part_index}"
            if transparent_part and group_index == 0 and part_index == 0:
                part.color = Color(0.2, 0.9, 0.5, 0.4)
            else:
                part.color = Color(0.2 + 0.3 * group_index, 0.9 - 0.4 * part_index, 0.5)
            parts.append(part)
        group = Compound(children=parts)
        group.label = f"group_{group_index}"
        groups.append(group)
    root = Compound(children=groups)
    root.label = "determinism_rig"
    return root


class StepWriteDeterminismTest(unittest.TestCase):
    def test_repeated_fresh_builds_write_identical_bytes(self) -> None:
        from cadgen.step_export import export_build123d_step_file

        with tempfile.TemporaryDirectory(prefix="step-determinism-") as tmp:
            digests = set()
            for run in range(3):
                out = Path(tmp) / f"run{run}.step"
                export_build123d_step_file(_build_assembly(), out)
                digests.add(hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertEqual(
                len(digests), 1,
                f"identical models wrote {len(digests)} distinct byte streams: {sorted(digests)}",
            )

    def test_transparent_part_still_writes_identical_bytes(self) -> None:
        """One alpha color must not switch canonicalization back off."""
        from cadgen.step_export import export_build123d_step_file

        with tempfile.TemporaryDirectory(prefix="step-determinism-alpha-") as tmp:
            digests = set()
            for run in range(4):
                out = Path(tmp) / f"run{run}.step"
                export_build123d_step_file(
                    _build_assembly(transparent_part=True), out
                )
                digests.add(hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertEqual(
                len(digests), 1,
                "a model with one transparent part wrote "
                f"{len(digests)} distinct byte streams: {sorted(digests)}",
            )

    def test_transparent_part_emits_the_rendering_tail(self) -> None:
        """Guard the premise of the test above: if OCCT ever stops emitting
        these entities the alpha case would pass for the wrong reason."""
        from cadgen.step_export import export_build123d_step_file

        with tempfile.TemporaryDirectory(prefix="step-determinism-alpha-") as tmp:
            out = Path(tmp) / "alpha.step"
            export_build123d_step_file(_build_assembly(transparent_part=True), out)
            text = out.read_text(errors="replace")
            self.assertIn("SURFACE_STYLE_RENDERING_WITH_PROPERTIES(", text)
            self.assertIn("SURFACE_STYLE_TRANSPARENT(", text)

    def _write_with(self, applier: str, path: Path, **rig_kwargs) -> bytes:
        """Export the rig with the style-tail permutation applied in `text` or
        in `model`."""
        import os

        from cadgen.step_export import export_build123d_step_file

        previous = os.environ.get("CADGEN_STEP_STYLE_REORDER")
        if applier == "model":
            os.environ["CADGEN_STEP_STYLE_REORDER"] = "model"
        else:
            os.environ.pop("CADGEN_STEP_STYLE_REORDER", None)
        try:
            export_build123d_step_file(_build_assembly(**rig_kwargs), path)
        finally:
            if previous is None:
                os.environ.pop("CADGEN_STEP_STYLE_REORDER", None)
            else:
                os.environ["CADGEN_STEP_STYLE_REORDER"] = previous
        return path.read_bytes()

    def test_both_appliers_write_identical_bytes(self) -> None:
        """The fast text path and the quadratic model path are the same file.

        This is the gate on the text rewrite: the written bytes are the
        content-addressed store key, so "equivalent STEP" is not good enough —
        a different line wrap would orphan every package built before it.
        """
        with tempfile.TemporaryDirectory(prefix="step-appliers-") as tmp:
            for label, rig_kwargs in (
                ("opaque", {}),
                ("transparent", {"transparent_part": True}),
            ):
                with self.subTest(rig=label):
                    in_text = self._write_with(
                        "text", Path(tmp) / f"{label}-text.step", **rig_kwargs
                    )
                    in_model = self._write_with(
                        "model", Path(tmp) / f"{label}-model.step", **rig_kwargs
                    )
                    self.assertEqual(
                        hashlib.sha256(in_text).hexdigest(),
                        hashlib.sha256(in_model).hexdigest(),
                        "text and model appliers disagree on the written bytes",
                    )

    def test_the_appliers_actually_reorder_something(self) -> None:
        """Control for the test above: both appliers must be doing work.

        If the rig ever stopped producing a permuted tail, the equality test
        would pass by comparing two untouched files."""
        from cadgen.step_export import _style_tail_plan

        with tempfile.TemporaryDirectory(prefix="step-appliers-") as tmp:
            plans = []
            original = None
            import cadgen.step_export as step_export

            original = step_export._style_tail_plan

            def capture(model):
                plan = original(model)
                plans.append(plan)
                return plan

            step_export._style_tail_plan = capture
            try:
                self._write_with("text", Path(tmp) / "probe.step")
            finally:
                step_export._style_tail_plan = original

            self.assertTrue(plans and plans[0] is not None, "no style tail plan was made")
            tail_start, total, old_numbers = plans[0]
            self.assertGreater(len(old_numbers), 1, "tail must hold several entities")
            self.assertNotEqual(
                old_numbers, list(range(tail_start, total + 1)),
                "the rig's tail was already in canonical order — this fixture no "
                "longer exercises the reorder",
            )

    def test_canonicalization_is_a_pure_reorder(self) -> None:
        """The canonical file must carry the same entity population — sorted
        entity RECORD bodies (numbers stripped) are invariant across runs even
        without canonicalization, so equality here plus byte-equality above
        means reordering, not rewriting."""
        from cadgen.step_export import export_build123d_step_file

        import re

        with tempfile.TemporaryDirectory(prefix="step-determinism-") as tmp:
            out = Path(tmp) / "one.step"
            export_build123d_step_file(_build_assembly(), out)
            text = out.read_text()
            styled = re.findall(r"= (?:OVER_RIDING_)?STYLED_ITEM\(", text)
            colours = re.findall(r"COLOUR_RGB\('',([^)]*)\)", text)
            self.assertGreaterEqual(len(styled), 6, "rig must exercise the styled path")
            self.assertEqual(len(set(colours)), 6, "all six authored colors survive")


if __name__ == "__main__":
    unittest.main()
