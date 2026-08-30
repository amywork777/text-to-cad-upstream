"""Demo part: a mounting plate with corner holes (cad-project exemplar)."""

from __future__ import annotations

from cadgen import build123d as bd
from cadgen import step

from lib import holes

WIDTH = 60.0
DEPTH = 40.0
THICKNESS = 4.0


@step(out="../STEP/plate.step")
def plate(hole_d: float = 4.5):
    body = bd.Box(WIDTH, DEPTH, THICKNESS)
    return holes.corner_holes(body, WIDTH, DEPTH, THICKNESS, hole_d)
