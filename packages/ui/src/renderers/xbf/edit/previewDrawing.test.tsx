import { cleanup, render, waitFor } from '@testing-library/react';
import * as THREE from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PreviewLayer from '../../../../dist/renderers/xbf/edit/PreviewLayer.js';
import SketchesLayer from '../../../../dist/renderers/xbf/edit/SketchesLayer.js';
import { revolvedFrame, turnArrowStart } from '../../../../dist/renderers/xbf/edit/sketchPicking.js';

// What the layers draw, kept by a 2D context that draws nothing: the tags' words and how many fills.
let texts: string[] = [];
let fills = 0;

beforeEach(() => {
  texts = [];
  fills = 0;
  const ignore = () => {};
  const context = {
    canvas: { clientWidth: 800 }, save: ignore, restore: ignore, beginPath: ignore, moveTo: ignore, lineTo: ignore, closePath: ignore, stroke: ignore,
    arc: ignore, rect: ignore, roundRect: ignore, setTransform: ignore, clearRect: ignore, setLineDash: ignore,
    fill: () => { fills += 1; }, fillText: (text: string) => { texts.push(text); }, measureText: (text: string) => ({ width: text.length * 6 }),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as never);
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// A view of the part from above and to one side, the model unmoved.
function viewport() {
  const host = document.createElement('div');
  Object.defineProperty(host, 'clientWidth', { value: 800 });
  Object.defineProperty(host, 'clientHeight', { value: 600 });
  document.body.append(host);
  const camera = new THREE.PerspectiveCamera(45, 800 / 600, 1, 1000);
  camera.up.set(0, 0, 1);
  camera.position.set(60, -80, 60);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  camera.updateProjectionMatrix();
  return { runtimeRef: { current: { THREE, camera, modelGroup: new THREE.Group() } }, hostRef: { current: host }, viewerReadyTick: 1 };
}

it('an extrude is shaded as a solid with its arrow and depth, and a revolve with its turn and angle', async () => {
  const view = viewport();
  const sketch = { file: 'a.py', line: 4, name: 'Sketch1', state: { frame: { origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }, unit: 1,
    loops: [[[-5, -5], [5, -5], [5, 5], [-5, 5]]], curves: [] } };
  const extrude = { kind: 'boss', end: 'blind', file: 'a.py', line: 4, taper: 0, depth: 10, reverse: false, label: '10 mm' };
  const { rerender } = render(<SketchesLayer viewport={view} sketches={[sketch]} selected={sketch} preview={extrude} through={50} />);
  await waitFor(() => expect(texts).toContain('10 mm'));
  expect(fills).toBeGreaterThan(0);
  // Where the body ends it, the arrow alone; a revolve a quarter turn about a line beside the profile.
  rerender(<SketchesLayer viewport={view} sketches={[sketch]} selected={sketch} through={50}
    preview={{ ...extrude, depth: 0, end: 'next', arrowOnly: true, label: 'Up To Next' }} />);
  await waitFor(() => expect(texts).toContain('Up To Next'));
  rerender(<SketchesLayer viewport={view} sketches={[sketch]} selected={null} through={50}
    preview={{ kind: 'cut', revolve: { a: [-8, -10], b: [-8, 10], angle: 90 }, file: 'a.py', line: 4, label: '90°' }} />);
  await waitFor(() => expect(texts).toContain('90°'));
});

it("a linear pattern's arrow runs along its copies and a hole's goes into its face, each tagged", async () => {
  const view = viewport();
  // Two copies of a 2 mm cube, 10 and 20 along X from one at the origin.
  const cube = (x: number) => [x - 1, -1, -1, x + 1, 1, 1];
  const added = { positions: [...cube(10), ...cube(20)], triangles: [0, 1, 0], edges: [] };
  const pattern = { mark: 'pattern', along: [1, 0, 0], spacing: 10, count: 3, label: '10 mm' };
  const { rerender } = render(<PreviewLayer viewport={view} preview={{ added, removed: null }} mark={pattern} extent={40} />);
  await waitFor(() => expect(texts).toContain('10 mm'));
  rerender(<PreviewLayer viewport={view} preview={null} mark={{ mark: 'hole', at: [0, 0, 2], into: [0, 0, -1], label: 'Through All' }} extent={40} />);
  await waitFor(() => expect(texts).toContain('Through All'));
});

it("an extrude's arrow dragged along its line sets the depth it reaches, and clicked turns the extrude the other way", async () => {
  const view = viewport();
  const { camera } = view.runtimeRef.current;
  const host = view.hostRef.current;
  const pixel = (z: number) => {
    const point = new THREE.Vector3(0, 0, z).project(camera);
    return { clientX: ((point.x + 1) * 800) / 2, clientY: ((1 - point.y) * 600) / 2 };
  };
  const sketch = { file: 'a.py', line: 4, name: 'Sketch1', state: { frame: { origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }, unit: 1,
    loops: [[[-5, -5], [5, -5], [5, 5], [-5, 5]]], curves: [] } };
  const onDepth = vi.fn();
  const onReverse = vi.fn();
  const extrude = { kind: 'boss', end: 'blind', file: 'a.py', line: 4, taper: 0, depth: 10, reverse: false, units: 'mm', label: '10 mm', text: '10',
    onDepth, onReverse };
  const { container } = render(<SketchesLayer viewport={view} sketches={[sketch]} selected={sketch} preview={extrude} through={50} />);
  // Its depth is in the box beside its arrow.
  const box = container.querySelector<HTMLInputElement>('[data-cad-value-box="depth"] input')!;
  await waitFor(() => expect(box.value).toBe('10'));
  // Taken where its arrow starts, at the extrude's end 10 up, and dragged to 20 up.
  host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, ...pixel(10) }));
  window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, ...pixel(20) }));
  // While dragged, the extrude is drawn at the depth reached, its box with it.
  await waitFor(() => expect(box.value).toMatch(/^(19\.\d+|20(\.\d+)?)$/));
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, ...pixel(20) }));
  expect(onDepth).toHaveBeenCalledTimes(1);
  expect(Math.abs(Number(onDepth.mock.calls[0][0]) - 20)).toBeLessThan(0.5);
  expect(onReverse).not.toHaveBeenCalled();
  // Drawn at its panel's depth again once let go (this panel kept it); then pressed and let go
  // where it is: a click, which reverses it.
  await waitFor(() => expect(box.value).toBe('10'));
  host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, ...pixel(10) }));
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, ...pixel(10) }));
  expect(onReverse).toHaveBeenCalledTimes(1);
});

it("a revolve's arrow dragged round its axis sets the angle it reaches, and clicked turns the revolve the other way", async () => {
  const view = viewport();
  const { camera } = view.runtimeRef.current;
  const host = view.hostRef.current;
  const frame = { origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
  const loops = [[[-5, -5], [5, -5], [5, 5], [-5, 5]]];
  const sketch = { file: 'a.py', line: 4, name: 'Sketch1', state: { frame, unit: 1, loops, curves: [] } };
  const [a, b] = [[-8, -10], [-8, 10]];
  // Where the arrow's head is when the revolve has turned so far.
  const start = turnArrowStart(loops, a, b);
  const pixel = (degrees: number) => {
    const turned = revolvedFrame(frame, 1, a, b, degrees);
    const point = new THREE.Vector3(...[0, 1, 2].map(axis => turned.origin[axis] + turned.x[axis] * start[0] + turned.y[axis] * start[1])).project(camera);
    return { clientX: ((point.x + 1) * 800) / 2, clientY: ((1 - point.y) * 600) / 2 };
  };
  const onAngle = vi.fn();
  const onReverse = vi.fn();
  const { container } = render(<SketchesLayer viewport={view} sketches={[sketch]} selected={null} through={50}
    preview={{ kind: 'boss', revolve: { a, b, angle: 90 }, file: 'a.py', line: 4, label: '90°', text: '90', onAngle, onReverse }} />);
  const box = container.querySelector<HTMLInputElement>('[data-cad-value-box="angle"] input')!;
  await waitFor(() => expect(box.value).toBe('90'));
  // Taken at its head, a quarter turn round, and dragged to half a turn: drawn and tagged there as it goes.
  host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, ...pixel(90) }));
  window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, ...pixel(180) }));
  await waitFor(() => expect(box.value).toBe('180'));
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, ...pixel(180) }));
  expect(onAngle).toHaveBeenCalledWith('180');
  // Drawn at its panel's angle again once let go; then pressed and let go where it is: a click, which reverses it.
  await waitFor(() => expect(box.value).toBe('90'));
  host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, ...pixel(90) }));
  window.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, ...pixel(90) }));
  expect(onReverse).toHaveBeenCalledTimes(1);
});

it("a depth the panel takes is a box beside its arrow, typed over as Fusion's is", async () => {
  const view = viewport();
  const sketch = { file: 'a.py', line: 4, name: 'Sketch1', state: { frame: { origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }, unit: 1,
    loops: [[[-5, -5], [5, -5], [5, 5], [-5, 5]]], curves: [] } };
  const onDepth = vi.fn();
  const extrude = { kind: 'boss', end: 'blind', file: 'a.py', line: 4, taper: 0, depth: 10, reverse: false, label: '10 mm', units: 'mm',
    text: '10', onDepth };
  const { container } = render(<SketchesLayer viewport={view} sketches={[sketch]} selected={sketch} preview={extrude} through={50} />);
  const box = container.querySelector<HTMLElement>('[data-cad-value-box="depth"]')!;
  await waitFor(() => expect(box.style.visibility).toBe('visible'));
  // Not tagged on the canvas as well.
  expect(texts).not.toContain('10 mm');
  const input = box.querySelector('input')!;
  expect(input.value).toBe('10');
  expect(box.textContent).toContain('mm');
  input.focus();
  input.value = '14';
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await waitFor(() => expect(onDepth).toHaveBeenCalledWith('14'));
  // Escape puts it back, setting nothing.
  input.focus();
  input.value = '99';
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onDepth).toHaveBeenCalledTimes(1);
});
