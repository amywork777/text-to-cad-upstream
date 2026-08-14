"""Warm-process daemon server for the CAD skill CLIs.

One long-lived process imports cadgen / OCP / build123d ONCE and then services
``scripts/gen`` / ``scripts/export`` / ``scripts/artifact`` / ``scripts/inspect``
/ ``scripts/snapshot`` invocations over a per-worktree unix socket, so opted-in
sessions (``CADGEN_WARM=1``) skip the multi-second interpreter+OCP startup on
every call. The daemon runs with ``CADGEN_DAEMON_CHILD=1`` so the launcher shim
never recurses into it.

Protocol — one JSON request per connection, JSON-lines response:

  request : {"tool": "gen"|"export"|"artifact"|"inspect"|"snapshot",
             "argv": [...], "cwd": "...",
             "token": <client version token>}
  response: {"stream": "stdout"|"stderr", "data": "..."} chunks, then
            {"exit": <int>} — or {"restart": true} when the client's version
            token differs from the daemon's startup token, after which the
            daemon exits so the client can respawn a fresh one.

Requests are handled strictly sequentially: OCP is single-threaded, and the cold
per-invocation CLIs this replaces were serialized anyway. Warm-process
determinism rides on cadgen's pre-run first-party module eviction (see
``cadgen._internal.generation.run_script_generator``); the daemon additionally
drops first-party modules after each request so model code never lingers
between requests. Python-level stdout/stderr are streamed to the client;
C-level OCP prints and daemon lifecycle logs land in the log file next to the
socket.
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from cadgen.daemon.client import compute_version_token, socket_path

# No sys.path setup: every tool the daemon serves is an ordinary cadgen module now, so it
# imports from the same distribution this file was loaded from. The block that used to
# mirror each launcher's lookup paths existed only because the parsers lived in the skill.

DEFAULT_IDLE_TIMEOUT_SECONDS = 600.0
REQUEST_READ_TIMEOUT_SECONDS = 30.0
CLIENT_LIVENESS_INTERVAL_SECONDS = 0.5

# Parser modules are imported directly rather than through a skill's launcher, so the
# daemon skips that launcher's CADGEN_WARM shim -- which would otherwise route straight
# back here. They are ordinary cadgen modules now, so this no longer depends on a skill's
# sys.path being set up first.
_TOOL_IMPORTS = {
    "gen": "cadgen.cli.step_gen",
    "export": "cadgen.cli.step_export",
    "artifact": "cadgen.cli.step_artifact",
    "inspect": "cadgen.cli.step_inspect.cli",
    "snapshot": "cadgen.cli.step_snapshot",
}
_TOOL_MAINS: dict[str, object] = {}

from cadgen.daemon import pool as pool_mod  # noqa: E402 - after _TOOL_IMPORTS, which worker.py reads

_POOL = pool_mod.Pool()


class _DaemonShutdown(BaseException):
    """Raised from the SIGTERM/SIGINT handler. A BaseException subclass distinct
    from SystemExit so a signal arriving mid-request cannot be mistaken for the
    running tool's own exit and swallowed by the per-request catches."""


class _StreamProxy(io.TextIOBase):
    """``sys.stdout``/``sys.stderr`` stand-in whose destination swaps per request.

    Installed BEFORE the tool modules are imported so def-time default bindings
    (e.g. snapshot's ``run_render_cli(stdout=sys.stdout, ...)``) capture the
    proxy and keep routing to the current request's client stream instead of
    the daemon log."""

    def __init__(self, fallback) -> None:
        self._fallback = fallback
        self._target = fallback

    def set_target(self, target) -> None:
        self._target = target

    def reset(self) -> None:
        self._target = self._fallback

    @property
    def encoding(self) -> str:  # TextIOBase declares encoding read-only
        return getattr(self._target, "encoding", None) or "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        return self._target.write(data)

    def flush(self) -> None:
        flush = getattr(self._target, "flush", None)
        if callable(flush):
            flush()

    def isatty(self) -> bool:
        return False


class _ChunkWriter:
    """File-like sink that forwards writes to the client as protocol frames.

    Shares ``send_lock`` with the liveness watchdog so job output and probe
    frames cannot interleave bytes on the socket."""

    def __init__(self, conn: socket.socket, stream: str, send_lock: threading.Lock) -> None:
        self._conn = conn
        self._stream = stream
        self._send_lock = send_lock

    def write(self, data) -> int:
        text = data if isinstance(data, str) else str(data)
        if text:
            with self._send_lock:
                _send(self._conn, {"stream": self._stream, "data": text})
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def _send(conn: socket.socket, frame: dict) -> None:
    conn.sendall(json.dumps(frame, separators=(",", ":")).encode("utf-8") + b"\n")


def _log(message: str) -> None:
    print(f"[cadgen-daemon] {message}", file=sys.__stderr__, flush=True)


def _idle_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("CADGEN_DAEMON_IDLE_TIMEOUT", "")))
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SECONDS


def _tool_main(tool: str):
    main = _TOOL_MAINS.get(tool)
    if main is None:
        main = getattr(importlib.import_module(_TOOL_IMPORTS[tool]), "main")
        _TOOL_MAINS[tool] = main
    return main


def _warm_imports() -> None:
    """Pay the heavy import cost before the socket exists — the client treats
    socket presence as readiness."""
    importlib.import_module("cadgen.generation")
    for tool in _TOOL_IMPORTS:
        try:
            _tool_main(tool)
        except Exception:  # noqa: BLE001 — surfaces per-request instead
            _log(f"warm import failed for {tool}:\n{traceback.format_exc()}")


def _evict_first_party_modules() -> None:
    # Same warm-process hygiene the viewer worker relies on: generation already
    # evicts first-party modules PRE-run for deterministic closure capture; this
    # post-request pass keeps model modules from lingering in the daemon between
    # requests (inspect/snapshot paths included).
    try:
        from cadgen._internal.source_hash import evict_first_party_modules
    except Exception:  # noqa: BLE001
        return
    with contextlib.suppress(Exception):
        evict_first_party_modules()


def _read_request(conn: socket.socket) -> dict | None:
    conn.settimeout(REQUEST_READ_TIMEOUT_SECONDS)
    chunks: list[bytes] = []
    try:
        while b"\n" not in (chunks[-1] if chunks else b""):
            data = conn.recv(65536)
            if not data:
                break
            chunks.append(data)
    except OSError:
        return None
    finally:
        conn.settimeout(None)
    raw = b"".join(chunks).split(b"\n", 1)[0].strip()
    if not raw:
        return None
    try:
        request = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    return request if isinstance(request, dict) else None


def _exit_code(exc: SystemExit, err: _ChunkWriter) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    err.write(f"{code}\n")
    return 1


def _watch_client(
    conn: socket.socket,
    send_lock: threading.Lock,
    done: threading.Event,
    tool: str,
    worker,
) -> None:
    """Kill the WORKER when the requesting client vanishes mid-job.

    Clients half-close their write side right after the request, so read-side EOF is
    normal and the only reliable death signal is a FAILED SEND (AF_UNIX raises immediately
    once the peer socket is gone). An empty stdout chunk is a no-op for every client, so
    it doubles as the liveness probe.

    The single-process daemon had to exit outright here, because the orphaned build was
    running inside it and there was no smaller thing to stop. With a pool there is: kill
    the one worker, leave the supervisor and every other job alone. The pool replaces it
    on the next acquire.
    """
    while not done.wait(CLIENT_LIVENESS_INTERVAL_SECONDS):
        try:
            with send_lock:
                _send(conn, {"stream": "stdout", "data": ""})
        except OSError:
            if done.is_set():
                return
            _log(f"{tool}: client disconnected mid-request; killing worker {worker.pid}")
            worker.kill()
            return


def _handle_request(
    conn: socket.socket,
    request: dict,
    stdout_proxy: _StreamProxy,
    stderr_proxy: _StreamProxy,
) -> None:
    """Relay one job to a warm worker and stream its frames back to the client.

    The supervisor no longer runs tools itself. It used to, which is why it could hold
    exactly one job: a tool needs os.chdir and sys.argv, and those are process globals.
    Each worker is its own process with its own globals, so jobs run concurrently without
    any of that reasoning -- and a segfaulting model costs one worker, not the daemon.

    The proxies are vestigial here (nothing in this process writes tool output any more)
    and are kept only so the signature matches what serve() passes.
    """
    del stdout_proxy, stderr_proxy
    tool = request.get("tool")
    argv = request.get("argv")
    send_lock = threading.Lock()
    started = time.perf_counter()

    if tool not in _TOOL_IMPORTS or not isinstance(argv, list):
        with send_lock:
            _send(conn, {"stream": "stderr", "data": f"cadgen-daemon: invalid request for tool {tool!r}\n"})
            _send(conn, {"exit": 1})
        return

    worker = _POOL.acquire()
    if worker is None:
        # Every worker busy and the pool is capped. Queueing here is what made the old
        # single-process daemon worse than useless for parallel work, so tell the client
        # to run cold instead.
        _log(f"{tool}: pool at capacity; client runs cold")
        with send_lock:
            _send(conn, {"cold": True})
        return

    exit_code, healthy = 1, True
    watchdog_done = threading.Event()
    watchdog = threading.Thread(
        target=_watch_client, args=(conn, send_lock, watchdog_done, tool, worker), daemon=True
    )
    watchdog.start()
    try:
        worker.send({
            "kind": "run",
            "tool": tool,
            "prog": request.get("prog"),
            "argv": [str(a) for a in argv],
            "cwd": request.get("cwd"),
        })
        for frame in worker.frames():
            if "exit" in frame:
                exit_code = int(frame.get("exit") or 0)
                break
            with send_lock:
                _send(conn, frame)
    except pool_mod.WorkerGone as exc:
        healthy = False
        with send_lock:
            _send(conn, {"stream": "stderr", "data": f"cadgen-daemon: {exc}\n"})
    except OSError:
        # The CLIENT went away mid-job. The worker is fine; stop relaying.
        healthy = True
    finally:
        watchdog_done.set()
        watchdog.join(timeout=CLIENT_LIVENESS_INTERVAL_SECONDS + 1.0)
        # A killed worker is not reusable; release() drops it and the pool respawns.
        _POOL.release(worker, healthy=healthy and worker.alive())

    _log(f"{tool} {argv!r} -> exit {exit_code} in {time.perf_counter() - started:.2f}s "
         f"(worker {worker.pid})")
    with contextlib.suppress(OSError):
        with send_lock:
            _send(conn, {"exit": exit_code})


_INFLIGHT: set[threading.Thread] = set()


def _serve_connection(conn, request, stdout_proxy, stderr_proxy) -> None:
    try:
        _handle_request(conn, request, stdout_proxy, stderr_proxy)
    except Exception:  # noqa: BLE001 - a job must never kill the supervisor
        _log("unhandled error serving a job:\n" + traceback.format_exc())
    finally:
        _INFLIGHT.discard(threading.current_thread())
        with contextlib.suppress(OSError):
            conn.close()


def serve() -> int:
    os.environ["CADGEN_DAEMON_CHILD"] = "1"
    sock_path = socket_path()
    token = compute_version_token()
    stdout_proxy = _StreamProxy(sys.stdout)
    stderr_proxy = _StreamProxy(sys.stderr)
    sys.stdout = stdout_proxy
    sys.stderr = stderr_proxy
    _warm_imports()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
    except OSError as exc:
        _log(f"cannot bind {sock_path}: {exc}")
        return 1
    server.listen(8)

    def _shutdown_handler(*_args) -> None:
        raise _DaemonShutdown

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _shutdown_handler)
    idle_timeout = _idle_timeout()
    _log(f"pid {os.getpid()} serving {sock_path} (token {token}, idle timeout {idle_timeout:.0f}s)")
    try:
        while True:
            server.settimeout(idle_timeout)
            try:
                conn, _ = server.accept()
            except TimeoutError:
                if any(thread.is_alive() for thread in list(_INFLIGHT)):
                    continue  # a long build is still running; not idle
                _POOL.reap_idle()
                _log("idle timeout; exiting")
                return 0
            try:
                request = _read_request(conn)
                if request is None:
                    continue
                if request.get("token") != token:
                    # Unlink BEFORE replying so the client's respawn cannot race
                    # this daemon's cleanup and lose the fresh daemon's socket.
                    server.close()
                    with contextlib.suppress(OSError):
                        os.unlink(sock_path)
                    with contextlib.suppress(OSError):
                        _send(conn, {"restart": True})
                    _log("version token changed; restarting")
                    return 0
                # One thread per job so a second client is served rather than queued.
                # The supervisor itself stays trivial -- it never imports OCP, so no
                # amount of model badness can take it down.
                worker_thread = threading.Thread(
                    target=_serve_connection,
                    args=(conn, request, stdout_proxy, stderr_proxy),
                    daemon=True,
                )
                _INFLIGHT.add(worker_thread)
                worker_thread.start()
                conn = None  # the thread owns it now
            except OSError:
                continue  # client vanished mid-request; keep serving
            finally:
                if conn is not None:
                    with contextlib.suppress(OSError):
                        conn.close()
            _POOL.reap_idle()
    except _DaemonShutdown:
        _log("signal received; exiting")
        return 0
    finally:
        _POOL.shutdown()
        with contextlib.suppress(OSError):
            server.close()
        with contextlib.suppress(OSError):
            os.unlink(sock_path)


USAGE = """\
cadgen-daemon takes no arguments.

It is the warm-process server, started for you by cadgen.daemon.client when
CADGEN_WARM=1 -- not a command to run by hand. It sits in scripts/ beside the
CLIs you probably meant: scripts/gen, scripts/export, scripts/inspect,
scripts/artifact, scripts/snapshot. Each of those takes --help.\
"""


def main(argv: list[str] | None = None) -> int:
    # Without this, ANY argument -- including --help, and including a typo on a real daemon
    # start -- fell through to serve() and bound the socket, so the caller got a resident
    # server for the full idle timeout instead of an answer.
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print(USAGE, file=sys.stderr)
        return 2
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
