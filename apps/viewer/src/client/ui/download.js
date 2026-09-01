// Screenshot capture only: the viewer saves canvas blobs the client itself
// produced. Artifact bytes are never downloaded through a URL — copy actions
// hand out paths from the catalog instead.
const DOWNLOAD_BLOCKED_MESSAGE = "Download was blocked by the browser";

function normalizeFilename(value) {
  return String(value || "").trim();
}

function downloadRequestedMessage(filename) {
  const normalizedFilename = normalizeFilename(filename);
  return normalizedFilename ? `Downloading ${normalizedFilename}` : "Downloading file";
}

function getDownloadDocument() {
  const doc = globalThis.document;
  if (!doc || typeof doc.createElement !== "function") {
    throw new Error("Downloads are not available in this browser");
  }
  return doc;
}

function clickDownloadLink(link) {
  if (typeof link.click !== "function") {
    throw new Error("Downloads are not available in this browser");
  }

  try {
    link.click();
  } catch (error) {
    throw error instanceof Error ? error : new Error(DOWNLOAD_BLOCKED_MESSAGE);
  }
}

function clickTemporaryLink(href, filename) {
  const doc = getDownloadDocument();
  const link = doc.createElement("a");
  link.href = href;
  link.rel = "noopener";
  const normalizedFilename = normalizeFilename(filename);
  if (normalizedFilename) {
    link.download = normalizedFilename;
  }
  if (link.style) {
    link.style.display = "none";
  }

  doc.body?.appendChild?.(link);
  try {
    clickDownloadLink(link);
  } finally {
    doc.body?.removeChild?.(link);
  }

  return {
    filename: normalizedFilename,
    message: downloadRequestedMessage(normalizedFilename),
    status: "requested"
  };
}

export function triggerBlobDownload(blob, { filename = "" } = {}) {
  if (!blob || typeof blob !== "object") {
    throw new Error("No download data is available");
  }
  const urlApi = globalThis.URL;
  if (typeof urlApi?.createObjectURL !== "function") {
    throw new Error("Downloads are not available in this browser");
  }

  const downloadUrl = urlApi.createObjectURL(blob);
  try {
    return clickTemporaryLink(downloadUrl, filename);
  } finally {
    const revoke = () => {
      urlApi.revokeObjectURL?.(downloadUrl);
    };
    if (typeof globalThis.setTimeout === "function") {
      globalThis.setTimeout(revoke, 1000);
    } else {
      revoke();
    }
  }
}
