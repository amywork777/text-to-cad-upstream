"""One warm OCP process. Reads job requests on stdin, writes framed output on stdout.

The daemon used to run tools inside itself, which capped it at one job forever: a tool
needs ``os.chdir`` and ``sys.argv``, and those are process globals. Moving the work into
subprocesses gives each job its own globals, so concurrency across workers costs nothing
to reason about — and a model that segfaults OCP takes down one worker instead of the
daemon.

The frames here are deliberately the same shape the daemon sends its client
(``{"stream": ..., "data": ...}`` then ``{"exit": ...}``), so the supervisor is a pure
relay and the client's wire protocol is untouched.

Two request kinds:

* ``run``    — a CLI tool, output streamed as frames. What the skill commands use.
* ``invoke`` — a cadgen module's ``main``, result returned as one payload. What the CAD
  Viewer needs, replacing its own warm-worker system.

Exits when stdin closes, so a supervisor that dies cannot leave a 274 MB OCP process
behind.
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import json
import os
import sys
import tempfile
import traceback

# Same registry the supervisor validates against; imported rather than duplicated.
from cadgen.daemon.server import _TOOL_IMPORTS, _evict_first_party_modules


def _emit(frame: dict) -> None:
    """One JSON line on the real stdout. Never the redirected one."""
    sys.__stdout__.write(json.dumps(frame, separators=(",", ":")) + "\n")
    sys.__stdout__.flush()


class _FrameWriter(io.TextIOBase):
    """File-like sink that turns a tool's writes into stream frames."""

    def __init__(self, stream: str) -> None:
        self._stream = stream

    def write(self, data) -> int:
        text = data if isinstance(data, str) else str(data)
        if text:
            _emit({"stream": self._stream, "data": text})
        return len(text)

    def isatty(self) -> bool:
        return False


def _park() -> None:
    """Leave the job's directory for one that cannot be deleted out from under us.

    A worker outlives the directories it builds in, and it inherits its starting cwd from
    whichever client happened to spawn the daemon. Holding either means a later
    ``os.getcwd()`` raises once that directory is removed, failing every subsequent job on
    this worker with no useful message. The single-process daemon never hit this because
    it restored the daemon's own cwd; a pooled worker is long-lived across many clients.
    """
    with contextlib.suppress(OSError):
        os.chdir(tempfile.gettempdir())


def _tool_main(tool: str):
    return getattr(importlib.import_module(_TOOL_IMPORTS[tool]), "main")


def _run(request: dict) -> int:
    tool = request.get("tool")
    argv = [str(a) for a in request.get("argv") or []]
    cwd = request.get("cwd")
    prog = str(request.get("prog") or "") or None

    if tool not in _TOOL_IMPORTS:
        _emit({"stream": "stderr", "data": f"cadgen-daemon: unknown tool {tool!r}\n"})
        return 1

    previous_argv = sys.argv
    out, err = _FrameWriter("stdout"), _FrameWriter("stderr")
    try:
        if isinstance(cwd, str) and os.path.isdir(cwd):
            os.chdir(cwd)
        sys.argv = [prog or f"scripts/{tool}", *argv]
        main = _tool_main(tool)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            # Pass the caller's name where the parser takes one, so a command reports the
            # same usage warm as cold.
            if prog and "prog" in inspect.signature(main).parameters:
                result = main(argv, prog=prog)
            else:
                result = main(argv)
        return 0 if result is None else int(result)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            err.write(code + "\n")
            return 1
        return int(code or 0)
    except BaseException:  # noqa: BLE001 - a failed build must not kill the worker
        err.write(traceback.format_exc())
        return 1
    finally:
        sys.argv = previous_argv
        _park()
        # Deterministic closure capture: the next job must see a clean first-party module
        # space or it records a different sourceClosureHash than a cold build would.
        _evict_first_party_modules()


def _invoke(request: dict) -> dict:
    """Run a cadgen module's main and return its payload — the CAD Viewer's contract."""
    module_name = str(request.get("module") or "")
    args = [str(a) for a in request.get("args") or []]
    repo_root = request.get("repo_root")
    try:
        if isinstance(repo_root, str) and os.path.isdir(repo_root):
            os.chdir(repo_root)
        module = importlib.import_module(module_name)
        # Its stdout is data to the caller, not something to stream.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(_FrameWriter("stderr")):
            code = module.main(args)
        return {"code": 0 if code is None else int(code), "stdout": buffer.getvalue()}
    except BaseException as exc:  # noqa: BLE001
        return {"code": 1, "stdout": "", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _park()
        _evict_first_party_modules()


def serve() -> int:
    os.environ["CADGEN_DAEMON_CHILD"] = "1"
    _emit({"ready": os.getpid()})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            _emit({"exit": 1, "error": "malformed request"})
            continue
        kind = request.get("kind")
        if kind == "ping":
            _emit({"pong": os.getpid()})
        elif kind == "invoke":
            _emit({"result": _invoke(request), "pid": os.getpid()})
        elif kind == "shutdown":
            return 0
        else:
            _emit({"exit": _run(request), "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
