/**
 * How the host has the mouse move the view (Studio's Settings, Engineering, sent in its host context as
 * `studio/viewerControls`): the buttons of the CAD a person comes from, which way the wheel zooms, and
 * whether it zooms toward the pointer. The app that hosts the viewer takes it from its host context;
 * every 3D view applies it to its camera controls (`attachViewerControls`). No host, nothing changes.
 * One per page, as a page is one view.
 */
export const MOUSE_PRESETS = ['studio', 'solidworks', 'nx', 'fusion', 'onshape'] as const;
export type MousePreset = (typeof MOUSE_PRESETS)[number];

export interface ViewerControls {
  readonly mouse: MousePreset;
  readonly reverseWheel: boolean;
  readonly zoomToPointer: boolean;
}

type Action = 'rotate' | 'pan' | 'zoom' | null;

/**
 * What the left, middle and right buttons do with no key held. OrbitControls swaps turning and panning while
 * Ctrl, Cmd or Shift is held, which gives SolidWorks' Ctrl + middle pan, NX's Shift + middle pan, Fusion's
 * Shift + middle orbit and Onshape's Ctrl + right pan as they are. A CAD's left button selects, so it moves
 * nothing here.
 */
const BUTTONS: Readonly<Record<MousePreset, readonly [Action, Action, Action]>> = {
  studio: ['rotate', 'zoom', 'pan'],
  solidworks: [null, 'rotate', null],
  nx: [null, 'rotate', null],
  fusion: [null, 'pan', null],
  onshape: [null, 'pan', 'rotate'],
};

interface Keys {
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly shiftKey: boolean;
}

/** Presses that zoom where the swap would turn or pan: SolidWorks' Shift + middle, Fusion's Ctrl + Shift + middle. */
export function zoomsOnPress(mouse: MousePreset, button: number, keys: Keys): boolean {
  if (button !== 1 || !keys.shiftKey) return false;
  const control = keys.ctrlKey || keys.metaKey;
  return (mouse === 'solidworks' && !control) || (mouse === 'fusion' && control);
}

/** The setting as the host's context says it: a known preset and two switches, or none. */
function read(value: unknown): ViewerControls | null {
  if (typeof value !== 'object' || value === null) return null;
  const { mouse, reverseWheel, zoomToPointer } = value as Record<string, unknown>;
  if (!MOUSE_PRESETS.includes(mouse as MousePreset)) return null;
  return Object.freeze({ mouse: mouse as MousePreset, reverseWheel: reverseWheel === true, zoomToPointer: zoomToPointer !== false });
}

const same = (a: ViewerControls | null, b: ViewerControls | null) =>
  a === b || (a !== null && b !== null && a.mouse === b.mouse && a.reverseWheel === b.reverseWheel && a.zoomToPointer === b.zoomToPointer);

let controls: ViewerControls | null = null;
const listeners = new Set<() => void>();

export const viewerControlsHost = {
  /** The setting the host sends now, or null. */
  get: (): ViewerControls | null => controls,
  /** The host's context says the setting: anything but a well-formed one is none. */
  set(next: unknown): void {
    const value = read(next);
    if (same(controls, value)) return;
    controls = value;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};

/** three's `MOUSE` constants, passed in so this file needs no three. */
export interface MouseActions {
  readonly ROTATE: number;
  readonly DOLLY: number;
  readonly PAN: number;
}

/** The parts of three's OrbitControls this uses. */
export interface OrbitControlsLike {
  mouseButtons: { LEFT?: number | null; MIDDLE?: number | null; RIGHT?: number | null };
  zoomToCursor?: boolean;
  domElement?: HTMLElement | null;
  _controlActive?: boolean;
  _customWheelEvent?: (event: WheelEvent) => { deltaY: number };
}

const SLOTS = ['LEFT', 'MIDDLE', 'RIGHT'] as const;

/**
 * Applies the host's setting to one view's camera controls, now and at each change, and puts back what it
 * found when the view goes. A press that zooms by a key (`zoomsOnPress`) zooms for that press only. It listens
 * on the canvas's parent in the capture phase, so the view's own capture listener on the canvas (its pan speed)
 * sees the press as it will be taken.
 */
export function attachViewerControls(orbit: OrbitControlsLike, mouse: MouseActions, host = viewerControlsHost): () => void {
  const found = { ...orbit.mouseButtons };
  const foundZoomToCursor = orbit.zoomToCursor;
  const action = (name: Action) =>
    name === 'rotate' ? mouse.ROTATE : name === 'pan' ? mouse.PAN : name === 'zoom' ? mouse.DOLLY : null;

  const ownWheel = Object.prototype.hasOwnProperty.call(orbit, '_customWheelEvent');
  const wheel = orbit._customWheelEvent;
  // A pinch reaches OrbitControls as a wheel with Ctrl held that it did not see pressed; it keeps its way.
  const reversed = function (this: OrbitControlsLike, event: WheelEvent) {
    const out = wheel!.call(this, event);
    if (!(event.ctrlKey && !this._controlActive)) out.deltaY = -out.deltaY;
    return out;
  };

  const apply = () => {
    const now = host.get();
    if (now === null) {
      Object.assign(orbit.mouseButtons, found);
      if ('zoomToCursor' in orbit) orbit.zoomToCursor = foundZoomToCursor;
    } else {
      BUTTONS[now.mouse].forEach((name, at) => {
        orbit.mouseButtons[SLOTS[at]] = action(name);
      });
      if ('zoomToCursor' in orbit) orbit.zoomToCursor = now.zoomToPointer;
    }
    if (typeof wheel !== 'function') return;
    if (now?.reverseWheel) orbit._customWheelEvent = reversed;
    else if (ownWheel) orbit._customWheelEvent = wheel;
    else delete orbit._customWheelEvent;
  };

  let held: { readonly slot: (typeof SLOTS)[number]; readonly value: number | null | undefined } | null = null;
  const release = () => {
    if (held === null) return;
    orbit.mouseButtons[held.slot] = held.value;
    held = null;
  };
  const press = (event: PointerEvent) => {
    release();
    const now = host.get();
    if (now === null || event.pointerType === 'touch' || !zoomsOnPress(now.mouse, event.button, event)) return;
    const slot = SLOTS[event.button];
    held = { slot, value: orbit.mouseButtons[slot] };
    orbit.mouseButtons[slot] = mouse.DOLLY;
  };

  const element = orbit.domElement ?? null;
  const scope = element?.parentElement ?? element;
  const view = element?.ownerDocument?.defaultView ?? null;
  scope?.addEventListener('pointerdown', press, { capture: true });
  view?.addEventListener('pointerup', release, { capture: true });
  view?.addEventListener('pointercancel', release, { capture: true });
  const unsubscribe = host.subscribe(apply);
  apply();

  return () => {
    unsubscribe();
    scope?.removeEventListener('pointerdown', press, { capture: true });
    view?.removeEventListener('pointerup', release, { capture: true });
    view?.removeEventListener('pointercancel', release, { capture: true });
    release();
    Object.assign(orbit.mouseButtons, found);
    if ('zoomToCursor' in orbit) orbit.zoomToCursor = foundZoomToCursor;
    if (ownWheel) orbit._customWheelEvent = wheel;
    else delete orbit._customWheelEvent;
  };
}
