import { sourceParamKey } from "./sourceFeatureDrafts.js";

const DEFAULT_PLANE = Object.freeze({
  supported: true,
  name: "Plane.XY",
  origin: [0, 0, 0],
  xAxis: [1, 0, 0],
  yAxis: [0, 1, 0],
  normal: [0, 0, 1],
});

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatDimension(value) {
  return Number(finiteNumber(value).toFixed(3)).toString();
}

function vector(values, fallback) {
  const source = Array.isArray(values) ? values : fallback;
  return fallback.map((fallbackValue, index) => finiteNumber(source?.[index], fallbackValue));
}

function draftParameterValue(parameter, drafts) {
  const draft = drafts?.[sourceParamKey(parameter)];
  return finiteNumber(draft ? draft.value : parameter?.value, finiteNumber(parameter?.value));
}

function parameterMap(entity, drafts) {
  return new Map((Array.isArray(entity?.params) ? entity.params : []).map((parameter) => [
    String(parameter?.name || ""),
    { ...parameter, value: draftParameterValue(parameter, drafts) },
  ]));
}

function normalizeEntity(entity, drafts, index) {
  const parameters = parameterMap(entity, drafts);
  const position = vector(entity?.position, [0, 0]);
  const op = String(entity?.op || "");
  if (op === "Rectangle") {
    const width = Math.abs(finiteNumber(parameters.get("width")?.value));
    const height = Math.abs(finiteNumber(parameters.get("height")?.value));
    if (!(width > 0) || !(height > 0)) return null;
    return {
      id: `rectangle-${index + 1}`,
      kind: "rectangle",
      mode: String(entity?.mode || "add"),
      center: position,
      width,
      height,
      parameters: {
        width: parameters.get("width") || null,
        height: parameters.get("height") || null,
      },
    };
  }
  if (op === "Circle") {
    const radius = Math.abs(finiteNumber(parameters.get("radius")?.value));
    if (!(radius > 0)) return null;
    return {
      id: `circle-${index + 1}`,
      kind: "circle",
      mode: String(entity?.mode || "add"),
      center: position,
      radius,
      parameters: { radius: parameters.get("radius") || null },
    };
  }
  return null;
}

export function sourceSketchBounds(entities) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const entity of Array.isArray(entities) ? entities : []) {
    if (entity.kind === "rectangle") {
      minX = Math.min(minX, entity.center[0] - entity.width / 2);
      maxX = Math.max(maxX, entity.center[0] + entity.width / 2);
      minY = Math.min(minY, entity.center[1] - entity.height / 2);
      maxY = Math.max(maxY, entity.center[1] + entity.height / 2);
    } else if (entity.kind === "circle") {
      minX = Math.min(minX, entity.center[0] - entity.radius);
      maxX = Math.max(maxX, entity.center[0] + entity.radius);
      minY = Math.min(minY, entity.center[1] - entity.radius);
      maxY = Math.max(maxY, entity.center[1] + entity.radius);
    }
  }
  if (![minX, minY, maxX, maxY].every(Number.isFinite)) {
    return { minX: -5, minY: -5, maxX: 5, maxY: 5, width: 10, height: 10 };
  }
  return {
    minX,
    minY,
    maxX,
    maxY,
    width: Math.max(maxX - minX, 1e-6),
    height: Math.max(maxY - minY, 1e-6),
  };
}

export function buildSourceSketchViewportModel(feature, drafts = {}) {
  const sketch = feature?.sketch;
  if (!sketch) return null;
  const rawPlane = sketch.plane || DEFAULT_PLANE;
  const plane = {
    supported: rawPlane.supported !== false,
    reason: String(rawPlane.reason || ""),
    name: String(rawPlane.name || DEFAULT_PLANE.name),
    origin: vector(rawPlane.origin, DEFAULT_PLANE.origin),
    xAxis: vector(rawPlane.xAxis, DEFAULT_PLANE.xAxis),
    yAxis: vector(rawPlane.yAxis, DEFAULT_PLANE.yAxis),
    normal: vector(rawPlane.normal, DEFAULT_PLANE.normal),
  };
  const entities = (Array.isArray(sketch.entities) ? sketch.entities : [])
    .map((entity, index) => normalizeEntity(entity, drafts, index))
    .filter(Boolean);
  return {
    id: String(sketch.id || "sketch"),
    label: String(sketch.label || "Sketch"),
    plane,
    entities,
    bounds: sourceSketchBounds(entities),
  };
}

export function sourceSketchCameraFrame(model, { aspect = 1, padding = 1.1, distance = 100 } = {}) {
  if (!model?.plane?.supported) return null;
  const bounds = model.bounds || sourceSketchBounds(model.entities);
  const target2d = [
    (bounds.minX + bounds.maxX) / 2,
    (bounds.minY + bounds.maxY) / 2,
  ];
  const span = Math.max(bounds.width, bounds.height, 1);
  let extentX = bounds.width / 2;
  let extentY = bounds.height / 2;
  for (const dimension of sourceSketchDimensionDescriptors(model)) {
    for (const point of [dimension.start, dimension.end]) {
      extentX = Math.max(extentX, Math.abs(point[0] - target2d[0]));
      extentY = Math.max(extentY, Math.abs(point[1] - target2d[1]));
    }
  }
  // Include the world-space label sprites and handle circles, not only their
  // anchor lines, so entering Sketch Edit never hides a dimension under a pane.
  extentX += span * 0.13;
  extentY += span * 0.08;
  const origin = vector(model.plane.origin, DEFAULT_PLANE.origin);
  const xAxis = vector(model.plane.xAxis, DEFAULT_PLANE.xAxis);
  const yAxis = vector(model.plane.yAxis, DEFAULT_PLANE.yAxis);
  const normal = vector(model.plane.normal, DEFAULT_PLANE.normal);
  const target = origin.map((value, index) => (
    value + xAxis[index] * target2d[0] + yAxis[index] * target2d[1]
  ));
  const safeAspect = Math.max(finiteNumber(aspect, 1), 1e-3);
  const halfHeight = Math.max(extentY, extentX / safeAspect, 1) * padding;
  const cameraDistance = Math.max(finiteNumber(distance, 100), halfHeight * 4);
  return {
    target,
    position: target.map((value, index) => value + normal[index] * cameraDistance),
    up: yAxis,
    orthographicHalfHeight: halfHeight,
  };
}

export function sourceSketchDimensionDescriptors(model) {
  const bounds = model?.bounds || sourceSketchBounds(model?.entities);
  const margin = Math.max(bounds.width, bounds.height, 1) * 0.12;
  return (Array.isArray(model?.entities) ? model.entities : []).flatMap((entity) => {
    const [cx, cy] = entity.center;
    if (entity.kind === "rectangle") {
      return [
        {
          id: `${entity.id}:width`,
          label: `${formatDimension(entity.width)} mm`,
          start: [cx - entity.width / 2, cy - entity.height / 2 - margin],
          end: [cx + entity.width / 2, cy - entity.height / 2 - margin],
        },
        {
          id: `${entity.id}:height`,
          label: `${formatDimension(entity.height)} mm`,
          start: [cx + entity.width / 2 + margin, cy - entity.height / 2],
          end: [cx + entity.width / 2 + margin, cy + entity.height / 2],
        },
      ];
    }
    if (entity.kind === "circle") {
      return [{
        id: `${entity.id}:radius`,
        label: `R ${formatDimension(entity.radius)} mm`,
        start: [cx, cy],
        end: [cx + entity.radius, cy],
      }];
    }
    return [];
  });
}
