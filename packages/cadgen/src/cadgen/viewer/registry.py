"""A best-effort registry of running CAD Viewers, so instances can be found and stopped.

Modelled on TensorBoard's ``.tensorboard-info`` and ``jupyter server list``: each live
backend drops a small JSON file naming itself, and the CLI reads that directory. It lives
in the system temp dir rather than a repo or the home dir, for TensorBoard's reasons --
it is per-user on macOS, outside every checkout (so parallel worktrees share one view of
what is running), and entries orphaned by a hard kill die at reboot instead of
accumulating forever.

The field that earns this module its keep is ``packageDir``. One viewer serves any
directory by URL, so instances do not differ by what they serve -- they differ by WHICH
CHECKOUT'S CODE they run, and a viewer started from another clone answering on the port
you wanted is this project's recurring confusion. ``cadgen viewer list`` makes that
visible.

Liveness is an HTTP identity probe, never a signal: ``os.kill(pid, 0)`` is the usual
POSIX idiom but on Windows any non-special signal terminates the target, and a recycled
pid would make us trust a stranger. A registry entry counts as live only when the port
answers ``/__cad/server`` with a matching pid.

Deliberately NOT auto-reuse. TensorBoard reuses a "compatible" instance; the launcher
here does not, because source-blind reuse of whatever held the port was a real bug. The
registry exists to make a collision legible, not automatic.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

from cadgen._internal.atomic_replace import replace_atomic

REGISTRY_DIR_NAME = "cadgen-viewer-info"
_PROBE_TIMEOUT_S = 0.5


def registry_dir() -> str:
    return os.path.join(tempfile.gettempdir(), REGISTRY_DIR_NAME)


def _ensure_registry_dir() -> str | None:
    """Create the registry dir 0700, or return None if it cannot be trusted.

    On a shared /tmp another user could pre-create the directory, so an existing one is
    used only when we own it. Failing closed here just means no registry entry; it must
    never stop a viewer from starting.
    """
    path = registry_dir()
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        if hasattr(os, "getuid"):  # POSIX: refuse someone else's directory
            if os.stat(path).st_uid != os.getuid():
                return None
    except OSError:
        return None
    return path


def entry_path(pid: int) -> str:
    return os.path.join(registry_dir(), f"viewer-{int(pid)}.json")


def _package_dir() -> str:
    """Directory of the running cadgen package -- i.e. which checkout's code this is."""
    try:
        import cadgen

        return os.path.dirname(os.path.abspath(cadgen.__file__ or ""))
    except Exception:  # noqa: BLE001 - identity metadata must never break a start
        return ""


def cadgen_version() -> str:
    try:
        from cadgen import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return ""


def register(host: str, port: int, *, pid: int | None = None) -> str:
    """Record this process as a live viewer. Returns the file written, or "" on failure.

    Best-effort by contract: a viewer that cannot write its entry still serves.
    """
    directory = _ensure_registry_dir()
    if directory is None:
        return ""
    pid = int(pid if pid is not None else os.getpid())
    payload = {
        "pid": pid,
        "host": str(host),
        "port": int(port),
        "version": cadgen_version(),
        "packageDir": _package_dir(),
        # The URL a human should open. In dev that is vite's port, not the backend's,
        # so the spawning process passes it down rather than us guessing from host:port.
        "publicUrl": os.environ.get("CADGEN_VIEWER_PUBLIC_URL", ""),
        "startedAt": time.time(),
    }
    target = entry_path(pid)
    temporary = f"{target}.{pid}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        # Atomic so a reader never sees a partial entry, and through the shared helper
        # so it inherits the WinError 32 retry every other rename in cadgen has
        # (issue #241: an SMB redirector can still hold the handle we just closed).
        replace_atomic(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return ""
    return target


def unregister(pid: int | None = None) -> None:
    pid = int(pid if pid is not None else os.getpid())
    try:
        os.unlink(entry_path(pid))
    except OSError:
        pass


def _read_entry(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            entry = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
        return None
    if not isinstance(entry.get("port"), int):
        return None
    return entry


def probe(entry: dict, timeout_s: float = _PROBE_TIMEOUT_S) -> bool:
    """True when the recorded port answers /__cad/server AS the recorded pid.

    Checking the pid matters as much as the port: after a hard kill the port is free for
    anything else to take, and stopping a stranger because a stale file named its port
    would be the worst thing this module could do.
    """
    import urllib.error
    import urllib.request

    host = str(entry.get("host") or "127.0.0.1")
    url = f"http://{host}:{int(entry['port'])}/__cad/server"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("pid") == entry["pid"]


def live_entries(*, reap: bool = True) -> list[dict]:
    """Every entry whose identity probe succeeds, oldest first. Stale files are deleted."""
    directory = registry_dir()
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    live: list[dict] = []
    for name in names:
        if not (name.startswith("viewer-") and name.endswith(".json")):
            continue
        path = os.path.join(directory, name)
        entry = _read_entry(path)
        if entry is not None and probe(entry):
            live.append(entry)
        elif reap:
            try:
                os.unlink(path)
            except OSError:
                pass
    live.sort(key=lambda item: item.get("startedAt") or 0)
    return live


def find_by_port(port: int, *, entries: list[dict] | None = None) -> dict | None:
    for entry in entries if entries is not None else live_entries():
        if entry.get("port") == int(port):
            return entry
    return None
