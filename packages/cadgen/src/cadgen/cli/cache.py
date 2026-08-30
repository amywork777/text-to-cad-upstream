"""``cadgen cache`` — inspect and garbage-collect the user-level caches.

The tiers all live under one root (``cadgen._internal.cache_paths``:
``CADGEN_CACHE_DIR``, else the platform cache dir, else ``~/.cache/cadgen``):

- ``components/`` — exact-geometry component store. The version salt is hashed
  INTO the cid, so dead generations are indistinguishable by name; age is the
  only signal.
- ``opmemo/`` — kernel-op memo, one subdirectory per salt generation
  (``v<opmemo-version>-b123d<build123d-version>``). Dead generations ARE
  identifiable by name.
- ``meshes/`` — shared tessellation cache; keys carry
  ``-t<tessellator-version>-``, so dead generations are identifiable by name
  (including legacy keys that predate the salt).

There is deliberately NO automatic or background GC: this command is the only
sweeper, run by a user or agent. Deletion is safe under concurrent producers
by construction — every entry is content-addressed and best-effort, so a
reader racing a deletion simply re-misses and rebuilds, and a producer racing
one re-publishes. Nothing here takes a lock.

Grows-forever context: every ``CACHE_SCHEMA_VERSION`` bump re-keys the
component store wholesale, every op-memo/build123d version bump starts a fresh
opmemo generation, and every ``TESSELLATION_VERSION`` bump orphans the mesh
tier's previous keys. Nothing else ever deletes those orphans.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from cadgen._internal.cache_paths import (
    MESH_TESSELLATION_VERSION,
    cache_root,
    components_dir,
    locks_dir,
    meshes_dir,
    opmemo_base_dir,
    packages_dir,
    records_dir,
)

# Matches the -t<version>- salt in a mesh entry name (key scheme home:
# packages/cadjs/src/lib/surf/tessellationCache.js).
_MESH_VERSION_RE = re.compile(r"-t(\d+)-l")

# Crash leftovers from atomic writes (tmp + rename): collectable once clearly
# abandoned. One hour is far beyond any single write.
_TMP_LEFTOVER_SECONDS = 60 * 60


def _opmemo_current_salt() -> str:
    """The live opmemo generation's directory name.

    Reads the build123d version from installed metadata instead of importing
    the module (which costs seconds of OCP import). op_memo itself uses
    ``build123d.__version__`` at runtime; the two agree for any normal
    install, and the worst case of a mismatch is deleting a still-live
    generation — a rebuild cost, never a correctness problem (best-effort
    cache).
    """
    from cadgen._internal.op_memo import _OP_MEMO_VERSION

    try:
        from importlib import metadata

        version = metadata.version("build123d")
    except Exception:  # noqa: BLE001 - absent metadata mirrors op_memo's fallback
        version = "unknown"
    return f"v{_OP_MEMO_VERSION}-b123d{version}"


@dataclass
class _TierReport:
    name: str
    path: str
    entries: int = 0
    bytes: int = 0
    generations: list[dict] = field(default_factory=list)
    notes: str = ""


def _dir_stats(path: Path) -> tuple[int, int]:
    entries = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            entries += 1
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass  # racing deletion: fine
    return entries, total


def _mesh_entry_dead(name: str) -> bool:
    """Dead by NAME: wrong/missing tessellator version, or an abandoned tmp."""
    if name.endswith(".tmp"):
        return False  # age-gated separately
    if not name.endswith(".tess"):
        return True  # foreign leftovers in a cache dir are collectable
    match = _MESH_VERSION_RE.search(name)
    return match is None or int(match.group(1)) != MESH_TESSELLATION_VERSION


def _package_generation(name: str) -> str:
    """The version salt of a package dir name (``<hash>-v<N>`` -> ``v<N>``)."""
    idx = name.rfind("-v")
    return name[idx + 1 :] if idx != -1 else "unsalted"


def _scan() -> list[_TierReport]:
    from cadgen._internal.cache_schema import CACHE_SCHEMA_VERSION

    reports: list[_TierReport] = []

    pkg = _TierReport("packages", str(packages_dir()))
    if packages_dir().is_dir():
        current = f"v{CACHE_SCHEMA_VERSION}"
        by_generation: dict[str, dict] = {}
        for child in sorted(packages_dir().iterdir()):
            if not child.is_dir():
                continue
            entries, size = _dir_stats(child)
            pkg.entries += entries
            pkg.bytes += size
            generation = _package_generation(child.name)
            bucket = by_generation.setdefault(
                generation,
                {"name": generation, "entries": 0, "bytes": 0, "dead": generation != current},
            )
            bucket["entries"] += entries
            bucket["bytes"] += size
        pkg.generations = list(by_generation.values())
        pkg.notes = (
            f"current generation: {current}; a package whose document changed is "
            "orphaned by key and age-swept; re-import self-heals in seconds"
        )
    reports.append(pkg)

    comp = _TierReport("components", str(components_dir()))
    if components_dir().is_dir():
        comp.entries, comp.bytes = _dir_stats(components_dir())
    comp.notes = "version salt is hashed into the cid; age-swept only"
    reports.append(comp)

    op = _TierReport("opmemo", str(opmemo_base_dir()))
    if opmemo_base_dir().is_dir():
        current = _opmemo_current_salt()
        for child in sorted(opmemo_base_dir().iterdir()):
            if not child.is_dir():
                continue
            entries, size = _dir_stats(child)
            op.entries += entries
            op.bytes += size
            op.generations.append({
                "name": child.name,
                "entries": entries,
                "bytes": size,
                "dead": child.name != current,
            })
        op.notes = f"current generation: {current}"
    reports.append(op)

    mesh = _TierReport("meshes", str(meshes_dir()))
    if meshes_dir().is_dir():
        live = {"name": f"t{MESH_TESSELLATION_VERSION}", "entries": 0, "bytes": 0, "dead": False}
        dead = {"name": "older/unsalted keys", "entries": 0, "bytes": 0, "dead": True}
        for child in meshes_dir().iterdir():
            if not child.is_file():
                continue
            try:
                size = child.stat().st_size
            except OSError:
                continue
            mesh.entries += 1
            mesh.bytes += size
            bucket = dead if _mesh_entry_dead(child.name) else live
            bucket["entries"] += 1
            bucket["bytes"] += size
        mesh.generations = [live, dead]
    reports.append(mesh)
    return reports


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def _cmd_info(as_json: bool) -> int:
    reports = _scan()
    if as_json:
        print(json.dumps({
            "root": str(cache_root()),
            "tiers": [report.__dict__ for report in reports],
        }))
        return 0
    print(f"cache root: {cache_root()}")
    for report in reports:
        print(f"\n{report.name}  ({report.path})")
        print(f"  entries: {report.entries}   size: {_human(report.bytes)}")
        if report.notes:
            print(f"  {report.notes}")
        for generation in report.generations:
            marker = "DEAD" if generation["dead"] else "live"
            print(
                f"    [{marker}] {generation['name']}: "
                f"{generation['entries']} entries, {_human(generation['bytes'])}"
            )
    return 0


def _remove_file(path: Path, dry_run: bool, stats: dict) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return  # racing deletion: already gone
    if not dry_run:
        try:
            path.unlink()
        except OSError:
            return
    stats["entries"] += 1
    stats["bytes"] += size


def _remove_tree(path: Path, dry_run: bool, stats: dict) -> None:
    entries, size = _dir_stats(path)
    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)
    stats["entries"] += entries
    stats["bytes"] += size


def _sweep_files(directory: Path, cutoff: float, dry_run: bool, stats: dict, *, everything: bool) -> None:
    if not directory.is_dir():
        return
    for child in directory.iterdir():
        if not child.is_file():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        stale_tmp = child.name.endswith(".tmp") and mtime < time.time() - _TMP_LEFTOVER_SECONDS
        if everything or stale_tmp or mtime < cutoff:
            _remove_file(child, dry_run, stats)


def _cmd_gc(max_age_days: float, delete_all: bool, dry_run: bool, as_json: bool) -> int:
    from cadgen._internal.cache_schema import CACHE_SCHEMA_VERSION

    cutoff = time.time() - max_age_days * 24 * 3600
    stats = {"entries": 0, "bytes": 0}

    # Packages sweep FIRST (tier ordering: evict packages before components —
    # a package rebuilds from finer tiers in seconds, so it is the cheapest
    # loss). Dead-by-salt generations go outright; live-generation packages
    # (orphans included — the key alone cannot say which document still
    # exists) are age-swept by the package dir's own mtime.
    if packages_dir().is_dir():
        current = f"v{CACHE_SCHEMA_VERSION}"
        for child in packages_dir().iterdir():
            if not child.is_dir():
                continue
            if delete_all or _package_generation(child.name) != current:
                _remove_tree(child, dry_run, stats)
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    _remove_tree(child, dry_run, stats)
            except OSError:
                continue
    # Locks/records are tiny bookkeeping; age-sweep keeps the tiers bounded.
    _sweep_files(locks_dir(), cutoff, dry_run, stats, everything=delete_all)
    _sweep_files(records_dir(), cutoff, dry_run, stats, everything=delete_all)

    # Dead-by-name generations go outright, regardless of age.
    if opmemo_base_dir().is_dir():
        current = _opmemo_current_salt()
        for child in opmemo_base_dir().iterdir():
            if child.is_dir() and (delete_all or child.name != current):
                _remove_tree(child, dry_run, stats)
        if not delete_all:
            _sweep_files(opmemo_base_dir() / current, cutoff, dry_run, stats, everything=False)
    if meshes_dir().is_dir():
        for child in meshes_dir().iterdir():
            if child.is_file() and (delete_all or _mesh_entry_dead(child.name)):
                _remove_file(child, dry_run, stats)
        if not delete_all:
            _sweep_files(meshes_dir(), cutoff, dry_run, stats, everything=False)

    # The component store has no name-visible generations: age sweep only.
    _sweep_files(components_dir(), cutoff, dry_run, stats, everything=delete_all)

    verb = "would free" if dry_run else "freed"
    if as_json:
        print(json.dumps({"dryRun": dry_run, **stats}))
    else:
        print(f"{verb} {_human(stats['bytes'])} across {stats['entries']} entries")
    return 0


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog or "cadgen cache",
        description="Inspect or garbage-collect cadgen's user-level caches.",
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    info = sub.add_parser("info", help="per-tier sizes, entry counts, and dead generations")
    info.add_argument("--json", action="store_true")
    gc = sub.add_parser("gc", help="delete dead generations; age-sweep live entries")
    gc.add_argument(
        "--max-age-days",
        type=float,
        default=30.0,
        help="age-sweep live entries older than this (default 30); dead generations go regardless",
    )
    gc.add_argument("--all", action="store_true", help="delete everything, current generations included")
    gc.add_argument("--dry-run", action="store_true", help="report what gc would delete, delete nothing")
    gc.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    args = build_parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    if args.verb == "info":
        return _cmd_info(args.json)
    return _cmd_gc(args.max_age_days, args.all, args.dry_run, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
