import { afterEach, expect, test } from 'vitest';
import { attachViewerControls, viewerControlsHost, zoomsOnPress, type OrbitControlsLike } from './viewerControlsHost.js';

const MOUSE = { ROTATE: 0, DOLLY: 1, PAN: 2 };
const NO_KEYS = { ctrlKey: false, metaKey: false, shiftKey: false };

afterEach(() => viewerControlsHost.set(null));

function orbitWithView() {
  const parent = new EventTarget();
  const view = new EventTarget();
  const proto = {
    _customWheelEvent(event: { deltaY: number }) {
      return { deltaY: event.deltaY };
    },
  };
  const orbit: OrbitControlsLike = Object.assign(Object.create(proto), {
    mouseButtons: { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN },
    zoomToCursor: true,
    _controlActive: false,
    domElement: { parentElement: parent, ownerDocument: { defaultView: view } } as unknown as HTMLElement,
  });
  const pointer = (type: string, init: Record<string, unknown>) =>
    Object.assign(new Event(type), { button: 0, pointerType: 'mouse', ...NO_KEYS, ...init });
  return { orbit, parent, view, pointer };
}

test('takes the setting only as a known preset, with the switches read safely', () => {
  viewerControlsHost.set({ mouse: 'solidworks', reverseWheel: true, zoomToPointer: false, more: 1 });
  expect(viewerControlsHost.get()).toEqual({ mouse: 'solidworks', reverseWheel: true, zoomToPointer: false });
  viewerControlsHost.set({ mouse: 'nx' });
  expect(viewerControlsHost.get()).toEqual({ mouse: 'nx', reverseWheel: false, zoomToPointer: true });
  for (const sent of [{ mouse: 'catia' }, { mouse: 1 }, 'solidworks', null, undefined]) {
    viewerControlsHost.set({ mouse: 'nx' });
    viewerControlsHost.set(sent);
    expect(viewerControlsHost.get()).toBeNull();
  }
});

test('each CAD puts its buttons where it has them, and a CAD left button moves nothing', () => {
  const { orbit } = orbitWithView();
  const dispose = attachViewerControls(orbit, MOUSE);
  const expected = {
    studio: { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN },
    solidworks: { LEFT: null, MIDDLE: MOUSE.ROTATE, RIGHT: null },
    nx: { LEFT: null, MIDDLE: MOUSE.ROTATE, RIGHT: null },
    fusion: { LEFT: null, MIDDLE: MOUSE.PAN, RIGHT: null },
    onshape: { LEFT: null, MIDDLE: MOUSE.PAN, RIGHT: MOUSE.ROTATE },
  };
  for (const [mouse, buttons] of Object.entries(expected)) {
    viewerControlsHost.set({ mouse });
    expect(orbit.mouseButtons, mouse).toEqual(buttons);
  }
  dispose();
});

test('only SolidWorks Shift + middle and Fusion Ctrl + Shift + middle zoom by a key', () => {
  const shift = { ...NO_KEYS, shiftKey: true };
  const ctrlShift = { ...shift, ctrlKey: true };
  expect(zoomsOnPress('solidworks', 1, shift)).toBe(true);
  expect(zoomsOnPress('solidworks', 1, ctrlShift)).toBe(false);
  expect(zoomsOnPress('fusion', 1, ctrlShift)).toBe(true);
  expect(zoomsOnPress('fusion', 1, shift)).toBe(false);
  expect(zoomsOnPress('nx', 1, shift)).toBe(false);
  expect(zoomsOnPress('solidworks', 0, shift)).toBe(false);
});

test('a key zoom lasts one press, then the button is what it was', () => {
  const { orbit, parent, view, pointer } = orbitWithView();
  const dispose = attachViewerControls(orbit, MOUSE);
  viewerControlsHost.set({ mouse: 'solidworks' });
  parent.dispatchEvent(pointer('pointerdown', { button: 1, shiftKey: true }));
  expect(orbit.mouseButtons.MIDDLE).toBe(MOUSE.DOLLY);
  view.dispatchEvent(pointer('pointerup', { button: 1 }));
  expect(orbit.mouseButtons.MIDDLE).toBe(MOUSE.ROTATE);
  parent.dispatchEvent(pointer('pointerdown', { button: 1, ctrlKey: true }));
  expect(orbit.mouseButtons.MIDDLE).toBe(MOUSE.ROTATE);
  dispose();
});

test('reverses the wheel but not a pinch, and zooms toward the pointer as set', () => {
  const { orbit } = orbitWithView();
  const dispose = attachViewerControls(orbit, MOUSE);
  const wheel = (deltaY: number, ctrlKey = false) => orbit._customWheelEvent!({ deltaY, ctrlKey } as WheelEvent).deltaY;
  viewerControlsHost.set({ mouse: 'studio', reverseWheel: true, zoomToPointer: false });
  expect(wheel(100)).toBe(-100);
  expect(wheel(4, true)).toBe(4);
  expect(orbit.zoomToCursor).toBe(false);
  viewerControlsHost.set({ mouse: 'studio' });
  expect(wheel(100)).toBe(100);
  expect(orbit.zoomToCursor).toBe(true);
  dispose();
});

test('with no setting from the host, and once the view goes, the controls are as it found them', () => {
  const { orbit } = orbitWithView();
  const dispose = attachViewerControls(orbit, MOUSE);
  expect(orbit.mouseButtons).toEqual({ LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN });
  viewerControlsHost.set({ mouse: 'onshape', reverseWheel: true, zoomToPointer: false });
  dispose();
  expect(orbit.mouseButtons).toEqual({ LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN });
  expect(orbit.zoomToCursor).toBe(true);
  expect(Object.prototype.hasOwnProperty.call(orbit, '_customWheelEvent')).toBe(false);
  viewerControlsHost.set({ mouse: 'nx' });
  expect(orbit.mouseButtons.LEFT).toBe(MOUSE.ROTATE);
});
