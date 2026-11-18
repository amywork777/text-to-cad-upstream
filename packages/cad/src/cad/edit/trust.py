"""A project's custom features run only once the person trusts them: a trust gate, not a sandbox.

A custom feature (``cad.build123d.feature``) is Python the project carries: a ``features.py`` written once
and copied from project to project, as Onshape's FeatureScript lives in a document. That moves the line
where code is trusted from the app to the document. A document that runs its code as it opens is the macro
problem Office had, so Studio's edit mode runs none of a project's code while the project declares custom
features the person has not trusted. It says which files and features they are, and runs them once the
person says to; the trust is remembered for the project and that code as it is (a hash of each file that
declares a feature), so the same project asks again when that code changes.

What is read here is read as text (``ast``), never imported: deciding whether to run a file never runs it.
Ribbon commands and the library's own functions are cadgen's and are never asked about.

This is a gate, not a sandbox: trusted, the code runs with the person's own permissions, as a model script
always has. Running it confined (a subprocess with restricted permissions, or a restricted Python) is the
follow-up. Nor does it judge a part's script that declares no feature: that stays as it was before custom
features, run as the person's own code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

__all__ = ["custom_code", "gate", "grant", "store_path"]

# The library modules ``feature`` is imported from (``cad.build123d``'s lazy name is ``_features``'s).
_FEATURE_MODULES = ("cad.build123d", "cad.build123d._features", "cadgen.build123d")
# Folders a project's own code never lives in, as the edit service skips them (`service._SKIP`).
_SKIP = re.compile(r"^(\.|node_modules$|__pycache__$|tmp$|dist$|build$|vendor$|site-packages$)")
_SCAN_LIMIT = 4000
_STORE = "trusted-projects.json"


def store_path() -> Path:
    """Where the trust given is kept: in the user's CAD state (``CAD_STATE_DIR`` overrides it), never in the
    project, which could otherwise trust itself."""
    from cad.engine.places import state_dir

    return state_dir() / "studio" / _STORE


def _features_in(text: str) -> list[str]:
    """The names of the custom features a file declares, read from its text: each function decorated
    with ``feature`` (or ``feature(...)``) as imported from the library, under any name it was imported as,
    or reached through the module (``build123d.feature``, ``cad.build123d.feature``)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    names, modules = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _FEATURE_MODULES:
            names |= {alias.asname or alias.name for alias in node.names if alias.name in ("feature", "*")}
            if any(alias.name == "*" for alias in node.names):
                names.add("feature")
        elif isinstance(node, ast.ImportFrom) and node.module in ("cad", "cadgen"):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == "build123d"}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _FEATURE_MODULES or alias.name in ("cad", "cadgen"):
                    modules.add(alias.asname or alias.name)

    def declares(decorator: ast.expr) -> bool:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            return target.id in names
        if isinstance(target, ast.Attribute) and target.attr == "feature":
            root = target.value
            while isinstance(root, ast.Attribute):
                root = root.value
            return isinstance(root, ast.Name) and root.id in modules
        return False

    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if declares(decorator):
                    named = decorator.args[0] if isinstance(decorator, ast.Call) and decorator.args else None
                    label = named.value if isinstance(named, ast.Constant) and isinstance(named.value, str) else node.name
                    found.append(label)
                    break
    return found


def _project_files(root: Path):
    seen = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(each for each in dirs if not _SKIP.match(each))
        for name in sorted(files):
            if name.endswith(".py"):
                seen += 1
                if seen > _SCAN_LIMIT:
                    return
                yield Path(folder) / name


def custom_code(root: Path) -> list[dict]:
    """Every file of the project that declares custom features: ``file`` (relative to ``root``), its
    ``features`` by name, and the ``sha256`` of its bytes, in the order of their paths."""
    root = Path(root).resolve()
    found = []
    for path in _project_files(root):
        try:
            raw = path.read_bytes()
            features = _features_in(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if features:
            found.append({"file": path.relative_to(root).as_posix(), "features": features, "sha256": hashlib.sha256(raw).hexdigest()})
    return found


def _digest(found: list[dict]) -> str:
    """One hash of the project's custom code as it is: every declaring file's path and hash."""
    return hashlib.sha256("\n".join(f"{each['file']}\0{each['sha256']}" for each in found).encode("utf-8")).hexdigest()


def _key(root: Path) -> str:
    return str(Path(root).resolve())


def _read_store() -> dict:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("projects"), dict) else {}


def _write_store(data: dict) -> None:
    from cad._internal.atomic_replace import write_bytes_atomic

    # Written whole, then moved into place: a store half written is never read.
    write_bytes_atomic(store_path(), json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))


def gate(root: Path) -> dict | None:
    """None when the project's code may run: it declares no custom feature, or the person trusted its
    custom code as it is now. Otherwise the refusal edit mode answers in the part's place, ``reason``
    ``"untrusted"`` and ``trust``: the files and features, the ``digest`` to grant, and ``changed``, true
    when the person had trusted this project's custom code and it has changed since."""
    found = custom_code(root)
    if not found:
        return None
    digest = _digest(found)
    given = _read_store().get("projects", {}).get(_key(root))
    if isinstance(given, dict) and given.get("digest") == digest:
        return None
    files = [{"file": each["file"], "features": each["features"]} for each in found]
    return {"ok": False, "reason": "untrusted",
            "error": "This project contains custom code features. Its code has not run: trust it to run it.",
            "trust": {"digest": digest, "files": files, "changed": isinstance(given, dict)}}


def grant(root: Path, digest: str) -> dict:
    """The person trusts the project's custom code as the prompt showed it (``digest``, the gate's). The
    code is read again first: what changed since the prompt is not what was trusted, and is asked about
    again."""
    found = custom_code(root)
    if not found:
        return {"ok": True}
    if _digest(found) != digest:
        refused = gate(root) or {}
        return {**refused, "error": "The project's custom code changed since you were asked. Look at it again before trusting it."}
    data = _read_store()
    data.setdefault("projects", {})[_key(root)] = {"digest": digest, "files": {each["file"]: each["sha256"] for each in found}}
    _write_store(data)
    return {"ok": True}
