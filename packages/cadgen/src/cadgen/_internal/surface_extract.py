"""B-rep surface extraction: the `.surf` component artifact (R1,
design/surface-rendering.md).

A `.surf` describes one component's EXACT geometry for client-side GPU
tessellation: per-face parametric surfaces (analytic where possible, NURBS
via GeomConvert otherwise), trim loops as ordered pcurves in (u,v) space,
and per-edge 3D curves with precomputed visibility classes. Face and edge
ordinals follow the same ``TopExp.MapShapes_s`` order the selector system
has always used, so refs (``#o1.2.f5``) keep their meaning.

Container layout (GLB-style, little-endian):

    magic  b"SURF" | version u32 | json_len u32 | json bytes | f32 bin

All float arrays live in one f32 binary chunk; the JSON index references
them as ``[offset_in_floats, count]`` pairs.

Extraction is READING, not computing: no tessellation happens here, which
is the entire point — display cost leaves the build path.
"""

from __future__ import annotations

import json
import struct
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GeomAbs import GeomAbs_C0, GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.GeomConvert import GeomConvert
from OCP.Geom import Geom_RectangularTrimmedSurface
from OCP.Geom2dConvert import Geom2dConvert
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_Orientation,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)
from OCP.TopoDS import TopoDS

SURF_MAGIC = b"SURF"
SURF_VERSION = 1


class Unextractable(Exception):
    """This shape cannot be represented as a .surf (caller falls through)."""


class _Bin:
    """The single f32 buffer; append() returns [offset, count] refs."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def append(self, floats) -> list[int]:
        offset = len(self.values)
        data = [float(v) for v in floats]
        self.values.extend(data)
        return [offset, len(data)]

    def payload(self) -> bytes:
        return struct.pack(f"<{len(self.values)}f", *self.values)


def _xyz(p) -> list[float]:
    return [p.X(), p.Y(), p.Z()]


def _frame(ax3) -> dict[str, list[float]]:
    return {
        "origin": _xyz(ax3.Location()),
        "xdir": _xyz(ax3.XDirection()),
        "ydir": _xyz(ax3.YDirection()),
        "zdir": _xyz(ax3.Direction()),
    }


def _nurbs_surface_payload(surface, bin_out: _Bin) -> dict[str, Any]:
    """Serialize a Geom_BSplineSurface completely (poles, weights, knots
    with multiplicities flattened, degrees, periodicity)."""
    nu, nv = surface.NbUPoles(), surface.NbVPoles()
    poles: list[float] = []
    weights: list[float] = []
    rational = surface.IsURational() or surface.IsVRational()
    for i in range(1, nu + 1):
        for j in range(1, nv + 1):
            pole = surface.Pole(i, j)
            poles.extend((pole.X(), pole.Y(), pole.Z()))
            if rational:
                weights.append(surface.Weight(i, j))

    def flat_knots(count_fn, knot_fn, mult_fn) -> list[float]:
        flat: list[float] = []
        for k in range(1, count_fn() + 1):
            flat.extend([knot_fn(k)] * mult_fn(k))
        return flat

    payload = {
        "kind": "nurbs",
        "degU": surface.UDegree(),
        "degV": surface.VDegree(),
        "nu": nu,
        "nv": nv,
        "periodicU": bool(surface.IsUPeriodic()),
        "periodicV": bool(surface.IsVPeriodic()),
        "poles": bin_out.append(poles),
        "knotsU": bin_out.append(
            flat_knots(surface.NbUKnots, surface.UKnot, surface.UMultiplicity)),
        "knotsV": bin_out.append(
            flat_knots(surface.NbVKnots, surface.VKnot, surface.VMultiplicity)),
    }
    if rational:
        payload["weights"] = bin_out.append(weights)
    return payload


def _surface_payload(face, bin_out: _Bin) -> dict[str, Any]:
    adaptor = BRepAdaptor_Surface(face)
    kind = adaptor.GetType()
    if kind == GeomAbs_SurfaceType.GeomAbs_Plane:
        plane = adaptor.Plane()
        return {"kind": "plane", **_frame(plane.Position())}
    if kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        cylinder = adaptor.Cylinder()
        return {"kind": "cylinder", "radius": cylinder.Radius(),
                **_frame(cylinder.Position())}
    if kind == GeomAbs_SurfaceType.GeomAbs_Cone:
        cone = adaptor.Cone()
        return {"kind": "cone", "radius": cone.RefRadius(),
                "semiAngle": cone.SemiAngle(), **_frame(cone.Position())}
    if kind == GeomAbs_SurfaceType.GeomAbs_Sphere:
        sphere = adaptor.Sphere()
        return {"kind": "sphere", "radius": sphere.Radius(),
                **_frame(sphere.Position())}
    if kind == GeomAbs_SurfaceType.GeomAbs_Torus:
        torus = adaptor.Torus()
        return {"kind": "torus", "majorRadius": torus.MajorRadius(),
                "minorRadius": torus.MinorRadius(), **_frame(torus.Position())}
    # PARAMETRIZATION IS PART OF THE CONTRACT: pcurves live in the original
    # surface's (u, v), so any serialization must evaluate identically at the
    # same parameters — SurfaceToBSplineSurface does NOT (a rational-quadratic
    # circle cannot carry angle parametrization, so revolved/extruded-arc
    # surfaces come back reparametrized and every trim lands wrong).
    if kind == GeomAbs_SurfaceType.GeomAbs_SurfaceOfRevolution:
        # Value(u, v) = basis(v) rotated by u around the axis.
        axis = adaptor.AxeOfRevolution()
        basis = _basis_curve_payload(adaptor.BasisCurve(), bin_out)
        return {
            "kind": "revolution",
            "origin": _xyz(axis.Location()),
            "dir": _xyz(axis.Direction()),
            "profile": basis,
        }
    if kind == GeomAbs_SurfaceType.GeomAbs_SurfaceOfExtrusion:
        # Value(u, v) = basis(u) + v * direction.
        basis = _basis_curve_payload(adaptor.BasisCurve(), bin_out)
        return {
            "kind": "extrusion",
            "dir": _xyz(adaptor.Direction()),
            "profile": basis,
        }
    surface = BRep_Tool.Surface_s(face)
    if surface is None:
        raise Unextractable("face with no surface")
    if kind in (GeomAbs_SurfaceType.GeomAbs_BSplineSurface,
                GeomAbs_SurfaceType.GeomAbs_BezierSurface):
        # Native NURBS: conversion is exact AND parametrization-preserving;
        # clamping periodic directions preserves both too.
        try:
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            bounded = Geom_RectangularTrimmedSurface(surface, u0, u1, v0, v1)
            nurbs = GeomConvert.SurfaceToBSplineSurface_s(bounded)
            if nurbs.IsUPeriodic():
                nurbs.SetUNotPeriodic()
            if nurbs.IsVPeriodic():
                nurbs.SetVNotPeriodic()
        except Exception as exc:
            raise Unextractable(f"NURBS conversion failed: {exc}") from exc
        return _nurbs_surface_payload(nurbs, bin_out)
    # Exotic kinds (offset surfaces, ...): parametrization-preserving
    # least-squares approximation.
    try:
        from OCP.GeomAbs import GeomAbs_C1
        from OCP.GeomConvert import GeomConvert_ApproxSurface

        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        bounded = Geom_RectangularTrimmedSurface(surface, u0, u1, v0, v1)
        approx = GeomConvert_ApproxSurface(
            bounded, 1e-4, GeomAbs_C1, GeomAbs_C1, 14, 14, 100, 0)
        if not approx.IsDone():
            raise Unextractable("surface approximation did not converge")
        nurbs = approx.Surface()
        if nurbs.IsUPeriodic():
            nurbs.SetUNotPeriodic()
        if nurbs.IsVPeriodic():
            nurbs.SetVNotPeriodic()
    except Unextractable:
        raise
    except Exception as exc:
        raise Unextractable(f"surface approximation failed: {exc}") from exc
    return _nurbs_surface_payload(nurbs, bin_out)


def _basis_curve_payload(basis_adaptor, bin_out: _Bin) -> dict[str, Any]:
    """Serialize a swept surface's basis curve in the edge-curve schema
    (line/circle/ellipse/bspline), preserving its parametrization: analytic
    kinds carry it inherently; general curves convert through
    CurveToBSplineCurve which keeps parameters for non-periodic input and is
    clamped (parametrization-preserving) otherwise."""
    kind = basis_adaptor.GetType()
    first = basis_adaptor.FirstParameter()
    last = basis_adaptor.LastParameter()
    if kind == GeomAbs_CurveType.GeomAbs_Line:
        line = basis_adaptor.Line()
        return {"kind": "line", "origin": _xyz(line.Location()),
                "dir": _xyz(line.Direction()), "range": [first, last]}
    if kind == GeomAbs_CurveType.GeomAbs_Circle:
        circle = basis_adaptor.Circle()
        return {"kind": "circle", "radius": circle.Radius(),
                **_frame(circle.Position()), "range": [first, last]}
    if kind == GeomAbs_CurveType.GeomAbs_Ellipse:
        ellipse = basis_adaptor.Ellipse()
        return {"kind": "ellipse", "majorRadius": ellipse.MajorRadius(),
                "minorRadius": ellipse.MinorRadius(),
                **_frame(ellipse.Position()), "range": [first, last]}
    try:
        bspline = basis_adaptor.BSpline()
        if bspline.IsPeriodic():
            bspline.SetNotPeriodic()
    except Exception as exc:
        raise Unextractable(f"basis curve conversion failed: {exc}") from exc
    return _bspline_curve3_payload(bspline, bin_out)


def _bspline_curve3_payload(bspline, bin_out: _Bin) -> dict[str, Any]:
    poles: list[float] = []
    weights: list[float] = []
    rational = bspline.IsRational()
    for i in range(1, bspline.NbPoles() + 1):
        pole = bspline.Pole(i)
        poles.extend((pole.X(), pole.Y(), pole.Z()))
        if rational:
            weights.append(bspline.Weight(i))
    flat: list[float] = []
    for k in range(1, bspline.NbKnots() + 1):
        flat.extend([bspline.Knot(k)] * bspline.Multiplicity(k))
    payload = {
        "kind": "bspline",
        "deg": bspline.Degree(),
        "n": bspline.NbPoles(),
        "periodic": bool(bspline.IsPeriodic()),
        "poles": bin_out.append(poles),
        "knots": bin_out.append(flat),
        "range": [bspline.FirstParameter(), bspline.LastParameter()],
    }
    if rational:
        payload["weights"] = bin_out.append(weights)
    return payload


def _curve2d_payload(edge, face, bin_out: _Bin) -> dict[str, Any]:
    curve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
    if curve is None:
        raise Unextractable("edge with no pcurve on its face")
    first, last = BRep_Tool.Range_s(edge, face)
    # Convert every pcurve to a 2D BSpline: one evaluator client-side, and
    # Geom2dConvert handles lines/arcs exactly (degree 1 / rational degree 2).
    # Trim first — unbounded curves (lines) refuse direct conversion.
    try:
        from OCP.Geom2d import Geom2d_TrimmedCurve

        bspline = Geom2dConvert.CurveToBSplineCurve_s(
            Geom2d_TrimmedCurve(curve, first, last))
        if bspline.IsPeriodic():
            bspline.SetNotPeriodic()
    except Exception as exc:
        raise Unextractable(f"pcurve conversion failed: {exc}") from exc
    poles: list[float] = []
    weights: list[float] = []
    rational = bspline.IsRational()
    for i in range(1, bspline.NbPoles() + 1):
        pole = bspline.Pole(i)
        poles.extend((pole.X(), pole.Y()))
        if rational:
            weights.append(bspline.Weight(i))
    flat: list[float] = []
    for k in range(1, bspline.NbKnots() + 1):
        flat.extend([bspline.Knot(k)] * bspline.Multiplicity(k))
    payload = {
        "deg": bspline.Degree(),
        "n": bspline.NbPoles(),
        "periodic": bool(bspline.IsPeriodic()),
        "poles": bin_out.append(poles),
        "knots": bin_out.append(flat),
        "range": [first, last],
    }
    if rational:
        payload["weights"] = bin_out.append(weights)
    return payload


def _curve3d_payload(edge, bin_out: _Bin) -> dict[str, Any] | None:
    if BRep_Tool.Degenerated_s(edge):
        return None
    adaptor = BRepAdaptor_Curve(edge)
    first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    kind = adaptor.GetType()
    if kind == GeomAbs_CurveType.GeomAbs_Line:
        line = adaptor.Line()
        return {"kind": "line", "origin": _xyz(line.Location()),
                "dir": _xyz(line.Direction()), "range": [first, last]}
    if kind == GeomAbs_CurveType.GeomAbs_Circle:
        circle = adaptor.Circle()
        return {"kind": "circle", "radius": circle.Radius(),
                **_frame(circle.Position()), "range": [first, last]}
    if kind == GeomAbs_CurveType.GeomAbs_Ellipse:
        ellipse = adaptor.Ellipse()
        return {"kind": "ellipse", "majorRadius": ellipse.MajorRadius(),
                "minorRadius": ellipse.MinorRadius(),
                **_frame(ellipse.Position()), "range": [first, last]}
    # General curve: sample-free exact NURBS conversion.
    curve = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    if curve is None:
        return None
    try:
        from OCP.Geom import Geom_TrimmedCurve

        bspline = GeomConvert.CurveToBSplineCurve_s(
            Geom_TrimmedCurve(curve, first, last))
        if bspline.IsPeriodic():
            bspline.SetNotPeriodic()
    except Exception:
        return None
    poles: list[float] = []
    weights: list[float] = []
    rational = bspline.IsRational()
    for i in range(1, bspline.NbPoles() + 1):
        pole = bspline.Pole(i)
        poles.extend((pole.X(), pole.Y(), pole.Z()))
        if rational:
            weights.append(bspline.Weight(i))
    flat: list[float] = []
    for k in range(1, bspline.NbKnots() + 1):
        flat.extend([bspline.Knot(k)] * bspline.Multiplicity(k))
    payload = {
        "kind": "bspline",
        "deg": bspline.Degree(),
        "n": bspline.NbPoles(),
        "periodic": bool(bspline.IsPeriodic()),
        "poles": bin_out.append(poles),
        "knots": bin_out.append(flat),
        "range": [bspline.FirstParameter(), bspline.LastParameter()],
    }
    if rational:
        payload["weights"] = bin_out.append(weights)
    return payload


def _edge_visibility_class(edge, faces: list, face_of_edge_count: int) -> str:
    from cadgen._internal.glb_topology import STEP_EDGE_VISIBILITY_CLASSES as C

    if BRep_Tool.Degenerated_s(edge):
        return C["DEGENERATE"]
    if face_of_edge_count > 2:
        return C["NON_MANIFOLD"]
    if face_of_edge_count == 1:
        if faces and BRep_Tool.IsClosed_s(edge, TopoDS.Face_s(faces[0])):
            return C["SEAM"]
        return C["BOUNDARY"]
    if any(BRep_Tool.IsClosed_s(edge, TopoDS.Face_s(f)) for f in faces):
        return C["SEAM"]
    try:
        continuity = BRep_Tool.Continuity_s(
            edge, TopoDS.Face_s(faces[0]), TopoDS.Face_s(faces[1]))
        if continuity == GeomAbs_C0:
            return C["FEATURE"]
        return C["TANGENT"]
    except Exception:
        return C["UNKNOWN"]


def extract_surface_component(
    shape,
    *,
    face_colors: dict | None = None,
    part_color: tuple | list | None = None,
) -> bytes:
    """Serialize one (unlocated) component shape as a .surf container.
    ``part_color`` is the part-level RGBA the component GLB used to bake into
    its material; the descriptor's occurrences carry no colour, so it ships
    on the component."""
    bin_out = _Bin()

    face_map = TopTools_IndexedMapOfShape()
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_faces)

    edge_ord_by_hash = {
        _shape_hash(edge_map.FindKey(i)): i
        for i in range(1, edge_map.Extent() + 1)
    }

    faces: list[dict[str, Any]] = []
    for ordinal in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(ordinal))
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        entry: dict[str, Any] = {
            "ord": ordinal,
            "reversed": face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED,
            "uv": [u0, u1, v0, v1],
            "surface": _surface_payload(face, bin_out),
            "loops": [],
        }
        if face_colors:
            color = face_colors.get(ordinal)
            if color is not None:
                entry["color"] = [float(c) for c in color]
        wire_explorer = TopExp_Explorer(face, TopAbs_WIRE)
        while wire_explorer.More():
            wire = TopoDS.Wire_s(wire_explorer.Current())
            loop: list[dict[str, Any]] = []
            walker = BRepTools_WireExplorer(wire, face)
            while walker.More():
                edge = walker.Current()
                pcurve = _curve2d_payload(edge, face, bin_out)
                pcurve["edgeOrd"] = edge_ord_by_hash.get(_shape_hash(edge), 0)
                pcurve["reversed"] = (
                    edge.Orientation() == TopAbs_Orientation.TopAbs_REVERSED)
                loop.append(pcurve)
                walker.Next()
            if loop:
                entry["loops"].append(loop)
            wire_explorer.Next()
        faces.append(entry)

    edges: list[dict[str, Any]] = []
    for ordinal in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(ordinal))
        # NB: list(TopTools_ListOfShape) costs ~2ms/call in OCP (its Python
        # iteration protocol unwinds C++ exceptions); First/Last/iterator
        # access is ~1000x cheaper and this loop runs once per edge.
        adjacent = []
        if edge_faces.Contains(edge):
            face_list = edge_faces.FindFromKey(edge)
            extent = face_list.Extent()
            if extent == 1:
                adjacent = [face_list.First()]
            elif extent == 2:
                adjacent = [face_list.First(), face_list.Last()]
            elif extent > 2:
                # Rare (non-manifold); the slow generic path is fine here.
                adjacent = list(face_list)
        entry = {
            "ord": ordinal,
            "class": _edge_visibility_class(edge, adjacent, len(adjacent)),
            "curve": _curve3d_payload(edge, bin_out),
        }
        edges.append(entry)

    index = {
        "version": SURF_VERSION,
        "faces": faces,
        "edges": edges,
        "counts": {"faces": face_map.Extent(), "edges": edge_map.Extent()},
    }
    if part_color is not None:
        index["partColor"] = [float(c) for c in part_color]
    json_bytes = json.dumps(index, separators=(",", ":")).encode("utf-8")
    payload = bin_out.payload()
    return (
        SURF_MAGIC
        + struct.pack("<II", SURF_VERSION, len(json_bytes))
        + json_bytes
        + payload
    )


def read_surf(data: bytes) -> tuple[dict, memoryview]:
    if data[:4] != SURF_MAGIC:
        raise ValueError("not a SURF container")
    version, json_len = struct.unpack_from("<II", data, 4)
    index = json.loads(data[12:12 + json_len].decode("utf-8"))
    return index, memoryview(data)[12 + json_len:]


def _shape_hash(shape) -> int:
    # Same identity the selector extraction uses for ordinal joins.
    from cadgen._internal.step_scene_selectors import _shape_hash as impl

    return impl(shape)
