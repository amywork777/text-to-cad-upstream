import { Group, Mesh } from 'three';
import { expect, it } from 'vitest';
import { camSourcePath, carriesCamJob, formatDuration, operationDetail, readCamJob } from '../../../dist/renderers/glb/cam/extras.js';
import { camExtras, camScene } from './__tests__/camFile';

it('reads the job a CAM result carries: verdict, setups, operations, errors first', () => {
  const job = readCamJob(camScene())!;
  expect(job.verdict).toEqual({ status: 'fix', headline: '1 to fix', errors: 1, warnings: 2 });
  expect(job.setups.map((setup: any) => [setup.id, setup.plain, setup.timeS, setup.operations.length])).toEqual([['top', 'Top', 90, 2]]);
  const pocket = job.operations[1];
  expect(pocket).toMatchObject({ index: 1, op: 'pocket', plain: 'Pocket', tool: 'T3', toolPlain: '4 mm ball', toolDiameterMm: 4, toolType: 'ball',
    rpm: 15000, feedMmMin: 900, timeS: 60, t0: 30, t1: 90, faces: ['#o1.f12', '#o1.f13'], limits: ['lite: engagement capped'], setup: 'top' });
  expect(job.findings.map((finding: any) => finding.level)).toEqual(['error', 'warning', 'warning']);
  expect(job.findings[0]).toMatchObject({ check: 'reach', message: 'Tool too long for this pocket', operation: 1, at: [4, 5, 6] });
  expect(job).toMatchObject({ durationS: 90, document: 'part.step', material: 'aluminum-6061', schema: 1 });
  expect(job.posts).toEqual([{ setup: 'top', file: 'part.top.nc', post: 'grbl' }]);
  expect(operationDetail(job.operations[0])).toBe('6 mm flat · 30 s');
});

it('is no job for a plain GLB, nor for one that only names the generator or only carries extras', () => {
  const plain = new Group();
  plain.add(new Mesh());
  expect(carriesCamJob(plain)).toBe(false);
  expect(readCamJob(plain)).toBeNull();
  expect(readCamJob(camScene({ extras: null }))).toBeNull();
  expect(readCamJob(camScene({ generator: '' }))).toBeNull();
  expect(readCamJob(null)).toBeNull();
});

it('reads a sparse or malformed job forgivingly: places, clocks, plain words and a verdict from its errors', () => {
  const root = camScene({ extras: { setups: [{ operations: [{ op: 'drill', time_s: '12', tool_plain: '5 mm drill' }, 'junk', { op: 'contour', time_s: 30 }] }, 7],
    findings: [{ check: 'gouge', severity: 'error', summary: 'Cuts into the part' }, { level: 'error' }, 'junk'], verdict: 'bad' } });
  const job = readCamJob(root)!;
  expect(job.setups).toHaveLength(1);
  expect(job.setups[0]).toMatchObject({ id: 'setup-1', plain: 'setup-1', timeS: 42 });
  expect(job.operations.map((op: any) => [op.index, op.plain, op.t0, op.t1, op.toolDiameterMm])).toEqual([[0, 'drill', 0, 12, 5], [1, 'contour', 12, 42, null]]);
  expect(job.operations[0].summary).toBe('drill with 5 mm drill');
  // A finding with nothing to say is left out.
  expect(job.findings).toEqual([{ check: 'gouge', level: 'error', message: 'Cuts into the part', operation: null, at: null }]);
  expect(job.verdict).toMatchObject({ status: 'fix', headline: '1 to fix', errors: 1, warnings: 0 });
  expect(job.durationS).toBe(42);
});

it('says a ready job in plain words when the file has no headline', () => {
  const extras = camExtras();
  extras.verdict = { status: 'ready' } as any;
  extras.findings = [];
  expect(readCamJob(camScene({ extras }))!.verdict).toEqual({ status: 'ready', headline: 'Ready to cut · 2 min · 2 tools', errors: 0, warnings: 0 });
});

it('resolves the part the job was planned from against the GLB, and says durations plainly', () => {
  expect(camSourcePath('/work/out/part.cam.glb', 'part.step')).toBe('/work/out/part.step');
  expect(camSourcePath('/work/out/part.cam.glb', '../src/part.step')).toBe('/work/src/part.step');
  expect(camSourcePath('/work/out/part.cam.glb', '/abs/part.step')).toBe('/abs/part.step');
  expect(camSourcePath('/work/out/part.cam.glb', '')).toBe('');
  expect([0, 0.4, 35, 59.4, 60, 2520, 3900, 7200].map(formatDuration)).toEqual(['0 s', '1 s', '35 s', '59 s', '1 min', '42 min', '1 h 5 min', '2 h']);
});
