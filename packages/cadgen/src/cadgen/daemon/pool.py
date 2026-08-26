"""A pool of warm OCP worker processes, owned by the daemon supervisor.

The dispatch rule, which is the whole design:

1. A free worker exists — use it. Warm, the common case.
2. All busy and the pool is below its cap — spawn one and wait for it. That caller pays
   roughly one OCP import, the same as running cold, but the worker PERSISTS, so a burst
   converges to warm instead of paying the import every time.
3. At the cap — wait a short while for one to free, then run cold if none does.

Rule 3 used to give up immediately, on the grounds that a queue is what made the old
single-process daemon worse than useless. That lesson was real but it was about a cap of
ONE: with a pool, refusing to wait at all means the cap bounds nothing. Overflow still
runs, so N callers produce N OCP processes no matter what the cap says, and the machine
can be driven into swap by a burst the pool was supposed to govern. A bounded wait puts
the ceiling back without reintroducing the serialisation: nobody blocks indefinitely, and
the cold path is still there the moment waiting stops paying.

The wait is bounded by roughly what running cold would have cost, so waiting is never the
slower choice by much. Jobs are usually short relative to an OCP import, so nearly every
wait ends in a warm worker rather than at the deadline.

Sizing follows the machine rather than a constant. See max_workers().
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time

DEFAULT_RECYCLE_AFTER = 200
DEFAULT_WORKER_IDLE_SECONDS = 300.0
_SPAWN_TIMEOUT_SECONDS = 120.0

# A warm worker measures ~281 MB resident on macOS/arm64 once it has served a job (the OCP
# import is lazy, so a freshly spawned one is ~25 MB until then). Adding a SECOND worker
# costs the system only ~50 MB, because OCP's mapped libraries are shared -- so summing RSS
# overstates the real cost by roughly 5x.
#
# The conservative figure is used anyway, deliberately. It only binds on small or
# containerised machines, which is exactly where over-spawning hurts and where the shared
# pages are least likely to save you; on anything roomy the CPU bound below decides first,
# so the pessimism costs nothing there.
WORKER_MEMORY_BYTES = 300 * 1024 * 1024
# Half the box. The rest is for the OS, the caller, the browser the Viewer runs in, and the
# geometry a build allocates on top of a worker's resting footprint.
MEMORY_FRACTION = 0.5
# Past this, more warm processes stop being the bottleneck and start being a liability to
# supervise. Nothing subtle -- just a refusal to let a huge machine spawn absurdly.
MAX_WORKERS_CEILING = 32
# Kept for machines where neither memory nor CPU can be read.
FALLBACK_MAX_WORKERS = 4

# How long a caller waits at the cap before running cold. A first job's OCP import measured
# 0.54 s with a warm page cache, so this is a few times the cost of the thing the caller
# would do instead -- long enough that a short job ahead of it frees a worker, short enough
# that waiting never becomes the expensive option. Cold-cache imports are slower, which is
# an argument for the headroom rather than against the bound.
DEFAULT_WAIT_SECONDS = 2.0


def _env_int(name: str) -> int | None:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _container_memory_limit() -> int | None:
    """A cgroup memory cap, which is the real limit inside a container.

    Physical RAM is the HOST's there. A 2 GB container on a 128 GB host that sizes itself
    against 128 GB gets OOM-killed, which is the shape of bug the JVM shipped for years
    before UseContainerSupport.
    """
    for path, unlimited in (
        ("/sys/fs/cgroup/memory.max", {"max"}),                  # cgroup v2
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", set()),  # cgroup v1
    ):
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            continue
        if raw in unlimited:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        # v1 spells "unlimited" as a huge sentinel rather than a word.
        if 0 < value < (1 << 62):
            return value
    return None


def _physical_memory() -> int | None:
    """Total RAM, or None where it cannot be read.

    TOTAL, never "available": available moves with the page cache and whatever else is
    running, so sizing on it would give the same command a different cap from one run to
    the next and make a report irreproducible. The fraction above is what leaves headroom.
    """
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        pass
    if sys.platform == "win32":  # pragma: no cover - not exercised by the POSIX runners
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
    return None


def memory_budget() -> int | None:
    """Bytes this pool may hold in warm workers, or None if RAM cannot be read."""
    physical = _physical_memory()
    limit = _container_memory_limit()
    if limit is not None:
        physical = limit if physical is None else min(physical, limit)
    return None if physical is None else int(physical * MEMORY_FRACTION)


def max_workers() -> int:
    """How many warm workers this machine should hold.

    Memory says what can be held, CPUs say what can usefully run at once, and the smaller
    wins. The flat default this replaced scaled DOWN on small machines but never up, so a
    64 GB workstation and an 8 GB laptop were both given four -- half the cores idle on one,
    and no way to tell without reading the source.
    """
    configured = _env_int("CADGEN_DAEMON_MAX_WORKERS")
    if configured is not None:
        return configured
    by_cpu = (os.cpu_count() or FALLBACK_MAX_WORKERS) - 2
    budget = memory_budget()
    if budget is None:
        return max(1, min(FALLBACK_MAX_WORKERS, by_cpu))
    by_memory = budget // WORKER_MEMORY_BYTES
    return max(1, min(by_memory, by_cpu, MAX_WORKERS_CEILING))


def wait_seconds() -> float:
    """Seconds to wait at the cap before telling the caller to run cold.

    Zero restores the old refuse-immediately behaviour, for anyone who wants it back.
    """
    raw = os.environ.get("CADGEN_DAEMON_WAIT", "").strip()
    if not raw:
        return DEFAULT_WAIT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_WAIT_SECONDS
    return max(0.0, value)


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
        # The working directory of the last job this worker served. Dispatch
        # prefers a free worker whose affinity matches the request, so repeat
        # builds of one model land on the worker whose in-memory op-memo cache
        # already holds that model's shapes (the disk tier makes a mismatch
        # cheap rather than free).
        self.affinity = ""
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
        finally:
            # Close the pipes explicitly; a supervisor that churns workers over a long
            # session would otherwise leak a file descriptor pair per worker.
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()


class Pool:
    """Owns every worker. Thread-safe; one lock, held only around bookkeeping."""

    def __init__(self) -> None:
        # A Condition, not a Lock: a caller at the cap sleeps here until release() or a
        # reaper frees a slot, instead of being turned away the moment the pool is full.
        self._cv = threading.Condition()
        self._workers: list[Worker] = []
        # Spawns in flight. Counted against the cap so two callers arriving together
        # cannot both see room for the last worker and both take it -- without this the
        # pool can exceed its own ceiling, which is the one thing it is for.
        self._pending = 0
        self.cold_overflows = 0
        self.crashes = 0
        self.recycles = 0
        self.waits = 0

    # --- acquisition -------------------------------------------------------------
    def acquire(self, affinity: str = "") -> Worker | None:
        """A worker to run one job on, or None meaning "run this cold".

        ``affinity`` is the job's working directory: among free workers, the
        one that last served that directory wins, so repeat builds of a model
        reuse the worker whose in-memory op-memo cache is already warm for it.
        Never trades warmth for a spawn or a wait — any free worker still
        beats both."""
        deadline: float | None = None
        with self._cv:
            while True:
                self._reap_dead_locked()
                chosen = None
                for worker in self._workers:
                    if worker.busy:
                        continue
                    if affinity and worker.affinity == affinity:
                        chosen = worker
                        break
                    if chosen is None:
                        chosen = worker
                if chosen is not None:
                    chosen.busy = True
                    if affinity:
                        chosen.affinity = affinity
                    return chosen
                if len(self._workers) + self._pending < max_workers():
                    self._pending += 1
                    break
                # At the cap. Wait for someone to finish rather than adding an OCP
                # process to a machine that is already running as many as it should.
                if deadline is None:
                    budget = wait_seconds()
                    if budget <= 0:
                        self.cold_overflows += 1
                        return None
                    deadline = time.monotonic() + budget
                    self.waits += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.cold_overflows += 1
                    return None
                self._cv.wait(remaining)
        # Spawn outside the lock: it costs an OCP import and must not block acquire().
        try:
            worker = Worker()
        except (OSError, WorkerGone):
            with self._cv:
                self._pending -= 1
                self.crashes += 1
                self._cv.notify()  # the slot this spawn reserved is free again
            return None
        with self._cv:
            self._pending -= 1
            worker.busy = True
            if affinity:
                worker.affinity = affinity
            self._workers.append(worker)
            return worker

    def release(self, worker: Worker, *, healthy: bool = True) -> None:
        with self._cv:
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
            # A worker went idle, or dropping one freed a slot to spawn into. Either way
            # somebody waiting at the cap can stop waiting; without this they sleep to
            # their deadline and run cold with an idle worker sitting right there.
            self._cv.notify()

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
        with self._cv:
            self._reap_dead_locked()
            now = time.monotonic()
            idle = [w for w in self._workers if not w.busy and now - w.last_used > DEFAULT_WORKER_IDLE_SECONDS]
            for worker in idle:
                if len(self._workers) <= 1:
                    break
                self._drop_locked(worker)
            self._cv.notify_all()

    def shutdown(self) -> None:
        with self._cv:
            for worker in list(self._workers):
                self._drop_locked(worker)
            # Nobody should still be waiting for a pool that is going away.
            self._cv.notify_all()

    # --- introspection -----------------------------------------------------------
    def snapshot(self) -> dict:
        with self._cv:
            return {
                "maxWorkers": max_workers(),
                "workers": [
                    {"pid": w.pid, "busy": w.busy, "jobsServed": w.jobs_served}
                    for w in self._workers
                ],
                "coldOverflows": self.cold_overflows,
                "waits": self.waits,
                "waitSeconds": wait_seconds(),
                "recycles": self.recycles,
                "crashes": self.crashes,
            }
