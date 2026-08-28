// Lazy singleton for the WASM OCCT kernel (opencascade.js full build).
//
// Import-side only (design/standalone-viewer.md Phase C): the render path never
// touches this — it exists so a Python-less viewer can convert a foreign STEP
// into the standard render package, once, at WASM speed. ~48MB module, ~2.3s
// init, so nothing loads it until an import actually starts.
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_ROOT = path.resolve(SERVER_DIR, "..", "..");

let kernelPromise = null;

export function loadKernel() {
  if (!kernelPromise) {
    kernelPromise = (async () => {
      const distDir = path.join(VIEWER_ROOT, "node_modules", "opencascade.js", "dist");
      // The emscripten module expects CJS globals its node build reads at import.
      globalThis.__dirname = distDir;
      globalThis.require = createRequire(pathToFileURL(path.join(distDir, "node.js")).href);
      const factory = (
        await import(pathToFileURL(path.join(distDir, "opencascade.full.js")).href)
      ).default;
      return await new factory({
        locateFile: (p) => (p.endsWith(".wasm") ? path.join(distDir, "opencascade.full.wasm") : p),
      });
    })();
  }
  return kernelPromise;
}

// C++ double& out-params surface in ocjs as objects with `.current`.
export function ref(value = 0) {
  return { current: value };
}
