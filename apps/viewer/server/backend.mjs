// The CAD Viewer's local-filesystem backend: root resolution, catalog
// absolutization (raw scanner URLs -> `/__cad/asset?file=...` form the client
// consumes verbatim), and the guarded asset-path resolver.
//
// Serves ONE directory, fixed when the process starts. Requests do not name a
// directory: a page URL is just the origin, and `?file=` names a file inside
// this root. The containment check is therefore unconditional.
import fs from "node:fs";
import path from "node:path";

import { contentTypeForPath } from "./contentTypes.mjs";
import { localAssetUrlForPath } from "./encoding.mjs";
import {
  isHiddenName,
  isServedCadAsset,
  pathIsInside,
  scanCadDirectory,
  CAD_CATALOG_SCHEMA_VERSION,
} from "./scanner.mjs";

export class ForbiddenAssetError extends Error {
  constructor() {
    super("Forbidden");
    this.statusCode = 403;
  }
}

function toPosix(value) {
  return String(value || "").split(path.sep).join("/");
}

export function absoluteFileRef(filePath) {
  return toPosix(path.resolve(filePath));
}

export function relativeFileRef(rootPath, filePath) {
  return toPosix(path.relative(path.resolve(rootPath), path.resolve(filePath)));
}

export function normalizedFileRef(value) {
  const raw = String(value || "").trim().replace(/\\/g, "/");
  if (!raw) {
    return "";
  }
  if (raw.includes("\0")) {
    throw new Error("File path contains an invalid null byte");
  }
  // `file=` carries a filesystem path, not a URL path: the catalog is the only
  // source of refs and it emits absolute_file_ref form, which needs no decoding.
  return path.isAbsolute(raw) ? absoluteFileRef(raw) : raw.replace(/^\/+/, "");
}

function queryValue(rawUrl, name) {
  try {
    const url = new URL(String(rawUrl || ""), "http://localhost");
    return url.searchParams.get(name) || "";
  } catch {
    return "";
  }
}

function assetPathFromCatalogUrl(scanRepoRoot, rawUrl) {
  const text = String(rawUrl || "").trim();
  if (!text) {
    return "";
  }
  try {
    const url = new URL(text, "http://localhost");
    const explicitFile = url.searchParams.get("file") || "";
    if (explicitFile) {
      return path.resolve(explicitFile);
    }
    return path.resolve(scanRepoRoot, decodeURIComponent(url.pathname).replace(/^\/+/, ""));
  } catch {
    const cleaned = text.split("?", 1)[0].split("#", 1)[0].replace(/^\/+/, "");
    return path.resolve(scanRepoRoot, cleaned);
  }
}

function absolutePathFromCatalogValue(scanRepoRoot, value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return path.isAbsolute(text) ? path.resolve(text) : path.resolve(scanRepoRoot, text);
}

function absolutizeKeyed(obj, scanRepoRoot, keys) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
    return obj;
  }
  const next = { ...obj };
  for (const key of keys) {
    if (next[key]) {
      next[key] = absoluteFileRef(absolutePathFromCatalogValue(scanRepoRoot, next[key]));
    }
  }
  return next;
}

function absolutizeEntry(entry, { rootPath, scanRepoRoot }) {
  const outputPath = path.resolve(rootPath, String(entry.file || ""));
  const next = { ...entry };
  next.file = absoluteFileRef(outputPath);
  next.rootRelativeFile = relativeFileRef(rootPath, outputPath);
  if (entry.url && !String(entry.url).startsWith("/__cad/store")) {
    const assetPath = assetPathFromCatalogUrl(scanRepoRoot, entry.url);
    next.url = localAssetUrlForPath(assetPath, queryValue(entry.url, "v"));
    next.assetFile = absoluteFileRef(assetPath);
  }
  for (const key of ["poseUrl", "sourceUrl"]) {
    // Store URLs (/__cad/store?file=<packages-relative>) are already in their
    // served form — their file param is store-relative by contract, never a
    // root path to absolutize.
    if (entry[key] && !String(entry[key]).startsWith("/__cad/store")) {
      const assetPath = assetPathFromCatalogUrl(scanRepoRoot, entry[key]);
      next[key] = localAssetUrlForPath(assetPath, queryValue(entry[key], "v"));
    }
  }
  if (entry.artifact) {
    next.artifact = absolutizeKeyed(entry.artifact, scanRepoRoot, ["stepPath", "packagePath", "sourcePath", "cadPath"]);
  }
  const relations = entry.relations;
  if (relations && typeof relations === "object") {
    const nextRelations = {};
    for (const [key, relation] of Object.entries(relations)) {
      if (!relation || typeof relation !== "object") {
        nextRelations[key] = relation;
        continue;
      }
      const relationPath = path.resolve(rootPath, String(relation.file || ""));
      const nextRelation = { ...relation };
      nextRelation.file = absoluteFileRef(relationPath);
      nextRelation.rootRelativeFile = relativeFileRef(rootPath, relationPath);
      if (relation.url) {
        const relAsset = assetPathFromCatalogUrl(scanRepoRoot, relation.url);
        nextRelation.url = localAssetUrlForPath(relAsset, queryValue(relation.url, "v"));
        nextRelation.assetFile = absoluteFileRef(relAsset);
      }
      nextRelations[key] = nextRelation;
    }
    next.relations = nextRelations;
  }
  return next;
}

export class LocalAssetBackend {
  constructor(root = "") {
    const rootPath = path.resolve(String(root || "").trim() || process.cwd());
    if (rootPath.includes("\0")) {
      throw new Error("CAD Viewer directory contains an invalid null byte");
    }
    if (!fs.existsSync(rootPath) || !fs.statSync(rootPath).isDirectory()) {
      throw new Error(`CAD Viewer directory not found: ${rootPath}`);
    }
    this.kind = "local-fs";
    this._root = { rootPath, rootName: path.basename(rootPath) };
  }

  resolveRoot() {
    return this._root;
  }

  readCatalog() {
    const rootPath = this._root.rootPath;
    const raw = scanCadDirectory(rootPath);
    return {
      schemaVersion: CAD_CATALOG_SCHEMA_VERSION,
      entries: raw.entries.map((entry) => absolutizeEntry(entry, { rootPath, scanRepoRoot: rootPath })),
    };
  }

  // Throws for anything outside the root; returns true when a hidden path should
  // 404. Only root-relative components are checked, so a root that itself lives
  // under a hidden absolute path still works.
  _rejectOutsideRoot(candidate) {
    const rootPath = this._root.rootPath;
    if (!(candidate === rootPath || pathIsInside(candidate, rootPath))) {
      throw new ForbiddenAssetError();
    }
    const relative = path.relative(rootPath, candidate);
    return relative
      .split(path.sep)
      .some((part) => part && part !== ".." && part.startsWith("."));
  }

  assetPathForFileRef(fileRef) {
    const normalized = normalizedFileRef(fileRef);
    if (!normalized || !path.isAbsolute(normalized)) {
      return null;
    }
    const candidate = path.resolve(normalized);
    if (!isServedCadAsset(candidate)) {
      return null;
    }
    if (this._rejectOutsideRoot(candidate)) {
      return null;
    }
    return candidate;
  }

  // Containment WITHOUT the served-asset extension filter, for callers that do
  // not stream bytes (reveal). The root and hidden-path rules still apply.
  containedPathForFileRef(fileRef) {
    const normalized = normalizedFileRef(fileRef);
    if (!normalized || !path.isAbsolute(normalized)) {
      return null;
    }
    const candidate = path.resolve(normalized);
    if (isHiddenName(path.basename(candidate))) {
      return null;
    }
    if (this._rejectOutsideRoot(candidate)) {
      return null;
    }
    return candidate;
  }

  contentTypeForPath(filePath) {
    return contentTypeForPath(filePath);
  }

  catalogEntryForFileRef(catalog, fileRef) {
    const norm = normalizedFileRef(fileRef);
    if (!norm || !catalog || typeof catalog !== "object") {
      return null;
    }
    for (const entry of catalog.entries || []) {
      if (normalizedFileRef(entry.file) === norm || normalizedFileRef(entry.rootRelativeFile) === norm) {
        return entry;
      }
    }
    return null;
  }
}
