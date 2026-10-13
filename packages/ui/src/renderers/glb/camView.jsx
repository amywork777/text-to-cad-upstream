/**
 * The CAM result viewer GlbRenderer loads only for a GLB that carries a job (`cadgen cam plan`): one module,
 * so the bundler makes it a chunk of its own and a plain GLB never fetches it. Everything GlbRenderer uses of
 * the CAM viewer is here, by name.
 */
import { useLayoutEffect } from "react";
import * as THREE from "three";
import { FileSheetStatusText } from "../kit/inspector/FileSheet.js";
import { CAM_JOB_PANEL_ID } from "./CamJobPanel.jsx";
import { faceSelector } from "./cam/extras.js";
import { camToolpathObjects, createCamPaths } from "./cam/lines.js";
import { camSceneMeshes, showCamMeshes } from "./cam/playback.js";
import { createCamTool } from "./cam/tool.js";

export { default as CamJobPanel } from "./CamJobPanel.jsx";
export { camChoices } from "./CamJobPanel.jsx";
export { camSourcePath, readCamJob } from "./cam/extras.js";
export { camOpColours } from "./cam/colours.js";
export { camClips } from "./cam/playback.js";
export { camSceneMeshes, showCamMeshes };

// Select's own panel, Job, which a person can close. A result opens with it up, except on a phone.
export const JOB_PANEL = Object.freeze({ id: CAM_JOB_PANEL_ID, label: "Job", startsClosed: false });

/** What Display shows of a result, before the person chooses: the paths and the part; the stock is a choice. */
export const CAM_SHOWN = Object.freeze({ toolpaths: true, rapids: true, stock: false, part: true });

/**
 * Display's sections of a result's own, after Surfaces: each a gate for what the file draws beyond a
 * plain GLB's surfaces — its toolpaths, its rapids, the simulated stock, the finished part — offered where the
 * file has it. `shown` is what is on; `onChange(patch)` changes it.
 */
export function camDisplaySections({ job, meshes, paths, shown, onChange }) {
  const sections = [];
  const gate = (id, title, words) => sections.push({ id: `cam-${id}`, title, enabled: shown[id] !== false,
    onEnabledChange: (on) => onChange({ [id]: on }), content: <FileSheetStatusText>{words}</FileSheetStatusText> });
  const operations = job.operations.length;
  if (paths.feed) gate("toolpaths", "Toolpaths", `${operations} operation${operations === 1 ? "" : "s"}, each in its own colour`);
  if (paths.rapid) gate("rapids", "Rapids", "Moves between cuts, dashed");
  if (meshes.stock.length) gate("stock", "Stock", "The stock as the job leaves it");
  if (meshes.part.length) gate("part", "Part", "The finished part");
  return sections;
}

/** Which kinds of path the file has: its lines, by kind. */
export function camPathKinds(root) {
  const kinds = { feed: false, rapid: false };
  for (const { kind } of camToolpathObjects(root)) kinds[kind] = true;
  return kinds;
}

/**
 * What Quick Edit gets for a choice: the part the job was planned from (`source`), the choice's faces as a
 * cad selector or, with none, the whole file, and the choice's sentence as its `summary`.
 */
export function camReferences(source, choice) {
  if (!source || !choice) return [];
  const faces = choice.faces.map(faceSelector);
  const target = faces.length ? { kind: "cad-selector", selectors: faces } : { kind: "whole-resource" };
  return [{ resource: { kind: "workspace-file", path: source }, target, ...(choice.summary ? { summary: choice.summary } : {}) }];
}

/**
 * The toolpaths and the riding tool, drawn into the viewport once its runtime is up (`createCamPaths`, which
 * needs its screen-space lines) and put away with the result. `controllerRef` holds `{ paths, tool }` while
 * they are up; `onChange` is told when they come and go, to draw what is shown.
 */
export function CamPaths({ runtimeRef, viewerReadyTick, root, cadRoot, job, scheme, controllerRef, onChange }) {
  useLayoutEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || !root || !job) return undefined;
    const pixelRatio = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    const paths = createCamPaths(runtime.THREE || THREE, root, job, { context: runtime, cadRoot, scheme, pixelRatio });
    if (!paths) return undefined;
    const tool = createCamTool(runtime.THREE || THREE, root, job, paths.frame);
    controllerRef.current = { paths, tool };
    onChange?.();
    return () => {
      controllerRef.current = null;
      tool.dispose();
      paths.dispose();
      onChange?.();
    };
    // The scheme is restyled in place (below), never rebuilt.
  }, [runtimeRef, viewerReadyTick, root, cadRoot, job]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const controller = controllerRef.current;
    if (!controller) return;
    controller.paths.style(scheme);
    onChange?.();
  }, [scheme]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/**
 * Draws what is shown, in one pass: the paths (on or off, isolated, revealed up to the moment playing) and the
 * tool at that moment, and the part and stock as Display says. Returns whether anything changed.
 */
export function paintCam({ controller, meshes, job, shown, isolate, moment }) {
  let changed = showCamMeshes(meshes, job, { part: shown.part !== false, stock: shown.stock !== false, time: moment ? moment.t : null });
  if (!controller) return changed;
  const { paths, tool } = controller;
  if (paths.update({ toolpaths: shown.toolpaths !== false, rapids: shown.rapids !== false, isolate, time: moment ? moment.t : null,
    setup: moment?.setup || null })) changed = true;
  if (moment) {
    tool.show(paths.toolAt(moment.t, moment.setup || null));
    return true;
  }
  tool.hide();
  return changed;
}
