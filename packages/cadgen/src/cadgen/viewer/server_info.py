"""Builds the /__cad/server payload (app id, dynamicRoot, serverFeatures, etc.)
that the CAD Viewer client consumes. The optional serverMode key is omitted when
empty.
"""

from __future__ import annotations

import os
import time

VIEWER_SERVER_APP_ID = "cad-viewer"
DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 3245


def normalize_viewer_port(value, fallback=DEFAULT_VIEWER_PORT) -> int:
    try:
        parsed = int(str(value if value is not None else ""))
    except (TypeError, ValueError):
        return fallback
    return parsed if 0 < parsed <= 65535 else fallback


def _resolve_view_root(root_path: str) -> dict:
    """The served directory, absolute. Empty means the process cwd.

    A viewer serves one root, fixed at startup, so this is a plain abspath. It used
    to run the value through a URL-path reader, because the directory arrived as a
    URL path and a Windows one looks like `/D:/models`. Requests no longer carry a
    directory, so there is no URL form left to decode."""
    resolved = os.path.abspath(str(root_path or "").strip() or os.getcwd())
    return {"rootPath": resolved, "rootName": os.path.basename(resolved)}


_STARTED_AT = time.time()


def _package_dir() -> str:
    """Directory of the running cadgen package, i.e. which checkout is answering."""
    try:
        import cadgen

        return os.path.dirname(os.path.abspath(cadgen.__file__ or ""))
    except Exception:  # noqa: BLE001 - identity metadata must never break a response
        return ""


def build_viewer_server_info(
    *,
    root_path: str = "",
    port: int = DEFAULT_VIEWER_PORT,
    pid: int | None = None,
    host: str = DEFAULT_VIEWER_HOST,
    backend: str = "local-fs",
    step_artifact_generation_available: bool = True,
    viewer_version: str = "",
    server_mode: str = "",
    server_features=None,
) -> dict:
    view_root = _resolve_view_root(root_path)
    normalized_port = normalize_viewer_port(port)
    normalized_mode = str(server_mode or "").strip()
    info = {
        "app": VIEWER_SERVER_APP_ID,
        "viewerVersion": str(viewer_version or ""),
    }
    if normalized_mode:
        info["serverMode"] = normalized_mode
    info["serverFeatures"] = [str(f or "").strip() for f in (server_features or []) if str(f or "").strip()]
    info["backend"] = backend
    info["rootPath"] = view_root["rootPath"]
    info["rootName"] = view_root["rootName"]
    info["port"] = normalized_port
    info["pid"] = pid if isinstance(pid, int) else os.getpid()
    info["stepArtifactGenerationAvailable"] = step_artifact_generation_available is not False
    # Identity, for the instance registry: `cadgen viewer list` probes this endpoint and
    # requires the pid above to match its entry, and reports which checkout's code that
    # pid is running -- the thing two viewers on two ports actually differ by. Additive
    # only; the SPA reads this payload.
    info["packageDir"] = _package_dir()
    info["startedAt"] = _STARTED_AT
    info["url"] = f"http://{host}:{normalized_port}"
    return info
