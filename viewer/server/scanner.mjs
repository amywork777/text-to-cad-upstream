// CAD directory scanner — produces the raw viewer catalog.
//
// The raw catalog entry shape is `{file, kind, url, hash, bytes, ...}` where
// `file` is root-relative, `url` is repo-relative (`/seg/seg?v=<token>`) and gets
// rewritten to the `/__cad/asset?file=...` form by the backend's absolutizer.
// `hash` is sha256 hex; `bytes` is the byte size; the `?v=` token is
// `base36(size)-base36(mtimeNs)` (encoding.fileVersion).
//
// The package-path helpers mirror cadgen.catalog: a generator entry
// (`<name>.step.py`) and the STEP file it outputs share ONE package
// (design/step-document-architecture.md), so both key by the STEP filename.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { fileVersion } from "./encoding.mjs";

export const CAD_CATALOG_SCHEMA_VERSION = 4;

export const SOURCE_EXTENSIONS = new Set([
  ".step", ".stp", ".stl", ".3mf", ".glb", ".dxf", ".urdf", ".srdf", ".sdf",
]);
export const IMPLICIT_CAD_EXTENSIONS = [".implicit.js", ".implicit.mjs"];
// Dot-prefixed (hidden) directories are skipped generically; this set only
// needs the non-hidden names.
const VIEWER_SKIPPED_DIRECTORIES = new Set([
  "__cadgen__", "__pycache__", "build", "coverage", "dist", "node_modules", "viewer",
]);

// Mirrors cadgen.catalog / cadgen._internal.{drawing,implicit}_package. Values are
// pinned by the scanner fixture test against packages cadgen actually writes.
export const CADGEN_DIRNAME = "__cadgen__";
export const CADGEN_MODELS_DIRNAME = "models";
const DRAWING_DESCRIPTOR_NAME = "drawing.json";
const DRAWING_PACKAGE_KIND = "drawing-package";
const IMPLICIT_DESCRIPTOR_NAME = "implicit.json";
const IMPLICIT_PACKAGE_KIND = "implicit-package";

export const DXF_GENERATOR_SUFFIX = ".dxf.py";

export function isDxfGeneratorPath(filePath) {
  return String(filePath || "").toLowerCase().endsWith(DXF_GENERATOR_SUFFIX);
}

export function isInsideCadgenDir(filePath) {
  return String(filePath || "").split(path.sep).includes(CADGEN_DIRNAME);
}

export function isRenderPackagePath(filePath) {
  const p = String(filePath || "");
  if (!path.basename(p)) {
    return false;
  }
  return (
    path.basename(path.dirname(p)) === CADGEN_MODELS_DIRNAME &&
    path.basename(path.dirname(path.dirname(p))) === CADGEN_DIRNAME
  );
}

// STEP models key by the STEP FILE: <name>.step.py -> <name>.step. Mirrors
// cadgen.catalog.render_package_dir.
function packageKeyName(name) {
  const lowered = name.toLowerCase();
  for (const suffix of [".step.py", ".stp.py"]) {
    if (lowered.endsWith(suffix)) {
      return name.slice(0, -3);
    }
  }
  return name;
}

function realpathOr(value) {
  try {
    return fs.realpathSync(value);
  } catch {
    // Resolve as much as exists: realpath the nearest existing ancestor so a
    // symlinked model folder still keys like cadgen's Path.resolve() does for
    // a not-yet-created package dir.
    const dir = path.dirname(value);
    if (dir === value) {
      return value;
    }
    return path.join(realpathOr(dir), path.basename(value));
  }
}

// Resolved, matching cadgen.catalog.render_package_dir exactly: two paths
// reaching the same package must take the same lock sentinel.
export function renderPackageDir(entryPath) {
  const base = realpathOr(path.resolve(entryPath));
  return realpathOr(
    path.join(path.dirname(base), CADGEN_DIRNAME, CADGEN_MODELS_DIRNAME, packageKeyName(path.basename(base))),
  );
}

// The package directory AS THE SCANNER WALKED IT — deliberately NOT resolved.
// An asset URL is relative to the scan root, so a realpath that leaves that
// root (a symlinked model folder, macOS /var -> /private/var) yields a URL
// that escapes the root and 404s.
export function renderPackageAssetDir(entryPath) {
  const base = path.resolve(entryPath);
  return path.join(path.dirname(base), CADGEN_DIRNAME, CADGEN_MODELS_DIRNAME, packageKeyName(path.basename(base)));
}

export function entryPathForRenderPackage(packagePath) {
  if (!isRenderPackagePath(packagePath)) {
    return null;
  }
  const folder = path.dirname(path.dirname(path.dirname(packagePath)));
  return path.join(folder, path.basename(packagePath));
}

// --- path / ref helpers ---
export function toPosixPath(value) {
  return String(value || "").split(path.sep).join("/");
}

export function relativePathStaysInsideRoot(relativePath) {
  return (
    relativePath === "" ||
    (relativePath !== ".." && !relativePath.startsWith(`..${path.sep}`) && !path.isAbsolute(relativePath))
  );
}

export function repoRelativePath(repoRoot, filePath) {
  return toPosixPath(path.relative(path.resolve(repoRoot), path.resolve(filePath)));
}

export function pathIsInside(filePath, rootPath) {
  return relativePathStaysInsideRoot(path.relative(path.resolve(rootPath), path.resolve(filePath)));
}

export function pathIsImplicitCadSource(value = "") {
  const pathname = String(value || "").split(/[?#]/, 1)[0].toLowerCase();
  return IMPLICIT_CAD_EXTENSIONS.some((ext) => pathname.endsWith(ext));
}

// --- file stats / hashing / urls ---
function fileStats(filePath) {
  try {
    const st = fs.statSync(filePath, { bigint: true });
    return st.isFile() ? st : null;
  } catch {
    return null;
  }
}

// sha256 memoized on (path, size, mtimeNs): the catalog is polled every 2s and
// re-hashing a multi-hundred-MB STEP per poll would put a full file read on the
// hot path. Same output as an uncached hash for any file the OS reports unchanged.
const HASH_CACHE = new Map();
const HASH_CACHE_LIMIT = 4096;

function sha256File(filePath, stats = null) {
  const st = stats || fileStats(filePath);
  const key = st ? `${filePath}\0${st.size}\0${st.mtimeNs}` : "";
  if (key && HASH_CACHE.has(key)) {
    return HASH_CACHE.get(key);
  }
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  const digest = hash.digest("hex");
  if (key) {
    if (HASH_CACHE.size >= HASH_CACHE_LIMIT) {
      HASH_CACHE.clear();
    }
    HASH_CACHE.set(key, digest);
  }
  return digest;
}

function encodeUrlPath(repoRelative) {
  return `/${repoRelative.split("/").map((part) => encodeURIComponent(part)).join("/")}`;
}

function packageDescriptorStats(packageDir) {
  return fileStats(path.join(packageDir, "assembly.json"));
}

export function assetForPath(repoRoot, filePath) {
  const st = fileStats(filePath);
  if (!st) {
    const descriptor = packageDescriptorStats(filePath);
    if (descriptor) {
      const version = fileVersion(descriptor);
      const repoPath = repoRelativePath(repoRoot, filePath);
      return {
        url: `${encodeUrlPath(repoPath)}?v=${encodeURIComponent(version)}`,
        hash: sha256File(path.join(filePath, "assembly.json"), descriptor),
        bytes: Number(descriptor.size),
      };
    }
    return null;
  }
  const version = fileVersion(st);
  const repoPath = repoRelativePath(repoRoot, filePath);
  return {
    url: `${encodeUrlPath(repoPath)}?v=${encodeURIComponent(version)}`,
    hash: sha256File(filePath, st),
    bytes: Number(st.size),
  };
}

function assetUrlForPath(repoRoot, filePath) {
  return encodeUrlPath(repoRelativePath(repoRoot, filePath));
}

// --- classification ---
function sourceFormatFromExtension(extension) {
  const normalized = extension.toLowerCase().replace(/^\./, "");
  return normalized === "stp" ? "stp" : normalized;
}

export function sourceFormatForPath(sourcePath, extension = null) {
  const ext = extension === null ? path.extname(sourcePath) : extension;
  return pathIsImplicitCadSource(sourcePath) ? "implicit" : sourceFormatFromExtension(ext);
}

// --- directory scan helpers ---
export function isHiddenName(name) {
  return String(name || "").startsWith(".");
}

function shouldSkipDirectory(name) {
  return VIEWER_SKIPPED_DIRECTORIES.has(name) || isHiddenName(name);
}

function collectCadSourceFiles(rootPath, result) {
  let entries;
  try {
    entries = fs.readdirSync(rootPath, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  } catch {
    return result;
  }
  for (const entry of entries) {
    const entryPath = path.join(rootPath, entry.name);
    if (entry.isDirectory()) {
      if (!shouldSkipDirectory(entry.name)) {
        collectCadSourceFiles(entryPath, result);
      }
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    if (isHiddenName(entry.name)) {
      continue;
    }
    const lowerName = entry.name.toLowerCase();
    const extension = path.extname(entry.name).toLowerCase();
    if (lowerName.endsWith(".step.py") || lowerName.endsWith(DXF_GENERATOR_SUFFIX)) {
      // List generated models/drawings whether or not their render artifact has been
      // built: an unbuilt one reports `needs-build` via /__cad/artifact and is built
      // on demand when opened, so a fresh checkout shows ALL generated entries.
      result.push(entryPath);
      continue;
    }
    if (SOURCE_EXTENSIONS.has(extension) || pathIsImplicitCadSource(entryPath)) {
      result.push(entryPath);
    }
  }
  return result;
}

export function fileHasPythonGenerator(filePath, generatorName) {
  if (!generatorName) {
    return false;
  }
  try {
    const text = fs.readFileSync(filePath, "utf8");
    return new RegExp(`\\b${generatorName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\(`).test(text);
  } catch {
    return false;
  }
}

// The root element's name attribute, when the root element has the expected tag.
// Minimal XML prolog scan — enough for URDF/SRDF pairing, which only needs the
// first start tag.
function xmlRootName(filePath, expectedTag = "robot") {
  let text;
  try {
    text = fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
  let i = 0;
  if (text.charCodeAt(0) === 0xfeff) {
    i = 1;
  }
  const length = text.length;
  for (;;) {
    while (i < length && /\s/.test(text[i])) {
      i += 1;
    }
    if (i >= length || text[i] !== "<") {
      return null;
    }
    if (text.startsWith("<?", i)) {
      const end = text.indexOf("?>", i);
      if (end === -1) return null;
      i = end + 2;
      continue;
    }
    if (text.startsWith("<!--", i)) {
      const end = text.indexOf("-->", i);
      if (end === -1) return null;
      i = end + 3;
      continue;
    }
    if (text.startsWith("<!", i)) {
      const end = text.indexOf(">", i);
      if (end === -1) return null;
      i = end + 1;
      continue;
    }
    break;
  }
  const match = /^<([A-Za-z_][\w.:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/.exec(text.slice(i));
  if (!match || match[1] !== expectedTag) {
    return null;
  }
  const nameAttr = /(?:^|\s)name\s*=\s*("([^"]*)"|'([^']*)')/.exec(match[2]);
  return nameAttr ? String(nameAttr[2] ?? nameAttr[3] ?? "").trim() : "";
}

function pairedUrdfPathForSrdf(sourcePath) {
  // An SRDF pairs with the same-directory URDF whose root <robot name> matches;
  // ambiguity (0 or 2+ matches) yields no pairing.
  const robotName = xmlRootName(sourcePath);
  if (!robotName) {
    return null;
  }
  const directory = path.dirname(sourcePath);
  let names;
  try {
    names = fs.readdirSync(directory).filter((name) => path.extname(name).toLowerCase() === ".urdf").sort();
  } catch {
    return null;
  }
  const matches = names
    .map((name) => path.join(directory, name))
    .filter((candidate) => xmlRootName(candidate) === robotName);
  if (matches.length !== 1) {
    return null;
  }
  return fileStats(matches[0]) ? matches[0] : null;
}

// --- render-package payload assets ---
// Which baked GLB a catalog entry renders from, per kind. A DXF and an implicit
// model have no renderable geometry of their own, so each bakes a mesh into its
// entry-keyed __cadgen__ package and the scanner publishes THAT as the entry's
// `glb` relation — one render path, fed by one asset key.
const RENDER_PACKAGE_GLB_PAYLOADS = {
  dxf: [DRAWING_DESCRIPTOR_NAME, DRAWING_PACKAGE_KIND, "preview"],
  implicit: [IMPLICIT_DESCRIPTOR_NAME, IMPLICIT_PACKAGE_KIND, "glb"],
};

function readPackageDescriptor(packageDir, descriptorName, packageKind) {
  let descriptor;
  try {
    descriptor = JSON.parse(fs.readFileSync(path.join(packageDir, descriptorName), "utf8"));
  } catch {
    return {};
  }
  if (!descriptor || typeof descriptor !== "object" || descriptor.kind !== packageKind) {
    return {};
  }
  return descriptor;
}

function renderPackageGlbRelation(repoRoot, rootPath, sourcePath, kind) {
  const payload = RENDER_PACKAGE_GLB_PAYLOADS[kind];
  if (!payload) {
    return null;
  }
  const [descriptorName, packageKind, payloadField] = payload;
  const packageDir = renderPackageAssetDir(sourcePath);
  const descriptor = readPackageDescriptor(packageDir, descriptorName, packageKind);
  const glbRef = String(descriptor[payloadField] || "").trim();
  const glbPath = glbRef ? path.join(packageDir, glbRef) : "";
  const stats = glbPath ? fileStats(glbPath) : null;
  if (!stats) {
    return null;
  }
  // size+mtime, not sha256: a baked mesh runs to tens of megabytes and neither
  // descriptor records a digest for it; the token changes on every rebuild, which
  // is all the client's cache key needs.
  const version = fileVersion(stats);
  return {
    file: repoRelativePath(rootPath, glbPath),
    url: `${assetUrlForPath(repoRoot, glbPath)}?v=${encodeURIComponent(version)}`,
    hash: version,
    bytes: Number(stats.size),
  };
}

// --- entry builders ---
function readDrawingCatalogMetadata(packageDir) {
  return readPackageDescriptor(packageDir, DRAWING_DESCRIPTOR_NAME, DRAWING_PACKAGE_KIND);
}

function applyDrawingPreviewStats(entry, packageDir) {
  // Imported and generated drawings bake the identical package, and the viewer
  // folds from these facts — one helper for BOTH kinds.
  const descriptor = readDrawingCatalogMetadata(packageDir);
  const previewStats = descriptor.previewStats;
  if (!previewStats || typeof previewStats !== "object") {
    return;
  }
  const bendLineCount = previewStats.bendLineCount;
  if (typeof bendLineCount === "number" && Number.isFinite(bendLineCount)) {
    entry.bendLineCount = Math.trunc(bendLineCount);
  }
  const axes = previewStats.bendAxisX;
  if (Array.isArray(axes) && axes.length) {
    entry.bendAxisX = axes.map((v) => Number(v));
  }
}

function applyDrawingProfile(entry, packageDir) {
  // Distinguishes "a dimensioned document, with nothing to bake" from "a cut
  // layout whose flat pattern has not been built yet" (issue #246).
  const profile = String(readDrawingCatalogMetadata(packageDir).profile || "").trim();
  if (profile) {
    entry.drawingProfile = profile;
  }
}

function applyDrawingGeometryRelation(entry, repoRoot, packageDir) {
  const descriptor = readDrawingCatalogMetadata(packageDir);
  const geometryRef = String(descriptor.geometry || "").trim();
  const geometryPath = geometryRef ? path.join(packageDir, geometryRef) : "";
  const stats = geometryPath ? fileStats(geometryPath) : null;
  if (!stats) {
    return;
  }
  const version = fileVersion(stats);
  const baseUrl = assetUrlForPath(repoRoot, geometryPath);
  const separator = baseUrl.includes("?") ? "&" : "?";
  entry.relations = entry.relations || {};
  entry.relations.drawingGeometry = {
    file: geometryPath,
    url: `${baseUrl}${separator}v=${encodeURIComponent(version)}`,
    bytes: Number(stats.size),
  };
}

function createSingleAssetEntry(repoRoot, rootPath, sourcePath, extension) {
  const kind = sourceFormatForPath(sourcePath, extension);
  const asset = assetForPath(repoRoot, sourcePath);
  const entry = {
    file: repoRelativePath(rootPath, sourcePath),
    kind,
    url: (asset && asset.url) || assetUrlForPath(repoRoot, sourcePath),
    hash: (asset && asset.hash) || "",
    bytes: (asset && asset.bytes) || 0,
  };
  const glbRelation = renderPackageGlbRelation(repoRoot, rootPath, sourcePath, kind);
  if (glbRelation) {
    entry.relations = entry.relations || {};
    entry.relations.glb = glbRelation;
  }
  if (kind === "dxf") {
    const packageDir = renderPackageAssetDir(sourcePath);
    applyDrawingPreviewStats(entry, packageDir);
    applyDrawingProfile(entry, packageDir);
    applyDrawingGeometryRelation(entry, repoRoot, packageDir);
  }
  if (kind === "srdf") {
    const pairedUrdf = pairedUrdfPathForSrdf(sourcePath);
    if (pairedUrdf) {
      const urdfAsset = assetForPath(repoRoot, pairedUrdf);
      if (urdfAsset) {
        entry.relations = { urdf: { file: repoRelativePath(rootPath, pairedUrdf), ...urdfAsset } };
      }
    }
  }
  return entry;
}

function createGeneratedDxfEntry(repoRoot, rootPath, sourcePath) {
  // A generated drawing has NO static DXF asset — nothing is committed and the
  // package caches only what it renders. Its identity is its source hash.
  const packageDir = renderPackageAssetDir(sourcePath);
  const descriptor = readDrawingCatalogMetadata(packageDir);
  const entryRef = repoRelativePath(rootPath, sourcePath);
  const contentHash = String(descriptor.sourceHash || "").trim();
  const entry = {
    file: entryRef,
    kind: "dxf",
    url: "",
    hash: contentHash,
    bytes: 0,
    sourceKind: "python",
  };
  applyDrawingPreviewStats(entry, packageDir);
  applyDrawingProfile(entry, packageDir);
  applyDrawingGeometryRelation(entry, repoRoot, packageDir);
  const glbRelation = renderPackageGlbRelation(repoRoot, rootPath, sourcePath, "dxf");
  if (glbRelation) {
    entry.relations = entry.relations || {};
    entry.relations.glb = glbRelation;
  }
  const source = { file: entryRef, sourcePath: entryRef };
  if (contentHash) {
    source.sourceHash = contentHash;
  }
  entry.source = source;
  return entry;
}

export function stepKindFromTopology(topology) {
  if (!topology) {
    return "part";
  }
  const index = topology.index && typeof topology.index === "object" ? topology.index : topology;
  if (topology.entryKind === "assembly" || (index && index.entryKind === "assembly")) {
    return "assembly";
  }
  const assembly = index && typeof index === "object" ? index.assembly : null;
  if (assembly && typeof assembly === "object" && assembly.root && typeof assembly.root === "object") {
    return "assembly";
  }
  return "part";
}

export function readStepCatalogMetadata(packageDir) {
  // Component package: assembly.json IS the index manifest.
  if (!packageDescriptorStats(packageDir)) {
    return {};
  }
  let descriptor;
  try {
    descriptor = JSON.parse(fs.readFileSync(path.join(packageDir, "assembly.json"), "utf8"));
  } catch {
    return {};
  }
  if (!descriptor || descriptor.kind !== "assembly-package") {
    return {};
  }
  const sourceKind = String(descriptor.sourceKind ?? "step").trim().toLowerCase() === "python" ? "python" : "step";
  return {
    topology: {
      index: descriptor,
      entryKind: String(descriptor.entryKind ?? "").trim().toLowerCase(),
      hasSelector: false,
      hasDisplayEdges: false,
    },
    sourceKind,
    sourceHash: String(descriptor.sourceHash ?? ""),
    stepHash: String(descriptor.stepHash ?? ""),
  };
}

function createStepEntry(repoRoot, rootPath, sourcePath, extension) {
  const entryIsPython = sourcePath.toLowerCase().endsWith(".py");
  const packageDir = renderPackageDir(sourcePath);
  const metadata = readStepCatalogMetadata(packageDir);
  const topology = metadata.topology;
  const packageAsset = assetForPath(repoRoot, packageDir);
  const topologyIndex = topology && topology.index && typeof topology.index === "object" ? topology.index : topology;
  const paramsPathRel = String((topologyIndex && topologyIndex.paramsPath) || "").trim();
  let stepModuleAsset = paramsPathRel
    ? assetForPath(repoRoot, path.resolve(path.dirname(sourcePath), paramsPathRel))
    : null;
  const entryRef = repoRelativePath(rootPath, sourcePath);
  const sourceHash = String(metadata.sourceHash || "").trim();
  const entry = {
    file: entryRef,
    kind: stepKindFromTopology(topology),
    url: (packageAsset && packageAsset.url) || assetUrlForPath(repoRoot, packageDir),
    hash: (packageAsset && packageAsset.hash) || "",
    bytes: (packageAsset && packageAsset.bytes) || 0,
    sourceKind: entryIsPython ? "python" : "step",
  };
  if (entryIsPython) {
    const source = { file: entryRef, sourcePath: entryRef };
    if (sourceHash) {
      source.sourceHash = sourceHash;
    }
    entry.source = source;
  }
  if (!entryIsPython && !stepModuleAsset) {
    // Imported STEP: no descriptor to declare a module, so look beside it.
    const sidecarPath = stepSidecarPath(sourcePath);
    if (fileStats(sidecarPath)) {
      stepModuleAsset = assetForPath(repoRoot, sidecarPath);
    }
  }
  if (stepModuleAsset) {
    entry.moduleUrl = stepModuleAsset.url;
  }
  return entry;
}

// --- viewer-only sidecar for imported STEP files ---
// An imported `.step`/`.stp` has no generator to declare a parameter/animation
// module, so the viewer also accepts `<name>.step.js` sitting beside it.
export const STEP_SIDECAR_SUFFIX = ".js";

export function stepSidecarPath(stepPath) {
  return `${stepPath}${STEP_SIDECAR_SUFFIX}`;
}

export function isStepSidecarPath(filePath) {
  const lowered = String(filePath || "").toLowerCase();
  if (!(lowered.endsWith(".step.js") || lowered.endsWith(".stp.js"))) {
    return false;
  }
  return Boolean(fileStats(filePath.slice(0, -STEP_SIDECAR_SUFFIX.length)));
}

// --- served-asset gate (security: which on-disk files /__cad/asset may serve) ---
function isDeclaredParamsSidecar(filePath) {
  const modelDir = path.dirname(filePath);
  const resolved = path.resolve(filePath);
  const packagesDir = path.join(modelDir, CADGEN_DIRNAME, CADGEN_MODELS_DIRNAME);
  let names;
  try {
    names = fs.readdirSync(packagesDir);
  } catch {
    return false;
  }
  for (const name of names) {
    const packageDir = path.join(packagesDir, name);
    let isDir = false;
    try {
      isDir = fs.statSync(packageDir).isDirectory();
    } catch {
      continue;
    }
    if (!isDir) {
      continue;
    }
    let descriptor;
    try {
      descriptor = JSON.parse(fs.readFileSync(path.join(packageDir, "assembly.json"), "utf8"));
    } catch {
      continue;
    }
    const paramsPath = String((descriptor && descriptor.paramsPath) || "").trim();
    if (paramsPath && path.resolve(modelDir, paramsPath) === resolved) {
      return true;
    }
  }
  return false;
}

export function isServedCadAsset(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  if (isHiddenName(path.basename(filePath))) {
    // Hidden (dot-prefixed) files are never served: generation locks, temp files.
    // Hidden directory components below the served root are rejected by the
    // backend, which knows the root; the basename check here stays root-agnostic
    // so a model root that itself lives under a hidden path still serves.
    return false;
  }
  if (isInsideCadgenDir(filePath)) {
    return true;
  }
  if ((extension === ".js" || extension === ".mjs") && (isDeclaredParamsSidecar(filePath) || isStepSidecarPath(filePath))) {
    return true;
  }
  if (SOURCE_EXTENSIONS.has(extension) || pathIsImplicitCadSource(filePath)) {
    return true;
  }
  return false;
}

// --- catalog sort (natural order, case-insensitive, numeric runs as integers) ---
export function sortCatalogEntries(entries) {
  return [...entries].sort((a, b) =>
    String(a.file || "").localeCompare(String(b.file || ""), undefined, { numeric: true, sensitivity: "base" }),
  );
}

// --- public scan API ---
export function scanCadDirectory(repoRoot) {
  // Scan one directory. It is its own root — a viewer serves exactly one, fixed
  // at startup.
  if (!repoRoot) {
    throw new Error("repoRoot is required");
  }
  const rootPath = path.resolve(repoRoot);
  const sourceFiles = collectCadSourceFiles(rootPath, []);
  const entries = [];
  for (const sourcePath of sourceFiles) {
    const logical = isRenderPackagePath(sourcePath) ? entryPathForRenderPackage(sourcePath) : sourcePath;
    const extension = path.extname(logical).toLowerCase();
    if (isDxfGeneratorPath(logical)) {
      entries.push(createGeneratedDxfEntry(repoRoot, rootPath, logical));
    } else if (extension === ".step" || extension === ".stp" || logical.toLowerCase().endsWith(".step.py")) {
      entries.push(createStepEntry(repoRoot, rootPath, logical, extension));
    } else {
      entries.push(createSingleAssetEntry(repoRoot, rootPath, sourcePath, extension));
    }
  }
  return { schemaVersion: CAD_CATALOG_SCHEMA_VERSION, entries: sortCatalogEntries(entries) };
}
