"""Direct editing: a solid's faces changed where they are, as NX's Synchronous Modeling and
Fusion's Offset Face and Delete change them, with no history needed. It is how a body that came in
with none (an imported STEP, ``read_step``) is edited, and it works on any other body as well.

``offset_faces(part, faces, distance)`` is NX's Offset Region: the faces picked move along their
normals by ``distance`` (outward, adding material, when positive), the faces around them stretched
to meet them, and faces tangent to them moved along with them. ``delete_faces(part, faces)`` is
Delete Face: the faces picked go and the solid is healed over them, so a hole, a round, a chamfer or
a boss comes out.

Each works solid by solid, keeps the part's label, colour and material, and raises ``ValueError``
in plain words where the kernel cannot make a valid solid of it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["delete_faces", "offset_faces"]


def _faces(faces: Any) -> list:
    if faces is None:
        return []
    if hasattr(faces, "wrapped") and not isinstance(faces, (list, tuple)):
        return [faces]
    return list(faces) if isinstance(faces, Iterable) else [faces]


def _carried(source: Any, made: Any) -> Any:
    """``made`` with ``source``'s label, colour and material, as the part they both are."""
    for name in ("label", "color", "material"):
        value = getattr(source, name, None)
        if value is not None:
            try:
                setattr(made, name, value)
            except (AttributeError, TypeError):
                pass
    return made


def _each_solid(part: Any, faces: list, change) -> Any:
    """``change(solid, its_faces)`` for every solid of ``part`` that holds a face picked; the others as they are."""
    import build123d as B
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_FACE

    if not faces:
        raise ValueError("Select faces on the model first.")
    solids = part.solids() if hasattr(part, "solids") else []
    if not solids:
        raise ValueError("This part has no solid to change.")
    left = list(faces)
    out = []
    for solid in solids:
        held = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
        TopExp.MapShapes_s(solid.wrapped, TopAbs_FACE, held)
        mine = [face for face in left if held.Contains(face.wrapped)]
        if not mine:
            out.append(solid)
            continue
        left = [face for face in left if face not in mine]
        made = change(solid, mine)
        if made is None or not made.is_valid or made.volume <= 0:
            raise ValueError("The kernel could not make a valid solid of that. Try a smaller distance, or fewer faces.")
        out.append(made)
    if left:
        raise ValueError("Some of the faces picked are not on this part.")
    # A part as build123d holds one: its solids in a compound.
    return _carried(part, B.Part(B.Compound(out).wrapped))


def offset_faces(part: Any, faces: Any, distance: float) -> Any:
    """NX's Offset Region: ``faces`` of ``part`` moved along their normals by ``distance`` (outward
    when positive), tangent faces with them, the solid stretched to meet them."""
    import build123d as B
    from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
    from OCP.GeomAbs import GeomAbs_Intersection

    distance = float(distance)
    if distance == 0:
        raise ValueError("An offset of 0 changes nothing. Type a distance.")

    def change(solid, mine):
        maker = BRepOffset_MakeOffset()
        maker.Initialize(solid.wrapped, 0.0, 1e-6, BRepOffset_Skin, False, False, GeomAbs_Intersection, False)
        for face in mine:
            maker.SetOffsetOnFace(face.wrapped, distance)
        maker.MakeOffsetShape()
        if not maker.IsDone():
            return None
        try:
            return B.Solid(maker.Shape())
        except Exception:
            return None

    return _each_solid(part, _faces(faces), change)


def delete_faces(part: Any, faces: Any) -> Any:
    """Delete Face: ``faces`` of ``part`` taken out and the solid healed over them (a hole, a
    round, a chamfer or a boss removed)."""
    import build123d as B
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    def change(solid, mine):
        maker = BRepAlgoAPI_Defeaturing()
        maker.SetShape(solid.wrapped)
        for face in mine:
            maker.AddFaceToRemove(face.wrapped)
        maker.Build()
        if not maker.IsDone():
            return None
        try:
            return B.Solid(maker.Shape())
        except Exception:
            return None

    return _each_solid(part, _faces(faces), change)
