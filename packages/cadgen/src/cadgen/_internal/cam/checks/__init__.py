"""Every check a CAM plan runs (spec section 9), by name: built, or registered and skipped until its module lands.

The registry pre-lists every check with its level and a lazy ``"module:function"``; :func:`run_checks` imports each
one whose module this cadgen has and calls ``run(ctx: CheckContext) -> list[finding]`` (the dict shape in
:mod:`.base`). A check whose module is absent is skipped and named in the result's ``skipped`` list, never an error:
adding a check is adding its module. Error-level findings make the verdict "N to fix"; warnings do not.

Stdlib only at import.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass

from cadgen._internal.cam.checks.base import by_severity

__all__ = ["CHECK_NAMES", "Entry", "REGISTRY", "run_checks"]

_PACKAGE = "cadgen._internal.cam.checks"


@dataclass(frozen=True)
class Entry:
    name: str
    level: str          # the level its findings usually carry: "error" | "warning"
    target: str         # "cadgen._internal.cam.checks.reach:run"
    plain: str


def _entry(name: str, level: str, plain: str) -> Entry:
    return Entry(name, level, f"{_PACKAGE}.{name}:run", plain)


REGISTRY: tuple[Entry, ...] = (
    _entry("gouge", "error", "a feed move cuts into the part beyond tolerance"),
    _entry("holder_collision", "error", "the holder or shank above the flutes touches stock or part"),
    _entry("reach", "error", "the cut is deeper than the flutes or the stickout"),
    _entry("rapid_into_stock", "error", "a rapid move passes through uncut stock"),
    _entry("travel", "error", "the path leaves the machine's travel"),
    _entry("corner_radius", "warning", "an inside corner is tighter than the tool's radius"),
    _entry("material_left", "warning", "stock is left above the part after every operation"),
    _entry("fixture", "error", "a move enters a fixture keep-out"),
    _entry("limits", "warning", "a feed or speed was clamped by the machine"),
    _entry("machine", "error", "an operation needs an axis the machine does not have"),
)
CHECK_NAMES = tuple(entry.name for entry in REGISTRY)


def available(entry: Entry) -> bool:
    return importlib.util.find_spec(entry.target.split(":")[0]) is not None


def run_checks(ctx) -> tuple[list[dict], list[str], list[str]]:
    """``(findings errors first, checks run, checks skipped)``."""
    found: list[dict] = []
    ran, skipped = [], []
    for entry in REGISTRY:
        if not available(entry):
            skipped.append(entry.name)
            continue
        module, function = entry.target.split(":")
        found.extend(getattr(importlib.import_module(module), function)(ctx))
        ran.append(entry.name)
    return by_severity(found), ran, skipped
