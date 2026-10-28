import { X } from "lucide-react";
import { TREE_GLYPH_STROKE } from "@text-to-cad/ui/primitives/tree-row";
import { cn } from "@text-to-cad/ui/utils";
import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetCheckboxRow,
  FileSheetControlRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import { Button } from "@text-to-cad/ui/primitives/button";
import { TOOL_PANEL_BUTTON_CLASS } from "../../kit/tools/ToolPanel.jsx";
import { SketchIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { SelectionList } from "./EditCommand.jsx";
import { ORIGIN_PLANES, selectionItems } from "./editMode.js";
import { nxPlane } from "./nx.js";
import { formatValue, MODEL_TOOLS, MODIFY_TOOLS, newCurves, PATTERN_TOOLS, patternOp, patternSettings, polygonSides, relationsFor, relationsOn, sketchTool,
  toolSize } from "./sketchMode.js";

const STATUS_CLASSES = Object.freeze({ "Fully defined": "text-foreground", "Under defined": "text-blue-600 dark:text-blue-400",
  "Over defined": "text-red-600 dark:text-red-400" });
const CHIP_CLASS = "rounded-md border border-border px-2 py-0.5 text-tiny text-foreground hover:bg-accent/70 disabled:opacity-50";

/** A sketch tool's size, typed over as SolidWorks' PropertyManager takes it: a number, or a size's name. */
function SizeRow({ label, value, unit, disabled, onCommit }) {
  return <FileSheetControlRow label={label} trailing={<span className="flex shrink-0 items-center gap-1">
    <FileSheetValueInput value={value} ariaLabel={label} disabled={disabled}
      onValueCommit={draft => { const text = String(draft).trim(); if (text) onCommit(text); }} />
    <span className="w-6 text-micro text-muted-foreground">{unit}</span>
  </span>} />;
}

function Header({ title, detail, actions = null }) {
  return <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
    <SketchIcon className="size-5 shrink-0" />
    <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">{title}</h2>
    {detail ? <span className="shrink-0 truncate text-tiny text-muted-foreground">{detail}</span> : null}
    {actions}
  </div>;
}

/**
 * A sketch pattern's PropertyManager, as SolidWorks' Linear and Circular Sketch Pattern set theirs
 * out: the entities selected to copy, a linear pattern's spacing, instances and angle, a circular
 * one's instances, total angle and the point it turns about; the copies are drawn dashed on the
 * sketch until the pattern is made.
 */
function PatternSettings({ edit, tool, units, disabled }) {
  const settings = edit.sketchSettings || {};
  const pattern = patternSettings(tool, settings, edit.sketchSelection, edit.sketch?.state, units);
  const set = key => text => edit.setSketchSettings({ [key]: text });
  const make = async () => {
    const reply = await edit.sketchOp(patternOp(pattern));
    if (reply?.ok) edit.selectInSketch([]);
  };
  return <>
    <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Entities to pattern</p>
    {pattern.items.length ? <ul aria-label="Entities to pattern" className="mx-2 mb-1.5 flex flex-col rounded-md border border-border px-2 py-1 text-tiny leading-5 text-foreground">
      {pattern.items.map(id => <li key={id} className="truncate">{id}</li>)}
    </ul> : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1.5`}>None selected yet.</p>}
    {pattern.type === "linear" ? <>
      <SizeRow label="Spacing" value={pattern.spacing} unit={units} disabled={disabled} onCommit={set("linearSpacing")} />
      <SizeRow label="Instances" value={String(pattern.count)} unit="" disabled={disabled} onCommit={set("linearCount")} />
      <SizeRow label="Angle" value={pattern.angle} unit="deg" disabled={disabled} onCommit={set("linearAngle")} />
    </> : <>
      <SizeRow label="Instances" value={String(pattern.count)} unit="" disabled={disabled} onCommit={set("circularCount")} />
      <SizeRow label="Total angle" value={pattern.angle} unit="deg" disabled={disabled} onCommit={set("circularAngle")} />
      <FileSheetControlRow label="About" value={pattern.center || "Origin"} />
    </>}
    <div className="flex px-2 pb-2 pt-1">
      <Button size="sm" disabled={disabled || !pattern.items.length} onClick={() => void make()}>Make the pattern</Button>
    </div>
  </>;
}

/** The Sketch command waiting for its plane, as SolidWorks asks for one: the origin's three, or a flat face. */
function PlanePicker({ edit, onPlane }) {
  return <div role="dialog" aria-label="Sketch" className="flex shrink-0 flex-col" data-cad-sketch-picker=""
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopPicking(); } }}>
    <Header title="Sketch" />
    <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} py-2`}>Select a plane to sketch on: one of these, a plane in the design tree, or a flat face of the model.</p>
    {/* An offset plane, as SolidWorks' Plane at an Offset distance: the one picked, moved along its normal. */}
    <SizeRow label="Offset distance" value={edit.planeOffset || "0"} unit={edit.state?.units || ""} disabled={edit.saving}
      onCommit={text => edit.setPlaneOffset(text === "0" ? "" : text)} />
    <div className="flex flex-col gap-1 px-2 pb-2">
      {ORIGIN_PLANES.map(plane => <button key={plane} type="button" className={cn(CHIP_CLASS, "text-left")} disabled={edit.saving}
        onClick={() => onPlane(plane)}>{nxPlane(plane)}</button>)}
    </div>
    <ConfirmButtons onCancel={edit.stopPicking} className="border-t border-border px-2 py-2" />
  </div>;
}

/**
 * Convert Entities' own settings, as SolidWorks' PropertyManager asks for them: the edges and faces
 * selected on the model (Entities to Convert), and Convert, which brings them into the sketch.
 */
function ConvertEntities({ edit, references }) {
  const items = selectionItems(references);
  const settings = edit.sketchSettings || {};
  const units = edit.state?.units || "";
  // Offset from the model, as SolidWorks' Offset Entities takes a model's edges: they come in as
  // construction geometry to hold the offset curves at the distance.
  const offset = String(settings.convertOffset ?? "").trim();
  const construction = Boolean(settings.convertConstruction) || Boolean(offset);
  const convert = async () => {
    const before = edit.sketch?.state;
    const reply = await edit.sketchOp({ kind: "convert", items, ...(construction ? { construction: true } : {}) });
    if (!reply?.ok) return;
    if (offset) {
      const made = newCurves(before, reply.sketch?.state);
      if (made.length) await edit.sketchOp({ kind: "offset", items: made, distance: offset, reverse: Boolean(settings.convertReverse), construction: false });
    }
    edit.setSketchTool(null);
  };
  return <>
    <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Entities to Convert</p>
    <SelectionList items={items} prompt="Select edges or a face on the model." />
    <FileSheetCheckboxRow label="For construction" checked={construction} disabled={Boolean(offset)}
      onCheckedChange={value => edit.setSketchSettings({ convertConstruction: Boolean(value) })} />
    <SizeRow label="Offset" value={offset || "0"} unit={units} disabled={edit.saving}
      onCommit={text => edit.setSketchSettings({ convertOffset: text === "0" ? "" : text })} />
    {offset ? <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(settings.convertReverse)}
      onCheckedChange={value => edit.setSketchSettings({ convertReverse: Boolean(value) })} /> : null}
    <div className="flex justify-end px-2 pb-2 pt-1">
      <Button type="button" size="sm" disabled={!items.length || edit.saving} onClick={() => void convert()}>Convert</Button>
    </div>
  </>;
}

/** Intersection Curve, as SolidWorks' brings in where the part crosses the sketch's plane, held there as the part changes. */
function IntersectionCurve({ edit }) {
  const settings = edit.sketchSettings || {};
  const bring = async () => {
    const reply = await edit.sketchOp({ kind: "intersection", ...(settings.convertConstruction ? { construction: true } : {}) });
    if (reply?.ok) edit.setSketchTool(null);
  };
  return <>
    <FileSheetCheckboxRow label="For construction" checked={Boolean(settings.convertConstruction)}
      onCheckedChange={value => edit.setSketchSettings({ convertConstruction: Boolean(value) })} />
    <div className="flex justify-end px-2 pb-2 pt-1">
      <Button type="button" size="sm" disabled={edit.saving} onClick={() => void bring()}>Bring it in</Button>
    </div>
  </>;
}

/**
 * Sketch mode's PropertyManager, docked at the viewer's left above the design tree, as SolidWorks
 * shows one while a sketch is edited: the sketch and how defined it is; the tool in hand, what it
 * asks for next and whether it draws construction geometry; and for what is selected, the
 * relations it can take (Add Relations), the ones it has (Existing Relations, each deleted with its
 * X), a dimension's value, and For construction. The sketch tools' own settings sit with them:
 * Sketch Fillet's radius, Offset Entities' distance with Reverse direction and Select chain, the
 * entities Mirror Entities has, and the model's edges and faces Convert Entities takes. In its
 * dialog's foot Finish Sketch builds the part again and Discard Changes
 * leaves it as it was.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>, onPlane(plane: string): void, references?: object[] }} props
 *   `references`: the faces and edges selected on the model, for Convert Entities.
 */
export default function SketchPanel({ edit, onPlane, references = [] }) {
  if (!edit.sketch) return edit.picking ? <PlanePicker edit={edit} onPlane={onPlane} /> : null;
  const { sketch } = edit;
  const state = sketch.state;
  const units = edit.state?.units || "";
  const disabled = edit.saving;
  const tool = sketchTool(edit.sketchTool);
  const settings = edit.sketchSettings || {};
  const selection = edit.sketchSelection;
  const curves = new Map((state?.curves || []).map(curve => [curve.id, curve]));
  // A dimension selected, or a fillet's arc, whose radius is its dimension.
  const filletArc = selection.length === 1 ? curves.get(selection[0])?.dimension : null;
  const dimension = selection.length === 1
    ? (state?.dimensions || []).find(each => each.id === selection[0] || (filletArc && each.id === filletArc)) : null;
  const selectedCurves = selection.filter(id => curves.has(id));
  const allConstruction = selectedCurves.length > 0 && selectedCurves.every(id => curves.get(id).construction);
  const relations = state && selection.length ? relationsFor(state, selection) : [];
  const existing = state && selection.length && !dimension ? relationsOn(state, selection) : [];
  const status = state?.status || "";
  const statusText = !state ? "Not solved" : status === "Under defined"
    ? `Under defined, ${state.dof} ${state.dof === 1 ? "way" : "ways"} it can still move` : status;
  const finish = { onOk: () => void edit.exitSketch(), onCancel: () => void edit.cancelSketch(), okLabel: "Exit Sketch",
    cancelLabel: "Discard Changes", busy: disabled };
  return <div role="dialog" aria-label={sketch.name} className="flex shrink-0 flex-col" data-cad-sketch-panel=""
    onKeyDown={event => { if (event.key === "Escape" && edit.sketchTool) { event.stopPropagation(); edit.setSketchTool(null); } }}>
    <Header title={`Editing ${sketch.name}`} detail={sketch.plane && sketch.plane !== "Plane" ? nxPlane(sketch.plane) : ""} />
    <p className={cn(FILE_SHEET_STATUS_TEXT_CLASSES, "py-1.5", STATUS_CLASSES[status])} aria-live="polite">{edit.saving ? "Solving" : statusText}</p>
    {sketch.error && !state ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2 text-destructive`}>{sketch.error}</p> : null}
    {tool ? <FileSheetSettingsSection title={tool.label} sectionId="sketch-tool">
      <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">{tool.prompts[Math.min(edit.sketchStep, tool.prompts.length - 1)]}</p>
      {tool.id === "fillet" ? <SizeRow label="Fillet radius" value={toolSize(settings.filletRadius, units, "fillet")} unit={units}
        disabled={disabled} onCommit={text => edit.setSketchSettings({ filletRadius: text })} /> : null}
      {tool.id === "chamfer" ? <SizeRow label="Distance" value={toolSize(settings.chamferDistance, units, "chamfer")} unit={units}
        disabled={disabled} onCommit={text => edit.setSketchSettings({ chamferDistance: text })} /> : null}
      {tool.id === "offset" ? <>
        <SizeRow label="Offset distance" value={toolSize(settings.offsetDistance, units, "offset")} unit={units} disabled={disabled}
          onCommit={text => edit.setSketchSettings({ offsetDistance: text })} />
        <FileSheetCheckboxRow label="Reverse direction" checked={settings.offsetReverse} onCheckedChange={value => edit.setSketchSettings({ offsetReverse: Boolean(value) })} />
        <FileSheetCheckboxRow label="Select chain" checked={settings.offsetChain} onCheckedChange={value => edit.setSketchSettings({ offsetChain: Boolean(value) })} />
        {/* Construction geometry, as SolidWorks' Offset Entities sets it: the picked base dashed, or the offset. */}
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pt-1`}>Construction geometry</p>
        <FileSheetCheckboxRow label="Base geometry" checked={Boolean(settings.offsetBase)} onCheckedChange={value => edit.setSketchSettings({ offsetBase: Boolean(value) })} />
        <FileSheetCheckboxRow label="Offset geometry" checked={Boolean(settings.offsetConstruction)} onCheckedChange={value => edit.setSketchSettings({ offsetConstruction: Boolean(value) })} />
      </> : null}
      {/* Polygon's Parameters: how many sides it is drawn with. */}
      {tool.id === "polygon" ? <SizeRow label="Sides" value={String(polygonSides(settings.polygonSides))} unit="" disabled={disabled}
        onCommit={text => edit.setSketchSettings({ polygonSides: text })} /> : null}
      {PATTERN_TOOLS.includes(tool.id) ? <PatternSettings edit={edit} tool={tool.id} units={units} disabled={disabled} /> : null}
      {tool.id === "convert" ? <ConvertEntities edit={edit} references={references} /> : null}
      {tool.id === "intersection" ? <IntersectionCurve edit={edit} /> : null}
      {tool.id === "mirror" && selection.length ? <>
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Entities to mirror</p>
        <ul aria-label="Entities to mirror" className="mx-2 mb-1.5 flex flex-col rounded-md border border-border px-2 py-1 text-tiny leading-5 text-foreground">
          {selection.map(id => <li key={id} className="truncate">{id}</li>)}
        </ul>
      </> : null}
      {tool.id !== "dimension" && tool.id !== "centerline" && !MODIFY_TOOLS.includes(tool.id) && !MODEL_TOOLS.includes(tool.id) ? <FileSheetCheckboxRow label="For construction" checked={edit.construction}
        onCheckedChange={value => edit.setConstruction(Boolean(value))} /> : null}
    </FileSheetSettingsSection> : null}
    {!tool && !selection.length && state ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>
      Pick a tool in the ribbon to draw, or select the sketch's lines and points to relate or dimension them. Drag what is blue to move it. Click a relation's glyph to pick it; Delete takes it off.
    </p> : null}
    {/* SolidWorks' View, Sketch Relations: each relation's glyph beside what it holds, a click on one picks it. */}
    {!tool && state ? <FileSheetCheckboxRow label="Show relations" checked={settings.relations !== false}
      onCheckedChange={value => edit.setSketchSettings({ relations: Boolean(value) })} /> : null}
    {dimension ? <FileSheetSettingsSection title={filletArc ? selection[0] : dimension.id} sectionId="sketch-dimension">
      <FileSheetControlRow label={dimension.named ? dimension.formula : filletArc || dimension.kind === "fillet" ? "Radius" : "Value"} trailing={<span className="flex shrink-0 items-center gap-1">
        <FileSheetValueInput value={formatValue(dimension.value, units, "plain")} ariaLabel={`${dimension.id} value`} disabled={disabled || dimension.driven}
          onValueCommit={draft => { const text = String(draft).trim(); if (text) void edit.sketchOp({ kind: "value", dimension: dimension.id, text }); }} />
        <span className="w-6 text-micro text-muted-foreground">{dimension.kind === "angle" ? "deg" : units}</span>
      </span>} />
      {/* SolidWorks' Driven option: a dimension that measures, holding nothing, shown in parentheses. */}
      {filletArc || dimension.kind === "fillet" || dimension.kind === "chamfer" ? null
        : <FileSheetCheckboxRow label="Driven" checked={Boolean(dimension.driven)} disabled={disabled}
          onCheckedChange={value => void edit.sketchOp({ kind: "driven", dimension: dimension.id, on: Boolean(value) })} />}
      <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>{dimension.driven
        ? "Driven: it measures what the sketch sets. Untick Driven to size with it."
        : "Type a number, or a size of the part by its name."}</p>
    </FileSheetSettingsSection> : null}
    {selection.length && !dimension && tool?.id !== "mirror" ? <FileSheetSettingsSection title="Selected Entities" sectionId="sketch-selection">
      <ul aria-label="Selected" className="mx-2 mb-1 flex flex-col rounded-md border border-border px-2 py-1 text-tiny leading-5 text-foreground">
        {selection.map(id => <li key={id} className="truncate">{id}</li>)}
      </ul>
      {relations.length ? <>
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Add Relations</p>
        <div className="flex flex-wrap gap-1 px-2 pb-1.5">
          {relations.map(({ relation, label }) => <button key={relation} type="button" className={CHIP_CLASS} disabled={disabled}
            onClick={() => void edit.sketchOp({ kind: "relate", relation, refs: selection })}>{label}</button>)}
        </div>
      </> : null}
      {existing.length ? <>
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Existing Relations</p>
        <ul className="mx-2 mb-1.5 flex flex-col">
          {existing.map(item => <li key={item.id} className="flex min-h-6 items-center gap-1 text-tiny text-foreground">
            <span className={cn("min-w-0 flex-1 truncate", item.redundant && "text-destructive")}>
              {item.value !== undefined ? `${item.id}, ${formatValue(item.value, units, item.kind)}` : item.id}
            </span>
            <button type="button" aria-label={`Delete ${item.id}`} className={TOOL_PANEL_BUTTON_CLASS} disabled={disabled}
              onClick={() => void edit.sketchOp({ kind: "delete", items: [item.id] })}>
              <X className="size-3" strokeWidth={TREE_GLYPH_STROKE} aria-hidden="true" />
            </button>
          </li>)}
        </ul>
      </> : null}
      {selectedCurves.length ? <FileSheetCheckboxRow label="For construction" checked={allConstruction} disabled={disabled}
        onCheckedChange={value => void edit.sketchOp({ kind: "construction", items: selectedCurves, on: Boolean(value) })} /> : null}
    </FileSheetSettingsSection> : null}
    <ConfirmButtons {...finish} className="border-t border-border px-2 py-2" />
  </div>;
}
