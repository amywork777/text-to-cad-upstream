// The /__cad/* HTTP contract, framework-free. One handler serves both runtimes:
// the standalone server (main.mjs, which adds static dist/SPA serving behind it)
// and the Vite dev middleware (which lets everything non-/__cad fall through to
// Vite). `handle(req, res)` resolves true when it wrote a response.
//
// Security / trust model: binds loopback and serves UNAUTHENTICATED — the
// loopback bind is the trust boundary against other processes and machines.
// Loopback is NOT a boundary against the user's own browser, so two gates
// defend against that specifically:
//
// * Host validation refuses a request whose Host names anything but
//   127.0.0.1/localhost/::1 — the DNS-rebinding case, where an attacker domain
//   re-resolves to loopback and the browser treats us as same-origin. Skipped
//   when bound non-loopback, matching Jupyter's allow_remote_access.
// * Every POST requires an `x-cadgen-viewer` header. POST /__cad/artifact
//   executes the target's generator, and since all params ride in the query
//   string with no body, a cross-origin POST is otherwise a no-preflight
//   "simple request". A custom header forces a preflight instead.
//
// No Access-Control-* headers are served, deliberately: their absence is what
// makes the same-origin policy block cross-origin reads and what makes that
// preflight fail. Do not add them.
import fs from "node:fs";
import path from "node:path";

import { LocalAssetBackend, ForbiddenAssetError, normalizedFileRef } from "./backend.mjs";
import { createCadgenOps } from "./cadgenOps.mjs";
import { contentTypeForStaticAsset } from "./contentTypes.mjs";
import { attachmentContentDisposition } from "./encoding.mjs";
import { pathIsInside, isDxfGeneratorPath, pathIsImplicitCadSource } from "./scanner.mjs";
import { pickSaveDestination } from "./saveDialog.mjs";
import { revealPath } from "./reveal.mjs";

export const POST_GUARD_HEADER = "x-cadgen-viewer";
export const LOCAL_SERVER_FEATURES = ["path-directory"];
const LOOPBACK_NAMES = new Set(["127.0.0.1", "localhost", "::1"]);

const STEP_EXPORT_FORMATS = new Set(["step", "stl", "3mf", "glb"]);
const IMPLICIT_EXPORT_FORMATS = new Set(["stl", "glb", "3mf"]);

export function hostnameOnly(hostHeader) {
  const value = String(hostHeader || "").trim();
  if (value.startsWith("[")) {
    const end = value.indexOf("]");
    return (end !== -1 ? value.slice(1, end) : value).toLowerCase();
  }
  const idx = value.lastIndexOf(":");
  if (idx !== -1 && /^\d+$/.test(value.slice(idx + 1))) {
    return value.slice(0, idx).toLowerCase();
  }
  return value.toLowerCase();
}

export function hostIsAllowed(hostHeader, boundHost) {
  // DNS-rebinding defense. The NAME is compared, never the port: the attack
  // requires a non-local name, and ignoring the port keeps odd-port instances
  // and the Vite dev middleware working. Skipped when the operator bound a
  // non-loopback interface — they have deliberately left the loopback trust
  // model. An absent Host header is allowed: HTTP/1.0 clients omit it, and the
  // browser (the threat this exists for) always sends it.
  if (!LOOPBACK_NAMES.has(hostnameOnly(boundHost))) {
    return true;
  }
  if (!String(hostHeader || "").trim()) {
    return true;
  }
  return LOOPBACK_NAMES.has(hostnameOnly(hostHeader));
}

function readViewerVersion() {
  try {
    const packageJson = JSON.parse(
      fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"),
    );
    return String(packageJson.version || "");
  } catch {
    return "";
  }
}

export function createCadApp({ root, host, port, distDir = "" }) {
  const backend = new LocalAssetBackend(root);
  const rootPath = backend.resolveRoot().rootPath;
  const ops = createCadgenOps(rootPath);
  const viewerVersion = readViewerVersion();
  const startedAt = Date.now() / 1000;

  // Lazily resolved, never blocking startup: until the probe lands the server
  // reports generation as available (the client's gate is `!== false`), then the
  // truth once known.
  let generationAvailable = true;
  ops.probe().then((result) => {
    generationAvailable = Boolean(result.ok);
  });

  function serverInfo() {
    return {
      app: "cad-viewer",
      viewerVersion,
      serverMode: "serve",
      serverFeatures: LOCAL_SERVER_FEATURES,
      backend: "local-fs",
      rootPath,
      rootName: backend.resolveRoot().rootName,
      port,
      pid: process.pid,
      stepArtifactGenerationAvailable: generationAvailable !== false,
      packageDir: path.dirname(new URL(import.meta.url).pathname),
      startedAt,
      url: `http://${host}:${port}`,
    };
  }

  function sendJson(req, res, status, payload) {
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    res.writeHead(status, {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "content-length": body.length,
    });
    res.end(req.method === "HEAD" ? undefined : body);
  }

  function sendBytes(req, res, status, data, contentType, { disposition = null } = {}) {
    const headers = { "cache-control": "no-store", "content-length": data.length };
    if (contentType) {
      headers["content-type"] = contentType;
    }
    if (disposition) {
      headers["content-disposition"] = disposition;
    }
    res.writeHead(status, headers);
    res.end(req.method === "HEAD" ? undefined : data);
  }

  function serveFile(req, res, filePath, contentType) {
    let data;
    try {
      if (!fs.statSync(filePath).isFile()) {
        return false;
      }
      data = fs.readFileSync(filePath);
    } catch {
      return false;
    }
    sendBytes(req, res, 200, data, contentType || "");
    return true;
  }

  function rejectedByHostCheck(req, res) {
    const hostHeader = req.headers.host || "";
    if (hostIsAllowed(hostHeader, host)) {
      return false;
    }
    sendJson(req, res, 403, {
      error: `Host header '${hostnameOnly(hostHeader)}' is not a local name; refusing (DNS-rebinding defense)`,
    });
    return true;
  }

  function rejectedAsCrossSitePost(req, res) {
    if (req.headers[POST_GUARD_HEADER]) {
      return false;
    }
    sendJson(req, res, 403, {
      error: `missing ${POST_GUARD_HEADER} header (cross-site POST blocked); send '${POST_GUARD_HEADER}: 1'`,
    });
    return true;
  }

  function serveAsset(req, res, query, { download }) {
    const candidate = backend.assetPathForFileRef(query.get("file") || "");
    if (!candidate || !fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) {
      sendJson(req, res, 404, { error: "Not found" });
      return;
    }
    const data = fs.readFileSync(candidate);
    const contentType = backend.contentTypeForPath(candidate) || "application/octet-stream";
    const disposition = download ? attachmentContentDisposition(path.basename(candidate)) : null;
    sendBytes(req, res, 200, data, contentType, { disposition });
  }

  function refererFileRef(req) {
    const value = req.headers.referer || req.headers.referrer || "";
    if (!value) {
      return "";
    }
    try {
      const url = new URL(value.includes("://") ? value : `http://localhost${value}`);
      return (url.searchParams.get("file") || "").trim();
    } catch {
      return "";
    }
  }

  function siblingFileRef(sourceFileRef, relativeFileRef) {
    const source = String(sourceFileRef || "").replace(/\\/g, "/");
    const relative = String(relativeFileRef || "").replace(/\\/g, "/").replace(/^\/+/, "");
    if (!source || !relative) {
      return "";
    }
    if (path.isAbsolute(source)) {
      return path.normalize(path.join(path.dirname(source), relative));
    }
    const sourceDir = path.posix.dirname(source);
    return path.posix.normalize(path.posix.join(sourceDir === "." ? "" : sourceDir, relative));
  }

  // GET /__cad/<rel>.<ext>: a sibling-of-Referer asset request (relative package
  // assets like URDF meshes / ../components). Returns true if it handled the
  // response (served or 403), false to fall through.
  function legacyCadAsset(req, res, pathname) {
    if (!pathname.startsWith("/__cad/") || pathname === "/__cad/asset") {
      return false;
    }
    let relativePath;
    try {
      relativePath = decodeURIComponent(pathname.slice("/__cad/".length));
    } catch {
      return false;
    }
    if (!relativePath || !path.extname(relativePath)) {
      return false;
    }
    const fileRef = siblingFileRef(refererFileRef(req), relativePath);
    if (!fileRef) {
      return false;
    }
    let candidate;
    try {
      candidate = backend.assetPathForFileRef(fileRef);
    } catch (error) {
      if (error instanceof ForbiddenAssetError) {
        sendBytes(req, res, 403, Buffer.from("Forbidden"), "");
        return true;
      }
      throw error;
    }
    if (!candidate) {
      return false;
    }
    return serveFile(req, res, candidate, backend.contentTypeForPath(candidate) || "");
  }

  function entryRefForStatus(fileRef) {
    const catalog = backend.readCatalog();
    const entry = backend.catalogEntryForFileRef(catalog, fileRef);
    return { catalog, ref: String((entry && entry.url) || "") };
  }

  async function handleArtifactStatus(req, res, query) {
    const fileRef = query.get("file") || "";
    const { ref } = entryRefForStatus(fileRef);
    const status = await ops.artifactStatus(fileRef);
    sendJson(req, res, 200, { ...status, ref });
  }

  async function handleArtifactBuild(req, res, query) {
    const fileRef = query.get("file") || "";
    const { ref } = entryRefForStatus(fileRef);
    const result = await ops.buildArtifact(fileRef, { force: (query.get("force") || "") === "1" });
    // Refresh the catalog AFTER the build (even on failure) and attach it: the
    // client republishes it, folding the build's new package into the store.
    const nextCatalog = backend.readCatalog();
    const status = result.ok === false ? 500 : 200;
    sendJson(req, res, status, { ...result, ref, catalog: nextCatalog });
  }

  // Export destination naming, per format. The Python op re-validates format and
  // containment; this only derives names for the dialog and the fallback path.
  function exportNaming(fileRef, format) {
    const normalized = normalizedFileRef(fileRef);
    const abs = path.isAbsolute(normalized) ? normalized : path.resolve(rootPath, normalized);
    if (isDxfGeneratorPath(abs)) {
      if (format !== "dxf") {
        throw new Error(`Unsupported export format for a DXF drawing: ${format}`);
      }
      const base = path.basename(abs).slice(0, -".dxf.py".length);
      return { baseName: base, suggestedName: `${base}.dxf`, defaultDir: path.dirname(abs) };
    }
    if (pathIsImplicitCadSource(abs)) {
      if (!IMPLICIT_EXPORT_FORMATS.has(format)) {
        throw new Error(`Unsupported implicit CAD export format: ${format || "(missing)"}`);
      }
      const base = path.basename(abs).replace(/\.implicit\.(mjs|js)$/i, "");
      return { baseName: base, suggestedName: `${base}.${format}`, defaultDir: path.dirname(abs) };
    }
    if (!STEP_EXPORT_FORMATS.has(format)) {
      throw new Error(`Unsupported export format: ${format}`);
    }
    // A `.step.py` generator exports through its logical STEP sibling's name.
    const stepPath = abs.toLowerCase().endsWith(".py") ? abs.slice(0, -3) : abs;
    const base = path.basename(stepPath).replace(/\.(step|stp)$/i, "");
    return { baseName: base, suggestedName: `${base}.${format}`, defaultDir: path.dirname(stepPath) };
  }

  async function handleExport(req, res, query) {
    const fileRef = query.get("file") || "";
    const format = String(query.get("format") || "step").trim().toLowerCase();
    const naming = exportNaming(fileRef, format);
    const destination = pickSaveDestination({
      suggestedName: naming.suggestedName,
      defaultDir: naming.defaultDir,
      prompt: `Export ${naming.baseName} as ${format.toUpperCase()}`,
    });
    if (destination.cancelled) {
      sendJson(req, res, 200, { ok: false, cancelled: true });
      return;
    }
    if (destination.path) {
      const result = await ops.generateExport(fileRef, format, path.resolve(destination.path));
      if (!result.ok) {
        sendJson(req, res, 400, { ok: false, error: String(result.error || "Export failed") });
        return;
      }
      const outPath = path.resolve(result.path || destination.path);
      const inside = outPath === rootPath || pathIsInside(outPath, rootPath);
      const payload = {
        ok: true,
        path: outPath,
        filename: result.filename || path.basename(outPath),
        format,
      };
      if (inside) {
        payload.catalogChanged = true;
      }
      sendJson(req, res, 200, payload);
      return;
    }
    // Headless fallback: write beside the source, hand to the browser via
    // /__cad/download.
    const outputPath = path.join(naming.defaultDir, naming.suggestedName);
    if (!(outputPath === rootPath || pathIsInside(outputPath, rootPath))) {
      throw new Error("Requested file is outside the active CAD Viewer root");
    }
    const result = await ops.generateExport(fileRef, format, outputPath);
    if (!result.ok) {
      sendJson(req, res, 400, { ok: false, error: String(result.error || "Export failed") });
      return;
    }
    const outputFileRef = path.relative(rootPath, outputPath).split(path.sep).join("/");
    const params = new URLSearchParams([["file", outputFileRef], ["asset", "output"]]);
    sendJson(req, res, 200, {
      ok: true,
      fallback: true,
      path: outputPath,
      filename: path.basename(outputPath),
      format,
      catalogChanged: true,
      downloadUrl: `/__cad/download?${params.toString()}`,
    });
  }

  function handleReveal(req, res, query) {
    // Resolves through the same containment as every other asset route; being a
    // POST it sits behind the cross-site header gate — which matters more here
    // than elsewhere, since it spawns a process.
    const fileRef = query.get("file") || "";
    let target = backend.containedPathForFileRef(fileRef);
    if (target && String(query.get("asset") || "output").trim() === "source") {
      const catalog = backend.readCatalog();
      const entry = backend.catalogEntryForFileRef(catalog, fileRef) || {};
      const source = entry.source && typeof entry.source === "object" ? entry.source : {};
      if (source.sourcePath) {
        // Re-resolve rather than trusting the catalog: the same containment must
        // apply to the source path as to the entry itself.
        const sourceTarget = backend.containedPathForFileRef(source.sourcePath);
        if (sourceTarget) {
          target = sourceTarget;
        }
      }
    }
    if (!target || !fs.existsSync(target)) {
      sendJson(req, res, 404, { ok: false, error: "Not found" });
      return;
    }
    const result = revealPath(target);
    if (result.unsupported) {
      sendJson(req, res, 501, { ok: false, error: "Revealing files is not supported here" });
      return;
    }
    if (!result.ok) {
      sendJson(req, res, 500, { ok: false, error: result.error || "Reveal failed" });
      return;
    }
    sendJson(req, res, 200, { ok: true, path: target });
  }

  function sendPlain(req, res, status, text) {
    sendBytes(req, res, status, Buffer.from(text, "utf8"), status === 404 ? "text/plain; charset=utf-8" : "");
  }

  // Static dist + SPA fallback (serve mode; dev serves the client via Vite). The
  // page lives at `/` and nothing else here is a directory, so this is an
  // ordinary static server: serve the file if the bundle has it, otherwise fall
  // through to index.html.
  function serveDist(req, res, pathname) {
    const requestPath = pathname === "/" ? "/index.html" : pathname;
    let decoded;
    try {
      decoded = decodeURIComponent(requestPath);
    } catch {
      sendPlain(req, res, 400, "Bad request");
      return;
    }
    const filePath = path.resolve(distDir, decoded.replace(/^\/+/, ""));
    if (!(filePath === distDir || filePath.startsWith(distDir + path.sep))) {
      sendPlain(req, res, 403, "Forbidden");
      return;
    }
    if (serveFile(req, res, filePath, contentTypeForStaticAsset(filePath))) {
      return;
    }
    if (requestPath.startsWith("/assets/")) {
      sendPlain(req, res, 404, "Not found");
      return;
    }
    const indexHtml = path.join(distDir, "index.html");
    if (!serveFile(req, res, indexHtml, contentTypeForStaticAsset(indexHtml))) {
      sendPlain(req, res, 404, "Not found");
    }
  }

  // Resolves true when a response was written; false means "not mine" (static
  // dist / Vite should take it).
  async function handle(req, res) {
    const method = req.method === "HEAD" ? "GET" : req.method;
    let url;
    try {
      url = new URL(req.url || "/", "http://localhost");
    } catch {
      sendJson(req, res, 400, { error: "Bad request" });
      return true;
    }
    const pathname = url.pathname;
    const query = url.searchParams;

    if (method === "GET") {
      if (rejectedByHostCheck(req, res)) {
        return true;
      }
      if (!pathname.startsWith("/__cad/")) {
        if (!distDir) {
          return false;
        }
        serveDist(req, res, pathname);
        return true;
      }
      try {
        if (pathname === "/__cad/server") {
          sendJson(req, res, 200, serverInfo());
        } else if (pathname === "/__cad/catalog") {
          sendJson(req, res, 200, backend.readCatalog());
        } else if (pathname === "/__cad/artifact") {
          await handleArtifactStatus(req, res, query);
        } else if (pathname === "/__cad/asset") {
          serveAsset(req, res, query, { download: false });
        } else if (pathname === "/__cad/download") {
          serveAsset(req, res, query, { download: true });
        } else if (!legacyCadAsset(req, res, pathname)) {
          if (!distDir) {
            return false;
          }
          serveDist(req, res, pathname);
        }
      } catch (error) {
        if (error instanceof ForbiddenAssetError) {
          sendJson(req, res, 403, { error: "Forbidden" });
        } else {
          sendJson(req, res, 400, { error: String(error && error.message ? error.message : error) });
        }
      }
      return true;
    }

    if (method === "POST") {
      // Gated before dispatch, not per route, so a POST route added later is
      // covered by construction.
      if (rejectedByHostCheck(req, res) || rejectedAsCrossSitePost(req, res)) {
        return true;
      }
      try {
        if (pathname === "/__cad/artifact") {
          await handleArtifactBuild(req, res, query);
        } else if (pathname === "/__cad/export") {
          await handleExport(req, res, query);
        } else if (pathname === "/__cad/reveal") {
          handleReveal(req, res, query);
        } else {
          res.writeHead(405, { allow: "POST", "content-length": 0 });
          res.end();
        }
      } catch (error) {
        if (error instanceof ForbiddenAssetError) {
          sendJson(req, res, 403, { error: "Forbidden" });
        } else {
          sendJson(req, res, 400, { ok: false, error: String(error && error.message ? error.message : error) });
        }
      }
      return true;
    }

    return false;
  }

  return { handle, serverInfo, backend, ops, rootPath };
}
