"""What changed between two versions of a part, as solids, for Studio's versions (``versions.py``).

Run as ``python -m cad.edit.solid_diff OLDER.step NEWER.step OUT_DIR``, or, for a model's script
(cadgen 0.10's part, which writes no file of its own), as ``python -m cad.edit.solid_diff --model
NAME REPOSITORY SCRIPT OLDER NEWER OUT_DIR``: the model is built at each version (a commit, or
``now``) into ``OUT_DIR/older.step`` and ``OUT_DIR/newer.step``, then those are compared. Ported from Fixture's
``apps/server/py/diff_revision.py``. The two STEP files are compared as solids and the material is
split into unchanged (grey, see-through), added (green) and removed (red), written as
``OUT_DIR/what-changed.step`` (the viewer's tab reads "What changed") with each kind a labelled child of its own, so the viewer and the model
pictures show the three colours. ``OUT_DIR/result.json`` gets the volumes, each version's size and
body count, and whether the part is the same or only moved: a part that is the same, or only moved
(little overlap, volumes within 10%), gets no ``what-changed.step``. When the comparison fails,
``result.json`` says why, with ``environment`` true when this machine's tooling failed (an import,
memory, a file) rather than the geometry.

This loads the CAD kernel, so it is always a process of its own: the viewer's server never imports
it (``test_module_boundaries``).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from cad._internal.atomic_replace import replace_atomic

__all__ = ["build", "compare", "main"]

EPS_MM3 = 1e-6
UNCHANGED = (0.5, 0.5, 0.5, 0.3)
ADDED = (0.0, 0.8, 0.0, 1.0)
REMOVED = (0.9, 0.0, 0.0, 1.0)


def _load(path: Path):
    """Import a STEP and fuse its solids into one shape (a compound where they are apart)."""
    from build123d import import_step

    solids = import_step(str(path)).solids()
    if not solids:
        raise ValueError(f"{path.name} has no solid bodies")
    merged = solids[0]
    for solid in solids[1:]:
        merged = merged + solid
    return merged, len(solids)


def _leaves(shape) -> list:
    """The solids of a boolean result, without the slivers that have no volume."""
    if shape is None:
        return []
    return [solid for solid in shape.solids() if solid.volume > EPS_MM3]


def _facts(shape, bodies: int) -> dict:
    box = shape.bounding_box()
    return {
        "bbox": {"min": [box.min.X, box.min.Y, box.min.Z], "max": [box.max.X, box.max.Y, box.max.Z]},
        "volume_mm3": float(sum(solid.volume for solid in shape.solids())),
        "bodies": bodies,
    }


def compare(older: Path, newer: Path, out: Path) -> dict:
    """The comparison of two STEP files, writing ``out/what-changed.step`` when there is a difference to show."""
    from build123d import Color, Compound, export_step

    (old, old_bodies), (new, new_bodies) = _load(older), _load(newer)
    kept, added, removed = _leaves(old & new), _leaves(new - old), _leaves(old - new)
    kept_mm3 = float(sum(solid.volume for solid in kept))
    added_mm3 = float(sum(solid.volume for solid in added))
    removed_mm3 = float(sum(solid.volume for solid in removed))
    same = added_mm3 + removed_mm3 < 1e-3
    volume_old, volume_new = old.volume, new.volume
    similar = abs(volume_old - volume_new) <= 0.1 * max(volume_old, volume_new)
    # Only moved: little overlap AND a similar size. A heavy edit (another volume) is a real change.
    moved = (not same) and similar and kept_mm3 < 0.5 * min(volume_old, volume_new)
    result = {
        "same": same,
        "moved": moved,
        "added_mm3": added_mm3,
        "removed_mm3": removed_mm3,
        "kept_mm3": kept_mm3,
        "older": _facts(old, old_bodies),
        "newer": _facts(new, new_bodies),
        "diff": None,
    }
    if same or moved:
        return result
    # One child per kind, so the tree reads Unchanged, Added and Removed once each. The colour goes on
    # every leaf solid: a colour on a group compound does not reach the renderer.
    groups = []
    for parts, rgba, label in ((kept, UNCHANGED, "Unchanged"), (added, ADDED, "Added"), (removed, REMOVED, "Removed")):
        for solid in parts:
            solid.color = Color(*rgba)
            solid.label = label
        if parts:
            groups.append(Compound(children=parts, label=label))
    out.mkdir(parents=True, exist_ok=True)
    written = out / "what-changed.step"
    export_step(Compound(children=groups, label="What changed"), str(written))
    result["diff"] = written.name
    return result


def _tree(repository: Path, version: str, into: Path) -> None:
    """The repository's files as a version had them, written into ``into``: a commit's tree, or for
    ``now`` the files on disk that git would keep (``.studio`` left out)."""
    from cad.edit.versions import NOW, _git

    if version != NOW:
        archive = _git(repository, "archive", "--format=tar", version)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(into, filter="data")
        return
    listed = _git(repository, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for name in filter(None, listed.decode("utf-8").split("\0")):
        source = repository / name
        if ".studio" in Path(name).parts or not source.is_file():
            continue
        (into / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, into / name)


def build(repository: Path, script: str, version: str, name: str, step: Path, side: str) -> None:
    """Model ``name`` of ``script`` (its path in the repository) built as ``version`` had it, written
    to ``step``. It is built from a scratch copy of that version's files, so it runs that version's
    code (the modules beside it too) and writes none of its outputs into the project. ``side``
    ("older" or "newer") names the version in a failure."""
    from cad.engine.api import export
    from cad.engine.build import load_script
    from cad.engine.model import models_in

    step.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="studio-version-") as scratch:
        tree = Path(scratch).resolve()
        _tree(repository, version, tree)
        path = tree / script
        if not path.is_file():
            raise ValueError(f"the {side} version has no {Path(script).name}")
        try:
            module = load_script(path)
        except Exception as error:  # noqa: BLE001 - the script's own failure, said as its
            raise ValueError(f"the {side} version's {path.name} failed: {error}") from error
        found = [model for model in models_in(vars(module), path) if name in (model.name, model.explicit_name)]
        if not found:
            raise ValueError(f"the {side} version's {path.name} has no model named {name}")
        try:
            export(found[0], step, daemon=False)
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"the {side} version's {name} did not build: {error}") from error


def _write(path: Path, payload: dict) -> None:
    """Write the result whole or not at all: a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}")
    partial.write_text(json.dumps(payload), encoding="utf-8")
    replace_atomic(partial, path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    model = args[:1] == ["--model"]
    if len(args) != (7 if model else 3):
        print("usage: python -m cad.edit.solid_diff OLDER.step NEWER.step OUT_DIR\n"
              "       python -m cad.edit.solid_diff --model NAME REPOSITORY SCRIPT OLDER NEWER OUT_DIR", file=sys.stderr)
        return 2
    out = Path(args[-1])
    older, newer = (out / "older.step", out / "newer.step") if model else (Path(args[0]), Path(args[1]))
    try:
        if model:
            name, repository, script = args[1], Path(args[2]), args[3]
            out.mkdir(parents=True, exist_ok=True)
            for side, version, step in (("older", args[4], older), ("newer", args[5], newer)):
                build(repository, script, version, name, step, side)
        result = compare(older, newer, out)
    except (ImportError, MemoryError, OSError) as error:
        result = {"error": str(error) or type(error).__name__, "environment": True}
    except Exception as error:  # noqa: BLE001 - the geometry's failure, said in the result
        result = {"error": str(error) or type(error).__name__, "environment": False}
    _write(out / "result.json", result)
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
