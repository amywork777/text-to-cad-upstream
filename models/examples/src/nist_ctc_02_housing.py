from __future__ import annotations

# Prompt: Semantic PMI on a part another system modelled: NIST's PMI Complex Test Case 2, a cast
# gearbox housing read from its STEP, given a model-based definition in cadgen's AP242 vocabulary:
# datums D (the open flange's face), E and F (the flange's two 12 mm locating holes), the flange's
# flatness, E and F's diameters and F's position to D|E; the two 100 mm and two 52 mm bearing bores'
# diameters and positions to D|E|F; the four mounting pads profiled to D; every other face held by
# a general profile to D|E|F; NIST's Note 1 (dimensions from the model are basic) and the edge note;
# and three views: an iso from each bearing side and section A-A through the bores' axis.
#
# Source: the NIST MBE PMI Validation and Conformance Testing project's CTC 2 (Rev C), whose test
# cases, CAD models and STEP files NIST publishes for use without restriction. Download
# NIST-PMI-STEP-Files.zip from https://www.nist.gov/document/nist-pmi-step-files and copy
# "AP203 geometry only/nist_ctc_02_asme1_rc.stp" into ../STEP/ (gitignored: Git holds no CAD files).
# The tolerance values are NIST's; NIST locates the bores from datum targets A|B|C on the casting,
# which cadgen does not write, so here they are positioned to the flange's D|E|F, and NIST's
# material modifiers and perpendicularity controls are left out for the same reason. NIST's test
# cases are not meant as best practice in applying GD&T. Do not manufacture to this.

from pathlib import Path

import build123d as bd

from cadgen import read_step, step
from cadgen.ap242 import (annotate, camera, datum, dimensional_size, flatness_tolerance, general_profile, note, place,
                          plus_minus_tolerance, position_tolerance, section, surface_profile_tolerance, view)
from lib.notes import NOTES

SOURCE = Path(__file__).parent / "../STEP/nist_ctc_02_asme1_rc.stp"


def _hole(body, diameter, near):
    """The cylindrical face of ``diameter`` whose centre is nearest ``near``: one half of a hole the
    file splits in two, which carries the hole's diameter and axis."""
    return min((face for face in body.faces().filter_by(bd.GeomType.CYLINDER) if abs(2 * face.radius - diameter) < 1e-3),
               key=lambda face: (face.center() - bd.Vector(*near)).length)


@step(out="../STEP/nist_ctc_02_housing.step")
def nist_ctc_02_housing():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"{SOURCE.name} is NIST's STEP: download it as this file's header says")
    body = read_step(SOURCE).solids()[0]
    body.label = "housing"
    planes = body.faces().filter_by(bd.GeomType.PLANE)
    flange = max((face for face in planes if abs(face.center().Z) < 1e-6 and face.normal_at().Z > 0.999),
                 key=lambda face: face.area)
    pads = [face for face in planes if abs(face.center().Z - 40) < 1e-6 and face.normal_at().Z > 0.999]
    hole_e, hole_f = _hole(body, 12, (216, 19, -12.5)), _hole(body, 12, (-150, 761, -12.5))
    bore, small = {}, {}
    for side, x in (("right", 1), ("left", -1)):
        bore[side] = _hole(body, 100, (261 * x, 200, -135))
        small[side] = _hole(body, 52, (241 * x, 200, -159))
    bores = []
    for side, x in (("right", 1), ("left", -1)):
        # Each bore's frames stacked outboard of its boss: x and y flip with the side, so each side's
        # view (below) draws them alike.
        out = (200 * x, 120 * x)
        bores += [
            dimensional_size(f"bore-{side}", bore[side], tolerance=plus_minus_tolerance(0.15),
                             presentation=place((261 * x, 200, -135), (*out, 90))),
            position_tolerance(f"bore-{side}-position", bore[side], 1.5, datums=["D", "E", "F"],
                               presentation=place((261 * x, 200, -135), (*out, 45))),
            dimensional_size(f"seat-{side}", small[side], tolerance=plus_minus_tolerance(0.15),
                             presentation=place((241 * x, 200, -159), (*out, -15))),
            position_tolerance(f"seat-{side}-position", small[side], 1.0, datums=["D", "E", "F"],
                               presentation=place((241 * x, 200, -159), (*out, -60))),
        ]
    flange_ids = ["D", "flange-flatness", "E", "hole-E", "F", "hole-F", "hole-F-position", "pads", "basic", "edges"]
    return annotate(
        body,
        datum("D", flange, presentation=place((-72, 8, 0), (-140, -160, -90))),
        flatness_tolerance("flange-flatness", flange, 0.05, presentation=place((72, 8, 0), (-60, -180, 210))),
        datum("E", hole_e, presentation=place((216, 19, -3), (60, -140, 30))),
        dimensional_size("hole-E", hole_e, tolerance=plus_minus_tolerance(0.05),
                         presentation=place((216, 19, -3), (140, -60, 60))),
        datum("F", hole_f, presentation=place((-150, 767, -3), (-100, 100, 20))),
        dimensional_size("hole-F", hole_f, tolerance=plus_minus_tolerance(0.05),
                         presentation=place((-150, 767, -3), (100, 100, 60))),
        position_tolerance("hole-F-position", hole_f, 0.05, datums=["D", "E"],
                           presentation=place((-150, 767, -3), (100, 100, 130))),
        *bores,
        # The four mounting pads, coplanar, held to the flange.
        surface_profile_tolerance("pads", pads, 0.1, datums=["D"], presentation=place((300, 300, 40), (100, 100, 60))),
        general_profile("general", 0.8, datums=["D", "E", "F"]),
        note("basic", NOTES["basic-from-model"]),
        note("edges", NOTES["edges"]),
        # Two isos, one from each bearing side, each showing what faces it.
        view("right", camera=camera((1, -1, 1), (0, 0, 1)),
             shows=flange_ids + [a["id"] for a in bores if a["id"].startswith(("bore-right", "seat-right"))]),
        view("left", camera=camera((-1, 1, 1), (0, 0, 1)),
             shows=[a["id"] for a in bores if a["id"].startswith(("bore-left", "seat-left"))]),
        # Section A-A across y through the bores' axis, keeping the far side so the front camera,
        # at -Y, looks at the cut.
        view("A-A", camera="front", shows=["bore-right", "seat-right", "bore-left", "seat-left"],
             section=section("y", 200, invert=True)),
        library=NOTES,
    )


if __name__ == "__main__":
    nist_ctc_02_housing()
