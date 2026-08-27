// Client-side mesh export: STL/GLB/3MF serialized in the browser from the same
// geometry the viewport renders (design/standalone-viewer.md Phase B).
//
// This is the no-cadgen fallback: the server route re-runs the generator and
// meshes natively when Python is available, but a standalone viewer already
// holds every triangle it drew, so "Export STL" must not require an install.
// The one honest difference from the native path: triangles are at RENDER
// tessellation rather than OCCT's export-tolerance meshing.
import { entrySourceFormat } from "cadjs/lib/fileFormats.js";
import { renderCapabilities } from "cadjs/lib/renderCapabilities.js";
import { entryAssetUrl, entryMeshAssetUrl } from "cadjs/lib/entryAssets.js";
import { loadRenderJson, loadRenderSurf } from "cadjs/lib/renderAssetClient.js";
import { loadRenderMeshByUrl } from "cadjs/lib/render/meshLoaders.js";
import { meshToFormat } from "cadjs/lib/implicitCad/exporters.js";
import { resolvePackageAssetUrl } from "../components/workbench/hooks/packageAssetUrl.js";

export const CLIENT_MESH_EXPORT_FORMATS = ["stl", "glb", "3mf"];

function toTransformArray(value) {
  if (!Array.isArray(value) || value.length < 12) {
    return null;
  }
  const matrix = value.slice(0, 12).map(Number);
  return matrix.every(Number.isFinite) ? matrix : null;
}

function matrixDeterminant3(matrix) {
  return (
    matrix[0] * (matrix[5] * matrix[10] - matrix[6] * matrix[9]) -
    matrix[1] * (matrix[4] * matrix[10] - matrix[6] * matrix[8]) +
    matrix[2] * (matrix[4] * matrix[9] - matrix[5] * matrix[8])
  );
}

// Expand one component's meshData (indexed or soup) into world-space triangle
// soup under `matrix` (row-major 3x4, absolute — the descriptor's occurrence
// transforms are not hierarchical). A mirroring transform flips the winding so
// the recomputed normals stay outward.
function appendTransformedSoup(chunks, meshData, matrix) {
  const vertices = meshData?.vertices;
  if (!vertices?.length) {
    return;
  }
  const indices = meshData.indices?.length
    ? meshData.indices
    : Uint32Array.from({ length: vertices.length / 3 }, (_, i) => i);
  const mirrored = matrix ? matrixDeterminant3(matrix) < 0 : false;
  const out = new Float32Array(indices.length * 3);
  for (let triangle = 0; triangle < indices.length / 3; triangle += 1) {
    for (let corner = 0; corner < 3; corner += 1) {
      const sourceCorner = mirrored ? 2 - corner : corner;
      const source = indices[triangle * 3 + sourceCorner] * 3;
      const target = (triangle * 3 + corner) * 3;
      const x = vertices[source];
      const y = vertices[source + 1];
      const z = vertices[source + 2];
      if (matrix) {
        out[target] = matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3];
        out[target + 1] = matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7];
        out[target + 2] = matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11];
      } else {
        out[target] = x;
        out[target + 1] = y;
        out[target + 2] = z;
      }
    }
  }
  chunks.push(out);
}

async function collectStepPackageSoup(entry) {
  const packageUrl = entryAssetUrl(entry, "glb");
  if (!packageUrl) {
    throw new Error("The model has no render package to export from");
  }
  const descriptor = await loadRenderJson(resolvePackageAssetUrl(packageUrl, "assembly.json"));
  if (!descriptor || descriptor.kind !== "assembly-package") {
    throw new Error("The model's render package is not an assembly package");
  }
  const components = descriptor.components || {};
  const meshDataByCid = new Map();
  await Promise.all(
    Object.entries(components).map(async ([cid, component]) => {
      const surfRef = String(component?.surf || "").trim();
      if (!surfRef) {
        return;
      }
      meshDataByCid.set(cid, await loadRenderSurf(resolvePackageAssetUrl(packageUrl, surfRef)));
    }),
  );
  const chunks = [];
  for (const occurrence of descriptor.occurrences || []) {
    const meshData = meshDataByCid.get(String(occurrence?.component || "").trim());
    if (meshData) {
      appendTransformedSoup(chunks, meshData, toTransformArray(occurrence?.transform));
    }
  }
  return chunks;
}

function mergeSoup(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  if (!total) {
    throw new Error("The model produced no triangles to export");
  }
  const merged = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function triggerBlobDownload(body, filename, contentType) {
  const blob = new Blob([body], { type: contentType || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    // Delayed: revoking synchronously races the click-initiated fetch in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
}

export function clientMeshExportSupported(entry, format) {
  if (!CLIENT_MESH_EXPORT_FORMATS.includes(String(format || "").toLowerCase())) {
    return false;
  }
  return renderCapabilities(entrySourceFormat(entry)).clientMeshExport != null;
}

// The serialization half, runtime-agnostic (node-testable): geometry in,
// bytes out. Returns {body, filename, contentType, triangleCount}.
export async function buildEntryMeshExport(entry, format) {
  const normalized = String(format || "").toLowerCase();
  const baseName = String(entry?.file || "model")
    .split("/")
    .pop()
    .replace(/\.(step|stp)(\.py)?$/i, "")
    .replace(/\.(stl|3mf|glb)$/i, "");
  let chunks;
  if (renderCapabilities(entrySourceFormat(entry)).clientMeshExport === "package") {
    chunks = await collectStepPackageSoup(entry);
  } else {
    const meshData = await loadRenderMeshByUrl(entryMeshAssetUrl(entry));
    chunks = [];
    appendTransformedSoup(chunks, meshData, null);
  }
  const positions = mergeSoup(chunks);
  const { body, contentType, extension } = meshToFormat({ positions }, normalized, { name: baseName });
  return {
    body,
    contentType,
    filename: `${baseName}${extension}`,
    triangleCount: positions.length / 9,
  };
}

// Export `entry` as `format`, entirely in the browser. Returns {filename}.
export async function exportEntryMeshClientSide(entry, format) {
  const { body, filename, contentType } = await buildEntryMeshExport(entry, format);
  triggerBlobDownload(body, filename, contentType);
  return { filename };
}
