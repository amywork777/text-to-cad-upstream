/**
 * Studio (studio-base): whether the view's host is Studio, which names a scene's nodes as an engineer reads them
 * (`renderers/kit/inspector/studioSceneNames.js`). The app sets it from its host (`apps/mcp/src/host/studioHost.ts`'s
 * `useStudioFiles`); Jake's own viewer leaves it off and shows the file's names as they are.
 */
let on = false;
const listeners = new Set<() => void>();

export const studioNames = {
  get: (): boolean => on,
  set(next: boolean): void {
    if (next === on) return;
    on = next;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
