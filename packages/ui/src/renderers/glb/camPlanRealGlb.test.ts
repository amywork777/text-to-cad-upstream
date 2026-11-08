import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import * as THREE from 'three';
import { expect, it } from 'vitest';
import { buildGlbDocumentFromBuffer } from '@cad/core/lib/render/glbMeshData.js';
import { createGlbScene } from '@cad/core/lib/render/glbScene.js';
import { camResultKind, carriesCamJob, isCamPlan } from '../../../dist/renderers/glb/cam/detect.js';
import { CamResultError, readCamPlan } from '../../../dist/renderers/glb/cam/extras.js';
import { cadFrame, camToolpathObjects, readCamSegments, toolPositionAt } from '../../../dist/renderers/glb/cam/lines.js';
import { camSceneMeshes, camTimeline } from '../../../dist/renderers/glb/cam/playback.js';
import { createCamTool } from '../../../dist/renderers/glb/cam/tool.js';

/*
 * Two real 0.11 results, written by `cad step plan plate.step --job ... --out DIR` (FreeCAD 1.1.1 plans, cad checks),
 * not by hand: a 40 x 30 x 6 mm plate with a 14 x 10 pocket down to z = 3 and a Ø5 through hole, on LinuxCNC.
 * - `plate.plan.result.*`: ready to cut, one setup `top` (+Z): face and pocket with T1 (a 4 mm flat), drill with T2
 *   (a 5 mm drill), 39 s, one G-code file.
 * - `plate.fix.result.*`: refused, T2 a 6 mm drill in the 5 mm hole (one `drill_size` error), so the drill is never
 *   planned and no G-code is written; the pocket is.
 * Each is the folder's `result.glb` (the picture: the part, the stock and the toolpaths) and its `result.json` (the
 * plan's every number). Loaded as the viewer loads them: GLTFLoader through core's GLB document.
 */
type Sample = 'plan' | 'fix';
const bytes = (name: string) => {
  const file = readFileSync(join(__dirname, '__tests__', name));
  const copy = new Uint8Array(file.byteLength);
  copy.set(file);
  return copy;
};
const planJson = (name: Sample) => JSON.parse(new TextDecoder().decode(bytes(`plate.${name}.result.json`)));
const load = async (name: Sample) => {
  const document = await buildGlbDocumentFromBuffer(bytes(`plate.${name}.result.glb`).buffer, {});
  return { document, scene: createGlbScene(THREE, document), root: document.scene };
};

/** A point of the file (glTF metres, Y up) in CAD mm, Z up. */
const cadPoint = ([x, y, z]: number[]) => [x * 1000, -z * 1000, y * 1000];

/** A mesh's box in CAD mm. */
const cadBox = (mesh: any) => {
  const position = mesh.geometry.getAttribute('position');
  const points = Array.from({ length: position.count }, (_, i) => cadPoint([position.getX(i), position.getY(i), position.getZ(i)]));
  return { min: [0, 1, 2].map((axis) => Math.min(...points.map((at) => at[axis]))), max: [0, 1, 2].map((axis) => Math.max(...points.map((at) => at[axis]))) };
};

it('knows a real plan by its asset\'s generator, not by extras it does not carry', async () => {
  const { document, scene, root } = await load('plan');
  expect(document.asset.generator).toBe('cad plan');
  expect([isCamPlan(document), camResultKind(document), carriesCamJob(root)]).toEqual([true, 'plan', false]);
  expect(camResultKind({ scene: root, asset: { generator: 'cad solve' } })).toBeNull();
  expect(camResultKind(null)).toBeNull();
  scene.dispose();
});

it('reads a real ready plan\'s job from its result.json: the verdict, the setup, every operation and tool as the plan wrote them', async () => {
  const written = planJson('plan');
  const job = readCamPlan(written);
  const numbers = written.measurements;
  expect([job.verdict.status, job.verdict.headline, job.verdict.errors, job.verdict.gcode]).toEqual(['ready', numbers.verdict.headline, 0, '']);
  expect([job.post, job.durationS, job.toolChanges, job.document, job.safety]).toEqual(['linuxcnc', numbers.duration_s, 1, written.path, numbers.safety]);
  expect(job.setups.map((setup: any) => [setup.id, setup.orientation, setup.axis, setup.timeS, setup.operations.map((op: any) => op.index)]))
    .toEqual([['top', '+Z', [0, 0, 1], numbers.setups[0].time_s, [0, 1, 2]]]);
  expect(job.operations.map((op: any) => [op.index, op.op, op.tool, op.toolType, op.toolDiameterMm, op.rpm, op.feedMmMin, op.t0, op.t1, op.faces]))
    .toEqual(numbers.operations.map((op: any) => [op.index, op.op, op.tool, op.tool === 'T1' ? 'flat' : 'drill', op.tool_diameter_mm, op.rpm,
      op.feed_mm_min, op.t0, op.t1, op.faces]));
  expect(job.tools.map((tool: any) => [tool.id, tool.plain, tool.type, tool.operations])).toEqual([['T1', '4 mm flat', 'flat', [0, 1]], ['T2', '5 mm drill', 'drill', [2]]]);
  expect(job.posts.map((post: any) => [post.setup, post.file.split('/').at(-1), post.post, post.tool])).toEqual([['top', 'plate.top.ngc', 'linuxcnc', '']]);
  expect(job.assumed).toEqual([{ key: 'machine.rapid_mm_min', value: '3000', why: 'for the cycle time only' }]);
  expect(job.findings).toEqual([]);
});

it('draws a real ready plan: every operation\'s lines on the program\'s clock, the part, and the stock box result.json gives', async () => {
  const { scene, root } = await load('plan');
  const written = planJson('plan');
  const job = readCamPlan(written);
  const lines = camToolpathObjects(root);
  expect(lines.map((entry: any) => [entry.setup, entry.kind])).toEqual([['top', 'feed'], ['top', 'rapid']]);
  expect(Object.keys(lines[0].object.geometry.attributes).sort()).toEqual(['_cam_op', '_cam_t', 'position']);
  const { groups, timeline } = readCamSegments(THREE, root);
  expect([...new Set(groups.filter((group: any) => group.kind === 'feed').map((group: any) => group.op))].sort()).toEqual([0, 1, 2]);
  const last = Math.max(...timeline.segments.map((segment: any) => segment.t1));
  expect(last).toBeLessThanOrEqual(job.durationS + 1e-2);
  expect(last).toBeGreaterThan(job.durationS * 0.9);
  expect(camTimeline(job).to).toBeCloseTo(job.durationS, 3);
  for (const op of job.operations) {
    const own = timeline.segments.filter((segment: any) => segment.op === op.index);
    expect(own.length).toBeGreaterThan(0);
    expect(Math.min(...own.map((segment: any) => segment.t0))).toBeGreaterThanOrEqual(op.t0 - 1e-2);
    expect(Math.max(...own.map((segment: any) => segment.t1))).toBeLessThanOrEqual(op.t1 + 1e-2);
  }
  const meshes = camSceneMeshes(root);
  expect([meshes.part.map((mesh: any) => mesh.name), meshes.stock.map((mesh: any) => mesh.name)]).toEqual([['part'], ['stock']]);
  // The stock box drawn is the plan's, in the file's metres turned to CAD mm; every cut is over it, within the tool's radius.
  const stock = cadBox(meshes.stock[0]);
  [0, 1, 2].forEach((axis) => {
    expect(stock.min[axis]).toBeCloseTo(written.measurements.stock_mm.min[axis], 3);
    expect(stock.max[axis]).toBeCloseTo(written.measurements.stock_mm.max[axis], 3);
  });
  const cuts = groups.filter((entry: any) => entry.kind === 'feed').flatMap((group: any) =>
    Array.from({ length: group.positions.length / 3 }, (_, i) => cadPoint(Array.from(group.positions.subarray(i * 3, i * 3 + 3)))));
  for (const axis of [0, 1]) {
    expect(Math.min(...cuts.map((at: number[]) => at[axis]))).toBeGreaterThanOrEqual(stock.min[axis] - 2.01);
    expect(Math.max(...cuts.map((at: number[]) => at[axis]))).toBeLessThanOrEqual(stock.max[axis] + 2.01);
  }
  // The file's metres are 1000 CAD mm a unit, and CAD's +Z is the file's +Y: the tool stands up out of the top setup.
  const frame = cadFrame(THREE, root, scene.object3D);
  expect(frame.mmPerUnit).toBeCloseTo(1000);
  const tool = createCamTool(THREE, root, job, frame);
  const place = toolPositionAt(timeline, (job.operations[1].t0 + job.operations[1].t1) / 2)!;
  expect(place.op).toBe(1);
  tool.show(place);
  expect(new THREE.Vector3(0, 1, 0).applyQuaternion(tool.object3D.quaternion).y).toBeCloseTo(1, 6);
  tool.dispose();
  scene.dispose();
});

it('reads a real refused plan: its error on the operation that cuts the face it names, no G-code, and only the pocket drawn', async () => {
  const { scene, root } = await load('fix');
  const written = planJson('fix');
  const job = readCamPlan(written);
  expect([job.verdict.status, job.verdict.errors, job.verdict.gcode, job.posts]).toEqual(['fix', 1, 'G-code not written: fix 1 error first', []]);
  expect(job.findings).toEqual([{ check: 'drill_size', level: 'error', message: written.findings[0].message, operation: 1, operations: [1], at: null }]);
  expect(job.tools.map((tool: any) => [tool.id, tool.plain])).toEqual([['T1', '4 mm flat'], ['T2', '6 mm drill']]);
  const { timeline } = readCamSegments(THREE, root);
  expect(new Set(timeline.segments.map((segment: any) => segment.op))).toEqual(new Set([0]));
  scene.dispose();
});

it('reads a finding\'s places as the plan joins them: a point, and an operation by its number', () => {
  const written = planJson('fix');
  written.findings = [
    { severity: 'error', code: 'gouge', message: 'cuts into the part', location: '(1.5, -2, 3), (4, 5, 6)', hint: null },
    { severity: 'warning', code: 'clamped', message: 'held', location: 'operation 1', hint: null },
  ];
  const [gouge, clamped] = readCamPlan(written).findings;
  expect([gouge.at, gouge.operation, clamped.level, clamped.operations]).toEqual([[1.5, -2, 3], null, 'warning', [0]]);
  written.findings = [{ severity: 'error', code: 'gouge', message: 'x', location: 'operation 9', hint: null }];
  expect(() => readCamPlan(written)).toThrow('result.json.findings[0].location names operation 9, which the result does not list');
});

it('refuses a real plan missing what the plan always writes, naming it, rather than draw a default in its place', () => {
  const cases: [(json: any) => void, string][] = [
    [(json) => { delete json.measurements; }, 'result.json.measurements is not an object'],
    [(json) => { delete json.measurements.operations[1].t0; }, 'result.json.measurements.operations[1].t0 is not a number'],
    [(json) => { json.measurements.operations[0].tool_plain = '4 mm'; }, 'result.json.measurements.operations[0].tool_plain names no kind of tool'],
    [(json) => { json.measurements.operations[2].setup = 'bottom'; }, 'result.json.measurements.operations[2].setup names bottom, a setup the result does not list'],
    [(json) => { json.measurements.tools.push('T9'); }, 'result.json.measurements.tools[2] names T9, a tool no operation runs'],
    [(json) => { delete json.measurements.setups[0].matrix; }, 'result.json.measurements.setups[0].matrix is not a list'],
    [(json) => { delete json.measurements.tool_changes; }, 'result.json.measurements.tool_changes is not an object'],
    [(json) => { delete json.path; }, 'result.json.path is not text'],
    [(json) => { delete json.findings; }, 'result.json.findings is not a list'],
  ];
  for (const [damage, said] of cases) {
    const json = planJson('plan');
    damage(json);
    expect(() => readCamPlan(json)).toThrow(CamResultError);
    expect(() => readCamPlan(json)).toThrow(`This CAM result is damaged: ${said}`);
  }
});
