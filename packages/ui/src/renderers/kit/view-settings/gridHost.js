/**
 * Studio (studio-base): whether a 3D view's Show grid is on where the file says nothing (`studio/gridDefault` in the
 * host context: `true` for on, anything else for the viewer's own off). A file's saved switch still wins, and Display's
 * Reset goes back to it (`viewerDisplaySettings.js`). No host, nothing changes. One per page, as a page is one view.
 * Plain JS, as the view settings it feeds run in the Node tests too.
 */
let grid = false;
const listeners = new Set();

export const gridHost = {
  /** Show grid's default now. @returns {boolean} */
  get: () => grid,
  /** The host's context says the default: only `true` turns it on. @param {unknown} next */
  set(next) {
    const value = next === true;
    if (value === grid) return;
    grid = value;
    for (const listener of listeners) listener();
  },
  /** @param {() => void} listener @returns {() => void} */
  subscribe(listener) {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }
};
