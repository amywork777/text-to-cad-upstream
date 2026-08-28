"""``cadgen viewer`` — start the CAD Viewer (the pure-JS server) on a local directory.

The viewer's backend is Node (``viewer/server`` in a checkout, ``_runtime/viewer_server``
in an installed cadgen); this command exists so a pip-installed cadgen can still start it
without knowing where the runtime lives. It resolves the server entry and the built
client, then execs ``node`` with the caller's arguments passed through — the stdout
contract (the ``CAD Viewer URL:`` line, ``--json``) is printed by the server itself.

The viewer is a static visualization tool: it runs no Python of its own (status,
rendering and the WASM STEP import are all JS), so nothing is handed down to the
child beyond the arguments. Node >= 22 is the one hard requirement.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from cadgen.assets import AssetMissing, viewer_dist_dir, viewer_server_entry

DEFAULT_PROG = "cadgen viewer"


def node_executable() -> str:
    configured = str(os.environ.get("VIEWER_NODE") or "").strip()
    if configured:
        return configured
    return shutil.which("node") or ""


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    node = node_executable()
    if not node:
        print(
            "The CAD Viewer server runs on Node.js (>= 22), which was not found on PATH.\n"
            "Install Node or point VIEWER_NODE at a node executable.",
            file=sys.stderr,
        )
        return 1
    try:
        server_entry = viewer_server_entry()
    except AssetMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1

    env = dict(os.environ)
    # The interpreter that ran `cadgen viewer` is by definition one that can import

    cmd = [node, str(server_entry), *args]
    if "--dist" not in args:
        try:
            cmd += ["--dist", str(viewer_dist_dir())]
        except AssetMissing:
            # The server resolves its own sibling dist (a source checkout's
            # viewer/dist); only an installed cadgen with a broken wheel truly
            # has none, and the server's error names the fix.
            pass
    if "--root" not in args:
        cmd += ["--root", os.getcwd()]

    child = subprocess.Popen(cmd, env=env)

    # Forward termination to the node child: killing this launcher must not
    # orphan a server holding the port.
    import signal

    def _forward(signum, _frame):
        child.terminate()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, _forward)
        except (ValueError, OSError):
            pass
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
