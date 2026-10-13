"""``fanuc``: Fanuc 0i/30i-style controls (``.nc``) for mills, 4th/5th-axis mills and lathes.

The program sits between ``%`` lines under an ``O`` number (``machine.program_number``, default 1000), comments are
upper case, and every dimension word carries a decimal point (a Fanuc reads ``X10`` as 10 microns).

Mill: ``G21``, a safe-start block, ``G54``..``G59``, ``M5 M9`` and ``G91 G28 Z0.`` then ``T M6``, ``G0 X Y`` over the
first point and ``G43 H`` at a clearance Z,
G2/G3 with I/J, M8/M7/M9, the canned cycles G81 G82 G83 G73 G84 (``M29 S`` rigid tapping; G74 left hand) G85 G86 G89
and G76 fine boring, dwell ``G4 P`` in milliseconds, ``M30``. A 3+2 setup enters the tilted working plane with
``G68.2`` (ZXZ angles of the setup's frame) and ``G53.1`` after each tool change and leaves it with ``G69``;
simultaneous moves post their A/B/C words under ``G43.4`` tool centre point control (rotary axes first, then
``G43.4 H``, then X Y, then Z; drilling posts expanded there). At the end Z goes home, then the table to rotary zero
(``G91 G28 A0. C0.``).

Lathe (G-code system A): ``G18``, diameter X, ``G28 U0. W0.`` before ``T0101``-style tool words, ``G50 S`` clamp
with ``G96`` constant surface speed or ``G97`` rpm, ``G98``/``G99`` feed per minute/revolution, the two-block ``G76``
thread, and the two-block ``G71`` roughing cycle with its profile blocks when ``machine.cycles`` is true (expanded
otherwise). No G90 on the lathe: in system A it is a turning cycle.
"""

from __future__ import annotations

from cadgen._internal.cam.posts._iso import CYCLES_OPTION, IsoPost
from cadgen._internal.cam.posts.base import Program

__all__ = ["FanucPost"]

PROGRAM_NUMBER = {"type": "number", "default": 1000, "minimum": 1,
                  "help": "the O number the program is stored under"}


class FanucPost(IsoPost):
    name = "fanuc"
    kinds = ("mill", "mill4", "mill5", "lathe")
    extension = ".nc"
    plain = "Fanuc"
    decimal_point = True
    program_wrap = True
    upper_comments = True
    mill_tool_home = ("G91 G28 Z0.", "G90")
    mill_end_home = ("G91 G28 Z0.", "G90")
    index_home_lines = ("G91 G28 Z0.", "G90")
    lathe_home = ("G28 U0. W0.",)
    tilt_style = "g68_2"
    tcp_code = "G43.4"
    rigid_tap_m29 = True
    dwell_ms = True
    lathe_feed_codes = ("G98", "G99")
    native_rough = True
    options = {"cycles": CYCLES_OPTION, "program_number": PROGRAM_NUMBER}

    def preamble(self, program: Program) -> list[str]:
        if self._lathe:
            return ["G21", "G0 G18 G40 G80 G98"]
        return ["G21", "G0 G17 G40 G49 G80 G90 G94"]
