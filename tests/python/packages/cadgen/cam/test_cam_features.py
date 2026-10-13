"""``cadgen cam features``: the block's holes, floors and pocket, read off the exact part."""

from __future__ import annotations

import unittest

from tests.python.support.cam_fixtures import BLOCK, block_step, class_directory, floor_ref


class BlockFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cadgen import cam

        cls.directory = class_directory(cls)
        cls.step = block_step(cls.directory)
        cls.result = cam.features(cls.step)

    def test_the_four_through_holes_at_their_centres(self):
        holes = self.result.holes
        self.assertEqual(4, len(holes))
        centres = sorted((round(h["center_mm"][0], 3), round(h["center_mm"][1], 3)) for h in holes)
        self.assertEqual(sorted(BLOCK["holes"]["centers"]), centres)
        for hole in holes:
            self.assertAlmostEqual(5.0, hole["diameter_mm"], places=4)
            self.assertAlmostEqual(25.0, hole["depth_mm"], places=3)
            self.assertTrue(hole["through"])
            self.assertEqual("+Z", hole["axis_word"])
            self.assertAlmostEqual(25.0, hole["center_mm"][2], places=3)

    def test_floors_top_bottom_and_the_stepped_pocket(self):
        kinds = sorted((f["kind"], f["z_mm"]) for f in self.result.floors)
        self.assertIn(("top", 25.0), kinds)
        self.assertIn(("bottom", 0.0), kinds)
        self.assertIn(("floor", 17.0), kinds)
        self.assertIn(("floor", 11.0), kinds)
        upper = next(f for f in self.result.floors if f["ref"] == floor_ref(self.result, 17.0))
        self.assertAlmostEqual(8.0, upper["pocket"]["depth_mm"], places=3)
        self.assertEqual(1, upper["pocket"]["islands"])
        lower = next(f for f in self.result.floors if f["ref"] == floor_ref(self.result, 11.0))
        self.assertAlmostEqual(6.0, lower["pocket"]["depth_mm"], places=3)

    def test_every_face_has_a_reading_and_the_box(self):
        self.assertTrue(self.result.ok)
        self.assertEqual([80.0, 60.0, 25.0], [round(v, 3) for v in self.result.bbox_mm["size"]])
        self.assertTrue(all(face["reading"] for face in self.result.faces))
        hole_faces = [f for f in self.result.faces if f.get("hole")]
        self.assertTrue(hole_faces and all("hole wall Ø5 along Z" in f["reading"] for f in hole_faces))
        island = [f for f in self.result.faces if f["surface"] == "cylinder" and f.get("hole") is False]
        self.assertTrue(island and "(outside)" in island[0]["reading"])
        lines = self.result.human_lines()
        self.assertIn("80 x 60 x 25 mm", lines[0])

    def test_the_mesh_faces_match_the_scene_ordinals(self):
        import numpy as np

        from cadgen._internal.cam.part import read_part

        part = read_part(self.step)
        for ordinal, info in part.faces.items():
            with self.subTest(face=info.ref):
                selection = part._scene.resolve(info.ref)
                centre = selection.shape().center()
                rows = np.asarray(part.triangles)[np.asarray(part.face_of_triangle) == ordinal]
                points = np.asarray(part.vertices)[np.unique(rows)]
                low, high = points.min(axis=0) - 1e-6, points.max(axis=0) + 1e-6
                self.assertTrue(np.all(low <= [centre.X, centre.Y, centre.Z]) or info.surface != "plane")
                self.assertTrue(np.all([centre.X, centre.Y, centre.Z] <= high) or info.surface != "plane")

    def test_a_ref_that_is_not_a_face_teaches(self):
        from cadgen._internal.cam.job_errors import CamJobError
        from cadgen._internal.cam.part import read_part

        part = read_part(self.step)
        with self.assertRaises(CamJobError) as caught:
            part.face("#o1.f999")
        self.assertIn("cadgen cam features lists them", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
