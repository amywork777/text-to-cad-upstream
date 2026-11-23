"""Studio (studio-base): a model shown is never older than its script without the view saying so (Studio's
law 3, "the code is the model"). A script written outside the edit service -- an agent's edit, an
editor's save -- builds nothing by itself, so a page waiting on its model's next version
(``GET /api/v1/documents/<id>/version``) would wait on the old build for ever. Asked on that wait,
``refresh`` compares the script's bytes with the ones the engine's build read (its ``fingerprint``)
and, where they differ, has the edit service build the part again, once for those bytes: the wait
then answers with the build's progress (the page says it is updating) and its version, or its
failure (said over the last version that built). Only in Studio's own engine (``CAD_STUDIO_ENGINE``):
Jake's viewer builds when its agent runs the part."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

_lock = threading.Lock()
# The script bytes (their fingerprint) a build was last asked for, by document: one build a change.
_asked: dict[str, str] = {}


def _studio() -> bool:
    return os.environ.get("CAD_STUDIO_ENGINE") == "1"


def stale_script(model: dict | None) -> Path | None:
    """The script of a held model whose bytes are no longer those its build read; None where they are, or
    where the model names no script that can be read (a shape handed over, a file opened)."""
    from cad.engine.identity import fingerprint

    source = (model or {}).get("source") or {}
    script, built = source.get("script"), source.get("fingerprint")
    if not isinstance(script, str) or not isinstance(built, str) or not built:
        return None
    now = fingerprint(script)
    return Path(script) if now is not None and now != built else None


def refresh(ident: str, held: Callable[[str], tuple] | None = None, build: Callable[[Path], None] | None = None) -> bool:
    """Has the model ``ident``'s part built again where its script changed since its build; True where a build
    was asked for now. ``held`` (``model_catalog.held``) and ``build`` (the edit service's) are a test's to
    replace. Never raises: a page's wait is answered whatever happens here."""
    if not _studio():
        return False
    try:
        if held is None:
            from .model_catalog import held as held_model

            held = held_model
        model, _why, _state = held(ident)
        script = stale_script(model)
        if script is None:
            return False
        from cad.engine.identity import fingerprint

        now = fingerprint(script) or ""
        with _lock:
            if _asked.get(ident) == now:
                return False
            _asked[ident] = now
        (build or _build)(script)
        return True
    except Exception:  # a page's wait never fails for this
        return False


def _build(script: Path) -> None:
    from cad.edit.service import _relative, project_root, shared_service

    service = shared_service()
    root = project_root(script)
    service.rebuild(root, _relative(root, script))


def forget() -> None:
    """A test's: every build asked for forgotten."""
    with _lock:
        _asked.clear()
