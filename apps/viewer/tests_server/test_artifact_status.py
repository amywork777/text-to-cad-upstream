"""The freshness verdict, the state machine, and where progress is read from.

Ports ``artifactStatus.test.mjs`` and ``buildProgress.test.mjs``, and adds the
case neither could have: a record published at the PACKAGES tier must be
visible. That is the defect this step fixes — ``cadgen step compile`` publishes
there, the old reader looked only in ``locks/``, and so the viewer's own import
never showed a bar.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server import store_paths  # noqa: E402
from server.artifact_status import (  # noqa: E402
    artifact_status,
    is_generated_document,
    owns_artifact_path,
    owns_dxf_path,
    owns_step_path,
    resolve_artifact_verdict,
)
from server.build_progress import (  # noqa: E402
    PROGRESS_FRESHNESS_MS,
    ProgressRegistry,
    build_progress_snapshot,
    status_record_path,
)

STEP_BYTES = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


class _Tree:
    """A models root plus its own private cache, wired through the environment."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name, "models")
        self.root.mkdir()
        self.cache = Path(self.tmp.name, "cache")
        self.cache.mkdir()
        self._previous = os.environ.get("CADGEN_CACHE_DIR")
        os.environ["CADGEN_CACHE_DIR"] = str(self.cache)

    def close(self) -> None:
        if self._previous is None:
            os.environ.pop("CADGEN_CACHE_DIR", None)
        else:
            os.environ["CADGEN_CACHE_DIR"] = self._previous
        self.tmp.cleanup()

    def step(self, name="model.step", body=STEP_BYTES) -> str:
        path = self.root / name
        path.write_bytes(body)
        return str(path)

    def package(self, step_path, *, kind="assembly-package", components=("c0.surf",), write_payloads=True):
        package_dir = Path(store_paths.render_package_dir(step_path))
        package_dir.mkdir(parents=True, exist_ok=True)
        descriptor = {
            "kind": kind,
            "components": {f"k{i}": {"surf": name} for i, name in enumerate(components)},
        }
        (package_dir / "assembly.json").write_text(json.dumps(descriptor), encoding="utf-8")
        if write_payloads:
            for name in components:
                target = package_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"SURF\x00")
        return package_dir

    def record(self, output_dir, **fields):
        path = Path(status_record_path(str(output_dir)))
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": 3,
            "runId": "run-1",
            "outcome": None,
            "updatedAt": round(time.time() * 1000),
            "phase": "components",
            "label": "Meshing components",
            "done": 3,
            "total": 10,
            "determinate": True,
        }
        payload.update(fields)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class ArtifactStatusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = _Tree()
        self.addCleanup(self.tree.close)


class Ownership(ArtifactStatusTestCase):
    def test_step_and_stp_are_owned_case_insensitively(self):
        for name in ("a.step", "a.STEP", "a.stp", "a.Stp"):
            self.assertTrue(owns_step_path(name), name)
        for name in ("a.py", "a.dxf", "a.stl", "astep", ""):
            self.assertFalse(owns_step_path(name), name)

    def test_dxf_is_never_owned(self):
        # A plain .dxf renders directly and generated-DXF entries were scripts,
        # which are not entries at all any more.
        self.assertFalse(owns_dxf_path("a.dxf"))
        self.assertFalse(owns_artifact_path("a.dxf"))


class Verdicts(ArtifactStatusTestCase):
    def test_a_fresh_package_is_ready(self):
        step = self.tree.step()
        self.tree.package(step)
        self.assertEqual(artifact_status(step, str(self.tree.root)), {"state": "ready"})

    def test_editing_the_file_unresolves_the_package(self):
        step = self.tree.step()
        self.tree.package(step)
        Path(step).write_bytes(STEP_BYTES + b"\n")
        # Content keying IS the digest gate: different bytes, different key.
        self.assertEqual(
            artifact_status(step, str(self.tree.root)),
            {"state": "needs-build", "reason": "missing_glb"},
        )

    def test_restoring_the_bytes_makes_it_ready_again_with_nothing_rebuilt(self):
        step = self.tree.step()
        self.tree.package(step)
        Path(step).write_bytes(STEP_BYTES + b"\n")
        Path(step).write_bytes(STEP_BYTES)
        self.assertEqual(artifact_status(step, str(self.tree.root)), {"state": "ready"})

    def test_a_missing_candidate_is_an_error_naming_the_raw_ref(self):
        self.assertEqual(
            artifact_status("nope.step", str(self.tree.root)),
            {"state": "error", "error": "Artifact source not found: nope.step"},
        )

    def test_an_unowned_format_is_an_error(self):
        path = self.tree.root / "notes.py"
        path.write_text("x = 1", encoding="utf-8")
        self.assertEqual(
            artifact_status(str(path), str(self.tree.root)),
            {"state": "error", "error": f"No render-artifact format owns this entry: {path}"},
        )

    def test_the_gate_order_missing_then_descriptor_then_kind_then_components(self):
        step = self.tree.step()
        package_dir = Path(store_paths.render_package_dir(step))

        self.assertEqual(artifact_status(step, str(self.tree.root))["reason"], "missing_glb")

        package_dir.mkdir(parents=True)
        self.assertEqual(
            artifact_status(step, str(self.tree.root))["reason"], "missing_step_topology"
        )

        (package_dir / "assembly.json").write_text('{"kind":"other"}', encoding="utf-8")
        self.assertEqual(
            artifact_status(step, str(self.tree.root))["reason"], "unsupported_step_topology"
        )

        (package_dir / "assembly.json").write_text(
            '{"kind":"assembly-package","components":{}}', encoding="utf-8"
        )
        self.assertEqual(artifact_status(step, str(self.tree.root))["reason"], "missing_glb")

    def test_a_component_whose_surf_payload_is_absent_is_missing_glb(self):
        step = self.tree.step()
        self.tree.package(step, write_payloads=False)
        self.assertEqual(artifact_status(step, str(self.tree.root))["reason"], "missing_glb")

    def test_a_package_at_an_older_schema_key_stops_resolving(self):
        # The schema gate lives in the package KEY, not in a descriptor field.
        step = self.tree.step()
        package_dir = self.tree.package(step)
        stale = package_dir.with_name(
            package_dir.name.replace(
                f"-v{store_paths.CACHE_SCHEMA_VERSION}",
                f"-v{store_paths.CACHE_SCHEMA_VERSION - 1}",
            )
        )
        package_dir.rename(stale)
        self.assertEqual(artifact_status(step, str(self.tree.root))["reason"], "missing_glb")


class GeneratedClassification(ArtifactStatusTestCase):
    def test_an_imported_step_with_no_sidecar_and_no_record_is_not_generated(self):
        self.assertFalse(is_generated_document(self.tree.step()))

    def test_a_sidecar_at_the_current_schema_is_a_fast_yes(self):
        step = self.tree.step()
        Path(store_paths.source_sidecar_path(step)).write_text(
            json.dumps({"schemaVersion": store_paths.SOURCE_SIDECAR_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        self.assertTrue(is_generated_document(step))

    def test_a_sidecar_at_another_schema_is_not_a_marker_and_the_record_decides(self):
        step = self.tree.step()
        Path(store_paths.source_sidecar_path(step)).write_text(
            json.dumps({"schemaVersion": 4}), encoding="utf-8"
        )
        self.assertFalse(is_generated_document(step))

        record = Path(store_paths.source_provenance_record_path(step))
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"sourceKind": "python"}), encoding="utf-8")
        self.assertTrue(is_generated_document(step))

    def test_an_evicted_truncated_or_kindless_record_degrades_to_imported(self):
        step = self.tree.step()
        record = Path(store_paths.source_provenance_record_path(step))
        record.parent.mkdir(parents=True, exist_ok=True)
        for body in ("{ truncated", "{}", '{"sourceKind":"   "}', "[]", "null"):
            record.write_text(body, encoding="utf-8")
            # Never raises: the records tier is evictable, so a missing or
            # broken marker is a routine state, not a fault.
            self.assertFalse(is_generated_document(step), body)

    def test_classification_rides_on_a_failing_verdict_too(self):
        # The case where it matters most is a document with NO package: that is
        # exactly when the import path asks whether to offer a compile.
        step = self.tree.step()
        record = Path(store_paths.source_provenance_record_path(step))
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"sourceKind": "python"}), encoding="utf-8")
        verdict = resolve_artifact_verdict(step, str(self.tree.root))
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["code"], "missing_glb")
        self.assertTrue(verdict["generated"])
        self.assertTrue(verdict["rawStep"])

    def test_provenance_is_path_keyed_while_packages_are_content_keyed(self):
        one = self.tree.step("one.step")
        two = self.tree.step("two.step")
        self.assertEqual(
            store_paths.render_package_dir(one), store_paths.render_package_dir(two)
        )
        record = Path(store_paths.source_provenance_record_path(one))
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"sourceKind": "python"}), encoding="utf-8")
        self.assertTrue(is_generated_document(one))
        self.assertFalse(is_generated_document(two))

    def test_classification_never_reaches_a_client_payload(self):
        step = self.tree.step()
        self.tree.package(step)
        status = artifact_status(step, str(self.tree.root))
        self.assertNotIn("generated", status)
        self.assertNotIn("sourceKind", status)


class SnapshotShapes(ArtifactStatusTestCase):
    def test_writing_beats_a_resolvable_package(self):
        step = self.tree.step()
        self.tree.package(step)
        status = artifact_status(
            step,
            str(self.tree.root),
            snapshot={"writing": True, "busy": False, "runId": "r1", "progress": {"phase": "x"}},
        )
        self.assertEqual(
            status, {"state": "generating", "runId": "r1", "progress": {"phase": "x"}}
        )

    def test_absent_run_id_and_progress_are_ABSENT_not_null(self):
        step = self.tree.step()
        status = artifact_status(
            step,
            str(self.tree.root),
            snapshot={"writing": True, "busy": False, "runId": None, "progress": None},
        )
        self.assertEqual(status, {"state": "generating"})

    def test_busy_over_an_ok_package_is_ready_plus_busy(self):
        step = self.tree.step()
        self.tree.package(step)
        status = artifact_status(
            step,
            str(self.tree.root),
            snapshot={"writing": False, "busy": True, "runId": "r2", "progress": None},
        )
        self.assertEqual(status, {"state": "ready", "busy": True, "runId": "r2"})

    def test_busy_over_an_unbuilt_package_is_needs_build_plus_blocked(self):
        step = self.tree.step()
        status = artifact_status(
            step,
            str(self.tree.root),
            snapshot={"writing": False, "busy": True, "runId": None, "progress": None},
        )
        self.assertEqual(
            status, {"state": "needs-build", "reason": "missing_glb", "blocked": True}
        )


class ProgressReader(ArtifactStatusTestCase):
    def test_a_fresh_record_becomes_a_writing_snapshot_with_phase_fields_on_top(self):
        step = self.tree.step()
        self.tree.record(store_paths.coordination_scope(step))
        snapshot = build_progress_snapshot(step)
        self.assertTrue(snapshot["writing"])
        self.assertFalse(snapshot["busy"])
        self.assertEqual(snapshot["runId"], "run-1")
        progress = snapshot["progress"]
        for key in ("phase", "label", "done", "total", "determinate"):
            self.assertIn(key, progress, key)

    def test_a_record_at_the_PACKAGES_tier_is_visible(self):
        # THE REGRESSION TEST FOR THIS STEP. `cadgen step compile` publishes at
        # status_path(render_package_dir(...)), not the locks tier — so reading
        # only locks/ meant the viewer's own import never reported a phase.
        step = self.tree.step()
        self.assertIsNone(build_progress_snapshot(step))
        self.tree.record(store_paths.render_package_dir(step), runId="pkg-run")
        snapshot = build_progress_snapshot(step)
        self.assertIsNotNone(snapshot, "a packages-tier record must be read")
        self.assertEqual(snapshot["runId"], "pkg-run")

    def test_the_fresher_of_the_two_tiers_wins(self):
        step = self.tree.step()
        now = round(time.time() * 1000)
        self.tree.record(store_paths.coordination_scope(step), runId="older", updatedAt=now - 5000)
        self.tree.record(store_paths.render_package_dir(step), runId="newer", updatedAt=now)
        self.assertEqual(build_progress_snapshot(step)["runId"], "newer")

    def test_a_terminal_or_stale_or_absent_record_yields_nothing(self):
        step = self.tree.step()
        scope = store_paths.coordination_scope(step)
        self.assertIsNone(build_progress_snapshot(step))

        self.tree.record(scope, outcome="done")
        self.assertIsNone(build_progress_snapshot(step), "a finished run is not in flight")

        self.tree.record(
            scope, updatedAt=round(time.time() * 1000) - PROGRESS_FRESHNESS_MS - 1000
        )
        self.assertIsNone(build_progress_snapshot(step), "a killed producer's badge ages out")

    def test_the_reader_is_schema_blind(self):
        # buildProgress.test.mjs wrote schemaVersion 1 and expected a snapshot.
        # The viewer cannot know a peer's run id before reading the record, so
        # staleness is gated on outcome plus the window, not on attribution.
        step = self.tree.step()
        self.tree.record(store_paths.coordination_scope(step), schemaVersion=1)
        self.assertIsNotNone(build_progress_snapshot(step))

    def test_a_non_string_run_id_becomes_none(self):
        step = self.tree.step()
        self.tree.record(store_paths.coordination_scope(step), runId=17)
        self.assertIsNone(build_progress_snapshot(step)["runId"])


class InProcessRegistry(ArtifactStatusTestCase):
    def test_our_own_build_is_served_from_memory_not_from_disk(self):
        step = self.tree.step()
        package_dir = store_paths.render_package_dir(step)
        registry = ProgressRegistry()
        registry.publish(package_dir, "live-run", {"phase": "components", "done": 4, "total": 9})
        snapshot = build_progress_snapshot(step, registry=registry)
        self.assertEqual(snapshot["runId"], "live-run")
        self.assertEqual(snapshot["progress"]["done"], 4)

    def test_the_live_channel_beats_a_peer_record(self):
        step = self.tree.step()
        self.tree.record(store_paths.coordination_scope(step), runId="from-disk")
        registry = ProgressRegistry()
        registry.publish(store_paths.render_package_dir(step), "in-process", {"phase": "package"})
        self.assertEqual(build_progress_snapshot(step, registry=registry)["runId"], "in-process")

    def test_clearing_falls_back_to_the_file_tiers(self):
        step = self.tree.step()
        package_dir = store_paths.render_package_dir(step)
        registry = ProgressRegistry()
        registry.publish(package_dir, "live", {"phase": "package"})
        registry.clear(package_dir)
        self.assertIsNone(build_progress_snapshot(step, registry=registry))

    def test_no_freshness_window_applies_to_the_live_channel(self):
        # The entry exists only while a worker we own is running, and is cleared
        # in a finally. The window is for producers we cannot observe.
        step = self.tree.step()
        registry = ProgressRegistry()
        registry.publish(store_paths.render_package_dir(step), "live", {"phase": "generate"})
        snapshot = build_progress_snapshot(step, registry=registry)
        self.assertIsNotNone(snapshot)
        self.assertGreater(snapshot["progress"]["updatedAt"], 0)


if __name__ == "__main__":
    unittest.main()
