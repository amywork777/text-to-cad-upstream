// WASM import of a foreign STEP into a standard render package.
//
// This is the assembly-walk + package-glue TWIN of the native import pipeline
// (design/standalone-viewer.md Phase C). It mirrors, function by function:
//
//   - cadgen/_internal/step_scene_loader.py  (_load_occurrence_tree_from_xcaf_doc,
//     _load_fallback_occurrence_tree, _label_name, _color_from_label/_shape)
//   - cadgen/_internal/step_scene_mesh.py    (scene_to_build123d_compound's tree
//     semantics, _scene_mesh_resolution_hints, adaptive_mesh_resolution_from_hints)
//   - cadgen/step_artifact_cli.py            (infer_entry_kind)
//   - cadgen/_internal/step_metadata.py      (read_text_to_cad_step_metadata, entryKind)
//   - cadgen/_internal/component_package.py  (build_package_from_compound: cids,
//     occurrence walk, descriptor)
//   - cadgen/_internal/generation.py         (_assembly_provenance_manifest)
//
// The output is the SAME package format cadgen writes (assembly.json +
// components/<cid>.{brep,surf}), so the existing render path consumes it and
// Python CLIs resolve refs against it. Byte divergence from a native build is
// allowed (different kernel versions serialize BREP differently); structural
// and geometric divergence is fenced by the conformance + interop suites.
//
// KNOWN DIVERGENCES from the native walk, on record:
//   - XCAFDoc_ColorTool.GetInstanceColor is not bound in this opencascade.js
//     build, so the shape-color fallback tries GetColor(shape, type) only.
//   - TDataStd_Name.Get is not bound either; label names are recovered by
//     saving the XCAF document as XmlXCAF into MEMFS once per import and
//     indexing <TDataStd_Name> text by label entry. Same names, other route.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { extractSurfaceComponent } from "./surfExtractTwin.mjs";

// --- contract constants (values mirrored from cadgen; the render-contract
// sync test asserts these stay equal to the Python source of truth) ---
export const STEP_PACKAGE_VERSION = 15; // package_freshness.STEP_PACKAGE_VERSION
export const STEP_TOPOLOGY_SCHEMA_VERSION = 2; // glb_topology.STEP_TOPOLOGY_SCHEMA_VERSION
export const PACKAGE_KIND = "assembly-package"; // component_package.PACKAGE_KIND
const DESCRIPTOR_NAME = "assembly.json";
const COMPONENT_DIRNAME = "components";
// glb_topology.step_topology_capabilities constants
const EDGE_CLASSIFICATION_ALGORITHM = "oc-brep-continuity-v1";
const SURFACE_EDGE_ALGORITHM = "oc-polygon-on-triangulation-v1";
const EDGE_ANGULAR_TOLERANCE_DEG = 2;
const EDGE_SAMPLE_COUNT = 3;
const EDGE_BARYCENTRIC_ATTRIBUTE = "_CAD_EDGE_BARYCENTRIC";
const EDGE_CLASS_ATTRIBUTE = "_CAD_EDGE_CLASS";
const EDGE_SURFACE_CLASS_CODES = {
  none: 0, feature: 1, tangent: 2, seam: 3, degenerate: 4, boundary: 5, nonManifold: 6, unknown: 7,
};
const DEFAULT_EDGE_VISIBILITY_CLASSES = ["feature", "tangent", "seam", "degenerate"];
const FEATURE_ONLY_VISIBILITY_CLASSES = ["feature"];

let memfsCounter = 0;
function memfsPath(suffix) {
  memfsCounter += 1;
  return `/tmp/step-import-${process.pid}-${memfsCounter}${suffix}`;
}

// --- step_metadata.read_text_to_cad_step_metadata, entryKind only ---
const METADATA_TAIL_BYTES = 1024 * 1024;
const ENTRY_KIND_PROPERTY = "cadgen:entryKind";
const GENERATOR_PROPERTY = "cadgen:generator";
const STEP_STRING = "'(?:''|[^'])*'";

function stepUnescape(raw) {
  let text = raw.trim();
  if (text.length >= 2 && text.startsWith("'") && text.endsWith("'")) {
    text = text.slice(1, -1);
  }
  return text.replace(/''/g, "'");
}

function entryKindFromStepText(stepText) {
  const items = new Map();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*DESCRIPTIVE_REPRESENTATION_ITEM\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*(${STEP_STRING})\\s*\\)\\s*;`, "gis",
  ))) {
    items.set(`#${match[1]}`, stepUnescape(match[3]));
  }
  const representations = new Map();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*REPRESENTATION\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*\\(([^)]*)\\)\\s*,\\s*#\\d+\\s*\\)\\s*;`, "gis",
  ))) {
    representations.set(`#${match[1]}`, match[3].match(/#\d+/g) || []);
  }
  const entryKindDefinitions = new Set();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*PROPERTY_DEFINITION\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*(${STEP_STRING})\\s*,\\s*#[0-9]+\\s*\\)\\s*;`, "gis",
  ))) {
    const propertyName = stepUnescape(match[3]);
    if (propertyName === ENTRY_KIND_PROPERTY || propertyName === "cadgen:entry_kind") {
      entryKindDefinitions.add(`#${match[1]}`);
    }
  }
  for (const match of stepText.matchAll(
    /#\d+\s*=\s*PROPERTY_DEFINITION_REPRESENTATION\s*\(\s*(#\d+)\s*,\s*(#\d+)\s*\)\s*;/gis,
  )) {
    if (!entryKindDefinitions.has(match[1])) {
      continue;
    }
    for (const itemRef of representations.get(match[2]) || []) {
      const value = items.get(itemRef);
      const normalized = String(value || "").trim().toLowerCase();
      if (normalized === "part" || normalized === "assembly") {
        return normalized;
      }
    }
  }
  return null;
}

export function readEmbeddedEntryKind(stepPath) {
  const size = fs.statSync(stepPath).size;
  const offset = Math.max(0, size - METADATA_TAIL_BYTES);
  const tail = Buffer.alloc(size - offset);
  const handle = fs.openSync(stepPath, "r");
  try {
    fs.readSync(handle, tail, 0, tail.length, offset);
  } finally {
    fs.closeSync(handle);
  }
  const tailText = tail.toString("utf8");
  if (!tailText.includes(ENTRY_KIND_PROPERTY) && !tailText.includes(GENERATOR_PROPERTY)) {
    return null;
  }
  const fromTail = entryKindFromStepText(tailText);
  if (fromTail !== null || offset === 0) {
    return fromTail;
  }
  return entryKindFromStepText(fs.readFileSync(stepPath, "utf8"));
}

// --- step_scene_loader._normalize_label_name ---
const REJECTED_LABEL_NAMES = new Set([
  "assembly", "solid", "compound", "compsolid", "shell", "face", "wire", "edge", "vertex",
]);

function normalizeLabelName(rawName) {
  if (rawName == null) {
    return null;
  }
  const text = String(rawName).split(/\s+/).filter(Boolean).join(" ");
  if (!text) {
    return null;
  }
  const lowered = text.toLowerCase();
  if (lowered.startsWith("open cascade step translator")) {
    return null;
  }
  if (REJECTED_LABEL_NAMES.has(lowered)) {
    return null;
  }
  if (/^\d+$/.test(text)) {
    return null;
  }
  return text;
}

// --- label-name index via one XmlXCAF save (TDataStd_Name.Get is unbound) ---
function xmlUnescape(text) {
  return text
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function labelNamesFromDocumentXml(xml) {
  const names = new Map();
  const stack = [];
  const token = /<label\s+tag="(\d+)"[^>]*>|<\/label>|<TDataStd_Name\b[^>]*>([^<]*)<\/TDataStd_Name>/g;
  for (const match of xml.matchAll(token)) {
    if (match[0].startsWith("<label")) {
      stack.push(match[1]);
    } else if (match[0] === "</label>") {
      stack.pop();
    } else if (stack.length) {
      names.set(stack.join(":"), xmlUnescape(match[2]));
    }
  }
  return names;
}

function buildLabelNameIndex(oc, app, hDoc) {
  const savePath = memfsPath(".xml");
  try {
    app.SaveAs_1(hDoc, new oc.TCollection_ExtendedString_2(savePath, false), new oc.Message_ProgressRange_1());
    const xml = oc.FS.readFile(savePath, { encoding: "utf8" });
    return labelNamesFromDocumentXml(xml);
  } catch {
    return new Map();
  } finally {
    try { oc.FS.unlink(savePath); } catch { /* never saved */ }
  }
}

// --- step_scene_loader small helpers ---
function labelEntry(oc, label) {
  const entry = new oc.TCollection_AsciiString_1();
  oc.TDF_Tool.Entry(label, entry);
  return entry.ToCString();
}

function labelName(oc, label, nameIndex) {
  return normalizeLabelName(nameIndex.get(labelEntry(oc, label)) ?? null);
}

function labelShape(oc, label) {
  try {
    return oc.XCAFDoc_ShapeTool.GetShape_2(label);
  } catch {
    return null;
  }
}

function shapeIsNull(shape) {
  return shape == null || shape.IsNull();
}

function shapeLocation(shape) {
  try {
    return shape.Location_1();
  } catch {
    return null;
  }
}

function composeLocations(parentLocation, childLocation) {
  if (parentLocation == null) {
    return childLocation;
  }
  if (childLocation == null) {
    return parentLocation;
  }
  try {
    return parentLocation.Multiplied(childLocation);
  } catch {
    return childLocation;
  }
}

function unlocatedShape(oc, shape) {
  try {
    return shape.Located(new oc.TopLoc_Location_1(), false);
  } catch {
    return shape;
  }
}

function locatedShape(oc, shape, location) {
  if (location == null) {
    return shape;
  }
  try {
    return shape.Located(location, false);
  } catch {
    return shape;
  }
}

const IDENTITY_TRANSFORM = Object.freeze([
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
]);

function locationTransformMatrix(location) {
  if (location == null) {
    return [...IDENTITY_TRANSFORM];
  }
  try {
    const trsf = location.Transformation();
    const rows = [];
    for (let row = 1; row <= 3; row += 1) {
      for (let column = 1; column <= 4; column += 1) {
        rows.push(trsf.Value(row, column));
      }
    }
    rows.push(0, 0, 0, 1);
    return rows;
  } catch {
    return [...IDENTITY_TRANSFORM];
  }
}

function xcafChildren(oc, label, resolvedLabel) {
  let sequence = new oc.TDF_LabelSequence_1();
  let hasChildren = oc.XCAFDoc_ShapeTool.GetComponents(label, sequence, false);
  if ((!hasChildren || sequence.Length() <= 0) && !resolvedLabel.IsEqual(label)) {
    sequence = new oc.TDF_LabelSequence_1();
    hasChildren = oc.XCAFDoc_ShapeTool.GetComponents(resolvedLabel, sequence, false);
  }
  if (!hasChildren || sequence.Length() <= 0) {
    return [];
  }
  const children = [];
  for (let index = 1; index <= sequence.Length(); index += 1) {
    children.push(sequence.Value(index));
  }
  return children;
}

function resolveReferredLabel(oc, label) {
  if (!oc.XCAFDoc_ShapeTool.IsReference(label)) {
    return label;
  }
  const referred = new oc.TDF_Label();
  if (oc.XCAFDoc_ShapeTool.GetReferredShape(label, referred)) {
    return referred;
  }
  return label;
}

// Quantity_Color stores LINEAR RGB (OCCT >= 7.5) and Red()/Green()/Blue()
// return linear components; the native pipeline emits sRGB (build123d Color
// round-trips through sRGB), so convert with OCCT's own transfer function.
function linearToSrgb(value) {
  return value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055;
}

function colorTuple(color) {
  const rgb = color.GetRGB();
  return [
    linearToSrgb(rgb.Red()),
    linearToSrgb(rgb.Green()),
    linearToSrgb(rgb.Blue()),
    color.Alpha(),
  ];
}

const COLOR_TYPE_ORDER = ["XCAFDoc_ColorSurf", "XCAFDoc_ColorGen", "XCAFDoc_ColorCurv"];

function colorFromLabel(oc, colorTool, label) {
  const color = new oc.Quantity_ColorRGBA_1();
  for (const typeName of COLOR_TYPE_ORDER) {
    try {
      if (colorTool.GetColor_5(label, oc.XCAFDoc_ColorType[typeName], color)) {
        return colorTuple(color);
      }
    } catch {
      continue;
    }
  }
  return null;
}

function colorFromShape(oc, colorTool, shape) {
  if (shapeIsNull(shape)) {
    return null;
  }
  const color = new oc.Quantity_ColorRGBA_1();
  for (const typeName of COLOR_TYPE_ORDER) {
    // GetInstanceColor is unbound in this build; the label route above covers
    // instance colors in practice (they land on the instance label).
    try {
      if (colorTool.GetColor_8(shape, oc.XCAFDoc_ColorType[typeName], color)) {
        return colorTuple(color);
      }
    } catch {
      continue;
    }
  }
  return null;
}

// --- step_scene_loader._load_occurrence_tree(+_from_xcaf_doc) twin ---
export function readStepScene(oc, stepPath) {
  const inputPath = memfsPath(".step");
  oc.FS.writeFile(inputPath, fs.readFileSync(stepPath));
  try {
    const app = new oc.TDocStd_Application();
    oc.XmlXCAFDrivers.DefineFormat(new oc.Handle_TDocStd_Application_2(app));
    const hDoc = new oc.Handle_TDocStd_Document_1();
    app.NewDocument_2(new oc.TCollection_ExtendedString_2("XmlXCAF", false), hDoc);

    const reader = new oc.STEPCAFControl_Reader_1();
    reader.SetColorMode(true);
    reader.SetNameMode(true);
    for (const mode of ["SetMatMode", "SetLayerMode", "SetSHUOMode"]) {
      if (typeof reader[mode] === "function") {
        reader[mode](true);
      }
    }
    const status = reader.ReadFile(inputPath);
    if (status.value !== oc.IFSelect_ReturnStatus.IFSelect_RetDone.value
        || !reader.Transfer_1(hDoc, new oc.Message_ProgressRange_1())) {
      return fallbackScene(oc, inputPath, stepPath);
    }

    const doc = hDoc.get();
    const shapeTool = oc.XCAFDoc_DocumentTool.ShapeTool(doc.Main()).get();
    const colorTool = oc.XCAFDoc_DocumentTool.ColorTool(doc.Main()).get();
    const freeLabels = new oc.TDF_LabelSequence_1();
    shapeTool.GetFreeShapes(freeLabels);
    if (freeLabels.Length() <= 0) {
      return fallbackScene(oc, inputPath, stepPath);
    }

    const nameIndex = buildLabelNameIndex(oc, app, hDoc);
    const prototypes = new Map(); // key -> { shape, name, color }

    const collect = (label, pathSegments, parentLocation) => {
      const resolvedLabel = resolveReferredLabel(oc, label);
      const instanceShape = labelShape(oc, label);
      const resolvedShape = labelShape(oc, resolvedLabel);
      const baseShape = !shapeIsNull(instanceShape) ? instanceShape : resolvedShape;
      const localLocation = baseShape != null ? shapeLocation(baseShape) : null;
      const currentLocation = composeLocations(parentLocation, localLocation);
      const children = xcafChildren(oc, label, resolvedLabel);
      const name = labelName(oc, label, nameIndex) || labelName(oc, resolvedLabel, nameIndex);
      const sourceName = labelName(oc, resolvedLabel, nameIndex) || name;
      const instanceLevelColor = colorFromLabel(oc, colorTool, label)
        || colorFromShape(oc, colorTool, instanceShape);
      const prototypeLevelColor = instanceLevelColor
        ? null
        : colorFromLabel(oc, colorTool, resolvedLabel)
          || colorFromShape(oc, colorTool, resolvedShape);
      const occurrenceColor = instanceLevelColor || prototypeLevelColor;
      // Which rung answered matters downstream: GetInstanceColor is unbound in
      // this build, so an occurrence that FELL THROUGH to prototype level while
      // sibling instances of the same prototype carry their own color is the
      // case native OCCT might color differently (see instanceColorWarnings).
      const colorSource = instanceLevelColor ? "instance" : prototypeLevelColor ? "prototype" : null;
      let prototypeKey = null;
      if (!children.length && !shapeIsNull(resolvedShape)) {
        prototypeKey = labelEntry(oc, resolvedLabel);
        if (!prototypes.has(prototypeKey)) {
          prototypes.set(prototypeKey, { shape: unlocatedShape(oc, resolvedShape) });
        }
      } else if (!children.length && !shapeIsNull(baseShape)) {
        prototypeKey = `${labelEntry(oc, label)}#base`;
        if (!prototypes.has(prototypeKey)) {
          prototypes.set(prototypeKey, { shape: unlocatedShape(oc, baseShape) });
        }
      }
      if (prototypeKey !== null) {
        const prototype = prototypes.get(prototypeKey);
        if (prototype.name === undefined) {
          prototype.name = sourceName || name || null;
        }
        if (prototype.color === undefined) {
          const prototypeColor = colorFromLabel(oc, colorTool, resolvedLabel)
            || colorFromShape(oc, colorTool, resolvedShape);
          prototype.color = prototypeColor ?? null;
        }
      }
      const childNodes = [];
      children.forEach((child, index) => {
        const childNode = collect(child, [...pathSegments, index + 1], currentLocation);
        if (childNode !== null) {
          childNodes.push(childNode);
        }
      });
      if (prototypeKey === null && !childNodes.length) {
        return null;
      }
      return {
        path: pathSegments,
        name: name ?? null,
        sourceName: sourceName ?? null,
        prototypeKey,
        color: occurrenceColor ?? null,
        colorSource,
        location: currentLocation ?? null,
        children: childNodes,
      };
    };

    const roots = [];
    for (let index = 1; index <= freeLabels.Length(); index += 1) {
      const node = collect(freeLabels.Value(index), [index], null);
      if (node !== null) {
        roots.push(node);
      }
    }
    if (!roots.length) {
      return fallbackScene(oc, inputPath, stepPath);
    }
    return { roots, prototypes };
  } finally {
    try { oc.FS.unlink(inputPath); } catch { /* already gone */ }
  }
}

// step_scene_loader._load_fallback_occurrence_tree twin
function fallbackScene(oc, inputPath, stepPath) {
  const reader = new oc.STEPControl_Reader_1();
  const status = reader.ReadFile(inputPath);
  if (status.value !== oc.IFSelect_ReturnStatus.IFSelect_RetDone.value) {
    throw new Error(`failed to read STEP file: ${stepPath}`);
  }
  reader.TransferRoots(new oc.Message_ProgressRange_1());
  const shape = reader.OneShape();
  if (shape.IsNull()) {
    throw new Error(`STEP file produced no shape: ${stepPath}`);
  }
  const stem = path.basename(stepPath).replace(/\.[^.]+$/, "");
  const prototypes = new Map([["fallback", { shape, name: stem, color: null }]]);
  return {
    roots: [{
      path: [1], name: stem, sourceName: stem, prototypeKey: "fallback",
      color: null, location: null, children: [],
    }],
    prototypes,
  };
}

// step_artifact_cli.infer_entry_kind twin
export function inferEntryKind(stepPath, scene) {
  const embedded = readEmbeddedEntryKind(stepPath);
  if (embedded !== null) {
    return embedded;
  }
  if (scene.roots.length > 1 || scene.roots.some((node) => node.children.length)) {
    return "assembly";
  }
  return "part";
}

// --- adaptive mesh resolution twin (step_scene_mesh) ---
function leafNodes(roots) {
  const leaves = [];
  const walk = (node) => {
    if (!node.children.length) {
      leaves.push(node);
      return;
    }
    node.children.forEach(walk);
  };
  roots.forEach(walk);
  return leaves;
}

function countShapes(oc, shape, shapeEnum) {
  const map = new oc.TopTools_IndexedMapOfShape_1();
  oc.TopExp.MapShapes_1(shape, shapeEnum, map);
  return map;
}

function prototypeTopologyCounts(oc, shape) {
  const faceMap = countShapes(oc, shape, oc.TopAbs_ShapeEnum.TopAbs_FACE);
  const edgeMap = countShapes(oc, shape, oc.TopAbs_ShapeEnum.TopAbs_EDGE);
  let curvedFaces = 0;
  for (let index = 1; index <= faceMap.Extent(); index += 1) {
    try {
      const surface = new oc.BRepAdaptor_Surface_2(oc.TopoDS.Face_1(faceMap.FindKey(index)), true);
      if (surface.GetType().value !== oc.GeomAbs_SurfaceType.GeomAbs_Plane.value) {
        curvedFaces += 1;
      }
    } catch {
      curvedFaces += 1;
    }
  }
  let curvedEdges = 0;
  for (let index = 1; index <= edgeMap.Extent(); index += 1) {
    try {
      const curve = new oc.BRepAdaptor_Curve_2(oc.TopoDS.Edge_1(edgeMap.FindKey(index)));
      if (curve.GetType().value !== oc.GeomAbs_CurveType.GeomAbs_Line.value) {
        curvedEdges += 1;
      }
    } catch {
      curvedEdges += 1;
    }
  }
  return { faces: faceMap.Extent(), edges: edgeMap.Extent(), curvedFaces, curvedEdges };
}

function bboxFromShape(oc, shape) {
  const box = new oc.Bnd_Box_1();
  try {
    oc.BRepBndLib.Add(shape, box, false);
  } catch {
    return null;
  }
  if (box.IsVoid()) {
    return null;
  }
  const min = box.CornerMin();
  const max = box.CornerMax();
  return { min: [min.X(), min.Y(), min.Z()], max: [max.X(), max.Y(), max.Z()] };
}

function transformBbox(box, transform) {
  const corners = [];
  for (const x of [box.min[0], box.max[0]]) {
    for (const y of [box.min[1], box.max[1]]) {
      for (const z of [box.min[2], box.max[2]]) {
        corners.push([
          transform[0] * x + transform[1] * y + transform[2] * z + transform[3],
          transform[4] * x + transform[5] * y + transform[6] * z + transform[7],
          transform[8] * x + transform[9] * y + transform[10] * z + transform[11],
        ]);
      }
    }
  }
  return bboxFromPoints(corners);
}

function bboxFromPoints(points) {
  if (!points.length) {
    return null;
  }
  const min = [...points[0]];
  const max = [...points[0]];
  for (const point of points.slice(1)) {
    for (let axis = 0; axis < 3; axis += 1) {
      if (point[axis] < min[axis]) min[axis] = point[axis];
      if (point[axis] > max[axis]) max[axis] = point[axis];
    }
  }
  return { min, max };
}

function bboxDiag(box) {
  if (box == null) {
    return 0;
  }
  const size = [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
  return Math.hypot(size[0], size[1], size[2]);
}

function round3(value) {
  return Math.round(value * 1000) / 1000;
}

function meshResolutionHints(oc, scene) {
  const counts = new Map();
  for (const [key, prototype] of scene.prototypes) {
    counts.set(key, prototypeTopologyCounts(oc, prototype.shape));
  }
  const leaves = leafNodes(scene.roots);
  const sum = (selector) => leaves.reduce((total, node) => {
    const entry = node.prototypeKey !== null ? counts.get(node.prototypeKey) : null;
    return total + (entry ? selector(entry) : 0);
  }, 0);
  const occurrenceFaceCount = sum((c) => c.faces);
  const occurrenceEdgeCount = sum((c) => c.edges);
  const occurrenceCurvedFaceCount = sum((c) => c.curvedFaces);
  const occurrenceCurvedEdgeCount = sum((c) => c.curvedEdges);
  let prototypeFaceCount = 0;
  let prototypeEdgeCount = 0;
  let prototypeCurvedFaceCount = 0;
  let prototypeCurvedEdgeCount = 0;
  for (const entry of counts.values()) {
    prototypeFaceCount += entry.faces;
    prototypeEdgeCount += entry.edges;
    prototypeCurvedFaceCount += entry.curvedFaces;
    prototypeCurvedEdgeCount += entry.curvedEdges;
  }
  const complexityScore = occurrenceFaceCount
    + occurrenceEdgeCount * 0.35
    + prototypeFaceCount * 0.5
    + leaves.length * 24.0;
  const curvaturePressureScore = occurrenceCurvedFaceCount * 1.6
    + occurrenceCurvedEdgeCount * 0.9
    + prototypeCurvedFaceCount * 0.8
    + prototypeCurvedEdgeCount * 0.4;

  const prototypeBoxes = new Map();
  for (const [key, prototype] of scene.prototypes) {
    prototypeBoxes.set(key, bboxFromShape(oc, prototype.shape));
  }
  const occurrenceBoxes = leaves
    .filter((node) => node.prototypeKey !== null && prototypeBoxes.get(node.prototypeKey) != null)
    .map((node) => transformBbox(
      prototypeBoxes.get(node.prototypeKey),
      locationTransformMatrix(node.location),
    ));
  const merged = occurrenceBoxes.length
    ? bboxFromPoints(occurrenceBoxes.flatMap((box) => [box.min, box.max]))
    : null;
  const diagonal = bboxDiag(merged);
  let scaleFactor;
  if (diagonal <= 50.0) scaleFactor = 0.65;
  else if (diagonal <= 150.0) scaleFactor = 0.8;
  else if (diagonal <= 500.0) scaleFactor = 1.0;
  else if (diagonal <= 1500.0) scaleFactor = 1.18;
  else scaleFactor = 1.35;
  return {
    bboxDiag: round3(diagonal),
    prototypeFaceCount,
    prototypeEdgeCount,
    prototypeCurvedFaceCount,
    prototypeCurvedEdgeCount,
    occurrenceFaceCount,
    occurrenceEdgeCount,
    occurrenceCurvedFaceCount,
    occurrenceCurvedEdgeCount,
    leafOccurrenceCount: leaves.length,
    complexityScore: round3(complexityScore),
    effectiveComplexityScore: round3(complexityScore * scaleFactor),
    curvaturePressureScore: round3(curvaturePressureScore * scaleFactor),
  };
}

// step_scene_mesh.adaptive_mesh_resolution_from_hints twin
export function adaptiveMeshResolutionFromHints(hints) {
  const effectiveScore = hints.effectiveComplexityScore;
  const curvaturePressure = hints.curvaturePressureScore;
  const leafCount = hints.leafOccurrenceCount;
  const faceCount = hints.occurrenceFaceCount;
  const edgeCount = hints.occurrenceEdgeCount;
  let profile;
  let tolerance;
  let angularTolerance;
  if (faceCount >= 20000 || edgeCount >= 55000 || effectiveScore >= 45000 || curvaturePressure >= 45000) {
    profile = "large-topology"; tolerance = 0.025; angularTolerance = 0.75;
  } else if (
    faceCount >= 8000 || edgeCount >= 22000 || effectiveScore >= 28000 || curvaturePressure >= 18000
    || (leafCount >= 80 && effectiveScore >= 22000)
  ) {
    profile = "coarse-assembly"; tolerance = 0.02; angularTolerance = 0.6;
  } else if (
    faceCount >= 2500 || edgeCount >= 8000 || effectiveScore >= 6000 || curvaturePressure >= 9000
    || (leafCount >= 80 && effectiveScore >= 6000)
    || (leafCount >= 24 && effectiveScore >= 3500)
  ) {
    profile = "balanced-assembly"; tolerance = 0.016; angularTolerance = 0.5;
  } else if (faceCount >= 800 || edgeCount >= 2500 || effectiveScore >= 1800 || curvaturePressure >= 3500) {
    profile = "medium"; tolerance = 0.014; angularTolerance = 0.45;
  } else if (faceCount >= 180 || edgeCount >= 600 || effectiveScore >= 450 || curvaturePressure >= 900) {
    profile = "fine"; tolerance = 0.008; angularTolerance = 0.3;
  } else {
    profile = "extra-fine"; tolerance = 0.006; angularTolerance = 0.2;
  }
  const resolvedHints = { ...hints };
  const diagonal = typeof hints.bboxDiag === "number" ? hints.bboxDiag : 0;
  if (diagonal > 500.0) {
    const scaleFloor = round3(diagonal * 3.0e-4);
    if (scaleFloor > tolerance) {
      tolerance = scaleFloor;
      angularTolerance = Math.min(angularTolerance, 0.35);
      resolvedHints.scaleFloorTolerance = scaleFloor;
    }
  }
  resolvedHints.profile = profile;
  return { tolerance, angularTolerance, profile, hints: resolvedHints };
}

// generation_spec._edge_visibility_classes_for_resolution twin
function edgeVisibilityClassesForResolution(profile, hints) {
  const featureOnly = profile === "large-topology" || profile === "coarse-assembly"
    || (hints.occurrenceEdgeCount || 0) >= 8000;
  return featureOnly ? [...FEATURE_ONLY_VISIBILITY_CLASSES] : [...DEFAULT_EDGE_VISIBILITY_CLASSES];
}

// --- component_package build twin ---
function sha256Hex(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function contentHashFromBrep(brepBytes) {
  const digest = crypto.createHash("sha256");
  digest.update(String(STEP_PACKAGE_VERSION), "utf8");
  digest.update(Buffer.from([0]));
  digest.update(brepBytes);
  return digest.digest("hex");
}

function shapeBrepBytes(oc, shape) {
  const outputPath = memfsPath(".brep");
  try {
    oc.BinTools.Write_4(
      shape.Located(new oc.TopLoc_Location_1(), false),
      outputPath,
      false, // theWithTriangles
      false, // theWithNormals
      // Pinned to the same version component_package._shape_brep_bytes pins,
      // so both producers' blobs stay mutually readable.
      oc.BinTools_FormatVersion.BinTools_FormatVersion_VERSION_4,
      new oc.Message_ProgressRange_1(),
    );
    return Buffer.from(oc.FS.readFile(outputPath));
  } finally {
    try { oc.FS.unlink(outputPath); } catch { /* never written */ }
  }
}

function writeAtomic(filePath, data) {
  const tempPath = `${filePath}.tmp-${process.pid}-${memfsCounter += 1}`;
  fs.writeFileSync(tempPath, data);
  fs.renameSync(tempPath, filePath);
}

function nodeLabelText(node) {
  // The native import path is build123d.import_step, which labels occurrences
  // with the PRODUCT (referred/source) name — 'Bolt3W', not the reader's
  // per-instance 'Bolt3W:1' — so prefer sourceName over the instance name.
  const label = String(node.sourceName || node.name || `o${node.path.join(".")}`).trim();
  return label || `o${node.path.join(".")}`;
}

function nodeColor(scene, node) {
  if (node.color != null) {
    return node.color;
  }
  if (node.prototypeKey !== null) {
    const prototype = scene.prototypes.get(node.prototypeKey);
    if (prototype && prototype.color != null) {
      return prototype.color;
    }
  }
  return null;
}

export function buildPackageFromStep(oc, stepPath, packageDir, options = {}) {
  const onProgress = options.onProgress || (() => {});
  const rootName = path.basename(stepPath).replace(/\.[^.]+$/, "");

  onProgress({ phase: "parse", detail: path.basename(stepPath) });
  const scene = readStepScene(oc, stepPath);
  const entryKind = options.entryKind || inferEntryKind(stepPath, scene);
  const stepHash = sha256Hex(fs.readFileSync(stepPath));

  onProgress({ phase: "analyze", detail: "mesh resolution" });
  const hints = meshResolutionHints(oc, scene);
  const resolution = adaptiveMeshResolutionFromHints(hints);
  const visibilityClasses = edgeVisibilityClassesForResolution(resolution.profile, resolution.hints);

  const componentDir = path.join(packageDir, COMPONENT_DIRNAME);
  fs.mkdirSync(componentDir, { recursive: true });

  const components = {};
  const occurrences = [];
  const pendingBuilds = new Map(); // cid -> { shape, partColor, brepBytes }
  const cidByPrototypeKey = new Map();

  const addLeaf = (shape, prototypeKey, worldLocation, occurrenceId, name, color) => {
    let cid = prototypeKey !== null ? cidByPrototypeKey.get(prototypeKey) : undefined;
    let contentHash = null;
    let brepBytes = null;
    if (cid === undefined) {
      brepBytes = shapeBrepBytes(oc, shape);
      contentHash = contentHashFromBrep(brepBytes);
      cid = contentHash.slice(0, 16);
      if (prototypeKey !== null) {
        cidByPrototypeKey.set(prototypeKey, cid);
      }
    }
    if (!(cid in components)) {
      if (contentHash === null) {
        brepBytes = shapeBrepBytes(oc, shape);
        contentHash = contentHashFromBrep(brepBytes);
      }
      const componentEntry = {
        surf: `${COMPONENT_DIRNAME}/${cid}.surf`,
        brep: `${COMPONENT_DIRNAME}/${cid}.brep`,
        contentHash,
      };
      if (color != null) {
        componentEntry.color = color.map(Number);
      }
      components[cid] = componentEntry;
      pendingBuilds.set(cid, { shape, partColor: color ?? null, brepBytes });
    }
    const occurrence = {
      id: occurrenceId,
      name,
      component: cid,
      transform: locationTransformMatrix(worldLocation),
    };
    if (color != null) {
      occurrence.color = color.map(Number);
    }
    occurrences.push(occurrence);
    return {
      id: occurrenceId, name, nodeType: "part", leafPartIds: [occurrenceId], children: [],
    };
  };

  // Mirror of scene_to_build123d_compound + build_package_from_compound's walk:
  // a single free root is the model root (no wrapper level), multiple roots get
  // a synthetic container; ids are the walk path from "o1".
  let assemblyRoot = null;
  const compoundParts = []; // located leaf shapes, for the descriptor bbox / part payload
  const collectCompoundParts = (node) => {
    if (!node.children.length) {
      if (node.prototypeKey !== null) {
        const prototype = scene.prototypes.get(node.prototypeKey);
        compoundParts.push(locatedShape(oc, prototype.shape, node.location));
      }
      return;
    }
    node.children.forEach(collectCompoundParts);
  };
  scene.roots.forEach(collectCompoundParts);
  if (!compoundParts.length) {
    throw new Error(`model ${rootName} has no geometry to package`);
  }

  const buildWholeShape = () => {
    if (compoundParts.length === 1 && scene.roots.length === 1 && !scene.roots[0].children.length) {
      return compoundParts[0];
    }
    const builder = new oc.BRep_Builder();
    const compound = new oc.TopoDS_Compound();
    builder.MakeCompound(compound);
    for (const part of compoundParts) {
      builder.Add(compound, part);
    }
    return compound;
  };
  const wholeShape = buildWholeShape();

  onProgress({ phase: "walk", detail: `${compoundParts.length} occurrence(s)` });
  if (entryKind !== "assembly") {
    // Part: one occurrence, one component holding the whole (root-unlocated)
    // geometry — component_package's single_component branch.
    const singleRootLeaf = scene.roots.length === 1 && !scene.roots[0].children.length
      ? scene.roots[0]
      : null;
    const location = singleRootLeaf ? singleRootLeaf.location : null;
    const name = singleRootLeaf ? nodeLabelText(singleRootLeaf) : (scene.roots.length === 1 ? nodeLabelText(scene.roots[0]) : rootName);
    const color = singleRootLeaf ? nodeColor(scene, singleRootLeaf) : null;
    addLeaf(wholeShape, singleRootLeaf ? singleRootLeaf.prototypeKey : null, location, "o1.1", name, color);
  } else {
    const walk = (node, occurrencePath) => {
      if (!node.children.length) {
        const prototype = node.prototypeKey !== null ? scene.prototypes.get(node.prototypeKey) : null;
        if (prototype == null) {
          return null;
        }
        return addLeaf(
          prototype.shape, node.prototypeKey, node.location,
          occurrencePath, nodeLabelText(node), nodeColor(scene, node),
        );
      }
      const childNodes = node.children
        .map((child, index) => walk(child, `${occurrencePath}.${index + 1}`))
        .filter(Boolean);
      return {
        id: occurrencePath,
        name: nodeLabelText(node),
        nodeType: "subassembly",
        leafPartIds: childNodes.flatMap((child) => child.leafPartIds),
        children: childNodes,
      };
    };
    if (scene.roots.length === 1) {
      assemblyRoot = walk(scene.roots[0], "o1");
    } else {
      const childNodes = scene.roots
        .map((root, index) => walk(root, `o1.${index + 1}`))
        .filter(Boolean);
      assemblyRoot = {
        id: "o1",
        name: rootName,
        nodeType: "subassembly",
        leafPartIds: childNodes.flatMap((child) => child.leafPartIds),
        children: childNodes,
      };
    }
    if (assemblyRoot) {
      assemblyRoot.nodeType = "assembly";
    }
  }
  if (!occurrences.length) {
    throw new Error(`model ${rootName} has no geometry to package`);
  }

  // Content-addressed component cache: a present <cid>.surf + <cid>.brep pair
  // is valid by construction (the cid IS the geometry hash).
  const cids = [...pendingBuilds.keys()];
  let built = 0;
  let reused = 0;
  cids.forEach((cid, index) => {
    const surfPath = path.join(componentDir, `${cid}.surf`);
    const brepPath = path.join(componentDir, `${cid}.brep`);
    if (!options.force && fs.existsSync(surfPath) && fs.existsSync(brepPath)) {
      reused += 1;
      return;
    }
    onProgress({ phase: "components", detail: cid, done: index, total: cids.length });
    const build = pendingBuilds.get(cid);
    const brepBytes = build.brepBytes ?? shapeBrepBytes(oc, build.shape);
    const localShape = build.shape.Located(new oc.TopLoc_Location_1(), false);
    const surf = extractSurfaceComponent(oc, localShape, { partColor: build.partColor });
    writeAtomic(brepPath, brepBytes);
    // The surf goes in place LAST so its existence signals a complete pair.
    writeAtomic(surfPath, surf);
    built += 1;
  });

  onProgress({ phase: "finalize", detail: DESCRIPTOR_NAME });
  const descriptor = {
    schemaVersion: STEP_TOPOLOGY_SCHEMA_VERSION,
    profile: "index",
    entryKind,
    sourceKind: "step",
    capabilities: {
      edgeClassification: {
        algorithm: EDGE_CLASSIFICATION_ALGORITHM,
        angularToleranceDeg: EDGE_ANGULAR_TOLERANCE_DEG,
        samples: EDGE_SAMPLE_COUNT,
      },
      surfaceEdgeRendering: {
        algorithm: SURFACE_EDGE_ALGORITHM,
        primitiveAttributes: {
          barycentric: EDGE_BARYCENTRIC_ATTRIBUTE,
          class: EDGE_CLASS_ATTRIBUTE,
        },
        classCodes: { ...EDGE_SURFACE_CLASS_CODES },
        visibilityClasses: [...visibilityClasses],
      },
    },
    edgeRendering: { visibilityClasses: [...visibilityClasses] },
    mesh: {
      linearDeflection: resolution.tolerance,
      angularDeflection: resolution.angularTolerance,
      relative: true,
      resolution: {
        mode: "auto",
        profile: resolution.profile,
        linearExplicit: false,
        angularExplicit: false,
        hints: resolution.hints,
      },
    },
    stepPath: path.basename(stepPath),
    stepHash,
    kind: PACKAGE_KIND,
    packageSchemaVersion: STEP_PACKAGE_VERSION,
    rootName,
    units: "mm",
    components,
    occurrences,
    assemblyMates: [],
  };
  if (assemblyRoot != null) {
    descriptor.assembly = { root: assemblyRoot };
  }
  const bbox = bboxFromShape(oc, wholeShape);
  if (bbox != null) {
    descriptor.bbox = bbox;
  }
  descriptor.stats = {
    occurrenceCount: occurrences.length,
    shapeCount: occurrences.length,
  };
  const warnings = instanceColorWarnings(scene.roots);
  if (warnings.length) {
    descriptor.importWarnings = warnings;
  }
  fs.mkdirSync(packageDir, { recursive: true });
  writeAtomic(path.join(packageDir, DESCRIPTOR_NAME), JSON.stringify(descriptor));
  return {
    entryKind,
    stepHash,
    componentCount: Object.keys(components).length,
    occurrenceCount: occurrences.length,
    built,
    reused,
    ...(warnings.length ? { warnings } : {}),
  };
}

// The honest slice of the GetInstanceColor gap (unbound in this opencascade.js
// build; see the header note): when SOME instances of a prototype carry their
// own readable instance-level color and OTHERS fell through to the prototype's
// color (or none), native OCCT's instance-color resolution might have colored
// the fall-throughs differently — this build cannot know. Uniformly colored
// assemblies (no instance-level colors, or all instances readable) never
// trigger. Pure over the scene tree so it is testable without a kernel.
export function instanceColorWarnings(roots) {
  const byPrototype = new Map(); // key -> { name, instance: n, fellThrough: n }
  const walk = (node) => {
    if (node.children?.length) {
      node.children.forEach(walk);
      return;
    }
    if (node.prototypeKey == null) {
      return;
    }
    let entry = byPrototype.get(node.prototypeKey);
    if (!entry) {
      byPrototype.set(node.prototypeKey, (entry = {
        name: node.sourceName || node.name || node.prototypeKey,
        instance: 0,
        fellThrough: 0,
      }));
    }
    if (node.colorSource === "instance") {
      entry.instance += 1;
    } else {
      entry.fellThrough += 1;
    }
  };
  roots.forEach(walk);
  const warnings = [];
  for (const { name, instance, fellThrough } of byPrototype.values()) {
    if (instance > 0 && fellThrough > 0) {
      warnings.push(
        `per-instance colors may be incomplete for "${name}": ${instance} instance(s) carry `
        + `their own color but ${fellThrough} resolved to the shared part color — the WASM `
        + "kernel cannot read instance-color attachments native OCCT resolves via "
        + "GetInstanceColor. Verify against the source CAD, or import with the CAD skill "
        + "(run its model script: python <source>).",
      );
    }
  }
  return warnings;
}
