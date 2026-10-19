import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BufferAttribute, BufferGeometry, Group, Mesh, Vector3 } from 'three';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';

// An FEA result's view under the real shell and the real playbar runtime (`useGlbAnimation`, not
// stood in): Play in preview steps a series' colours through its frames as the playbar's clock runs,
// and Clip cuts the result open. Only what loads the file and the WebGL viewport are replaced.
const loaded = vi.hoisted(() => ({ scene: null as any }));
vi.mock('../../../dist/renderers/kit/shell/ShellViewport.js', () => ({
  default: forwardRef(function StandInViewport(props: any, ref) {
    useImperativeHandle(ref, () => ({ requestRender() {} }));
    // A view update is acknowledged as the viewport does once it holds the frame that shows it.
    const update = props.viewUpdate;
    useEffect(() => { if (update?.revision) update.binding.complete(update.revision); }, [update?.revision, update?.binding]);
    return <div data-stand-in-viewport="">{typeof props.children === 'function' ? props.children({ hostRef: { current: null }, runtimeRef: { current: null }, mountRef: { current: null }, viewerReadyTick: 1, commitScene: () => true }) : props.children}</div>;
  })
}));
vi.mock('../../../dist/renderers/glb/useGlbScene.js', () => ({
  useGlbScene: () => ({ scene: loaded.scene, revision: 'one', busy: false, error: null, progress: null })
}));
import GlbRenderer, { loadFeaView } from '../../../dist/renderers/glb/GlbRenderer.js';
import { ViewerElementContext, ViewerHostContext } from '../../../dist/host/context.js';
import { testHost } from '../../../dist/host/testing/host.js';

// Frames run by hand: each `frame(ms)` runs the callbacks waiting for the next animation frame at that time.
let waiting: Array<(now: number) => void> = [];
const frame = (now: number) => act(() => { const due = waiting; waiting = []; due.forEach(callback => callback(now)); });
// The FEA viewer is its own chunk (`GlbRenderer.lazy.test.tsx`): loaded once here, a result draws as soon as it mounts.
beforeAll(() => loadFeaView());
beforeEach(() => {
  waiting = [];
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
  vi.stubGlobal('requestAnimationFrame', (callback: (now: number) => void) => { waiting.push(callback); return waiting.length; });
  vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(performance, 'now').mockReturnValue(0);
});
afterEach(() => { vi.restoreAllMocks(); cleanup(); vi.unstubAllGlobals(); document.querySelectorAll('[data-test-navbar]').forEach(slot => slot.remove()); });

// Heat over time, as `cadgen fea solve` writes it: a temperature per frame, warming from 25 °C, the
// model never deformed (its displacement is zero), opening on the hottest frame.
const WARMUP = {
  generator: 'cadgen fea', name: 'heatsink temperature', deformation_scale: 1, document: 'part.step', occurrence: 'o1', faces: ['#o1.f1', '#o1.f2'],
  analysis: { type: 'thermal_transient', tier: 1, word: 'Heat over time', reference_C: 25 },
  fields: [{ attribute: '_TEMPERATURE', name: 'temperature', units: '°C', min: 25, max: 75, attribute_scale: 1, signed: true, per_frame: true }],
  series: { kind: 'time', unit: 's', default: 2, frames: [
    { value: 0, label: '0 s', attributes: { temperature: '_TEMPERATURE' } },
    { value: 60, label: '60 s', attributes: { temperature: '_TEMPERATURE_F1' } },
    { value: 120, label: '2 min', attributes: { temperature: '_TEMPERATURE_F2' } }] },
};

function mount(extras: Record<string, unknown> | null = WARMUP) {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), 3));
  geometry.setIndex([0, 1, 2, 1, 3, 2]);
  geometry.setAttribute('color', new BufferAttribute(new Uint8Array(16).fill(7), 4, true));
  geometry.setAttribute('_displacement', new BufferAttribute(new Float32Array(12), 3));
  geometry.setAttribute('_face', new BufferAttribute(new Float32Array([0, 0, 0, 1]), 1));
  geometry.setAttribute('_temperature', new BufferAttribute(new Float32Array([25, 25, 25, 25]), 1));
  geometry.setAttribute('_temperature_f1', new BufferAttribute(new Float32Array([25, 40, 50, 30]), 1));
  geometry.setAttribute('_temperature_f2', new BufferAttribute(new Float32Array([25, 60, 75, 40]), 1));
  const mesh = new Mesh(geometry);
  if (extras) Object.assign(mesh.userData, extras);
  const root = new Group();
  root.add(mesh);
  const bounds = { min: [0, 0, 0], max: [1, 1, 0] };
  loaded.scene = { document: { scene: root }, object3D: root, bounds, restBounds: bounds, revision: 'one' };
  const slot = document.createElement('div');
  slot.setAttribute('data-test-navbar', '');
  document.body.append(slot);
  let snapshot: any = { toolStack: { panels: {}, collapsed: {} } };
  const preferences = { getSnapshot: () => snapshot, subscribe: () => () => {}, update(patch: any) { snapshot = { ...snapshot, ...patch }; } };
  const catalog = { entries: [], error: null };
  const client = { resources: {}, subscribe: () => () => {}, getSnapshot: () => catalog };
  const props = { source: { id: 'one' }, file: { path: '/models/part.glb', name: 'part.glb', kind: 'file' }, document: null, navbarSlot: slot,
    onReady() {}, onOpenFile() {}, appearance: { colorScheme: 'light' }, state: undefined, onStateChange() {}, onNavigationActionsChange() {}, reload() {},
    data: { client, entry: { path: '/models/part.glb', hash: 'h' }, services: { preferences } } };
  function ViewerElement({ children }: { children: React.ReactNode }) {
    const element = useRef<HTMLDivElement | null>(null);
    return <ViewerElementContext.Provider value={element}><div ref={element}>{children}</div></ViewerElementContext.Provider>;
  }
  render(<ViewerHostContext.Provider value={testHost()}><ViewerElement><GlbRenderer {...(props as any)} /></ViewerElement></ViewerHostContext.Provider>);
  return mesh;
}

it('Play in preview steps a heat-over-time result\'s colours through its frames, and leaves the unmoving model\'s positions alone', () => {
  const mesh = mount();
  // Vertex 2's colour: red at the hottest frame's 75 °C, which the result opens on; blue at the start's 25 °C.
  const vertex2 = () => Array.from(mesh.geometry.getAttribute('color').array as Uint8Array).slice(8, 11);
  const position = mesh.geometry.getAttribute('position');
  const hottest = vertex2();
  const placed = position.version;
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Preview' })); });
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Play animation' })); });
  const seen = [vertex2()];
  for (const ms of [250, 750, 1500, 2250]) { frame(ms); seen.push(vertex2()); }
  // Play starts at 0 s, all 25 °C, and every tick of its clock shows a new blend of two frames.
  expect(seen[0]).toEqual([13, 26, 230]);
  expect(seen[0]).not.toEqual(hottest);
  expect(new Set(seen.map(String)).size).toBe(seen.length);
  // A temperature moves nothing: its frames share the file's displacement, so no tick rewrites the
  // positions (and their normals and markers).
  expect(position.version).toBe(placed);
});

it('a result has a GLB\'s tools, Clip among them, and a cut never recolours it or its colour bar', () => {
  const mesh = mount();
  const colours = Array.from(mesh.geometry.getAttribute('color').array as Uint8Array);
  // The tools any GLB has, Select first: Clip is the viewer's (`kit/tools/model-effects`), the cut the viewport's.
  const strip = Array.from(document.querySelectorAll('[data-cad-toolbar] button')).map(button => button.getAttribute('aria-label'));
  expect(strip[0]).toBe('Select');
  expect(strip).toContain('Clip');
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Clip' })); });
  act(() => { fireEvent.keyDown(screen.getByRole('slider', { name: 'Clip amount' }), { key: 'End' }); });
  // A cut discards; it never recolours. The colour bar stays the reading it was, and Study stays the sidebar's.
  expect(Array.from(mesh.geometry.getAttribute('color').array as Uint8Array)).toEqual(colours);
  expect(document.querySelector('[aria-label="temperature colour bar"]')).toBeTruthy();
  expect(screen.getByRole('region', { name: 'Study' })).toBeTruthy();
});

const DROPPED = {
  generator: 'cadgen fea', name: 'plate drop (estimate)', deformation_scale: 1, document: 'part.step', occurrence: 'o1', faces: ['#o1.f1', '#o1.f2'],
  analysis: { type: 'drop', tier: 2, word: 'Drop (estimate)', estimate: true, limits: [], noun: 'this drop', warnings: [],
    fall: { height_mm: 1000, direction: [0, 0, -1], speed_m_s: 4.4287, floor: { point_mm: [500, 0, 0], normal: [0, 0, 1] }, impact_ms: 0.9 } },
  fields: [{ attribute: '_TEMPERATURE', name: 'von Mises stress', units: 'MPa', min: 0, max: 75, attribute_scale: 1, field: 'von_mises' }],
  study: { drop: { height_mm: 1000, onto: ['#o1.f1'], stop_mm: 2, direction: [0, 0, -1] }, material: { name: 'ABS', yield_MPa: 40 } },
};

it('a drop moves as kinematics does: a Time row and named states pose it, and the sidebar\'s Animation plays the fall', () => {
  const mesh = mount(DROPPED);
  const height = () => { mesh.updateMatrixWorld(true); return new Vector3().setFromMatrixPosition(mesh.matrixWorld).y; };
  // It opens on the peak of the stop, on the floor, its Time row saying the real time from landing.
  const time = screen.getByRole('slider', { name: 'Time' });
  const said = () => (screen.getByLabelText('Time slider value') as HTMLInputElement).value;
  expect(height()).toBeCloseTo(0, 6);
  expect(said()).toBe('450 µs');
  // Dragged to its start, it is up at its height, released: as Released, the named state, puts it.
  act(() => { fireEvent.keyDown(time, { key: 'Home' }); });
  expect(height()).toBeCloseTo(1, 6);
  expect(said()).toBe('\u22120.45 s');
  act(() => { fireEvent.keyDown(time, { key: 'End' }); });
  expect(height()).toBeCloseTo(0, 6);
  expect(said()).toBe('At rest');
  // The file sidebar's Animation plays the same timeline as Drop: from its height, falling, the readout in plain words.
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Play animation' })); });
  frame(0);
  frame(100);
  expect(height()).toBeCloseTo(1, 6);
  expect(document.querySelector('[data-fea-fall-time]')!.textContent).toBe('1 m above the floor');
  frame(700);
  expect(height()).toBeLessThan(1);
  expect(height()).toBeGreaterThan(0);
  const floor = mesh.parent!.getObjectByName('fea-drop-floor')!;
  expect(floor.visible).toBe(true);
  frame(1200);
  expect(document.querySelector('[data-fea-fall-scale]')!.textContent).toBe('slowed 2,000×');
  // Reset puts it back where the Time row has it, the readout gone.
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Reset animation' })); });
  expect(height()).toBeCloseTo(0, 6);
  expect((document.querySelector('[data-fea-fall-clock]') as HTMLElement).style.display).toBe('none');
});

// Heat stress as `cadgen fea solve` writes it: its motion is the heat coming on, on a Heat row.
const HEATED = {
  generator: 'cadgen fea', name: 'strip heat stress', deformation_scale: 1, document: 'part.step', occurrence: 'o1', faces: ['#o1.f1', '#o1.f2'],
  analysis: { type: 'thermal_stress', tier: 1, word: 'Heat stress', reference_C: 25 },
  fields: [{ attribute: '_TEMPERATURE', name: 'temperature', units: '°C', min: 25, max: 75, attribute_scale: 1, field: 'temperature', signed: true }],
};

it('a motion\'s row plays in place: its play button runs the timeline in the tools view, pressed again or dragged it stops', () => {
  mount(HEATED);
  const said = () => (screen.getByLabelText('Heat slider value') as HTMLInputElement).value;
  expect(said()).toBe('100 % of the heat');
  // At its end, play starts it over from ambient and the row follows the clock.
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Play the motion' })); });
  frame(0);
  frame(500);
  expect(said()).toBe('25 % of the heat');
  // Pressed again it pauses where it is.
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Pause' })); });
  frame(1000);
  expect(said()).toBe('25 % of the heat');
  // Playing again from there; a drag of the row pauses it and takes the row's value.
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Play the motion' })); });
  frame(1000);
  frame(1500);
  expect(said()).toBe('50 % of the heat');
  act(() => { fireEvent.keyDown(screen.getByRole('slider', { name: 'Heat' }), { key: 'Home' }); });
  expect(screen.getByRole('button', { name: 'Play the motion' })).toBeTruthy();
  frame(2000);
  expect(said()).toBe('0 % of the heat');
});
