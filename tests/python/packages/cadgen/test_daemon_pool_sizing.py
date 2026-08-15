"""How big the pool gets, and what happens once it is full.

Two changes are pinned here. The cap follows the machine instead of a constant, so a large
box stops being handed the same four workers as a laptop. And a caller that arrives at the
cap waits briefly for a worker instead of being turned away at once -- which is what makes
the cap a real ceiling, because the old behaviour let every overflow caller start its own
OCP process and bounded nothing at all.

Machines are simulated rather than detected. These properties have to hold on hardware the
test runner will never be, and a suite that only checks the box it happens to run on would
pass everywhere and mean nothing.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from tests.python.support.paths import add_repo_path

add_repo_path("packages", "cadgen", "src")

from cadgen.daemon import pool as pool_mod  # noqa: E402

GB = 1024**3


class _FakeWorker:
    """Stands in for a subprocess: sizing and dispatch are bookkeeping, not OCP."""

    _next_pid = 1000

    def __init__(self) -> None:
        _FakeWorker._next_pid += 1
        self.pid = _FakeWorker._next_pid
        self.busy = False
        self.jobs_served = 0
        self.last_used = time.monotonic()

    def alive(self) -> bool:
        return True

    def kill(self) -> None:
        pass


def sized(*, gb: float | None, cpus: int, cgroup: int | None = None) -> int:
    with mock.patch.dict("os.environ", {"CADGEN_DAEMON_MAX_WORKERS": ""}, clear=False), \
            mock.patch.object(pool_mod, "_physical_memory", return_value=None if gb is None else int(gb * GB)), \
            mock.patch.object(pool_mod, "_container_memory_limit", return_value=cgroup), \
            mock.patch("os.cpu_count", return_value=cpus):
        return pool_mod.max_workers()


class Sizing(unittest.TestCase):
    def test_a_big_machine_is_no_longer_capped_at_a_constant(self):
        # The regression this replaced: 64 GB / 32 cores also got four.
        self.assertEqual(30, sized(gb=64, cpus=32))

    def test_a_small_laptop_lands_where_it_always_did(self):
        self.assertEqual(2, sized(gb=8, cpus=4))

    def test_cpus_bind_before_memory_on_a_roomy_machine(self):
        # 68 GB would hold ~113 workers; 10 cores is the real limit.
        self.assertEqual(8, sized(gb=68, cpus=10))

    def test_memory_binds_before_cpus_on_a_dense_one(self):
        # Many cores, little RAM: an 8 GB box budgets 4 GB, which holds 13 workers, well
        # under the 62 the cores would allow.
        self.assertEqual(13, sized(gb=8, cpus=64))

    def test_a_container_limit_beats_host_memory(self):
        # The OOM-kill shape: a small container on a large host.
        self.assertEqual(3, sized(gb=128, cpus=32, cgroup=2 * GB))

    def test_the_ceiling_holds_on_an_enormous_machine(self):
        self.assertEqual(pool_mod.MAX_WORKERS_CEILING, sized(gb=1024, cpus=256))

    def test_it_never_returns_zero(self):
        # A tiny container must still get one worker, not a pool that can never serve.
        self.assertEqual(1, sized(gb=0.2, cpus=1))
        self.assertEqual(1, sized(gb=64, cpus=1))

    def test_unreadable_memory_falls_back_rather_than_guessing_big(self):
        self.assertEqual(pool_mod.FALLBACK_MAX_WORKERS, sized(gb=None, cpus=32))

    def test_an_explicit_setting_wins_over_every_bound(self):
        with mock.patch.dict("os.environ", {"CADGEN_DAEMON_MAX_WORKERS": "12"}, clear=False):
            self.assertEqual(12, pool_mod.max_workers())

    def test_a_junk_setting_is_ignored_rather_than_crashing(self):
        with mock.patch.dict("os.environ", {"CADGEN_DAEMON_MAX_WORKERS": "banana"}, clear=False), \
                mock.patch.object(pool_mod, "_physical_memory", return_value=8 * GB), \
                mock.patch.object(pool_mod, "_container_memory_limit", return_value=None), \
                mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(2, pool_mod.max_workers())


class WaitingAtTheCap(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(pool_mod, "Worker", _FakeWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pool = pool_mod.Pool()
        self.addCleanup(self.pool.shutdown)

    def _cap(self, n: int):
        return mock.patch.object(pool_mod, "max_workers", return_value=n)

    def test_a_freed_worker_is_handed_to_the_waiter(self):
        with self._cap(1):
            held = self.pool.acquire()
            self.assertIsNotNone(held)

            got: list = []
            waiter = threading.Thread(target=lambda: got.append(self.pool.acquire()))
            waiter.start()
            time.sleep(0.1)                      # let it reach the wait
            self.assertEqual([], got, "it should still be waiting, not already cold")
            self.pool.release(held)
            waiter.join(timeout=5)

        self.assertIs(got[0], held, "the waiter should get the warm worker, not None")
        self.assertEqual(0, self.pool.cold_overflows)
        self.assertEqual(1, self.pool.waits)

    def test_it_gives_up_and_runs_cold_when_nothing_frees(self):
        with self._cap(1), mock.patch.object(pool_mod, "wait_seconds", return_value=0.2):
            self.pool.acquire()
            started = time.monotonic()
            self.assertIsNone(self.pool.acquire())
            waited = time.monotonic() - started

        self.assertGreaterEqual(waited, 0.2, "it must actually wait before giving up")
        self.assertLess(waited, 3.0, "the wait is bounded, not a queue")
        self.assertEqual(1, self.pool.cold_overflows)

    def test_zero_restores_the_old_refuse_immediately_behaviour(self):
        with self._cap(1), mock.patch.object(pool_mod, "wait_seconds", return_value=0.0):
            self.pool.acquire()
            started = time.monotonic()
            self.assertIsNone(self.pool.acquire())
            self.assertLess(time.monotonic() - started, 0.1)
        self.assertEqual(0, self.pool.waits)

    def test_the_cap_holds_when_callers_arrive_together(self):
        # Spawning happens outside the lock, so without reserving the slot first two
        # threads could both see room for the last worker and both take it.
        with self._cap(3), mock.patch.object(pool_mod, "wait_seconds", return_value=0.0):
            got: list = []
            lock = threading.Lock()

            def grab():
                worker = self.pool.acquire()
                with lock:
                    got.append(worker)

            threads = [threading.Thread(target=grab) for _ in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        workers = [w for w in got if w is not None]
        self.assertEqual(3, len(workers), "the pool exceeded its own cap")
        self.assertEqual(3, len({id(w) for w in workers}), "one worker served two callers")

    def test_a_burst_below_the_cap_still_spawns_without_waiting(self):
        # Rule 2 is unchanged: room in the pool means spawn, never wait.
        with self._cap(4), mock.patch.object(pool_mod, "wait_seconds", return_value=30.0):
            started = time.monotonic()
            workers = [self.pool.acquire() for _ in range(4)]
            self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(4, len([w for w in workers if w is not None]))
        self.assertEqual(0, self.pool.waits)

    def test_status_reports_the_wait_budget_and_how_often_it_was_used(self):
        with self._cap(1), mock.patch.object(pool_mod, "wait_seconds", return_value=0.05):
            self.pool.acquire()
            self.pool.acquire()
        snapshot = self.pool.snapshot()
        self.assertEqual(1, snapshot["waits"])
        self.assertEqual(1, snapshot["coldOverflows"])
        self.assertIn("waitSeconds", snapshot)


if __name__ == "__main__":
    unittest.main()
