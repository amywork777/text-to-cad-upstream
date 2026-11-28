import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { gridHost } from "./gridHost.js";
import { DISPLAY_DEFAULTS, DISPLAY_RESET_PATCH } from "./viewerDisplaySettings.js";
import { createViewSettingsStore } from "./viewSettingsStore.js";

// Studio (studio-base): the host's Show grid default (`studio/gridDefault`, `gridHost.js`).
afterEach(() => gridHost.set(undefined));

const shown = store => store.getSnapshot().scene.view.grid.enabled;

test("the host's default takes only true, and its listeners hear each change once", () => {
  let heard = 0;
  const unsubscribe = gridHost.subscribe(() => heard++);
  for (const sent of [1, "true", { enabled: true }, null]) {
    gridHost.set(sent);
    assert.equal(gridHost.get(), false, String(sent));
  }
  gridHost.set(true);
  gridHost.set(true);
  assert.deepEqual([gridHost.get(), heard], [true, 1]);
  unsubscribe();
});

test("with the host's default on, a file with no saved grid shows it, and the record stays sparse", () => {
  gridHost.set(true);
  const store = createViewSettingsStore();
  assert.equal(shown(store), true);
  assert.deepEqual(store.getSnapshot().display, { mode: "solid" });
  assert.equal(DISPLAY_DEFAULTS.grid, true);
});

test("a file's saved grid off wins over the host's default, and switching it off is saved", () => {
  gridHost.set(true);
  assert.equal(shown(createViewSettingsStore({ grid: false })), false);
  const store = createViewSettingsStore();
  store.setGrid(false);
  assert.deepEqual([shown(store), store.getSnapshot().display], [false, { mode: "solid", grid: false }]);
  store.setGrid(true);
  assert.deepEqual([shown(store), store.getSnapshot().display], [true, { mode: "solid" }]);
});

test("Reset puts the grid back to the host's default", () => {
  gridHost.set(true);
  const store = createViewSettingsStore({ mode: "xray", grid: false });
  store.patch(DISPLAY_RESET_PATCH);
  assert.deepEqual([shown(store), store.getSnapshot().display], [true, { mode: "solid", camera: { projection: "orthographic" } }]);
});

test("with no default from the host, the grid is off until a file says so, as before", () => {
  const store = createViewSettingsStore();
  assert.deepEqual([shown(store), DISPLAY_DEFAULTS.grid], [false, false]);
  store.setGrid(true);
  assert.deepEqual([shown(store), store.getSnapshot().display], [true, { mode: "solid", grid: true }]);
  store.patch(DISPLAY_RESET_PATCH);
  assert.deepEqual([shown(store), store.getSnapshot().display], [false, { mode: "solid", camera: { projection: "orthographic" } }]);
});
