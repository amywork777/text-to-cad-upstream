// Pooled client for surfWorker.js.
//
// Unlike the single-worker GLB client this is a POOL: a large assembly has
// hundreds of independent components and tessellation is pure CPU, so the
// wall-clock win scales with cores. Requests round-robin across workers;
// each resolves to { meshData, bundle } for one component URL. Returns null
// from loadSurfComponentInWorker when Workers are unavailable (node, old
// browsers) so callers can fall back to inline tessellation.

let pool = null;
let nextWorkerIndex = 0;
let nextRequestId = 1;
const pendingRequests = new Map();

function makeAbortError() {
  if (typeof DOMException === "function") {
    return new DOMException("The operation was aborted.", "AbortError");
  }
  const error = new Error("The operation was aborted.");
  error.name = "AbortError";
  return error;
}

function workersSupported() {
  return typeof Worker === "function" && typeof URL === "function";
}

function poolSize() {
  const cores = typeof navigator !== "undefined" ? navigator.hardwareConcurrency || 4 : 4;
  return Math.max(2, Math.min(cores - 1, 8));
}

function rejectAllPending(error) {
  for (const request of pendingRequests.values()) {
    request.cleanup();
    request.reject(error);
  }
  pendingRequests.clear();
}

function ensurePool() {
  if (!workersSupported()) {
    return null;
  }
  if (pool) {
    return pool;
  }
  try {
    pool = Array.from({ length: poolSize() }, () => {
      const worker = new Worker(new URL("./surfWorker.js", import.meta.url), { type: "module" });
      worker.addEventListener("message", (event) => {
        const message = event.data || {};
        const request = pendingRequests.get(message.id);
        if (!request) {
          return;
        }
        pendingRequests.delete(message.id);
        request.cleanup();
        if (message.ok) {
          request.resolve({ meshData: message.meshData, bundle: message.bundle });
          return;
        }
        const error = new Error(message.error?.message || "Failed to load surf component in worker.");
        error.name = message.error?.name || "Error";
        request.reject(error);
      });
      worker.addEventListener("error", (event) => {
        // One broken worker poisons in-flight requests; tear the pool down
        // so the next load falls back (or rebuilds a fresh pool).
        rejectAllPending(new Error(event?.message || "surf worker failed."));
        for (const w of pool || []) w.terminate?.();
        pool = null;
      });
      return worker;
    });
  } catch {
    pool = null;
    return null;
  }
  return pool;
}

export function loadSurfComponentInWorker(url, { signal } = {}) {
  const workers = ensurePool();
  if (!workers) {
    return null;
  }
  if (signal?.aborted) {
    return Promise.reject(makeAbortError());
  }
  const id = nextRequestId;
  nextRequestId += 1;
  const worker = workers[nextWorkerIndex % workers.length];
  nextWorkerIndex += 1;
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      signal?.removeEventListener?.("abort", abort);
    };
    const abort = () => {
      pendingRequests.delete(id);
      cleanup();
      worker.postMessage({ type: "cancel", id });
      reject(makeAbortError());
    };
    pendingRequests.set(id, { resolve, reject, cleanup });
    signal?.addEventListener?.("abort", abort, { once: true });
    worker.postMessage({ type: "loadSurf", id, url });
  });
}
