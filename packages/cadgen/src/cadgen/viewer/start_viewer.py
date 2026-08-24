"""Single-port CAD Viewer launcher (serve mode, Python backend).

Runs the `start` npm script: it starts the Python CAD Viewer backend — which
serves the prebuilt Vite bundle in `dist/` plus the /__cad API — on a single
port (default 3245). If the port is free it starts; if the port is already in
use it exits 1 with a `--port <n>` hint. It does NOT probe-and-reuse a running
Viewer or roll onto another port. Prints the load-bearing stdout contract (the
CAD Viewer URL line + optional --json {url,port,action}).

A Viewer serves ONE directory, given by --root and defaulting to the process
cwd. The page is always the bare origin; `?file=` selects a file inside that
root. To serve a second directory, start a second Viewer on another port --
`cadgen viewer list` shows which root each running instance holds.

This is the consumer entry point for running the built Viewer. For local client
iteration in a source checkout use `npm run dev` (Vite/HMR) instead; see the
repo AGENTS.md for the dev-vs-prod and per-worktree port guidance.

Run: python -m cadgen.viewer.start_viewer [--port N] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time

from cadgen.viewer import cadgen_bridge
from cadgen.viewer import registry
from cadgen.viewer.server_info import DEFAULT_VIEWER_PORT, DEFAULT_VIEWER_HOST

_PROBE_TIMEOUT_S = 0.35


def viewer_url(host: str, port: int) -> str:
    """The Viewer URL: just the origin.

    The path used to BE the served directory, which is why this once had to convert a
    filesystem path into URL form. A viewer serves one root now, so there is nothing
    to encode -- `?file=` names a file inside it."""
    return f"http://{host}:{port}/"


def port_is_free(host: str, port: int) -> bool:
    """True only when nothing is listening on host:port (connection refused). A
    live listener — or an ambiguous/unreachable socket — counts as occupied, so
    we never race a bind against another process."""
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


def spawn_backend(host: str, port: int, dist_root: str = "", root: str = ""):
    """Spawn the Python backend (serves the built dist + /__cad) on host:port."""
    env = dict(os.environ)
    env["VIEWER_CAD_BACKEND_VALIDATED"] = "1"
    cmd = [sys.executable, "-m", "cadgen.viewer.server", "--host", host, "--port", str(port)]
    if root:
        cmd += ["--root", str(root)]
    # --dist is threaded through rather than resolved here so the child reports the
    # missing-client error itself, with the same text however it was started.
    if dist_root:
        cmd += ["--dist", str(dist_root)]
    return subprocess.Popen(cmd, env=env)


def open_when_ready(url: str, host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Wait for the backend to answer, then open `url` in the user's browser.

    Opening immediately after spawn races the child's bind and lands on a connection
    error, so poll /__cad/server first. Best-effort throughout: a timeout or a machine
    with no browser is a warning, never a failed start -- the URL is already on stdout
    and remains the real interface.
    """
    import urllib.error
    import urllib.request

    probe = f"http://{host}:{port}/__cad/server"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=0.25) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.1)
    else:
        print(f"Viewer did not answer within {timeout_s:g}s; not opening a browser.", file=sys.stderr)
        return False

    import webbrowser

    try:
        if webbrowser.open(url):
            return True
    except Exception as exc:  # noqa: BLE001 - a browser launcher must never fail the start
        print(f"Could not open a browser: {exc}", file=sys.stderr)
        return False
    print("Could not open a browser; use the URL above.", file=sys.stderr)
    return False


# Both front doors reach this: `cadgen viewer` (which passes its own name) and
# `python -m cadgen.viewer` (which does not, so argparse derives it from argv[0]).
DEFAULT_PROG = "python -m cadgen.viewer"


def main(argv=None, *, prog: str = DEFAULT_PROG):
    parser = argparse.ArgumentParser(
        prog=prog, description="Start the Python CAD Viewer backend on a single port"
    )
    parser.add_argument("--host", default=DEFAULT_VIEWER_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_VIEWER_PORT)
    parser.add_argument("--json", action="store_true", dest="json_result")
    # Opt-in, the inverse of Jupyter's auto-open-by-default: this viewer is started by
    # agents far more often than by humans, and an agent does not want a browser window.
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the Viewer URL in your browser once the backend answers.",
    )
    parser.add_argument(
        "--dist",
        default="",
        dest="dist_root",
        help="Directory holding the built CAD Viewer client. Defaults to the copy shipped "
             "inside cadgen; CADGEN_VIEWER_DIST is the environment equivalent.",
    )
    parser.add_argument(
        "--root",
        default="",
        help="The directory this Viewer serves. Defaults to the current directory. "
             "One root per instance: start another Viewer on another port to serve another.",
    )
    args, _unknown = parser.parse_known_args(argv)

    # The one directory this Viewer will serve. Validated before the port is taken, so a
    # bad --root fails immediately instead of after the instance is registered.
    directory = os.path.abspath(str(args.root or "").strip() or os.getcwd())
    if not os.path.isdir(directory):
        print(f"CAD Viewer root is not a directory: {directory}", file=sys.stderr)
        return 1
    host, port = args.host, args.port

    if not port_is_free(host, port):
        # Deliberately NOT reuse (source-blind reuse of whatever held the port was a real
        # bug here): say who has it so the collision is diagnosable, then still refuse.
        holder = registry.find_by_port(port)
        if holder is not None:
            print(
                f"Port {port} on {host} is already serving a CAD Viewer: "
                f"pid {holder.get('pid')}, cadgen {holder.get('version') or '?'}, "
                f"from {holder.get('packageDir') or '?'}.",
                file=sys.stderr,
            )
            print(
                f"Stop it with `cadgen viewer stop --port {port}`, or rerun with --port <n>.",
                file=sys.stderr,
            )
            return 1
        print(
            f"Port {port} on {host} is already in use. "
            f"Rerun with --port <n> to use a different port.",
            file=sys.stderr,
        )
        return 1

    try:
        cadgen_bridge.require_cadgen_runtime(directory)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    url = viewer_url(host, port)
    print(f"Starting CAD Viewer at {url} (serving {directory})")
    print(f"CAD Viewer URL: {url}")
    if args.json_result:
        print(json.dumps({"url": url, "port": port, "action": "start"}))
    sys.stdout.flush()
    child = spawn_backend(host, port, args.dist_root, root=directory)
    if args.open_browser:
        # After spawn (nothing to poll before it), before wait() blocks for the child.
        open_when_ready(url, host, port)
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
