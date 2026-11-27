"""A STEP file read back by the kernel, as a CAD program would read it: whether it is one valid solid, and its
volume. What writes a STEP without the kernel (``cad gsl step``'s faceted writer) holds its file to this before
handing it over."""

from __future__ import annotations

from pathlib import Path

__all__ = ["read_back"]


def read_back(path: Path) -> tuple[bool, float] | None:
    """``(one valid solid, its volume in mm3)``, or None where the file does not read."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_SOLID

    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        return None
    reader.TransferRoots()
    shape = reader.OneShape()
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return shape.ShapeType() == TopAbs_SOLID and BRepCheck_Analyzer(shape).IsValid(), float(properties.Mass())
