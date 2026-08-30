"""Demo drawing: the plate's flat pattern (outline + corner holes)."""

from __future__ import annotations

import ezdxf

from cadgen import dxf

from lib import holes
from plate import DEPTH, WIDTH  # importing a model never builds it


@dxf(write="../DXF/plate_drawing.dxf")
def plate_drawing(hole_d: float = 4.5):
    document = ezdxf.new()
    space = document.modelspace()
    half_w, half_d = WIDTH / 2, DEPTH / 2
    space.add_lwpolyline(
        [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)],
        close=True,
    )
    for x, y in holes.corner_hole_centers(WIDTH, DEPTH):
        space.add_circle((x, y), hole_d / 2)
    return document
