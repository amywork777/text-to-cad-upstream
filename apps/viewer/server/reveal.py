"""Reveal a file in the OS file manager, for ``POST /__cad/reveal``.

Returns exactly one of ``{"ok": True}``, ``{"unsupported": True}`` (no known
file manager, or disabled by env) or ``{"ok": False, "error": ...}``.

``VIEWER_DISABLE_NATIVE_REVEAL=1`` forces unsupported, so a headless CI run
cannot pop a Finder window if something calls this by accident. Every test in
this repo sets it.

Every spawn passes an ARGUMENT VECTOR and never a shell string: the target is a
path from the served root, and a filename containing shell metacharacters must
be an ordinary filename rather than an injection.
"""

from __future__ import annotations

import os
import subprocess
import sys

__all__ = ["reveal_path", "TIMEOUT_SECONDS"]

TIMEOUT_SECONDS = 10.0


def _run(args: list[str]) -> dict:
    """One opener attempt, mapped onto the three-shape result.

    ``subprocess`` raises where Node's ``spawnSync`` sets ``result.error``, so
    both the missing-binary and the timeout cases have to be caught into the
    structured failure. A ``TimeoutExpired`` escaping here would surface as a
    500 where Node produced ``{ok: false, error}``.
    """
    try:
        result = subprocess.run(  # noqa: S603 - argument vector, never a shell
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as error:
        return {"ok": False, "error": f"could not run {args[0]}: {error}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{args[0]} timed out after {int(TIMEOUT_SECONDS)}s"}
    except OSError as error:
        return {"ok": False, "error": f"could not run {args[0]}: {error}"}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().split("\n")[0]
        return {"ok": False, "error": detail or f"{args[0]} exited {result.returncode}"}
    return {"ok": True}


def reveal_path(target) -> dict:
    if str(os.environ.get("VIEWER_DISABLE_NATIVE_REVEAL") or "").strip() == "1":
        return {"unsupported": True}
    resolved = os.path.abspath(str(target or ""))
    if not os.path.exists(resolved):
        return {"ok": False, "error": f"no such file: {resolved}"}

    if sys.platform == "darwin":
        return _run(["open", "-R", resolved])

    if sys.platform.startswith("win"):
        # explorer returns nonzero even on success, so its exit code says
        # nothing and the spawn itself is the only signal. Detached so a
        # long-lived file manager never holds the request thread.
        #
        # `/select,<path>` is ONE argv element. Windows argument quoting
        # differs between Node and Python's list2cmdline for backslash-before-
        # quote runs, so a path containing a space is the case to watch; the
        # command line this produces is pinned by a test rather than assumed.
        try:
            subprocess.Popen(  # noqa: S603 - argument vector, never a shell
                ["explorer", f"/select,{resolved}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except OSError as error:
            return {"ok": False, "error": f"could not run explorer: {error}"}
        return {"ok": True}

    # Linux/BSD: no portable "reveal and select", so open the containing folder.
    directory = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
    for opener in ("xdg-open", "gio", "nautilus"):
        args = [opener, "open", directory] if opener == "gio" else [opener, directory]
        result = _run(args)
        # A real failure from an opener that EXISTS is the answer; only
        # "could not run" means try the next one.
        if result.get("ok") or "could not run" not in str(result.get("error") or ""):
            return result
    return {"unsupported": True}
