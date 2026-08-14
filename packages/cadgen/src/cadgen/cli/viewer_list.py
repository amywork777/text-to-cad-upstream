"""``cadgen viewer list`` — what CAD Viewers are running, and whose code they run.

The equivalent of ``jupyter server list`` / TensorBoard's ``.tensorboard-info``. One
viewer serves any directory by URL, so instances never differ by what they serve; they
differ by WHICH CHECKOUT'S CODE answers a port, which is why every row leads with the
version and package directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence

from cadgen.viewer import registry

DEFAULT_PROG = "cadgen viewer list"


def _age(started: float) -> str:
    if not started:
        return ""
    seconds = max(0, int(time.time() - started))
    if seconds >= 3600:
        return f"  up {seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"  up {seconds // 60}m"


def format_entry(entry: dict) -> str:
    url = entry.get("publicUrl") or f"http://{entry.get('host', '127.0.0.1')}:{entry.get('port')}/"
    return (
        f"  port {entry.get('port')}  pid {entry.get('pid')}  "
        f"cadgen {entry.get('version') or '?'}{_age(entry.get('startedAt') or 0)}\n"
        f"    {url}\n"
        f"    {entry.get('packageDir') or '?'}"
    )


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = argparse.ArgumentParser(prog=prog, description="List running CAD Viewers")
    parser.add_argument("--json", action="store_true", dest="json_result")
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = registry.live_entries()  # also reaps anything that fails its identity probe
    if args.json_result:
        sys.stdout.write(json.dumps(entries, separators=(",", ":")) + "\n")
        return 0
    if not entries:
        sys.stdout.write("No CAD Viewer is running.\n")
        return 0
    sys.stdout.write(f"{len(entries)} CAD Viewer{'s' if len(entries) != 1 else ''} running:\n")
    for entry in entries:
        sys.stdout.write(format_entry(entry) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
