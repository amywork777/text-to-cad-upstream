"""Every analysis ``cadgen fea`` knows, by name. A study names one (``analysis``; ``static`` when it names none);
any other name is an error listing these. Stdlib only: the modules import lazily.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cadgen._internal.fea.analyses.base import Tier

if TYPE_CHECKING:
    from cadgen._internal.fea.analyses.base import Analysis

__all__ = ["ANALYSIS_NAMES", "DEFAULT_ANALYSIS", "Entry", "REGISTRY", "get_analysis"]

DEFAULT_ANALYSIS = "static"


@dataclass(frozen=True)
class Entry:
    name: str
    tier: Tier
    module: str            # "cadgen._internal.fea.analyses.static"
    cls: str               # "StaticAnalysis"
    word: str


REGISTRY: dict[str, Entry] = {entry.name: entry for entry in (
    Entry("static", 1, "cadgen._internal.fea.analyses.static", "StaticAnalysis", "Strength"),
)}
ANALYSIS_NAMES: tuple[str, ...] = tuple(REGISTRY)

_INSTANCES: dict[str, "Analysis"] = {}


def get_analysis(name: str) -> "Analysis":
    """The analysis class's instance. An unknown name: ValueError listing ANALYSIS_NAMES."""
    if name in _INSTANCES:
        return _INSTANCES[name]
    entry = REGISTRY.get(name) if isinstance(name, str) else None
    if entry is None:
        raise ValueError(f"analysis: {name!r} is not an analysis cadgen knows; use one of {', '.join(ANALYSIS_NAMES)}")
    instance = getattr(importlib.import_module(entry.module), entry.cls)()
    _INSTANCES[name] = instance
    return instance
