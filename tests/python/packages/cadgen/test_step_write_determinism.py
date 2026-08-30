"""Written STEP bytes are a function of model content, not heap layout.

OCCT's STEPCAFControl_Writer registers each styled product's presentation
graph (MDGPR + styled items + colours) by iterating an ADDRESS-hashed shape
map, so an assembly with two or more styled products serializes its style
section in heap-address order — byte-different files for identical models,
varying per process and even per call. cadgen's package keys and export
records are content hashes of these bytes, so every wobble orphaned a store
package and dirtied committed fixtures.

``_canonicalize_presentation_styles`` reorders that tail into content order
after transfer (the same post-transfer canonicalization contract as
``_renumber_nauo_ids``). This test builds the same nested, multi-product,
per-occurrence-colored assembly from scratch repeatedly — fresh allocations
every time, exactly what flips the map order — and demands identical bytes.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")


def _build_assembly():
    """A minimal shape that hits the nondeterministic path: nested group
    products whose parts carry per-occurrence colors — several MDGPRs."""
    from build123d import Color, Compound
    from build123d.topology import Solid

    groups = []
    for group_index in range(3):
        parts = []
        for part_index in range(2):
            part = Solid.make_box(4 + group_index, 3 + part_index, 2)
            part = part.moved(part.location)  # fresh wrapper, shared TShape semantics
            part.label = f"part_{group_index}_{part_index}"
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
