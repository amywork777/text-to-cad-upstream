import React, { forwardRef, useEffect, useImperativeHandle } from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import * as THREE from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { buildGlbDocumentFromBuffer } from '@cad/core/lib/render/glbMeshData.js';
import { createGlbScene } from '@cad/core/lib/render/glbScene.js';

// A 0.11 plan's `result.glb` (the real one, `plate.plan.result.glb`) is the picture alone: its job is the
// `result.json` beside it, which the renderer reads through the workspace's resources, from the GLB's own URL. Only
// what loads the file and the WebGL viewport are replaced.
const loaded = vi.hoisted(() => ({ scene: null as any }));
vi.mock('../../../dist/renderers/kit/shell/ShellViewport.js', () => ({
  default: forwardRef(function StandInViewport(props: any, ref) {
    useImperativeHandle(ref, () => ({ requestRender() {} }));
    const update = props.viewUpdate;
    useEffect(() => { if (update?.revision) update.binding.complete(update.revision); }, [update?.revision, update?.binding]);
    return <div data-stand-in-viewport="" />;
  })
}));
vi.mock('../../../dist/renderers/glb/useGlbScene.js', () => ({
  useGlbScene: () => ({ scene: loaded.scene, revision: 'one', busy: false, error: null, progress: null })
}));
import GlbRenderer from '../../../dist/renderers/glb/GlbRenderer.js';
import { ViewerHostContext } from '../../../dist/host/context.js';
import { testHost } from '../../../dist/host/testing/host.js';

const fixture = (name: string) => {
  const file = readFileSync(join(__dirname, '__tests__', name));
  const copy = new Uint8Array(file.byteLength);
  copy.set(file);
  return copy;
};
const GLB_URL = '/api/v1/local/files?path=%2Fwork%2FCAM%2Fresult.glb&v=1';

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); loaded.scene?.dispose?.(); loaded.scene = null; });

async function mount(readJson: (url: string) => Promise<unknown>) {
  const document = await buildGlbDocumentFromBuffer(fixture('plate.plan.result.glb').buffer, {});
  loaded.scene = createGlbScene(THREE, document);
  const asked: string[] = [];
  const resources = {
    resolveDependency: (source: string, reference: string) => `${source}#${reference}`,
    readJson: (url: string) => { asked.push(url); return readJson(url); },
  };
  const settings = { toolStack: { panels: {}, collapsed: {} } };
  const catalog = { entries: [], error: null };
  const preferences = { getSnapshot: () => settings, subscribe: () => () => {}, update() {} };
  const client = { resources, subscribe: () => () => {}, getSnapshot: () => catalog };
  const path = '/work/CAM/result.glb';
  const props = { source: { id: 'one' }, file: { path, name: 'result.glb', kind: 'file' }, document: null, navbarSlot: null,
    onReady() {}, onOpenFile() {}, appearance: { colorScheme: 'light' }, state: null, onStateChange() {}, onNavigationActionsChange() {}, reload() {},
    data: { client, entry: { path, kind: 'glb', url: GLB_URL, hash: 'h' }, services: { preferences } } };
  render(<ViewerHostContext.Provider value={testHost()}><GlbRenderer {...(props as any)} /></ViewerHostContext.Provider>);
  return asked;
}

it('a plan\'s result.glb reads its job from the result.json beside it, then offers Job with the plan\'s operations', async () => {
  const written = JSON.parse(new TextDecoder().decode(fixture('plate.plan.result.json')));
  const asked = await mount(async () => written);
  const job = await waitFor(() => {
    const found = document.querySelector<HTMLElement>('[data-flat-panel-section="job"]');
    if (!found) throw new Error('no Job yet');
    return found;
  }, { timeout: 30000 });
  expect(asked).toEqual([`${GLB_URL}#result.json`]);
  expect(job.textContent).toContain(written.measurements.verdict.headline);
  for (const name of ['Face', 'Pocket', 'Drill']) expect(screen.getByRole('button', { name: `Select ${name}` })).toBeTruthy();
}, 30000);

it('a plan whose result.json will not read is refused as a file that failed to load, never drawn without its job', async () => {
  await mount(async () => { throw new Error('result.json is not a file the viewer sends'); });
  const alert = await screen.findByRole('alert', {}, { timeout: 30000 });
  expect(alert.textContent).toContain('result.json beside this GLB could not be read (result.json is not a file the viewer sends)');
  expect(document.querySelector('[data-flat-panel-section="job"]')).toBeNull();
}, 30000);
