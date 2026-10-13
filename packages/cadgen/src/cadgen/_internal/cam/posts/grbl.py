"""``grbl``: GRBL 1.1 (hobby mills, routers, diode and CO2 lasers on GRBL boards).

GRBL has no tool changer, no tool-length table and no canned cycles. An ``M0`` tool change cannot work on it: in the
Hold state an ``M0`` leaves, GRBL will not jog or probe, so the new tool cannot be touched off, and with no table the
next, longer tool would rapid into the stock. So a mill or router setup that uses more than one tool is posted one
file per tool (``split_by_tool``, :meth:`~cadgen._internal.cam.posts.base.Post.render_tool_files`): each a complete
program that names its tool and says "file k of n: load T2, zero Z on the stock top, then run", carries the coolant
in effect, and starts safe (Z up to the clearance height, then X Y, then down). :meth:`GrblPost.render` refuses a
multi-tool setup in one file. Drilling cycles post as their expanded moves. Arcs are G2/G3 with I/J, helical with Z.
Dwell ``G4 P`` is in seconds. ``M3`` has no spindle-at-speed feedback on GRBL, so every spindle start from standstill
is followed by ``G4 P<machine.spindle_spinup_s>`` (3 s by default) before the tool may cut. Coolant M8 (flood); stock
GRBL builds have no M7, so mist and air both map to M8.

A laser's beam is ``M4`` (dynamic power: off while stationary and during rapids, scaled with speed) with ``S`` out of
GRBL's default ``$30=1000``. Because M4 fires nothing while the head is still, a pierce dwell is fired in ``M3``
(constant power, which in laser mode fires at once) and the cut switches back to ``M4``: ``M3 S.. / G4 P.. / M4 S..``.
A laser's tool events are beam settings, not tools: a laser program is never split.
"""

from __future__ import annotations

from cadgen._internal.cam.job_errors import CamJobError
from cadgen._internal.cam.posts.base import Post, Program

__all__ = ["GrblPost"]


class GrblPost(Post):
    name = "grbl"
    kinds = ("mill", "router", "laser")
    extension = ".nc"
    plain = "GRBL 1.1"
    accepts_arcs = True
    canned_cycles = frozenset()
    tool_changer = False
    split_by_tool = True
    options = {
        "spindle_spinup_s": {"type": "number", "default": 3.0,
                             "help": "seconds to dwell after the spindle starts, before the tool cuts (GRBL does not "
                                     "wait for the spindle to reach speed)"},
    }

    def render(self, program: Program) -> str:
        if program.machine.kind != "laser" and len(self.tool_programs(program)) > 1:
            raise CamJobError(f"setup {program.setup.id}: GRBL cannot change tools inside one program (no tool table, "
                              "and it cannot jog to touch off a tool after M0); post the setup one file per tool "
                              "(render_tool_files)")
        return super().render(program)

    def tool_programs(self, program):
        pieces = super().tool_programs(program)
        return [(pieces[0][0], program)] if program.machine.kind == "laser" else pieces

    def preamble(self, program):
        return ["G90 G94 G17 G21"]

    def on_tool(self, data, program, first):
        tool = program.tools[data["tool"]]
        if program.machine.kind == "laser":
            return [self.comment(f"Beam: {self.tool_label(tool)}")]
        return [self.comment(f"Load {self.tool_label(tool)}")]

    def tool_change_height(self, program):
        # Every file starts with Z up at the clearance height in the work frame, before the spindle starts. Not
        # G53 (machine coordinates): they mean something only on a machine that homes ($22=1), and without homing
        # GRBL's machine zero is wherever it was switched on. The work Z was just zeroed on the setup's Z zero with
        # this tool, so the clearance height is above the stock and the clamps whatever the machine.
        return None if program.machine.kind == "laser" else float(program.clearance_z)

    def spinup(self, program):
        seconds = float(self.option(program, "spindle_spinup_s"))
        return [f"G4 P{self.num(seconds)}"] if seconds > 0 and program.machine.kind != "laser" else []

    def on_coolant(self, data, program):
        # Stock GRBL 1.1 has no M7 (it is a compile-time option): mist and air both run the one coolant output.
        return [{"flood": "M8", "mist": "M8", "air": "M8", "off": "M9"}[data.get("mode", "off")]]

    def on_beam(self, data, program):
        if not data.get("on"):
            return ["M5"]
        power = self.num(round(1000 * float(data.get("power", 1.0))))
        if data.get("pierce_s"):
            # M4 fires nothing while the head is still: pierce at constant power, then cut in dynamic mode.
            return [f"M3 S{power}", f"G4 P{self.num(float(data['pierce_s']))}", f"M4 S{power}"]
        return [f"M4 S{power}"]

    def footer(self, program):
        return ["M5"] + (["M9"] if self.coolant_on() else []) + ["M2"]
