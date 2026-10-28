"""Hand edits to a part's script, for the viewer's edit mode.

The part script stays the source. A part is a model of cadgen's engine: a function marked ``@model``
(or with the file decorators, ``@xbf``, ``@step``...) in a script, whose document the engine holds by
its id (``cadgen.engine.ids.model_id`` of the script and the function); the script is its feature
tree. Edit mode reads it as a design: a warm tracer process (``tracer.py``, in this Python) runs the
script with every number in the project's files remembering where it is written and each build123d
operation recorded, and answers with the part's history, its named sizes and its dimensions. A change
rewrites one number in the source; then every part script that uses the changed file is built again
through the engine, as the agent's run builds it, so its document, and the viewer showing it, follow.

The CAD kernel never loads into the server: the tracer and the builds are processes of their own
(``test_module_boundaries``). This module only starts them and passes JSON, and notes the lines each
hand edit writes, for who made each feature (``authors.py``: git and a small record, no kernel). The
server is the engine's daemon, so those processes are its children: each is tracked by the process
it started, and ends with the service (``close``) or, left alone, when the daemon is gone.
"""

from __future__ import annotations

import ast
import atexit
import hashlib
import itertools
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from cadgen.edit import authors

__all__ = ["EditService", "dependents", "project_root", "script_for", "shared_service"]

# A cold trace imports build123d and runs the part once: seconds. A part that runs longer than this
# is stopped, and the next request starts a fresh tracer.
TRACE_TIMEOUT = 180
BUILD_TIMEOUT = 900
# Folders a project's own scripts never live in: left out of the scan for what uses a file, and of
# the scripts who made each feature is judged against (`authors.py`).
_SKIP = re.compile(r"^(\.|node_modules$|__pycache__$|tmp$|dist$|build$|vendor$|site-packages$)")
_SCAN_LIMIT = 4000
# A part script declares a model of the engine's: ``@model``, or any of its file decorators
# (``cadgen.engine.model``), bare or through the module (``@cadgen.model``).
_DECORATORS = ("model", "xbf", "step", "glb", "stl", "threemf", "dxf")
_PART = re.compile(rf"^\s*@(?:cadgen\.)?(?:{'|'.join(_DECORATORS)})\b", re.M)
_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
# What a change may name: a number (`literal`), a dimension on the model, or a feature's input, and
# the value typed; `leaf` answers which size to change when several make the value. A `command`
# writes a feature's line after the part's body (`commands.py`); a `splice` puts lines back or
# writes them again (a command's Undo and Redo). A `sketch` change is sketch mode's
# (`sketching.py`): its strokes are not built, as a CAD tool rebuilds when the sketch is left. A
# `remove` deletes a feature of the design tree (`deleting.py`), and `suppress` sets one aside. `bar`
# is where the rollback bar is (the part shown as it was above a feature; a change with nothing else
# only moves it), and `bar_after` where it goes once the change is made. A `preview` is a command
# made without writing it, for its panel to draw what OK would make; it changes nothing, so nothing
# is built.
_CHANGE_KEYS = ("literal", "dimension", "input", "leaf", "text", "files", "command", "preview", "mass", "draft_check", "interference", "parameter", "rename", "appearance", "mate", "compare", "splice", "sizes", "preview_sizes", "set_material",
                "sketch", "remove",
                "suppress", "reorder", "bar", "bar_after")
# Changes that write none of the engineer's own lines (`authors.py`): Undo puts lines back as they
# were, whoever wrote them, and Redo writes again lines noted when first made (`splice`); Suppress
# sets a feature's lines aside as comments, and Unsuppress puts them back as they were.
_PUTS_BACK = ("splice", "suppress")


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def is_part(path: Path) -> bool:
    try:
        return bool(_PART.search(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def _decorated(node: ast.expr) -> tuple[str | None, str | None]:
    """A decorator as the engine reads it: its kind (``model``, ``step``...) and its ``name=``."""
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call is not None else node
    kind = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else None
    named = next((keyword.value.value for keyword in (call.keywords if call is not None else ())
                  if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)), None)
    return (kind if kind in _DECORATORS else None), named


def model_of(text: str) -> tuple[str, str | None] | None:
    """The part's model as its script declares it, read without running it: the first function a
    decorator of the engine's marks, and the explicit ``name=`` it gives (None: the script's and the
    function's). None for a script that declares none."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            marks = [_decorated(each) for each in node.decorator_list]
            if any(kind for kind, _ in marks):
                return node.name, next((named for _, named in marks if named), None)
    return None


def document_of(script: Path) -> str | None:
    """The id of the document a part script's model makes, as the engine computes it
    (``cadgen.engine.ids.model_id``): what the viewer opens the part by. None for a script that
    declares no model."""
    from cadgen.engine.ids import model_id

    try:
        found = model_of(Path(script).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    if found is None:
        return None
    try:
        return model_id(script, found[0], found[1])
    except (TypeError, ValueError):
        return None


def _model_home(ident: str) -> Path | None:
    """The script a model's document is built from, as the engine's registry of documents records it
    (``cadgen.engine.registry``, in the caller's state folder; no kernel). None for an id it does
    not hold as a model's: a shape handed over, an opened file, or one never built."""
    from cadgen.engine import registry

    held = registry.current()
    record = held.get(ident) if held is not None else None
    if not record or record.get("kind") != "model":
        return None
    try:
        return registry.home(held, record)
    except (KeyError, TypeError, ValueError, OSError):
        return None


def script_for(file_ref: str) -> Path | None:
    """The part script a viewer file is built from: the script itself; a model's document by its id,
    the script the engine records it is built from; a file a part writes (a STEP, an xbf), the script
    of the same name beside it, or beside its ``XBF`` folder (``@xbf``'s default). None when there
    is none, or it declares no model."""
    if not file_ref:
        return None
    from cadgen.engine.ids import is_id

    text = str(file_ref).split("#", 1)[0].strip()
    if is_id(text):
        home = _model_home(text)
        return home.resolve() if home is not None and home.is_file() and is_part(home) else None
    path = Path(text).expanduser()
    if not path.is_absolute():
        return None
    suffix = path.suffix.lower()
    if suffix == ".py":
        candidates = [path]
    elif suffix in (".step", ".stp", ".xbf"):
        candidates = [path.with_suffix(".py")]
        if suffix == ".xbf" and path.parent.name == "XBF":
            candidates.append(path.parent.parent / f"{path.stem}.py")
    else:
        return None
    return next((each.resolve() for each in candidates if each.is_file() and is_part(each)), None)


def imported_step(file_ref: str) -> Path | None:
    """A STEP brought in rather than built: a ``.step`` or ``.stp`` file with no part script beside it."""
    if not file_ref:
        return None
    path = Path(str(file_ref).split("#", 1)[0]).expanduser()
    if path.suffix.lower() not in (".step", ".stp") or not path.is_absolute() or not path.is_file():
        return None
    return path.resolve() if script_for(str(path)) is None else None


def _adopted_names(source: Path):
    """The scripts a STEP brought in is made a part by, in the order they are taken: ``bracket_part.py``, then ``bracket_part2.py``..."""
    yield source.with_name(f"{source.stem}_part.py")
    for n in itertools.count(2):
        yield source.with_name(f"{source.stem}_part{n}.py")


def _studio_projects() -> list[tuple[Path, dict]]:
    """Studio's projects: each folder a project lists, with the project's record. Studio keeps the
    records apart from the folders, one ``<id>/project.json`` each under ``$STUDIO_PROJECTS_DIR``
    (else ``~/studio-projects``), so a copy or a folder added from elsewhere is a project's folder
    without a git repository of its own."""
    records = Path((os.environ.get("STUDIO_PROJECTS_DIR") or "").strip() or "~/studio-projects").expanduser()
    listed = []
    for path in sorted(records.glob("*/project.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            listed += [(Path(str(folder["path"])).expanduser().resolve(), record) for folder in record.get("folders") or ()]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return listed


def project_root(script: Path) -> Path:
    """The project a part belongs to: the nearest folder holding a git repository or Studio's
    ``project.json``, or that a Studio project lists, else the script's own folder."""
    listed = {folder for folder, _record in _studio_projects()}
    for folder in [script.parent, *script.parent.parents]:
        if (folder / ".git").exists() or (folder / "project.json").is_file() or folder in listed:
            return folder
    return script.parent


def _project_units(root: Path) -> dict:
    """The units and the material the brief of the Studio project listing ``root`` names, as a
    trace request's."""
    for folder, record in _studio_projects():
        brief = record.get("brief") if folder == root else None
        if not isinstance(brief, dict):
            continue
        named = {**({"units": brief["units"]} if brief.get("units") in ("in", "mm") else {}),
                 **({"material": brief["material"].strip()} if isinstance(brief.get("material"), str) and brief["material"].strip() else {})}
        if named:
            return named
    return {}


def _relative(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _drawn(file_ref: str, script: Path) -> Path:
    """What a part's drawing reads the part from: the STEP the viewer shows, where that is a file on
    disk (a part that writes one, or a drawing made before parts were models of the engine's), else
    the part's script, whose model a drawing calls (``drawings.template``)."""
    path = Path(str(file_ref or "").split("#", 1)[0]).expanduser()
    return path if path.is_absolute() and path.suffix.lower() in (".step", ".stp") and path.is_file() else script


def _drawing_of(root: Path, step: Path) -> dict | None:
    """A part's drawing, for the Drawing panel: its script, the PDF it writes (and whether that is
    there), and its sheet as the panel opens on it."""
    from cadgen.edit import drawings

    try:
        found = drawings.find(root, step)
        if found is None:
            return None
        sheet = drawings.read(found.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, drawings.DrawingError):
        return None
    out = sheet.pop("out", None)
    pdf = (found.parent / out).resolve() if out else None
    return {"script": _relative(root, found), "pdf": _relative(root, pdf) if pdf else "", "drawn": bool(pdf and pdf.exists()), **sheet}


def _python_files(root: Path) -> list[Path]:
    found: list[Path] = []
    folders = [root]
    while folders and len(found) < _SCAN_LIMIT:
        folder = folders.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            if _SKIP.match(entry.name):
                continue
            if entry.is_dir(follow_symlinks=False):
                folders.append(Path(entry.path))
            elif entry.name.endswith(".py"):
                found.append(Path(entry.path))
    return found


def dependents(root: Path, changed: str) -> list[Path]:
    """Every part script that uses ``changed`` (a file relative to ``root``), directly or through
    others, parts before the assemblies that import them."""
    root = root.resolve()
    uses: dict[Path, set[str]] = {}
    for path in _python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        uses[path] = {(match.group(1) or match.group(2)).split(".")[-1] for match in _IMPORT.finditer(source)}
    touched = {(root / changed).resolve()}
    grew = True
    while grew:
        grew = False
        for path, imported in uses.items():
            if path not in touched and any(each.stem in imported for each in touched):
                touched.add(path)
                grew = True
    parts = [path for path in touched if path in uses and is_part(path)]
    return sorted(parts, key=lambda path: ("assembl" in str(path).lower(), str(path)))


def _hash_inside(root: Path, rel: str) -> str | None:
    """A project file's hash as the tracer records it, for a file inside the project only."""
    try:
        path = (root / str(rel)).resolve()
        path.relative_to(root.resolve())
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except (OSError, ValueError):
        return None


def _line_inside(root: Path, rel, line) -> list[str]:
    """A project file's line as it reads now, for a file inside the project only: none for any other."""
    try:
        path = (root / str(rel)).resolve()
        path.relative_to(root.resolve())
        return [path.read_text(encoding="utf-8").splitlines()[int(line) - 1]] if int(line) >= 1 else []
    except (OSError, ValueError, IndexError, TypeError, UnicodeDecodeError):
        return []


def _files_key(files) -> tuple:
    """The files a part was read from, by their hashes (a reply's ``files``, a page's poll), as one key."""
    return tuple(sorted((str(rel), str(digest)) for rel, digest in files.items())) if isinstance(files, dict) else ()


def _judged(reply: dict) -> list[dict] | None:
    """What who made a reply's features is judged by (`authors.py`): each one's key, file and first
    line, an assembly's parts' too. None for a reply that does not read the part (a sketch solved on
    its own, a drawing's sheet)."""
    if not reply.get("ok") or "features" not in reply:
        return None
    features = reply["features"] or [feature for component in reply.get("components") or [] for feature in component.get("features") or []]
    return [{key: feature.get(key) for key in ("key", "file", "text", "suppressed")} for feature in features]


class _Tracer:
    """The warm tracer: one process, one request at a time."""

    def __init__(self, python: str) -> None:
        self.python = python
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._next = 0

    def _start(self) -> None:
        self._process = subprocess.Popen(
            [self.python, "-m", "cadgen.edit.tracer", "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **_no_window(),
        )
        self._lines = queue.Queue()
        threading.Thread(target=self._read, args=(self._process, self._lines), daemon=True).start()

    @staticmethod
    def _read(process: subprocess.Popen, lines: queue.Queue) -> None:
        with process.stdout:
            for line in process.stdout:
                lines.put(line)
        lines.put(None)

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            process.stdin.close()  # its stdout is the reader's, closed when it reads the end
        except OSError:
            pass

    def ask(self, request: dict, timeout: float = TRACE_TIMEOUT) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            self._next += 1
            ident = self._next
            try:
                self._process.stdin.write(json.dumps({**request, "id": ident}) + "\n")
                self._process.stdin.flush()
            except OSError:
                self.stop()
                return {"ok": False, "error": "The part could not be read. Try again."}
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    return {"ok": False, "error": "Reading the part took too long."}
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line is None:
                    self._process = None
                    return {"ok": False, "error": "Reading the part stopped. Try again."}
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue  # something the part printed past the tracer
                if isinstance(reply, dict) and reply.get("id") == ident:
                    reply.pop("id", None)
                    return reply


def alive(pid: int) -> bool:
    """Whether process ``pid`` still runs. On Windows by opening it (``os.kill`` there ends a process
    whatever the signal), elsewhere by signal 0."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: it has not ended
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def end_with_parent(exit_code: int = 0) -> None:
    """This process ended once the one that started it is gone, as it notices within a second: its
    parent changes (POSIX hands an orphan to another), or no longer runs (Windows keeps the number).
    A child the edit service starts (the tracer, a build) holds a kernel or an engine request for
    nothing once the engine's daemon that started it is gone."""
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent and alive(parent):
            time.sleep(1)
        os._exit(exit_code)

    threading.Thread(target=watch, daemon=True).start()


# A part built again, in a process of its own: its script's models built by the engine, as the
# agent's run builds them (``cadgen.engine.api.build_script``: every model it defines, each writing
# what its decorators declare), in the engine of this process's environment, which it never starts
# (``never_start_engine``): with none running, the build fails saying so. A script whose models are
# none of the engine's runs as it is. It ends with the process that started it: the engine's daemon,
# which the server is.
_BUILD = """
import sys
from cadgen.edit.service import end_with_parent, never_start_engine
end_with_parent(1)
never_start_engine()
script = sys.argv[1]
from cadgen.engine import api
try:
    report = api.build_script(script)
except Exception as error:
    print(str(error) or type(error).__name__, file=sys.stderr)
    raise SystemExit(1)
if not report.models:
    import runpy
    sys.argv = [script]
    runpy.run_path(script, run_name="__main__")
    raise SystemExit(0)
failed = [row for row in report.models if not row.get("ok")]
if failed:
    print(str(failed[0].get("error") or "the build failed").strip(), file=sys.stderr)
    raise SystemExit(1)
"""

NO_ENGINE = "the engine is not running"


def never_start_engine() -> None:
    """This process reaches the engine that runs, and never starts one (``client._start`` refused):
    the edit service's children ask the engine their server is part of, and with it gone, say so
    (``NO_ENGINE``) rather than leave an engine of their own behind."""
    from cadgen.engine import client

    def refused(*_args, **_kwargs):
        raise ConnectionError(NO_ENGINE)

    client._start = refused


class _Builds:
    """The parts built again after a change: one batch at a time, in order. Each build is a child
    process tracked by its handle, so closing the service ends the one running (``stop``). The
    status says each batch's scripts by name and their documents by id (``document_of``)."""

    def __init__(self, python: str) -> None:
        self.python = python
        self._lock = threading.Lock()
        self._batches: queue.Queue[tuple[int, list[Path]]] = queue.Queue()
        self._batch = 0
        self._running: subprocess.Popen | None = None
        self._stopped = False
        # Each script queued or building, by its path: how many builds of it are still to finish.
        self._waiting: dict[str, int] = {}
        self.status: dict = {"scripts": [], "documents": [], "done": 0, "error": None}
        threading.Thread(target=self._work, daemon=True).start()

    def start(self, scripts: list[Path]) -> None:
        with self._lock:
            self._batch += 1
            self.status = {"scripts": [path.name for path in scripts], "documents": [document_of(path) for path in scripts],
                           "done": 0, "error": None}
            for path in scripts:
                self._waiting[str(Path(path).resolve())] = self._waiting.get(str(Path(path).resolve()), 0) + 1
            self._batches.put((self._batch, list(scripts)))

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.status)

    def pending(self, script: Path) -> bool:
        """Whether a build of ``script`` is queued or running: its document is about to change."""
        with self._lock:
            return self._waiting.get(str(Path(script).resolve()), 0) > 0

    def stop(self) -> None:
        """No more builds, and the one running ended: by the process this service started."""
        with self._lock:
            self._stopped = True
            running, self._running = self._running, None
        _end(running)

    def _build(self, script: Path) -> str | None:
        """One part built again: None, or why it failed (the last lines it said)."""
        with self._lock:
            if self._stopped:
                return "the edit service stopped"
            try:
                process = subprocess.Popen(
                    [self.python, "-c", _BUILD, str(script)],
                    cwd=script.parent,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    **_no_window(),
                )
            except OSError as failure:
                return str(failure)
            self._running = process
        try:
            _out, said = process.communicate(timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            _end(process)
            return f"the build took longer than {BUILD_TIMEOUT} seconds"
        finally:
            with self._lock:
                if self._running is process:
                    self._running = None
        return None if process.returncode == 0 else _last_said(said) or "the build failed"

    def _work(self) -> None:
        while True:
            batch, scripts = self._batches.get()
            for script in scripts:
                error = self._build(script)
                with self._lock:
                    key = str(Path(script).resolve())
                    self._waiting[key] = self._waiting.get(key, 1) - 1
                    if self._waiting[key] <= 0:
                        del self._waiting[key]
                    if batch != self._batch:
                        continue  # a newer change's batch is the one shown; this one still finishes
                    if error:
                        self.status["error"] = f"{script.name}: {error}"
                    self.status["done"] += 1


def _last_said(said: str | None) -> str:
    """A failed build's last two lines, as one: its traceback's marker lines (only spaces, ``^`` and ``~``, under the
    code they point at) and blank ones left out, and each line's indent with them."""
    lines = [line.strip() for line in (said or "").splitlines() if line.strip(" \t^~")]
    return " ".join(lines[-2:])


def _end(process: subprocess.Popen | None) -> None:
    """A child this service started, ended and waited for (never one found by its name)."""
    if process is None:
        return
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


class EditService:
    """Edit mode for one viewer server: its tracer, and the builds its changes start."""

    def __init__(self, python: str | None = None, *, build: bool = True) -> None:
        self.python = python or sys.executable
        self._tracer = _Tracer(self.python)
        self._builds = _Builds(self.python) if build else None
        # Each part script's features as last read (`_judged`), with the files' hashes they were read
        # from, for a read that finds those files as they were to say who made them as it is now: a
        # turn's checkpoint made since, say. A page that read another version (the script put back
        # since) is not told by this one's keys.
        self._read: dict[str, tuple[tuple, list[dict]]] = {}

    def building(self) -> dict:
        return self._builds.snapshot() if self._builds else {"scripts": [], "documents": [], "done": 0, "error": None}

    def rebuild(self, root: Path, changed: str) -> dict:
        """Every part that uses ``changed`` (a file relative to ``root``) built again, as after a
        change here: for a size changed from Studio's Sizes (``sizes.py``)."""
        if self._builds is not None:
            self._builds.start(dependents(root, changed))
        return self.building()

    def editable(self, file_ref: str) -> dict:
        """Whether a viewer file has a part script beside it to edit: answered at once, so a view
        that cannot be edited never changes its layout for edit mode while the part is read. A STEP
        with none is one brought in (``importable``): it can be made a part to model on (``adopt``),
        and the part made of it before is named (``part``)."""
        script = script_for(file_ref)
        if script is not None:
            document = document_of(script)
            return {"ok": True, "editable": True, "document": document, **self._built(script, document)}
        source = imported_step(file_ref)
        if source is None:
            return {"ok": True, "editable": False}
        # The first part made of it, where there is one: the names are taken in order, so none taken means none made.
        first = next(_adopted_names(source))
        made = document_of(first) if first.is_file() else None
        if made is None:
            return {"ok": True, "editable": False, "importable": True}
        return {"ok": True, "editable": False, "importable": True, "part": made, **self._built(first, made)}

    def _built(self, script: Path, document: str | None) -> dict:
        """Whether a part's document can be opened yet. ``partBuilt``: whether the engine holds it (a
        build that failed, or is still running, leaves none to open: an id never built is not built by
        opening it); ``partBuilding``: whether a build of it is queued or running, so a page waits for
        it rather than saying it could not be made; ``partError``: why its last build failed, where the
        builds' last batch says so, so the page says it rather than building it again."""
        building = self._builds is not None and self._builds.pending(script)
        built = document is not None and _model_home(document) is not None and not building
        status = self.building()
        failed = status["error"] if not built and not building and script.name in status["scripts"] else None
        return {"partBuilt": built, "partBuilding": building, **({"partError": failed} if failed else {})}

    def adopt(self, file_ref: str) -> dict:
        """A STEP brought in made a part to model on, as SolidWorks makes a part of a STEP it opens:
        a script beside it (``<name>_part.py``) whose model reads it as one body with no history, so
        the file brought in is never written over; then built, so its document is the engine's.
        ``part``: that document's id, to open."""
        source = imported_step(file_ref)
        if source is None:
            return {"ok": False, "error": "Only a STEP with no part script can be made a part."}
        script = next(candidate for candidate in _adopted_names(source) if not candidate.exists())
        name = script.stem
        function = re.sub(r"\W", "_", name)
        function = function if function[:1].isalpha() or function[:1] == "_" else f"part_{function}"
        script.write_text(
            f'''"""{source.stem}, brought in from {source.name}: one body with no history, modeled on here."""

from pathlib import Path

from cadgen import model, read_step


@model
def {function}():
    source = Path(__file__).parent / {source.name!r}
    if not source.is_file():
        raise FileNotFoundError(f"the STEP this part reads is gone: {{source}}")
    part = read_step(source)
    return part
''', encoding="utf-8")
        if self._builds is not None:
            self._builds.start([script])
        return {"ok": True, "part": document_of(script), "script": str(script), "building": self.building()}

    def state(self, file_ref: str, files: dict | None = None, bar: dict | None = None) -> dict:
        """The part as a design: its history, named sizes and dimensions. ``files`` is the hashes a
        page read last; when none of them changed, the answer says so and the part is not run.
        ``bar``: where the page has the rollback bar, said again as the part now reads."""
        script = script_for(file_ref)
        if script is None:
            return {"ok": False, "reason": "no-script", "error": "This model has no part script beside it."}
        root = project_root(script)
        if isinstance(files, dict) and files and all(_hash_inside(root, rel) == digest for rel, digest in files.items()):
            # The part reads as it did, but who made its features may have moved on: a turn ended.
            kept = self._read.get(str(script))
            read = kept[1] if kept is not None and kept[0] == _files_key(files) else None
            return {"ok": True, "unchanged": True, "building": self.building(),
                    **({"authors": authors.feature_authors(root, read)} if read is not None else {})}
        reply = self._tracer.ask({"script": str(script), "root": str(root), "mesh": False, **_project_units(root),
                                  **({"bar": bar} if bar else {})})
        self._keep_read(script, reply)
        drawing = _drawing_of(root, _drawn(file_ref, script)) if reply.get("ok") else None
        return {**reply, "root": str(root), "building": self.building(), **({"drawing": drawing} if drawing else {})}

    def change(self, payload: dict) -> dict:
        """One number changed in the part's source, or a command's line written, then the parts
        that use the changed file built again. ``adopt``: a STEP brought in made a part (``adopt``).
        ``build``, alone: the part built as it is, changing nothing -- Studio's New part, whose script
        is written and then built before its document is opened (``editable`` says when it is)."""
        if isinstance(payload.get("adopt"), dict):
            return self.adopt(str(payload.get("file") or ""))
        script = script_for(payload.get("file") or "")
        if script is None:
            return {"ok": False, "error": "This model has no part script to change."}
        root = project_root(script)
        if payload.get("build") is True and not any(key in payload for key in _CHANGE_KEYS):
            return {"ok": True, "document": document_of(script), "root": str(root),
                    "building": self.rebuild(root, _relative(root, script))}
        if isinstance(payload.get("drawing"), dict):
            return {**self.drawing(root, script, _drawn(payload["file"], script), payload["drawing"]), "root": str(root), "building": self.building()}
        request = {key: payload[key] for key in _CHANGE_KEYS if key in payload}
        reply = self._tracer.ask({**request, "script": str(script), "root": str(root), "op": "edit", "mesh": False,
                                  **_project_units(root)})
        made = reply.get("change") if reply.get("ok") else None
        if isinstance(made, dict):
            self._note(root, request, made, reply)
        self._keep_read(script, reply)
        if isinstance(made, dict) and made.get("build", True) and self._builds is not None:
            self._builds.start(dependents(root, made["file"]))
        return {**reply, "root": str(root), "building": self.building()}

    def _keep_read(self, script: Path, reply: dict) -> None:
        read = _judged(reply)
        if read is not None:
            self._read[str(script)] = (_files_key(reply.get("files")), read)

    @staticmethod
    def _note(root: Path, request: dict, made: dict, reply: dict) -> None:
        """Who made it (`authors.py`): the lines a change made by hand wrote noted as the engineer's,
        from its Redo, and the reply's marks read again with them. A number typed on the model or in
        a row has no Redo of its own: its line as it now reads. A size changed in User Expressions
        (`literal`) is a named size's line, never a feature's, and Undo and Redo of a number send the
        same request, so it notes nothing."""
        if any(key in request for key in _PUTS_BACK):
            return
        redo = made.get("redo")
        if isinstance(redo, dict) and isinstance(redo.get("hunks"), list):
            rel, added = str(redo.get("file") or ""), authors.written(redo["hunks"])
        elif ("dimension" in request or "input" in request) and made.get("from") != made.get("to"):
            rel, added = str(made.get("file") or ""), _line_inside(root, made.get("file"), made.get("line"))
        else:
            return
        authors.note_hand_edit(root, rel, added)
        read = _judged(reply)
        if added and read is not None:
            reply["authors"] = authors.feature_authors(root, read)

    def drawing(self, root: Path, script: Path, step: Path, spec: dict) -> dict:
        """Make Drawing, and the Drawing panel's changes to its sheet (`drawings.py`): the drawing's
        script written beside the part, then run, which writes its PDF. The part is not run."""
        from cadgen.edit import drawings

        found = drawings.find(root, step)
        old = None
        try:
            if spec.get("make"):
                if found is not None:
                    return {"ok": False, "error": f"{step.stem} has a drawing already ({_relative(root, found)}). Change its sheet in the Drawing panel."}
                found = script.parent / f"{step.stem}_drawing.py"
                named = _project_units(root)
                found.write_text(drawings.template(step.stem, step, found, material=named.get("material", ""), units=named.get("units", "mm")),
                                 encoding="utf-8")
                words = "made a drawing of it: top, front, right and isometric views, each with its overall size, on an A3 sheet"
            else:
                if found is None:
                    return {"ok": False, "error": f"{step.stem} has no drawing yet. Make one first."}
                old = found.read_text(encoding="utf-8")
                made, said = drawings.change(old, spec.get("sheet") or {})
                found.write_text(made, encoding="utf-8")
                words = f"changed its drawing's sheet: {said}"
            pdf = drawings.build(found)
        except drawings.DrawingError as error:
            if old is not None:
                found.write_text(old, encoding="utf-8")
            return {"ok": False, "error": str(error), **({"drawing": _drawing_of(root, step)} if found else {})}
        return {"ok": True, "drawingOnly": True, "drawing": _drawing_of(root, step),
                "change": {"kind": "drawing", "file": _relative(root, found), "line": 1, "words": words, "pdf": _relative(root, pdf), "build": False}}

    def face_feature(self, payload: dict) -> dict:
        """The feature of the design tree that made a face the viewer picked, for double-click and
        the chips that name a face by it. ``payload``: ``file``, the document the face is on (a
        model's id, or a file's path, as ``state`` takes it); ``face``, its number on the part
        (``12``) or an engine ref to it (``plate/face 12``); and ``made_by``, what the engine said
        made it (the facts of the face, ``cadgen inspect``'s ``made_by``), when the viewer has read
        it; ``files``, the hashes of the files the page read the part from (``state``'s). While a build of
        the part is queued or running, or the files are no longer those, the answer is ``stale`` and
        names no feature. A model's document is answered from ``made_by`` (asked of the engine here when it was not
        given): the feature, function, file and line of the call that made the face, matched to the
        tree's rows, which are keyed by file and line. A file (an imported STEP, a part's STEP or
        xbf) names no model, so it, and a model's document no live worker built, falls back to the
        geometric map of the trace (``face_features.py``). Answers ``{"ok", "faceFeature": {"face",
        "feature", "component", "source", "madeBy", "stale"?}}``: ``feature`` a key of ``state``'s ``features`` (or of a
        component's), or None; ``source`` ``"made_by"``, ``"geometric"`` or None."""
        file_ref = str(payload.get("file") or "")
        face = payload.get("face")
        script = script_for(file_ref)
        if script is None:
            return {"ok": False, "reason": "no-script", "error": "This model has no part script beside it."}
        root = project_root(script)
        files = payload.get("files")
        if (self._builds is not None and self._builds.pending(script)) or \
                (isinstance(files, dict) and files and not all(_hash_inside(root, rel) == digest for rel, digest in files.items())):
            # The document on screen is about to change, or the page read other files than are there: a face of it
            # names no feature until the page reads the part again.
            return {"ok": True, "faceFeature": {"face": face, "feature": None, "component": None, "source": None, "madeBy": None,
                                                "stale": True}}
        made = payload.get("made_by") if isinstance(payload.get("made_by"), dict) else _made_by(file_ref, face)
        return self._tracer.ask({"script": str(script), "root": str(root), "op": "face", "face": face, "made_by": made,
                                 "mesh": False, **_project_units(root)})

    def close(self) -> None:
        """The tracer and the build running ended: what closes the engine's server closes them."""
        self._tracer.stop()
        if self._builds is not None:
            self._builds.stop()


def catalogue_key(given) -> str | None:
    """A material as bd_materials' catalogue names it (``canonical_name``: ``Alu_G6061_T6``), from a
    material or any name ``bd_materials.resolve`` takes; None for one it does not have."""
    from bd_materials import canonical_name, resolve

    if not isinstance(given, str):
        try:
            return canonical_name(given)
        except (TypeError, ValueError):
            given = getattr(given, "name", "")
    text = str(given or "").strip()
    if not text:
        return None
    try:
        return canonical_name(resolve(text))
    except ValueError:
        return None


def _made_by(file_ref: str, face) -> dict | None:
    """What the engine says made a face of a model's document (``cadgen.engine.api.inspect``, in this
    process's engine environment): None for a file, which names no model, or when the engine does not
    know (no live worker built it)."""
    from cadgen.engine.ids import is_id

    ident, _, _ = str(file_ref).partition("#")
    if not is_id(ident.strip()):
        return None
    ref = f"face {face}" if isinstance(face, int) and not isinstance(face, bool) else str(face or "")
    if not ref.strip():
        return None
    try:
        from cadgen.engine import api

        facts = api.inspect(ident.strip(), ref)
    except Exception:  # noqa: BLE001 - an engine that cannot say leaves the geometric map to answer
        return None
    found = facts.get("made_by") if isinstance(facts, dict) else None
    return found if isinstance(found, dict) else None


_shared: EditService | None = None
_shared_lock = threading.Lock()


def shared_service() -> EditService:
    """The server's one edit service, started on first use, closed with the process that holds it
    (``close_shared``: the engine's server calls it when it closes; ``atexit`` for any other)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = EditService()
            atexit.register(close_shared)
        return _shared


def close_shared() -> None:
    """The server's edit service closed, its tracer and its build ended, if it was ever started."""
    global _shared
    with _shared_lock:
        service, _shared = _shared, None
    if service is not None:
        service.close()
