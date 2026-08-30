"""Demo drawing: the plate's flat pattern (outline + corner holes)."""

from __future__ import annotations

from cadgen import build123d as bd
from cadgen import dxf

from lib import holes
from plate import DEPTH, WIDTH  # importing a model never builds it


@dxf(out="../DXF/plate_drawing.dxf")
def plate_drawing(hole_d: float = 4.5):
    with bd.BuildSketch() as cut:
        bd.Rectangle(WIDTH, DEPTH)
        with bd.Locations(*holes.corner_hole_centers(WIDTH, DEPTH)):
            bd.Circle(hole_d / 2, mode=bd.Mode.SUBTRACT)
    return cut.sketch  # a bare shape is the CUT layer
