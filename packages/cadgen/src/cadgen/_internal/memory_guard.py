"""A hard ceiling on one build's memory, so a runaway kernel operation ends the
BUILD instead of the machine.

A model can always author a boolean the kernel cannot finish -- a fillet-heavy
casting used as a tool, a fuzzy fuse over a thousand tangent faces -- and OCCT
answers by allocating until the OS steps in. On 2026-09-02 that took a
workstation down overnight: single build processes reached 100-230 GB and the
kernel's memory killer took unrelated processes with them, while the builds
themselves printed nothing. The daemon's dead-worker message and the runner's
teaching errors are useless if the machine is gone.

The guard samples this process's PEAK resident size once a second and, past the
cap, prints one line naming the cap, the stage the build was in, and the
override, then exits the process. It exits rather than raising because the
runaway is inside a C++ call that Python cannot interrupt: ``KeyboardInterrupt``
would be delivered when the boolean returns, which is never. Locks are
``flock``-held and released by the kernel on exit; progress records are UI.

Default: half of the memory budget the daemon pool already sizes itself by
(the cgroup limit inside a container, else physical RAM), never below 4 GB.
A legitimate full build of a 2,500-part engine measured 4.1 GB, so a 64 GB
workstation gives 8x headroom. ``CADGEN_MAX_RSS_GB`` overrides; ``0`` disables.
"""

from __future__ import annotations

import os
import resource
import sys
import threading
import time
from typing import Callable

ENV_VAR = "CADGEN_MAX_RSS_GB"
DEFAULT_FRACTION_OF_BUDGET = 0.5
FLOOR_BYTES = 4 * 1024**3
SAMPLE_SECONDS = 1.0
EXIT_CODE = 137  # the code the OS killer would have produced, so wrappers treat both alike


def peak_rss_bytes() -> int:
    """This process's peak resident size in bytes (ru_maxrss is KB on Linux, bytes on macOS)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage) if sys.platform == "darwin" else int(usage) * 1024


def format_gb(value: int | float) -> str:
    return f"{value / 1024**3:.1f} GB"


def resolve_cap_bytes(environ=None) -> int | None:
    """The cap in bytes, or None when disabled.

    ``CADGEN_MAX_RSS_GB``: a positive number of gigabytes; ``0`` disables; an
    unparsable value is ignored (the default applies) rather than disabling the
    guard by accident."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_VAR, "")).strip()
    if raw:
        try:
            gigabytes = float(raw)
        except ValueError:
            gigabytes = None
        if gigabytes is not None:
            if gigabytes <= 0:
                return None
            return int(gigabytes * 1024**3)
    from cadgen.daemon.pool import memory_budget

    budget = memory_budget()
    if budget is None:
        return FLOOR_BYTES
    return max(FLOOR_BYTES, int(budget * DEFAULT_FRACTION_OF_BUDGET))


class MemoryGuard:
    """Watch the process's peak RSS on a daemon thread; abort past the cap.

    ``read_peak`` and ``abort`` are injectable for tests. ``describe_stage`` is
    consulted at abort time so the message names what the build was doing."""

    def __init__(
        self,
        cap_bytes: int | None,
        *,
        label: str,
        describe_stage: Callable[[], str] | None = None,
        read_peak: Callable[[], int] = peak_rss_bytes,
        abort: Callable[[int], None] | None = None,
        sample_seconds: float = SAMPLE_SECONDS,
    ) -> None:
        self.cap_bytes = cap_bytes
        self.label = label
        self.describe_stage = describe_stage or (lambda: "")
        self.read_peak = read_peak
        self.abort = abort or (lambda code: os._exit(code))
        self.sample_seconds = sample_seconds
        self.tripped_at: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> bool:
        """One sample; True when the cap was exceeded (and the abort was invoked)."""
        if self.cap_bytes is None:
            return False
        peak = self.read_peak()
        if peak <= self.cap_bytes:
            return False
        self.tripped_at = peak
        stage = self.describe_stage()
        where = f" during {stage}" if stage else ""
        sys.stderr.write(
            f"cadgen: {self.label} exceeded the build memory cap{where}: peak {format_gb(peak)} "
            f"> cap {format_gb(self.cap_bytes)}. Aborting this build so the machine keeps running. "
            f"A runaway kernel operation (a boolean or fillet that never converges) is the usual cause; "
            f"the stage named above is where to look. Raise the cap with {ENV_VAR}=<gigabytes>, or "
            f"{ENV_VAR}=0 to disable the guard.\n"
        )
        sys.stderr.flush()
        self.abort(EXIT_CODE)
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.sample_seconds):
            if self.check():
                return

    def __enter__(self) -> "MemoryGuard":
        if self.cap_bytes is not None:
            self._thread = threading.Thread(target=self._run, name="cadgen-memory-guard", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.sample_seconds * 2)
