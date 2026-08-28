"""Shared hole helpers (plain module: no @step here)."""

from __future__ import annotations

from cadgen import build123d as bd

INSET = 6.0


def corner_hole_centers(width: float, depth: float):
    """The four corner-hole centers, shared by the part and its drawing."""
    return [
        (sx * (width / 2 - INSET), sy * (depth / 2 - INSET))
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]


def corner_holes(body, width: float, depth: float, thickness: float, hole_d: float):
    for x, y in corner_hole_centers(width, depth):
        body -= bd.Pos(x, y, 0) * bd.Cylinder(hole_d / 2, thickness * 2)
    return body
