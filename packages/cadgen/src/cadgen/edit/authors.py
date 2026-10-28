"""Who made each feature of a part, you or the agent, as Studio records it from the time it began
keeping track of the project.

Studio (a T3 Code fork) checkpoints the project for every chat: a commit kept under
``versions.CHECKPOINTS`` as a chat's first run starts (``.../ordinal/0``), before the agent writes
anything, and another as each turn ends. Recording begins at the first trace of a part in a git
repository that holds one; the viewer used on its own, in a project no chat has run in, writes
nothing there. The record's baseline is the project as the newest checkpoint then holds it, of any
chat: the snapshot T3 took at the start of the turn under way, a chat's first run's or the last
turn's end.

A repository with worktrees linked to it (``git worktree``: T3 Code makes one for each chat run in a
worktree of its own) keeps every checkout's checkpoints under the same refs, and nothing tells which
are this checkout's, so the newest may be another's and its turns would mark this one's features.
Such a repository is not recorded and its features have no marks, a record begun before it was
linked too (``_linked``: any entry in git's ``worktrees`` folder, a stale one included; a repository
git cannot read is taken as one). The cost: a project in a repository with T3 worktrees shows no
dots. Telling the checkouts apart needs Studio's server to mark each checkpoint with the checkout it
was made in.

A feature is told by the first line of its statement, as code: stripped, and without the comment at
its end, which is its name in the design tree (Rename writes it there), so a renamed feature is
still the line it was.

- It is nobody's when the baseline holds that line, in any of its scripts: whatever the newest
  checkpoint held when the record began, whoever made it. A script moved since keeps its lines. A
  script recording leaves out (``_left_out``) has no baseline, so none of its features is marked.
- Else it is yours when a hand edit wrote that line: the edit service notes the lines each change
  made by hand writes (``note_hand_edit``, ``written``).
- Else it is the agent's when a turn's checkpoint made since the baseline holds that line in that
  file: not the baseline's own checkpoint, and not a chat's first run's.
- Else it is nobody's: a line no turn's checkpoint holds yet (the agent's turn still running) has
  no mark rather than a wrong one.

Known, and accepted:

- A turn that ended before the record began has no marks: its features are in the baseline. The
  record begins at a part's first read (the workspace's, or Simple view's one quiet read as a model
  opens), so a project first opened after a turn ended has no marks for that turn.
- An edit made outside Studio between two turns is counted with the next turn, as T3 Code's own
  turn diff counts it: that turn's checkpoint is the first record of the line.

The record is ``LEDGER`` in the project, one JSON object a line, only ever added to: first the
baseline, its checkpoint and when that was (``start``), then one for each hand edit. It lies
beside ``versions.py``'s own scratch in ``.studio``, which git is told to leave out, so no
checkpoint takes it.

Who made a feature is a nicety: git missing, a git command failing or a record cut short leaves the
features with no marks, never a part that cannot be read.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tokenize
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cadgen.edit import versions
from cadgen._internal.atomic_replace import replace_atomic

__all__ = ["LEDGER", "feature_authors", "note_hand_edit", "start", "written"]

LEDGER = ".studio/authors.jsonl"
# A project whose scripts together are bigger than this is not recorded: its record would be too
# big to read again each time a turn ends.
BASELINE_LIMIT = 16 * 1024 * 1024
# Checkpoint copies of files kept read; past this many they are read again as asked.
_BLOBS_KEPT = 4096
# A part's body held in a name to go on from, as a command or Appearance holds a body the part
# returned outright: `return Box(...)` becomes `part = Box(...)`, which is still the line it was.
_HELD = re.compile(r"[A-Za-z_]\w*\s*=\s*(?P<value>.+)")

# Each file's lines as last judged, by (project, file): the moment they were (the checkpoints listed
# and the record's size), and the lines of the baseline, yours and those turns hold.
_JUDGED: dict[tuple[str, str], tuple[tuple, tuple[frozenset, frozenset, frozenset]]] = {}
# Each checkpoint copy of a file read, by (project, blob): its lines, as code.
_BLOBS: dict[tuple[str, str], frozenset] = {}
# Each project's checkpoints as last listed, by its folder: the stamp of git's ref files they were
# listed at (``_refs_stamp``), the checkpoints, and one digest of them all.
_TURNS: dict[str, tuple[tuple, list[dict], str]] = {}
# Each project folder's git repository, as git said once: its top and the folder holding its refs,
# or None for no repository.
_GIT: dict[str, tuple[Path, Path] | None] = {}
# Projects whose record cannot be begun (too big, git's exclude file unreadable, a folder that cannot
# be written), not tried again by this process on every trace.
_UNRECORDABLE: set[str] = set()


def _lines(lines) -> list[str]:
    """Lines stripped, blank ones left out, each once, in order."""
    return list(dict.fromkeys(stripped for line in lines if (stripped := str(line).strip())))


def _code(line: str) -> str:
    """A line as code: stripped, without the comment at its end. Read with Python's own tokenizer,
    so a ``#`` in a string stays; a line it cannot read (inside a string) stays whole."""
    line = str(line).strip()
    if "#" not in line:
        return line
    try:
        for token in tokenize.generate_tokens(io.StringIO(line).readline):
            if token.type == tokenize.COMMENT:
                return line[: token.start[1]].rstrip()
    except Exception:  # noqa: BLE001 - see the docstring: the line is kept whole
        pass
    return line


def _codes(lines) -> frozenset:
    """Lines as code (``_code``), each once, comments alone left out."""
    return frozenset(code for line in lines if (code := _code(line)))


def _forms(code: str) -> tuple[str, ...]:
    """A line, and the line it was when it holds in a name what a line returned outright (``_HELD``)."""
    held = _HELD.fullmatch(code)
    return (code, f"return {held['value']}") if held else (code,)


def _file(rel) -> str | None:
    """A file's path in the project as the record keeps it, or None for one outside the project."""
    text = str(rel or "")
    path = Path(text)
    return None if not text or path.is_absolute() or ".." in path.parts else path.as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _repository(root: Path) -> tuple[Path, Path] | None:
    """The project's git repository: its top and the folder holding its refs, asked of git once."""
    if str(root) not in _GIT:
        try:
            top, common = versions._git(root, "rev-parse", "--show-toplevel", "--git-common-dir").decode("utf-8").splitlines()[:2]
            _GIT[str(root)] = (Path(top).resolve(), (root / common).resolve())
        except (versions.VersionsError, OSError, ValueError):
            _GIT[str(root)] = None
    return _GIT[str(root)]


def _git_folder(root: Path) -> bool:
    """Whether the project's folder is the top of a git repository (it holds ``.git``)."""
    if not (root / ".git").exists():
        return False
    repository = _repository(root)
    return repository is not None and repository[0] == root


def _linked(root: Path) -> bool:
    """Whether the project's repository has worktrees linked to it (the module's words): an entry in
    the ``worktrees`` folder of its common git folder, a stale one too, or a repository git cannot
    read. Looked at on every call, git asked only once for its folder: a worktree may be added at any
    time."""
    repository = _repository(root)
    if repository is None:
        return True
    try:
        with os.scandir(repository[1] / "worktrees") as entries:
            return any(entries)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _refs_stamp(root: Path) -> tuple:
    """git's files of the checkpoints' refs as they are now, read without running git (but once, to
    find them): the stamp changes whenever a checkpoint is made, moved or taken away, loose,
    packed or in a reftable, so a part read while nothing moved lists no checkpoints again."""
    repository = _repository(root)
    if repository is None:
        raise versions.VersionsError(f"{root} keeps no versions: it is not a git repository")
    common = repository[1]
    paths = [common / "packed-refs", common / "reftable" / "tables.list"]
    for folder, _folders, files in os.walk(common / versions.CHECKPOINTS):
        paths += [Path(folder), *(Path(folder) / name for name in sorted(files))]
    stamp = []
    for path in paths:
        try:
            found = path.stat()
            stamp.append((path.as_posix(), found.st_mtime_ns, found.st_size))
        except FileNotFoundError:
            # Not there, or gone since the walk found it (a ref's lock, renamed into the ref).
            stamp.append((path.as_posix(), None, None))
    return tuple(stamp)


def _turns(root: Path) -> tuple[list[dict], str]:
    """The project's checkpoints, oldest first (``versions._checkpoints``), and a digest of all of
    them, which moves when any is made, moved or taken away, wherever it sorts: listed again only
    when their refs moved."""
    stamp = _refs_stamp(root)
    listed = _TURNS.get(str(root))
    if listed is None or listed[0] != stamp:
        turns = [row for row in versions._checkpoints(root) if row["ref"].startswith(versions.CHECKPOINTS)]
        digest = hashlib.sha256("\n".join(f"{turn['ref']} {turn['commit']}" for turn in turns).encode("utf-8")).hexdigest()
        listed = _TURNS[str(root)] = (stamp, turns, digest)
    return listed[1], listed[2]


def _skipped(name: str) -> bool:
    """Whether a folder or a file is one the edit service never scans for a project's scripts
    (``service._SKIP``: dot folders, tmp, build, dist, vendor, node_modules...)."""
    from cadgen.edit.service import _SKIP

    return bool(_SKIP.match(name))


def _left_out(root: Path, file: str) -> bool:
    """Whether recording leaves a project file out of its baseline: it, or a folder it is in, is
    one the edit service never scans (``_skipped``), or it is in a virtual environment (a folder
    holding ``pyvenv.cfg``)."""
    parts = PurePosixPath(file).parts
    return any(_skipped(part) for part in parts) or any((root.joinpath(*parts[:depth]) / "pyvenv.cfg").is_file() for depth in range(1, len(parts)))


def _cat(root: Path, blobs: list[str]) -> dict[str, bytes]:
    """Each blob's bytes, read from git in one ``cat-file --batch``."""
    if not blobs:
        return {}
    out = versions._git(root, "cat-file", "--batch", stdin=("\n".join(blobs) + "\n").encode("utf-8"))
    found, at = {}, 0
    for blob in blobs:
        end = out.index(b"\n", at)
        _name, kind, *size = out[at:end].decode("utf-8").split()
        at = end + 1
        if kind != "blob" or not size:
            continue  # "missing"
        found[blob] = out[at : at + int(size[0])]
        at += int(size[0]) + 1
    return found


def _committed_baseline(root: Path, commit: str) -> dict[str, list[str]] | None:
    """Each project script's lines as ``commit`` holds them (the newest checkpoint as the record
    begins), by its path: only the scripts it holds, but those recording leaves out, the virtual
    environments it holds among them. None when they are too big together to record."""
    listed = versions._git(root, "ls-tree", "-r", "-l", "-z", commit).decode("utf-8", "surrogateescape")
    entries = []
    for entry in filter(None, listed.split("\0")):
        meta, _, path = entry.partition("\t")
        _mode, kind, blob, size = meta.split()
        entries.append((kind, blob, size, PurePosixPath(path)))
    environments = {path.parent for _kind, _blob, _size, path in entries if path.name == "pyvenv.cfg" and path.parent != PurePosixPath(".")}
    kept, total = [], 0
    for kind, blob, size, path in entries:
        if kind != "blob" or path.suffix != ".py" or any(_skipped(part) for part in path.parts) or not environments.isdisjoint(path.parents):
            continue
        total += int(size)
        if total > BASELINE_LIMIT:
            return None
        kept.append((path.as_posix(), blob))
    data = _cat(root, sorted({blob for _path, blob in kept}))
    found: dict[str, list[str]] = {}
    for path, blob in kept:
        try:
            found[path] = _lines(data[blob].decode("utf-8").splitlines())
        except (KeyError, UnicodeDecodeError):
            continue
    return found


def _begin(root: Path, ledger: Path, turns: list[dict]) -> bool:
    """The record's first line written (``start``): True once it is there, False when it cannot be.
    Its baseline is the project as the newest of ``turns`` (the project's checkpoints, oldest first)
    holds it, of whatever chat: the snapshot T3 took at the start of the turn under way, a chat's
    first run's or the last turn's end. The record is dated at that checkpoint and names it, as no
    turn of the agent's: a turn that ended before has no marks."""
    partial = ledger.with_name(f".{ledger.name}.{os.getpid()}")
    try:
        # Git is told to leave `.studio` out before anything is written there.
        versions._leave_out_of_git(root)
        newest = turns[-1]
        baseline = _committed_baseline(root, newest["commit"])
        if baseline is None:
            return False
        began = datetime.fromtimestamp(newest["time"], timezone.utc).isoformat(timespec="seconds")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        record = {"start": began, "checkpoint": newest["commit"], "baseline": baseline}
        partial.write_text(json.dumps(record) + "\n", encoding="utf-8")
        # Another viewer's tracer may have begun first: its record stands.
        if not ledger.exists():
            replace_atomic(partial, ledger)
        return True
    except Exception:  # noqa: BLE001 - git's exclude file unreadable (UTF-16, as PowerShell appends), a folder that cannot be written
        return False
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass


def start(root: Path) -> None:
    """Begin recording who makes each feature of the project at ``root``: the record's first line,
    the project as its newest checkpoint holds it, dated at that checkpoint (``_begin``). Once only,
    and only at the top of a git repository that holds a checkpoint, a chat having run in it, and no
    worktree linked to it (``_linked``); no checkpoint, no record. Anything in the way leaves the
    project unrecorded."""
    try:
        root = Path(root).resolve()
        ledger = root / LEDGER
        if ledger.exists() or str(root) in _UNRECORDABLE or not _git_folder(root) or _linked(root):
            return
        turns = _turns(root)[0]
        if turns and not _begin(root, ledger, turns):
            _UNRECORDABLE.add(str(root))
    except Exception:  # noqa: BLE001 - a nicety (the module's words): the part is read, unrecorded
        return


def written(hunks) -> list[str]:
    """The lines a change's hunks (``commands.hunks``: each run of ``old`` lines that becomes
    ``new``) write as the engineer's own: every new line but a comment alone, one whose code the
    hunk only keeps, moves or renames (among the lines it replaces), and the part's body held in a
    name to go on from (``_HELD``)."""
    out: list[str] = []
    for hunk in hunks if isinstance(hunks, list) else []:
        if not isinstance(hunk, dict) or not isinstance(hunk.get("new"), list):
            continue
        replaced = _codes(hunk.get("old") if isinstance(hunk.get("old"), list) else [])
        out += [line for line in _lines(hunk["new"]) if (code := _code(line)) and replaced.isdisjoint(_forms(code))]
    return out


def note_hand_edit(root: Path, rel: str, added: list[str]) -> None:
    """Record ``added``, lines a hand edit wrote in ``rel`` (a file's path in the project), as yours:
    one record added to the ledger, its lines stripped and blank ones left out. Nothing where
    recording has not begun: before the part's first trace, or where it never begins."""
    try:
        file, lines = _file(rel), _lines(added)
        if file is None or not lines:
            return
        record = json.dumps({"at": _now(), "by": "you", "file": file, "lines": lines}) + "\n"
        # Added to a record that is there, never one made here.
        handle = os.open(Path(root) / LEDGER, os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0))
        try:
            os.write(handle, record.encode("utf-8"))
        finally:
            os.close(handle)
    except Exception:  # noqa: BLE001 - a nicety (the module's words): the change stands, unnoted
        return


def _read(ledger: Path) -> tuple[float, str | None, frozenset, frozenset] | None:
    """The record: when its baseline was (in seconds), the checkpoint it was read from, the
    baseline's lines and the lines hand edits wrote, each as code (``_code``) and in whatever file,
    as a file moved since keeps its lines. None when its first line is not a beginning."""
    began, checkpoint, before, yours = None, None, frozenset(), set()
    with ledger.open(encoding="utf-8") as text:
        for number, line in enumerate(text):
            try:
                record = json.loads(line)
            except ValueError:
                record = None  # one being written, or cut short
            if number == 0:
                if not isinstance(record, dict) or not isinstance(record.get("start"), str) or not isinstance(record.get("baseline"), dict):
                    return None
                began = datetime.fromisoformat(record["start"]).timestamp()
                checkpoint = record.get("checkpoint") if isinstance(record.get("checkpoint"), str) else None
                before = _codes(line for lines in record["baseline"].values() if isinstance(lines, list) for line in lines)
            elif isinstance(record, dict) and record.get("by") == "you" and isinstance(record.get("lines"), list):
                yours |= _codes(each for each in record["lines"] if isinstance(each, str))
    return (began, checkpoint, before, frozenset(yours)) if began is not None else None


def _blob_lines(root: Path, blobs: list[str]) -> list[frozenset]:
    """Each blob's lines, as code: read from git once, those not read yet in one ``cat-file``."""
    if len(_BLOBS) > _BLOBS_KEPT:
        _BLOBS.clear()
    for blob, data in _cat(root, [blob for blob in blobs if (str(root), blob) not in _BLOBS]).items():
        _BLOBS[(str(root), blob)] = _codes(data.decode("utf-8", "replace").splitlines())
    return [_BLOBS.get((str(root), blob), frozenset()) for blob in blobs]


def _held(root: Path, file: str, turns: list[dict], began: float, baseline: str | None) -> frozenset:
    """The lines of ``file`` that the turns' checkpoints made since the baseline (``began``) hold,
    as code: each checkpoint's copy of the file read once. The baseline's own checkpoint is no
    turn, told by its commit (a turn's end it may be, whose second others share), nor is a chat's
    first run's (``ordinal/0``)."""
    since = [turn for turn in turns if turn["time"] >= int(began) and turn["ordinal"] > 0 and turn["commit"] != baseline]
    blobs = sorted({blob for blob in versions._blobs(root, [f"{turn['commit']}:{file}" for turn in since]) if blob})
    return frozenset().union(*_blob_lines(root, blobs)) if blobs else frozenset()


def _authors(root: Path, features: list[dict]) -> dict[str, str]:
    ledger = root / LEDGER
    try:
        size = ledger.stat().st_size
    except OSError:
        return {}
    # A record begun before a worktree was linked marks nothing either: its newest checkpoints may be another checkout's.
    if _linked(root):
        return {}
    turns, listed = _turns(root)
    moment = (listed, size)
    record = None
    made: dict[str, str] = {}
    outside: dict[str, bool] = {}
    for feature in features:
        file, text = _file(feature.get("file")), _code(feature.get("text") or "")
        # A suppressed feature's line is Studio's note of what it was (`deleting.py`), not a statement.
        if file is None or not text or not feature.get("key") or feature.get("suppressed"):
            continue
        # A file recording leaves out has no baseline to tell its lines from before by.
        if file not in outside:
            outside[file] = _left_out(root, file)
        if outside[file]:
            continue
        judged = _JUDGED.get((str(root), file))
        if judged is None or judged[0] != moment:
            if record is None:
                record = _read(ledger)
                if record is None:
                    return {}
            began, checkpoint, before, yours = record
            judged = _JUDGED[(str(root), file)] = (moment, (before, yours, _held(root, file, turns, began, checkpoint)))
        before, yours, held = judged[1]
        forms = _forms(text)
        if not before.isdisjoint(forms):
            continue
        if not yours.isdisjoint(forms):
            made[feature["key"]] = "you"
        elif not held.isdisjoint(forms):
            made[feature["key"]] = "agent"
    return made


def feature_authors(root: Path, features: list[dict]) -> dict[str, str]:
    """Who made each of ``features`` (the tracer's: its ``key``, ``file``, and ``text``, the first
    line of its statement stripped), by its key: "you" or "agent", and no entry for one nobody is
    known to have made (the module's words). Each file is judged once for each moment of the
    project: the checkpoints listed and the record's size."""
    try:
        return _authors(Path(root).resolve(), features)
    except Exception:  # noqa: BLE001 - a nicety (the module's words): the part is read with no marks
        return {}
