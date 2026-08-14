"""``cadgen viewer stop`` — terminate a running CAD Viewer by port or pid.

Only ever signals a process the registry can still identify: ``live_entries()`` probes
each recorded port and requires the answering pid to match the entry. Without that, a
stale file naming a port that something ELSE has since taken would make this command kill
a stranger, which is the worst thing it could do.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from collections.abc import Sequence

from cadgen.viewer import registry

DEFAULT_PROG = "cadgen viewer stop"
_EXIT_WAIT_S = 3.0


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = argparse.ArgumentParser(prog=prog, description="Stop a running CAD Viewer")
    parser.add_argument("--port", type=int, default=None, help="Port of the viewer to stop.")
    parser.add_argument("--pid", type=int, default=None, help="Process id of the viewer to stop.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.port is None and args.pid is None:
        sys.stderr.write("Specify which viewer to stop: --port <n> or --pid <n>.\n")
        return 2

    entries = registry.live_entries()
    if args.port is not None:
        target, described = registry.find_by_port(args.port, entries=entries), f"port {args.port}"
    else:
        target = next((entry for entry in entries if entry.get("pid") == args.pid), None)
        described = f"pid {args.pid}"

    if target is None:
        sys.stderr.write(f"No running CAD Viewer for {described}.\n")
        return 1

    pid = int(target["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        sys.stderr.write(f"Could not stop pid {pid}: {exc}\n")
        return 1

    deadline = time.time() + _EXIT_WAIT_S
    while time.time() < deadline:
        if not registry.probe(target, timeout_s=0.25):
            registry.unregister(pid)
            sys.stdout.write(f"Stopped CAD Viewer on port {target.get('port')} (pid {pid}).\n")
            return 0
        time.sleep(0.1)
    sys.stderr.write(f"CAD Viewer pid {pid} did not exit within {_EXIT_WAIT_S:g}s.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
