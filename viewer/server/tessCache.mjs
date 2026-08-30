// The viewer server's side of the shared component-tessellation cache
// (design/unified-tessellation.md): the same ~/.cache/cadgen/meshes store the
// export CLI and the snapshot host use, served to the viewer client on
// /__tess_cache/ — GET one entry, POST one write-back, POST /batch for the
// TESB container (one round trip for a whole assembly's hit set). Entries are
// OPAQUE here: the server stores and frames bytes; the one codec lives in
// packages/cadjs/src/lib/surf/tessellationCache.js, which is also the batch
// format's home. The store I/O below is a deliberate INLINE COPY of
// packages/cadjs/src/lib/surf/tessellationCacheFs.mjs (same directory, same
// naming, same best-effort semantics): the bundled skill runtime ships only
// dist/ + server/ and runs `node server/main.mjs` with no node_modules and no
// cadjs tree, so neither a bare "cadjs" specifier nor a relative import into
// viewer/packages/cadjs resolves there. tessCache.test.mjs pins this copy
// against the cadjs original so they cannot drift silently.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function tessellationCacheEnabled() {
  return process.env.CADGEN_MESH_CACHE !== "0";
}

// Inline mirror of cadgenCacheRootDir in the cadjs fs module (same resolution
// rule as Python's cadgen/_internal/cache_paths.py): CADGEN_CACHE_DIR, else
// the platform cache convention, else ~/.cache/cadgen.
function cadgenCacheRootDir(env = process.env) {
  const override = (env.CADGEN_CACHE_DIR || "").trim();
  if (override) return override;
  if (process.platform === "win32") {
    const localAppData = (env.LOCALAPPDATA || "").trim();
    if (localAppData) return path.join(localAppData, "cadgen");
  } else {
    const xdgCacheHome = (env.XDG_CACHE_HOME || "").trim();
    if (xdgCacheHome) return path.join(xdgCacheHome, "cadgen");
  }
  return path.join(os.homedir(), ".cache", "cadgen");
}

export function tessellationCacheDir() {
  return path.join(cadgenCacheRootDir(), "meshes");
}

function readCachedTessellationBytes(key) {
  if (!tessellationCacheEnabled()) return null;
  try {
    const buffer = fs.readFileSync(path.join(tessellationCacheDir(), `${key}.tess`));
    return new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);
  } catch {
    return null;
  }
}

function writeCachedTessellationBytes(key, bytes) {
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

export const TESS_CACHE_ROUTE_PREFIX = "/__tess_cache/";
export const TESS_CACHE_BATCH_PATH = "/__tess_cache/batch";
// Mirror of the snapshot host's TESS_CACHE_NAME_PATTERN: the cache lives
// OUTSIDE any served root, so a bad name is refused before touching disk.
const TESS_CACHE_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9.+_-]*\.tess$/;
const TESS_CACHE_BATCH_MAGIC = 0x42534554; // "TESB" little-endian
const TESS_CACHE_BATCH_VERSION = 1;
const TESS_CACHE_BATCH_MAX_NAMES = 4096;

export function tessCacheKeyFromRoutePath(pathname) {
  let name;
  try {
    name = decodeURIComponent(String(pathname || "").slice(TESS_CACHE_ROUTE_PREFIX.length));
  } catch {
    return null; // malformed percent-encoding is a refusal, not a crash
  }
  if (!TESS_CACHE_NAME_PATTERN.test(name) || name.includes("..")) {
    return null;
  }
  return name.slice(0, -".tess".length);
}

export function readTessCacheEntry(pathname) {
  const key = tessCacheKeyFromRoutePath(pathname);
  if (key === null) {
    return { status: 403, body: null };
  }
  const bytes = readCachedTessellationBytes(key);
  return bytes ? { status: 200, body: bytes } : { status: 404, body: null };
}

export function writeTessCacheEntry(pathname, body) {
  const key = tessCacheKeyFromRoutePath(pathname);
  if (key === null) {
    return 403;
  }
  // Accepted-and-dropped when disabled or empty: the client must never fail
  // on a best-effort write-back. writeCachedTessellationBytes already
  // swallows disk errors and honours CADGEN_MESH_CACHE=0.
  if (body && body.length) {
    writeCachedTessellationBytes(key, body);
  }
  return 204;
}

// The TESB container for a JSON {"names": [...]} request. Refused names and
// read failures are per-entry MISSES (zero length), never errors; a malformed
// request returns null (the route answers 400).
export function readTessCacheBatch(body) {
  let names;
  try {
    names = JSON.parse(Buffer.from(body || []).toString("utf8"))?.names;
  } catch {
    return null;
  }
  if (!Array.isArray(names) || names.length > TESS_CACHE_BATCH_MAX_NAMES) {
    return null;
  }
  const entries = names.map((name) => {
    if (typeof name !== "string") return null;
    const key = tessCacheKeyFromRoutePath(`${TESS_CACHE_ROUTE_PREFIX}${name}`);
    return key === null ? null : readCachedTessellationBytes(key);
  });
  let total = 12;
  for (const entry of entries) {
    total += 4 + (entry ? (entry.length + 3) & ~3 : 0);
  }
  const out = Buffer.alloc(total);
  out.writeUInt32LE(TESS_CACHE_BATCH_MAGIC, 0);
  out.writeUInt32LE(TESS_CACHE_BATCH_VERSION, 4);
  out.writeUInt32LE(entries.length, 8);
  let offset = 12;
  for (const entry of entries) {
    out.writeUInt32LE(entry ? entry.length : 0, offset);
    offset += 4;
    if (entry && entry.length) {
      out.set(entry, offset);
      offset += (entry.length + 3) & ~3;
    }
  }
  return out;
}
