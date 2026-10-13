import React, { forwardRef, useEffect, useImperativeHandle } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { BufferAttribute, BufferGeometry, Group, Mesh } from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { camScene } from './__tests__/camFile';

// The CAM result viewer is a chunk of its own (`camView.jsx`): a plain GLB never fetches it, and a result loads it
// before it is drawn, then shows Job. Only what loads the file and the WebGL viewport are replaced.
const loaded = vi.hoisted(() => ({ scene: null as any, requested: 0, overlays: 0 }));
vi.mock('../../../dist/renderers/kit/shell/ShellViewport.js', () => ({
  default: forwardRef(function StandInViewport(props: any, ref) {
    useImperativeHandle(ref, () => ({ requestRender() {} }));
    const update = props.viewUpdate;
    useEffect(() => { if (update?.revision) update.binding.complete(update.revision); }, [update?.revision, update?.binding]);
    return <div data-stand-in-viewport="">{typeof props.children === 'function' ? props.children({ hostRef: { current: null }, runtimeRef: { current: null }, mountRef: { current: null }, viewerReadyTick: 1, commitScene: () => true }) : props.children}</div>;
  })
}));
vi.mock('../../../dist/renderers/glb/useGlbScene.js', () => ({
  useGlbScene: () => ({ scene: loaded.scene, revision: 'one', busy: false, error: null, progress: null })
}));
vi.mock('../../../dist/renderers/glb/camView.js', async (importOriginal) => { loaded.requested += 1; return importOriginal(); });
import GlbRenderer from '../../../dist/renderers/glb/GlbRenderer.js';
import { ViewerHostContext } from '../../../dist/host/context.js';
import { testHost } from '../../../dist/host/testing/host.js';

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(root: Group, path = '/models/part.glb') {
  const bounds = { min: [0, 0, 0], max: [10, 10, 5] };
  loaded.scene = { document: { scene: root, clips: [] }, object3D: root, bounds, restBounds: bounds, revision: 'one' };
  const settings = { toolStack: { panels: {}, collapsed: {} } };
  const catalog = { entries: [], error: null };
  const preferences = { getSnapshot: () => settings, subscribe: () => () => {}, update() {} };
  const client = { resources: {}, subscribe: () => () => {}, getSnapshot: () => catalog };
  const props = { source: { id: 'one' }, file: { path, name: path.split('/').at(-1), kind: 'file' }, document: null, navbarSlot: null,
    onReady() {}, onOpenFile() {}, appearance: { colorScheme: 'light' }, onStateChange() {}, onNavigationActionsChange() {}, reload() {},
    data: { client, entry: { path, hash: 'h' }, services: { preferences } } };
  return render(<ViewerHostContext.Provider value={testHost()}><GlbRenderer {...(props as any)} /></ViewerHostContext.Provider>);
}

it('a plain GLB never requests the CAM viewer', async () => {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3));
  const root = new Group();
  root.add(new Mesh(geometry));
  mount(root);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(loaded.requested).toBe(0);
  expect(screen.queryByRole('region', { name: 'Job' })).toBeNull();
  // It still has no tools, so no strip.
  expect(screen.queryByRole('group', { name: 'Interaction tools' })).toBeNull();
});

it('a CAM result loads the CAM viewer, then shows Job; a row isolates its operation until it is chosen again', async () => {
  mount(camScene(), '/models/part.cam.glb');
  // The model waits as the file loading while the chunk comes in.
  expect(screen.queryByRole('region', { name: 'Job' })).toBeNull();
  expect(await screen.findByRole('region', { name: 'Job' }, { timeout: 30000 })).toBeTruthy();
  expect(loaded.requested).toBe(1);
  const pocket = screen.getByRole('button', { name: 'Select Pocket' });
  fireEvent.click(pocket);
  expect(pocket.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Select Face' }));
  expect(screen.getByRole('button', { name: 'Select Pocket' }).getAttribute('aria-pressed')).toBe('false');
  fireEvent.click(screen.getByRole('button', { name: 'Select Face' }));
  expect(screen.getByRole('button', { name: 'Select Face' }).getAttribute('aria-pressed')).toBe('false');
}, 30000);
