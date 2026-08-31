// URL/header encoders the client contract is pinned to. These are the native JS
// semantics the Python backend had to port byte-for-byte (its tests/golden.json
// was generated from exactly these expressions); here they are simply the language.
import path from "node:path";

// ?v= cache token: base36(size)-base36(mtimeNs). BigInt because mtimeNs ~ 1e18.
export function fileVersion(stats) {
  return `${BigInt(stats.size).toString(36)}-${stats.mtimeNs.toString(36)}`;
}

// /__cad/asset?file=<ABS>&v=<token> with URLSearchParams form encoding, `v`
// omitted when empty. The client rewrites ONLY the `file` param
// (packageAssetUrl.js), so the shape must stay exactly this.
export function localAssetUrlForPath(filePath, version = "") {
  const params = new URLSearchParams();
  params.set("file", path.resolve(String(filePath || "")));
  const normalized = String(version || "").trim();
  if (normalized) {
    params.set("v", normalized);
  }
  return `/__cad/asset?${params.toString()}`;
}

export function encodeContentDispositionFilename(value) {
  // encodeURIComponent then additionally percent-escape '()* (RFC5987 tightening).
  return encodeURIComponent(value).replace(/['()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
}

export function downloadFilename(value) {
  const normalized = String(value || "").replace(/\\/g, "/");
  const base = path.posix.basename(normalized) || "download";
  return base.replace(/[\x00-\x1f"\\]/g, "_");
}

export function attachmentContentDisposition(filename) {
  const safe = downloadFilename(filename);
  const quoted = safe.replace(/[^\x20-\x7e]/g, "_");
  const star = encodeContentDispositionFilename(safe);
  return `attachment; filename="${quoted}"; filename*=UTF-8''${star}`;
}

// Match JS decodeURIComponent strictness for incoming URL paths: it throws on a
// malformed percent escape, and the caller maps that to a 400 rather than a crash.
export function strictDecodeUriComponent(value) {
  return decodeURIComponent(value);
}
