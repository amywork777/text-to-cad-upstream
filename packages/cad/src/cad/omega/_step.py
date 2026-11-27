"""``step``: a GSL model written as a STEP solid that any CAD program opens, held to the model's field, as ``cad
gsl step FILE [OUT]`` does.

A field has no faces to write, so the solid is the model's mesh, each triangle a planar face of one closed shell
(a B-rep every CAD program reads as a solid body, with no surfaces fitted). A lattice meshes to hundreds of
thousands of triangles, about 2.5 kB of STEP each, so the mesh is first reduced (``fast_simplification``'s
quadric decimation) to the fewest triangles that stay within ``tolerance`` of the field, and held to it both
ways, as ``bake`` holds an exact part:

- **the field at the solid's surface**: at every vertex and the middle of every face, the model's field over its
  gradient's length, the distance to its surface to first order (a blend's or a lattice's field alone overstates it);
- **the model's surface to the solid**: points on the surface (omega's ``surface``) measured to the faces.

The mesh as meshed is held first: no reduction is nearer the model than it. Where gsl's own depth (9) is not within
``tolerance`` (a lattice cut by a flat face leaves vertices off its sharp edges), the model is meshed one deeper;
where that is not either, or a depth was named, nothing is written, and the departure is said. Then each reduction is tried
from the fewest triangles up, and the first that is closed, manifold and within ``tolerance`` both ways is
written (the mesh itself where none is). The STEP is read back before it is handed over: one valid solid, its
volume the mesh's.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from cad.results import CheckResult

__all__ = ["DEFAULT_TOLERANCE", "step"]

#: mm the STEP's surface may depart from the model's, either way, when no tolerance is named.
DEFAULT_TOLERANCE = 0.2
#: The fractions of the mesh's triangles tried, fewest first; the mesh itself (1.0) last.
_KEEPS = (0.02, 0.04, 0.07, 0.12, 0.2, 0.35, 0.6, 1.0)
#: The relative difference allowed between the STEP read back and the mesh it was made from.
_VOLUME_READBACK = 1e-3


def _distance(session: Any, text: str, points: Any, defs: str) -> Any:
    """How far each of ``points`` is from the model's surface: the field over its gradient's length, a first-order
    distance that a blend or a lattice, whose field is no true distance, does not overstate. A gradient under 0.2
    (a crease of the field) is taken as 0.2, which overstates rather than hides."""
    import numpy as np

    from cad.omega._check import queryable
    from cad.omega._fit import _BATCH, _union

    code = queryable(text)
    shape = _union(session, code, defs)
    out = np.empty(len(points))
    for start in range(0, len(points), _BATCH):
        chunk = points[start:start + _BATCH]
        request: dict[str, Any] = {"op": "eval", "code": code, "exprs": [shape], "points": chunk.tolist()}
        if defs:
            request["defs"] = defs
        group = session.request(request)["groups"][0]
        values = np.abs(np.asarray(group["values"][0], np.float64))
        lengths = np.linalg.norm(np.asarray(group["gradients"][0], np.float64).reshape(-1, 3), axis=1)
        out[start:start + len(chunk)] = values / np.maximum(lengths, 0.2)
    return out


def _welded(triangles: Any) -> tuple[Any, Any]:
    """``triangles`` (n, 3, 3) as vertices and faces, with equal points made one vertex."""
    import numpy as np

    points = triangles.reshape(-1, 3)
    _keys, first, index = np.unique(np.round(points / 1e-6).astype(np.int64), axis=0, return_index=True,
                                    return_inverse=True)
    return points[first], index.reshape(-1, 3)


def _reduced(vertices: Any, faces: Any, keep: float) -> tuple[Any, Any]:
    import numpy as np

    if keep >= 1.0:
        return vertices, faces
    import fast_simplification

    v, f = fast_simplification.simplify(vertices.astype(np.float32), faces.astype(np.int32), target_reduction=1 - keep)
    f = f.astype(np.int64)
    # A thin sheet collapsed onto itself leaves a fin: one triangle twice, wound opposite ways, enclosing nothing,
    # whose edges four faces share. Both copies go, and the shell is closed and manifold again.
    _sets, index, count = np.unique(np.sort(f, axis=1), axis=0, return_inverse=True, return_counts=True)
    f = f[count[index.reshape(-1)] == 1]
    used, f = np.unique(f, return_inverse=True)
    return v.astype(np.float64)[used], f.reshape(-1, 3)


def _write_faceted(vertices: Any, faces: Any, name: str, path: Path) -> None:
    """``faces`` as one AP214 ``FACETED_BREP``: a closed shell of planar faces, each a ``POLY_LOOP`` of three shared
    points on its own plane. About a sixth of the bytes of the same solid as an ``ADVANCED_BREP``, whose faces
    and edges each carry their own geometry."""
    import numpy as np

    a, b, c = (vertices[faces[:, k]] for k in range(3))
    normal = np.cross(b - a, c - a)
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    along = b - a
    along /= np.linalg.norm(along, axis=1)[:, None]
    lines: list[str] = []

    def add(entity: str) -> str:
        lines.append(f"#{len(lines) + 1}={entity};")
        return f"#{len(lines)}"

    def direction(xyz: Any) -> str:
        return add("DIRECTION('',(%.7f,%.7f,%.7f))" % tuple(xyz))

    label = "".join(ch for ch in name if ch.isascii() and ch.isprintable() and ch not in "'\\") or "part"
    context = add("APPLICATION_CONTEXT('automotive_design')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{context})")
    product_context = add(f"PRODUCT_CONTEXT('',{context},'mechanical')")
    product = add(f"PRODUCT('{label}','{label}','',({product_context}))")
    formation = add(f"PRODUCT_DEFINITION_FORMATION('','',{product})")
    definition_context = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{context},'design')")
    definition = add(f"PRODUCT_DEFINITION('design','',{formation},{definition_context})")
    shape = add(f"PRODUCT_DEFINITION_SHAPE('','',{definition})")
    points = [add("CARTESIAN_POINT('',(%.5f,%.5f,%.5f))" % xyz) for xyz in map(tuple, vertices.tolist())]
    bounded = []
    for (i, j, k), n, d in zip(faces.tolist(), normal.tolist(), along.tolist()):
        loop = add(f"POLY_LOOP('',({points[i]},{points[j]},{points[k]}))")
        bound = add(f"FACE_OUTER_BOUND('',{loop},.T.)")
        frame = add(f"AXIS2_PLACEMENT_3D('',{points[i]},{direction(n)},{direction(d)})")
        plane = add(f"PLANE('',{frame})")
        bounded.append(add(f"FACE_SURFACE('',({bound}),{plane},.T.)"))
    shell = add(f"CLOSED_SHELL('',({','.join(bounded)}))")
    brep = add(f"FACETED_BREP('{label}',{shell})")
    zero = add("CARTESIAN_POINT('',(0.,0.,0.))")
    origin = add(f"AXIS2_PLACEMENT_3D('',{zero},{direction((0, 0, 1))},{direction((1, 0, 0))})")
    mm = add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    radian = add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    steradian = add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    accuracy = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),{mm},'distance_accuracy_value','')")
    units = add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({accuracy})) "
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{radian},{steradian})) REPRESENTATION_CONTEXT('',''))")
    representation = add(f"FACETED_BREP_SHAPE_REPRESENTATION('{label}',({brep},{origin}),{units})")
    add(f"SHAPE_DEFINITION_REPRESENTATION({shape},{representation})")
    header = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('a GSL model as a faceted solid'),'2;1');\n"
              f"FILE_NAME('{label}.step','',(''),(''),'cad gsl step','','');\n"
              "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
    path.write_text(header + "\n".join(lines) + "\nENDSEC;\nEND-ISO-10303-21;\n", encoding="ascii")


def step(path: Path, out: Path | None = None, *, define: tuple[str, ...] = (), depth: int | None = None,
         tolerance: float = DEFAULT_TOLERANCE, strict: bool = False, verbose: bool = False) -> CheckResult:
    import os

    import numpy as np

    from cad._internal.atomic_replace import replace_atomic
    from cad._internal.findings import FindingsReport
    from cad._internal.validation_door import display_path, failed, resolved_target, result_from_findings
    from cad.omega._check import measure
    from cad.omega._fit import _concept_surface, distance_to_triangles
    from cad.omega._mesh import DEFAULT_DEPTH, mesh, read_glb, statements
    from cad.omega._program import find_gsl

    target = resolved_target(path, label="omega")
    if not tolerance > 0:
        return failed(target, f"tolerance is the mm the STEP may depart from the model, above 0, not {tolerance}")
    where = display_path(target)
    written = Path(out).expanduser().absolute() if out is not None else target.with_suffix(".step")
    findings = FindingsReport()
    defs = statements(tuple(define))
    text = target.read_text(encoding="utf-8", errors="replace")

    import omega_core

    tried: list[dict[str, Any]] = []
    # gsl's own depth first; where its mesh is further off than the tolerance (sharp edges where a lattice meets a
    # flat face), one deeper, which halves the cell. A depth that was asked for is the only one tried.
    depths = (depth,) if depth is not None else (DEFAULT_DEPTH, DEFAULT_DEPTH + 1)
    chosen = meshed = vertices = faces = surface = None
    for each in depths:
        meshed = mesh(target, define=define, depth=each, strict=strict, verbose=verbose)
        if not meshed.ok:
            return meshed
        vertices, faces = _welded(read_glb(Path(meshed.measurements["glb"])))
        with omega_core.Session(source_paths=(target.parent,), program=str(find_gsl())) as session:
            low, high = vertices.min(axis=0), vertices.max(axis=0)
            surface = _concept_surface(session, text, defs, (low - 1.0, high + 1.0))

            def held(keep: float, at: int = each) -> tuple[Any, Any, dict, dict]:
                v, f = _reduced(vertices, faces, keep)
                shape = measure(v[f])
                said: dict[str, Any] = {"depth": at, "triangles": int(len(f)), "closed": not (
                    shape["open_edges"] or shape["non_manifold_edges"] or shape["volume_mm3"] <= 0)}
                if said["closed"]:
                    field = _distance(session, text, np.concatenate([v, v[f].mean(axis=1)]), defs)
                    back = distance_to_triangles(surface, v[f]) if len(surface) else np.full(1, np.inf)
                    said.update(field_at_step_mm=float(field.max()), surface_to_step_mm=float(back.max()),
                                departure_mm=float(max(field.max(), back.max())),
                                beyond_tolerance=int((field > tolerance).sum() + (back > tolerance).sum()))
                    if verbose:
                        print(f"[omega] depth {at}, {len(f)} triangles: field {said['field_at_step_mm']:.3f} mm, "
                              f"surface {said['surface_to_step_mm']:.3f} mm", file=sys.stderr)
                tried.append(said)
                return v, f, shape, said

            # The mesh as meshed first: what no reduction can be better than.
            baseline = held(1.0)
            if baseline[3]["closed"] and baseline[3]["departure_mm"] <= tolerance:
                chosen = baseline
                for keep in _KEEPS:
                    found = held(keep)
                    if found[3]["closed"] and found[3]["departure_mm"] <= tolerance:
                        chosen = found
                        break
        if chosen is not None:
            break
    measurements: dict[str, Any] = {"tolerance_mm": tolerance, "meshed_triangles": int(len(faces)),
                                    "depth": meshed.measurements.get("depth"), "tried": tried,
                                    "surface_points": int(len(surface))}
    if chosen is None:
        meshed_said = [each for each in tried if each["triangles"] == len(faces)][-1]
        departure = meshed_said.get("departure_mm", float("inf"))
        findings.add("error", "step_outside_tolerance", f"gsl's own mesh at depth {measurements['depth']} departs "
                     f"{departure:.3g} mm from the model at {meshed_said.get('beyond_tolerance', 0)} of its points, so "
                     f"no STEP of it is within {tolerance:g} mm", path=where,
                     hint=f"--depth {measurements['depth'] + 1} (one more halves the cell, about four times the time "
                          f"and memory) or --tolerance {departure:.2g}")
        result = result_from_findings(target, findings.deduplicated(), strict=strict, summary="")
        return CheckResult(ok=False, path=result.path, findings=result.findings, summary=result.summary,
                           measurements=measurements)
    v, f, shape, said = chosen
    field, back = said["field_at_step_mm"], said["surface_to_step_mm"]

    from cad._internal.step_readback import read_back

    written.parent.mkdir(parents=True, exist_ok=True)
    making = written.with_name(f"{written.stem}.{os.getpid()}.making.step")
    try:
        _write_faceted(v, f, target.stem, making)
        read = read_back(making)
        if read is None:
            return failed(target, f"the STEP written does not read back: {display_path(written)}",
                          code="step_reads_back_wrong")
        valid, volume = read
        if not valid or abs(volume - shape["volume_mm3"]) > _VOLUME_READBACK * shape["volume_mm3"]:
            findings.add("error", "step_reads_back_wrong", f"the STEP read back is {'a valid' if valid else 'no valid'} "
                         f"solid of {volume:.6g} mm3, from a mesh of {shape['volume_mm3']:.6g} mm3", path=where)
            result = result_from_findings(target, findings.deduplicated(), strict=strict, summary="")
            return CheckResult(ok=False, path=result.path, findings=result.findings, summary=result.summary,
                               measurements=measurements)
        replace_atomic(making, written)
    finally:
        making.unlink(missing_ok=True)

    measurements.update(step=str(written), faces=int(len(f)), volume_mm3=volume,
                        field_volume_mm3=meshed.measurements.get("field_volume_mm3"),
                        field_at_step_mm=field, surface_to_step_mm=back, bytes=written.stat().st_size,
                        bbox_min=shape["bbox_min"], bbox_max=shape["bbox_max"])
    summary = (f"OK {where} -> {display_path(written)}: one solid of {len(f)} planar faces, {volume:.6g} mm3, "
               f"within {max(field, back):.3g} mm of the model (field at its surface {field:.3g} mm, the model's "
               f"surface to it {back:.3g} mm), {written.stat().st_size / 1e6:.1f} MB")
    result = result_from_findings(target, findings.deduplicated(), strict=strict, summary=summary)
    return CheckResult(ok=result.ok, path=result.path, findings=result.findings, summary=result.summary,
                       measurements=measurements)
