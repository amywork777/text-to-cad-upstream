import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import * as THREE from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditSelectionBar from '../../../../dist/renderers/xbf/edit/EditSelectionBar.js';
import { VIEWER_DOUBLE_CLICK_ACTIVATION_DELAY_MS } from '../../../../dist/renderers/xbf/clickActivation.js';

// The viewport as the renderer's overlay is handed it, with the WebGL runtime replaced by what the bar reads of it: an
// orthographic camera straight over a 600 × 400 canvas, one pixel a unit, the model's origin at the canvas' middle
// (so a point (x, y, 0) is at (300 + x, 200 − y)), and the model group the part sits under.
const CANVAS = { width: 600, height: 400 };
function viewport() {
  const camera = new THREE.OrthographicCamera(-300, 300, 200, -200, 0.1, 1000);
  camera.position.set(0, 0, 100);
  camera.lookAt(0, 0, 0);
  const modelGroup = new THREE.Group();
  const domElement = { clientWidth: CANVAS.width, clientHeight: CANVAS.height };
  const scene = new THREE.Scene();
  const runtime = { THREE, camera, modelGroup, scene, renderer: { domElement, getRenderTarget: () => null } };
  const host = document.createElement('div');
  host.setAttribute('data-host', '');
  return { runtime, host, viewport: { runtimeRef: { current: runtime }, hostRef: { current: host }, viewerReadyTick: 0 } };
}
/** A plate 100 × 40 in the middle of the canvas: on screen, x from 250 to 350 and y from 180 to 220. */
const PLATE = [-50, 50].flatMap(x => [-20, 20].map(y => [x, y, 0]));

const noop = () => {};
const ALL = [{ id: 'ask', enabled: true }, { id: 'add-context', enabled: true }, { id: 'annotate', enabled: true }, { id: 'edit', enabled: true }];

// jsdom lays nothing out: the bar is given the box it has in the app, and a frame the bar asks for is a timer. A render of
// the view is the scene's after-render hook called as the renderer calls it (`drawn`): the bar lays itself out then.
const sizeOf = Object.getOwnPropertyDescriptors(HTMLElement.prototype);
const boxOf = Element.prototype.getBoundingClientRect;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(0), 16) as unknown as number);
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 200 });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 28 });
});
afterEach(() => {
  cleanup();
  document.querySelectorAll('[data-cad-scene-backdrop]').forEach(each => each.remove());
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Object.defineProperties(HTMLElement.prototype, { offsetWidth: sizeOf.offsetWidth, offsetHeight: sizeOf.offsetHeight });
  Element.prototype.getBoundingClientRect = boxOf;
});

function bar(props: Record<string, unknown> = {}, rig = viewport()) {
  const handlers = { onAsk: vi.fn(), onAddContext: vi.fn(), onAnnotate: vi.fn(), onEdit: vi.fn() };
  const element = (extra: Record<string, unknown>) => <EditSelectionBar viewport={rig.viewport} actions={ALL} anchorKey="face:o1.f12" anchor={() => PLATE}
    editKind="Hole" editHint="Edit Feature" {...handlers} {...props} {...extra} />;
  const view = render(element({}));
  return { ...view, ...rig, ...handlers, show: (extra: Record<string, unknown>) => view.rerender(element(extra)) };
}
/** Time passing: past the double-click window, a few frames of the camera loop. */
const wait = (ms = VIEWER_DOUBLE_CLICK_ACTIVATION_DELAY_MS + 100) => act(() => { vi.advanceTimersByTime(ms); });
/** The view drawn once, as the viewport draws it after the camera moved. */
const drawn = (rig: ReturnType<typeof viewport>) => act(() => { rig.runtime.scene.onAfterRender(rig.runtime.renderer as never, rig.runtime.scene, rig.runtime.camera as never, null as never, null as never, null as never); });
const toolbar = () => screen.queryByRole('toolbar', { name: 'Selection' });
const placed = () => { const style = toolbar()!.style; return [style.left, style.top]; };
const names = () => within(toolbar()!).getAllByRole('button').map(button => button.getAttribute('aria-label') || button.textContent);

it('waits out the double-click window before it shows, so the second click of a double-click on the model is the model\'s', () => {
  bar();
  expect(toolbar()).toBeNull();
  wait(VIEWER_DOUBLE_CLICK_ACTIVATION_DELAY_MS - 20);
  expect(toolbar()).toBeNull();
  wait(100);
  expect(toolbar()).not.toBeNull();
});

it('draws the actions it has a handler for, each with its icon and its name, and presses them', () => {
  const view = bar({ onAddContext: undefined });
  wait();
  // Add to context waits for the handler that does it (the chat box to fill); the three that work are there.
  expect(names()).toEqual(['Ask', 'Annotate', 'Edit']);
  for (const name of ['Ask', 'Annotate', 'Edit']) {
    expect(within(toolbar()!).getByRole('button', { name }).querySelector('svg use')!.getAttribute('href')).toMatch(/^#nx-/);
  }
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
  fireEvent.click(screen.getByRole('button', { name: 'Annotate' }));
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  expect([view.onAsk, view.onAnnotate, view.onEdit].map(handler => handler.mock.calls.length)).toEqual([1, 1, 1]);
  // With it, the four of the design, in its order.
  view.show({ onAddContext: view.onAddContext });
  expect(names()).toEqual(['Ask', 'Add to context', 'Annotate', 'Edit']);
  fireEvent.click(screen.getByRole('button', { name: 'Add to context' }));
  expect(view.onAddContext).toHaveBeenCalledTimes(1);
});

it('draws only what it is offered: no Edit for a pick that has no feature to edit', () => {
  bar({ actions: ALL.slice(0, 3) });
  wait();
  expect(names()).toEqual(['Ask', 'Add to context', 'Annotate']);
});

it('draws Edit with the picked feature\'s own icon, naming what it opens, and holds it, saying why, while a change is on its way', () => {
  const view = bar();
  wait();
  const edit = () => screen.getByRole('button', { name: 'Edit' });
  expect(edit().querySelector('use')!.getAttribute('href')).toBe('#nx-hole');
  expect(edit().getAttribute('aria-description')).toBe('Edit Feature');
  expect(edit().hasAttribute('disabled')).toBe(false);
  view.show({ actions: ALL.map(action => (action.id === 'edit' ? { ...action, enabled: false, reason: 'Wait for the change in progress to finish.' } : action)) });
  expect(edit().hasAttribute('disabled')).toBe(true);
  expect(edit().getAttribute('aria-description')).toBe('Wait for the change in progress to finish.');
  fireEvent.click(edit());
  expect(view.onEdit).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Ask' }).hasAttribute('disabled')).toBe(false);
});

it('stands above the pick, centred on it, and follows the camera as it moves', () => {
  const view = bar();
  wait();
  // The plate is on screen from (250, 180) to (350, 220): the bar, 200 wide and 28 tall, 10 above it.
  expect(placed()).toEqual(['200px', '142px']);
  // The camera pans 20 units right, so the model is 20 pixels left on the screen.
  view.runtime.camera.position.x += 20;
  // Nothing follows until the view is drawn: no frame runs at rest.
  wait(50);
  expect(placed()).toEqual(['200px', '142px']);
  drawn(view);
  expect(placed()).toEqual(['180px', '142px']);
  // And zooms in, so the plate fills more of the screen: the same box.
  view.runtime.camera.zoom = 2;
  view.runtime.camera.updateProjectionMatrix();
  drawn(view);
  const zoomed = placed();
  expect(Number.parseFloat(zoomed[1])).toBeLessThan(142);
});

it('goes below the pick where there is no room above it, and is nowhere when the pick is out of the view or behind it', () => {
  const view = bar({ anchor: () => PLATE.map(([x, y, z]) => [x, y + 180, z]) });
  wait();
  // The plate now spans y from 0 to 40 on screen, and the bar is 8 px in at least from the top: below it.
  expect(placed()).toEqual(['200px', '50px']);
  view.show({ anchor: () => PLATE.map(([x, y, z]) => [x + 900, y, z]), anchorKey: 'face:far' });
  wait(50);
  expect(toolbar()).toBeNull();
  view.show({ anchor: () => PLATE.map(([x, y]) => [x, y, 500]), anchorKey: 'face:behind' });
  wait(50);
  expect(toolbar()).toBeNull();
  view.show({ anchor: () => PLATE, anchorKey: 'face:o1.f12' });
  wait(50);
  expect(toolbar()).not.toBeNull();
});

/**
 * The canvas in its viewport box with the workspace over it, as the frame lays it out: a toolbar 32 px tall across the top,
 * and the design tree at the left, 256 px wide from y = 40 to 300, 8 px in.
 */
function workspaceRig() {
  const rig = viewport();
  const backdrop = document.createElement('div');
  backdrop.setAttribute('data-cad-scene-backdrop', '');
  backdrop.innerHTML = '<div data-cad-dock="toolbar"></div><aside data-cad-dock="navigator"></aside>';
  backdrop.prepend(rig.host);
  document.body.append(backdrop);
  const rects = new Map<Element, DOMRect>([
    [rig.host, DOMRect.fromRect({ x: 0, y: 0, width: 600, height: 400 })],
    [backdrop.querySelector('[data-cad-dock="toolbar"]')!, DOMRect.fromRect({ x: 0, y: 0, width: 600, height: 32 })],
    [backdrop.querySelector('[data-cad-dock="navigator"]')!, DOMRect.fromRect({ x: 8, y: 40, width: 256, height: 260 })],
  ]);
  Element.prototype.getBoundingClientRect = function (this: Element) { return rects.get(this) ?? boxOf.call(this); };
  return rig;
}
/** A pick as the model's points: the box from (x0, y0) to (x1, y1) of the model, which the screen shows from (300 + x0, 200 − y1) to (300 + x1, 200 − y0). */
const quad = (x0: number, y0: number, x1: number, y1: number) => [[x0, y0, 0], [x1, y0, 0], [x0, y1, 0], [x1, y1, 0]];

it('keeps clear of the design tree: beside a pick it would be centred over, if centred it would run under the navigator', () => {
  const rig = workspaceRig();
  // The pick is on screen from (250, 140) to (310, 180): the navigator's edge, 264, runs through it.
  bar({ anchor: () => quad(-50, 20, 10, 60) }, rig);
  wait();
  const [left, top] = placed().map(Number.parseFloat);
  expect(left).toBeGreaterThanOrEqual(8 + 256);
  expect(top).toBeGreaterThanOrEqual(40);
});

it('keeps below the toolbar: a pick high in the view has the bar clear of the toolbar', () => {
  const rig = workspaceRig();
  // The pick is on screen from y = 30 to 60, the toolbar's foot (y = 32) over its top.
  bar({ anchor: () => quad(0, 140, 40, 170) }, rig);
  wait();
  expect(Number.parseFloat(placed()[1])).toBeGreaterThanOrEqual(32 + 8);
});

it('is nowhere for a pick hidden behind the toolbar', () => {
  const rig = workspaceRig();
  // The pick is on screen from y = 5 to 25, all under the toolbar.
  bar({ anchor: () => quad(0, 175, 40, 195) }, rig);
  wait();
  expect(toolbar()).toBeNull();
});

it('never takes a double-click: a press or a double-click on it stops at it, and does not reach the model under it', () => {
  const rig = viewport();
  const outer = { down: vi.fn(), double: vi.fn() };
  const view = render(<div onPointerDown={outer.down} onDoubleClick={outer.double}>
    <EditSelectionBar viewport={rig.viewport} actions={ALL} anchorKey="k" anchor={() => PLATE} editKind="Hole" onAsk={noop} onAnnotate={noop} onEdit={noop} />
  </div>);
  wait();
  const ask = screen.getByRole('button', { name: 'Ask' });
  fireEvent.pointerDown(ask);
  fireEvent.doubleClick(ask);
  fireEvent.pointerDown(toolbar()!);
  fireEvent.doubleClick(toolbar()!);
  expect([outer.down.mock.calls.length, outer.double.mock.calls.length]).toEqual([0, 0]);
  view.unmount();
});

it('is not there when nothing is offered, and is gone once the camera loop is: nothing keeps running', () => {
  const view = bar({ actions: [] });
  wait();
  expect(toolbar()).toBeNull();
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
