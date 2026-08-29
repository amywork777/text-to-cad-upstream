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
import { SOURCE_SIDECAR_SUFFIX } from "./packageContract.mjs";
import { renderPackageDir as storeRenderPackageDir, storePackagesDir } from "./storePaths.mjs";

export const CAD_CATALOG_SCHEMA_VERSION = 4;

export const SOURCE_EXTENSIONS = new Set([
  ".step", ".stp", ".stl", ".3mf", ".glb", ".dxf", ".urdf", ".srdf", ".sdf",
]);
// Dot-prefixed (hidden) directories are skipped generically; this set only
// needs the non-hidden names.
const VIEWER_SKIPPED_DIRECTORIES = new Set([
  "__cadgen__", "__pycache__", "build", "coverage", "dist", "node_modules", "viewer",
]);

export const DXF_GENERATOR_SUFFIX = ".dxf.py";

export function isDxfGeneratorPath(filePath) {
  return String(filePath || "").toLowerCase().endsWith(DXF_GENERATOR_SUFFIX);
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

// Store-primary resolution: packages live in the user-level store keyed by
// the document's content hash (storePaths.mjs mirrors cadgen.catalog).
export { renderPackageDir } from "./storePaths.mjs";

export function sourceSidecarPath(entryPath) {
  return `${path.resolve(entryPath)}${SOURCE_SIDECAR_SUFFIX}`;
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
  // Real paths exist here for ALIAS EQUALITY, never refusal (ports the settled
  // semantics of develop's 9bc6bd44 + b0f59af3): macOS's /var -> /private/var
  // and symlinked served roots must compare as inside, so a path is contained
  // when EITHER its lexical or its resolved location stays inside the root.
  // Symlinked model directories are a feature — this repo's own dev layout is
  // symlinks, and pointing a link at a shared parts library outside the folder
  // is a normal way to bring external content in. A link out of the served
  // directory grants no reach the URL did not already grant: the viewer serves
  // any absolute directory named at startup.
  if (relativePathStaysInsideRoot(path.relative(path.resolve(rootPath), path.resolve(filePath)))) {
    return true;
  }
  return relativePathStaysInsideRoot(path.relative(realpathOr(path.resolve(rootPath)), realpathOr(path.resolve(filePath))));
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

// Package assets are served by the /__cad/store route, whose `file` param is
// relative to the store's packages/ tier. The client's resolvePackageAssetUrl
// rewrites the same param for sub-assets, so the URL shape matches root assets.
function storeAssetUrl(packageDir, descriptorStats) {
  const rel = path.relative(storePackagesDir(), packageDir).split(path.sep).join("/");
  const base = `/__cad/store?file=${encodeURIComponent(rel)}`;
  return descriptorStats ? `${base}&v=${encodeURIComponent(fileVersion(descriptorStats))}` : base;
}

function packageDescriptorStats(packageDir) {
  return fileStats(path.join(packageDir, "assembly.json"));
}

export function assetForPath(repoRoot, filePath) {
  const st = fileStats(filePath);
  if (!st) {
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
  return sourceFormatFromExtension(ext);
}

// --- directory scan helpers ---
export function isHiddenName(name) {
  return String(name || "").startsWith(".");
}

function shouldSkipDirectory(name) {
  return VIEWER_SKIPPED_DIRECTORIES.has(name) || isHiddenName(name);
}

// Depth cap: far beyond what a real layout reaches, and enough to stop a
// symlink-loop crash even if the visited-real-path tracking ever fails to see
// one (mirrors develop's scanner guard).
const SCAN_MAX_DEPTH = 64;

function collectCadSourceFiles(rootPath, result, visited = null, depth = 0) {
  // Directory symlinks are followed ON PURPOSE (ports b0f59af3 + 9bc6bd44's
  // scanner semantics from develop): a symlinked model folder — this repo's
  // own dev layout, or a link to a shared parts library — must catalog like a
  // real directory. Dirent.isDirectory() is false for links, so resolve link
  // targets with stat. Visited REAL directory paths terminate loops (`ln -s .
  // loop`) and aliases; the depth cap is the outer guard. Walk order stays
  // deterministic (sorted).
  if (depth > SCAN_MAX_DEPTH) {
    return result;
  }
  let realRoot;
  try {
    realRoot = fs.realpathSync(rootPath);
  } catch {
    return result;
  }
  if (visited === null) {
    visited = new Set();
  }
  if (visited.has(realRoot)) {
    return result;
  }
  visited.add(realRoot);
  let entries;
  try {
    entries = fs.readdirSync(rootPath, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  } catch {
    return result;
  }
  for (const entry of entries) {
    const entryPath = path.join(rootPath, entry.name);
    let isDirectory = entry.isDirectory();
    let isFile = entry.isFile();
    if (entry.isSymbolicLink()) {
      try {
        const stat = fs.statSync(entryPath);
        isDirectory = stat.isDirectory();
        isFile = stat.isFile();
      } catch {
        continue; // broken link
      }
    }
    if (isDirectory) {
      if (!shouldSkipDirectory(entry.name)) {
        collectCadSourceFiles(entryPath, result, visited, depth + 1);
      }
      continue;
    }
    if (!isFile) {
      continue;
    }
    if (isHiddenName(entry.name)) {
      continue;
    }
    const extension = path.extname(entry.name).toLowerCase();
    // ARTIFACTS-ONLY (design/library-first-generation.md): model scripts are
    // never catalog entries. A model with no artifact simply does not appear
    // until its script has been run; artifact→source linkage is descriptor
    // provenance, not filenames.
    if (SOURCE_EXTENSIONS.has(extension)) {
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

// --- entry builders ---
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

export function readStepCatalogMetadata(packageDir, sourcePath = null) {
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
  // Everything SOURCE-derived rides the model-side sidecar
  // (<name>.step.source.json); its existence is the generated-vs-imported
  // marker. The store descriptor is STEP-pure.
  let sidecar = null;
  if (sourcePath) {
    try {
      const parsed = JSON.parse(fs.readFileSync(sourceSidecarPath(sourcePath), "utf8"));
      sidecar = parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      sidecar = null;
    }
  }
  return {
    topology: {
      index: descriptor,
      entryKind: String(descriptor.entryKind ?? "").trim().toLowerCase(),
      hasSelector: false,
      hasDisplayEdges: false,
    },
    sourceKind: sidecar ? "python" : "step",
    sourcePath: String(sidecar?.sourcePath ?? ""),
    sourceHash: String(sidecar?.sourceHash ?? ""),
    stepHash: String(descriptor.stepHash ?? ""),
    pose: sidecar && typeof sidecar.pose === "object" && sidecar.pose ? sidecar.pose : null,
  };
}

function createStepEntry(repoRoot, rootPath, sourcePath, extension) {
  // Catalog entries are ARTIFACTS (the .step/.stp file); whether the model is
  // python-backed comes from the package descriptor's provenance, never from
  // sibling filenames (design/library-first-generation.md).
  const packageDir = storeRenderPackageDir(sourcePath);
  const metadata = readStepCatalogMetadata(packageDir, sourcePath);
  const topology = metadata.topology;
  const descriptorStats = packageDescriptorStats(packageDir);
  const topologyIndex = topology && topology.index && typeof topology.index === "object" ? topology.index : topology;
  const poseBlock = metadata.pose || null;
  const entryRef = repoRelativePath(rootPath, sourcePath);
  const sourceHash = String(metadata.sourceHash || "").trim();
  const generated = metadata.sourceKind === "python";
  const entry = {
    file: entryRef,
    kind: stepKindFromTopology(topology),
    url: storeAssetUrl(packageDir, descriptorStats),
    hash: descriptorStats ? sha256File(path.join(packageDir, "assembly.json"), descriptorStats) : "",
    bytes: descriptorStats ? Number(descriptorStats.size) : 0,
    sourceKind: generated ? "python" : "step",
  };
  if (generated) {
    // sourcePath is recorded relative to the STEP file by generation.
    const sourcePathRel = String(metadata.sourcePath || "").trim();
    const resolvedSource = sourcePathRel
      ? path.resolve(path.dirname(sourcePath), sourcePathRel)
      : null;
    if (resolvedSource && fileStats(resolvedSource)) {
      const source = {
        file: repoRelativePath(rootPath, resolvedSource),
        sourcePath: repoRelativePath(rootPath, resolvedSource),
      };
      if (sourceHash) {
        source.sourceHash = sourceHash;
      }
      entry.source = source;
    }
  }
  if (generated) {
    // The model-side sidecar (served by the ordinary asset route — it lives
    // in the root) carries mates and pose; the client merge point fetches it.
    entry.sourceUrl = assetUrlForPath(repoRoot, sourceSidecarPath(sourcePath));
  }
  if (poseBlock) {
    // Declarative pose (the ONLY pose mechanism): the client fetches the
    // source sidecar and compiles its pose block; the optional escape-hatch
    // module rides INLINE in the sidecar (pose.moduleSource).
    entry.poseUrl = entry.sourceUrl || assetUrlForPath(repoRoot, sourceSidecarPath(sourcePath));
  } else if (
    String((topologyIndex && topologyIndex.paramsPath) || "").trim() ||
    fileStats(legacyParamsSidecarPath(sourcePath))
  ) {
    // Retired mechanism, teaching note: a .params.js sidecar (or an old
    // descriptor still recording one) is ignored — pose data has exactly one
    // authoring surface now. The client surfaces this on the params panel.
    entry.legacyParamsSidecar = true;
  }
  return entry;
}

// The retired sidecar convention, detected only to TEACH (never loaded).
export function legacyParamsSidecarPath(stepPath) {
  const parsed = path.parse(String(stepPath || ""));
  return path.join(parsed.dir, `${parsed.name}.params.js`);
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
  if (filePath.endsWith(SOURCE_SIDECAR_SUFFIX)) {
    // The model-side source sidecar (<name>.step.source.json): pose + mates
    // for the client. Loose .js sidecars beside models are NOT served —
    // the .params.js mechanism is retired.
    return true;
  }
  if (SOURCE_EXTENSIONS.has(extension)) {
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
    const logical = sourcePath;
    const extension = path.extname(logical).toLowerCase();
    if (extension === ".step" || extension === ".stp") {
      entries.push(createStepEntry(repoRoot, rootPath, logical, extension));
    } else {
      entries.push(createSingleAssetEntry(repoRoot, rootPath, sourcePath, extension));
    }
  }
  return { schemaVersion: CAD_CATALOG_SCHEMA_VERSION, entries: sortCatalogEntries(entries) };
}
