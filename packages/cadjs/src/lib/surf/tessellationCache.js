// THE component-tessellation cache interface (design/unified-tessellation.md
// Phase 3): one key scheme, one codec, shared by every consumer that turns a
// .surf into triangles — the export CLI (bin/mesh-export.mjs), the snapshot
// browser runtime, and later the viewer (Phase 5). A cache entry is one FULL
// tessellateComponent result for one component at one tolerance pair, so a
// snapshot warms the cache for an export and vice versa.
//
// This module is BROWSER-PURE: codec and key only, no filesystem. Node
// consumers pair it with tessellationCacheFs.mjs (the ~/.cache/cadgen/meshes
// store); browser consumers reach a store through the pluggable async
// provider below (the snapshot page's provider round-trips bytes over its
// Playwright-routed /__tess_cache/ origin, served by cadgen's snapshot host).
//
// Entry layout (little-endian): "TESS" magic u32, version u32, headerLength
// u32, JSON header padded with trailing spaces to a 4-byte boundary, then the
// typed-array payload — positions f32, normals f32, faceOrds f32, indices
// u32, sideOrds u32, then each display-edge polyline f32 in header order.
// Every section is 4-byte-sized, so decode returns zero-copy views over the
// source buffer.

import { DEFAULT_OPTIONS, tessellateComponent } from "./tessellate.js";

export const TESS_CACHE_MAGIC = 0x53534554; // "TESS" little-endian
// v2: full component payload (faceOrds, sideOrds, edges, bounds, scale) so
// render consumers can reuse entries; v1 stored the export subset only.
export const TESS_CACHE_VERSION = 2;

// Tolerances are part of the key; format them canonically so 0.0015 and
// 1.5e-3 hit the same entry.
export function tessellationCacheKey(cid, options = {}) {
  const effective = { ...DEFAULT_OPTIONS, ...options };
  const num = (value) => Number(value).toExponential(6);
  return `${cid}-l${num(effective.chordTolerance)}-a${num(effective.angleTolerance)}`;
}

// Debug toggles change the geometry or bloat the result; those runs must
// neither read nor write the shared cache.
export function tessellationOptionsCacheable(options = {}) {
  return !options.collectBoundaryDebug && !options.noSharedBoundaries && !options.noConformPass;
}

function align4(value) {
  return (value + 3) & ~3;
}

export function encodeComponentTessellation(component, { partColor = null } = {}) {
  const edges = Array.isArray(component.edges) ? component.edges : [];
  const headerJson = JSON.stringify({
    partColor: partColor ?? null,
    faceRanges: component.faceRanges,
    bounds: { min: [...component.bounds.min], max: [...component.bounds.max] },
    scale: component.scale,
    positionCount: component.positions.length,
    normalCount: component.normals.length,
    faceOrdCount: component.faceOrds.length,
    indexCount: component.indices.length,
    sideOrdCount: component.sideOrds.length,
    edges: edges.map((edge) => ({
      ord: edge.ord,
      visibilityClass: edge.visibilityClass ?? null,
      count: edge.polyline.length,
    })),
  });
  const headerBytes = new TextEncoder().encode(headerJson);
  // Pad the header with spaces (valid JSON whitespace) so the payload starts
  // 4-byte aligned and decode can hand out views instead of copies.
  const headerLength = align4(headerBytes.length);
  const payloadFloats =
    component.positions.length +
    component.normals.length +
    component.faceOrds.length +
    component.indices.length +
    component.sideOrds.length +
    edges.reduce((sum, edge) => sum + edge.polyline.length, 0);
  const bytes = new Uint8Array(12 + headerLength + payloadFloats * 4);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, TESS_CACHE_MAGIC, true);
  view.setUint32(4, TESS_CACHE_VERSION, true);
  view.setUint32(8, headerLength, true);
  bytes.set(headerBytes, 12);
  bytes.fill(0x20, 12 + headerBytes.length, 12 + headerLength);
  let offset = 12 + headerLength;
  const append = (array, Ctor) => {
    new Ctor(bytes.buffer, offset, array.length).set(array);
    offset += array.length * 4;
  };
  append(component.positions, Float32Array);
  append(component.normals, Float32Array);
  append(component.faceOrds, Float32Array);
  append(component.indices, Uint32Array);
  append(component.sideOrds, Uint32Array);
  for (const edge of edges) append(edge.polyline, Float32Array);
  return bytes;
}

export function decodeComponentTessellation(bytes) {
  try {
    if (!(bytes instanceof Uint8Array) || bytes.length < 12) return null;
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (view.getUint32(0, true) !== TESS_CACHE_MAGIC) return null;
    if (view.getUint32(4, true) !== TESS_CACHE_VERSION) return null;
    const headerLength = view.getUint32(8, true);
    const header = JSON.parse(
      new TextDecoder().decode(bytes.subarray(12, 12 + headerLength)),
    );
    let offset = bytes.byteOffset + 12 + headerLength;
    const expect =
      (header.positionCount +
        header.normalCount +
        header.faceOrdCount +
        header.indexCount +
        header.sideOrdCount +
        header.edges.reduce((sum, edge) => sum + edge.count, 0)) * 4;
    if (bytes.byteOffset + bytes.byteLength - offset !== expect) return null;
    // Zero-copy views are only sound on 4-byte-aligned offsets; a misaligned
    // source buffer (e.g. a subarray) falls back to copying via slice.
    const aligned = offset % 4 === 0;
    const take = (count, Ctor) => {
      const section = aligned
        ? new Ctor(bytes.buffer, offset, count)
        : new Ctor(bytes.buffer.slice(offset, offset + count * 4));
      offset += count * 4;
      return section;
    };
    const positions = take(header.positionCount, Float32Array);
    const normals = take(header.normalCount, Float32Array);
    const faceOrds = take(header.faceOrdCount, Float32Array);
    const indices = take(header.indexCount, Uint32Array);
    const sideOrds = take(header.sideOrdCount, Uint32Array);
    const edges = header.edges.map((edge) => ({
      ord: edge.ord,
      visibilityClass: edge.visibilityClass,
      polyline: take(edge.count, Float32Array),
    }));
    return {
      component: {
        positions,
        normals,
        faceOrds,
        indices,
        sideOrds,
        faceRanges: header.faceRanges,
        edges,
        bounds: header.bounds,
        scale: header.scale,
      },
      partColor: header.partColor ?? null,
    };
  } catch {
    return null; // a corrupt entry is a miss, never an error
  }
}

// --- pluggable store (browser consumers) -----------------------------------
//
// get(key) -> Promise<Uint8Array|null>, put(key, bytes) -> Promise<void>.
// Both are best-effort: any throw is treated as a miss / ignored. No provider
// registered (the default — e.g. the viewer today) means every call
// tessellates exactly as before.

let cacheProvider = null;

export function setTessellationCacheProvider(provider) {
  cacheProvider = provider && typeof provider.get === "function" ? provider : null;
}

export async function tessellateComponentCached(index, floats, { cid = "", options = {} } = {}) {
  const provider = cacheProvider;
  if (!provider || !cid || !tessellationOptionsCacheable(options)) {
    return tessellateComponent(index, floats, options);
  }
  const key = tessellationCacheKey(cid, options);
  try {
    const cached = decodeComponentTessellation(await provider.get(key));
    if (cached) return cached.component;
  } catch {
    // miss
  }
  const component = tessellateComponent(index, floats, options);
  if (typeof provider.put === "function") {
    try {
      await provider.put(
        key,
        encodeComponentTessellation(component, {
          partColor: Array.isArray(index.partColor) ? index.partColor : null,
        }),
      );
    } catch {
      // best-effort write-back
    }
  }
  return component;
}
