// Node-side store for the shared component-tessellation cache: the
// ~/.cache/cadgen/meshes/<key>.tess directory consumed by bin/mesh-export.mjs
// and served to the snapshot page by cadgen's snapshot host (which reads the
// same directory from Python — the path and naming here are a cross-language
// contract). Best-effort by design: read/write failures are misses, writes
// are atomic (tmp + rename), CADGEN_MESH_CACHE=0 disables everything.
//
// Keep this file the only fs-touching half; the codec and key scheme live in
// tessellationCache.js, which stays browser-pure.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function tessellationCacheEnabled(env = process.env) {
  return env.CADGEN_MESH_CACHE !== "0";
}

export function tessellationCacheDir() {
  return path.join(os.homedir(), ".cache", "cadgen", "meshes");
}

export function readCachedTessellationBytes(key) {
  if (!tessellationCacheEnabled()) return null;
  try {
    const buffer = fs.readFileSync(path.join(tessellationCacheDir(), `${key}.tess`));
    return new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);
  } catch {
    return null;
  }
}

export function writeCachedTessellationBytes(key, bytes) {
  if (!tessellationCacheEnabled()) return;
  try {
    const dir = tessellationCacheDir();
    fs.mkdirSync(dir, { recursive: true });
    const target = path.join(dir, `${key}.tess`);
    const temp = `${target}.${process.pid}.tmp`;
    fs.writeFileSync(temp, bytes);
    fs.renameSync(temp, target);
  } catch {
    // Best-effort: a full disk or a permissions problem must not fail callers.
  }
}
