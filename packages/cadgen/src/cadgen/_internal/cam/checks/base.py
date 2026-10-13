"""The findings shape every CAM check writes, and the context a check reads.

A finding is a dict in the KiCad/FEA shape, so an agent reads CAM, FEA and board findings alike::

    {"check": "reach", "severity": "error" | "warning" | "info", "type": "reach_flutes",
     "summary": "Tool too long for this pocket: ...", "description": "...", "items": [{...}, ...]}

``check`` is the check's registry name (spec section 9); ``type`` the specific kind within it. ``items`` locate it:
each item may carry ``setup`` (id), ``operation`` (the global operation index the viewer's rows use), ``at`` (a
point in part mm) and numbers. :func:`by_severity` sorts errors first. Stdlib only.
"""

from __future__ import annotations

__all__ = ["by_severity", "finding", "xyz"]

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
