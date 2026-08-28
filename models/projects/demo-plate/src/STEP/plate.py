"""Demo part: a mounting plate with corner holes (cad-project exemplar)."""

from __future__ import annotations

import sys
from pathlib import Path

# src/ on sys.path so mirrored scripts share src/lib (python puts THIS
# folder on the path, not the project's src/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cadgen import build123d as bd
from cadgen import step

from lib import holes  # noqa: E402

WIDTH = 60.0
DEPTH = 40.0
THICKNESS = 4.0


@step(write="../../STEP/plate.step")
def plate(hole_d: float = 4.5):
    body = bd.Box(WIDTH, DEPTH, THICKNESS)
    return holes.corner_holes(body, WIDTH, DEPTH, THICKNESS, hole_d)
