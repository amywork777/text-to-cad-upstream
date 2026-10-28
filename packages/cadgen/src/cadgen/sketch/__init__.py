"""Constrained 2D sketches, written in a part's script and solved when it runs.

A sketch is drawn on a plane (Top, Front, Right, or a face's) as points, lines, arcs, circles and splines,
held by relations (horizontal, coincident, tangent) and dimensions (a distance, a radius, an
angle) the way a CAD tool's sketcher holds them, with the dimensions taking the part's named
sizes. Running the script solves the sketch, so a changed size moves the geometry that depends
on it, and the closed loops become a face to extrude, revolve or cut::

    from cadgen.sketch import Sketch

    s = Sketch("Sketch1", plane="Top")
    bottom, right, top, left = s.rectangle((0, 0), (70, 25))
    s.coincident(bottom.start, s.origin)
    s.length(bottom, LENGTH)
    s.length(left, WIDTH)
    hole = s.circle((35, 12.5), 4)
    s.diameter(hole, HOLE)
    plate = extrude(s.face(), amount=THICKNESS)

See ``sketch.py`` for every entity, relation and dimension, ``solver.py`` for how a sketch is
solved and how defined it is, ``regions.py`` for how its loops become faces, and ``fillets.py``
for where a sketch fillet's arc falls.
"""

from .sketch import Arc, Circle, Line, Point, Relation, Sketch, SketchError, Spline

__all__ = ["Arc", "Circle", "Line", "Point", "Relation", "Sketch", "SketchError", "Spline"]
