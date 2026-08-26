import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSourceSketchViewportModel,
  sourceSketchCameraFrame,
  sourceSketchDimensionDescriptors,
} from "./sourceSketchViewport.js";

const FEATURE = {
  id: "extrude-1",
  sketch: {
    id: "sketch-1",
    label: "Sketch1",
    plane: {
      supported: true,
      name: "Plane.XZ",
      origin: [10, 20, 30],
      xAxis: [1, 0, 0],
      yAxis: [0, 0, 1],
      normal: [0, -1, 0],
    },
    entities: [
      {
        op: "Rectangle",
        mode: "add",
        position: [2, 3],
        params: [
          { name: "width", value: 40, span: [10, 12] },
          { name: "height", value: 24, span: [14, 16] },
        ],
      },
      {
        op: "Circle",
        mode: "subtract",
        position: [2, 3],
        params: [{ name: "radius", value: 4, span: [20, 21] }],
      },
    ],
  },
};

test("buildSourceSketchViewportModel uses authored plane, locations, and live drafts", () => {
  const model = buildSourceSketchViewportModel(FEATURE, {
    "10:12": { span: [10, 12], value: "50" },
    "20:21": { span: [20, 21], value: "6" },
  });
  assert.deepEqual(model.plane.origin, [10, 20, 30]);
  assert.deepEqual(model.entities.map((entity) => entity.center), [[2, 3], [2, 3]]);
  assert.equal(model.entities[0].width, 50);
  assert.equal(model.entities[1].radius, 6);
  assert.deepEqual(model.bounds, { minX: -23, minY: -9, maxX: 27, maxY: 15, width: 50, height: 24 });
});

test("sourceSketchCameraFrame looks normal to the authored plane and fits the profile", () => {
  const model = buildSourceSketchViewportModel(FEATURE);
  const frame = sourceSketchCameraFrame(model, { aspect: 2, padding: 1.5, distance: 80 });
  assert.deepEqual(frame.target, [12, 20, 33]);
  assert.deepEqual(frame.position, [12, -100, 33]);
  assert.deepEqual(frame.up, [0, 0, 1]);
  assert.equal(frame.orthographicHalfHeight, 30);
});

test("sourceSketchDimensionDescriptors follows draft geometry", () => {
  const model = buildSourceSketchViewportModel(FEATURE, {
    "10:12": { span: [10, 12], value: "50" },
  });
  const dimensions = sourceSketchDimensionDescriptors(model);
  assert.deepEqual(dimensions.map((dimension) => dimension.label), ["50 mm", "24 mm", "R 4 mm"]);
  assert.deepEqual(dimensions[2].end, [6, 3]);
});

test("dynamic sketch planes remain editable in source but cannot enter viewport edit mode", () => {
  const model = buildSourceSketchViewportModel({
    sketch: {
      id: "sketch-dynamic",
      plane: { supported: false, reason: "dynamic" },
      entities: FEATURE.sketch.entities,
    },
  });
  assert.equal(model.plane.supported, false);
  assert.equal(sourceSketchCameraFrame(model), null);
});
