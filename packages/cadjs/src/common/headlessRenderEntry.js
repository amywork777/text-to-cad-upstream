import gifencDefault, {
  GIFEncoder as exportedGifEncoder
} from "gifenc";
import * as THREE from "three";
import {
  buildModel
} from "./cadScene.js";
import {
  captureModel,
  modelOptionsForRenderJob,
  renderJobContext,
  renderModel
} from "./renderMeshScene.js";
import {
  hasStepParameterRenderValues
} from "./stepParameters.js";
import {
  loadSource,
  stepParameterFrameRuntime
} from "./source.js";
import {
  setTessellationCacheProvider
} from "../lib/surf/tessellationCache.js";
import {
  orbitFrameOutputs
} from "./headlessOrbitFrames.js";
import {
  resolveHeadlessJobKind
} from "./headlessJobKind.js";
// The unified snapshot runtime carries both backends: the mesh path below and
// the implicit raymarch path, which now lives beside this file rather than in a
// separate implicitjs package, so the whole snapshot bundle exposes a single
// window.__snapshotRender entry that dispatches by job kind.
import {
  runImplicitCadHeadlessRenderJob
} from "./implicitHeadlessRenderEntry.js";
// The GIF palette/encoder logic is shared with the implicit entry (single source,
// same as camera.js) so both backends pick the SAME transparent slot.
import { encodeGifFrameImageData } from "./gifFrameEncoder.js";

const GIFEncoder = exportedGifEncoder || gifencDefault?.GIFEncoder || gifencDefault;

async function dataUrlToImageData(dataUrl, width, height) {
  const image = new Image();
  image.decoding = "async";
  const loaded = new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = () => reject(new Error("Failed to load rendered orbit frame"));
  });
  image.src = dataUrl;
  await loaded;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0, width, height);
  return context.getImageData(0, 0, width, height);
}

function shouldEncodeTransparentGif(job = {}) {
  const backgroundType = String(
    job.theme?.background?.type || ""
  ).toLowerCase();
  return Boolean(job.render?.transparent) || backgroundType === "transparent";
}

// Coarse per-stage wall times for the last view-mode job, attached to its
// result so the driver can print where a slow snapshot actually went (load =
// fetch + tessellate/cache-hit + meshData; build = scene composition; render
// = GL draw; capture = readback + encode).
const headlessStageTimings = {};

async function capturePreparedSource(source, job) {
  const buildStarted = performance.now();
  const context = renderJobContext(source.meshData, job);
  const model = buildModel(THREE, source, modelOptionsForRenderJob(context, job));
  headlessStageTimings.buildModelMs = Math.round(performance.now() - buildStarted);
  if (context.mode === "list" || context.mode === "section") {
    try {
      return await captureModel({ model, context }, { job });
    } finally {
      model.dispose();
    }
  }
  const renderStarted = performance.now();
  const viewport = renderModel(THREE, model, { job, context });
  headlessStageTimings.renderMs = Math.round(performance.now() - renderStarted);
  try {
    const captureStarted = performance.now();
    const captured = await captureModel(viewport, { job });
    headlessStageTimings.captureMs = Math.round(performance.now() - captureStarted);
    if (captured && typeof captured === "object" && !Array.isArray(captured)) {
      captured.stageTimings = { ...headlessStageTimings };
    }
    return captured;
  } finally {
    viewport.dispose();
  }
}

async function renderOrbit(source, job) {
  const orbit = orbitFrameOutputs(job);
  const frameResult = await capturePreparedSource(source, {
    ...job,
    mode: "view",
    outputs: orbit.outputs,
    render: {
      ...(job.render || {}),
      lockFraming: true
    }
  });
  const encoder = GIFEncoder();
  const transparent = shouldEncodeTransparentGif(job);
  for (let index = 0; index < frameResult.outputs.length; index += 1) {
    const imageData = await dataUrlToImageData(frameResult.outputs[index].dataUrl, orbit.width, orbit.height);
    const frame = encodeGifFrameImageData(imageData, { transparent });
    encoder.writeFrame(frame.indexed, orbit.width, orbit.height, {
      palette: frame.palette,
      transparent: frame.transparent,
      transparentIndex: frame.transparentIndex,
      delay: 1000 / orbit.fps,
      repeat: 0,
      dispose: frame.transparent ? 2 : -1
    });
  }
  encoder.finish();
  const bytes = encoder.bytesView();
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return {
    ok: true,
    mode: "orbit",
    outputs: [{
      path: orbit.path,
      width: orbit.width,
      height: orbit.height,
      frameCount: orbit.frameCount,
      mimeType: "image/gif",
      dataUrl: `data:image/gif;base64,${btoa(binary)}`
    }],
    timings: frameResult.timings,
    warnings: frameResult.warnings || []
  };
}

async function renderParamAnimation(source, job, stepParameterSource) {
  const params = stepParameterSource.renderParameters;
  const output = Array.isArray(job.outputs) && job.outputs.length ? job.outputs[0] : {};
  const width = Math.max(1, Math.floor(Number(output.width || job.width || 720)));
  const height = Math.max(1, Math.floor(Number(output.height || job.height || 480)));
  const frameOutputs = Array.from({ length: params.frameCount }, (_, index) => ({
    ...output,
    path: "",
    width,
    height,
    stepParameters: stepParameterFrameRuntime(stepParameterSource, index)
  }));
  const frameResult = await capturePreparedSource(source, {
    ...job,
    outputs: frameOutputs,
    render: {
      ...(job.render || {}),
      lockFraming: true
    }
  });
  const encoder = GIFEncoder();
  const transparent = shouldEncodeTransparentGif(job);
  for (let index = 0; index < frameResult.outputs.length; index += 1) {
    const imageData = await dataUrlToImageData(frameResult.outputs[index].dataUrl, width, height);
    const frame = encodeGifFrameImageData(imageData, { transparent });
    encoder.writeFrame(frame.indexed, width, height, {
      palette: frame.palette,
      transparent: frame.transparent,
      transparentIndex: frame.transparentIndex,
      delay: 1000 / params.fps,
      repeat: params.loop === false ? -1 : 0,
      dispose: frame.transparent ? 2 : -1
    });
  }
  encoder.finish();
  const bytes = encoder.bytesView();
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return {
    ok: true,
    mode: String(job.mode || "view").toLowerCase(),
    outputs: [{
      path: String(output.path || job.output || ""),
      width,
      height,
      frameCount: params.frameCount,
      fps: params.fps,
      durationSeconds: params.durationSeconds,
      loop: params.loop !== false,
      mimeType: "image/gif",
      dataUrl: `data:image/gif;base64,${btoa(binary)}`
    }],
    timings: frameResult.timings,
    warnings: frameResult.warnings || []
  };
}

export async function runHeadlessRenderJob(job) {
  if (resolveHeadlessJobKind(job) === "implicit") {
    return runImplicitCadHeadlessRenderJob(job);
  }
  const loadStarted = performance.now();
  const source = await loadSource(job);
  headlessStageTimings.loadSourceMs = Math.round(performance.now() - loadStarted);
  const stepParameterSource = source.stepParameterSource;
  const explicitParams = hasStepParameterRenderValues(job.stepParameters);
  const renderJob = {
    ...job,
    selectorRuntime: source.selectorRuntime,
    displayEdgeRuntime: source.displayEdgeRuntime
  };
  if (stepParameterSource && explicitParams && String(job.mode || "view").toLowerCase() !== "view") {
    throw new Error("stepParameters support only view mode; set display.mode for display-style changes");
  }
  const renderJobWithStepParameters = stepParameterSource
    ? {
        ...renderJob,
        stepParameters: stepParameterFrameRuntime(stepParameterSource, 0)
      }
    : renderJob;
  if (stepParameterSource?.renderParameters?.animated) {
    return renderParamAnimation(source, renderJob, stepParameterSource);
  }
  if (String(job.mode || "view").toLowerCase() === "orbit") {
    return renderOrbit(source, renderJobWithStepParameters);
  }
  return capturePreparedSource(source, renderJobWithStepParameters);
}

if (typeof window !== "undefined") {
  window.__snapshotRender = runHeadlessRenderJob;
  // The snapshot host (cadgen's snapshot driver) serves the shared component-
  // tessellation cache (~/.cache/cadgen/meshes) on /__tess_cache/ through its
  // Playwright route, so repeat snapshots — and any component an export
  // already tessellated — skip tessellation entirely, and a snapshot miss
  // warms the cache for later exports. Both directions are best-effort: a
  // host without the route (404) or a disabled cache degrades to plain
  // in-page tessellation.
  setTessellationCacheProvider({
    async get(key) {
      try {
        const response = await fetch(`/__tess_cache/${encodeURIComponent(key)}.tess`, { cache: "no-store" });
        if (!response.ok) return null;
        return new Uint8Array(await response.arrayBuffer());
      } catch {
        return null;
      }
    },
    async put(key, bytes) {
      try {
        await fetch(`/__tess_cache/${encodeURIComponent(key)}.tess`, { method: "POST", body: bytes });
      } catch {
        // best-effort write-back
      }
    },
  });
}
