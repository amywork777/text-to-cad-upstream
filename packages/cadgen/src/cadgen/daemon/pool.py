"""A pool of warm OCP worker processes, owned by the daemon supervisor.

The dispatch rule, which is the whole design:

1. A free worker exists — use it. Warm, the common case.
2. All busy and the pool is below its cap — spawn one and wait for it. That caller pays
   roughly one OCP import, the same as running cold, but the worker PERSISTS, so a burst
   converges to warm instead of paying the import every time.
3. At the cap — return None and let the caller run cold. A bounded pool that queues would
   be worse than no pool for parallel work, which is exactly the trap the single-process
   daemon fell into.

Sizing: a warm worker is ~274 MB resident, so the default cap is deliberately small.
Workers are spawned lazily, so a sequential user still only ever starts one.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time

DEFAULT_MAX_WORKERS = 4
DEFAULT_RECYCLE_AFTER = 200
DEFAULT_WORKER_IDLE_SECONDS = 300.0
_SPAWN_TIMEOUT_SECONDS = 120.0


def max_workers() -> int:
    try:
        configured = int(os.environ.get("CADGEN_DAEMON_MAX_WORKERS", ""))
    except ValueError:
        configured = 0
    if configured > 0:
        return configured
    return max(1, min(DEFAULT_MAX_WORKERS, (os.cpu_count() or 4) - 2))


def _recycle_after() -> int:
    try:
        return max(0, int(os.environ.get("CADGEN_DAEMON_RECYCLE", "")))
    except ValueError:
        return DEFAULT_RECYCLE_AFTER


class WorkerGone(RuntimeError):
    """The worker died or stopped speaking. Its job is lost; the pool replaces it."""


class Worker:
    """One warm subprocess. Owned by the pool; never shared between concurrent jobs."""

    def __init__(self) -> None:
        env = dict(os.environ)
        # Guards against a worker's own CLI call routing back into the daemon.
        env["CADGEN_DAEMON_CHILD"] = "1"
        # Drawing packages are content-addressed and ezdxf's ordering follows the hash
        # seed. Setting it here is strictly better than the dispatch re-run: a warm job
        # never pays an interpreter restart.
        env["PYTHONHASHSEED"] = "0"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cadgen.daemon.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            env=env, text=True, bufsize=1,
        )
        self.jobs_served = 0
        self.busy = False
        self.last_used = time.monotonic()
        ready = self._read_frame(timeout=_SPAWN_TIMEOUT_SECONDS)
        if not ready or "ready" not in ready:
            self.kill()
            raise WorkerGone("worker did not announce itself")
        self.pid = int(ready["ready"])

    def _read_frame(self, timeout: float | None = None) -> dict | None:
        """Frames are newline-delimited JSON; a closed pipe means the worker is gone."""
        line = self.proc.stdout.readline() if self.proc.stdout else ""
        if line == "":
            return None
        try:
            return json.loads(line)
        except ValueError:
            return {"stream": "stderr", "data": line}

    def send(self, request: dict) -> None:
        if self.proc.poll() is not None or self.proc.stdin is None:
            raise WorkerGone("worker is not running")
        try:
            self.proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise WorkerGone(f"worker stdin closed: {exc}") from exc

    def frames(self):
        """Yield frames until the terminating one, which is yielded last."""
        while True:
            frame = self._read_frame()
            if frame is None:
                raise WorkerGone("worker closed the connection")
            yield frame
            if "exit" in frame or "result" in frame or "pong" in frame:
                return

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self) -> None:
        proc = self.proc
        try:
            if proc.poll() is None:
                # Closing stdin is the polite exit; the worker's read loop ends on EOF.
                if proc.stdin is not None:
                    with contextlib.suppress(OSError):
                        proc.stdin.close()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        except OSError:
            pass


class Pool:
    """Owns every worker. Thread-safe; one lock, held only around bookkeeping."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: list[Worker] = []
        self.cold_overflows = 0
        self.crashes = 0
        self.recycles = 0

    # --- acquisition -------------------------------------------------------------
    def acquire(self) -> Worker | None:
        """A worker to run one job on, or None meaning "run this cold"."""
        with self._lock:
            self._reap_dead_locked()
            for worker in self._workers:
                if not worker.busy:
                    worker.busy = True
                    return worker
            if len(self._workers) >= max_workers():
                self.cold_overflows += 1
                return None
        # Spawn outside the lock: it costs an OCP import and must not block acquire().
        try:
            worker = Worker()
        except (OSError, WorkerGone):
            with self._lock:
                self.crashes += 1
            return None
        with self._lock:
            worker.busy = True
            self._workers.append(worker)
            return worker

    def release(self, worker: Worker, *, healthy: bool = True) -> None:
        with self._lock:
            worker.busy = False
            worker.last_used = time.monotonic()
            worker.jobs_served += 1
            recycle_after = _recycle_after()
            if not healthy or not worker.alive():
                self.crashes += 0 if healthy else 1
                self._drop_locked(worker)
            elif recycle_after and worker.jobs_served >= recycle_after:
                # Bound OCP's memory growth over a long-lived session.
                self.recycles += 1
                self._drop_locked(worker)

    # --- maintenance -------------------------------------------------------------
    def _drop_locked(self, worker: Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.kill()

    def _reap_dead_locked(self) -> None:
        for worker in list(self._workers):
            if not worker.alive():
                self._workers.remove(worker)

    def reap_idle(self) -> None:
        """Drop idle workers down to one, so a finished burst returns the memory."""
        with self._lock:
            self._reap_dead_locked()
            now = time.monotonic()
            idle = [w for w in self._workers if not w.busy and now - w.last_used > DEFAULT_WORKER_IDLE_SECONDS]
            for worker in idle:
                if len(self._workers) <= 1:
                    break
                self._drop_locked(worker)

    def shutdown(self) -> None:
        with self._lock:
            for worker in list(self._workers):
                self._drop_locked(worker)

    # --- introspection -----------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "maxWorkers": max_workers(),
                "workers": [
                    {"pid": w.pid, "busy": w.busy, "jobsServed": w.jobs_served}
                    for w in self._workers
                ],
                "coldOverflows": self.cold_overflows,
                "recycles": self.recycles,
                "crashes": self.crashes,
            }
