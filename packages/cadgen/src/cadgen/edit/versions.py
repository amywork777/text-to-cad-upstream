"""A part's versions in a Studio project, and what changed between two of them.

Studio (a T3 Code fork) ends every chat turn with a checkpoint: a commit of the project folder kept
under ``refs/t3/orchestration-v2/checkpoints/<the thread's scope>/ordinal/<turn>``, beside the
folder's own branch, which never moves. Those commits are the project's versions. This module reads
them with git to list the versions of one file (each time its contents changed, in order, and the
working file when it differs from the last), and compares two: their solids (``solid_diff.py``, a
process of its own, since this one never loads the CAD kernel), the named sizes in the part's
script, and any text files asked for, as each version had them.

What it writes, the two versions' files and the difference between them, goes under
``<folder>/.studio/compare/<key>/``, the key named by the file and the two versions' contents, so a
comparison is made once and found again. Git is told to leave ``.studio`` out (``info/exclude``), so
a checkpoint never takes it.

Going back to a version (``restore``, Google Docs' Restore this version) writes the part's file and
the script it is built from over the files on disk, as that version had them. What was on disk is
kept first, unless a version already holds it as it is: a commit of the newest version's tree with
those files as they were, under ``refs/studio/kept/``, made with an index of its own so the folder's
own index and branch never move. Kept versions are listed with the checkpoints, so going back loses
nothing and can itself be gone back on.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from cadgen._internal.atomic_replace import replace_atomic

__all__ = ["VersionsError", "compare", "named_sizes", "restore", "versions"]

CHECKPOINTS = "refs/t3/orchestration-v2/checkpoints/"
# What was on disk when a version was gone back to: Studio's, beside T3 Code's checkpoints.
KEPT = "refs/studio/kept/"
# Who a kept version is by, whatever the folder's git is set up with.
KEPT_BY = {
    "GIT_AUTHOR_NAME": "Studio",
    "GIT_AUTHOR_EMAIL": "studio@localhost",
    "GIT_COMMITTER_NAME": "Studio",
    "GIT_COMMITTER_EMAIL": "studio@localhost",
}
# A version is a commit's id, as the list gives it.
COMMIT_ID = re.compile(r"[0-9a-f]{7,64}")
COMPARE_DIR = ".studio/compare"
# A comparison still running after this long is taken to have died, and the next request starts it again.
DIFF_TIMEOUT = 600
TEXT_LIMIT = 512 * 1024
TEXTS_LIMIT = 16
NOW = "now"
# Names of units, not of sizes: `LENGTH * INCH` (as the tracer's ``UNIT_NAMES``).
UNIT_NAMES = {"INCH", "INCHES", "IN", "MM", "MM_PER_IN", "MM_PER_INCH"}


class VersionsError(ValueError):
    """A request this module cannot answer: no repository, a file outside it, a version it lacks."""


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _git(cwd: Path, *args: str, stdin: bytes | None = None, env: dict | None = None) -> bytes:
    ran = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
        **_no_window(),
    )
    if ran.returncode != 0:
        message = ran.stderr.decode("utf-8", "replace").strip()
        raise VersionsError(message or f"git {args[0]} failed")
    return ran.stdout


def _repository(folder: Path) -> Path:
    if not folder.is_dir():
        raise VersionsError(f"{folder} is not a folder")
    try:
        return Path(_git(folder, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    except VersionsError as error:
        raise VersionsError(f"{folder} keeps no versions: it is not a git repository") from error


def _in_repository(top: Path, folder: Path, path: str) -> str:
    """The file's path in the repository, from its path in the folder (or a full path)."""
    target = Path(path).expanduser()
    target = (target if target.is_absolute() else folder / target).resolve()
    try:
        return target.relative_to(top).as_posix()
    except ValueError as error:
        raise VersionsError(f"{path} is outside the project's repository") from error


def _checkpoints(top: Path) -> list[dict]:
    """Every chat turn's checkpoint in the repository, and what was kept on going back, oldest first."""
    listed = _git(top, "for-each-ref", "--format=%(objectname) %(creatordate:unix) %(refname)", CHECKPOINTS, KEPT)
    rows = []
    for line in listed.decode("utf-8").splitlines():
        commit, when, ref = line.split(" ", 2)
        ordinal = ref.rsplit("/", 1)[-1]
        rows.append({"commit": commit, "time": int(when), "ref": ref, "ordinal": int(ordinal) if ordinal.isdigit() else 0})
    rows.sort(key=lambda row: (row["time"], row["ordinal"]))
    return rows


def _blobs(top: Path, specs: list[str]) -> list[str | None]:
    """The blob each ``<commit>:<path>`` names, or None where that commit has no such file."""
    if not specs:
        return []
    answered = _git(top, "cat-file", "--batch-check=%(objectname) %(objecttype)", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    return [line.split(" ", 1)[0] if line.endswith(" blob") else None for line in answered.decode("utf-8").splitlines()]


def _working_blob(top: Path, rel: str) -> str | None:
    if not (top / rel).is_file():
        return None
    return _git(top, "hash-object", "--", rel).decode("utf-8").strip()


def versions(folder: str, path: str) -> dict:
    """The versions of one file of the project, oldest first: each checkpoint where its contents
    changed (``id`` the commit, ``ref`` the checkpoint, ``time`` in seconds), and ``now`` last when
    the file on disk differs from the last checkpoint's (a hand edit since the last turn)."""
    folder_path = Path(folder).expanduser()
    top = _repository(folder_path)
    rel = _in_repository(top, folder_path, path)
    rows = _checkpoints(top)
    found: list[dict] = []
    for row, blob in zip(rows, _blobs(top, [f"{row['commit']}:{rel}" for row in rows])):
        if blob is None or (found and found[-1]["blob"] == blob):
            continue
        found.append({"id": row["commit"], "ref": row["ref"], "time": row["time"], "blob": blob})
    working = _working_blob(top, rel)
    if working is not None and (not found or found[-1]["blob"] != working):
        found.append({"id": NOW, "ref": None, "time": int((top / rel).stat().st_mtime), "blob": working})
    return {"ok": True, "versions": found}


def _bytes_at(top: Path, rel: str, version: str) -> bytes | None:
    """The file as a version had it: a checkpoint's commit, or ``now`` for the file on disk."""
    if version == NOW:
        try:
            return (top / rel).read_bytes()
        except OSError:
            return None
    try:
        return _git(top, "cat-file", "blob", f"{version}:{rel}")
    except VersionsError:
        return None


def _blob_at(top: Path, rel: str, version: str) -> str | None:
    if version == NOW:
        return _working_blob(top, rel)
    return _blobs(top, [f"{version}:{rel}"])[0]


def _text_at(top: Path, rel: str, version: str) -> str | None:
    data = _bytes_at(top, rel, version)
    if data is None or len(data) > TEXT_LIMIT:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _number(node: ast.AST) -> float | int | None:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _number(node.operand)
        if inner is not None:
            return -inner if isinstance(node.op, ast.USub) else inner
    return None


def named_sizes(source: str | None) -> list[dict] | None:
    """A part script's named sizes, as the tracer names them: every ``NAME = <number>`` (or
    ``NAME: float = <number>``), in the order written, but unit names. None when there is no script
    or it does not parse."""
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    sizes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            name, value = node.target.id, node.value
        else:
            continue
        number = _number(value)
        if number is None or name.startswith("__") or name.upper() in UNIT_NAMES:
            continue
        sizes.append({"name": name, "value": number, "line": node.lineno, "col": node.col_offset})
    sizes.sort(key=lambda size: (size["line"], size["col"]))
    return [{"name": size["name"], "value": size["value"], "line": size["line"]} for size in sizes]


def _script_of(rel: str) -> str | None:
    """The part script a file is built from, by Studio's rule (``service.script_for``): the script
    itself, or the one of the same name beside a STEP."""
    suffix = Path(rel).suffix.lower()
    if suffix == ".py":
        return rel
    if suffix in (".step", ".stp"):
        return Path(rel).with_suffix(".py").as_posix()
    return None


def _leave_out_of_git(top: Path) -> None:
    """Tell git to ignore ``.studio``, in this clone only, so no checkpoint takes a comparison."""
    exclude = Path(_git(top, "rev-parse", "--git-path", "info/exclude").decode("utf-8").strip())
    exclude = exclude if exclude.is_absolute() else top / exclude
    text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if ".studio/" in text.splitlines():
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as file:
        file.write(("" if text == "" or text.endswith("\n") else "\n") + ".studio/\n")


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        return
    partial = path.with_name(f".{path.name}.{os.getpid()}")
    partial.write_bytes(data)
    replace_atomic(partial, path)


def _shape(out: Path, suffix: str, *, retry: bool, wait: bool) -> dict:
    """The solids' comparison: done (its result), working (asked again in ``retryMs``), or failed."""
    done, started = out / "result.json", out / "started"
    if retry:
        for stale in (done, started):
            stale.unlink(missing_ok=True)
    if done.is_file():
        result = json.loads(done.read_text(encoding="utf-8"))
        return {"status": "failed", **result} if "error" in result else {"status": "done", **result}
    if started.is_file():
        if not wait and time.time() - started.stat().st_mtime < DIFF_TIMEOUT:
            return {"status": "working", "retryMs": 1000}
        started.unlink(missing_ok=True)
    # One comparison at a time: the request that makes the mark starts it, the rest wait for it.
    try:
        mark = os.open(started, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"status": "working", "retryMs": 1000}
    os.write(mark, str(os.getpid()).encode("utf-8"))
    os.close(mark)
    command = [sys.executable, "-P", "-m", "cadgen.edit.solid_diff", str(out / f"older{suffix}"), str(out / f"newer{suffix}"), str(out)]
    if wait:
        subprocess.run(command, capture_output=True, check=False, timeout=DIFF_TIMEOUT, **_no_window())
        return _shape(out, suffix, retry=False, wait=False)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
        **_no_window(),
    )
    # Reaped when it ends, so a long-lived server gathers no finished processes.
    threading.Thread(target=process.wait, daemon=True).start()
    return {"status": "working", "retryMs": 1000}


def compare(
    folder: str,
    path: str,
    older: str,
    newer: str,
    texts: list | None = None,
    *,
    retry: bool = False,
    wait: bool = False,
) -> dict:
    """What changed in one file between two of its versions (each a checkpoint's commit, or ``now``).

    ``files`` are the two versions' files and, once the solids are compared, the difference, each
    by its path in the folder. ``shape`` is the solids' comparison (STEP files only). ``script`` is
    the part script at both versions with its named sizes, and ``texts`` the text files asked for
    (check results, say), at both. ``wait`` compares the solids before answering, for tests and the
    command line; a request answers at once and is asked again while the solids are compared.
    """
    folder_path = Path(folder).expanduser()
    top = _repository(folder_path)
    rel = _in_repository(top, folder_path, path)
    older_blob, newer_blob = _blob_at(top, rel, older), _blob_at(top, rel, newer)
    if older_blob is None or newer_blob is None:
        raise VersionsError(f"{path} is not in one of the two versions")
    key = hashlib.sha256(f"{rel}\n{older_blob}\n{newer_blob}".encode("utf-8")).hexdigest()[:20]
    out = folder_path.resolve() / COMPARE_DIR / key
    out.mkdir(parents=True, exist_ok=True)
    _leave_out_of_git(top)
    suffix = Path(rel).suffix.lower()
    for name, version in (("older", older), ("newer", newer)):
        target = out / f"{name}{suffix}"
        if not target.exists():
            data = _bytes_at(top, rel, version)
            if data is None:
                raise VersionsError(f"{path} could not be read at one of the two versions")
            _write_once(target, data)
    shown = (out.relative_to(folder_path.resolve())).as_posix()
    result: dict = {
        "ok": True,
        "key": key,
        "files": {"older": f"{shown}/older{suffix}", "newer": f"{shown}/newer{suffix}", "diff": None},
        "shape": _shape(out, suffix, retry=retry, wait=wait) if suffix in (".step", ".stp") else {"status": "unsupported"},
    }
    if result["shape"].get("diff"):
        result["files"]["diff"] = f"{shown}/{result['shape']['diff']}"
    script = _script_of(rel)
    if script is not None:
        older_text, newer_text = _text_at(top, script, older), _text_at(top, script, newer)
        if older_text is not None or newer_text is not None:
            result["script"] = {
                "path": Path(os.path.relpath(top / script, folder_path.resolve())).as_posix(),
                "older": older_text,
                "newer": newer_text,
                "olderSizes": named_sizes(older_text),
                "newerSizes": named_sizes(newer_text),
            }
    if texts:
        asked = [str(text) for text in texts if isinstance(text, str)][:TEXTS_LIMIT]
        result["texts"] = {}
        for text in asked:
            other = _in_repository(top, folder_path, text)
            result["texts"][text] = {"older": _text_at(top, other, older), "newer": _text_at(top, other, newer)}
    return result


def _part_files(top: Path, rel: str, version: str) -> list[str]:
    """A part's files to go back, each that the version has: the file, and what it is built from
    beside it (its script by Studio's rule, ``_script_of``, or a SolidCraft design)."""
    candidates = [rel]
    script = _script_of(rel)
    if script is not None and script != rel:
        candidates.append(script)
    suffix = Path(rel).suffix.lower()
    if suffix in (".step", ".stp"):
        candidates.append(Path(rel).with_suffix(".solidcraft").as_posix())
    elif suffix == ".py":
        candidates.append(Path(rel).with_suffix(".step").as_posix())
    blobs = _blobs(top, [f"{version}:{candidate}" for candidate in candidates])
    return [candidate for candidate, blob in zip(candidates, blobs) if blob is not None]


def _on_record(top: Path, rows: list[dict], files: list[str]) -> bool:
    """Whether a version (a checkpoint, or one kept before) holds every one of the files as on disk."""
    if not rows:
        return False
    working = [_working_blob(top, file) for file in files]
    blobs = _blobs(top, [f"{row['commit']}:{file}" for row in rows for file in files])
    count = len(files)
    return any(blobs[at : at + count] == working for at in range(0, len(blobs), count))


def _keep(top: Path, files: list[str], base: str | None) -> str:
    """The files as they are on disk, kept as a version: a commit of ``base``'s tree (the newest
    version) with them as they are, under ``KEPT``. A scratch index does the work, so the folder's
    own index, branch and files are left as they are."""
    with tempfile.TemporaryDirectory(prefix="studio-keep-") as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index"), **KEPT_BY}
        if base is not None:
            _git(top, "read-tree", base, env=env)
        for file in files:
            if (top / file).is_file():
                blob = _git(top, "hash-object", "-w", "--", file).decode("utf-8").strip()
                _git(top, "update-index", "--add", "--cacheinfo", f"100644,{blob},{file}", env=env)
            else:
                _git(top, "update-index", "--force-remove", "--", file, env=env)
        tree = _git(top, "write-tree", env=env).decode("utf-8").strip()
        parents = ["-p", base] if base is not None else []
        message = "Kept by Studio before going back to an earlier version"
        commit = _git(top, "commit-tree", "--no-gpg-sign", tree, *parents, "-m", message, env=env)
    kept = commit.decode("utf-8").strip()
    _git(top, "update-ref", f"{KEPT}{int(time.time() * 1000)}-{kept[:12]}", kept)
    return kept


def restore(folder: str, path: str, version: str) -> dict:
    """Go back to a version of one file of the project, as Google Docs' Restore this version does:
    the file and what it is built from (``_part_files``), as the version had them, written over the
    files on disk. What was on disk is kept as a version first (``_keep``), unless one already holds
    it. ``restored`` is the files written, by their paths in the folder; ``kept`` the kept version's
    commit, or None when nothing needed keeping."""
    folder_path = Path(folder).expanduser()
    top = _repository(folder_path)
    rel = _in_repository(top, folder_path, path)
    if version == NOW:
        raise VersionsError("That is the file on disk already.")
    if not COMMIT_ID.fullmatch(version):
        raise VersionsError("There is no such version.")
    files = _part_files(top, rel, version)
    if rel not in files:
        raise VersionsError(f"{path} is not in that version")
    rows = _checkpoints(top)
    kept = None if _on_record(top, rows, files) else _keep(top, files, rows[-1]["commit"] if rows else None)
    for file in files:
        data = _bytes_at(top, file, version)
        if data is None:
            raise VersionsError(f"{file} could not be read at that version")
        target = top / file
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.{os.getpid()}.restore")
        partial.write_bytes(data)
        if target.exists():
            shutil.copymode(target, partial)
        replace_atomic(partial, target)
    shown = [Path(os.path.relpath(top / file, folder_path.resolve())).as_posix() for file in files]
    return {"ok": True, "restored": shown, "kept": kept}
