import { useCallback, useEffect, useRef } from "react";

// One hook on each scene's `onAfterRender`, shared by every layer that follows it, so layers coming and going never
// leave a chain of wrappers behind: what was there before is called first, then each layer.
const HOOKS = new WeakMap();

/**
 * Hears every render of `scene` to the screen (not one into a render target, a picture's or a pick's): `listener(camera)` is
 * called right after it, so what a layer draws over the viewport moves in the frame the model does. Returns the way to stop.
 * The hook wraps whatever the scene had (the Measure overlay's, say) and calls it first; a call that comes back into it
 * through a wrapper of its own is not run twice.
 *
 * @param {{ onAfterRender: Function }} scene
 * @param {(camera: object) => void} listener
 * @returns {() => void}
 */
export function onSceneRendered(scene, listener) {
  let entry = HOOKS.get(scene);
  if (!entry) {
    entry = { listeners: new Set(), previous: scene.onAfterRender, running: false, hook: null };
    const owned = entry;
    owned.hook = function sceneRendered(...args) {
      if (owned.running) return;
      owned.running = true;
      try {
        owned.previous?.apply(this, args);
        const [renderer, , camera] = args;
        if (!renderer?.getRenderTarget?.()) for (const each of [...owned.listeners]) each(camera);
      } finally {
        owned.running = false;
      }
    };
    scene.onAfterRender = owned.hook;
    HOOKS.set(scene, owned);
  }
  entry.listeners.add(listener);
  const owned = entry;
  return () => {
    owned.listeners.delete(listener);
    if (owned.listeners.size) return;
    if (scene.onAfterRender === owned.hook) scene.onAfterRender = owned.previous;
    if (HOOKS.get(scene) === owned) HOOKS.delete(scene);
  };
}

/**
 * A layer over the viewport painted when the view is drawn, and only then: after each render of the viewport's scene
 * through its camera (`onSceneRendered`), and once on the next frame when the layer asks (`request`, returned: its input
 * changed). Nothing runs while the view is at rest. `paint` is read when it runs, so it may change every render. With
 * `active` false nothing is heard.
 *
 * @param {{ runtimeRef: { current: object | null }, viewerReadyTick?: number }} viewport
 * @param {() => void} paint
 * @param {boolean} [active]
 * @returns {() => void} request
 */
export function useSceneRendered(viewport, paint, active = true) {
  const paintRef = useRef(paint);
  paintRef.current = paint;
  const frameRef = useRef(0);
  const request = useCallback(() => {
    if (frameRef.current || typeof requestAnimationFrame !== "function") return;
    frameRef.current = requestAnimationFrame(() => { frameRef.current = 0; paintRef.current(); });
  }, []);
  const { runtimeRef, viewerReadyTick } = viewport;
  useEffect(() => {
    if (!active) return undefined;
    const scene = runtimeRef?.current?.scene;
    const stop = scene ? onSceneRendered(scene, (camera) => { if (camera === runtimeRef.current?.camera) paintRef.current(); }) : null;
    request();
    return () => {
      stop?.();
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
    };
  }, [runtimeRef, viewerReadyTick, active, request]);
  return request;
}
