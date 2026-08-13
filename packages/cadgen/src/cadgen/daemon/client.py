"""Stdlib-only client for the warm CAD CLI daemon.

The tool launchers' ``CADGEN_WARM`` shim imports this module BEFORE any heavy
import, so it must stay dependency-free and cheap to import. Everything here
falls back to ``None`` (caller runs inline, cold) on any spawn or protocol
problem — the daemon is a fast path, never a requirement.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# The installed cadgen package directory. Everything the daemon holds resident lives under
# it, so it is both the identity of "which cadgen is this" and the thing to watch for edits.
# It resolves correctly either way: an editable install points at a checkout's source, a
# wheel install at site-packages.
CADGEN_DIR = Path(__file__).resolve().parents[1]

SPAWN_WAIT_SECONDS = 30.0  # first daemon start pays the full OCP import

# The daemon handles requests STRICTLY SEQUENTIALLY. A client that connects while
# the daemon is still finishing someone else's build — including an orphaned one
# whose client was killed — is accepted by the listen backlog and then simply
# waits. Without a deadline that wait is unbounded, which is how a warm call ends
# up hanging for minutes on a model that builds cold in seconds. Bound it: a
# legitimate large build can be silent for a long time, so the default is
# generous, but it is finite, so the documented cold fallback actually happens.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0
# What makes a running daemon stale. The distribution version alone is not enough in a
# checkout, where an editable install keeps one version across every edit; .py mtimes alone
# are not enough for a wheel, where they are fixed at install time and two versions can be
# installed in turn without any file changing under a given path. Use both.
# Skill code is deliberately NOT watched any more: the skills hold thin shims that the
# daemon never imports, so editing one cannot make the resident process stale.

_RESTART = object()


def socket_path() -> Path:
    override = os.environ.get("CADGEN_DAEMON_SOCKET")
    if override:
        return Path(override)
    digest = hashlib.sha256(str(CADGEN_DIR).encode("utf-8")).hexdigest()[:12]
    return Path(os.environ.get("TMPDIR") or "/tmp") / f"cadgen-daemon-{digest}.sock"


def log_path(sock_path: Path) -> Path:
    return sock_path.with_suffix(".log")


def request_timeout() -> float:
    """Seconds to wait for the daemon before giving up and running cold.

    ``CADGEN_DAEMON_TIMEOUT`` overrides; 0 or a negative value disables the
    deadline entirely (the old, unbounded behaviour) for anyone who genuinely
    wants to wait out a very long queued build.
    """
    raw = os.environ.get("CADGEN_DAEMON_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS
    return value if value > 0 else 0.0


def compute_version_token(root: Path | None = None) -> str:
    """The running daemon's identity: cadgen's version plus the newest ``.py`` mtime under
    it. Client and server compute this identically; inequality means restart."""
    base = Path(root) if root is not None else CADGEN_DIR
    newest = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            try:
                mtime = os.stat(os.path.join(dirpath, filename)).st_mtime_ns
            except OSError:
                continue
            newest = max(newest, mtime)

    from cadgen import __version__

    return f"{__version__}:{newest}"


def run_via_daemon(tool: str, argv: list[str], cwd: str | None = None) -> int | None:
    """Run one CLI invocation on the warm daemon; ``None`` means run inline instead."""
    if os.environ.get("CADGEN_WARM") != "1" or os.environ.get("CADGEN_DAEMON_CHILD"):
        return None
    argv = [str(arg) for arg in argv]
    if "-" in argv:
        # "-" conventionally reads a payload from stdin (e.g. snapshot --job -);
        # the daemon has no stdin channel, so run those inline.
        return None
    payload = {
        "tool": str(tool),
        "argv": argv,
        "cwd": str(cwd) if cwd else os.getcwd(),
        "token": compute_version_token(),
    }
    sock_path = socket_path()
    for attempt in range(2):
        conn = _connect_or_spawn(sock_path)
        if conn is None:
            return None
        try:
            outcome = _run_request(conn, payload)
        finally:
            try:
                conn.close()
            except OSError:
                pass
        if outcome is _RESTART and attempt == 0:
            continue  # stale daemon exited; respawn once and retry
        return outcome if isinstance(outcome, int) else None
    return None


def _connect(sock_path: Path) -> socket.socket:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(str(sock_path))
    except OSError:
        conn.close()
        raise
    return conn


def _connect_or_spawn(sock_path: Path) -> socket.socket | None:
    try:
        return _connect(sock_path)
    except OSError:
        pass
    try:
        sock_path.unlink()  # stale socket from a dead daemon
    except FileNotFoundError:
        pass
    except OSError:
        return None
    process = _spawn_daemon(sock_path)
    if process is None:
        return None
    deadline = time.monotonic() + SPAWN_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            return _connect(sock_path)
        except OSError:
            if process.poll() is not None:
                return None
            time.sleep(0.05)
    return None


def _spawn_daemon(sock_path: Path) -> subprocess.Popen | None:
    env = dict(os.environ)
    env["CADGEN_DAEMON_CHILD"] = "1"
    env.setdefault("CADGEN_DAEMON_SOCKET", str(sock_path))
    try:
        with open(log_path(sock_path), "ab") as log_file:
            return subprocess.Popen(
                [sys.executable, "-m", "cadgen.daemon"],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
    except OSError:
        return None


def _run_request(conn: socket.socket, payload: dict) -> int | object | None:
    """Send one request and stream the response; int exit code, ``_RESTART``, or
    ``None`` on any protocol fault."""
    try:
        conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        conn.shutdown(socket.SHUT_WR)
    except OSError:
        return None
    timeout = request_timeout()
    if timeout:
        # Applies per read, not to the whole request: a daemon that is streaming
        # output keeps resetting it, so only genuine silence trips the deadline.
        conn.settimeout(timeout)
    streams = {"stdout": sys.stdout, "stderr": sys.stderr}
    try:
        with conn.makefile("r", encoding="utf-8") as reader:
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    return None
                if not isinstance(message, dict):
                    return None
                if message.get("restart"):
                    return _RESTART
                if "exit" in message:
                    return int(message["exit"])
                target = streams.get(message.get("stream"))
                data = message.get("data")
                if target is None or not isinstance(data, str):
                    return None
                target.write(data)
                target.flush()
    except TimeoutError:
        # Silent past the deadline: either the daemon is wedged, or it is still
        # grinding through a queued build we cannot see. Either way, fall back to
        # a cold in-process run so THIS invocation still completes. Say so on
        # stderr — a silent 10-minute stall that then "just works" is the exact
        # confusion this deadline exists to prevent.
        print(
            f"cadgen-daemon: no response for {timeout:.0f}s; running cold "
            "(set CADGEN_DAEMON_TIMEOUT to change or 0 to wait indefinitely)",
            file=sys.stderr,
            flush=True,
        )
        return None
    except (OSError, ValueError):
        return None
    return None  # EOF without an exit frame
