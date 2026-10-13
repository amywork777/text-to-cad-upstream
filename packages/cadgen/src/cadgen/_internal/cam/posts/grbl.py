"""``grbl``: GRBL 1.1 (hobby mills, routers, diode and CO2 lasers on GRBL boards).

GRBL has no tool changer and no canned cycles: a tool change is a spindle stop, a comment naming the tool and an
``M0`` pause (the first tool is a comment to load it); drilling cycles post as their expanded moves. Arcs are G2/G3
with I/J, helical with Z. Dwell ``G4 P`` is in seconds. Coolant M8 (flood) and M7 (mist; air maps to M7). A laser's
beam is ``M4`` (dynamic power, off during rapids) with ``S`` out of GRBL's default ``$30=1000``.
"""

from __future__ import annotations

from cadgen._internal.cam.posts.base import Post

__all__ = ["GrblPost"]


class GrblPost(Post):
    name = "grbl"
    kinds = ("mill", "router", "laser")
    extension = ".nc"
    plain = "GRBL 1.1"
    accepts_arcs = True
    canned_cycles = frozenset()
    tool_changer = False

    def preamble(self, program):
        return ["G90 G94 G17 G21"]

    def on_beam(self, data, program):
        if not data.get("on"):
            return ["M5"]
        lines = [f"M4 S{self.num(round(1000 * float(data.get('power', 1.0))))}"]
        if data.get("pierce_s"):
            lines.append(f"G4 P{self.num(float(data['pierce_s']))}")
        return lines

    def footer(self, program):
        return ["M5", "M9", "M2"]
