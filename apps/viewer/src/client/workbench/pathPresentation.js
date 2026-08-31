function cleanText(value) {
  return String(value ?? "").trim();
}

export function normalizeRelativePath(value) {
  return cleanText(value)
    .replace(/\\/g, "/")
    .replace(/^\/+/, "")
    .replace(/\/+$/, "");
}

function normalizePathPrefix(value) {
  return cleanText(value)
    .replace(/\\/g, "/")
    .replace(/\/+$/, "");
}

function stripQueryAndHash(value) {
  return cleanText(value).replace(/[?#].*$/, "");
}

function pathnameFromUrlOrPath(value) {
  const text = cleanText(value);
  if (!text) {
    return "";
  }
  try {
    return new URL(text, "http://cad.local").pathname;
  } catch {
    return stripQueryAndHash(text);
  }
}

function pathRelativeToPrefix(filePath, prefix) {
  const normalizedPath = normalizePathPrefix(filePath);
  const normalizedPrefix = normalizePathPrefix(prefix);
  if (!normalizedPath || !normalizedPrefix) {
    return "";
  }
  if (normalizedPath === normalizedPrefix) {
    return "";
  }
  return normalizedPath.startsWith(`${normalizedPrefix}/`)
    ? normalizedPath.slice(normalizedPrefix.length + 1)
    : "";
}

function suffixFromAnchorDirectory(filePath, anchorFile = "") {
  const normalizedPath = normalizeRelativePath(filePath);
  const normalizedAnchor = normalizeRelativePath(anchorFile);
  if (!normalizedPath || !normalizedAnchor) {
    return normalizedPath;
  }
  const anchorParts = normalizedAnchor.split("/").filter(Boolean);
  anchorParts.pop();
  if (!anchorParts.length) {
    return normalizedPath;
  }
  const anchorDir = anchorParts.join("/");
  const marker = `/${anchorDir}/`;
  const searchable = `/${normalizedPath}`;
  const markerIndex = searchable.lastIndexOf(marker);
  return markerIndex >= 0
    ? searchable.slice(markerIndex + 1)
    : normalizedPath;
}

export function viewerRootRelativePath(value, viewerServerInfo = {}, {
  anchorFile = "",
} = {}) {
  const text = cleanText(value);
  if (!text) {
    return "";
  }

  // One root, so one prefix to try. There used to be a second pass against
  // `directoryRoot` with the per-request `rootDir` stripped back off -- two names for
  // the same directory, reconciled on every path. The server sends `rootPath` alone.
  const rootPathRelative = pathRelativeToPrefix(stripQueryAndHash(text), viewerServerInfo?.rootPath);
  if (rootPathRelative) {
    return normalizeRelativePath(rootPathRelative);
  }

  return suffixFromAnchorDirectory(normalizeRelativePath(pathnameFromUrlOrPath(text)), anchorFile);
}
