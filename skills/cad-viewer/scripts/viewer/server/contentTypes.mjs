// The two hand-written content-type maps. Do NOT replace these with a mime
// library: the three.js GLB/WASM loaders and the browser ES-module loader are
// strict, so the bytes must match what the client has always been served.
import path from "node:path";

// Static dist/SPA assets. Unknown extension -> "" (caller sets NO content-type header).
const STATIC_CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm",
};

export function contentTypeForStaticAsset(filePath) {
  return STATIC_CONTENT_TYPES[path.extname(String(filePath || "")).toLowerCase()] || "";
}

// CAD asset map (/__cad/asset + /__cad/download). Unknown ext -> octet-stream.
const ASSET_CONTENT_TYPES = {
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".glb": "model/gltf-binary",
  ".stl": "model/stl",
  ".3mf": "model/3mf",
  ".step": "application/step",
  ".stp": "application/step",
  ".dxf": "application/dxf",
  ".py": "text/plain; charset=utf-8",
  ".urdf": "application/xml; charset=utf-8",
  ".srdf": "application/xml; charset=utf-8",
  ".sdf": "application/xml; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

export function contentTypeForPath(filePath) {
  return ASSET_CONTENT_TYPES[path.extname(String(filePath || "")).toLowerCase()] || "application/octet-stream";
}
