"""Read side of the CAD Viewer instance registry, for ``cadgen viewer list``/``stop``.

The registry itself is WRITTEN by the viewer's JS server (viewer/server/registry.mjs):
each live instance drops a small JSON file in the system temp dir naming itself,
modelled on TensorBoard's ``.tensorboard-info`` / ``jupyter server list``. This module
only reads, probes, and reaps.

Liveness is an HTTP identity probe, never a signal: a registry entry counts as live
only when the recorded port answers ``/__cad/server`` with a matching pid — after a
hard kill the port is free for anything else to take, and stopping a stranger because
a stale file named its port would be the worst thing this command could do.
"""

from __future__ import annotations

import json
import os
import tempfile

REGISTRY_DIR_NAME = "cadgen-viewer-info"
_PROBE_TIMEOUT_S = 0.5


def registry_dir() -> str:
    return os.path.join(tempfile.gettempdir(), REGISTRY_DIR_NAME)


def entry_path(pid: int) -> str:
    return os.path.join(registry_dir(), f"viewer-{int(pid)}.json")


def unregister(pid: int) -> None:
    try:
        os.unlink(entry_path(int(pid)))
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
    """True when the recorded port answers /__cad/server AS the recorded pid."""
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
