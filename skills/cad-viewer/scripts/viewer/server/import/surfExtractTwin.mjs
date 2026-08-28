// The .surf extractor TWIN: WASM OCCT edition of
// packages/cadgen/src/cadgen/_internal/surface_extract.py.
//
// This is deliberately DUPLICATED logic (the approved trade in
// design/standalone-viewer.md): the native extractor runs in-process on live
// shapes at generation time and must stay Python; this twin exists so a
// Python-less viewer can import a foreign STEP. The two are kept honest by
// the cross-implementation conformance suite
// (tests/python/packages/cadgen/test_surf_extractor_conformance.py) over
// models/conformance — every semantic change to either side must land in both
// and pass it. Comments below reference the Python lines they mirror; keep the
// structure parallel so diffs stay reviewable.
//
// Output contract: identical SURF container semantics (magic/version/JSON
// index/f32 bin), same face/edge ordinals (TopExp.MapShapes order), same
// classification and selector-metadata columns. Byte identity with Python is
// NOT required (GeomConvert differs across kernel versions); geometric
// equivalence within the suite's tolerances is.
import { ref } from "./ocKernel.mjs";

export const SURF_MAGIC = "SURF";
export const SURF_VERSION = 2;

// Mirrors cadgen._internal.glb_topology (pinned there; a drift fails the
// conformance suite's classification comparison).
const STEP_EDGE_FLAGS = {
  DEGENERATE: 1 << 1,
  SEAM: 1 << 2,
  NOT_REFERENCEABLE: 1 << 3,
  BOUNDARY: 1 << 4,
  NON_MANIFOLD: 1 << 5,
  HARD: 1 << 6,
  TANGENT: 1 << 7,
  UNKNOWN_CONTINUITY: 1 << 8,
};
const VISIBILITY = {
  FEATURE: "feature",
  TANGENT: "tangent",
  SEAM: "seam",
  DEGENERATE: "degenerate",
  BOUNDARY: "boundary",
  NON_MANIFOLD: "nonManifold",
  UNKNOWN: "unknown",
};
const EDGE_ANGULAR_TOLERANCE_DEG = 2;
const EDGE_SAMPLE_COUNT = 3;

export class Unextractable extends Error {}

// The single f32 buffer; append() returns [offset, count] refs. (py: _Bin)
class Bin {
  constructor() {
    this.values = [];
  }

  append(floats) {
    const offset = this.values.length;
    for (const value of floats) {
      this.values.push(Number(value));
    }
    return [offset, this.values.length - offset];
  }

  payload() {
    return Buffer.from(new Float32Array(this.values).buffer);
  }
}

function xyz(p) {
  return [p.X(), p.Y(), p.Z()];
}

function frame(ax3) {
  return {
    origin: xyz(ax3.Location()),
    xdir: xyz(ax3.XDirection()),
    ydir: xyz(ax3.YDirection()),
    zdir: xyz(ax3.Direction()),
  };
}

// GeomAbs enum -> the manifest spelling ("plane", "bsplinesurface", ...).
// (py: _enum_name_geomabs; embind enums stringify via constructor.name lookup)
function enumNameGeomAbs(oc, enumValue) {
  for (const [name, value] of Object.entries(oc.GeomAbs_SurfaceType)) {
    if (value === enumValue && name.startsWith("GeomAbs_")) {
      return name.slice("GeomAbs_".length).toLowerCase();
    }
  }
  for (const [name, value] of Object.entries(oc.GeomAbs_CurveType)) {
    if (value === enumValue && name.startsWith("GeomAbs_")) {
      return name.slice("GeomAbs_".length).toLowerCase();
    }
  }
  return "othersurface";
}

function uvBounds(oc, face) {
  const u0 = ref();
  const u1 = ref();
  const v0 = ref();
  const v1 = ref();
  oc.BRepTools.UVBounds_1(face, u0, u1, v0, v1);
  return [u0.current, u1.current, v0.current, v1.current];
}

function bndBox(oc, topo) {
  try {
    const box = new oc.Bnd_Box_1();
    oc.BRepBndLib.Add(topo, box, false);
    if (box.IsVoid()) {
      return null;
    }
    const xmin = ref();
    const ymin = ref();
    const zmin = ref();
    const xmax = ref();
    const ymax = ref();
    const zmax = ref();
    box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    return [xmin.current, ymin.current, zmin.current, xmax.current, ymax.current, zmax.current];
  } catch {
    return null;
  }
}

// (py: _face_metrics)
function faceMetrics(oc, face) {
  const metrics = {};
  try {
    const props = new oc.GProp_GProps_1();
    oc.BRepGProp.SurfaceProperties_1(face, props, false, false);
    metrics.area = props.Mass();
    metrics.center = xyz(props.CentreOfMass());
  } catch {
    // metrics are best-effort, matching the producer
  }
  const box = bndBox(oc, face);
  if (box !== null) {
    metrics.bbox = box;
  }
  return metrics;
}

// (py: _edge_metrics)
function edgeMetrics(oc, edge) {
  const metrics = {};
  try {
    const props = new oc.GProp_GProps_1();
    oc.BRepGProp.LinearProperties(edge, props, false, false);
    metrics.length = props.Mass();
    metrics.center = xyz(props.CentreOfMass());
  } catch {
    // best-effort
  }
  const box = bndBox(oc, edge);
  if (box !== null) {
    metrics.bbox = box;
  }
  return metrics;
}

// (py: _assert_surface_covers_face — the v14 flying-geometry guard)
function assertSurfaceCoversFace(payload, u0, u1, v0, v1, bin) {
  if (payload.kind !== "nurbs") {
    return;
  }
  const values = bin.values;
  const [kuOff, kuLen] = payload.knotsU;
  const [kvOff, kvLen] = payload.knotsV;
  const firstU = values[kuOff];
  const lastU = values[kuOff + kuLen - 1];
  const firstV = values[kvOff];
  const lastV = values[kvOff + kvLen - 1];
  const epsU = Math.max(Math.abs(u1 - u0), 1.0) * 1e-6;
  const epsV = Math.max(Math.abs(v1 - v0), 1.0) * 1e-6;
  if (u0 < firstU - epsU || u1 > lastU + epsU || v0 < firstV - epsV || v1 > lastV + epsV) {
    throw new Unextractable(
      `surface domain [${firstU}, ${lastU}]x[${firstV}, ${lastV}] does not cover ` +
        `face UV [${u0}, ${u1}]x[${v0}, ${v1}] — evaluation would extrapolate`,
    );
  }
}

// (py: _nurbs_surface_payload) — surface is a raw Geom_BSplineSurface object.
function nurbsSurfacePayload(surface, bin) {
  const nu = surface.NbUPoles();
  const nv = surface.NbVPoles();
  const poles = [];
  const weights = [];
  const rational = surface.IsURational() || surface.IsVRational();
  for (let i = 1; i <= nu; i += 1) {
    for (let j = 1; j <= nv; j += 1) {
      const pole = surface.Pole(i, j);
      poles.push(pole.X(), pole.Y(), pole.Z());
      if (rational) {
        weights.push(surface.Weight(i, j));
      }
    }
  }
  const flatKnots = (countFn, knotFn, multFn) => {
    const flat = [];
    for (let k = 1; k <= countFn(); k += 1) {
      const knot = knotFn(k);
      const mult = multFn(k);
      for (let m = 0; m < mult; m += 1) {
        flat.push(knot);
      }
    }
    return flat;
  };
  const payload = {
    kind: "nurbs",
    degU: surface.UDegree(),
    degV: surface.VDegree(),
    nu,
    nv,
    periodicU: Boolean(surface.IsUPeriodic()),
    periodicV: Boolean(surface.IsVPeriodic()),
    poles: bin.append(poles),
    knotsU: bin.append(
      flatKnots(() => surface.NbUKnots(), (k) => surface.UKnot(k), (k) => surface.UMultiplicity(k)),
    ),
    knotsV: bin.append(
      flatKnots(() => surface.NbVKnots(), (k) => surface.VKnot(k), (k) => surface.VMultiplicity(k)),
    ),
  };
  if (rational) {
    payload.weights = bin.append(weights);
  }
  return payload;
}

function downcastBSplineSurface(oc, geomSurfaceHandle) {
  try {
    const handle = oc.Handle_Geom_BSplineSurface_2(
      // DownCast pattern below is version-dependent; the caller try/catches.
      geomSurfaceHandle,
    );
    return handle && !handle.IsNull() ? handle.get() : null;
  } catch {
    return null;
  }
}

// (py: _surface_payload)
function surfacePayload(oc, face, bin) {
  const adaptor = new oc.BRepAdaptor_Surface_2(face, true);
  const kind = adaptor.GetType();
  const T = oc.GeomAbs_SurfaceType;
  if (kind === T.GeomAbs_Plane) {
    return { kind: "plane", ...frame(adaptor.Plane().Position()) };
  }
  if (kind === T.GeomAbs_Cylinder) {
    const cylinder = adaptor.Cylinder();
    return { kind: "cylinder", radius: cylinder.Radius(), ...frame(cylinder.Position()) };
  }
  if (kind === T.GeomAbs_Cone) {
    const cone = adaptor.Cone();
    return {
      kind: "cone",
      radius: cone.RefRadius(),
      semiAngle: cone.SemiAngle(),
      ...frame(cone.Position()),
    };
  }
  if (kind === T.GeomAbs_Sphere) {
    const sphere = adaptor.Sphere();
    return { kind: "sphere", radius: sphere.Radius(), ...frame(sphere.Position()) };
  }
  if (kind === T.GeomAbs_Torus) {
    const torus = adaptor.Torus();
    return {
      kind: "torus",
      majorRadius: torus.MajorRadius(),
      minorRadius: torus.MinorRadius(),
      ...frame(torus.Position()),
    };
  }
  // PARAMETRIZATION IS PART OF THE CONTRACT (py lines 250-272): swept kinds
  // carry axis + profile; SurfaceToBSplineSurface would reparametrize them.
  if (kind === T.GeomAbs_SurfaceOfRevolution) {
    const axis = adaptor.AxeOfRevolution();
    // BasisCurve returns a Handle_Adaptor3d_Curve; the adaptor itself is inside.
    const basis = basisCurvePayload(oc, adaptor.BasisCurve().get(), bin);
    return {
      kind: "revolution",
      origin: xyz(axis.Location()),
      dir: xyz(axis.Direction()),
      profile: basis,
    };
  }
  if (kind === T.GeomAbs_SurfaceOfExtrusion) {
    const basis = basisCurvePayload(oc, adaptor.BasisCurve().get(), bin);
    return { kind: "extrusion", dir: xyz(adaptor.Direction()), profile: basis };
  }
  const surfaceHandle = oc.BRep_Tool.Surface_2(face);
  if (!surfaceHandle || surfaceHandle.IsNull()) {
    throw new Unextractable("face with no surface");
  }
  if (kind === T.GeomAbs_BSplineSurface || kind === T.GeomAbs_BezierSurface) {
    // Native NURBS direct copy — valid only when the face's UV range sits
    // inside the clamped domain (py lines 276-310; the v14 periodic trap).
    // Downcasts go through DynamicType names: version-portable, no Handle
    // casting gymnastics.
    let native = surfaceHandle.get();
    if (native.DynamicType().get().Name() === "Geom_RectangularTrimmedSurface") {
      native = native.BasisSurface().get();
    }
    if (native.DynamicType().get().Name() === "Geom_BSplineSurface") {
      const nurbsHandle = native.Copy();
      const nurbs = nurbsHandle.get ? nurbsHandle.get() : nurbsHandle;
      if (nurbs.IsUPeriodic()) {
        nurbs.SetUNotPeriodic();
      }
      if (nurbs.IsVPeriodic()) {
        nurbs.SetVNotPeriodic();
      }
      const [u0, u1, v0, v1] = uvBounds(oc, face);
      const epsU = Math.max(Math.abs(u1 - u0), 1.0) * 1e-9;
      const epsV = Math.max(Math.abs(v1 - v0), 1.0) * 1e-9;
      if (
        u0 >= nurbs.UKnot(1) - epsU &&
        u1 <= nurbs.UKnot(nurbs.NbUKnots()) + epsU &&
        v0 >= nurbs.VKnot(1) - epsV &&
        v1 <= nurbs.VKnot(nurbs.NbVKnots()) + epsV
      ) {
        return nurbsSurfacePayload(nurbs, bin);
      }
    }
    // Trim + convert (segmenting preserves parametrization).
    try {
      const [u0, u1, v0, v1] = uvBounds(oc, face);
      const bounded = new oc.Geom_RectangularTrimmedSurface_1(surfaceHandle, u0, u1, v0, v1, true, true);
      const boundedHandle = new oc.Handle_Geom_Surface_2(bounded);
      const nurbs = oc.GeomConvert.SurfaceToBSplineSurface(boundedHandle).get();
      if (nurbs.IsUPeriodic()) {
        nurbs.SetUNotPeriodic();
      }
      if (nurbs.IsVPeriodic()) {
        nurbs.SetVNotPeriodic();
      }
      return nurbsSurfacePayload(nurbs, bin);
    } catch (error) {
      if (error instanceof Unextractable) throw error;
      throw new Unextractable(`NURBS conversion failed: ${error?.message || error}`);
    }
  }
  // Exotic kinds: parametrization-preserving approximation (py lines 322-343).
  try {
    const [u0, u1, v0, v1] = uvBounds(oc, face);
    const bounded = new oc.Geom_RectangularTrimmedSurface_1(surfaceHandle, u0, u1, v0, v1, true, true);
    const boundedHandle = new oc.Handle_Geom_Surface_2(bounded);
    const approx = new oc.GeomConvert_ApproxSurface_1(
      boundedHandle, 1e-4, oc.GeomAbs_Shape.GeomAbs_C1, oc.GeomAbs_Shape.GeomAbs_C1, 14, 14, 100, 0,
    );
    if (!approx.IsDone()) {
      throw new Unextractable("surface approximation did not converge");
    }
    const nurbs = approx.Surface().get();
    if (nurbs.IsUPeriodic()) {
      nurbs.SetUNotPeriodic();
    }
    if (nurbs.IsVPeriodic()) {
      nurbs.SetVNotPeriodic();
    }
    return nurbsSurfacePayload(nurbs, bin);
  } catch (error) {
    if (error instanceof Unextractable) throw error;
    throw new Unextractable(`surface approximation failed: ${error?.message || error}`);
  }
}

// (py: _basis_curve_payload)
function basisCurvePayload(oc, basisAdaptor, bin) {
  const kind = basisAdaptor.GetType();
  const first = basisAdaptor.FirstParameter();
  const last = basisAdaptor.LastParameter();
  const T = oc.GeomAbs_CurveType;
  if (kind === T.GeomAbs_Line) {
    const line = basisAdaptor.Line();
    return { kind: "line", origin: xyz(line.Location()), dir: xyz(line.Direction()), range: [first, last] };
  }
  if (kind === T.GeomAbs_Circle) {
    const circle = basisAdaptor.Circle();
    return { kind: "circle", radius: circle.Radius(), ...frame(circle.Position()), range: [first, last] };
  }
  if (kind === T.GeomAbs_Ellipse) {
    const ellipse = basisAdaptor.Ellipse();
    return {
      kind: "ellipse",
      majorRadius: ellipse.MajorRadius(),
      minorRadius: ellipse.MinorRadius(),
      ...frame(ellipse.Position()),
      range: [first, last],
    };
  }
  if (kind === T.GeomAbs_BSplineCurve) {
    let bspline = basisAdaptor.BSpline().get();
    let period = null;
    if (bspline.IsPeriodic()) {
      // Clamp a COPY (py lines 370-379): SetNotPeriodic on the adaptor's own
      // handle would rewrite the shape being extracted.
      period = bspline.Period();
      bspline = bspline.Copy().get();
      bspline.SetNotPeriodic();
    }
    return bsplineCurve3Payload(bspline, bin, period);
  }
  if (kind === T.GeomAbs_BezierCurve) {
    try {
      const bspline = oc.GeomConvert.CurveToBSplineCurve(
        new oc.Handle_Geom_Curve_2(basisAdaptor.Bezier().get()),
        oc.Convert_ParameterisationType.Convert_TgtThetaOver2,
      ).get();
      return bsplineCurve3Payload(bspline, bin, null);
    } catch (error) {
      throw new Unextractable(`basis bezier conversion failed: ${error?.message || error}`);
    }
  }
  try {
    const curve = basisAdaptor.Curve(); // Handle_Geom_Curve
    const trimmed = new oc.Geom_TrimmedCurve(curve, first, last, true, true);
    const approx = new oc.GeomConvert_ApproxCurve_1(
      new oc.Handle_Geom_Curve_2(trimmed), 1e-5, oc.GeomAbs_Shape.GeomAbs_C1, 32, 14,
    );
    if (!approx.IsDone()) {
      throw new Unextractable("basis curve approximation did not converge");
    }
    const bspline = approx.Curve().get();
    if (bspline.IsPeriodic()) {
      bspline.SetNotPeriodic();
    }
    return bsplineCurve3Payload(bspline, bin, null);
  } catch (error) {
    if (error instanceof Unextractable) throw error;
    throw new Unextractable(`basis curve conversion failed: ${error?.message || error}`);
  }
}

// (py: _bspline_curve3_payload)
function bsplineCurve3Payload(bspline, bin, period) {
  const poles = [];
  const weights = [];
  const rational = bspline.IsRational();
  for (let i = 1; i <= bspline.NbPoles(); i += 1) {
    const pole = bspline.Pole(i);
    poles.push(pole.X(), pole.Y(), pole.Z());
    if (rational) {
      weights.push(bspline.Weight(i));
    }
  }
  const flat = [];
  for (let k = 1; k <= bspline.NbKnots(); k += 1) {
    const knot = bspline.Knot(k);
    const mult = bspline.Multiplicity(k);
    for (let m = 0; m < mult; m += 1) {
      flat.push(knot);
    }
  }
  const payload = {
    kind: "bspline",
    deg: bspline.Degree(),
    n: bspline.NbPoles(),
    periodic: Boolean(bspline.IsPeriodic()),
    poles: bin.append(poles),
    knots: bin.append(flat),
    range: [bspline.FirstParameter(), bspline.LastParameter()],
  };
  if (period !== null && period !== undefined) {
    payload.period = Number(period);
  }
  if (rational) {
    payload.weights = bin.append(weights);
  }
  return payload;
}

// (py: _curve2d_payload)
function curve2dPayload(oc, edge, face, bin) {
  // OCCT's (E, F, first, last) overload is unbound in this build, and the
  // out-handle form returns the edge's FIRST pcurve regardless of face — the
  // adaptor is the face-specific accessor with the same range semantics.
  const pcurveAdaptor = new oc.BRepAdaptor_Curve2d_2(edge, face);
  const curveHandle = pcurveAdaptor.Curve();
  if (!curveHandle || curveHandle.IsNull()) {
    throw new Unextractable("edge with no pcurve on its face");
  }
  const firstParameter = pcurveAdaptor.FirstParameter();
  const lastParameter = pcurveAdaptor.LastParameter();
  let bspline;
  try {
    const trimmed = new oc.Geom2d_TrimmedCurve(
      curveHandle, firstParameter, lastParameter, true, true,
    );
    bspline = oc.Geom2dConvert.CurveToBSplineCurve(
      new oc.Handle_Geom2d_Curve_2(trimmed),
      oc.Convert_ParameterisationType.Convert_TgtThetaOver2,
    ).get();
    if (bspline.IsPeriodic()) {
      bspline.SetNotPeriodic();
    }
  } catch (error) {
    throw new Unextractable(`pcurve conversion failed: ${error?.message || error}`);
  }
  const poles = [];
  const weights = [];
  const rational = bspline.IsRational();
  for (let i = 1; i <= bspline.NbPoles(); i += 1) {
    const pole = bspline.Pole(i);
    poles.push(pole.X(), pole.Y());
    if (rational) {
      weights.push(bspline.Weight(i));
    }
  }
  const flat = [];
  for (let k = 1; k <= bspline.NbKnots(); k += 1) {
    const knot = bspline.Knot(k);
    const mult = bspline.Multiplicity(k);
    for (let m = 0; m < mult; m += 1) {
      flat.push(knot);
    }
  }
  const payload = {
    deg: bspline.Degree(),
    n: bspline.NbPoles(),
    periodic: Boolean(bspline.IsPeriodic()),
    poles: bin.append(poles),
    knots: bin.append(flat),
    // The CONVERTED curve's own domain (py lines 474-478).
    range: [bspline.FirstParameter(), bspline.LastParameter()],
  };
  if (rational) {
    payload.weights = bin.append(weights);
  }
  const span = flat[flat.length - 1] - flat[0] || 1.0;
  if (
    payload.range[0] < flat[0] - 1e-6 * span ||
    payload.range[1] > flat[flat.length - 1] + 1e-6 * span
  ) {
    throw new Unextractable(
      `pcurve range ${JSON.stringify(payload.range)} escapes knot domain ` +
        `[${flat[0]}, ${flat[flat.length - 1]}] — evaluation would extrapolate`,
    );
  }
  return payload;
}

// (py: _curve3d_payload)
function curve3dPayload(oc, edge, bin) {
  if (oc.BRep_Tool.Degenerated(edge)) {
    return null;
  }
  const adaptor = new oc.BRepAdaptor_Curve_2(edge);
  const first = adaptor.FirstParameter();
  const last = adaptor.LastParameter();
  const kind = adaptor.GetType();
  const T = oc.GeomAbs_CurveType;
  if (kind === T.GeomAbs_Line) {
    const line = adaptor.Line();
    return { kind: "line", origin: xyz(line.Location()), dir: xyz(line.Direction()), range: [first, last] };
  }
  if (kind === T.GeomAbs_Circle) {
    const circle = adaptor.Circle();
    return { kind: "circle", radius: circle.Radius(), ...frame(circle.Position()), range: [first, last] };
  }
  if (kind === T.GeomAbs_Ellipse) {
    const ellipse = adaptor.Ellipse();
    return {
      kind: "ellipse",
      majorRadius: ellipse.MajorRadius(),
      minorRadius: ellipse.MinorRadius(),
      ...frame(ellipse.Position()),
      range: [first, last],
    };
  }
  const firstRef = ref();
  const lastRef = ref();
  const curveHandle = oc.BRep_Tool.Curve_2(edge, firstRef, lastRef);
  if (!curveHandle || curveHandle.IsNull()) {
    return null;
  }
  let bspline;
  try {
    const trimmed = new oc.Geom_TrimmedCurve(curveHandle, first, last, true, true);
    bspline = oc.GeomConvert.CurveToBSplineCurve(
      new oc.Handle_Geom_Curve_2(trimmed),
      oc.Convert_ParameterisationType.Convert_TgtThetaOver2,
    ).get();
    if (bspline.IsPeriodic()) {
      bspline.SetNotPeriodic();
    }
  } catch {
    return null;
  }
  return bsplineCurve3Payload(bspline, bin, null);
}

// --- classification (py: _classify_surf_edge + step_scene_geometry helpers) ---
function normalize(vector) {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  return length > 0 ? [vector[0] / length, vector[1] / length, vector[2] / length] : null;
}

function angleBetweenDeg(a, b) {
  if (!a || !b) {
    return null;
  }
  const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  return (Math.acos(dot) * 180) / Math.PI;
}

function faceNormalAtEdgeFraction(oc, edge, face, fraction) {
  const curve = new oc.BRepAdaptor_Curve2d_2(edge, face);
  const first = curve.FirstParameter();
  const last = curve.LastParameter();
  if (!Number.isFinite(first) || !Number.isFinite(last) || Math.abs(last - first) <= 1e-12) {
    return null;
  }
  const uv = curve.Value(first + (last - first) * fraction);
  const surface = new oc.BRepAdaptor_Surface_2(face, true);
  const props = new oc.BRepLProp_SLProps_2(surface, 1, 1e-6);
  props.SetParameters(uv.X(), uv.Y());
  if (!props.IsNormalDefined()) {
    return null;
  }
  const n = props.Normal();
  let normal = [n.X(), n.Y(), n.Z()];
  if (face.Orientation_1() === oc.TopAbs_Orientation.TopAbs_REVERSED) {
    normal = [-normal[0], -normal[1], -normal[2]];
  }
  return normalize(normal);
}

function edgeContinuityName(oc, edge, faces) {
  if (faces.length !== 2) {
    return "";
  }
  try {
    if (!oc.BRep_Tool.HasContinuity_1(edge, faces[0], faces[1])) {
      return "";
    }
    const continuity = oc.BRep_Tool.Continuity_1(edge, faces[0], faces[1]);
    for (const [name, value] of Object.entries(oc.GeomAbs_Shape)) {
      if (value === continuity && name.startsWith("GeomAbs_")) {
        return name.slice("GeomAbs_".length).toLowerCase();
      }
    }
    return "";
  } catch {
    return "";
  }
}

function isSmoothContinuity(value) {
  return ["g1", "c1", "g2", "c2", "c3", "cn"].includes(String(value || "").toLowerCase());
}

function sampledEdgeDihedralDeg(oc, edge, faces) {
  if (faces.length !== 2) {
    return null;
  }
  let maxAngle = null;
  const denominator = EDGE_SAMPLE_COUNT + 1;
  for (let index = 1; index <= EDGE_SAMPLE_COUNT; index += 1) {
    const fraction = index / denominator;
    let left = null;
    let right = null;
    try {
      left = faceNormalAtEdgeFraction(oc, edge, faces[0], fraction);
      right = faceNormalAtEdgeFraction(oc, edge, faces[1], fraction);
    } catch {
      left = null;
      right = null;
    }
    const angle = angleBetweenDeg(left, right);
    if (angle !== null && Number.isFinite(angle)) {
      maxAngle = maxAngle === null ? angle : Math.max(maxAngle, angle);
    }
  }
  return maxAngle;
}

function classifySurfEdge(oc, edge, faces) {
  const F = STEP_EDGE_FLAGS;
  const C = VISIBILITY;
  const count = faces.length;
  const result = { adjacentFaceCount: count, dihedralDeg: null };
  if (oc.BRep_Tool.Degenerated(edge)) {
    return { ...result, cls: C.DEGENERATE, continuity: "degenerate", flags: F.DEGENERATE };
  }
  const seam = faces.some((f) => oc.BRep_Tool.IsClosed_2(edge, f));
  if (seam || (count === 1 && faces.length && oc.BRep_Tool.IsClosed_2(edge, faces[0]))) {
    return { ...result, cls: C.SEAM, continuity: "seam", flags: F.SEAM };
  }
  if (count === 0) {
    return {
      ...result,
      cls: C.FEATURE,
      continuity: "unknown",
      flags: F.NOT_REFERENCEABLE | F.UNKNOWN_CONTINUITY,
    };
  }
  if (count === 1) {
    return { ...result, cls: C.BOUNDARY, continuity: "boundary", flags: F.BOUNDARY };
  }
  if (count > 2) {
    return { ...result, cls: C.NON_MANIFOLD, continuity: "non_manifold", flags: F.NON_MANIFOLD };
  }
  const continuity = edgeContinuityName(oc, edge, faces);
  if (continuity === "c0") {
    const dihedral = sampledEdgeDihedralDeg(oc, edge, faces);
    return { ...result, cls: C.FEATURE, continuity: "c0", flags: F.HARD, dihedralDeg: dihedral };
  }
  if (isSmoothContinuity(continuity)) {
    const dihedral = sampledEdgeDihedralDeg(oc, edge, faces);
    return { ...result, cls: C.TANGENT, continuity, flags: F.TANGENT, dihedralDeg: dihedral };
  }
  const dihedral = sampledEdgeDihedralDeg(oc, edge, faces);
  if (dihedral !== null) {
    if (dihedral > EDGE_ANGULAR_TOLERANCE_DEG) {
      return { ...result, cls: C.FEATURE, continuity: "sampled_hard", flags: F.HARD, dihedralDeg: dihedral };
    }
    return { ...result, cls: C.TANGENT, continuity: "sampled_tangent", flags: F.TANGENT, dihedralDeg: dihedral };
  }
  return { ...result, cls: C.UNKNOWN, continuity: "unknown", flags: F.UNKNOWN_CONTINUITY };
}

// --- selector metadata (py: step_scene_geometry._surface_params/_curve_params) ---
function selectorSurfaceParams(oc, adaptor, surfaceType) {
  const params = {};
  try {
    if (surfaceType === "plane") {
      const plane = adaptor.Plane();
      params.origin = xyz(plane.Location());
      params.axis = xyz(plane.Axis().Direction());
    } else if (surfaceType === "cylinder") {
      const cylinder = adaptor.Cylinder();
      params.origin = xyz(cylinder.Location());
      params.axis = xyz(cylinder.Axis().Direction());
      params.radius = cylinder.Radius();
    } else if (surfaceType === "cone") {
      const cone = adaptor.Cone();
      params.origin = xyz(cone.Location());
      params.axis = xyz(cone.Axis().Direction());
      params.semiAngleRad = cone.SemiAngle();
    } else if (surfaceType === "sphere") {
      const sphere = adaptor.Sphere();
      params.center = xyz(sphere.Location());
      params.radius = sphere.Radius();
    } else if (surfaceType === "torus") {
      const torus = adaptor.Torus();
      params.center = xyz(torus.Location());
      params.axis = xyz(torus.Axis().Direction());
      params.majorRadius = torus.MajorRadius();
      params.minorRadius = torus.MinorRadius();
    } else if (surfaceType === "beziersurface" || surfaceType === "bsplinesurface") {
      params.uClosed = Boolean(adaptor.IsUPeriodic());
      params.vClosed = Boolean(adaptor.IsVPeriodic());
    }
  } catch {
    return {};
  }
  return params;
}

function selectorCurveParams(oc, adaptor, curveType) {
  const params = {};
  try {
    if (curveType === "line") {
      const line = adaptor.Line();
      params.origin = xyz(line.Location());
      params.direction = xyz(line.Direction());
    } else if (curveType === "circle") {
      const circle = adaptor.Circle();
      params.center = xyz(circle.Location());
      params.axis = xyz(circle.Axis().Direction());
      params.radius = circle.Radius();
    } else if (curveType === "ellipse") {
      const ellipse = adaptor.Ellipse();
      params.center = xyz(ellipse.Location());
      params.axis = xyz(ellipse.Axis().Direction());
      params.majorRadius = ellipse.MajorRadius();
      params.minorRadius = ellipse.MinorRadius();
    } else if (curveType === "hyperbola") {
      const hyperbola = adaptor.Hyperbola();
      params.center = xyz(hyperbola.Location());
      params.axis = xyz(hyperbola.Axis().Direction());
      params.majorRadius = hyperbola.MajorRadius();
      params.minorRadius = hyperbola.MinorRadius();
    } else if (curveType === "parabola") {
      const parabola = adaptor.Parabola();
      params.center = xyz(parabola.Location());
      params.axis = xyz(parabola.Axis().Direction());
      params.focal = parabola.Focal();
    } else if (curveType === "beziercurve" || curveType === "bsplinecurve") {
      params.degree = adaptor.Degree();
      params.periodic = Boolean(adaptor.IsPeriodic());
      params.rational = Boolean(adaptor.IsRational());
    }
  } catch {
    return {};
  }
  return params;
}

// --- the extractor (py: extract_surface_component) ---
export function extractSurfaceComponent(oc, shape, { faceColors = null, partColor = null } = {}) {
  const bin = new Bin();

  const faceMap = new oc.TopTools_IndexedMapOfShape_1();
  const edgeMap = new oc.TopTools_IndexedMapOfShape_1();
  const E = oc.TopAbs_ShapeEnum;
  oc.TopExp.MapShapes_1(shape, E.TopAbs_FACE, faceMap);
  oc.TopExp.MapShapes_1(shape, E.TopAbs_EDGE, edgeMap);
  const edgeFaces = new oc.TopTools_IndexedDataMapOfShapeListOfShape_1();
  oc.TopExp.MapShapesAndAncestors(shape, E.TopAbs_EDGE, E.TopAbs_FACE, edgeFaces);

  // Shape (solid/shell) membership (py lines 645-693). FindIndex replaces the
  // Python hash-dict joins: same TShape+Location identity, native lookup.
  const shapesMeta = [];
  const shapeByFace = new Map();
  const shapeByEdge = new Map();

  const recordShape = (sub, kind) => {
    const ordinal = shapesMeta.length + 1;
    let volume = null;
    if (kind === "solid") {
      try {
        const props = new oc.GProp_GProps_1();
        oc.BRepGProp.VolumeProperties_1(sub, props, false, false, false);
        volume = props.Mass();
      } catch {
        volume = null;
      }
    }
    shapesMeta.push({ ord: ordinal, kind, volume });
    const subFaces = new oc.TopTools_IndexedMapOfShape_1();
    oc.TopExp.MapShapes_1(sub, E.TopAbs_FACE, subFaces);
    for (let i = 1; i <= subFaces.Extent(); i += 1) {
      const faceOrd = faceMap.FindIndex(subFaces.FindKey(i));
      if (faceOrd > 0 && !shapeByFace.has(faceOrd)) {
        shapeByFace.set(faceOrd, ordinal);
      }
    }
    const subEdges = new oc.TopTools_IndexedMapOfShape_1();
    oc.TopExp.MapShapes_1(sub, E.TopAbs_EDGE, subEdges);
    for (let i = 1; i <= subEdges.Extent(); i += 1) {
      const edgeOrd = edgeMap.FindIndex(subEdges.FindKey(i));
      if (edgeOrd > 0 && !shapeByEdge.has(edgeOrd)) {
        shapeByEdge.set(edgeOrd, ordinal);
      }
    }
  };

  const solidExplorer = new oc.TopExp_Explorer_2(shape, E.TopAbs_SOLID, E.TopAbs_SHAPE);
  while (solidExplorer.More()) {
    recordShape(solidExplorer.Current(), "solid");
    solidExplorer.Next();
  }
  if (!shapesMeta.length) {
    const shellExplorer = new oc.TopExp_Explorer_2(shape, E.TopAbs_SHELL, E.TopAbs_SHAPE);
    while (shellExplorer.More()) {
      recordShape(shellExplorer.Current(), "shell");
      shellExplorer.Next();
    }
  }
  if (!shapesMeta.length) {
    shapesMeta.push({ ord: 1, kind: "shape", volume: null });
  }

  const faces = [];
  for (let ordinal = 1; ordinal <= faceMap.Extent(); ordinal += 1) {
    const face = oc.TopoDS.Face_1(faceMap.FindKey(ordinal));
    const [u0, u1, v0, v1] = uvBounds(oc, face);
    const adaptor = new oc.BRepAdaptor_Surface_2(face, true);
    const surfaceType = enumNameGeomAbs(oc, adaptor.GetType());
    const entry = {
      ord: ordinal,
      shape: shapeByFace.get(ordinal) ?? 1,
      reversed: face.Orientation_1() === oc.TopAbs_Orientation.TopAbs_REVERSED,
      uv: [u0, u1, v0, v1],
      surfaceType,
      ...faceMetrics(oc, face),
      surface: surfacePayload(oc, face, bin),
      loops: [],
    };
    assertSurfaceCoversFace(entry.surface, u0, u1, v0, v1, bin);
    if (entry.surface.kind === "plane") {
      const sign = entry.reversed ? -1.0 : 1.0;
      entry.normal = entry.surface.zdir.map((c) => sign * c);
    }
    const params = selectorSurfaceParams(oc, adaptor, surfaceType);
    if (Object.keys(params).length) {
      entry.params = params;
    }
    if (faceColors) {
      const color = faceColors.get ? faceColors.get(ordinal) : faceColors[ordinal];
      if (color != null) {
        entry.color = Array.from(color, Number);
      }
    }
    const wireExplorer = new oc.TopExp_Explorer_2(face, E.TopAbs_WIRE, E.TopAbs_SHAPE);
    while (wireExplorer.More()) {
      const wire = oc.TopoDS.Wire_1(wireExplorer.Current());
      const loop = [];
      const walker = new oc.BRepTools_WireExplorer_3(wire, face);
      while (walker.More()) {
        const edge = walker.Current();
        const pcurve = curve2dPayload(oc, edge, face, bin);
        pcurve.edgeOrd = Math.max(edgeMap.FindIndex(edge), 0);
        pcurve.reversed = edge.Orientation_1() === oc.TopAbs_Orientation.TopAbs_REVERSED;
        loop.push(pcurve);
        walker.Next();
      }
      if (loop.length) {
        entry.loops.push(loop);
      }
      wireExplorer.Next();
    }
    faces.push(entry);
  }

  const edges = [];
  for (let ordinal = 1; ordinal <= edgeMap.Extent(); ordinal += 1) {
    const edge = oc.TopoDS.Edge_1(edgeMap.FindKey(ordinal));
    const adjacent = [];
    const mapIndex = edgeFaces.FindIndex(edge);
    if (mapIndex > 0) {
      // No list iterator binding in this build: walk a COPY destructively
      // (First + RemoveFirst) so the map's own list is never mutated.
      const faceList = edgeFaces.FindFromIndex(mapIndex);
      const copy = new oc.TopTools_ListOfShape_1();
      copy.Assign(faceList);
      while (copy.Size() > 0) {
        adjacent.push(copy.First_1());
        copy.RemoveFirst();
      }
    }
    // Dedupe (a seam appears twice under one face; py lines 759-770).
    const uniqueFaces = [];
    const dedupedOrds = [];
    const seen = new Set();
    for (const f of adjacent) {
      const faceOrd = Math.max(faceMap.FindIndex(f), 0);
      if (!seen.has(faceOrd)) {
        seen.add(faceOrd);
        uniqueFaces.push(oc.TopoDS.Face_1(f));
        dedupedOrds.push(faceOrd);
      }
    }
    const classification = classifySurfEdge(oc, edge, uniqueFaces);
    if (uniqueFaces.length !== adjacent.length) {
      classification.cls = VISIBILITY.SEAM;
      classification.continuity = "seam";
      classification.flags = STEP_EDGE_FLAGS.SEAM;
    }
    const curveAdaptor = new oc.BRepAdaptor_Curve_2(edge);
    const curveType = enumNameGeomAbs(oc, curveAdaptor.GetType());
    const entry = {
      ord: ordinal,
      shape: shapeByEdge.get(ordinal) ?? 1,
      class: classification.cls,
      continuity: classification.continuity,
      dihedralDeg: classification.dihedralDeg,
      flags: Number(classification.flags),
      adjacentFaceCount: uniqueFaces.length,
      curveType,
      faceOrds: dedupedOrds,
      ...edgeMetrics(oc, edge),
      curve: curve3dPayload(oc, edge, bin),
    };
    const params = selectorCurveParams(oc, curveAdaptor, curveType);
    if (Object.keys(params).length) {
      entry.params = params;
    }
    edges.push(entry);
  }

  const index = {
    version: SURF_VERSION,
    shapes: shapesMeta,
    faces,
    edges,
    counts: { faces: faceMap.Extent(), edges: edgeMap.Extent() },
  };
  if (partColor != null) {
    index.partColor = Array.from(partColor, Number);
  }
  const jsonBytes = Buffer.from(JSON.stringify(index), "utf8");
  const header = Buffer.alloc(12);
  header.write(SURF_MAGIC, 0, "ascii");
  header.writeUInt32LE(SURF_VERSION, 4);
  header.writeUInt32LE(jsonBytes.length, 8);
  return Buffer.concat([header, jsonBytes, bin.payload()]);
}

// Read a location-stripped BinTools blob into a TopoDS_Shape.
export function shapeFromBrepBuffer(oc, buffer) {
  const tempPath = `/brep-${Math.floor(performance.now() * 1000) % 1_000_000_000}.bin`;
  oc.FS.writeFile(tempPath, new Uint8Array(buffer));
  const shape = new oc.TopoDS_Shape();
  try {
    oc.BinTools.Read_2(shape, tempPath, new oc.Message_ProgressRange_1());
  } finally {
    oc.FS.unlink(tempPath);
  }
  if (shape.IsNull()) {
    throw new Error("BinTools read produced a null shape");
  }
  return shape;
}
