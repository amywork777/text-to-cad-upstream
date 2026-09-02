"""The build memory ceiling: cap resolution, the trip, and memory on stage lines."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from cadgen._internal import memory_guard
from cadgen._internal.memory_guard import ENV_VAR, FLOOR_BYTES, MemoryGuard, resolve_cap_bytes
from cadgen.cli_logging import CliLogger

GB = 1024**3


class CapResolutionTest(unittest.TestCase):
    def test_env_override_in_gigabytes(self) -> None:
        self.assertEqual(12 * GB, resolve_cap_bytes({ENV_VAR: "12"}))
        self.assertEqual(int(1.5 * GB), resolve_cap_bytes({ENV_VAR: "1.5"}))

    def test_zero_disables(self) -> None:
        self.assertIsNone(resolve_cap_bytes({ENV_VAR: "0"}))
        self.assertIsNone(resolve_cap_bytes({ENV_VAR: "-3"}))

    def test_garbage_falls_back_to_the_default_not_to_disabled(self) -> None:
        self.assertIsNotNone(resolve_cap_bytes({ENV_VAR: "lots"}))

    def test_default_is_half_the_budget_with_a_floor(self) -> None:
        cap = resolve_cap_bytes({})
        self.assertIsNotNone(cap)
        self.assertGreaterEqual(cap, FLOOR_BYTES)


class GuardTripTest(unittest.TestCase):
    def _guard(self, peak: int, cap: int, stage: str = "run step model w16.py"):
        aborted: list[int] = []
        guard = MemoryGuard(
            cap,
            label="build of w16.py",
            describe_stage=lambda: stage,
            read_peak=lambda: peak,
            abort=aborted.append,
        )
        return guard, aborted

    def test_below_the_cap_nothing_happens(self) -> None:
        guard, aborted = self._guard(peak=3 * GB, cap=8 * GB)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertFalse(guard.check())
        self.assertEqual([], aborted)
        self.assertEqual("", err.getvalue())

    def test_above_the_cap_names_the_stage_and_the_override_then_aborts(self) -> None:
        guard, aborted = self._guard(peak=40 * GB, cap=32 * GB)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertTrue(guard.check())
        self.assertEqual([memory_guard.EXIT_CODE], aborted)
        message = err.getvalue()
        self.assertIn("during run step model w16.py", message)
        self.assertIn("peak 40.0 GB > cap 32.0 GB", message)
        self.assertIn(f"{ENV_VAR}=<gigabytes>", message)
        self.assertIn(f"{ENV_VAR}=0", message)

    def test_disabled_guard_never_reads_or_aborts(self) -> None:
        reads: list[int] = []
        guard = MemoryGuard(None, label="x", read_peak=lambda: reads.append(1) or 10**15, abort=lambda code: self.fail("aborted"))
        with guard:
            self.assertFalse(guard.check())
        self.assertEqual([], reads)

    def test_context_manager_thread_trips_on_its_own(self) -> None:
        import time

        aborted: list[int] = []
        guard = MemoryGuard(1, label="x", read_peak=lambda: 2, abort=aborted.append, sample_seconds=0.01)
        with guard:
            deadline = time.monotonic() + 2
            while not aborted and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual([memory_guard.EXIT_CODE], aborted)


class StageLinesCarryMemoryTest(unittest.TestCase):
    def test_verbose_stage_line_reports_peak_rss_and_stage_nesting(self) -> None:
        err = io.StringIO()
        logger = CliLogger("cad", verbose=True, stream=err) if "stream" in CliLogger.__dataclass_fields__ else CliLogger("cad", verbose=True)
        with redirect_stderr(err):
            with logger.timed("outer"):
                with logger.timed("inner"):
                    self.assertEqual("inner", logger.current_stage())
                self.assertEqual("outer", logger.current_stage())
        self.assertEqual("", logger.current_stage())
        text = err.getvalue()
        self.assertIn("inner completed in", text)
        self.assertRegex(text, r"outer completed in .*\(peak rss \d+\.\d GB\)")


if __name__ == "__main__":
    unittest.main()
