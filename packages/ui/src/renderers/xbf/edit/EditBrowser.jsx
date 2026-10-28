import { useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@text-to-cad/ui/utils";
import { Button } from "@text-to-cad/ui/primitives/button";
import { ScrollArea } from "@text-to-cad/ui/primitives/scroll-area";
import {
  FILE_SHEET_COMPACT_BUTTON_CLASSES,
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetButtonRow,
  FileSheetControlRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import { WORKSPACE_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { TOOL_PANEL_BUTTON_CLASS } from "../../kit/tools/ToolPanel.jsx";
import EditCommand from "./EditCommand.jsx";
import EditTree from "./EditTree.jsx";
import SketchPanel from "./SketchPanel.jsx";
import DraftAnalysis from "./DraftAnalysis.jsx";
import InterferencePanel from "./InterferencePanel.jsx";
import MassProperties from "./MassProperties.jsx";
import MatePanel from "./MatePanel.jsx";
import InsertComponents from "./InsertComponents.jsx";
import DrawingPanel from "./DrawingPanel.jsx";
import ComparePanel from "./ComparePanel.jsx";
import ExpressionsPanel from "./ExpressionsPanel.jsx";
import Appearance from "./Appearance.jsx";
import EditSizes from "./EditSizes.jsx";
import { formulaWords, restates, selectionDimensions, sizeName, treeFeatures } from "./editMode.js";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { nxPlane, treeTitles } from "./nx.js";

const UNIT_MARKS = Object.freeze({ mm: "mm", in: "in" });

/**
 * Whether the browser floats a card in the dialog's place beside the design tree (`card`): the open
 * command's or sketch's panel, a panel the toolbar opened (Measure Bodies, Expressions...; the Drawing
 * once the part has its sheet), or what went wrong. The frame keeps the top column clear of it
 * (`RendererShell`'s `dialogOpen`).
 */
export function floatsCard(edit) {
  return Boolean(edit.sketch || edit.picking || edit.command || edit.error || edit.confirming
    || (edit.inspecting && (edit.inspecting !== "drawing" || edit.state?.drawing)));
}

/** A number of the part, as its row shows it: its value in the source, typed over to change it, and its unit. */
function ValueField({ value, unit, label, disabled, onCommit }) {
  return <span className="flex shrink-0 items-center gap-1">
    <FileSheetValueInput value={value} ariaLabel={`${label} value`} disabled={disabled}
      onValueCommit={draft => { const text = String(draft).trim(); if (text && text !== String(value)) onCommit(text); }} />
    <span className="w-4 text-micro text-muted-foreground">{UNIT_MARKS[unit] || unit || ""}</span>
  </span>;
}

/**
 * Edit mode's browser, what the design tree holds (the frame's card at the view's top-left): the
 * design tree (`EditTree.jsx`: the part, its Parameters, the origin's planes, its features with their
 * sketches), and under it the selection's own values, as a PropertyManager shows them: a
 * feature's inputs, or a sketch's dimensions. Every value is typed over to change it; a change is
 * one number in the part's script (`cadgen/edit`). While a modeling command is open, its panel
 * floats in a card of its own over the model (`card`), apart from the tree, where a feature to copy
 * is picked; while a sketch is edited, or the Sketch command waits for its plane, the sketch's
 * PropertyManager does (`SketchPanel.jsx`). What went wrong is said in that card too, so the Part
 * Navigator folded to its title never hides it.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>, names: ReturnType<typeof import("./editMode.js").featureNames>,
 *   tree: ReturnType<typeof import("./editMode.js").featureTree>, references?: object[],
 *   onEditSketch?: (sketch: object) => void, onPlane?: (plane: string) => void, onOpenPart?: ((component: object) => void) | null }} props
 *   `references`: the faces and edges selected on the model; `onOpenPart`: a part of an assembly
 *   opened on its own, to be modeled (SolidWorks' Open Part), and `backTo` ({ title, open }) the
 *   assembly a part was opened from; `onEditSketch`: a sketch's
 *   double-click in the tree; `onPlane`: an origin plane picked for a new sketch; `card`: the
 *   place beside the design tree where the open command's panel floats;
 *   `onDeselect`: a face or edge the command's panel lists taken out of the selection (its id).
 */
export default function EditBrowser({ edit, names, tree, references = [], onEditSketch = () => {}, onPlane = () => {}, onOpenPart = null,
  backTo = null, card = null, onDeselect = null }) {
  const [open, setOpen] = useState(true);
  const { state, status } = edit;
  const rows = state?.rows || [];
  const disabled = edit.saving || status !== "ready";
  const selected = edit.selected || "";
  const sketchSelected = selected.startsWith("sketch:");
  const feature = treeFeatures(tree).find(each => each.id === (sketchSelected ? selected.slice("sketch:".length) : selected)) || null;
  // A part of an assembly, selected in the tree: an assembly places its parts, so a part is
  // modeled on its own, opened as SolidWorks' Open Part opens it.
  const component = tree.assembly ? tree.components.find(each => each.id === selected) || null : null;
  // Its title as the design tree has it ("Boss-Extrude2"), with what the script calls it.
  const titles = treeTitles(tree);
  const title = !feature ? "" : sketchSelected
    ? `${titles.get(feature.sketch?.id) || feature.sketch?.title || "Sketch"}${feature.sketch?.plane && feature.sketch.plane !== "Plane" ? `, ${nxPlane(feature.sketch.plane)}` : ""}`
    : `${titles.get(feature.id) || feature.title}${feature.name ? `, ${feature.name}` : ""}`;
  // A feature's inputs, its sketch's dimensions among them (D1@Sketch2), each changed through the
  // feature, so the part is built again with it.
  const featureInputs = feature => feature.rows.flatMap(key => (rows.find(row => row.key === key)?.inputs || []).map((input, index) => ({
    key: `${key}:${index}`, label: input.label, value: input.display, unit: input.unit, formula: input.formula,
    request: text => ({ input: { row: key, index }, text }) })));
  const sketchInputs = feature && sketchSelected && feature.sketch?.constrained
    ? featureInputs(feature).filter(input => input.label.endsWith(`@${feature.sketch.title}`)) : null;
  const inputs = !feature ? [] : sketchInputs || (sketchSelected
    ? selectionDimensions(state, tree, selected).map(dimension => ({ key: dimension.id, label: sizeName(dimension.name), value: dimension.display,
      unit: state?.units, formula: dimension.formula, request: text => ({ dimension: dimension.id, text }) }))
    : featureInputs(feature));
  // The open command's or sketch's panel, in a card of its own over the model's top-right corner, as
  // a CAD tool's command dialog floats apart from its tree; here, above the tree, where the view
  // keeps no card for it.
  const panel = edit.sketch || edit.picking ? <SketchPanel edit={edit} onPlane={onPlane} references={references} />
    : edit.command === "sizes" ? <EditSizes key={`sizes:${edit.editing?.id || ""}`} edit={edit} />
    : edit.command ? <EditCommand key={`${edit.command}:${edit.editing?.id || ""}`} edit={edit} names={names} references={references} tree={tree}
      onDeselect={onDeselect} />
      // Mass Properties, from the ribbon's Inspect group, in the same card.
      : edit.inspecting === "mass" ? <MassProperties edit={edit} />
        // Draft Analysis, from the Inspect group: the part shaded by its draft against the pull.
        : edit.inspecting === "draft" ? <DraftAnalysis edit={edit} />
        // Interference Detection, from the Inspect group: the parts that overlap, and by how much.
        : edit.inspecting === "interference" ? <InterferencePanel edit={edit} />
        : edit.inspecting === "appearance" ? <Appearance edit={edit} />
          // Mate, from the ribbon's Assemble group: an assembly's part placed by two picks.
          : edit.inspecting === "mate" ? <MatePanel edit={edit} references={references} components={tree?.components || []} onDeselect={onDeselect} />
            // Insert Components, from the same group: a part of the project added to the assembly.
            : edit.inspecting === "insert" ? <InsertComponents edit={edit} />
            // The part's drawing, from the ribbon's Drawing group.
            : edit.inspecting === "drawing" && edit.state?.drawing ? <DrawingPanel edit={edit} />
              // Compare, from the ribbon's Inspect group.
              : edit.inspecting === "compare" ? <ComparePanel edit={edit} />
                // Expressions, from the Inspect tab: the part's user expressions, typed over to change them.
                : edit.inspecting === "expressions" ? <ExpressionsPanel edit={edit} />
                  : null;
  // What went wrong, over what follows it (`ruled`): the open panel, or the tree where there is no card.
  const error = ruled => edit.error ? <div className={cn("flex items-start gap-1 px-2 py-1.5 text-tiny text-destructive", ruled && "border-b border-border")} role="alert">
    <span className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
      {edit.error}
      {edit.redraw ? <Button type="button" variant="outline" size="sm" className={FILE_SHEET_COMPACT_BUTTON_CLASSES}
        onClick={edit.askRedraw}>Redraw it as a sketch</Button> : null}
    </span>
    <button type="button" aria-label="Dismiss" className={TOOL_PANEL_BUTTON_CLASS} onClick={edit.dismissError}><X className="size-3" aria-hidden="true" /></button>
  </div> : null;
  // SolidWorks' Confirm Delete: the feature's child features named, deleted with it on Delete All.
  const asked = edit.confirming;
  const confirm = ruled => asked ? <div className={cn("flex flex-col gap-1.5 px-2 py-1.5 text-tiny", ruled && "border-b border-border")}
    role="alertdialog" aria-label="Confirm Delete">
    <span className="font-medium text-foreground">Confirm Delete</span>
    <span className="text-muted-foreground">{`${asked.title} has child feature${asked.children.length > 1 ? "s" : ""}: `
      + `${asked.children.map(child => child.title).join(", ")}. Delete ${asked.children.length > 1 ? "them" : "it"} too?`}</span>
    <ConfirmButtons okLabel="Delete All" onOk={() => void edit.confirmDelete()} onCancel={edit.dismissDelete} busy={edit.saving} />
  </div> : null;
  // The card, the workspace's white surface, scrolls in the viewer's one ScrollArea once its panel is taller than the view.
  const floating = (panel || edit.error || asked) && card ? createPortal(<ScrollArea data-cad-command-card="" className={cn(WORKSPACE_SURFACE_CLASS,
    "pointer-events-auto max-h-full")}>{confirm(Boolean(panel))}{error(Boolean(panel))}{panel}</ScrollArea>, card) : null;
  return <div className="flex h-full min-h-0 flex-col" data-cad-edit-browser="">
    {floating || <>{confirm(true)}{error(true)}{panel}</>}
    <ScrollArea className="min-h-0 flex-1">
      <EditTree edit={edit} tree={tree} onEditSketch={onEditSketch} onOpenPart={onOpenPart} backTo={backTo} />
      {component && !edit.command && !edit.sketch ? <FileSheetSettingsSection title={component.title} sectionId="edit-component">
        <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>
          {(component.document || component.step) && onOpenPart ? "A part of this assembly. Open it to change its features, sketch on it and add new ones."
            : "A part of this assembly. Ask the agent to change it."}</p>
        {(component.document || component.step) && onOpenPart ? <div className="pb-2"><FileSheetButtonRow>
          <Button type="button" variant="outline" size="sm" className={cn(FILE_SHEET_COMPACT_BUTTON_CLASSES, "justify-center")}
            onClick={() => onOpenPart(component)}>Open Part</Button>
        </FileSheetButtonRow></div> : null}
      </FileSheetSettingsSection> : null}
      {feature && !edit.command && !edit.sketch ? <FileSheetSettingsSection title={title} sectionId="edit-feature" open={open} onOpenChange={setOpen}>
        {feature.kind === "Sketch" ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>
          Double-click it to edit the sketch, or make a solid of it with an extrude or a revolve.</p>
          : feature.suppressed ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>
            Suppressed: its lines are comments in the script. Tick its box in the design tree to put it back.</p>
          : inputs.length === 0 ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`}>Nothing to set here.</p>
          : inputs.map(input => <FileSheetControlRow key={input.key} label={input.label}
            trailing={<ValueField value={input.value} unit={input.unit} label={input.label} disabled={disabled}
              onCommit={text => edit.change(input.request(text))} />}>
            {restates(input.formula, input.value) ? null : <span className="block truncate text-micro text-muted-foreground">{`= ${formulaWords(input.formula)}`}</span>}
          </FileSheetControlRow>)}
        {feature.file ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2 pt-1`}>{`${feature.file.split("/").pop()}, line ${feature.line}`}</p> : null}
      </FileSheetSettingsSection> : null}
    </ScrollArea>
  </div>;
}
