"""cadgen.interference: pairwise part-vs-part clash detection."""

import unittest

from build123d import Box, Pos

from cadgen.interference import Occurrence, _shape_bbox, find_clashes


def occurrence(ref, name, shape):
    return Occurrence(ref=ref, name=name, shape=shape.wrapped, bbox=_shape_bbox(shape.wrapped))


class FindClashesTest(unittest.TestCase):
    def setUp(self):
        self.a = occurrence("o1.1", "block_a", Pos(0, 0, 0) * Box(100, 100, 100))
        # overlaps a by 20 mm across a 100x100 face -> 200000 mm^3
        self.overlapping = occurrence("o1.2", "block_b", Pos(80, 0, 0) * Box(100, 100, 100))
        self.far = occurrence("o1.3", "block_c", Pos(0, 400, 0) * Box(100, 100, 100))
        self.touching = occurrence("o1.4", "block_d", Pos(0, 100, 0) * Box(100, 100, 100))

    def test_reports_a_real_overlap_with_its_volume(self):
        clashes, _stats = find_clashes([self.a, self.overlapping])
        self.assertEqual(len(clashes), 1)
        self.assertAlmostEqual(clashes[0].volume, 200000.0, delta=1.0)
        self.assertEqual({clashes[0].a_ref, clashes[0].b_ref}, {"o1.1", "o1.2"})

    def test_separated_parts_are_rejected_by_bbox_without_a_boolean(self):
        clashes, stats = find_clashes([self.a, self.far])
        self.assertEqual(clashes, [])
        self.assertEqual(stats["pairs_skipped_bbox"], 1)
        self.assertEqual(stats["pairs_tested"], 0)

    def test_touching_faces_are_contact_not_a_clash(self):
        # Neighbouring panels share a face by design; a sliver must not be a clash.
        clashes, stats = find_clashes([self.a, self.touching])
        self.assertEqual(clashes, [], "coincident faces are contact, not interpenetration")
        self.assertGreaterEqual(stats["pairs_tested"], 1, "and it must actually be tested")

    def test_tolerance_can_be_raised_to_ignore_small_overlaps(self):
        clashes, _stats = find_clashes([self.a, self.overlapping], tolerance=500000.0)
        self.assertEqual(clashes, [])

    def test_stats_distinguish_nothing_overlapped_from_nothing_tested(self):
        _clashes, stats = find_clashes([self.a, self.overlapping, self.far, self.touching])
        self.assertEqual(stats["occurrences"], 4)
        self.assertEqual(stats["pairs_total"], 6)
        self.assertGreater(stats["pairs_tested"], 0)

    def test_max_pairs_truncation_is_reported(self):
        _clashes, stats = find_clashes(
            [self.a, self.overlapping, self.touching], max_pairs=0
        )
        self.assertEqual(stats["pairs_tested"], 0)
        self.assertGreater(stats["pairs_truncated"], 0, "silent truncation would fake a pass")

    def test_clashes_are_sorted_worst_first(self):
        small = occurrence("o1.5", "small", Pos(0, 0, 98) * Box(100, 100, 100))
        clashes, _stats = find_clashes([self.a, self.overlapping, small])
        self.assertGreaterEqual(len(clashes), 2)
        volumes = [clash.volume for clash in clashes]
        self.assertEqual(volumes, sorted(volumes, reverse=True))


class InstanceTreeOccurrenceTest(unittest.TestCase):
    """A compound_from_instances assembly places instances at the OCCT level,
    so the in-memory scene's XCAF walk sees ONE childless leaf: a 26-instance
    arm reported 0 pairs tested and PASSed green. The scene now carries the
    explicit occurrence tree, and interference walks THAT — the same o1.N
    namespace `inspect refs` resolves."""

    def _scene(self):
        import tempfile
        from pathlib import Path

        from build123d import Location

        from cadgen.instances import compound_from_instances
        from cadgen.step_export import build_build123d_step_scene

        proto = Box(10, 10, 10)
        proto.label = "cube"
        compound = compound_from_instances(
            "pair",
            [
                (proto, Location((0, 0, 0)), "a"),
                (proto, Location((5, 0, 0)), "b"),  # 5 mm overlap with a
                (proto, Location((100, 0, 0)), "c"),
            ],
        )
        with tempfile.TemporaryDirectory(prefix="cadgen-interfere-") as tempdir:
            return build_build123d_step_scene(compound, Path(tempdir) / "pair.step")

    def test_scene_carries_the_instance_tree(self):
        scene = self._scene()
        self.assertIsNotNone(scene.instance_occurrence_tree)

    def test_instanced_assembly_flattens_to_placed_leaves(self):
        from cadgen.interference import occurrences_from_scene

        occurrences = occurrences_from_scene(self._scene())
        self.assertEqual(
            ["o1.1", "o1.2", "o1.3"], [occurrence.ref for occurrence in occurrences]
        )
        self.assertEqual(["a", "b", "c"], [occurrence.name for occurrence in occurrences])
        # Placements must be WORLD placements: c sits at x=100.
        self.assertAlmostEqual(occurrences[2].bbox[0], 95.0, delta=1e-6)

    def test_instanced_assembly_clash_is_found(self):
        from cadgen.interference import occurrences_from_scene

        occurrences = occurrences_from_scene(self._scene())
        clashes, stats = find_clashes(occurrences, tolerance=0.01)
        self.assertEqual(stats["occurrences"], 3)
        self.assertGreater(stats["pairs_tested"], 0, "zero pairs tested was the silent pass")
        self.assertEqual(len(clashes), 1)
        self.assertAlmostEqual(clashes[0].volume, 500.0, delta=1.0)
        self.assertEqual({clashes[0].a_ref, clashes[0].b_ref}, {"o1.1", "o1.2"})

    def test_label_rows_come_from_the_same_tree(self):
        from cadgen.interference import scene_label_rows

        rows = {row["id"]: row["name"] for row in scene_label_rows(self._scene())}
        self.assertEqual(rows.get("o1.2"), "b")


class InconclusiveVerdictTest(unittest.TestCase):
    """`pairs tested == 0` because fewer than two occurrences were selected is
    not a pass — inspect_interference reports conclusive=False and ok=False so
    text (INCONCLUSIVE) and exit codes cannot render it as green."""

    def test_inconclusive_text_never_says_pass(self):
        from cadgen.cli.step_inspect.cli import _format_interfere_text

        text = _format_interfere_text(
            {
                "ok": False,
                "entry": "tom",
                "tolerance": 0.01,
                "stats": {
                    "occurrences": 1,
                    "pairs_total": 0,
                    "pairs_tested": 0,
                    "pairs_skipped_bbox": 0,
                    "pairs_truncated": 0,
                },
                "conclusive": False,
                "inconclusiveReason": "the document presents 1 leaf occurrence(s); "
                "at least two are needed to test a pair",
                "clashCount": 0,
                "clashes": [],
                "errors": [],
            }
        )
        self.assertIn("INCONCLUSIVE", text)
        self.assertNotIn("PASS", text)

    def test_conclusive_clean_run_still_passes(self):
        from cadgen.cli.step_inspect.cli import _format_interfere_text

        text = _format_interfere_text(
            {
                "ok": True,
                "entry": "tom",
                "tolerance": 0.01,
                "stats": {
                    "occurrences": 2,
                    "pairs_total": 1,
                    "pairs_tested": 0,
                    "pairs_skipped_bbox": 1,
                    "pairs_truncated": 0,
                },
                "conclusive": True,
                "clashCount": 0,
                "clashes": [],
                "errors": [],
            }
        )
        self.assertIn("PASS", text)


if __name__ == "__main__":
    unittest.main()
