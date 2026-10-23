"""Illustrative avionics mounting bracket for the local aerospace/MBD demo.

One solid, mm. Geometry and tolerance values are demonstration choices, not
requirements from an aircraft drawing. This is not a qualified flight part.
"""
from __future__ import annotations

import build123d as bd
from cadgen.engine import pmi, step, xbf


def geometry():
    body = bd.Pos(0, 0, 4) * bd.Box(120, 80, 8)
    body += bd.Pos(0, 36, 26) * bd.Box(120, 8, 36)
    # Two 6 mm webs support the back wall, outside the mounting pattern.
    web = bd.extrude(bd.Plane.YZ * bd.Polygon((12, 8), (32, 8), (32, 36), align=None), amount=6)
    for x in (-52, 46):
        body += bd.Pos(x, 0, 0) * web
    for x in (-36, 36):
        for y in (-23, 23):
            body -= bd.Pos(x, y, 4) * bd.Cylinder(3.3, 10)
    body -= bd.Pos(0, -18, 4) * bd.Cylinder(5, 10)
    # Rounded through-slots in the base and back wall reduce the solid volume.
    for x in (-20, 20):
        slot = bd.Pos(x, 2, -1) * bd.Rot(0, 0, 90) * bd.SlotOverall(28, 14)
        body -= bd.extrude(slot, amount=10)
    wall_window = bd.Plane.XZ * bd.Pos(0, 26) * bd.RectangleRounded(36, 16, 4)
    body -= bd.Pos(0, 41, 0) * bd.extrude(wall_window, amount=10)
    for x in (-38, 38):
        body -= bd.Pos(x, 36, 28) * bd.Rot(90, 0, 0) * bd.Cylinder(3.2, 10)
    body.label = "avionics bracket"
    assert len(body.solids()) == 1 and body.is_valid
    return body


def planar_face(body, axis, coordinate):
    candidates = [f for f in body.faces().filter_by(bd.GeomType.PLANE)
                  if abs(tuple(f.center())[axis] - coordinate) < 1e-6
                  and abs(tuple(f.normal_at())[axis]) > .999]
    assert candidates, (axis, coordinate)
    return max(candidates, key=lambda f: f.area)


@xbf(out="../XBF/aerospace_avionics_bracket.xbf")
@step(out="../XBF/aerospace_avionics_bracket.step")
def aerospace_avionics_bracket():
    body = geometry()
    bottom, top = planar_face(body, 2, 0), planar_face(body, 2, 8)
    back, left = planar_face(body, 1, 40), planar_face(body, 0, -60)
    bore = [f for f in body.faces().filter_by(bd.GeomType.CYLINDER)
            if abs(f.radius - 5) < 1e-6]
    assert len(bore) == 1
    return pmi.annotate(
        body,
        pmi.datum("A", bottom, presentation=pmi.place((45, -32, 0), (0, -16, -10))),
        pmi.datum("B", back, presentation=pmi.place((45, 40, 35), (15, 16, 0))),
        pmi.datum("C", left, presentation=pmi.place((-60, -25, 4), (-18, -10, 0))),
        pmi.distance("base-thickness", bottom, top, tolerance=pmi.plus_minus(.1),
                     presentation=pmi.place((60, -15, 4), (22, -8, 0))),
        pmi.diameter("locating-bore", bore[0], tolerance=pmi.plus_minus(.05, 0),
                     presentation=pmi.place((5, -18, 8), (18, -22, 16))),
        pmi.flatness("mounting-face-flatness", bottom, .05,
                     presentation=pmi.place((-42, -32, 0), (-8, -18, -12))),
        pmi.position("locating-bore-position", bore[0], .1, datums=["A", "B", "C"],
                     presentation=pmi.place((-5, -18, 8), (-18, -22, 30))),
        # The bore's true position: basic (theoretically exact) distances from B and C, measured.
        pmi.basic("bore-from-B", back, bore[0], presentation=pmi.place((0, 11, 8), (8, 0, 0))),
        pmi.basic("bore-from-C", left, bore[0], presentation=pmi.place((-30, -18, 8), (0, -8, 0))),
    )


if __name__ == "__main__":
    aerospace_avionics_bracket()
