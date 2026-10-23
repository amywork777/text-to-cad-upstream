"""Assembly drawing of the motorcycle shock absorber: a general arrangement and a
sheet for each part.

Run `python motorcycle_shock_absorber.py` first; this script documents the STEP
it writes. The parts list is read off that STEP. The model names its two mounting
eyes apart (lower, upper), so they arrive as two items; they are one part, made
twice, and merge() lists them as one after checking their shapes are the same.
The general arrangement balloons each
part where it is first seen; each part's sheet is a first pass at its views,
overall sizes and holes, and the run prints what each sheet still leaves
unstated.
"""

from pathlib import Path

import cadgen
from cadgen.eng_drawing import assembly_sheets, eng_drawing, parts_list

STEP = Path(__file__).parent / "../../STEP/motorcycle_shock_absorber/motorcycle_shock_absorber.step"


@eng_drawing(out="../../PDF/motorcycle_shock_absorber/motorcycle_shock_absorber_drawing.pdf")
def motorcycle_shock_absorber_drawing():
    parts = parts_list(cadgen.read_scene(STEP))
    parts.merge("mounting_eye:lower", "mounting_eye:upper")
    return assembly_sheets(parts, title="MOTORCYCLE SHOCK ABSORBER", part_number="MSA-100", revision="A",
                           author="text-to-cad", general_tolerance="ISO 2768-m")


if __name__ == "__main__":
    motorcycle_shock_absorber_drawing()
