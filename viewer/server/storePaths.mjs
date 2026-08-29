// Store-primary resolution: the JS mirror of cadgen's cache_paths + catalog
// helpers (cadgen/_internal/cache_paths.py, cadgen/catalog.py). Render
// packages live in the user-level store keyed by the DOCUMENT's content hash;
// locks and progress records key by the MODEL's path. The render-contract
// sync test pins the shared literals via packageContract.mjs.
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { STEP_PACKAGE_VERSION } from "./packageContract.mjs";

// Inline mirror of cadgenCacheRootDir (same resolution rule as Python):
// CADGEN_STORE_DIR, else the platform cache convention, else ~/.cache/cadgen.
export function cadgenCacheRootDir(env = process.env) {
  const override = (env.CADGEN_STORE_DIR || "").trim();
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

export function storePackagesDir() {
  return path.join(cadgenCacheRootDir(), "packages");
}

export function storeLocksDir() {
  return path.join(cadgenCacheRootDir(), "locks");
}

// Content-hash memo keyed by (path, mtimeNs, size): status polls and catalog
// scans re-ask for the same file's hash constantly. A stale hit needs an edit
// preserving BOTH mtime-ns and size — not a real editor.
const HASH_MEMO = new Map();

export function artifactFileHash(filePath) {
  let resolved;
  let stat;
  try {
    resolved = fs.realpathSync(filePath);
    stat = fs.statSync(resolved);
  } catch {
    return null;
  }
  const cached = HASH_MEMO.get(resolved);
  const mtimeNs = String(stat.mtimeNs ?? stat.mtimeMs);
  if (cached && cached.mtimeNs === mtimeNs && cached.size === stat.size) {
    return cached.hash;
  }
  let hash;
  try {
    hash = crypto.createHash("sha256").update(fs.readFileSync(resolved)).digest("hex");
  } catch {
    return null;
  }
  HASH_MEMO.set(resolved, { mtimeNs, size: stat.size, hash });
  return hash;
}

export function packageDirForHash(stepHash) {
  return path.join(storePackagesDir(), `${stepHash}-v${STEP_PACKAGE_VERSION}`);
}

/** The store package dir for an artifact file, resolved by CONTENT; a missing
 * or unreadable file resolves to a deterministic never-created path so every
 * existence-checking caller just answers "no package". */
export function renderPackageDir(filePath) {
  const digest = artifactFileHash(filePath);
  if (digest === null) {
    return path.join(storePackagesDir(), `unbuilt-${artifactPathKey(filePath)}`);
  }
  return packageDirForHash(digest);
}

/** Model-path identity for locks/progress: sha256 of the resolved path,
 * truncated to 24 hex chars (mirror of cadgen.catalog.artifact_path_key). */
export function artifactPathKey(filePath) {
  let resolved;
  try {
    resolved = fs.realpathSync(filePath);
  } catch {
    resolved = path.resolve(String(filePath));
  }
  return crypto.createHash("sha256").update(resolved, "utf-8").digest("hex").slice(0, 24);
}

/** The coordination scope the progress reader derives dot-named siblings
 * from: <cache>/locks/<pathKey> (mirror of cadgen.catalog.coordination_scope). */
export function coordinationScope(filePath) {
  return path.join(storeLocksDir(), artifactPathKey(filePath));
}
