import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';

import { densify, shapeMarks, textMark } from '../../../../annotation/geometry.js';
import { projectAnnotations } from './annotation3d.js';
import { faceShapesOf, faceShapesText } from './faceShapes.js';

/**
 * Marks on a face, as shapes in that face's own coordinates: what the agent gets of the annotation beside its picture.
 */

// A 20 × 10 × 4 block (or `block`'s width and depth), part "block", its top face (face 6 of /work/block.step) at z = 4; with
// `boss`, a 4 × 4 × 2 boss on it at x 4 to 8, its top at z = 6. A camera looks at the top face's middle from 100 mm away,
// straight down, or tipped `tilt` degrees back from above about X, turned `roll` degrees about its view, `span` millimetres
// from the window's middle to its top at the face's middle: orthographic, or with `perspective`. From straight above,
// unturned, orthographic at the span of 50, one pixel is a millimetre: screen pixel (x, y) is (x − 50, 50 − y).
function rig({ roll = 0, tilt = 0, span = 50, boss = false, perspective = false, block = [20, 10] } = {}) {
  const scene = new THREE.Scene();
  const modelGroup = new THREE.Group();
  scene.add(modelGroup);
  const part = (id, size, [x, y, z]) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshBasicMaterial());
    mesh.userData.partId = id;
    mesh.position.set(x, y, z);
    modelGroup.add(mesh);
  };
  part('block', [...block, 4], [0, 0, 2]);
  if (boss) part('boss', [4, 4, 2], [6, 0, 5]);
  const camera = perspective ? new THREE.PerspectiveCamera(2 * Math.atan(span / 100) * 180 / Math.PI, 1, 0.1, 500)
    : new THREE.OrthographicCamera(-span, span, span, -span, 0.1, 500);
  const turn = degrees => degrees * Math.PI / 180;
  const X = new THREE.Vector3(1, 0, 0), target = new THREE.Vector3(0, 0, 4);
  const back = new THREE.Vector3(0, 0, 1).applyAxisAngle(X, turn(tilt));
  camera.up.copy(new THREE.Vector3(0, 1, 0).applyAxisAngle(X, turn(tilt)).applyAxisAngle(back, turn(roll)));
  camera.position.copy(target).addScaledVector(back, 100);
  camera.lookAt(target);
  scene.add(camera);
  scene.updateMatrixWorld(true);
  return { THREE, scene, camera, modelGroup, activeClipPlanes: [], requestRender() {} };
}
const SIZE = { width: 100, height: 100 };
const STYLE = { color: '#ff2d55', width: 2 };
const TOP = '/work/block.step#o1.f6';
const SIDE = '/work/block.step#o1.f2';
const CHAMFER = '/work/block.step#o1.f9';
// The top face, split in two by the tessellation's own seam: two faces in the one plane.
const SPLIT = '/work/block.step#o1.f7';
const BOSS = '/work/block.step#o2.f1';
const EDGE = '/work/block.step#o1.e4';
// What the renderer calls a face by a touch's reference, as the STEP view does: a face by its chip's words ("" for one it has
// no name for), and null for a reference that names no face (an edge).
const NAMES = { [TOP]: 'block · face 6', [SIDE]: 'block · face 2' };
const labelOf = ref => (/\.f\d+$/.test(ref) ? NAMES[ref] ?? '' : null);
const onTop = () => [{ part: 'block', ref: TOP }];
const outline = points => points.map(([x, y]) => ({ x, y }));
const tenths = values => values.map(value => Math.round(value * 10) / 10 || 0);
// Where a screen point falls on the top face's plane, along its ray: in the face's frame (u along X, v along Y) from `origin`.
function onTopFace(runtime, origin, { x, y }) {
  const caster = new THREE.Raycaster();
  caster.setFromCamera(new THREE.Vector2(x / SIZE.width * 2 - 1, 1 - y / SIZE.height * 2), runtime.camera);
  const at = caster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -4), new THREE.Vector3());
  return [at.x - origin[0], at.y - origin[1]];
}
// Each point of a mark where it falls, in the top face's frame from `origin`.
const uvOf = (item, origin) => Array.from({ length: item.under.length / 3 }, (_, index) => [item.under[index * 3] - origin[0], item.under[index * 3 + 1] - origin[1]]);
const stroke = (id, points) => ({ kind: 'stroke', id, points: outline(points), closed: false, color: '#ff2d55', width: 2, opacity: 1 });
// A mark as the viewer keeps it, drawn exactly on a plane through its first point (in the model's millimetres).
const drawn = (id, points, { normal = [0, 0, 1], ref = TOP, ...rest } = {}) => {
  const xyz = Float32Array.from(points.flat());
  return { id, kind: 'stroke', closed: false, color: '#ff2d55', width: 2, opacity: 1, points: xyz, under: xyz,
    level: { point: points[0], normal }, touches: [{ part: 'block', ref }], ...rest };
};

test("turns a square drawn on a block's top face into a polygon in that face's coordinates", () => {
  const runtime = rig();
  // A closed loop a pixel at a time round a 4 × 2 square, from (-2, -1) on the top face: (0, 0), (4, 0), (4, 2), (0, 2) from
  // where it starts. The ink stands two pixels off the face toward the eye; the square is where it was drawn.
  const square = { ...stroke('square', []), closed: true, width: 3, points: densify(outline([[48, 51], [52, 51], [52, 49], [48, 49]]), true, 1) };
  const items = projectAnnotations(runtime, [square], SIZE, { touchesAt: onTop });
  assert.deepEqual(faceShapesOf(items, { units: 'mm', labelOf }), [{
    face: TOP, label: 'block · face 6',
    frame: { origin: [-2, -1, 4], u: [1, 0, 0], v: [0, 1, 0], normal: [0, 0, 1] },
    shapes: [{ kind: 'polygon', points: [[0, 0], [4, 0], [4, 2], [0, 2]] }],
  }]);
});

test("keeps a Shapes rectangle a rectangle: its centre, its size and how far it is turned on the face", () => {
  // The view turned 30° about itself: a rectangle square to the screen lies turned 30° on the face.
  const runtime = rig({ roll: 30 });
  const marks = shapeMarks('rectangle', { x: 46, y: 48.5 }, { x: 54, y: 51.5 }, STYLE);
  const items = projectAnnotations(runtime, marks, SIZE, { touchesAt: onTop });
  // The Shapes tool says what it drew.
  assert.deepEqual(items.map(item => item.shape), ['rectangle']);
  const [group] = faceShapesOf(items, { units: 'mm', labelOf });
  // Its middle is the face's (0, 0); its first corner, where the frame starts, is 4.2 and 0.7 from it.
  assert.deepEqual(group.shapes, [{ kind: 'rectangle', center: [4.2, 0.7], size: [8, 3], angle: 30 }]);
});

test("says a Shapes rectangle as one only where it lies square on the face; slanted to the view, the four-cornered polygon it lies as", () => {
  // Seen square on, a rounded Shapes rectangle is a rectangle on the face, its corners where its straight sides meet: 8 × 3 mm
  // turned 30°, its middle under the window's.
  const square = rig({ roll: 30, span: 12.5 });
  const [flat] = projectAnnotations(square, shapeMarks('rectangle', { x: 34, y: 44 }, { x: 66, y: 56 }, STYLE), SIZE, { touchesAt: onTop });
  assert.deepEqual(faceShapesOf([flat], { units: 'mm', labelOf })[0].shapes,
    [{ kind: 'rectangle', center: tenths(onTopFace(square, flat.level.point, { x: 50, y: 50 })), size: [8, 3], angle: 30 }]);
  // Tipped 45° back as well, the face takes it as a parallelogram: the polygon of the corners its straight sides meet at, each
  // where a corner of the rectangle drawn on the screen falls on the face.
  const slanted = rig({ roll: 30, tilt: 45, span: 12.5 });
  const [ink] = projectAnnotations(slanted, shapeMarks('rectangle', { x: 38, y: 46 }, { x: 62, y: 54 }, STYLE), SIZE, { touchesAt: onTop });
  const [shape] = faceShapesOf([ink], { units: 'mm', labelOf })[0].shapes;
  const drawnCorners = [[38, 46], [62, 46], [62, 54], [38, 54]].map(([x, y]) => onTopFace(slanted, ink.level.point, { x, y }));
  assert.deepEqual([shape.kind, shape.points.length], ['polygon', 4]);
  for (const corner of drawnCorners) {
    assert.ok(shape.points.some(point => Math.hypot(point[0] - corner[0], point[1] - corner[1]) <= 0.1),
      `no corner within 0.1 of (${corner}): ${JSON.stringify(shape.points)}`);
  }
});

test("finds a drawn rectangle's four straight sides at any turn and tilt: square on a rectangle, slanted its four corners", () => {
  const box = ([fx, fy, tx, ty]) => [{ x: fx, y: fy }, { x: tx, y: ty }];
  const drawnOn = (view, [from, to]) => {
    const runtime = rig({ span: 12.5, ...view });
    const [ink] = projectAnnotations(runtime, shapeMarks('rectangle', from, to, STYLE), SIZE, { touchesAt: onTop });
    const corners = [[from.x, from.y], [to.x, from.y], [to.x, to.y], [from.x, to.y]].map(([x, y]) => onTopFace(runtime, ink.level.point, { x, y }));
    return { shape: faceShapesOf([ink], { units: 'mm', labelOf })[0].shapes[0], corners, middle: onTopFace(runtime, ink.level.point, { x: 50, y: 50 }) };
  };
  // Square on, turned 5°, in either projection: a rectangle of the 10 × 5 mm drawn, under the window's middle.
  for (const perspective of [false, true]) {
    const { shape, middle } = drawnOn({ roll: 5, perspective }, box([30, 40, 70, 60]));
    assert.deepEqual(shape, { kind: 'rectangle', center: tenths(middle), size: [10, 5], angle: 5 }, perspective ? 'in perspective' : 'orthographic');
  }
  // Isometric-like, it lands as a parallelogram: its four corners, each where a drawn corner falls on the face.
  const near = (points, corner, within) => points.some(point => Math.hypot(point[0] - corner[0], point[1] - corner[1]) <= within);
  const iso = drawnOn({ tilt: 54.7, roll: 45, block: [400, 400] }, box([30, 40, 70, 60]));
  assert.deepEqual([iso.shape.kind, iso.shape.points.length], ['polygon', 4]);
  assert.ok(iso.corners.every(corner => near(iso.shape.points, corner, 0.1)), JSON.stringify(iso.shape.points));
  // At any turn and tilt, in either projection, it is never said as its outline: square on a rectangle, else its four corners,
  // every corner said where the drawn one falls (a rectangle's rebuilt from its centre, size and angle as said, to their tenths).
  const corners = ({ center: [cu, cv], size: [w, h], angle }) => {
    const t = angle * Math.PI / 180, along = [Math.cos(t) * w / 2, Math.sin(t) * w / 2], across = [-Math.sin(t) * h / 2, Math.cos(t) * h / 2];
    return [[1, 1], [-1, 1], [-1, -1], [1, -1]].map(([a, b]) => [cu + a * along[0] + b * across[0], cv + a * along[1] + b * across[1]]);
  };
  const boxes = [[30, 40, 70, 60], [36, 44, 61, 52], [25, 30, 75, 70], [45, 47, 55, 53]].map(box);
  let index = 0;
  for (const perspective of [false, true]) {
    for (const tilt of [0, 20, 40, 54.7, 65]) {
      for (const roll of [0, 5, 17, 33, 45, 62, 81]) {
        const { shape, corners: drawn } = drawnOn({ tilt, roll, perspective, block: [400, 400] }, boxes[index++ % boxes.length]);
        const at = `${perspective ? 'perspective' : 'orthographic'}, tilt ${tilt}, roll ${roll}: ${JSON.stringify(shape)}`;
        if (tilt === 0) assert.equal(shape.kind, 'rectangle', at);
        if (shape.kind === 'rectangle') assert.ok(drawn.every(corner => near(corners(shape), corner, 0.15)), at);
        else assert.ok(shape.kind === 'polygon' && shape.points.length === 4 && drawn.every(corner => near(shape.points, corner, 0.1)), at);
      }
    }
  }
  // Too small to say at a tenth, its corners all one point, it is no polygon.
  const tiny = drawn('tiny', [[0, 0, 4], [0.04, 0, 4], [0.03, 0.02, 4], [0.01, 0.02, 4], [0, 0, 4]], { closed: true, shape: 'rectangle' });
  assert.deepEqual(faceShapesOf([tiny], { units: 'mm', labelOf })[0].shapes, [{ kind: 'polyline', points: [[0, 0]] }]);
});

test("says an ellipse only where its outline is one, on a slanted face too, fitted to all of it; else the polygon it is", () => {
  const slanted = rig({ roll: 30, tilt: 45, span: 12.5 });
  const [ink] = projectAnnotations(slanted, shapeMarks('ellipse', { x: 38, y: 46 }, { x: 62, y: 54 }, STYLE), SIZE, { touchesAt: onTop });
  const [ellipse] = faceShapesOf([ink], { units: 'mm', labelOf })[0].shapes;
  assert.equal(ellipse.kind, 'ellipse');
  // As said, to the tenth, it runs through the ink all the way round.
  const { center: [cu, cv], radii: [a, b], angle } = ellipse;
  const turn = angle * Math.PI / 180;
  for (const [u, v] of uvOf(ink, ink.level.point)) {
    const along = (u - cu) * Math.cos(turn) + (v - cv) * Math.sin(turn), across = (v - cv) * Math.cos(turn) - (u - cu) * Math.sin(turn);
    const off = Math.abs((along / a) ** 2 + (across / b) ** 2 - 1) / (2 * Math.hypot(along / (a * a), across / (b * b)));
    assert.ok(off <= 0.15, `(${u}, ${v}) is ${off} off the ellipse said`);
  }
  // A closed outline called a shape it is not, a square an ellipse and a trapezoid a rectangle, is the polygon it is.
  const square = drawn('round', [[0, 0, 4], [4, 0, 4], [4, 4, 4], [0, 4, 4], [0, 0, 4]], { closed: true, shape: 'ellipse' });
  const trapezoid = drawn('box', [[0, 0, 4], [6, 0, 4], [5, 3, 4], [1, 3, 4], [0, 0, 4]], { closed: true, shape: 'rectangle' });
  assert.deepEqual(faceShapesOf([square, trapezoid], { units: 'mm', labelOf })[0].shapes, [
    { kind: 'polygon', points: [[0, 0], [4, 0], [4, 4], [0, 4]] },
    { kind: 'polygon', points: [[0, 0], [6, 0], [5, 3], [1, 3]] },
  ]);
});

test("keeps each Shapes tool's own shape: a line's ends, an arrow from its tail to its tip, text where it was written, an ellipse", () => {
  const runtime = rig();
  const items = projectAnnotations(runtime, [
    ...shapeMarks('line', { x: 42, y: 52 }, { x: 58, y: 52 }, STYLE),
    ...shapeMarks('arrow', { x: 44, y: 54 }, { x: 52, y: 46 }, STYLE),
    textMark('Cut here', { x: 46, y: 48 }, { width: 8, height: 4 }, { color: '#ff2d55', fontPx: 16 }),
    ...shapeMarks('ellipse', { x: 51, y: 48 }, { x: 57, y: 52 }, STYLE),
  ], SIZE, { touchesAt: onTop });
  // All on the one face: one frame, from where the first of them starts, (-8, -2) on the top.
  const groups = faceShapesOf(items, { units: 'mm', labelOf });
  assert.deepEqual(groups.map(group => group.frame.origin), [[-8, -2, 4]]);
  // The arrow is said once, by its line: its head's wings are part of it.
  assert.deepEqual(groups[0].shapes, [
    { kind: 'line', from: [0, 0], to: [16, 0] },
    { kind: 'arrow', from: [2, -2], to: [10, 6] },
    { kind: 'text', at: [4, 4], text: 'Cut here' },
    { kind: 'ellipse', center: [12, 2], radii: [3, 2], angle: 0 },
  ]);
  assert.deepEqual(faceShapesText(groups, 'mm').split('\n').slice(2), [
    '- line from (0, 0) to (16, 0)',
    '- arrow from (2, -2) to (10, 6)',
    '- text "Cut here" at (4, 4)',
    '- ellipse centred at (12, 2), radii 3 × 2, turned 0°',
  ]);
});

test("leaves a mark across two faces to the picture", () => {
  const runtime = rig({ boss: true });
  const x = point => point.x - 50;
  const shapes = (marks, touchesAt, placement = 'surface') =>
    faceShapesOf(projectAnnotations(runtime, marks, SIZE, { touchesAt, placement }), { units: 'mm', labelOf });
  // From the block's top (x -4) onto the boss's (x 6): it touches both faces, and what is under it climbs 2 mm.
  const across = stroke('across', [[46, 50], [56, 50]]);
  assert.deepEqual(shapes([across], point => (x(point) < 4 ? onTop() : [{ part: 'boss', ref: BOSS }])), []);
  // Either keeps it out alone. Named as the one face, it still climbs onto the boss; On plane its ink stays at the top's
  // level, but the boss is what it was drawn over.
  assert.deepEqual(shapes([across], onTop), []);
  assert.deepEqual(shapes([across], onTop, 'plane'), []);
  // Flat on the top, it stays out across two faces of that one plane, and where an edge is touched more than a face.
  const flat = stroke('flat', [[42, 50], [50, 50]]);
  assert.deepEqual(shapes([flat], point => (x(point) < -4 ? onTop() : [{ part: 'block', ref: SPLIT }])), []);
  assert.deepEqual(shapes([flat], () => [{ part: 'block', ref: EDGE }, ...onTop()]), []);
  // Half of it run off the block into the air, it is not drawn on the face, so it is not said as on it; nor a line drawn from
  // the air onto the face (over nothing the renderer names nothing).
  const block = point => (Math.abs(x(point)) <= 10 ? onTop() : []);
  assert.deepEqual(shapes([stroke('off', [[50, 47], [75, 47]])], block), []);
  assert.deepEqual(shapes(shapeMarks('line', { x: 80, y: 47 }, { x: 55, y: 47 }, STYLE), block), []);
  assert.deepEqual(shapes(shapeMarks('arrow', { x: 80, y: 47 }, { x: 55, y: 47 }, STYLE), block), []);
  // On the top face alone, it is a shape on it; but not in a view that names no face.
  assert.deepEqual(shapes([flat], onTop).map(group => group.shapes), [[{ kind: 'polyline', points: [[0, 0], [8, 0]] }]]);
  assert.deepEqual(faceShapesOf(projectAnnotations(runtime, [flat], SIZE, { touchesAt: onTop }), { units: 'mm' }), []);
});

test("writes inches for an inch part", () => {
  // The model is in millimetres; an inch part's marks are said in inches, to a tenth of an inch.
  const groups = faceShapesOf([drawn('in', [[25.4, 0, 12.7], [50.8, 0, 12.7], [76.2, 25.4, 12.7]])], { units: 'in', labelOf });
  assert.deepEqual(groups.map(group => [group.frame.origin, group.shapes]), [[[1, 0, 0.5], [{ kind: 'polyline', points: [[0, 0], [1, 0], [2, 1]] }]]]);
  assert.deepEqual(faceShapesText(groups, 'in').split('\n'), [
    "Marks on the model, in each face's own coordinates (in):",
    'block · face 6: plane through (1, 0, 0.5), normal (0, 0, 1), u along (1, 0, 0), v along (0, 1, 0)',
    '- polyline (0, 0) → (1, 0) → (2, 1)',
  ]);
});

test("takes a face's u along the model's X, or its Y where X is within 10° of the face's normal, and v across them", () => {
  const tilt = degrees => [Math.cos(degrees * Math.PI / 180), 0, Math.sin(degrees * Math.PI / 180)];
  const groups = faceShapesOf([
    // The block's side, facing X: u along Y, v along Z.
    drawn('side', [[10, -1, 2], [10, 3, 2]], { normal: [1, 0, 0], ref: SIDE }),
    // A face tilted 5° from it is still within 10°.
    drawn('tilted', [[10, 0, 1], [10, 2, 1]], { normal: tilt(5), ref: SPLIT }),
    // A 45° chamfer: X along it, v along Y. A face the renderer has no name for goes by its reference.
    drawn('chamfer', [[9, 0, 3], [9, 4, 3]], { normal: tilt(45), ref: CHAMFER }),
  ], { units: 'mm', labelOf });
  assert.deepEqual(groups.map(({ label, frame }) => [label, frame.u, frame.v, frame.normal]), [
    ['block · face 2', [0, 1, 0], [0, 0, 1], [1, 0, 0]],
    [SPLIT, [0, 1, 0], [-0.087, 0, 0.996], [0.996, 0, 0.087]],
    [CHAMFER, [0.707, 0, -0.707], [0, 1, 0], [0.707, 0, 0.707]],
  ]);
  // Two marks on each face, one face's frame: the second said from where the first started.
  const [side] = faceShapesOf([drawn('a', [[10, -1, 2], [10, 3, 2]], { normal: [1, 0, 0], ref: SIDE }),
    drawn('b', [[10, 0, 0], [10, 0, 3]], { normal: [1, 0, 0], ref: SIDE })], { units: 'mm', labelOf });
  assert.deepEqual(side.shapes, [{ kind: 'polyline', points: [[0, 0], [4, 0]] }, { kind: 'polyline', points: [[1, -2], [1, 1]] }]);
});

test("words the agent's text exactly", () => {
  const groups = [{
    face: '/work/servo.step#o1.f12', label: 'Hole (6) · face 12',
    frame: { origin: [10, 0, 5], u: [1, 0, 0], v: [0, 1, 0], normal: [0, 0, 1] },
    shapes: [
      { kind: 'rectangle', center: [12, 4.5], size: [8, 3], angle: 0 },
      { kind: 'polyline', points: [[0, 0], [5, 2], [9, 2]] },
    ],
  }];
  assert.equal(faceShapesText(groups, 'mm'), [
    "Marks on the model, in each face's own coordinates (mm):",
    'Hole (6) · face 12: plane through (10, 0, 5), normal (0, 0, 1), u along (1, 0, 0), v along (0, 1, 0)',
    '- rectangle centred at (12, 4.5), 8 × 3, turned 0°',
    '- polyline (0, 0) → (5, 2) → (9, 2)',
  ].join('\n'));
  // No mark on a face, no text.
  assert.equal(faceShapesText([], 'mm'), '');
});
