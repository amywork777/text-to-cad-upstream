import unittest
from typing import Any
from unittest import mock

import build123d
from OCP.BRepMesh import BRepMesh_IncrementalMesh

from cadgen._internal import glb_mesh_payload
from cadgen._internal.glb_mesh_payload import (
    ShapeGlbMeshPayload,
    prototype_glb_mesh_payload,
    shape_glb_mesh_payload,
)

DEFAULT_COLOR = (0.72, 0.72, 0.72, 1.0)


def _meshed_fixture_shape() -> Any:
    part = build123d.Box(20, 30, 10) + build123d.Cylinder(radius=6, height=40)
    part = part + build123d.Pos(10, 0, 0) * build123d.Sphere(radius=8)
    shape = part.wrapped
    BRepMesh_IncrementalMesh(shape, 0.1, True, 0.1, True).Perform()
    return shape


def _synthetic_prototype() -> dict[str, Any]:
    return {
        "edges": [
            {"ordinal": 1, "surfaceClassCode": 2},
            {"ordinal": 2, "surfaceClassCode": 0},
            {"ordinal": 3, "surfaceClassCode": 7},
        ],
        "faces": [
            {
                # Classified (ordinals 1 and 3), zero-class (ordinal 2), and
                # unmatched triangle sides on one face.
                "shapeHash": 11,
                "ordinal": 1,
                "triangleNodes": [
                    [0.0, 0.0, 0.0],
                    [10.0, 0.0, 0.0],
                    [0.0, 10.0, 0.0],
                    [10.0, 10.0, 0.0],
                ],
                "triangleNormals": [[0.0, 0.0, 1.0]] * 4,
                "triangles": [(0, 1, 2), (1, 3, 2)],
                "edgeSideOrdinals": {(0, 1): 1, (1, 3): 2, (2, 3): 3},
            },
            {
                # Face with an empty triangle list must be skipped entirely.
                "shapeHash": 12,
                "ordinal": 2,
                "triangleNodes": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "triangleNormals": [],
                "triangles": [],
            },
            {
                # No classified edges and no per-node normals: exercises the
                # face-normal fallback fill.
                "shapeHash": 13,
                "ordinal": 3,
                "triangleNodes": [[0.0, 0.0, 5.0], [5.0, 0.0, 5.0], [0.0, 5.0, 5.0]],
                "normal": (0.0, 0.0, 1.0),
                "triangles": [(0, 1, 2)],
            },
        ],
    }


class GlbMeshPayloadVectorizedTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_shape = _meshed_fixture_shape()

    def assert_payloads_byte_identical(
        self,
        actual: ShapeGlbMeshPayload,
        expected: ShapeGlbMeshPayload,
    ) -> None:
        self.assertEqual(actual.positions.tobytes(), expected.positions.tobytes())
        self.assertEqual(actual.normals.tobytes(), expected.normals.tobytes())
        self.assertEqual(actual.barycentrics.tobytes(), expected.barycentrics.tobytes())
        self.assertEqual(actual.edge_classes.tobytes(), expected.edge_classes.tobytes())
        self.assertEqual(len(actual.primitives), len(expected.primitives))
        for (actual_color, actual_indices), (expected_color, expected_indices) in zip(
            actual.primitives, expected.primitives
        ):
            self.assertEqual(actual_color, expected_color)
            self.assertEqual(actual_indices.tobytes(), expected_indices.tobytes())
        self.assertEqual(actual.minimum, expected.minimum)
        self.assertEqual(actual.maximum, expected.maximum)
        self.assertEqual(actual.face_runs_by_hash, expected.face_runs_by_hash)
        self.assertEqual(
            actual.surface_half_edges_by_face_ordinal,
            expected.surface_half_edges_by_face_ordinal,
        )

    def _prototype_payload_pair(
        self,
        prototype: dict[str, Any],
        *,
        face_colors: dict[int, tuple[float, float, float, float]],
        include_surface_edges: bool,
    ) -> tuple[ShapeGlbMeshPayload, ShapeGlbMeshPayload]:
        vectorized = prototype_glb_mesh_payload(
            prototype,
            default_color=DEFAULT_COLOR,
            face_colors=face_colors,
            include_surface_edges=include_surface_edges,
        )
        with mock.patch.object(glb_mesh_payload, "numpy", None):
            fallback = prototype_glb_mesh_payload(
                prototype,
                default_color=DEFAULT_COLOR,
                face_colors=face_colors,
                include_surface_edges=include_surface_edges,
            )
        return vectorized, fallback

    def test_numpy_runtime_is_available(self) -> None:
        self.assertIsNotNone(glb_mesh_payload.numpy)

    def test_synthetic_prototype_matches_python(self) -> None:
        prototype = _synthetic_prototype()
        for include_surface_edges in (True, False):
            with self.subTest(include_surface_edges=include_surface_edges):
                vectorized, fallback = self._prototype_payload_pair(
                    prototype,
                    face_colors={11: (0.0, 0.5, 1.0, 1.0)},
                    include_surface_edges=include_surface_edges,
                )
                self.assertIn(11, vectorized.face_runs_by_hash)
                self.assertIn(13, vectorized.face_runs_by_hash)
                # The empty-triangles face contributes nothing.
                self.assertNotIn(12, vectorized.face_runs_by_hash)
                if include_surface_edges:
                    # Ordinal 2 has class code 0 and never appears; only the
                    # classified sides of face ordinal 1 are recorded.
                    self.assertEqual(
                        sorted(vectorized.surface_half_edges_by_face_ordinal),
                        [1],
                    )
                    recorded_ordinals = {
                        entry[0]
                        for entry in vectorized.surface_half_edges_by_face_ordinal[1]
                    }
                    self.assertEqual(recorded_ordinals, {1, 3})
                else:
                    self.assertEqual(vectorized.surface_half_edges_by_face_ordinal, {})
                self.assert_payloads_byte_identical(vectorized, fallback)

    def test_shape_payload_matches_python(self) -> None:
        for include_surface_edges in (True, False):
            with self.subTest(include_surface_edges=include_surface_edges):
                vectorized = shape_glb_mesh_payload(
                    self.fixture_shape,
                    default_color=DEFAULT_COLOR,
                    face_colors={},
                    include_surface_edges=include_surface_edges,
                )
                with mock.patch.object(glb_mesh_payload, "numpy", None):
                    fallback = shape_glb_mesh_payload(
                        self.fixture_shape,
                        default_color=DEFAULT_COLOR,
                        face_colors={},
                        include_surface_edges=include_surface_edges,
                    )
                self.assertGreater(len(vectorized.positions), 0)
                self.assert_payloads_byte_identical(vectorized, fallback)


if __name__ == "__main__":
    unittest.main()
