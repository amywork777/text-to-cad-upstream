import { useEffect, useRef, useState } from "react";
import { MEASURE_DIMENSION_COMMITTED_COLOR } from "@text-to-cad/core/lib/viewer/measureDimension.js";
import { Button } from "@text-to-cad/ui/primitives/button";
import { cn } from "@text-to-cad/ui/utils";
import { sizeName } from "./editMode.js";
import { useSceneRendered } from "./sceneRendered.js";

const ARROW_PX = 7;
const EMPTY = Object.freeze([]);
const CHIP_CLASS = "pointer-events-auto absolute left-0 top-0 z-10 whitespace-nowrap rounded-md border bg-background px-1.5 py-0.5 text-micro tabular-nums text-foreground shadow-sm";

/** One dimension's lines on the canvas: its witness lines, and the dimension line with an arrow at each end. */
function drawDimension(context, segments, color, active) {
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineCap = "round";
  context.globalAlpha = active ? 1 : 0.8;
  segments.forEach(([start, end], index) => {
    const last = index === segments.length - 1;
    context.lineWidth = last ? (active ? 2 : 1.5) : 1;
    context.beginPath();
    context.moveTo(start[0], start[1]);
    context.lineTo(end[0], end[1]);
    context.stroke();
    if (!last) return;
    const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
    if (length < ARROW_PX * 3) return;
    for (const [tip, from] of [[start, end], [end, start]]) {
      const ux = (tip[0] - from[0]) / length;
      const uy = (tip[1] - from[1]) / length;
      context.beginPath();
      context.moveTo(tip[0], tip[1]);
      context.lineTo(tip[0] - ux * ARROW_PX - uy * ARROW_PX * 0.45, tip[1] - uy * ARROW_PX + ux * ARROW_PX * 0.45);
      context.lineTo(tip[0] - ux * ARROW_PX + uy * ARROW_PX * 0.45, tip[1] - uy * ARROW_PX - ux * ARROW_PX * 0.45);
      context.closePath();
      context.fill();
    }
  });
  context.globalAlpha = 1;
}

/** A dimension's value, typed over like SolidWorks' Modify box: Enter changes it, Escape leaves it. */
function DimensionChip({ dimension, units, editing, active, disabled, onEdit, onHover, onCommit, chipRef }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef(null);
  useEffect(() => {
    if (!editing) return;
    setDraft(String(dimension.display));
    requestAnimationFrame(() => { inputRef.current?.focus(); inputRef.current?.select(); });
  }, [editing, dimension.display]);
  const label = `${sizeName(dimension.name)}${dimension.formula && dimension.formula !== dimension.display ? `, ${dimension.formula}` : ""}`;
  return <div ref={chipRef} className={cn(CHIP_CLASS, active || editing ? "border-[color:var(--edit-dimension)]" : "border-border")}
    style={{ "--edit-dimension": MEASURE_DIMENSION_COMMITTED_COLOR, visibility: "hidden" }}
    data-cad-edit-dimension={dimension.id}
    onPointerEnter={() => onHover(dimension.id)} onPointerLeave={() => onHover(null)}>
    {editing ? <form className="flex items-center gap-1" onSubmit={event => { event.preventDefault(); onCommit(draft); }}>
      <input ref={inputRef} value={draft} aria-label={`${sizeName(dimension.name)} value`} inputMode="decimal"
        className="w-16 bg-transparent text-micro tabular-nums text-foreground outline-none"
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); onEdit(null); } }}
        onBlur={() => onEdit(null)} />
      {units ? <span className="text-muted-foreground">{units}</span> : null}
    </form> : <button type="button" disabled={disabled} aria-label={`${label}. Double-click to change`}
      className="cursor-text tabular-nums disabled:cursor-default"
      onDoubleClick={() => onEdit(dimension.id)}
      onKeyDown={event => { if (event.key === "Enter") onEdit(dimension.id); }}>
      {dimension.label}
    </button>}
  </div>;
}

/**
 * Edit mode's layer over the viewport: the selected feature's dimensions on the model, drawn in
 * Measure's color, each with its value, which a double-click changes. The points are the part's
 * own millimetres (`cadgen/edit`), placed as the model is (under the model group), and laid out
 * again only when the view is drawn or the dimensions changed.
 *
 * @param {{ viewport: { runtimeRef: object, hostRef: object, viewerReadyTick: number },
 *   dimensions: object[], units: string, disabled?: boolean, choice?: object | null,
 *   onChange(dimension: object, text: string): void, onChoose(leaf: string): void, onDismissChoice(): void,
 *   planes?: { points: number[][], strong: boolean }[], origin?: number | null }} props
 *   `planes`: the origin planes the design tree has selected or under its pointer (`planeOutline`);
 *   `origin`: the length of the origin's axes, drawn while the tree selects the Origin.
 */
export default function EditDimensions({ viewport, dimensions, units, disabled = false, choice = null, onChange, onChoose, onDismissChoice,
  planes = EMPTY, origin = null }) {
  const canvasRef = useRef(null);
  const chips = useRef(new Map());
  const dimensionsRef = useRef(dimensions);
  dimensionsRef.current = dimensions;
  const marksRef = useRef({ planes, origin });
  marksRef.current = { planes, origin };
  const [editing, setEditing] = useState(null);
  const [hovered, setHovered] = useState(null);
  const activeRef = useRef(null);
  activeRef.current = editing || hovered;

  // Laid out after each render of the view and once when the dimensions or the marks change (`useSceneRendered`), never per
  // frame at rest.
  const paintRef = useRef(() => {});
  const request = useSceneRendered(viewport, () => paintRef.current());
  useEffect(() => { request(); });
  useEffect(() => {
    const host = viewport.hostRef?.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return undefined;
    let painted = "";
    let paintedDimensions = null;
    let paintedActive = null;
    let paintedMarks = null;
    const paint = () => {
      const runtime = viewport.runtimeRef?.current;
      if (!runtime?.camera || !runtime.modelGroup) return;
      const width = host.clientWidth || 1;
      const height = host.clientHeight || 1;
      const dpr = window.devicePixelRatio || 1;
      const { camera, modelGroup, THREE } = runtime;
      camera.updateMatrixWorld();
      modelGroup.updateMatrixWorld();
      // Everything a layout depends on; an idle view compares and returns.
      const key = [width, height, dpr, camera.zoom, camera.matrixWorld.elements.join(), camera.projectionMatrix.elements.join(),
        modelGroup.matrixWorld.elements.join()].join("|");
      const list = dimensionsRef.current;
      const marks = marksRef.current;
      if (key === painted && list === paintedDimensions && activeRef.current === paintedActive && marks === paintedMarks) return;
      painted = key;
      paintedDimensions = list;
      paintedActive = activeRef.current;
      paintedMarks = marks;
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      const context = canvas.getContext("2d");
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      const scratch = new THREE.Vector3();
      const toScreen = point => {
        scratch.set(point[0], point[1], point[2]).applyMatrix4(modelGroup.matrixWorld);
        // In front of the camera at all: the viewer's orthographic camera sits well back, with its
        // near plane far in front of it, and a plane's corner can come closer than that.
        const inFront = scratch.clone().applyMatrix4(camera.matrixWorldInverse).z < 0;
        scratch.project(camera);
        return inFront ? [((scratch.x + 1) * width) / 2, ((1 - scratch.y) * height) / 2] : null;
      };
      // An origin plane, as a CAD tool shows one: a square through the origin, filled faintly.
      for (const plane of marks.planes) {
        const corners = plane.points.map(toScreen);
        if (corners.some(corner => !corner)) continue;
        context.beginPath();
        corners.forEach(([x, y], index) => (index ? context.lineTo(x, y) : context.moveTo(x, y)));
        context.closePath();
        context.globalAlpha = plane.strong ? 0.16 : 0.08;
        context.fillStyle = MEASURE_DIMENSION_COMMITTED_COLOR;
        context.fill();
        context.globalAlpha = plane.strong ? 0.9 : 0.5;
        context.strokeStyle = MEASURE_DIMENSION_COMMITTED_COLOR;
        context.lineWidth = 1.25;
        context.stroke();
        context.globalAlpha = 1;
      }
      // The origin: its three axes in the colors every CAD tool gives them.
      if (marks.origin) {
        const center = toScreen([0, 0, 0]);
        for (const [axis, color] of [[[marks.origin, 0, 0], "#ef4444"], [[0, marks.origin, 0], "#22c55e"], [[0, 0, marks.origin], "#3b82f6"]]) {
          const tip = toScreen(axis);
          if (!center || !tip) continue;
          context.strokeStyle = color;
          context.lineWidth = 2;
          context.beginPath();
          context.moveTo(center[0], center[1]);
          context.lineTo(tip[0], tip[1]);
          context.stroke();
        }
      }
      for (const dimension of list) {
        const segments = (dimension.lines || []).map(([start, end]) => [toScreen(start), toScreen(end)]).filter(([a, b]) => a && b);
        drawDimension(context, segments, MEASURE_DIMENSION_COMMITTED_COLOR, dimension.id === activeRef.current);
        const chip = chips.current.get(dimension.id);
        const at = dimension.anchor ? toScreen(dimension.anchor) : null;
        if (!chip) continue;
        chip.style.visibility = at ? "visible" : "hidden";
        if (at) chip.style.transform = `translate(${Math.round(at[0])}px, ${Math.round(at[1])}px) translate(-50%, -50%)`;
      }
    };
    paintRef.current = paint;
    request();
    return () => { paintRef.current = () => {}; };
  }, [viewport.hostRef, viewport.runtimeRef, viewport.viewerReadyTick, request]);

  return <>
    <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 z-10 h-full w-full" aria-hidden="true" data-cad-edit-dimensions="" />
    <div className="pointer-events-none absolute inset-0 z-10" role="group" aria-label="Dimensions">
      {dimensions.map(dimension => <DimensionChip key={dimension.id} dimension={dimension} units={units}
        editing={editing === dimension.id} active={hovered === dimension.id} disabled={disabled}
        chipRef={element => { if (element) chips.current.set(dimension.id, element); else chips.current.delete(dimension.id); }}
        onEdit={setEditing} onHover={setHovered}
        onCommit={text => { setEditing(null); if (String(text).trim() && String(text).trim() !== String(dimension.display)) onChange(dimension, String(text).trim()); }} />)}
    </div>
    {/* Under the workspace's toolbar, which floats over the view's top (`--cad-workspace-top`). */}
    {choice ? <div className="pointer-events-auto absolute left-1/2 z-30 w-[min(20rem,calc(100%-1rem))] -translate-x-1/2 rounded-lg border border-border bg-background p-2.5 text-tiny shadow-md"
      style={{ top: "calc(var(--cad-workspace-top, 0px) + 3rem)" }} role="dialog" aria-label="Which size to change">
      <p className="mb-2 text-foreground">That value comes from a formula. Change which size?</p>
      <div className="flex flex-wrap gap-1">
        {choice.options.map(option => <Button key={option.id} type="button" variant="outline" size="sm" className="h-7 px-2 text-tiny"
          onClick={() => onChoose(option.id)}>{sizeName(option.name)}</Button>)}
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-tiny text-muted-foreground" onClick={onDismissChoice}>Cancel</Button>
      </div>
    </div> : null}
  </>;
}

