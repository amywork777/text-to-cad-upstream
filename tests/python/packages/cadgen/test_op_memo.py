"""Op-memoization invariants (design/incremental-generation.md, Phase 1).

The contract under test: memoized kernel ops return canonically reconstructed
shapes whose bytes are independent of cache state (cold or warm, first run or
tenth), never mutate or consume caller arguments, and fall through untouched
for anything they cannot key or store.
"""

from __future__ import annotations

import hashlib
import io
import os
import unittest

from cadgen._internal import op_memo


def _digest(shape) -> str:
    from OCP.BinTools import BinTools, BinTools_FormatVersion

    stream = io.BytesIO()
    BinTools.Write_s(shape.wrapped, stream, False, False,
                     BinTools_FormatVersion.BinTools_FormatVersion_CURRENT)
    return hashlib.sha256(stream.getvalue()).hexdigest()


def _build_part():
    from build123d.topology import Solid

    box = Solid.make_box(20, 20, 8)
    return box.cut(Solid.make_cylinder(3, 12))


class OpMemoTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        op_memo.install()
        op_memo.clear()
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["CADGEN_OP_MEMO"] = "1"
        self._prev_store = os.environ.get("CADGEN_STORE_DIR")
        os.environ["CADGEN_STORE_DIR"] = self._tmp.name

    def tearDown(self):
        op_memo.clear()
        os.environ.pop("CADGEN_OP_MEMO", None)
        if self._prev_store is None:
            os.environ.pop("CADGEN_STORE_DIR", None)
        else:
            os.environ["CADGEN_STORE_DIR"] = self._prev_store
        self._tmp.cleanup()

    def test_install_is_idempotent(self):
        from build123d.topology import Face

        self.assertFalse(op_memo.install())  # second call is a no-op
        self.assertTrue(getattr(Face.make_surface.__func__, "__op_memo__", False))

    def test_cache_state_independence(self):
        first = _build_part()
        stats_before = op_memo.stats()
        second = _build_part()
        stats_after = op_memo.stats()
        self.assertGreater(stats_after["hits"], stats_before["hits"])
        self.assertEqual(_digest(first), _digest(second))

    def test_hit_returns_independent_tshape(self):
        first = _build_part()
        second = _build_part()
        self.assertIsNot(first.wrapped.TShape(), second.wrapped.TShape())

    def test_mutating_a_result_does_not_poison_the_cache(self):
        from OCP.BRepMesh import BRepMesh_IncrementalMesh

        first = _build_part()
        reference = _digest(first)
        # Mutate the first result the way the pipeline does (meshing).
        BRepMesh_IncrementalMesh(first.wrapped, 0.1, False, 0.5, True)
        BRepMesh_IncrementalMesh(first.wrapped, 0.5, False, 0.8, True)
        second = _build_part()
        self.assertEqual(_digest(second), reference)

    def test_orientation_is_part_of_the_key(self):
        from build123d.topology import Solid

        solid = Solid.make_box(5, 5, 5)
        forward = solid.wrapped
        key_fwd = op_memo._shape_key(solid)
        solid.wrapped = forward.Reversed()
        key_rev = op_memo._shape_key(solid)
        self.assertNotEqual(key_fwd, key_rev)

    def test_generator_arguments_pass_through_uncached(self):
        from build123d.topology import Solid

        box = Solid.make_box(20, 20, 8)
        edges = (e for e in box.edges()[:2])
        before = op_memo.stats()["unkeyable"]
        result = box.fillet(1.0, edges)
        self.assertEqual(op_memo.stats()["unkeyable"], before + 1)
        self.assertLess(result.volume, box.volume)

    def test_kill_switch(self):
        os.environ["CADGEN_OP_MEMO"] = "0"
        before = dict(op_memo.stats())
        part = _build_part()
        after = op_memo.stats()
        self.assertEqual(after["hits"], before["hits"])
        self.assertEqual(after["misses"], before["misses"])
        self.assertGreater(part.volume, 0)

    def test_disabled_and_enabled_geometry_match(self):
        os.environ["CADGEN_OP_MEMO"] = "0"
        plain = _build_part()
        os.environ["CADGEN_OP_MEMO"] = "1"
        memoized = _build_part()
        self.assertAlmostEqual(plain.volume, memoized.volume, places=9)

    def test_vector_and_axis_arguments_are_keyable(self):
        # Vector/Axis carry a `wrapped` (gp_Vec/gp_Ax1); they must normalize as
        # value types, not fall into the shape branch and become unkeyable —
        # builder-heavy models pass them to Solid.extrude/revolve constantly.
        from build123d import Axis, Location, Vector
        from build123d.topology import Face, Solid, Wire

        face = Face.make_surface(Wire.make_circle(6.0))
        before = op_memo.stats()["unkeyable"]
        first = Solid.extrude(face, Vector(0, 0, 4))
        off_axis = Face.make_surface(Wire.make_circle(2.0)).moved(Location((0, 10, 0)))
        Solid.revolve(off_axis, 180.0, Axis.X)
        self.assertEqual(op_memo.stats()["unkeyable"], before)
        hits_before = op_memo.stats()["hits"]
        second = Solid.extrude(face, Vector(0, 0, 4))
        self.assertGreater(op_memo.stats()["hits"], hits_before)
        self.assertEqual(_digest(first), _digest(second))

    def test_disk_tier_survives_memory_clear(self):
        first = _build_part()
        reference = _digest(first)
        op_memo.clear()  # simulate a fresh process: memory gone, disk kept
        before = op_memo.stats()["disk_hits"]
        second = _build_part()
        after = op_memo.stats()
        self.assertGreater(after["disk_hits"], before)
        self.assertEqual(_digest(second), reference)

    def test_disk_tier_kill_switch(self):
        os.environ["CADGEN_OP_MEMO_DISK"] = "0"
        try:
            _build_part()
            op_memo.clear()
            before = op_memo.stats()["disk_hits"]
            _build_part()
            self.assertEqual(op_memo.stats()["disk_hits"], before)
        finally:
            os.environ.pop("CADGEN_OP_MEMO_DISK", None)


class ComponentStoreTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["CADGEN_STORE_DIR"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("CADGEN_STORE_DIR", None)
        self._tmp.cleanup()

    def test_publish_then_fetch_hardlinks(self):
        from pathlib import Path

        from cadgen._internal import component_store

        # The component document pair (.surf render view + .brep exact
        # shape), keyed by bare cid (no mesh tolerances exist any more).
        src = Path(self._tmp.name) / "cid123.surf"
        src.write_bytes(b"surf-payload")
        src.with_name("cid123.brep").write_bytes(b"brep-payload")
        component_store.publish(src, "cid123")
        dest = Path(self._tmp.name) / "out" / "fetched.surf"
        dest.parent.mkdir()
        self.assertTrue(component_store.fetch("cid123", dest))
        self.assertEqual(dest.read_bytes(), b"surf-payload")
        self.assertEqual(src.stat().st_ino, dest.stat().st_ino)
        self.assertEqual(
            dest.with_name("cid123.brep").read_bytes(), b"brep-payload")

    def test_fetch_requires_the_brep_half(self):
        from pathlib import Path

        from cadgen._internal import component_store

        src = Path(self._tmp.name) / "cidsurfonly.surf"
        src.write_bytes(b"surf-payload")
        component_store.publish(src, "cidsurfonly")
        dest = Path(self._tmp.name) / "fetched.surf"
        self.assertFalse(component_store.fetch("cidsurfonly", dest))

    def test_fetch_misses_unknown_cid(self):
        from pathlib import Path

        from cadgen._internal import component_store

        dest = Path(self._tmp.name) / "fetched.surf"
        self.assertFalse(component_store.fetch("nope", dest))

    def test_store_deletion_leaves_fetched_files_intact(self):
        import shutil
        from pathlib import Path

        from cadgen._internal import component_store

        src = Path(self._tmp.name) / "cid123.surf"
        src.write_bytes(b"payload")
        src.with_name("cid123.brep").write_bytes(b"brep")
        component_store.publish(src, "cid123")
        dest = Path(self._tmp.name) / "fetched.surf"
        component_store.fetch("cid123", dest)
        shutil.rmtree(Path(self._tmp.name) / "components")
        self.assertEqual(dest.read_bytes(), b"payload")

    def test_kill_switch(self):
        from pathlib import Path

        from cadgen._internal import component_store

        os.environ["CADGEN_COMPONENT_STORE"] = "0"
        try:
            src = Path(self._tmp.name) / "cid123.surf"
            src.write_bytes(b"payload")
            component_store.publish(src, "cid123")
            dest = Path(self._tmp.name) / "fetched.surf"
            self.assertFalse(component_store.fetch("cid123", dest))
        finally:
            os.environ.pop("CADGEN_COMPONENT_STORE", None)


if __name__ == "__main__":
    unittest.main()
