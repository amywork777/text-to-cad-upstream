import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import * as THREE from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { buildGlbDocumentFromBuffer } from '@cad/core/lib/render/glbMeshData.js';
import { createGlbScene } from '@cad/core/lib/render/glbScene.js';
import { carriesFeaResult } from '../../../dist/renderers/glb/fea/generator.js';
import { readFeaResult, recolorByField } from '../../../dist/renderers/glb/feaResult.js';

/*
 * A real result, written by `cad step solve --out` (0.11's CalculiX solve), not by hand: `cantilever.result.glb`, a
 * 100 x 10 x 10 mm aluminium 6061-T6 bar fixed at one end (face 1) with 50 N down on the other (face 2), and the
 * `result.json` the same solve printed. Loaded as the viewer loads it (GLTFLoader through core's GLB document): the
 * result's extras arrive on its mesh, `_VON_MISES`, `_DISPLACEMENT` and `_FACE` lowercased, and its colour is the
 * ramp's texture at `TEXCOORD_0`.
 */
const fixture = (name: string) => {
  const file = readFileSync(join(__dirname, '__tests__', name));
  const copy = new Uint8Array(file.byteLength);
  copy.set(file);
  return copy;
};
const solved = JSON.parse(new TextDecoder().decode(fixture('cantilever.result.json')));

// jsdom decodes no image, so the ramp's PNG never loads: the image is handed over as it is, and its pixels are no part of the reading.
beforeEach(() => {
  vi.spyOn(THREE.ImageLoader.prototype, 'load').mockImplementation(function (_url: string, onLoad?: (image: HTMLImageElement) => void) {
    const image = document.createElement('img');
    queueMicrotask(() => onLoad?.(image));
    return image;
  });
});
afterEach(() => { vi.restoreAllMocks(); });

const load = async () => {
  const document = await buildGlbDocumentFromBuffer(fixture('cantilever.result.glb').buffer, {});
  return { scene: createGlbScene(THREE, document), root: document.scene };
};

it('reads a real 0.11 result: the renderer finds it, its safety factor is the solve\'s, its fields von Mises in MPa and displacement in mm', async () => {
  const { scene, root } = await load();
  expect(carriesFeaResult(root)).toBe(true);
  const result = readFeaResult(root)!;
  expect(result).not.toBeNull();
  expect(result.safetyFactor).toBe(solved.measurements.safety_factor);
  expect(result.deformationScale).toBe(solved.measurements.deformation_scale);
  expect(result.fields.map((field: any) => [field.attribute, field.name, field.units])).toEqual([
    ['_von_mises', 'von Mises stress', 'MPa'], ['_displacement', 'displacement', 'mm']]);
  // The ranges are the solve's peaks, in those units: the file's displacement is in metres, 1000 mm a unit.
  const [stress, displacement] = result.fields;
  expect(stress.max).toBe(solved.measurements.max_von_mises_MPa);
  expect([displacement.max, displacement.attributeScale]).toEqual([solved.measurements.max_displacement_mm, 1000]);
  expect(result.checks.map((check: any) => [check.kind, check.status])).toEqual(solved.measurements.checks.map((check: any) => [check.kind, check.status]));
  scene.dispose();
});

it('reads the real study: held at the fixed end, the 50 N load on the free end, made of 6061-T6', async () => {
  const { scene, root } = await load();
  const { study, faces } = readFeaResult(root)!;
  expect(faces).toEqual(['COMPOUND/face 1', 'COMPOUND/face 2', 'COMPOUND/face 3', 'COMPOUND/face 4', 'COMPOUND/face 5', 'COMPOUND/face 6']);
  expect(study.fixtures).toEqual([{ type: 'fixed', faces: ['COMPOUND/face 1'] }]);
  expect(study.loads).toEqual([{ type: 'force', faces: ['COMPOUND/face 2'], vector: solved.measurements.applied_force_N, pressure: null }]);
  expect(study.material).toEqual({ name: 'Aluminum 6061-T6', yieldMPa: solved.measurements.yield_MPa });
  scene.dispose();
});

it('recolours a real result coloured by its ramp texture: vertex colours from the field, the texture given way to them', async () => {
  const { scene, root } = await load();
  const result = readFeaResult(root)!;
  const { mesh } = result;
  expect(mesh.geometry.getAttribute('color')).toBeUndefined();
  expect(mesh.material.map).toBeTruthy();
  expect(recolorByField(mesh, result.fields[0], result.ramp)).toBe(true);
  const color = mesh.geometry.getAttribute('color');
  expect([color.count, color.itemSize, color.normalized]).toEqual([mesh.geometry.getAttribute('position').count, 4, true]);
  expect([mesh.material.map, mesh.material.vertexColors]).toEqual([null, true]);
  // The ramp runs blue to red: the most stressed vertex is drawn red, the least blue.
  const values = mesh.geometry.getAttribute('_von_mises').array as Float32Array;
  const at = (index: number) => Array.from((color.array as Uint8Array).slice(index * 4, index * 4 + 3));
  const peak = values.indexOf(Math.max(...values)), least = values.indexOf(Math.min(...values));
  expect(at(peak)[0]).toBeGreaterThan(at(peak)[2]);
  expect(at(least)[2]).toBeGreaterThan(at(least)[0]);
  scene.dispose();
});

it('refuses a real result missing what the solve always writes, rather than show less', async () => {
  const { scene, root } = await load();
  const mesh = readFeaResult(root)!.mesh;
  mesh.geometry.deleteAttribute('uv');
  expect(() => readFeaResult(root)).toThrow('no vertex colours and no ramp texture');
  delete mesh.userData.study;
  expect(() => readFeaResult(root)).toThrow();
  scene.dispose();
});
