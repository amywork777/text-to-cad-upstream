"""Engineering drawing of the perforated plate: a hole table instead of callouts.

Run `python perforated_plate.py` first; this script documents the STEP it writes.
The sheet chooses its own size and scale, the holes and slot are tagged and
tabulated from the part, and the corner radius is stated by a general note read
off the part, so none of those numbers is typed here.
"""

from pathlib import Path

import cadgen
from cadgen.eng_drawing import Sheet, eng_drawing, geometry_notes

STEP = Path(__file__).parent / "../STEP/perforated_plate.step"


@eng_drawing(out="../PDF/perforated_plate_drawing.pdf")
def perforated_plate_drawing():
    part = cadgen.read_step(STEP)
    sheet = Sheet(size=None, scale=None, title="PERFORATED PLATE", part_number="PP-160", revision="A",
                  author="text-to-cad", general_tolerance="ISO 2768-m", notes=geometry_notes(part))
    top, front, _right = sheet.three_views(part)
    top.overall()
    top.hole_table()                    # every hole and the slot, tagged, measured from the corner
    front.overall(width=False)
    return sheet


if __name__ == "__main__":
    perforated_plate_drawing()
