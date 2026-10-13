"""The findings shape every CAM check writes, and the context a check reads.

A finding is a dict in the KiCad/FEA shape, so an agent reads CAM, FEA and board findings alike::

    {"check": "reach", "severity": "error" | "warning" | "info", "type": "reach_flutes",
     "summary": "Tool too long for this pocket: ...", "description": "...", "items": [{...}, ...]}

``check`` is the check's registry name (spec section 9); ``type`` the specific kind within it. ``items`` locate it:
each item may carry ``setup`` (id), ``operation`` (the global operation index the viewer's rows use), ``at`` (a
point in part mm) and numbers. :func:`by_severity` sorts errors first.

:class:`CheckContext` is what every check reads: the job, the part, the stock and its simulator's reports, and per
setup (:class:`SetupPlan`) its WCS, heights, toolpath (WCS) and part sections; per operation (:class:`OpPlan`) its
spec, tool, feeds, plan facts (``meta``) and times. A check is ``run(ctx) -> list[finding]``. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["CheckContext", "OpPlan", "SetupPlan", "by_severity", "finding", "xyz"]

_SEVERITY = {"error": 0, "warning": 1, "info": 2}


def finding(check: str, severity: str, kind: str, summary: str, description: str = "", items=()) -> dict:
    if severity not in _SEVERITY:
        raise ValueError(f"severity {severity!r} is not error, warning or info")
    return {"check": check, "severity": severity, "type": kind, "summary": summary, "description": description,
            "items": list(items)}


def by_severity(found) -> list[dict]:
    """Errors first, then warnings, then notes; stable within each."""
    return sorted(found, key=lambda item: _SEVERITY[item["severity"]])


def xyz(point, digits: int = 3) -> list[float]:
    return [round(float(c), digits) + 0.0 for c in point]


@dataclass
class OpPlan:
    """One planned operation, as the checks, the results and the GLB read it."""

    index: int                      # global, in program order across setups
    setup: str
    spec: Any                       # job.OpSpec
    operation: Any                  # operations.base.Operation
    tool: Any                       # tools.Tool | None
    feeds: Any                      # feeds.Feeds | None
    params: Any = None
    meta: dict = field(default_factory=dict)
    summary: str = ""
    time_s: float = 0.0
    t0: float = 0.0                 # program time, s, across setups
    t1: float = 0.0
    #: Its moves in its setup's toolpath: ``[start, end)``.
    start: int = 0
    end: int = 0


@dataclass
class SetupPlan:
    setup: Any                      # job.Setup
    wcs: Any                        # wcs.WCS
    heights: Any                    # linking.Heights
    toolpath: Any = None            # ir.Toolpath, WCS
    sections: Any = None            # geom2d.Sections of the part in this WCS
    t0: float = 0.0
    time_s: float = 0.0


@dataclass
class CheckContext:
    job: Any
    part: Any
    stock: Any                      # stock.StockGeometry
    sim: Any                        # the StockSim after every setup
    sim_reports: dict               # setup id -> stock.SimReport
    setups: list                    # [SetupPlan]
    ops: list                       # [OpPlan]
    tolerance_mm: float
    logger: Any = None

    def setup_plan(self, setup_id: str) -> SetupPlan:
        return next(plan for plan in self.setups if plan.setup.id == setup_id)

    def ops_in(self, setup_id: str) -> list:
        return [op for op in self.ops if op.setup == setup_id]
