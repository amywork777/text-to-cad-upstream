"""The flock-backed generation snapshot: idle | writing | busy, decided by the kernel.

This is the one "is a build running" answer in the system. The viewer's JS
status authority reads a build's progress record ADVISORILY (decoration only);
every correctness decision — producer mutual exclusion, contended builds —
rides on this kernel state, which no pid, heartbeat, or age window may ever
approximate (cadgen/coordination/lock.py documents the measured failures of
that design).
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.coordination import lock as lock_mod  # noqa: E402
from cadgen.coordination import snapshot  # noqa: E402


@unittest.skipUnless(
    lock_mod.locking_available(),
    "no kernel locking backend here, so there is no state for the snapshot to report",
)
class GenerationLock(unittest.TestCase):
    """The snapshot reports what the kernel says. There is no pid, heartbeat, or age to
    fake, so these drive REAL lock states — including from a separate process, which is
    the case that actually matters.

    Held through coordination.lock rather than raw fcntl. The lock has two backends and
    the snapshot is supposed to read either; calling flock directly meant this whole class
    skipped on Windows, leaving the msvcrt backend's contribution to the viewer's "is a
    build running" answer untested on the only platform where it is used.
    """

    def _lock_for(self, package_dir):
        from cadgen.coordination.paths import write_lock_path

        return str(write_lock_path(package_dir))

    def test_unheld_lock_is_idle(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            open(self._lock_for(pkg), "wb").close()
            self.assertEqual("idle", snapshot(pkg).state)

    def test_never_built_artifact_is_idle(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                "idle", snapshot(os.path.join(d, "never-built.step")).state
            )

    def test_reading_status_does_not_create_the_sentinel(self):
        """The old probe opened the sentinel "a+b", so merely asking for status
        materialised a lock file for an artifact that had never been built."""
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            snapshot(pkg)
            self.assertFalse(os.path.exists(self._lock_for(pkg)))

    def test_empty_path_is_idle(self):
        self.assertEqual("idle", snapshot("").state)

    def test_held_lock_reads_as_writing(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            with lock_mod.exclusive(self._lock_for(pkg)):
                self.assertEqual("writing", snapshot(pkg).state)
            self.assertEqual("idle", snapshot(pkg).state)

    def test_concurrent_readers_do_not_see_a_phantom_build(self):
        """flock conflicts per open file description, so the previous LOCK_EX probe
        conflicted with OTHER PROBES: two status reads racing over an idle, fresh model
        made one of them report a build in flight (~6% with four threads)."""
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            open(self._lock_for(pkg), "wb").close()
            seen = []
            guard = threading.Lock()

            def worker():
                hits = sum(
                    1 for _ in range(1500) if snapshot(pkg).state != "idle"
                )
                with guard:
                    seen.append(hits)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(0, sum(seen))

    def test_lock_held_by_another_process_is_writing(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            lp = self._lock_for(pkg)
            ready = os.path.join(d, "ready")
            # Holds it the way a real builder does, so this exercises whichever backend
            # the platform actually ships rather than a POSIX-only call.
            code = (
                "import time\n"
                "from cadgen.coordination import lock\n"
                f"with lock.exclusive({lp!r}):\n"
                f"    open({ready!r},'wb').close()\n"
                "    time.sleep(30)\n"
            )
            proc = subprocess.Popen([sys.executable, "-c", code])
            try:
                for _ in range(200):
                    if os.path.exists(ready):
                        break
                    time.sleep(0.02)
                self.assertTrue(os.path.exists(ready), "helper never acquired the lock")
                self.assertEqual("writing", snapshot(pkg).state)
                # SIGKILL: no unwind, no cleanup handler. The kernel must still release.
                proc.kill()
                proc.wait(timeout=10)
                for _ in range(200):
                    if snapshot(pkg).state == "idle":
                        break
                    time.sleep(0.02)
                self.assertEqual(
                    "idle",
                    snapshot(pkg).state,
                    "a killed builder must leave no stale lock",
                )
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_a_dead_runs_record_is_not_shown_as_live_progress(self):
        """A SIGKILLed build leaves a non-terminal record on disk forever. Attributing it
        to whoever holds the lock NEXT is what made the viewer render "Meshing components
        31/50" for a run that had meshed nothing, then jump backwards."""
        from cadgen.coordination import record as record_mod
        from cadgen.coordination.paths import status_path

        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            record_mod.write_record(
                status_path(pkg),
                record_mod.build_record(
                    run_id="deadbeef",
                    kind="step-package",
                    intent="write",
                    started_at_ms=0.0,
                    outcome=None,
                    progress={"phase": "components", "done": 31, "total": 50, "ratio": 0.77},
                ),
            )
            with lock_mod.exclusive(self._lock_for(pkg)):
                snap = snapshot(pkg)
            self.assertEqual("writing", snap.state)
            self.assertIsNone(snap.progress)


if __name__ == "__main__":
    unittest.main()
