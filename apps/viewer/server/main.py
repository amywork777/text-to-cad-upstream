#!/usr/bin/env python3
"""Single-port CAD Viewer server and instance manager.

Launching is UNCONDITIONAL, Jupyter-style: ``main.py --root <dir>`` always ends
with the URL of a live, correct Viewer for that directory. If an
identity-probed instance already serves ``realpath(root)`` at this viewer
version, its URL is printed with ``action:"reused"`` and nothing is spawned
(``--new`` skips the lookup); otherwise the server binds the first free port
from 3245 upward and prints ``action:"started"``. An EXPLICIT ``--port`` stays
strict — it exits 1 when taken — because then the port was the ask. The printed
URL (and the ``--json {url,port,action}`` line) is the contract; the port is an
output of launch, never something the caller reasons about.

Also the instance manager: ``main.py list [--json]`` shows every running Viewer
(identity-probed, stale entries reaped) and ``main.py stop --port <n>`` /
``--pid <n>`` terminates one. These live here rather than in a separate tool
because the registry the server writes is the only source of truth. Dev never
registers (``--no-registry``): the registry is bundled instances only.

Three flags exist for the dev server and nowhere else: ``--ephemeral`` (bind any
free port), ``--no-registry`` (stay out of reuse), and ``--api-only`` (serve the
two API prefixes and nothing else, because Vite owns the client — this is what
lets ``npm run dev`` work on a checkout that has never been built).

A Viewer serves ONE directory, given by ``--root`` and defaulting to the
invoking directory. The page is always the bare origin; ``?file=`` selects a
file inside that root. To serve a second directory, just launch again with that
root.

cadgen is NOT required to start: without it the viewer serves packaged models
read-only and importing a foreign STEP answers with an install hint.

Launch is::

    <the interpreter that installed requirements.txt> server/main.py --root <abs>

There is no interpreter discovery, and deliberately so: the previous backend
searched ``$CADGEN_PYTHON``, ``PATH``, and ``<servedRoot>/.venv/bin/python``,
which meant OPENING AN UNTRUSTED FOLDER THAT SHIPS A .venv handed it the
interpreter to execute. The server is now the interpreter. Do not reintroduce a
search in any form.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- interpreter floor ---------------------------------------------------
#
# Checked HERE, at import, before a single request can arrive. macOS still
# ships Python 3.9 as `python3` — which is also the default this app's dev
# server spawns — and on 3.9 the server BOOTS, prints the URL contract, and
# then answers the very first catalog request with a raw
# `realpath() got an unexpected keyword argument 'strict'`. A tool that starts
# and then fails on first contact is worse than one that refuses to start, so
# it refuses to start.
#
# The floor is 3.11, not the 3.10 today's code strictly needs (`strict=` landed
# in 3.10): 3.11 is what cadgen's own metadata requires and what the skill
# documents, and one number that is true everywhere beats three that drift.
# Everything in this block is deliberately 3.9-parseable, or the refusal would
# itself be a SyntaxError.
MINIMUM_PYTHON = (3, 11)


def unsupported_python_message(version_info=None, executable: str = "") -> str:
    """The refusal text for an interpreter below the floor; ``""`` when it is fine.

    Split from the check so it can be asserted on from a test run, which by
    construction runs on an interpreter that is ABOVE the floor.
    """
    version_info = sys.version_info if version_info is None else version_info
    if tuple(version_info)[:2] >= MINIMUM_PYTHON:
        return ""
    required = ".".join(str(part) for part in MINIMUM_PYTHON)
    running = ".".join(str(part) for part in tuple(version_info)[:3])
    newer = "python3.{}".format(MINIMUM_PYTHON[1])
    return (
        "CAD Viewer needs Python {required} or newer. This interpreter is {running}:\n"
        "    {executable}\n"
        "\n"
        "Run the server with a newer one:\n"
        "    {newer} server/main.py --root <absolute dir>\n"
        "For `npm run dev`, name it with VIEWER_PYTHON:\n"
        "    VIEWER_PYTHON={newer} npm run dev\n"
        "\n"
        "macOS ships {running_major} as `python3`; install a newer interpreter with\n"
        "Homebrew (`brew install python@3.13`), pyenv, or python.org.\n"
    ).format(
        required=required,
        running=running,
        executable=executable or sys.executable,
        newer=newer,
        running_major=".".join(str(part) for part in tuple(version_info)[:2]),
    )


_UNSUPPORTED_PYTHON = unsupported_python_message()
if _UNSUPPORTED_PYTHON:
    sys.stderr.write(_UNSUPPORTED_PYTHON)
    sys.stderr.flush()
    raise SystemExit(1)

# The one legal sys.path insert: this file's own directory's parent, so
# `server.*` imports resolve when main.py is run as a script. It is inside the
# skill root, which is what the self-containment rules permit. NEVER PYTHONPATH,
# never site.addsitedir, never a path outside this tree.
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from server import registry  # noqa: E402
from server.handler import CadHTTPServer, make_handler_class  # noqa: E402
from server.http_app import create_cad_app, read_viewer_version  # noqa: E402

DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 3245
# How far past the default the launcher will roll looking for a free port
# before giving up. Far beyond any plausible number of live Viewers.
PORT_ROLL_LIMIT = 100
STOP_WAIT_SECONDS = 3.0

VIEWER_ROOT = str(Path(__file__).resolve().parent.parent)

# EADDRINUSE/EACCES are the only "taken" signals. Windows raises WSAEADDRINUSE /
# WSAEACCES, which Python maps onto these same errnos.
_PORT_TAKEN_ERRNOS = frozenset({errno.EADDRINUSE, errno.EACCES})


def _out(text: str) -> None:
    """stdout, FLUSHED.

    Python block-buffers stdout when it is not a TTY, and the serve path never
    exits. Both the launcher test and the launch smoke test poll a LONG-LIVED
    process's redirected stdout for the ``{url,port,action}`` line, so an
    unflushed write is a hang, not a late line. The documented launch command
    carries neither ``-u`` nor ``PYTHONUNBUFFERED``, so this cannot be delegated
    to the environment.
    """
    sys.stdout.write(text)
    sys.stdout.flush()


def _err(text: str) -> None:
    sys.stderr.write(text)
    sys.stderr.flush()


def _compact_json(payload) -> str:
    # JSON.stringify emits no spaces. The launch smoke test greps for the
    # literal '"action":"reused"' and '"port":<n>', which Python's default
    # separators would break.
    return json.dumps(payload, separators=(",", ":"))


def parse_args(argv: list[str]) -> dict:
    """Hand-rolled, NOT argparse.

    Two incompatibilities make argparse the wrong tool: it errors on unknown
    arguments where this launcher tolerates them, and ``type=int`` exits 2 on
    ``--port abc`` where this falls back. Reproducing the fallbacks in argparse
    costs more than the loop.
    """
    args = {
        "host": DEFAULT_VIEWER_HOST,
        "port": DEFAULT_VIEWER_PORT,
        # Explicit --port means "this port or fail"; the default means "any free
        # port from the base" and enables the reuse lookup + roll.
        "port_explicit": False,
        "root": "",
        "dist": "",
        "json": False,
        "open": False,
        "fresh": False,
        # Additive flags, all three for dev (see vite.config.mjs).
        "ephemeral": False,
        "no_registry": False,
        "api_only": False,
    }
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--host":
            index += 1
            args["host"] = (argv[index] if index < len(argv) else "") or args["host"]
        elif arg == "--port":
            index += 1
            raw = argv[index] if index < len(argv) else ""
            # `Number(x) || default`: 0, NaN and a missing value are all falsy
            # and keep the default WHILE STILL SETTING port_explicit — so
            # `--port 0` means strict 3245, not an ephemeral port. That is what
            # --ephemeral is for.
            try:
                parsed = int(str(raw), 10)
            except (TypeError, ValueError):
                parsed = 0
            args["port"] = parsed or args["port"]
            args["port_explicit"] = True
        elif arg == "--root":
            index += 1
            args["root"] = (argv[index] if index < len(argv) else "") or ""
        elif arg == "--dist":
            index += 1
            args["dist"] = (argv[index] if index < len(argv) else "") or ""
        elif arg == "--json":
            args["json"] = True
        elif arg == "--open":
            args["open"] = True
        elif arg == "--new":
            args["fresh"] = True
        elif arg == "--ephemeral":
            args["ephemeral"] = True
        elif arg == "--no-registry":
            args["no_registry"] = True
        elif arg == "--api-only":
            args["api_only"] = True
        # Unknown args tolerated, matching the old launcher.
        index += 1
    if not (0 < args["port"] <= 65535):
        args["port"] = DEFAULT_VIEWER_PORT
        args["port_explicit"] = False
    return args


def _path_inside(candidate: str, container: str) -> bool:
    relative = os.path.relpath(candidate, container)
    return relative == "" or (
        relative != ".." and not relative.startswith(f"..{os.sep}") and not os.path.isabs(relative)
    )


def resolve_directory_root(*, root: str = "", env=None, cwd: str | None = None) -> str:
    """The directory this Viewer serves.

    ``--root``, else where the USER invoked it, rejecting anything inside the
    viewer app itself so a launch from the source tree never serves the source
    tree. ``INIT_CWD`` is npm's "where npm was invoked" and is still read: an
    agent may invoke through an npm-shaped wrapper, and dropping it would
    silently change what a bare launch serves.

    The refusal is a footgun guard, not a boundary: an explicit ``--root``
    naming the viewer app is accepted without complaint.
    """
    env = os.environ if env is None else env
    cwd = os.getcwd() if cwd is None else cwd
    if root:
        return os.path.abspath(os.path.join(cwd, root))
    for candidate in (env.get("INIT_CWD"), cwd):
        if not candidate:
            continue
        resolved = os.path.abspath(candidate)
        if resolved != VIEWER_ROOT and not _path_inside(resolved, VIEWER_ROOT):
            return resolved
    return os.path.abspath(cwd)


def resolve_dist_dir(explicit: str) -> str:
    candidates = [c for c in (str(explicit or "").strip(), os.path.join(VIEWER_ROOT, "dist")) if c]
    for candidate in candidates:
        resolved = os.path.abspath(candidate)
        if os.path.exists(os.path.join(resolved, "index.html")):
            return resolved
    return ""


def port_is_free(host: str, port: int) -> bool:
    """True when this process can BIND host:port.

    The same operation the server is about to perform, so the probe cannot
    disagree with reality. This used to probe by CONNECTING, with only
    ECONNREFUSED counting as free; on Windows a connect to a closed port
    routinely fails some other way (Hyper-V/WSL port exclusions, loopback
    filtering, refusals arriving as timeouts), so free ports read as occupied.
    A definite EADDRINUSE (or EACCES, Windows's answer for its excluded ranges)
    keeps the friendly rerun-without---port message; any OTHER failure counts as
    free, because this probe exists only for that message — the server's own
    bind stays authoritative.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if not sys.platform.startswith("win"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
        probe.listen(1)
        return True
    except OSError as error:
        return error.errno not in _PORT_TAKEN_ERRNOS
    finally:
        probe.close()


def _open_when_ready(url: str, host: str, port: int, timeout_seconds: float = 2.0) -> None:
    probe = f"http://{host}:{port}/__cad/server"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with urllib.request.urlopen(probe, timeout=0.25) as response:  # noqa: S310 - loopback only
                if 200 <= response.status < 300:
                    break
        except (urllib.error.URLError, OSError, TimeoutError):
            pass  # keep polling
        if time.monotonic() >= deadline:
            _err(f"Viewer did not answer within {int(timeout_seconds)}s; not opening a browser.\n")
            return
        time.sleep(0.1)
    try:
        if sys.platform == "darwin":
            command = ["open", url]
        elif sys.platform.startswith("win"):
            # `start` is a cmd builtin, not an executable. The empty string is
            # the window title, which start would otherwise take from the URL.
            command = ["cmd", "/c", "start", "", url]
        else:
            command = ["xdg-open", url]
        subprocess.Popen(  # noqa: S603 - argument vector, never a shell
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=not sys.platform.startswith("win"),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) if sys.platform.startswith("win") else 0,
        )
    except OSError as error:
        _err(f"Could not open a browser: {error}\n")


def _realpath_or(candidate) -> str:
    try:
        return os.path.realpath(str(candidate or ""), strict=True)
    except OSError:
        return str(candidate or "")


def find_reusable(directory: str, viewer_version: str) -> dict | None:
    """The reuse key: realpath(root) x viewer version, over identity-probed entries.

    Never port, never pid — keying on the port was the old source-blind reuse
    bug, and pid-liveness is the probe's job. Dev instances never register, so
    nothing here can hand back a Vite proxy target.
    """
    root_real = _realpath_or(directory)
    for entry in registry.live_entries():  # probes pids, reaps stale files
        if _realpath_or(entry.get("root")) == root_real and str(entry.get("version") or "") == str(
            viewer_version or ""
        ):
            return entry
    return None


# --- list / stop ---------------------------------------------------------


def _format_age(started_at) -> str:
    if not started_at:
        return ""
    seconds = max(0, int(time.time() - started_at))
    if seconds >= 3600:
        return f"  up {seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"  up {seconds // 60}m"


def _format_entry(entry: dict) -> str:
    url = f"http://{entry.get('host') or '127.0.0.1'}:{entry.get('port')}/"
    return (
        f"  port {entry.get('port')}  pid {entry.get('pid')}  "
        f"viewer {entry.get('version') or '?'}{_format_age(entry.get('startedAt'))}\n"
        f"    {url}\n"
        f"    serving  {entry.get('root') or '?'}\n"
        f"    code     {entry.get('packageDir') or '?'}"
    )


def list_command(argv: list[str]) -> int:
    """What CAD Viewers are running, and whose code answers each port.

    A viewer serves one directory fixed at startup, so instances differ both by
    what they serve and by WHICH CHECKOUT'S CODE holds the port.
    """
    as_json = "--json" in argv
    entries = registry.live_entries()  # also reaps anything that fails its identity probe
    if as_json:
        _out(f"{_compact_json(entries)}\n")
        return 0
    if not entries:
        _out("No CAD Viewer is running.\n")
        return 0
    _out(f"{len(entries)} CAD Viewer{'' if len(entries) == 1 else 's'} running:\n")
    for entry in entries:
        _out(f"{_format_entry(entry)}\n")
    return 0


def stop_command(argv: list[str]) -> int:
    """Terminate a running CAD Viewer.

    Only ever signals a process the registry can still identify: ``live_entries``
    probes each recorded port and requires the answering pid to match.
    """
    port = None
    pid = None
    index = 0
    while index < len(argv):
        if argv[index] == "--port":
            index += 1
            try:
                port = int(argv[index]) if index < len(argv) else None
            except (TypeError, ValueError):
                port = None
        elif argv[index] == "--pid":
            index += 1
            try:
                pid = int(argv[index]) if index < len(argv) else None
            except (TypeError, ValueError):
                pid = None
        index += 1
    if not port and not pid:
        _err("Specify which viewer to stop: --port <n> or --pid <n>.\n")
        return 2
    entries = registry.live_entries()
    described = f"port {port}" if port else f"pid {pid}"
    target = None
    for entry in entries:
        if (entry.get("port") == int(port)) if port else (entry.get("pid") == int(pid)):
            target = entry
            break
    if not target:
        _err(f"No running CAD Viewer for {described}.\n")
        return 1
    try:
        os.kill(int(target["pid"]), signal.SIGTERM)
    except OSError as error:
        _err(f"Could not stop pid {target['pid']}: {error}\n")
        return 1
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not registry.probe(target, 0.25):
            # Unregister from the CALLER side. On Windows os.kill(SIGTERM) maps
            # to TerminateProcess: no signal handler runs and no atexit fires,
            # so this is the only thing that removes the entry.
            registry.unregister(target["pid"])
            _out(f"Stopped CAD Viewer on port {target['port']} (pid {target['pid']}).\n")
            return 0
        time.sleep(0.1)
    _err(f"CAD Viewer pid {target['pid']} did not exit within {int(STOP_WAIT_SECONDS)}s.\n")
    return 1


# --- serve ---------------------------------------------------------------


class _LateApp:
    """Stand-in so the socket can be bound before the app knows its port.

    ``serverInfo`` must name the port actually taken, which is only known after
    the bind — so the bind comes first and the real app is attached the instant
    it succeeds, before ``serve_forever`` accepts anything. Nothing can reach
    this; answering 503 rather than raising keeps a freak race diagnosable
    instead of turning it into a stack trace.
    """

    def handle(self, request, response) -> None:  # noqa: ARG002
        response.send_json(503, {"ok": False, "error": "server starting"})


def _bind(host: str, port: int, args: dict) -> CadHTTPServer:
    """Bind, rolling by BINDING rather than pre-probing.

    The bind is the only check that cannot disagree with reality, and a lost
    race just moves to the next candidate. Explicit ``--port`` gets a single
    attempt; ``--ephemeral`` binds port 0 and reports what the OS gave.
    """
    placeholder = _LateApp()
    if args["ephemeral"]:
        return CadHTTPServer((host, 0), make_handler_class(placeholder), placeholder)
    last_candidate = port if args["port_explicit"] else port + PORT_ROLL_LIMIT
    while True:
        try:
            return CadHTTPServer((host, port), make_handler_class(placeholder), placeholder)
        except OSError as error:
            taken = error.errno in _PORT_TAKEN_ERRNOS
            if not taken or args["port_explicit"] or port >= last_candidate:
                raise
            port += 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Only argv[0] is inspected, so `main.py --json list` is a SERVE
    # invocation with an unknown arg, not a list.
    if argv and argv[0] == "list":
        return list_command(argv[1:])
    if argv and argv[0] == "stop":
        return stop_command(argv[1:])

    args = parse_args(argv)
    directory = resolve_directory_root(root=args["root"])
    if not os.path.isdir(directory):
        # Booting a viewer whose root does not exist would answer every request
        # with a 404 that looks like a missing model rather than a missing root.
        _err(f"CAD Viewer root is not a directory: {directory}\n")
        return 1

    # Reuse before spawn: a live, identity-probed instance already serving this
    # realpath(root) at this viewer version IS the requested viewer. Explicit
    # --port opts out (you asked for a port, not a viewer), --new forces fresh.
    # Ephemeral dev backends never reuse and never register.
    if not args["fresh"] and not args["port_explicit"] and not args["ephemeral"]:
        held = find_reusable(directory, read_viewer_version())
        if held:
            url = f"http://{held.get('host') or DEFAULT_VIEWER_HOST}:{held['port']}/"
            _out(f"Reusing CAD Viewer at {url} (serving {held.get('root')}, pid {held['pid']})\n")
            _out(f"CAD Viewer URL: {url}\n")
            if args["json"]:
                _out(f"{_compact_json({'url': url, 'port': held['port'], 'action': 'reused'})}\n")
            if args["open"]:
                # Awaited here: this process exits immediately afterwards.
                _open_when_ready(url, held.get("host") or DEFAULT_VIEWER_HOST, held["port"])
            return 0

    # Checked AFTER the reuse lookup, so a reuse succeeds with no --dist.
    #
    # --api-only exempts the check because in dev the CLIENT COMES FROM VITE:
    # this process serves only /__cad and /__tess_cache, and requiring a built
    # dist/ made `npm run dev` fail on any checkout that had not run
    # `npm run build` first — dist/ is gitignored, so that is every fresh
    # clone. The dist routes still answer 404 in that mode, which is what they
    # already do for an empty dist_dir.
    dist_dir = "" if args["api_only"] else resolve_dist_dir(args["dist"])
    if not dist_dir and not args["api_only"]:
        _err(
            "No built CAD Viewer client found. Build one with `npm run build` "
            "in the CAD Viewer app directory, or point --dist at a dist directory. "
            "(--api-only serves the API alone, for a dev server that supplies its own client.)\n"
        )
        return 1

    host = args["host"]
    port = args["port"]
    if args["port_explicit"]:
        # An explicit port is a demand, not a preference: refuse when taken, and
        # say who has it so the collision is diagnosable.
        if not port_is_free(host, port):
            holder = registry.find_by_port(port)
            if holder:
                _err(
                    f"Port {port} on {host} is already serving a CAD Viewer: "
                    f"pid {holder.get('pid')}, viewer {holder.get('version') or '?'}, "
                    f"from {holder.get('packageDir') or '?'}.\n"
                    f"Stop it with `{sys.executable} {os.path.abspath(__file__)} stop --port {port}`, "
                    f"or rerun without --port to take any free port.\n"
                )
            else:
                _err(f"Port {port} on {host} is already in use. Rerun without --port to take any free port.\n")
            return 1

    try:
        server = _bind(host, port, args)
    except OSError as error:
        _err(f"{error}\n")
        return 1
    port = server.server_address[1]

    # Attach the real app in the same breath as the successful bind: the socket
    # is listening but serve_forever has not accepted anything, so no request
    # can be dropped in the gap, and serverInfo names the port actually taken.
    app = create_cad_app(root=directory, host=host, port=port, dist_dir=dist_dir)
    server.app = app
    server.RequestHandlerClass = make_handler_class(app)

    url = f"http://{host}:{port}/"
    started = "Starting CAD Viewer API" if args["api_only"] else "Starting CAD Viewer"
    _out(f"{started} at {url} (serving {directory})\n")
    _out(f"CAD Viewer URL: {url}\n")
    if args["json"]:
        _out(f"{_compact_json({'url': url, 'port': port, 'action': 'started'})}\n")

    # Announce this instance so `main.py list` can find it — after the bind, so
    # we never advertise a port we failed to take. Dev skips it: a registered
    # dev backend would be REUSED by a later real launch on the same root,
    # handing an agent a URL served by Vite's proxy target.
    if not args["no_registry"]:
        registry.register(
            host=host, port=port, root=directory, viewer_version=app.server_info()["viewerVersion"]
        )

        import atexit  # noqa: PLC0415

        atexit.register(registry.unregister)

    def shutdown(_signum=None, _frame=None):
        if not args["no_registry"]:
            registry.unregister()
        # shutdown() blocks until serve_forever returns, and calling it from a
        # signal handler running ON the serving thread deadlocks. Dispatch it.
        threading.Thread(target=server.shutdown, daemon=True).start()
        # Hard-exit fallback: `stop` gives the process 3s, and an in-flight
        # stream must not outlive that.
        timer = threading.Timer(0.5, os._exit, (0,))
        timer.daemon = True
        timer.start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if args["open"]:
        threading.Thread(target=_open_when_ready, args=(url, host, port), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if not args["no_registry"]:
            registry.unregister()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
