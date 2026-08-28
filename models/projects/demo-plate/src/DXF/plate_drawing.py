"""Demo drawing: the plate's flat pattern (outline + corner holes)."""

from __future__ import annotations

import sys
from pathlib import Path

# src/ on sys.path so mirrored scripts share src/lib (python puts THIS
# folder on the path, not the project's src/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ezdxf

from cadgen import dxf

from lib import holes  # noqa: E402
from STEP.plate import DEPTH, WIDTH  # noqa: E402  (import never builds)


@dxf(write="../../DXF/plate_drawing.dxf")
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
