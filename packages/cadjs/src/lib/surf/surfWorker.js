// Surf component worker (design/surface-rendering.md R2).
//
// One request = one component URL. The worker fetches the .surf, parses,
// tessellates, and builds BOTH consumers' payloads — the render meshData
// and the selector bundle — in a single pass over one tessellation, then
// transfers every typed array to the main thread. Tessellation is the cost
// this migration moved from the build to the client; running it here keeps
// the page's main thread free to paint and respond while a large assembly
// loads across the whole worker pool.

import { parseSurf } from "./container.js";
import { tessellateComponent } from "./tessellate.js";
import { buildMeshDataFromSurf } from "./surfMeshData.js";
import { buildSelectorBundleFromSurf } from "./surfSelectorBundle.js";
import { meshDataTransferList } from "../render/meshTransfer.js";

const activeControllers = new Map();

async function loadArrayBuffer(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status} ${response.statusText}`);
  }
  return response.arrayBuffer();
}

function bundleTransferList(bundle) {
  return Object.values(bundle?.buffers || {})
    .map((view) => view?.buffer)
    .filter((buffer) => buffer instanceof ArrayBuffer && buffer.byteLength > 0);
}

self.addEventListener("message", async (event) => {
  const message = event.data || {};
  const id = message.id;
  if (!id) {
    return;
  }
  if (message.type === "cancel") {
    activeControllers.get(id)?.abort();
    activeControllers.delete(id);
    return;
  }
  if (message.type !== "loadSurf") {
    return;
  }
  const controller = new AbortController();
  activeControllers.set(id, controller);
  try {
    const buffer = await loadArrayBuffer(message.url, controller.signal);
    const { index, floats } = parseSurf(buffer);
    // Optional tolerance override (viewport LOD re-tessellates a component at
    // a finer chord level from the same exact surfaces).
    const component = tessellateComponent(index, floats, message.tessellation || {});
    const meshData = buildMeshDataFromSurf(index, floats, { component });
    const bundle = buildSelectorBundleFromSurf(index, floats, { component });
    if (controller.signal.aborted) {
      return;
    }
    self.postMessage(
      { id, ok: true, meshData, bundle },
      [...new Set([...meshDataTransferList(meshData), ...bundleTransferList(bundle)])],
    );
  } catch (error) {
    if (!controller.signal.aborted) {
      self.postMessage({
        id,
        ok: false,
        error: {
          name: error?.name || "Error",
          message: error instanceof Error ? error.message : String(error),
        },
      });
    }
  } finally {
    activeControllers.delete(id);
  }
});
