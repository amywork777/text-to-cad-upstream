"""The supervisor: crash isolation, de-duplication, and errors as values.

Nothing here pins the old design's leavings — no stdout scraping, no exit-code
archaeology, no truncated stderr. A compile answers with a payload or a
structured error, and a dead worker is an ordinary outcome rather than a
mystery.

Driven by ``fake_worker.py`` so the outcomes are deterministic and fast. The
REAL worker is exercised end to end by the import proof in the step's notes;
what these cover is the supervisor's behaviour around it, which no amount of
real compiling would exercise on purpose (nothing makes OCCT segfault to order).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server import compile_client as compile_client_module  # noqa: E402
from server.build_progress import ProgressRegistry  # noqa: E402
from server.cadgen_ops import CLI_BUILD_HINT, CadgenOps  # noqa: E402
from server.compile_client import CompileClient, set_cadgen_probe_for_tests  # noqa: E402

FAKE_WORKER = str(Path(__file__).resolve().parent / "fake_worker.py")


class CompileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name, "models")
        self.root.mkdir()
        self.cache = Path(self.tmp.name, "cache")
        self._previous_cache = os.environ.get("CADGEN_CACHE_DIR")
        os.environ["CADGEN_CACHE_DIR"] = str(self.cache)
        self.addCleanup(self._restore_cache)
        self.spawn_log = Path(self.tmp.name, "spawns.log")
        os.environ["FAKE_WORKER_SPAWN_LOG"] = str(self.spawn_log)
        self.addCleanup(lambda: os.environ.pop("FAKE_WORKER_SPAWN_LOG", None))
        # cadgen is not actually needed by the fake worker, but the supervisor
        # checks availability before spawning.
        set_cadgen_probe_for_tests(lambda: True)
        self.addCleanup(set_cadgen_probe_for_tests, None)

    def _restore_cache(self) -> None:
        if self._previous_cache is None:
            os.environ.pop("CADGEN_CACHE_DIR", None)
        else:
            os.environ["CADGEN_CACHE_DIR"] = self._previous_cache

    def client(self, *, registry=None, max_workers=2) -> CompileClient:
        client = CompileClient(
            registry=registry,
            max_workers=max_workers,
            worker_command=[sys.executable, FAKE_WORKER],
        )
        self.addCleanup(client.shutdown)
        return client

    def step(self, name: str) -> str:
        path = self.root / name
        path.write_bytes(f"ISO-10303-21;{name}".encode())
        return str(path)

    def spawn_count(self) -> int:
        if not self.spawn_log.exists():
            return 0
        return len([line for line in self.spawn_log.read_text().splitlines() if line.strip()])


class ResultsAndErrorsAreValues(CompileTestCase):
    def test_a_successful_compile_returns_the_payload_shape(self):
        client = self.client()
        result = client.compile(self.step("ok.step"))
        self.assertEqual(
            set(result), {"ok", "document", "package", "skipped", "contended"}
        )
        self.assertTrue(result["ok"])

    def test_an_exception_in_the_worker_arrives_as_a_structured_error(self):
        client = self.client()
        result = client.compile(self.step("raise.step"))
        self.assertFalse(result["ok"])
        self.assertIn("StaleDocumentError", result["error"])

    def test_progress_frames_reach_the_registry_with_a_stable_run_id(self):
        registry = ProgressRegistry()
        client = self.client(registry=registry)
        candidate = self.step("slow.step")
        from server.store_paths import render_package_dir

        package_dir = render_package_dir(candidate)

        seen = []

        def watch():
            while not done.is_set():
                snapshot = registry.snapshot(package_dir)
                if snapshot is not None:
                    seen.append((snapshot["runId"], snapshot["progress"]["done"]))
                time.sleep(0.05)

        done = threading.Event()
        watcher = threading.Thread(target=watch)
        watcher.start()
        client.compile(candidate)
        done.set()
        watcher.join()

        self.assertTrue(seen, "progress must be observable while the build runs")
        run_ids = {run_id for run_id, _ in seen}
        self.assertEqual(len(run_ids), 1, f"runId must be stable within a run, saw {run_ids}")
        self.assertGreater(max(done_count for _, done_count in seen), 1)

    def test_the_registry_entry_is_cleared_when_the_compile_ends(self):
        from server.store_paths import render_package_dir

        registry = ProgressRegistry()
        client = self.client(registry=registry)
        candidate = self.step("ok.step")
        client.compile(candidate)
        self.assertIsNone(registry.snapshot(render_package_dir(candidate)))


class CrashIsolation(CompileTestCase):
    def test_a_crashed_worker_becomes_an_ordinary_failure(self):
        client = self.client()
        result = client.compile(self.step("crash.step"))
        self.assertFalse(result["ok"])
        self.assertIn("crashed", result["error"])
        self.assertIn("crash.step", result["error"])

    def test_the_in_flight_entry_clears_so_the_next_request_is_not_stuck(self):
        from server.store_paths import render_package_dir

        client = self.client()
        candidate = self.step("crash.step")
        client.compile(candidate)
        self.assertFalse(client.in_flight(render_package_dir(candidate)))

    def test_a_replacement_worker_is_spawned_lazily_on_the_next_request(self):
        client = self.client()
        client.compile(self.step("crash.step"))
        before = self.spawn_count()
        result = client.compile(self.step("ok.step"))
        self.assertTrue(result["ok"])
        self.assertEqual(self.spawn_count(), before + 1, "a fresh worker must replace the dead one")

    def test_the_pool_does_not_shrink_after_a_crash(self):
        # The slot must come back. If a crash leaked one, the pool would narrow
        # by one per crash until nothing could compile at all.
        client = self.client(max_workers=2)
        for _ in range(3):
            client.compile(self.step("crash.step"))
        results = [client.compile(self.step(f"ok{i}.step")) for i in range(2)]
        self.assertTrue(all(result["ok"] for result in results))

    def test_two_consecutive_crashes_on_one_document_trip_the_breaker(self):
        client = self.client()
        candidate = self.step("crash.step")
        for _ in range(2):
            self.assertIn("crashed", client.compile(candidate)["error"])
        spawns = self.spawn_count()
        result = client.compile(candidate)
        self.assertIn("not retrying", result["error"])
        self.assertEqual(self.spawn_count(), spawns, "a poisoned document must stop costing workers")

    def test_the_breaker_is_per_document(self):
        client = self.client()
        crash = self.step("crash.step")
        for _ in range(3):
            client.compile(crash)
        self.assertTrue(client.compile(self.step("ok.step"))["ok"])


class Deduplication(CompileTestCase):
    def test_concurrent_requests_for_one_document_produce_exactly_one_spawn(self):
        client = self.client(max_workers=4)
        candidate = self.step("slow.step")
        results = []

        threads = [
            threading.Thread(target=lambda: results.append(client.compile(candidate)))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["ok"] for result in results))
        # Node got this atomicity free from its event loop. A check, then a
        # create, then a store under separate lock acquisitions would let two
        # threads each start a compile of one document.
        self.assertEqual(self.spawn_count(), 1)

    def test_attached_requests_all_receive_the_same_answer(self):
        client = self.client(max_workers=4)
        candidate = self.step("slow.step")
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(client.compile(candidate)))
            for _ in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len({repr(result) for result in results}), 1)

    def test_two_different_documents_compile_concurrently(self):
        # The livelock guard: with ONE shared worker, a POST for a second
        # document would answer contended, the status route would report
        # needs-build (no build of it is in flight anywhere), and the client
        # would re-POST every few seconds for the length of the first build.
        client = self.client(max_workers=2)
        first, second = self.step("slow.step"), self.step("slow2.step")
        results = {}

        def run(ref, key):
            results[key] = client.compile(ref)

        started = time.monotonic()
        threads = [
            threading.Thread(target=run, args=(first, "a")),
            threading.Thread(target=run, args=(second, "b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.monotonic() - started

        self.assertTrue(results["a"]["ok"])
        self.assertTrue(results["b"]["ok"])
        self.assertFalse(results["a"].get("contended"))
        self.assertFalse(results["b"].get("contended"))
        # Each fake build sleeps ~2s; serial would be ~4s.
        self.assertLess(elapsed, 3.5, "different documents must not serialise")

    def test_a_full_pool_answers_contended_rather_than_blocking(self):
        # The occupier must outlast ACQUIRE_TIMEOUT_SECONDS, or the second
        # request simply waits its turn and succeeds — which is correct
        # behaviour, and would make this assertion vacuous.
        client = self.client(max_workers=1)
        occupier = threading.Thread(target=lambda: client.compile(self.step("long.step")))
        occupier.start()
        time.sleep(0.3)
        started = time.monotonic()
        result = client.compile(self.step("other.step"))
        elapsed = time.monotonic() - started
        occupier.join()
        # Reuses a payload shape the client already understands: attach and
        # poll rather than pin a request thread for someone else's build.
        self.assertTrue(result["ok"])
        self.assertTrue(result["contended"])
        self.assertLess(elapsed, compile_client_module.ACQUIRE_TIMEOUT_SECONDS + 2)


class WorkerReuse(CompileTestCase):
    def test_a_warm_worker_is_reused_across_compiles(self):
        client = self.client()
        for name in ("a.step", "b.step", "c.step"):
            self.assertTrue(client.compile(self.step(name))["ok"])
        self.assertEqual(self.spawn_count(), 1, "the kernel must stay warm between builds")

    def test_a_worker_idle_past_the_budget_is_reaped_rather_than_reused(self):
        # A warm worker holds ~280MB. Past the budget that is no longer worth
        # keeping, and one import on the next build is the price.
        os.environ["VIEWER_CADGEN_IDLE_TIMEOUT"] = "0.5"
        self.addCleanup(lambda: os.environ.pop("VIEWER_CADGEN_IDLE_TIMEOUT", None))
        client = self.client()
        client.compile(self.step("a.step"))
        self.assertEqual(self.spawn_count(), 1)
        time.sleep(0.8)
        client.compile(self.step("b.step"))
        self.assertEqual(self.spawn_count(), 2, "a stale worker must be replaced, not reused")


class IdleWatchdog(CompileTestCase):
    def test_a_silent_worker_is_killed_and_the_entry_leaves_generating(self):
        from server.store_paths import render_package_dir

        os.environ["VIEWER_CADGEN_IDLE_TIMEOUT"] = "1"
        self.addCleanup(lambda: os.environ.pop("VIEWER_CADGEN_IDLE_TIMEOUT", None))
        client = self.client()
        candidate = self.step("hang.step")
        result = client.compile(candidate)
        self.assertFalse(result["ok"])
        self.assertIn("went silent", result["error"])
        self.assertFalse(client.in_flight(render_package_dir(candidate)))


class SoftDependency(CompileTestCase):
    def test_with_no_cadgen_the_import_path_names_the_fix_and_nothing_spawns(self):
        set_cadgen_probe_for_tests(lambda: False)
        client = self.client()
        result = client.compile(self.step("ok.step"))
        self.assertFalse(result["ok"])
        self.assertIn("requires cadgen", result["error"])
        self.assertIn("Viewing existing models does not need cadgen", result["error"])
        self.assertEqual(self.spawn_count(), 0)


class OpsWiring(CompileTestCase):
    def ops(self, **kwargs) -> CadgenOps:
        registry = ProgressRegistry()
        return CadgenOps(str(self.root), registry=registry, client=self.client(registry=registry, **kwargs))

    def test_an_unowned_entry_is_ready_without_touching_the_kernel(self):
        ops = self.ops()
        self.assertEqual(ops.artifact_status("model.stl"), {"state": "ready"})
        self.assertEqual(ops.build_artifact("model.stl"), {"ok": True, "state": "ready"})
        self.assertEqual(self.spawn_count(), 0)

    def test_a_foreign_step_is_offered_as_an_import(self):
        ops = self.ops()
        self.step("ok.step")
        status = ops.artifact_status("ok.step")
        self.assertEqual(status["state"], "needs-build")
        self.assertTrue(status["stepImport"])

    def test_with_no_cadgen_the_offer_becomes_an_actionable_error(self):
        set_cadgen_probe_for_tests(lambda: False)
        ops = self.ops()
        self.step("ok.step")
        status = ops.artifact_status("ok.step")
        self.assertEqual(status["state"], "error")
        self.assertIn("has not been imported yet", status["error"])
        self.assertIn("requires cadgen", status["error"])

    def test_a_generated_document_is_never_routed_through_the_compile_door(self):
        import json as json_module

        from server import store_paths

        ops = self.ops()
        candidate = self.step("gen.step")
        sidecar = Path(store_paths.source_sidecar_path(candidate))
        sidecar.write_text(
            json_module.dumps({"schemaVersion": store_paths.SOURCE_SIDECAR_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        status = ops.artifact_status("gen.step")
        self.assertEqual(status, {"state": "error", "error": CLI_BUILD_HINT})
        result = ops.build_artifact("gen.step")
        self.assertEqual(result["error"], CLI_BUILD_HINT)
        self.assertEqual(self.spawn_count(), 0)

    def test_a_failed_import_is_a_500_shaped_payload(self):
        ops = self.ops()
        self.step("crash.step")
        result = ops.build_artifact("crash.step")
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "error")
        self.assertTrue(result["error"].startswith("STEP import failed: "))

    def test_a_contended_import_reports_generating(self):
        ops = self.ops(max_workers=1)
        self.step("long.step")
        self.step("other.step")
        occupier = threading.Thread(target=lambda: ops.build_artifact("long.step"))
        occupier.start()
        time.sleep(0.3)
        result = ops.build_artifact("other.step")
        occupier.join()
        self.assertEqual(
            result, {"ok": True, "state": "generating", "contended": True}
        )

    def test_an_in_flight_import_with_no_frame_yet_is_indeterminate_generating(self):
        ops = self.ops()
        candidate = self.step("slow.step")
        thread = threading.Thread(target=lambda: ops.build_artifact("slow.step"))
        thread.start()
        try:
            deadline = time.monotonic() + 5
            states = []
            while time.monotonic() < deadline:
                states.append(ops.artifact_status("slow.step"))
                if states[-1].get("state") == "generating":
                    break
                time.sleep(0.02)
            generating = [s for s in states if s.get("state") == "generating"]
            self.assertTrue(generating, "an in-flight import must report generating")
        finally:
            thread.join()


if __name__ == "__main__":
    unittest.main()
