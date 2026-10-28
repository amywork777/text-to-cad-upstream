"""A part's element ordinals: its faces, edges and vertices numbered as ``TopExp.MapShapes`` numbers them.

Studio keeps this module from cadgen 0.7 (2f793659fb), which removed it with the old build pipeline:
Studio's FEA, CAM, manufacturing checks and CAD mode number a part's faces with it. cadgen 0.8 numbers a
part's elements by the same rule (``engine/refs.py``: ``face N``, ``faceNames`` and the XBM2 buffer), so
an ordinal here is the engine's ordinal for the same shape. OCP only, loaded when called.
"""

from __future__ import annotations

__all__ = ["entity_map", "shape_entities"]


def shape_entities(shape):
    """A part's bodies, the ``sN`` of a 0.7 ref: its solids, else its shells, else the shape itself."""
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    for kind in (TopAbs_SOLID, TopAbs_SHELL):
        found = []
        explorer = TopExp_Explorer(shape, kind)
        while explorer.More():
            found.append(explorer.Current())
            explorer.Next()
        if found:
            return tuple(found)
    return (shape,)


def entity_map(shape, kind):
    """A shape's faces, edges or vertices (``kind``) as an indexed map: ``FindKey(n)`` is element ``n``,
    ``FindIndex(element)`` its ordinal, ``Extent()`` how many there are."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher

    entities = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    TopExp.MapShapes_s(shape, {"face": TopAbs_FACE, "edge": TopAbs_EDGE, "vertex": TopAbs_VERTEX}[kind], entities)
    return entities
