"""Studio's standard custom features: ready in every project's Custom menu, as Onshape ships a library of
FeatureScript features beside the ones a team writes.

Each is a ``@feature`` like any a project declares (``_features.py``), placed on one flat face picked on
the model, measured from that face's centre along its own axes. A part calls one as it calls its own::

    from cad.build123d.standard_features import clearance_hole

    body = clearance_hole(body, body.faces().sort_by(Axis.Z)[-1], size="M3", x=12)

Every standard size here comes from a published table, never a guess (Studio's law 4):

- Clearance holes: ISO 273:1979, Fasteners: Clearance holes for bolts and screws, its fine, medium and
  coarse series (read from IS 1821:1987, which is identical to it).
- Heat-set inserts: CNC Kitchen's standard threaded inserts, their length, hole diameter (D3) and
  minimum wall (W), as its product pages publish them (3DJake, retrieved 2026-11-17).
"""

from __future__ import annotations

from typing import Any

from ._features import Angle, Count, Enum, Faces, FeatureError, Length, feature

# ISO 273:1979, Table 1: the clearance hole d_h for a thread diameter d, in its fine, medium and coarse series (mm).
ISO_273 = {
    "M2": {"fine": 2.2, "medium": 2.4, "coarse": 2.6},
    "M2.5": {"fine": 2.7, "medium": 2.9, "coarse": 3.1},
    "M3": {"fine": 3.2, "medium": 3.4, "coarse": 3.6},
    "M4": {"fine": 4.3, "medium": 4.5, "coarse": 4.8},
    "M5": {"fine": 5.3, "medium": 5.5, "coarse": 5.8},
    "M6": {"fine": 6.4, "medium": 6.6, "coarse": 7.0},
    "M8": {"fine": 8.4, "medium": 9.0, "coarse": 10.0},
}

# CNC Kitchen standard threaded inserts: length L, hole diameter D3 and minimum wall W around the hole (mm).
CNC_KITCHEN_INSERTS = {
    "M2": {"length": 3.0, "hole": 3.2, "wall": 1.3},
    "M2.5": {"length": 4.0, "hole": 4.0, "wall": 1.6},
    "M3": {"length": 5.7, "hole": 4.0, "wall": 1.6},
    "M4": {"length": 8.1, "hole": 5.6, "wall": 2.1},
    "M5": {"length": 9.5, "hole": 6.4, "wall": 2.6},
}

_SCREWS = {size: size for size in ISO_273}
_INSERTS = {size: size for size in CNC_KITCHEN_INSERTS}
_FITS = {"fine": "Fine", "medium": "Medium", "coarse": "Coarse"}


def _flat_face(name: str, param: str, picked: Any):
    """The one flat face picked for ``param``, refused in the feature's words when it is not one."""
    import build123d as bd

    face = picked if isinstance(picked, bd.Face) else next(iter(picked), None) if picked is not None else None
    if not isinstance(face, bd.Face):
        raise FeatureError(f"{name}: select a face on the model.", feature=name, param=param)
    if face.geom_type != bd.GeomType.PLANE:
        raise FeatureError(f"{name}: the face must be flat.", feature=name, param=param)
    return face


def _through(body: Any) -> float:
    """A depth that passes through the whole body from any of its faces."""
    return body.bounding_box().diagonal * 2 + 1


def _cut(name: str, param: str, body: Any, tools: list, words: str):
    """``body`` less ``tools``, refused when they take nothing from it."""
    if not tools:
        return body
    result = body - tools
    if abs(result.volume - body.volume) < 1e-9:
        raise FeatureError(f"{name}: {words}", feature=name, param=param)
    return result


def _hole(plane: Any, x: float, y: float, diameter: float, depth: float):
    """A cylinder ``depth`` deep into the part from a point on the face's plane."""
    import build123d as bd

    return plane.location * bd.Location((x, y, 0)) * bd.Cylinder(
        diameter / 2, depth, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))


@feature("Bolt Circle", collapsed=("Options",), face=Faces(max=1), diameter=Length(label="Circle Diameter", min=0),
         count=Count(min=1, max=72), hole=Length(label="Hole Diameter", min=0),
         spread=Enum({"full": "Full circle", "half": "Half circle"}, group="Options"),
         start=Angle(label="Start Angle", group="Options"))
def bolt_circle(body, face, diameter=40, count=6, hole=4, spread="full", start=0):
    """Through holes spaced evenly on a circle about the face's centre."""
    import build123d as bd

    plane = bd.Plane(_flat_face("Bolt Circle", "face", face))
    if hole >= diameter * 3.141592653589793 / count and count > 1:
        raise FeatureError(f"Bolt Circle: {count} holes of {hole:g} overlap on a {diameter:g} circle.", feature="Bolt Circle", param="hole")
    full = spread == "full"
    places = bd.PolarLocations(diameter / 2, count, start_angle=start, angular_range=360 if full else 180, endpoint=not full)
    depth = _through(body)
    holes = [plane.location * place * bd.Cylinder(hole / 2, depth, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))
             for place in places]
    return _cut("Bolt Circle", "diameter", body, holes, "the holes miss the part.")


@feature("Vent Slots", collapsed=("Rows",), face=Faces(max=1), length=Length(label="Slot Length", min=0),
         width=Length(label="Slot Width", min=0), count=Count(label="Slots", min=1, max=100),
         pitch=Length(label="Slot Spacing", min=0), angle=Angle(),
         rows=Count(min=1, max=50, group="Rows"), row_pitch=Length(label="Row Spacing", min=0, group="Rows"))
def vent_slots(body, face, length=20, width=3, count=6, pitch=6, angle=0, rows=1, row_pitch=25):
    """Rounded slots through the part, side by side in rows centred on the face, for air or light."""
    import build123d as bd

    picked = _flat_face("Vent Slots", "face", face)
    if width >= length:
        raise FeatureError("Vent Slots: a slot must be longer than it is wide.", feature="Vent Slots", param="width")
    if count > 1 and pitch <= width:
        raise FeatureError(f"Vent Slots: slots {width:g} wide need more than {width:g} between centres.", feature="Vent Slots", param="pitch")
    if rows > 1 and row_pitch <= length:
        raise FeatureError(f"Vent Slots: rows of {length:g} slots need more than {length:g} between them.", feature="Vent Slots", param="row_pitch")
    plane = bd.Plane(picked)
    turn = bd.Location((0, 0, 0), (0, 0, angle))
    depth = _through(body)
    slots = []
    for place in bd.GridLocations(pitch, row_pitch, count, rows):
        outline = plane.location * turn * place * bd.Rot(0, 0, 90) * bd.SlotOverall(length, width)
        inside = sum(each.area for each in picked.intersect(outline) or [])
        if inside < outline.area * 0.999:
            raise FeatureError("Vent Slots: the slots run off the face.", feature="Vent Slots", param="count")
        slots.append(bd.extrude(outline, amount=depth, dir=-plane.z_dir))
    return _cut("Vent Slots", "face", body, slots, "the slots miss the part.")


@feature("Clearance Hole", collapsed=("Position",), face=Faces(max=1), size=Enum(_SCREWS, label="Screw"),
         fit=Enum(_FITS, label="Fit (ISO 273)"), x=Length(label="X", group="Position"), y=Length(label="Y", group="Position"))
def clearance_hole(body, face, size="M3", fit="medium", x=0, y=0):
    """A through hole a metric screw passes, sized by ISO 273's fine, medium or coarse series."""
    import build123d as bd

    plane = bd.Plane(_flat_face("Clearance Hole", "face", face))
    diameter = ISO_273[size][fit]
    return _cut("Clearance Hole", "x", body, [_hole(plane, x, y, diameter, _through(body))], "the hole misses the part.")


@feature("Heat-set Insert Boss", collapsed=("Position",), face=Faces(max=1), size=Enum(_INSERTS, label="Insert"),
         height=Length(label="Boss Height", min=0), extra_wall=Length(label="Extra Wall", min=0),
         extra_depth=Length(label="Extra Hole Depth", min=0), x=Length(label="X", group="Position"),
         y=Length(label="Y", group="Position"))
def heat_set_insert_boss(body, face, size="M3", height=8, extra_wall=0, extra_depth=0, x=0, y=0):
    """A boss on the face with a hole for a CNC Kitchen standard heat-set insert: the hole its maker gives,
    the insert's length deep, in at least the wall its maker asks for. A height of 0 makes the hole alone."""
    import build123d as bd

    plane = bd.Plane(_flat_face("Heat-set Insert Boss", "face", face))
    insert = CNC_KITCHEN_INSERTS[size]
    at = plane.location * bd.Location((x, y, 0))
    made = body
    if height > 0:
        outer = insert["hole"] + 2 * (insert["wall"] + extra_wall)
        made = made + at * bd.Cylinder(outer / 2, height, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    depth = insert["length"] + extra_depth
    pilot = at * bd.Location((0, 0, height)) * bd.Cylinder(
        insert["hole"] / 2, depth, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))
    return _cut("Heat-set Insert Boss", "x", made, [pilot], "the insert's hole misses the part.")
