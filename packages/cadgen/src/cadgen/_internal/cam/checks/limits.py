"""``limits``: a feed or spindle speed the machine clamped (each clamp the feeds rules reported)."""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding

__all__ = ["run"]


def run(ctx) -> list[dict]:
    out = []
    for op in ctx.ops:
        for note in getattr(op.feeds, "clamped", ()) or ():
            out.append(finding("limits", "warning", "limits", f"{op.summary}: {note}",
                               "the machine's max_rpm or max_feed_mm_min held the starting point back; the cut is "
                               "slower than the table suggests", [{"setup": op.setup, "operation": op.index}]))
    return out
