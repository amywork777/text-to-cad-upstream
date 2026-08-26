"""The pool's dispatch rule, which is the whole reason it exists.

1. A free worker -> use it. Sequential work must never grow the pool.
2. All busy, below the cap -> spawn and wait. That caller pays roughly one OCP import,
   but the worker persists, so a burst CONVERGES to warm instead of paying per burst.
3. At the cap -> run cold. Queueing behind a full pool is what made the single-process
   daemon worse than no daemon for parallel work; a bounded queue would reintroduce it.

Asserted on worker identity and on outputs, never on timing: a test that fails when the
machine is busy teaches people to rerun it rather than read it.
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.daemon import pool as pool_mod  # noqa: E402


class _StubWorker:
    """Stands in for a subprocess: the dispatch rule is about bookkeeping, not OCP."""

    _next_pid = 1000

    def __init__(self) -> None:
        _StubWorker._next_pid += 1
        self.pid = _StubWorker._next_pid
        self.busy = False
        self.jobs_served = 0
        self.last_used = 0.0
        self.killed = False
        self.affinity = ""
        self._alive = True

    def alive(self) -> bool:
        return self._alive

    def kill(self) -> None:
        self.killed = True
        self._alive = False


class _PoolFixture(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(pool_mod, "Worker", _StubWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pool = pool_mod.Pool()
        self.addCleanup(self.pool.shutdown)

    def _cap(self, size: int):
        return mock.patch.dict(os.environ, {"CADGEN_DAEMON_MAX_WORKERS": str(size)})


class DispatchRule(_PoolFixture):
    def test_sequential_work_reuses_one_worker(self):
        seen = set()
        with self._cap(4):
            for _ in range(5):
                worker = self.pool.acquire()
                self.assertIsNotNone(worker)
                seen.add(worker.pid)
                self.pool.release(worker)
        self.assertEqual(len(seen), 1, "sequential jobs must not grow the pool")

    def test_a_burst_below_the_cap_spawns_one_worker_each(self):
        with self._cap(4):
            held = [self.pool.acquire() for _ in range(3)]
        self.assertEqual(len({w.pid for w in held}), 3)
        for worker in held:
            self.pool.release(worker)

    def test_at_the_cap_the_caller_is_told_to_run_cold(self):
        with self._cap(2):
            first, second = self.pool.acquire(), self.pool.acquire()
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            # Third caller: no queueing, no fifth worker -- run cold.
            self.assertIsNone(self.pool.acquire())
        self.assertEqual(self.pool.snapshot()["coldOverflows"], 1)
        for worker in (first, second):
            self.pool.release(worker)

    def test_a_burst_converges_and_stops_spawning(self):
        with self._cap(3):
            first = [self.pool.acquire() for _ in range(3)]
            pids = {w.pid for w in first}
            for worker in first:
                self.pool.release(worker)
            second = [self.pool.acquire() for _ in range(3)]
            self.assertEqual({w.pid for w in second}, pids, "a warm burst must not respawn")
            for worker in second:
                self.pool.release(worker)

    def test_concurrent_acquire_never_hands_one_worker_to_two_callers(self):
        with self._cap(4):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                got = list(pool.map(lambda _: self.pool.acquire(), range(8)))
        live = [w for w in got if w is not None]
        self.assertEqual(len({w.pid for w in live}), len(live), "a worker was handed out twice")
        self.assertLessEqual(len(live), 4)
        for worker in live:
            self.pool.release(worker)


class AffinityRouting(_PoolFixture):
    def test_matching_affinity_wins_among_free_workers(self):
        with self._cap(4):
            a = self.pool.acquire("/models/tom")
            b = self.pool.acquire("/models/gripper")
            self.pool.release(a)
            self.pool.release(b)
            again = self.pool.acquire("/models/gripper")
            self.assertIs(again, b, "the worker warm for this model must win")
            self.pool.release(again)

    def test_affinity_never_waits_for_a_busy_worker(self):
        with self._cap(4):
            a = self.pool.acquire("/models/tom")
            # a stays busy; the same model must still get SOME worker instantly.
            b = self.pool.acquire("/models/tom")
            self.assertIsNotNone(b)
            self.assertIsNot(a, b)
            self.pool.release(a)
            self.pool.release(b)

    def test_no_affinity_behaves_as_before(self):
        with self._cap(4):
            a = self.pool.acquire()
            self.pool.release(a)
            b = self.pool.acquire()
            self.assertIs(a, b)
            self.pool.release(b)


class WorkerLifecycle(_PoolFixture):
    def test_an_unhealthy_worker_is_dropped_not_reused(self):
        with self._cap(4):
            worker = self.pool.acquire()
            self.pool.release(worker, healthy=False)
            self.assertTrue(worker.killed)
            replacement = self.pool.acquire()
            self.assertNotEqual(replacement.pid, worker.pid)
            self.pool.release(replacement)

    def test_a_worker_that_died_is_never_handed_out(self):
        with self._cap(4):
            worker = self.pool.acquire()
            self.pool.release(worker)
            worker._alive = False  # e.g. an OCP segfault between jobs
            replacement = self.pool.acquire()
            self.assertNotEqual(replacement.pid, worker.pid)
            self.pool.release(replacement)

    def test_a_worker_is_recycled_after_its_job_budget(self):
        # OCP's memory grows over a long session, so a worker is not immortal.
        with self._cap(4), mock.patch.dict(os.environ, {"CADGEN_DAEMON_RECYCLE": "2"}):
            first = self.pool.acquire()
            self.pool.release(first)
            again = self.pool.acquire()
            self.assertEqual(again.pid, first.pid, "recycled too early")
            self.pool.release(again)  # second job reaches the budget
            self.assertTrue(first.killed)
            third = self.pool.acquire()
            self.assertNotEqual(third.pid, first.pid)
            self.pool.release(third)
        self.assertEqual(self.pool.snapshot()["recycles"], 1)

    def test_idle_workers_are_reaped_down_to_one(self):
        with self._cap(4):
            held = [self.pool.acquire() for _ in range(3)]
            for worker in held:
                self.pool.release(worker)
            for worker in held:
                worker.last_used = -pool_mod.DEFAULT_WORKER_IDLE_SECONDS * 2
            self.pool.reap_idle()
        self.assertEqual(len(self.pool.snapshot()["workers"]), 1, "a finished burst must return memory")

    def test_shutdown_kills_every_worker(self):
        # An orphaned 274 MB OCP process per session is how this feature gets disabled.
        with self._cap(4):
            held = [self.pool.acquire() for _ in range(3)]
            for worker in held:
                self.pool.release(worker)
        self.pool.shutdown()
        self.assertTrue(all(w.killed for w in held))
        self.assertEqual(self.pool.snapshot()["workers"], [])


class Sizing(unittest.TestCase):
    def test_the_cap_is_configurable(self):
        with mock.patch.dict(os.environ, {"CADGEN_DAEMON_MAX_WORKERS": "7"}):
            self.assertEqual(pool_mod.max_workers(), 7)

    def test_the_default_leaves_the_machine_room(self):
        import os as _os

        with mock.patch.dict(os.environ, {"CADGEN_DAEMON_MAX_WORKERS": ""}):
            cap = pool_mod.max_workers()
        # The cap follows the machine now rather than a constant, so the property is that
        # it leaves headroom -- at least one worker, never more cores than the box has
        # spare, and never past the ceiling. Which bound binds is per-machine and is
        # covered against simulated hardware in test_daemon_pool_sizing.
        self.assertGreaterEqual(cap, 1)
        self.assertLessEqual(cap, pool_mod.MAX_WORKERS_CEILING)
        self.assertLessEqual(cap, max(1, (_os.cpu_count() or 4) - 2))

    def test_a_nonsense_cap_falls_back_rather_than_crashing(self):
        with mock.patch.dict(os.environ, {"CADGEN_DAEMON_MAX_WORKERS": "banana"}):
            self.assertGreaterEqual(pool_mod.max_workers(), 1)


class RealWorkerProcess(unittest.TestCase):
    """One end-to-end check that the stub above is not lying about the real thing."""

    def test_a_real_worker_starts_answers_and_dies_with_its_pool(self):
        pool = pool_mod.Pool()
        try:
            with mock.patch.dict(os.environ, {"CADGEN_DAEMON_MAX_WORKERS": "1"}):
                worker = pool.acquire()
            self.assertIsNotNone(worker, "could not start a real worker")
            self.assertTrue(worker.alive())
            worker.send({"kind": "ping"})
            frames = list(worker.frames())
            self.assertEqual(frames[-1].get("pong"), worker.pid)
            pool.release(worker)
        finally:
            pool.shutdown()
        self.assertFalse(worker.alive(), "shutdown left a worker running")


if __name__ == "__main__":
    unittest.main()


class DaemonStatusCommand(unittest.TestCase):
    """`cadgen daemon status` — warm compute you can see.

    It asks the supervisor rather than looking at the filesystem: a socket file outlives
    a killed daemon, and only the supervisor knows which workers are busy.
    """

    def test_no_daemon_reports_that_plainly_without_starting_one(self):
        import io
        import contextlib as _ctx

        from cadgen.cli import daemon_status

        buffer = io.StringIO()
        # Pin the supported platform: where the daemon cannot run at all the command says
        # so instead, and promising "one starts on the next build" there would be false.
        # That branch has its own coverage in test_daemon_unsupported_platform.
        with mock.patch("cadgen.daemon.client.status", return_value=None) as asked, \
                mock.patch("cadgen.daemon.client.daemon_supported", return_value=True), \
                _ctx.redirect_stdout(buffer):
            self.assertEqual(daemon_status.main([]), 0)
        asked.assert_called_once()
        self.assertIn("No CAD daemon is running", buffer.getvalue())

    def test_a_running_daemon_is_rendered_with_its_workers(self):
        import io
        import contextlib as _ctx

        from cadgen.cli import daemon_status

        payload = {
            "pid": 99, "socket": "/tmp/x.sock", "version": "1.2.3", "token": "t",
            "maxWorkers": 4, "startedAt": 0, "jobs": 7, "coldOverflows": 2,
            "recycles": 1, "crashes": 0,
            "workers": [{"pid": 100, "busy": True, "jobsServed": 5}],
        }
        buffer = io.StringIO()
        with mock.patch("cadgen.daemon.client.status", return_value=payload), \
                _ctx.redirect_stdout(buffer):
            daemon_status.main([])
        rendered = buffer.getvalue()
        self.assertIn("pid 99", rendered)
        self.assertIn("1/4 (1 busy)", rendered)
        self.assertIn("pid 100  busy  5 jobs", rendered)
        self.assertIn("2 cold overflows", rendered)

    def test_json_output_is_the_raw_payload(self):
        import io
        import json as _json
        import contextlib as _ctx

        from cadgen.cli import daemon_status

        payload = {"pid": 5, "workers": []}
        buffer = io.StringIO()
        with mock.patch("cadgen.daemon.client.status", return_value=payload), \
                _ctx.redirect_stdout(buffer):
            daemon_status.main(["--json"])
        self.assertEqual(_json.loads(buffer.getvalue()), payload)

    def test_the_two_word_command_beats_the_one_word_daemon(self):
        # Same dispatch trap as `viewer list`: without the two-word entry, `daemon status`
        # would run the daemon itself with "status" as a stray argument.
        from cadgen.cli import _COMMANDS

        self.assertEqual(_COMMANDS["daemon status"][0], "cadgen.cli.daemon_status")
        self.assertEqual(_COMMANDS["daemon"][0], "cadgen.daemon")
