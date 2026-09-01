"""The child that holds the CAD kernel. Nothing else in the server imports OCP.

WHY A CHILD AT ALL, when requirement 3 asks for a DIRECT call
--------------------------------------------------------------
The call IS direct: this process calls cadgen's compile entry point as a Python
function, installs a progress sink on it, and returns its payload dict. What
crosses the process boundary is structured frames, not scraped text — the thing
the old design could not do, because it ran ``cadgen step compile`` as an opaque
CLI child and reverse-scanned stdout for a line starting with ``{``.

What the separate process buys is CRASH ISOLATION. OCCT is C++: a fillet after a
boolean can segfault, and this repo has been bitten by exactly that class. A
segfault in the kernel takes down the process it runs in, and a viewer that dies
because one document is malformed is not a viewer. It also keeps ~280MB of
kernel RSS out of the long-lived server, and keeps cadgen's deliberate
module-eviction (it clears first-party modules between builds for closure
determinism) away from the server's own module space.

THE FRAME CHANNEL IS NOT STDOUT, AND THAT IS LOAD-BEARING
----------------------------------------------------------
OCCT's default messenger writes to FILE DESCRIPTOR 1 from C++, with ANSI colour,
bypassing ``sys.stdout`` entirely. Anything framed on stdout would be
interleaved with kernel chatter mid-build. (The Node backend survived this only
because it reverse-scanned for the LAST line starting with ``{`` — that scan was
the mitigation, not legacy cruft, and a progress frame emitted mid-build has no
such tolerance.)

So: frames go over a loopback socket this process connects back on, and fd 1 is
duplicated onto fd 2 at startup, which sends every byte OCCT prints into the
server's log stream where it belongs. Requests arrive on stdin. Diagnostics and
protocol can then never collide, and EOF on the frame socket stays an unambiguous
crash signal.

Run as: ``python compile_worker.py --frame-port N --token T``
"""

from __future__ import annotations

import json
import os
import socket
import sys
import traceback
import uuid

# The protocol frames, one JSON object per line on the frame socket:
#
#   {"id": <req>, "runId": "...", "progress": {...phase block...}}   zero or more
#   {"id": <req>, "result": {ok, document, package, skipped, contended}}   exactly
#   {"id": <req>, "error": "<message>", "errorType": "...", "traceback": "..."} one of
#
# An exception becomes a VALUE on this channel. No exit-code archaeology, no
# stderr truncation: the parent turns the error string straight into the wire's
# failure shape.
#
# `error` is the exception's BARE message, and the class name rides in the
# separate `errorType` field. The parent prefixes it — "STEP import failed:
# {error}" — and that string is what the viewer's import-failure card shows, so
# a class name spliced into it reads as "STEP import failed: RuntimeError:
# failed to read STEP file" to someone who has no idea what a RuntimeError is.
# cadgen already writes messages meant to be read by a person; a human string
# and a diagnostic label are two fields, never one.

# A peer holding the package's write lock makes our run answer `contended` after
# this long rather than queueing behind an arbitrarily long peer build. The
# client treats contended exactly like attaching to a peer's progress.
IMPORT_LOCK_TIMEOUT_SECONDS = 5.0

# --- the cadgen API contract -------------------------------------------------
#
# It lives HERE, in the one module that calls cadgen at all, so there is a single
# definition of what the Viewer needs from it. compile_client imports these names
# to answer the availability probe; importing this module costs the server
# nothing, because every cadgen import in it is inside a function body.
#
# WHAT WE NEED: ``build_step_artifact`` must take ``sink=``. Against a cadgen
# that does not, every import raises ``build_step_artifact() got an unexpected
# keyword argument 'sink'`` at the moment a user presses Import, after the probe
# has already promised ``stepImportAvailable: true``.
#
# THE CHECK IS THE SIGNATURE, NOT THE VERSION, and that choice is load-bearing.
# An editable install stamps its metadata version when it is installed, and this
# repo does not bump VERSION during development — so every contributor's cadgen
# reports the LAST RELEASE's number while its source is the working copy. A
# version floor would therefore refuse the one install that definitely has the
# feature, and CI (which installs requirements-dev.txt editable) would refuse it
# too. The version below is for the MESSAGE and for requirements.txt; it is
# never the gate.
BUILD_MODULE = "cadgen.step_artifact_cli"
BUILD_FUNCTION = "build_step_artifact"
SINK_PARAMETER = "sink"

#: The first RELEASE that carries the sink — 0.4.28 was the last one without it.
#: Named in `apps/viewer/requirements.txt` and in the upgrade hint, so a user
#: whose cadgen is genuinely too old is told a number they can act on.
MINIMUM_CADGEN_VERSION = "0.4.29"

# The document suffixes the import path accepts. cadgen's own CLI doors apply
# the same rule from ``cadgen._internal.doors``; this states it locally rather
# than importing a private module, because the server has ALREADY established
# both of that door's invariants before a request reaches this process:
#
#   * suffix + existence: ``CadgenOps._is_raw_step_file`` (owns_step_path +
#     os.path.exists) gates every call to ``client.compile``.
#   * not a stale GENERATED document: ``resolve_artifact_verdict``'s
#     ``generated`` flag gates the same call, and the viewer computes it with
#     its own sidecar reader, which needs no cadgen at all.
#
# So the private import bought a re-check of things already checked, at the
# price of a dependency on cadgen's internals that no release promises to keep.
# The local check below keeps the defence and drops the coupling.
DOCUMENT_SUFFIXES = (".step", ".stp")


def installed_cadgen_version() -> str | None:
    """The installed cadgen's version, or ``None`` when it has no metadata.

    Metadata only: this reads the distribution's ``.dist-info`` and does NOT
    import cadgen, which is what makes it safe to call from the server process.
    ``None`` means cadgen is importable but not installed — a source tree on
    ``PYTHONPATH``, which is how this repo's own test runners supply it.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cadgen")
    except PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a metadata read that fails tells us nothing
        return None


def cadgen_supports_progress_sink() -> bool | None:
    """Does the INSTALLED ``build_step_artifact`` take ``sink=``?

    ``True``/``False``, or ``None`` when it cannot be answered — and ``None`` is
    a real answer, not a failure: every unknown degrades to "assume usable", so
    the probe can never falsely refuse an import. A definite ``False`` is the
    only thing that turns the offer off, and ``_require_progress_sink`` in the
    worker re-asks the same question of the real object before every compile.

    Answered WITHOUT IMPORTING CADGEN, which is the whole difficulty: the server
    process must never pull a ~300MB kernel install into itself just to decide
    whether to show a button. So the module is located through the path finders
    (``PathFinder`` searches the directories a spec names; it executes nothing)
    and its source is read and parsed. ``inspect.signature`` would be simpler and
    is what the worker uses — the worker has already imported cadgen by then.
    """
    import ast
    import importlib.machinery
    import importlib.util

    try:
        package, _, module_name = BUILD_MODULE.rpartition(".")
        package_spec = importlib.util.find_spec(package)
        locations = list(getattr(package_spec, "submodule_search_locations", None) or [])
        if not locations:
            return None
        spec = importlib.machinery.PathFinder.find_spec(module_name, locations)
        origin = getattr(spec, "origin", None)
        if not origin or not str(origin).endswith(".py"):
            # A zipped or bytecode-only install has no source to read. Unknown,
            # so usable; the worker's runtime check is what covers it.
            return None
        with open(origin, "r", encoding="utf-8", errors="replace") as handle:
            tree = ast.parse(handle.read(), filename=str(origin))
    except Exception:  # noqa: BLE001 - any failure to look is an unknown answer
        return None

    definitions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, definitions) and node.name == BUILD_FUNCTION:
            arguments = node.args
            names = {
                argument.arg
                for argument in (*arguments.args, *arguments.kwonlyargs, *arguments.posonlyargs)
            }
            if arguments.kwarg is not None:
                return None  # **kwargs swallows everything; the signature says nothing
            return SINK_PARAMETER in names
    # The function is not where we expect it. That is not "too old" — it is a
    # cadgen this check does not understand, so it gets the benefit of the doubt.
    return None


def cadgen_too_old_message(found: str | None) -> str:
    """The one actionable sentence for an installed-but-too-old cadgen.

    Shaped like ``CADGEN_UNAVAILABLE`` in compile_client, because the client
    treats the two the same way: the import is refused, viewing is untouched,
    and the text says what to run.
    """
    have = f"has {found}" if found else "has an older one"
    return (
        f"importing a STEP file requires cadgen {MINIMUM_CADGEN_VERSION} or newer, and the "
        f"Python running this Viewer {have}. Upgrade it (pip install --upgrade "
        f"'cadgen>={MINIMUM_CADGEN_VERSION}'). Viewing existing models does not need cadgen."
    )


def _require_progress_sink(build) -> None:
    """Refuse a cadgen too old to narrate its own build.

    The server's probe normally answers this before a request is ever routed
    here, by reading the same signature off disk. This asks the REAL object, one
    step from the call, and it is the only check that survives everything the
    static one cannot see: a zipped install with no source, a module moved to a
    name this code does not know, a monkey-patched build function. Either way
    the user gets the actionable sentence rather than ``build_step_artifact()
    got an unexpected keyword argument 'sink'``.
    """
    import inspect

    try:
        parameters = inspect.signature(build).parameters
    except (TypeError, ValueError):  # pragma: no cover - an unintrospectable callable
        return
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return  # **kwargs may well accept it; let the call be the judge
    if SINK_PARAMETER not in parameters:
        raise RuntimeError(cadgen_too_old_message(installed_cadgen_version()))


class _FrameChannel:
    """Line-delimited JSON over the loopback socket back to the server."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def send(self, frame: dict) -> None:
        payload = json.dumps(frame, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
        self._sock.sendall(payload)


def _document(document_path: str):
    """The document this request names, or a ``ValueError``/``FileNotFoundError``.

    See ``DOCUMENT_SUFFIXES``: this is deliberately the viewer's own check
    rather than cadgen's private CLI door, because the server has already made
    both of that door's guarantees before spawning us.
    """
    from pathlib import Path

    path = Path(str(document_path)).expanduser()
    if path.suffix.lower() not in DOCUMENT_SUFFIXES:
        accepted = "/".join(DOCUMENT_SUFFIXES)
        raise ValueError(f"the STEP import takes a {accepted} document: {document_path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"document does not exist: {document_path}")
    return resolved


def _compile(document_path: str, *, force: bool, request_id, channel: _FrameChannel) -> dict:
    """Call cadgen's compile path directly, narrating it as it goes.

    cadgen is imported HERE, on first use, so a spawned-but-unused worker stays
    small and a viewer whose interpreter has no cadgen still starts.

    ``build_step_artifact`` rather than the public ``cadgen.step.compile`` verb,
    because that verb hardcodes ``repo_root=Path.cwd()``: os.chdir is
    process-global — unusable under a threading server — and cwd is the wrong
    base anyway, since ``repo_root`` both names the build's display refs and
    bounds the sibling-entry scan. It cannot take a base either: adding one
    would add a ``--base`` flag to ``cadgen step compile`` (its parser is
    MIRRORED from the signature), and a ``sink=`` parameter would disqualify the
    verb from mirror status altogether, since a callable is outside the
    derivable annotation set. ``build_step_artifact`` is the public,
    non-underscored entry point the verb itself calls.
    """
    from pathlib import Path

    from cadgen.step_artifact_cli import build_step_artifact

    _require_progress_sink(build_step_artifact)

    # One id for the whole run. The client's bar resets when runId changes,
    # because a ratio is only monotonic within a run — so this must be minted
    # once per request and never per event.
    run_id = uuid.uuid4().hex

    document = _document(document_path)

    def sink(event) -> None:
        channel.send({"id": request_id, "runId": run_id, "progress": event.progress_payload()})

    payload = build_step_artifact(
        # The document's OWN directory, matching what the Node child got from
        # cwd=dirname(candidate). For an imported STEP this reaches
        # _relative_to_base/_cad_ref_for_step, which produce the source_ref and
        # cad_ref display strings — the label the user watches during the build
        # and the ref the contended payload carries. Never the served root.
        repo_root=document.parent,
        step=document,
        source_path=None,
        force=force,
        lock_timeout_s=IMPORT_LOCK_TIMEOUT_SECONDS,
        sink=sink,
    )

    def path_of(key: str):
        value = payload.get(key)
        return str(Path(str(value)).resolve()) if value else None

    # The CompileResult shape the wire already carries.
    return {
        "ok": bool(payload.get("ok", True)),
        "document": path_of("stepPath"),
        "package": path_of("packagePath"),
        "skipped": bool(payload.get("skipped")),
        "contended": bool(payload.get("contended")),
    }


def _serve(channel: _FrameChannel) -> int:
    # An explicit readline loop rather than iterating the file: this process
    # must act on each request the instant it arrives, and a readline that
    # returns "" is unambiguously the parent closing stdin, which is how a
    # worker learns it has been retired.
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        request_id = request.get("id")
        if request.get("op") == "shutdown":
            return 0
        try:
            result = _compile(
                str(request.get("candidate") or ""),
                force=bool(request.get("force")),
                request_id=request_id,
                channel=channel,
            )
            channel.send({"id": request_id, "result": result})
        except BaseException as error:  # noqa: BLE001 - every failure is a frame
            # Including SystemExit/KeyboardInterrupt: a cancelled compile is a
            # failed compile, and the parent is owed an answer either way.
            # str(error) can be empty — `raise RuntimeError()`, or a bare
            # KeyboardInterrupt — and an empty error string would surface as
            # "STEP import failed: ". The class name is the fallback THEN, and
            # only then.
            message = str(error).strip() or type(error).__name__
            channel.send(
                {
                    "id": request_id,
                    "error": message,
                    "errorType": type(error).__name__,
                    "traceback": traceback.format_exc(),
                }
            )


def main(argv: list[str]) -> int:
    port = 0
    token = ""
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--frame-port" and index + 1 < len(argv):
            index += 1
            port = int(argv[index])
        elif argument == "--token" and index + 1 < len(argv):
            index += 1
            token = argv[index]
        index += 1
    if not port:
        print("compile_worker: --frame-port is required", file=sys.stderr)
        return 2

    sock = socket.create_connection(("127.0.0.1", port))
    channel = _FrameChannel(sock)
    channel.send({"hello": token, "pid": os.getpid()})

    # OCCT prints to fd 1 from C++, so fd 1 must not be a channel anyone parses.
    # Point it at stderr: kernel chatter becomes ordinary log output, and
    # nothing this process writes can corrupt the frame stream.
    try:
        os.dup2(sys.stderr.fileno(), 1)
    except (OSError, ValueError):
        pass

    try:
        return _serve(channel)
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
