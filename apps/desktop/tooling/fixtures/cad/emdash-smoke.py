"""Small deterministic part used by Hardcore's CAD runtime smoke test."""

from cadgen import build123d as bd
from cadgen import step


@step()
def emdash_smoke(
    width: float = 30,
    depth: float = 20,
    height: float = 6,
    hole_radius: float = 3,
):
    body = bd.Box(width, depth, height)
    mounting_hole = bd.Pos(0, 0, -1) * bd.Cylinder(hole_radius, height + 2)
    part = body - mounting_hole
    part.label = "emdash_smoke_plate"
    return part
