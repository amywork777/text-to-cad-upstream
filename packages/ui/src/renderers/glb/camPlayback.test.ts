import { Mesh } from 'three';
import { expect, it, vi } from 'vitest';
import { readCamJob } from '../../../dist/renderers/glb/cam/extras.js';
import { SIMULATE_SECONDS, camClips, camSceneMeshes, camTimeline, showCamMeshes } from '../../../dist/renderers/glb/cam/playback.js';
import { camExtras, camScene } from './__tests__/camFile';

it('plays the program as Simulate, fast enough to watch, its moment the program\'s time', () => {
  const job = readCamJob(camScene())!;
  expect(camTimeline(job)).toEqual({ from: 0, to: 90, pace: SIMULATE_SECONDS / 90 });
  const onMoment = vi.fn();
  const clips = camClips(job, onMoment);
  // One setup: Simulate alone.
  expect(clips.map((clip: any) => [clip.id, clip.label, clip.duration])).toEqual([['cam:simulate', 'Simulate', 30]]);
  clips[0].play.apply(15);
  expect(onMoment).toHaveBeenLastCalledWith({ t: 45, setup: null });
  clips[0].play.apply(99);
  expect(onMoment).toHaveBeenLastCalledWith({ t: 90, setup: null });
  clips[0].play.release();
  expect(onMoment).toHaveBeenLastCalledWith(null);
});

it('adds a clip per setup when the job has more than one, each at the same pace over its own span', () => {
  const extras = camExtras();
  extras.setups.push({ id: 'bottom', plain: 'Bottom', time_s: 30, orientation: '-Z', operations: [
    { index: 2, op: 'contour', plain: 'Profile', tool: 'T1', tool_plain: '6 mm flat', time_s: 30, t0: 90, t1: 120, summary: 'Profile', limits: [] } as any] });
  extras.duration_s = 120;
  const onMoment = vi.fn();
  const clips = camClips(readCamJob(camScene({ extras }))!, onMoment);
  expect(clips.map((clip: any) => [clip.label, clip.duration])).toEqual([['Simulate', 30], ['Simulate Top', 22.5], ['Simulate Bottom', 7.5]]);
  clips[2].play.apply(0);
  expect(onMoment).toHaveBeenLastCalledWith({ t: 90, setup: 'bottom' });
  // A real-time program shorter than the cap plays as it runs.
  const short = camExtras();
  short.duration_s = 10;
  short.setups[0].operations.forEach((op: any) => { op.t0 /= 9; op.t1 /= 9; });
  expect(camClips(readCamJob(camScene({ extras: short }))!, onMoment)[0].duration).toBe(10);
});

it('shows the part and the stock as Display says, and the stock an operation leaves while it plays', () => {
  const root = camScene();
  const job = readCamJob(root)!;
  const meshes = camSceneMeshes(root);
  expect([meshes.part.length, meshes.stock.length]).toEqual([1, 1]);
  expect(showCamMeshes(meshes, job, { part: true, stock: false })).toBe(true);
  expect([meshes.part[0].visible, meshes.stock[0].object.visible]).toEqual([true, false]);
  expect(showCamMeshes(meshes, job, { part: true, stock: false })).toBe(false);
  // Stock stored after each operation: the one after the last finished, the final one at rest.
  const afterFace = new Mesh();
  Object.assign(afterFace.userData, { kind: 'stock', operation: 0 });
  const afterPocket = new Mesh();
  Object.assign(afterPocket.userData, { kind: 'stock', operation: 1 });
  root.remove(meshes.stock[0].object);
  root.add(afterFace, afterPocket);
  const staged = camSceneMeshes(root);
  showCamMeshes(staged, job, { stock: true, time: 40 });
  expect([afterFace.visible, afterPocket.visible]).toEqual([true, false]);
  showCamMeshes(staged, job, { stock: true, time: null });
  expect([afterFace.visible, afterPocket.visible]).toEqual([false, true]);
});
