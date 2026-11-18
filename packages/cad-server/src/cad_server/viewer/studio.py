"""Studio's own part of the viewer server (studio-base, not Jake's text-to-cad): its routes under
``/api/v1/local`` -- a project's models, edit mode, a part's versions, Sizes -- and the shapes of
CAD mode that are no model of the person's.

Jake's files call into this module from one place each: ``http_app.CadApp._local`` hands it every
``/api/v1/local`` route it does not answer itself (``local``), and ``recents.RecentStore`` asks it
which records Recents leaves out (``is_bar``)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The name CAD mode's rollback bar hands its body to the engine by (``cad.edit.tracer._bar_name``),
# a shape that is no model of the person's, so Recents leaves it out (``is_bar``).
_BAR = re.compile(r" at the rollback bar [0-9a-f]{8}\Z")


def is_bar(record: dict) -> bool:
    """Whether a registry record is the body of CAD mode's rollback bar."""
    return record.get("kind") == "shape" and bool(_BAR.search(str(record.get("name") or "")))


def local(app, request, response, rest) -> bool:
    """Answers ``/api/v1/local/<rest>`` when it is one of Studio's routes, and says whether it was:
    ``GET models``, ``POST edit/{state,change,face}``, ``POST versions[/compare|/restore]`` and
    ``POST sizes[/set|/add]``. ``app`` is the ``http_app.CadApp`` the request came to."""
    from .http_app import send_json

    route = rest[0] if rest else ""
    if rest == ["models"]:
        app._methods(request, {"GET": lambda: send_json(response, 200, _models(app, request.query))})
    elif route == "edit" and rest[1:] in (["state"], ["change"], ["face"]):
        app._methods(request, {"POST": lambda: _handle_edit(request, response, rest[1])})
    elif route == "versions" and rest[1:] in ([], ["compare"], ["restore"]):
        app._methods(request, {"POST": lambda: _handle_versions(request, response, rest[1:])})
    elif route == "sizes" and rest[1:] in ([], ["set"], ["add"]):
        app._methods(request, {"POST": lambda: _handle_sizes(request, response, rest[1:])})
    else:
        return False
    return True


def _models(app, query) -> dict:
    """``GET /api/v1/local/models?root=A&root=B``: project folders' models, every folder asked in
    one read of the registry (``folder_models.py``)."""
    from .folder_models import folders_models
    from .http_app import ApiError

    roots = [value for name, value in query if name == "root"]
    try:
        answer = folders_models(app.recents.registry, roots)
    except ValueError as error:
        raise ApiError(400, str(error), "name each project folder as ?root=<its absolute path>") from error
    if len(roots) == 1:
        answer["models"] = answer["roots"][roots[0]]
    return answer


def _payload(request, what: str) -> dict:
    """A Studio request's JSON object, its body at most 64 KiB (a command names its faces and edges
    with the geometry the viewer read of each)."""
    from .http_app import CadApp

    CadApp._limit(request, 65536)
    payload = json.loads(request.body() or b"{}")
    if type(payload) is not dict:
        raise ValueError(f"a {what} request is an object")
    return payload


def _service():
    """The edit service, its processes run in the CAD kernel's environment (``base.ensure``), which
    this server's own process may not be."""
    from cad.edit.service import kernel_python, shared_service, use_kernel
    from cad_server._internal import base

    if kernel_python() == sys.executable:
        env = base.ensure(told=lambda line: None, engine=True)
        if env is not None and not env.own:
            use_kernel(env.python)
    return shared_service()


def _answer(response, work) -> None:
    """``work()``'s answer, or its failure answered as ``{ok: false, error}``: nothing about Studio's
    routes is reported as a crash or goes into analytics. The API's own errors stay errors."""
    from .http_app import ApiError, send_json

    try:
        result = work()
    except ApiError:
        raise
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "error": str(error) or type(error).__name__}
    send_json(response, 200, result)


def _handle_edit(request, response, action) -> None:
    """``POST /api/v1/local/edit/{state,change,face}``: edit mode (``cad/edit``) -- the part script
    read as a design, one number of it changed, the feature that made a face. The work is the edit
    service's processes, never this one's."""

    def work():
        payload = _payload(request, "an edit")
        service = _service()
        if action == "state" and payload.get("probe"):
            # Whether the file has a part script to edit, answered without running it.
            return service.editable(str(payload.get("file") or ""))
        if action == "state":
            return service.state(str(payload.get("file") or ""), payload.get("files"), payload.get("bar"))
        if action == "face":
            # The feature that made a face the viewer picked: from the engine's ``made_by``, or the trace's map.
            return service.face_feature(payload)
        return service.change(payload)

    _answer(response, work)


def _handle_versions(request, response, rest) -> None:
    """``POST /api/v1/local/versions[/compare|/restore]``: a part's versions (``cad/edit/versions.py``)
    -- the versions of one file in the project's checkpoints, what changed between two of them, and
    going back to one (what is on disk kept as a version first)."""

    def work():
        payload = _payload(request, "a versions")
        from cad.edit import versions

        _service()  # names the kernel's Python a comparison runs in
        folder, path = str(payload.get("folder") or ""), str(payload.get("path") or "")
        if rest == ["compare"]:
            return versions.compare(
                folder,
                path,
                str(payload.get("older") or ""),
                str(payload.get("newer") or ""),
                payload.get("texts") if type(payload.get("texts")) is list else None,
                model=str(payload.get("model") or "") or None,
                retry=payload.get("retry") is True,
            )
        if rest == ["restore"]:
            return versions.restore(folder, path, str(payload.get("version") or ""))
        return versions.versions(folder, path)

    _answer(response, work)


def _handle_sizes(request, response, rest) -> None:
    """``POST /api/v1/local/sizes[/set|/add]``: Studio's Sizes (``cad/edit/sizes.py``) -- every named
    size in a project's scripts, read without running them; one changed where it is written, the
    parts that use its file then built again in the edit service's processes; a shared one added."""

    def work():
        payload = _payload(request, "a sizes")
        from cad.edit import sizes

        folder = str(payload.get("folder") or "")
        if rest == ["set"]:
            result = sizes.set_size(
                folder,
                str(payload.get("file") or ""),
                str(payload.get("name") or ""),
                int(payload.get("line") or 0),
                str(payload.get("old") or ""),
                str(payload.get("text") or ""),
            )
            return {**result, "building": _service().rebuild(Path(result["root"]), result["file"])}
        if rest == ["add"]:
            return sizes.add_shared(
                folder, str(payload.get("name") or ""), str(payload.get("text") or ""), str(payload.get("note") or "")
            )
        return sizes.sizes(folder)

    _answer(response, work)
