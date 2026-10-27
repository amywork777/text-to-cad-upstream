"""The part a job machines, read once: exact faces from ``read_step``/``read_xbf``, one tessellation, or a DXF's
profiles.

:func:`read_part` returns a :class:`Part`:

* ``vertices`` (V, 3) and ``triangles`` (T, 3) in part mm: one tessellation of the occurrence at
  ``deflection_mm`` (OCCT's incremental mesher, linear and angular deflection), wound outward; and
  ``face_of_triangle`` (T,) with each triangle's face ordinal (the ``N`` of ``face N``);
* ``faces``: one :class:`FaceInfo` per face ordinal (surface type, area, centre, plane normal or cylinder axis,
  whether a cylinder is a hole), read from the exact B-rep;
* :meth:`Part.face` resolves a job's face ref to its :class:`FaceInfo` with a teaching error for a ref that is not on
  this part, and :meth:`Part.edge` an edge ref to its exact ``TopoDS_Edge``; :meth:`Part.ocp_face` hands back the
  exact ``TopoDS_Face`` (world placement);
* :meth:`Part.mesh_in` the mesh in a setup's WCS (cached per setup).

A DXF part (``kind == "dxf"``) has ``profiles`` (shapely polygons, even-odd filled, in mm on z = 0; blocks expanded,
annotation skipped and said in ``notes``, any other entity refused: :func:`dxf_curves`) and a mesh extruded to the
sheet's thickness; it has no faces. Stdlib at import; numpy, OCP and ezdxf inside.

A ref is the engine's (``cadgen.engine.refs``, what ``cadgen inspect`` answers and the CAD Viewer copies): ``face 12``
on a document of one part, ``bracket/face 12`` or ``kit/arm/face 12`` under the part's occurrence, an element's name
(``bracket/f:bracket.body.3``) where the file names its faces, optionally after the document (``bracket.step#face
12``). It is resolved in the document as it is read here, never through the engine: CAM reads a file, not a model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cadgen._internal.cam.job_errors import CamJobError

__all__ = ["DXF_SUFFIXES", "PART_SUFFIXES", "FaceInfo", "Part", "dxf_curves", "element_kind", "read_dxf_drawing",
           "read_dxf_profiles", "read_part"]

DXF_SUFFIXES = (".dxf",)
#: The documents a part is read from: a STEP, or an engine document (a model's ``@xbf``, or ``cadgen export ID
#: part.xbf``).
PART_SUFFIXES = (".step", ".stp", ".xbf")
#: The default tessellation: fine enough that sections and checks are good to a few hundredths of a millimetre.
DEFAULT_DEFLECTION_MM = 0.01
ANGULAR_DEFLECTION = 0.15
#: The kinds an element name's codes stand for, as the reader keeps them (``kernel/imported.py``).
_NAME_KINDS = (("vertex", 0), ("edge", 1), ("face", 2))


def element_kind(ref: object) -> str | None:
    """The kind of element a ref names (``face``, ``edge``, ``vertex``) when it is one ref of one element, else None:
    what a job's ``faces`` or ``edges`` entry is read as before the part is."""
    from cadgen.engine.refs import RefError, parse

    if not isinstance(ref, str):
        return None
    try:
        _file, selectors = parse(ref)
    except RefError:
        return None
    return selectors[0].kind if len(selectors) == 1 else None


class _Document:
    """A read document's occurrence tree as the engine's refs resolve it (``refs.resolve_structure``): an assembly by
    its components, a part by its element names; each part's entry holds its node of the build123d tree."""

    def __init__(self, path: Path, tree) -> None:
        self.path = path
        self.prototypes: list[dict] = []
        self.parts: list[dict] = []
        root = self._entry(tree)
        if not root["name"]:
            root["name"] = path.stem  # several roots, or one unnamed: the document's name
        self.structure = {"tree": root, "prototypes": self.prototypes}

    def _entry(self, node) -> dict:
        children = list(getattr(node, "children", ()) or ())
        if children:
            return {"name": node.label or "", "children": [self._entry(child) for child in children]}
        from cadgen.engine.kernel.imported import ELEMENT_NAMES

        names = node.__dict__.get(ELEMENT_NAMES) or {}
        self.prototypes.append({f"{kind}Names": {str(o): text for o, text in (names.get(code) or {}).items()}
                                for kind, code in _NAME_KINDS})
        entry = {"name": node.label or "", "prototype": len(self.prototypes) - 1, "node": node}
        self.parts.append(entry)
        return entry

    def resolve(self, ref: str):
        """The one thing ``ref`` names (a ``refs.Hit``); ValueError where it names nothing, or several things."""
        from cadgen.engine.refs import resolve_structure

        hits = resolve_structure(self.structure, ref, self.path)
        if len(hits) != 1:
            raise ValueError(f"it names {len(hits)} things; give each its own entry")
        return hits[0]

@dataclass(frozen=True)
class FaceInfo:
    ref: str
    ordinal: int
    #: plane, cylinder, cone, sphere, torus, bspline, bezier, revolution, extrusion, offset, other
    surface: str
    area_mm2: float
    center_mm: tuple[float, float, float]
    #: A plane's outward normal (face orientation applied).
    normal: tuple[float, float, float] | None = None
    #: A cylinder's or a cone's axis direction and a point on it.
    axis: tuple[float, float, float] | None = None
    axis_point: tuple[float, float, float] | None = None
    radius_mm: float | None = None
    #: A cylinder whose material is outside it (a hole wall); False for a boss; None for anything else.
    hole: bool | None = None
    #: The face's tessellated bounds in part mm.
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None


@dataclass
class Part:
    document: Path
    occurrence: str
    kind: str                       # "step" (a STEP or an xbf: B-rep) | "dxf"
    vertices: Any                   # (V, 3) float
    triangles: Any                  # (T, 3) int
    face_of_triangle: Any           # (T,) int, face ordinal (0 for a DXF)
    faces: dict[int, FaceInfo]
    deflection_mm: float
    shape: Any = None               # build123d Shape (world placement); None for a DXF
    profiles: list = field(default_factory=list)   # DXF: shapely Polygons
    #: What reading it skipped (a DXF's text and dimensions), in plain words, for the result's warnings.
    notes: list = field(default_factory=list)
    _document: Any = None
    #: The occurrence's path from the document's root: the identity a ref's part is checked against.
    _path: str = ""
    _face_map: Any = None
    _edge_map: Any = None
    _ordinals: Any = None
    _wcs_cache: dict = field(default_factory=dict)

    @property
    def bbox(self):
        import numpy as np

        return np.asarray(self.vertices).min(axis=0), np.asarray(self.vertices).max(axis=0)

    def _element(self, ref: str, where: str, kind: str):
        try:
            hit = self._document.resolve(ref)
        except ValueError as exc:
            raise CamJobError(f"{where}: {ref} is not {'an' if kind == 'edge' else 'a'} {kind} of this part ({exc}); "
                              + ("cadgen cam features lists them" if kind == "face" else "select the edges in the Viewer")
                              ) from None
        if hit.kind != kind:
            raise CamJobError(f"{where}: {ref} is {'a part' if hit.kind is None else f'a {hit.kind}'} reference; "
                              f"name {kind}s ({kind} 12)")
        if hit.path != self._path:
            raise CamJobError(f"{where}: {ref} is on {hit.path}, but the job machines {self.occurrence}")
        count = len(self.faces) if kind == "face" else self._edges().Extent()
        if not 1 <= hit.ordinal <= count:
            raise CamJobError(f"{where}: {ref} is not {'an' if kind == 'edge' else 'a'} {kind} of this part (it has "
                              f"{count}); " + ("cadgen cam features lists them" if kind == "face"
                                               else "select the edges in the Viewer"))
        return hit

    def _edges(self):
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape

        if self._edge_map is None:
            self._edge_map = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(self.shape.wrapped, TopAbs_EDGE, self._edge_map)
        return self._edge_map

    def face(self, ref: str, where: str = "faces") -> FaceInfo:
        """The face a job names, or the teaching error."""
        if self.kind != "step":
            raise CamJobError(f"{where}: {ref} names a face, but a DXF has no faces; name its profiles with region")
        return self.faces[self._element(ref, where, "face").ordinal]

    def edge(self, ref: str, where: str = "edges"):
        """``(canonical ref, TopoDS_Edge)`` of the edge a job names (world placement), or the teaching error."""
        from OCP.TopoDS import TopoDS

        if self.kind != "step":
            raise CamJobError(f"{where}: {ref} names an edge, but a DXF has no edges; follow its profiles with region")
        hit = self._element(ref, where, "edge")
        return hit.ref, TopoDS.Edge_s(self._edges().FindKey(hit.ordinal))

    def ordinal(self, ref: str) -> int:
        """The ordinal of a face by its canonical ref (a :class:`FaceInfo`'s ``ref``, as ``cam features`` lists it)."""
        if self._ordinals is None:
            self._ordinals = {info.ref: ordinal for ordinal, info in self.faces.items()}
        return self._ordinals[ref]

    def ocp_face(self, ordinal: int):
        """The exact ``TopoDS_Face`` of a face ordinal, in part coordinates."""
        from OCP.TopoDS import TopoDS

        return TopoDS.Face_s(self._face_map.FindKey(ordinal))

    def mesh_in(self, wcs):
        """(vertices, triangles) in the WCS of ``wcs``; cached per setup."""
        key = (wcs.setup_id, wcs.rotation, wcs.origin)
        if key not in self._wcs_cache:
            self._wcs_cache[key] = (wcs.to_wcs(self.vertices), self.triangles)
        return self._wcs_cache[key]

    def classify(self, points) -> Any:
        """For each part point, whether it is inside the solid (exact, OCCT's classifier); DXF: inside a profile."""
        import numpy as np

        points = np.asarray(points, dtype=float)
        if self.kind == "dxf":
            import shapely

            union = shapely.union_all(self.profiles)
            top = float(np.asarray(self.vertices)[:, 2].max())
            return np.array([bool(union.contains(shapely.Point(p[0], p[1]))) and 0 <= p[2] <= top for p in points])
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN

        classifier = BRepClass3d_SolidClassifier(self.shape.wrapped)
        out = []
        for p in points:
            classifier.Perform(gp_Pnt(float(p[0]), float(p[1]), float(p[2])), 1e-6)
            out.append(classifier.State() == TopAbs_IN)
        return np.array(out, dtype=bool)


def read_part(document: Path, *, occurrence: str | None = None, deflection_mm: float | None = None,
              sheet_thickness_mm: float | None = None) -> Part:
    """Read a STEP occurrence (or a DXF) and tessellate it once."""
    document = Path(document)
    if document.suffix.lower() in DXF_SUFFIXES:
        if not document.is_file():
            raise CamJobError(f"no DXF at {document}")
        # A plan always names the sheet's thickness (run.py refuses a DXF job without one); read for its profiles
        # alone (``cam features``) the drawing stays flat, at z = 0.
        return _read_dxf(document, thickness=float(sheet_thickness_mm) if sheet_thickness_mm is not None else 0.0)
    suffix = document.suffix.lower()
    if suffix not in PART_SUFFIXES:
        raise CamJobError(f"this command takes a {'/'.join((*PART_SUFFIXES, *DXF_SUFFIXES))} document: {document}")
    what = "xbf" if suffix == ".xbf" else "STEP"
    if not document.is_file():
        raise CamJobError(f"no {what} at {document}")
    from cadgen.engine.model import read_step, read_xbf

    try:
        tree = (read_xbf if suffix == ".xbf" else read_step)(document)
    except (RuntimeError, ValueError, OSError) as exc:
        # An empty, truncated or foreign file: the reader's first line says why.
        why = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        raise CamJobError(f"{document.name} is not {'an' if what == 'xbf' else 'a'} {what} that can be read "
                          f"({why[:200]}); export it again from the CAD tool") from None
    read = _Document(document, tree)
    if occurrence:
        try:
            hit = read.resolve(occurrence)
        except ValueError as exc:
            raise CamJobError(f"occurrence {occurrence}: {exc}") from None
        if hit.kind is not None or "prototype" not in hit.node.payload:
            raise CamJobError(f"{occurrence} is not a part occurrence of {document.name}; the parts are "
                              f"{', '.join(_part_paths(read))}")
    else:
        if len(read.parts) != 1:
            raise CamJobError(f"the document has {len(read.parts)} parts; CAM machines one part: pass --occurrence "
                              f"{' or '.join(_part_paths(read)[:4])}")
        hit = read.resolve(_part_paths(read)[0])
    node = hit.node.payload["node"]
    return _tessellate(document, read, hit, node.located(node.global_location), deflection_mm or DEFAULT_DEFLECTION_MM)


def _part_paths(read: _Document) -> list[str]:
    from cadgen.engine.refs import path_text, structure_tree

    root = structure_tree(read.structure)
    return [path_text(root, part) for part in root.parts()]


#: The largest part (mm on any axis) CAM reads: ten metres, past any machine bed (job.MAX_STOCK_MM). A bigger one is
#: a units slip (a drawing in metres read as mm), and meshing it to a hundredth of a millimetre would fill the memory.
MAX_PART_MM = 10_000.0


def _check_size(what: str, box) -> None:
    """Refuse a part (a build123d BoundBox, or ``(low, high)`` points) bigger than :data:`MAX_PART_MM`, or with no
    extent at all, before it is meshed."""
    if hasattr(box, "size"):
        size = (box.size.X, box.size.Y, box.size.Z)
    else:
        size = tuple(float(h) - float(l) for l, h in zip(*box))
    if not all(math.isfinite(v) for v in size):
        raise CamJobError(f"{what} has no finite size; export it again from the CAD tool")
    if max(size) > MAX_PART_MM:
        raise CamJobError(f"{what} is {max(size) / 1000:,.1f} m across; CAM machines parts up to "
                          f"{MAX_PART_MM / 1000:g} m: check the units (cadgen reads mm)")


def _surface_name(adaptor) -> str:
    from OCP.GeomAbs import GeomAbs_SurfaceType

    names = {
        GeomAbs_SurfaceType.GeomAbs_Plane: "plane", GeomAbs_SurfaceType.GeomAbs_Cylinder: "cylinder",
        GeomAbs_SurfaceType.GeomAbs_Cone: "cone", GeomAbs_SurfaceType.GeomAbs_Sphere: "sphere",
        GeomAbs_SurfaceType.GeomAbs_Torus: "torus", GeomAbs_SurfaceType.GeomAbs_BSplineSurface: "bspline",
        GeomAbs_SurfaceType.GeomAbs_BezierSurface: "bezier",
        GeomAbs_SurfaceType.GeomAbs_SurfaceOfRevolution: "revolution",
        GeomAbs_SurfaceType.GeomAbs_SurfaceOfExtrusion: "extrusion",
        GeomAbs_SurfaceType.GeomAbs_OffsetSurface: "offset",
    }
    return names.get(adaptor.GetType(), "other")


def _tessellate(path: Path, read: _Document, hit, shape, deflection: float) -> Part:
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    ref = hit.ref
    wrapped = shape.wrapped
    _check_size(f"{ref} of {path.name}", shape.bounding_box())
    BRepMesh_IncrementalMesh(wrapped, deflection, False, ANGULAR_DEFLECTION, True)
    # Ordinals as the engine numbers a part's elements: TopExp.MapShapes over its shape.
    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(wrapped, TopAbs_FACE, face_map)
    # A face's canonical ref: its name where the file gives it one, else its ordinal, under its owner as ``inspect``
    # spells it (the document's name for a document of one part).
    names = {int(o): text for o, text in read.prototypes[hit.node.payload["prototype"]]["faceNames"].items()}
    owner = read.resolve(f"{hit.path}/face 1").ref.rpartition("/")[0] if face_map.Extent() else ref
    vertices: list = []
    triangles: list = []
    owners: list = []
    faces: dict[int, FaceInfo] = {}
    offset = 0
    for ordinal in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(ordinal))
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        reversed_ = face.Orientation() == TopAbs_REVERSED
        bounds = None
        if triangulation is not None and triangulation.NbTriangles():
            transform = location.Transformation()
            nodes = np.empty((triangulation.NbNodes(), 3))
            for i in range(1, triangulation.NbNodes() + 1):
                p = triangulation.Node(i).Transformed(transform)
                nodes[i - 1] = (p.X(), p.Y(), p.Z())
            tris = np.empty((triangulation.NbTriangles(), 3), dtype=np.int64)
            for i in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(i).Get()
                tris[i - 1] = (a - 1, c - 1, b - 1) if reversed_ else (a - 1, b - 1, c - 1)
            vertices.append(nodes)
            triangles.append(tris + offset)
            owners.append(np.full(len(tris), ordinal, dtype=np.int64))
            offset += len(nodes)
            bounds = (tuple(float(v) for v in nodes.min(axis=0)), tuple(float(v) for v in nodes.max(axis=0)))
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centre = props.CentreOfMass()
        adaptor = BRepAdaptor_Surface(face)
        surface = _surface_name(adaptor)
        normal = axis = axis_point = radius = hole = None
        if surface == "plane":
            direction = adaptor.Plane().Axis().Direction()
            n = (direction.X(), direction.Y(), direction.Z())
            normal = tuple(-v for v in n) if reversed_ else n
            normal = tuple(round(float(v), 9) + 0.0 for v in normal)
        elif surface in ("cylinder", "cone"):
            ax = (adaptor.Cylinder() if surface == "cylinder" else adaptor.Cone()).Axis()
            d, p = ax.Direction(), ax.Location()
            axis = tuple(round(float(v), 9) + 0.0 for v in (d.X(), d.Y(), d.Z()))
            axis_point = (float(p.X()), float(p.Y()), float(p.Z()))
            if surface == "cylinder":
                radius = float(adaptor.Cylinder().Radius())
                # A hole's surface normal points at its axis: material is outside the cylinder.
                u = 0.5 * (adaptor.FirstUParameter() + adaptor.LastUParameter())
                v = 0.5 * (adaptor.FirstVParameter() + adaptor.LastVParameter())
                from OCP.gp import gp_Pnt, gp_Vec

                point, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
                adaptor.D1(u, v, point, du, dv)
                outward = du.Crossed(dv)
                if reversed_:
                    outward.Reverse()
                radial = gp_Vec(point.X() - p.X(), point.Y() - p.Y(), point.Z() - p.Z())
                axial = gp_Vec(d.X(), d.Y(), d.Z())
                radial = radial.Subtracted(axial.Multiplied(radial.Dot(axial)))
                hole = bool(outward.Dot(radial) < 0)
        element = names.get(ordinal) or f"face {ordinal}"
        faces[ordinal] = FaceInfo(
            ref=f"{owner}/{element}" if owner else element, ordinal=ordinal, surface=surface, area_mm2=float(props.Mass()),
            center_mm=(float(centre.X()), float(centre.Y()), float(centre.Z())), normal=normal, axis=axis,
            axis_point=axis_point, radius_mm=radius, hole=hole, bounds=bounds,
        )
    if not triangles:
        raise CamJobError(f"{ref} of {path.name} has no surface to machine")
    return Part(document=path, occurrence=ref, kind="step", vertices=np.vstack(vertices),
                triangles=np.vstack(triangles), face_of_triangle=np.concatenate(owners), faces=faces,
                deflection_mm=deflection, shape=shape, _document=read, _path=hit.path, _face_map=face_map)


# --- DXF -------------------------------------------------------------------------------------------------

#: The entities a drawing's outlines are drawn with: each is followed as a path.
DXF_CURVES = ("LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE")
#: Annotation a drawing may carry beside its outlines: skipped and counted, never cut. Anything else is refused.
DXF_ANNOTATIONS = ("TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION",
                   "LEADER", "MLEADER", "MULTILEADER", "HATCH")


def dxf_curves(path: Path, *, tolerance_mm: float = 0.01) -> tuple[list, dict[str, int]]:
    """Every curve a DXF's model space draws, ``([(points [(x, y)] mm, closed)], skipped {type: count})``.

    Blocks (``INSERT``) are expanded, nested ones too, with their placement, scale and rotation; its ``$INSUNITS``
    are honoured. Annotation (:data:`DXF_ANNOTATIONS`: text, dimensions, leaders, hatches) is skipped and counted;
    any other entity, or a curve that cannot be followed as a path, is refused naming its handle and type: a part
    is never cut with a piece of its drawing silently left out."""
    import ezdxf
    from ezdxf import path as dxf_path

    try:
        document = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as exc:
        raise CamJobError(f"{path.name} is not a readable DXF: {exc}") from None
    scale = {1: 25.4, 2: 304.8, 5: 10.0, 6: 1000.0}.get(int(document.header.get("$INSUNITS", 4) or 4), 1.0)
    # Its extent first, from control points (cheap): a drawing kilometres across is refused before it is flattened to
    # a hundredth of a millimetre.
    try:
        from ezdxf import bbox as dxf_bbox

        extents = dxf_bbox.extents(document.modelspace(), fast=True)
    except Exception:  # noqa: BLE001 - an entity ezdxf cannot bound is refused below, by the walk
        extents = None
    if extents is not None and extents.has_data:
        low, high = extents.extmin, extents.extmax
        _check_size(path.name, ((low.x * scale, low.y * scale), (high.x * scale, high.y * scale)))
    curves: list = []
    skipped: dict[str, int] = {}

    def named(entity, inside: str) -> str:
        handle = entity.dxf.get("handle")
        return f"{entity.dxftype()} {handle}" if handle else f"a {entity.dxftype()} in {inside}"

    def walk(entities, inside: str) -> None:
        for entity in entities:
            kind = entity.dxftype()
            if kind == "INSERT":
                block = f"block {entity.dxf.get('name', '?')} (INSERT {entity.dxf.get('handle') or inside})"
                try:
                    children = list(entity.virtual_entities())
                except Exception as exc:  # noqa: BLE001 - ezdxf's reason goes into the refusal
                    raise CamJobError(f"{path.name}: {block} cannot be expanded ({exc}); explode it in the "
                                      "drawing") from None
                attribs = len(getattr(entity, "attribs", ()) or ())
                if attribs:
                    skipped["ATTRIB"] = skipped.get("ATTRIB", 0) + attribs
                walk(children, block)
                continue
            if kind in DXF_ANNOTATIONS:
                skipped[kind] = skipped.get(kind, 0) + 1
                continue
            if kind not in DXF_CURVES:
                raise CamJobError(f"{path.name}: {named(entity, inside)} is not a curve that can be cut; draw the "
                                  f"outlines as {', '.join(DXF_CURVES[:-1]).lower()} or {DXF_CURVES[-1].lower()}s "
                                  "and delete it (text, dimensions and hatches are skipped)")
            try:
                points = [(v.x * scale, v.y * scale) for v in dxf_path.make_path(entity).flattening(tolerance_mm / scale)]
            except Exception as exc:  # noqa: BLE001 - ezdxf's reason goes into the refusal
                raise CamJobError(f"{path.name}: {named(entity, inside)} cannot be followed as a path ({exc}); redraw "
                                  "it as lines, arcs or a polyline") from None
            if len(points) < 2:
                continue
            closed = kind == "CIRCLE" or math.dist(points[0], points[-1]) <= 1e-6 * max(1.0, scale)
            curves.append((points, closed))

    walk(document.modelspace(), "model space")
    return curves, skipped


#: The key :func:`read_dxf_drawing` counts open curves under in its skipped dict: curves that close no profile.
OPEN_CURVES = "open curve"


def skipped_words(name: str, skipped: dict[str, int]) -> str:
    """``bracket.dxf: 2 TEXT and 1 DIMENSION skipped (annotation is not cut ...)``, or "". Open curves (that close no
    profile, :data:`OPEN_CURVES`) get their own sentence."""
    skipped = dict(skipped)
    stray = skipped.pop(OPEN_CURVES, 0)
    words = (f"{name}: {stray} open curve piece(s) close no profile and are not cut; close them, or delete them if "
             "they are construction lines") if stray else ""
    if not skipped:
        return words
    parts = [f"{count} {kind}" for kind, count in sorted(skipped.items())]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return (f"{name}: {listed} skipped (annotation is not cut; explode text to curves in the drawing to cut or "
            "engrave it)") + (f". {words}" if words else "")


def read_dxf_drawing(path: Path, *, tolerance_mm: float = 0.01) -> tuple[list, dict[str, int]]:
    """The DXF's closed regions as shapely polygons (mm), even-odd filled: closed polylines, circles, ellipses and
    splines as rings, open lines and arcs joined into rings where their ends meet; and what was skipped
    (:func:`dxf_curves`)."""
    import shapely

    curves, skipped = dxf_curves(path, tolerance_mm=tolerance_mm)
    rings: list = []
    loose: list = []
    for points, closed in curves:
        if closed and len(points) >= 4:
            ring = shapely.Polygon(points)
            rings.append(ring if ring.is_valid else ring.buffer(0))
        else:
            loose.append(shapely.LineString(points))
    if loose:
        noded = shapely.union_all(shapely.set_precision(shapely.GeometryCollection(loose), 1e-6))
        polygons, cuts, dangles, invalid = shapely.polygonize_full(shapely.get_parts(noded))
        rings.extend(shapely.get_parts(polygons))
        # What joined into no ring is not cut: counted, so the run says so rather than dropping it unseen.
        stray = [g for g in (*shapely.get_parts(cuts), *shapely.get_parts(dangles), *shapely.get_parts(invalid))
                 if g.length > 1e-6]
        if stray:
            skipped = {**skipped, OPEN_CURVES: len(stray)}
    filled = shapely.Polygon()
    for ring in rings:
        filled = filled.symmetric_difference(ring)
    return [p for p in shapely.get_parts(filled) if p.area > 1e-9], skipped


def read_dxf_profiles(path: Path, *, tolerance_mm: float = 0.01) -> list:
    """The DXF's closed regions as shapely polygons (:func:`read_dxf_drawing` without the skipped count)."""
    return read_dxf_drawing(path, tolerance_mm=tolerance_mm)[0]


def _read_dxf(path: Path, *, thickness: float) -> Part:
    import numpy as np
    import shapely

    profiles, skipped = read_dxf_drawing(path)
    if not profiles:
        raise CamJobError(f"{path.name} has no closed profile to cut; close its outlines (polylines or circles)")
    vertices: list = []
    triangles: list = []
    offset = 0
    for polygon in profiles:
        tris = shapely.get_parts(shapely.constrained_delaunay_triangles(polygon))
        for z, flip in ((thickness, False), (0.0, True)):
            for tri in tris:
                coords = np.asarray(tri.exterior.coords)[:3]
                e1, e2 = coords[1] - coords[0], coords[2] - coords[0]
                signed = e1[0] * e2[1] - e1[1] * e2[0]
                order = [0, 1, 2] if (signed > 0) != flip else [0, 2, 1]
                vertices.append(np.column_stack([coords[order], np.full(3, z)]))
                triangles.append(np.arange(3) + offset)
                offset += 3
        oriented = shapely.geometry.polygon.orient(polygon, 1.0)
        for ring in (oriented.exterior, *oriented.interiors):
            coords = np.asarray(ring.coords)
            for a, b in zip(coords[:-1], coords[1:]):
                quad = np.array([[a[0], a[1], 0.0], [b[0], b[1], 0.0], [b[0], b[1], thickness], [a[0], a[1], thickness]])
                vertices.append(quad)
                triangles.extend([np.array([0, 1, 2]) + offset, np.array([0, 2, 3]) + offset])
                offset += 4
    tri_array = np.vstack(triangles).astype(np.int64)
    return Part(document=path, occurrence="", kind="dxf", vertices=np.vstack(vertices), triangles=tri_array,
                face_of_triangle=np.zeros(len(tri_array), dtype=np.int64), faces={}, deflection_mm=0.01,
                profiles=profiles, notes=[note] if (note := skipped_words(path.name, skipped)) else [])
