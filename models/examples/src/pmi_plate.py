from __future__ import annotations

# Prompt: A 100 x 60 x 10 mm plate with a 10 mm through-hole at its centre, carrying semantic PMI:
# datums A (bottom), B (front side) and C (left side), the plate's thickness and the hole's
# diameter with explicit tolerances, the top's flatness, and the hole's position to A|B|C, its true
# position located by basic dimensions from B and C.
#
# Every tolerance value below is ILLUSTRATIVE: chosen to exercise the PMI export, not taken from
# any drawing, standard or process capability. Do not manufacture to them.

import build123d as bd

from cadgen.engine import materials, pmi, step, xbf


@xbf(out="../XBF/pmi_plate.xbf")
@step(out="../XBF/pmi_plate.step")
def pmi_plate():
    body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
    body.label = "plate"
    body.material = materials.aluminium_6061
    bottom = body.faces().sort_by(bd.Axis.Z)[0]
    top = body.faces().sort_by(bd.Axis.Z)[-1]
    front = body.faces().sort_by(bd.Axis.Y)[0]
    left = body.faces().sort_by(bd.Axis.X)[0]
    hole = body.faces().filter_by(bd.GeomType.CYLINDER)[0]
    return pmi.annotate(
        body,
        pmi.datum("A", bottom, presentation=pmi.place((40, -20, -5), (0, -15, -10))),
        pmi.datum("B", front, presentation=pmi.place((40, -30, 0), (0, -15, 0))),
        pmi.datum("C", left, presentation=pmi.place((-50, 20, 0), (-15, 0, 0))),
        # Illustrative: 10 +/-0.2.
        pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus(0.2),
                     presentation=pmi.place((50, 30, 0), (15, 0, 0))),
        # Illustrative: diameter 10 +0.1/0.
        pmi.diameter("hole-diameter", hole, tolerance=pmi.plus_minus(0.1, 0),
                     presentation=pmi.place((5, 0, 5), (15, 15, 0))),
        # Illustrative: flatness 0.05.
        pmi.flatness("top-flatness", top, 0.05, presentation=pmi.place((-30, 20, 5), (0, 15, 0))),
        # Illustrative: position diameter 0.1 to A|B|C.
        pmi.position("hole-position", hole, 0.1, datums=["A", "B", "C"],
                     presentation=pmi.place((-5, 0, 5), (-15, 15, 0))),
        # The hole's true position: basic (theoretically exact) distances from B and C, measured.
        pmi.basic("hole-from-B", front, hole, presentation=pmi.place((0, -15, 5), (6, 0, 0))),
        pmi.basic("hole-from-C", left, hole, presentation=pmi.place((-25, 0, 5), (0, 6, 0))),
    )


if __name__ == "__main__":
    pmi_plate()
