"""Engineering drawing of the angle bracket: an auxiliary view of its inclined tab.

Run `python angle_bracket.py` first; this script documents the STEP it writes. No
principal view shows the tab's face or its hole true, so VIEW C looks square onto
it, and the hole in it is called out there, read off the part.
"""

from pathlib import Path

import cadgen
from angle_bracket import TAB_FACE_POINT
from cadgen.eng_drawing import Sheet, eng_drawing

STEP = Path(__file__).parent / "../STEP/angle_bracket.step"


@eng_drawing(out="../PDF/angle_bracket_drawing.pdf")
def angle_bracket_drawing():
    part = cadgen.read_step(STEP)
    sheet = Sheet(size=None, scale=None, title="ANGLE BRACKET", part_number="AB-030", revision="A",
                  author="text-to-cad", general_tolerance="ISO 2768-m")
    top, front, right, iso = sheet.three_views(part, iso=True)
    top.overall()
    top.holes()
    front.overall(width=False)
    tab = sheet.auxiliary(front, TAB_FACE_POINT)   # VIEW C, square onto the tab
    tab.holes()
    return sheet


if __name__ == "__main__":
    angle_bracket_drawing()
