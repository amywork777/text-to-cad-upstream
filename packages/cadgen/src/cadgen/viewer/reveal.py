"""Reveal a file in the OS file manager (subprocess), for POST /__cad/reveal.

Same shape as :mod:`cadgen.viewer.save_dialog`: the capability only exists as an OS
subprocess, so this module is the dispatch table and nothing else.

Returns exactly one of ``{"ok": True}``, ``{"unsupported": True}`` (no known file manager
for this platform, or disabled by env) or ``{"ok": False, "error": ...}``.

``VIEWER_DISABLE_NATIVE_REVEAL=1`` forces unsupported, so a headless CI run cannot pop a
Finder window if something calls this by accident.
"""

from __future__ import annotations

import os
import subprocess
import sys

# macOS and Windows can select the file inside its folder; Linux has no portable
# equivalent, so the containing directory is opened instead.
_TIMEOUT_S = 10


def _spawn(args: list[str]) -> dict:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"could not run {args[0]}: {exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"ok": False, "error": detail[0] if detail else f"{args[0]} exited {proc.returncode}"}
    return {"ok": True}


def reveal_path(path: str) -> dict:
    """Show `path` in the platform file manager, selecting it where that is possible."""
    if str(os.environ.get("VIEWER_DISABLE_NATIVE_REVEAL", "")).strip() == "1":
        return {"unsupported": True}
    target = os.path.abspath(str(path or ""))
    if not os.path.exists(target):
        return {"ok": False, "error": f"no such file: {target}"}

    if sys.platform == "darwin":
        return _spawn(["open", "-R", target])
    if os.name == "nt":
        # explorer returns nonzero even on success, so its exit code says nothing.
        try:
            subprocess.Popen(["explorer", f"/select,{target}"])
        except OSError as exc:
            return {"ok": False, "error": f"could not run explorer: {exc}"}
        return {"ok": True}
    # Linux/BSD: no portable "reveal and select", so open the containing folder.
    directory = target if os.path.isdir(target) else os.path.dirname(target)
    for opener in ("xdg-open", "gio", "nautilus"):
        args = [opener, "open", directory] if opener == "gio" else [opener, directory]
        result = _spawn(args)
        if result.get("ok") or "could not run" not in str(result.get("error", "")):
            return result
    return {"unsupported": True}
