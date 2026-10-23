import { useMemo, useState } from "react";
import { CircleAlert, Eye, EyeOff, Pin, Plus } from "lucide-react";
import { pmiNumber, pmiToleranceText } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { Button } from "@text-to-cad/ui/primitives/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@text-to-cad/ui/primitives/dropdown-menu";
import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { ROW_NAME_UNDER_ACTIONS, TreeRowLabel, TreeRowSurface, treeRowActionsClass } from "@text-to-cad/ui/primitives/tree-row";
import { cn } from "@text-to-cad/ui/utils";
import { FileSheetStatusText, FileSheetValueInput } from "../../kit/inspector/FileSheet.js";
import { InfoRow, MonoValue } from "../../kit/inspector/referenceRows.jsx";
import ToolPanel, { TOOL_PANEL_BUTTON_CLASS, ToolPanelHeadAction } from "../../kit/tools/ToolPanel.jsx";
import { PmiGlyph, PmiIcon } from "./pmiGlyphs.jsx";
import { parseToleranceInput, pmiCreateOptions } from "./pmiCreate.js";

// An engine document's **PMI**, a section of the file sidebar for a document that carries any:
// every annotation, a row each -- its glyph and what its callout says, and its eye -- in the
// document's order; the one picked opens under its row, its values read out with their units and
// where each came from (a nominal measured on the geometry, a tolerance as the code gave it, or
// none given), its references and how they stand, where it is placed; an annotation the viewer does
// not draw is a row too, saying so. Its head holds New (what the faces Select has picked can be) and
// the eye of them all. Where the document is made from code the agent can change, a value edited
// here, a label moved in the view, a placement pinned or a new annotation is a change Quick Edit
// carries to the agent (`useXbfPmi`): nothing here writes the file.

const ROW_ACTIONS_WIDTH = "1.5rem";
const ROLE_NAMES = Object.freeze({ feature: "Feature", from: "From", to: "To" });
const STATUS_WORDS = Object.freeze({ ok: "", missing: "Missing", ambiguous: "Ambiguous" });
const STATUS_TEXT = Object.freeze({ missing: "text-red-500", ambiguous: "text-amber-500" });
const mm = (value, unit = "mm") => `${value} ${unit}`;

function RowEye({ id, hidden, onToggle }) {
  const action = hidden ? "Show" : "Hide";
  return <div data-row-actions="" className={treeRowActionsClass(hidden)}>
    <TooltipHint content={action}>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`${action} ${id}`} aria-pressed={hidden} className="h-5 w-4 text-muted-foreground"
        data-pmi-visibility={id} onClick={event => { event.stopPropagation(); onToggle(id); }}>
        {hidden ? <EyeOff className="size-3" aria-hidden="true" /> : <Eye className="size-3" aria-hidden="true" />}
      </Button>
    </TooltipHint>
  </div>;
}

const toleranceInputText = tolerance => (tolerance ? pmiToleranceText(tolerance).text : "");

function ToleranceField({ value, onCommit, label = "Tolerance" }) {
  const [error, setError] = useState("");
  return <>
    <div className="flex items-center justify-between gap-3 py-0.5">
      <span className="shrink-0 text-tiny text-muted-foreground">{label}</span>
      <FileSheetValueInput value={toleranceInputText(value)} ariaLabel={label} inputMode="text" className="w-20 min-w-0"
        onValueCommit={(text) => {
          const read = parseToleranceInput(text);
          setError(read.error || "");
          if (!read.error) onCommit(read.tolerance);
        }} />
    </div>
    {error ? <p role="alert" className="text-tiny text-destructive">{error}</p> : null}
  </>;
}

function ValueField({ value, onCommit, label }) {
  const [error, setError] = useState("");
  return <>
    <div className="flex items-center justify-between gap-3 py-0.5">
      <span className="shrink-0 text-tiny text-muted-foreground">{label}</span>
      <FileSheetValueInput value={value === null || value === undefined ? "" : pmiNumber(value)} ariaLabel={label} className="w-16 min-w-0"
        onValueCommit={(text) => {
          const number = Number(String(text).trim());
          if (!String(text).trim()) { setError(""); onCommit(null); return; }
          if (!(Number.isFinite(number) && number > 0)) { setError("A tolerance value is more than 0"); return; }
          setError("");
          onCommit(number);
        }} />
    </div>
    {error ? <p role="alert" className="text-tiny text-destructive">{error}</p> : null}
  </>;
}

function DatumPicker({ letters, value, onChange }) {
  if (!letters.length) return null;
  return <div className="flex items-center justify-between gap-3 py-0.5">
    <span className="shrink-0 text-tiny text-muted-foreground">Datums</span>
    <div className="flex flex-wrap justify-end gap-1">
      {letters.map(letter => <button key={letter} type="button" aria-pressed={value.includes(letter)} data-pmi-datum-choice={letter}
        onClick={() => onChange(value.includes(letter) ? value.filter(item => item !== letter) : [...value, letter].sort())}
        className={cn("h-5 min-w-5 rounded-sm border px-1 text-tiny", value.includes(letter) ? "border-foreground bg-accent text-foreground" : "border-border text-muted-foreground")}>
        {letter}
      </button>)}
    </div>
  </div>;
}

/** The values of an annotation, read out: what it is, and where every number came from. */
function EntryDetails({ entry, pmi, letters }) {
  const editable = pmi.editable && entry.supported && entry.status === "ok";
  const construction = pmi.constructions.get(entry.id);
  const pending = pmi.changes.find(change => change.key === `edit:${entry.id}`);
  const values = pending?.values || {};
  const given = key => (Object.prototype.hasOwnProperty.call(values, key) ? values[key] : undefined);
  return <div className="px-2 pb-1.5 pt-0.5" data-pmi-details={entry.id}>
    {entry.statusText ? <p className={cn("flex items-start gap-1 py-0.5 text-tiny", STATUS_TEXT[entry.status])} role="status">
      <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" /><span className="min-w-0 [overflow-wrap:anywhere]">{entry.statusText}</span>
    </p> : null}
    {!entry.supported ? <FileSheetStatusText className="px-0">{`Not shown: ${entry.unsupported}.`}</FileSheetStatusText> : null}
    {entry.kind === "dimension" && entry.supported ? <>
      {entry.dimension.nominal === null ? <InfoRow label="Nominal" copy={false}>Unknown: nothing to measure</InfoRow>
        : <InfoRow label="Nominal" title="Measured on the geometry by the engine"><MonoValue>{mm(entry.callout.diameter ? `⌀${pmiNumber(entry.dimension.nominal, 3)}` : pmiNumber(entry.dimension.nominal, 3), entry.dimension.unit)}</MonoValue>
          <span className="text-muted-foreground">{entry.dimension.source === "geometry" ? ", measured" : ""}</span></InfoRow>}
      {editable ? <ToleranceField value={given("tolerance") === undefined ? entry.dimension.tolerance : given("tolerance")}
        onCommit={tolerance => pmi.edit(entry.id, { tolerance })} />
        : <InfoRow label="Tolerance">{entry.dimension.tolerance ? <MonoValue>{mm(pmiToleranceText(entry.dimension.tolerance).text, entry.dimension.unit)}</MonoValue> : "None given"}</InfoRow>}
    </> : null}
    {entry.kind === "datum" && entry.supported ? <InfoRow label="Letter">{entry.datum.letter}</InfoRow> : null}
    {entry.kind === "geometric_tolerance" && entry.supported ? <>
      <InfoRow label="Kind">{entry.callout.title}</InfoRow>
      {editable ? <ValueField label="Tolerance" value={given("value") ?? entry.tolerance.value} onCommit={value => { if (value !== null) pmi.edit(entry.id, { value }); }} />
        : <InfoRow label="Tolerance"><MonoValue>{mm(`${entry.callout.diameter ? "⌀" : ""}${entry.callout.value}`, entry.tolerance.unit)}</MonoValue></InfoRow>}
      {entry.tolerance.characteristic === "position" ? (editable
        ? <DatumPicker letters={letters} value={given("datums") ?? entry.tolerance.datums} onChange={datums => pmi.edit(entry.id, { datums })} />
        : <InfoRow label="Datums">{entry.tolerance.datums.join(", ") || "None"}</InfoRow>) : null}
    </> : null}
    {entry.refs.map(ref => <InfoRow key={`${ref.role}:${ref.written}`} label={ROLE_NAMES[ref.role] || ref.role} copy={ref.ref}
      title={ref.status === "ok" ? ref.ref : `${STATUS_WORDS[ref.status]}: ${ref.written}`}>
      <span className={cn("[overflow-wrap:anywhere]", STATUS_TEXT[ref.status])}>{ref.written}</span>
      {ref.status === "ambiguous" && ref.candidates.length ? <span className="block text-muted-foreground">{`names ${ref.candidates.join(", ")}`}</span> : null}
    </InfoRow>)}
    {entry.supported ? <InfoRow label="Placed" copy={false}>{pending?.values.presentation ? "Moved, in Quick Edit" : entry.presentation ? "In code" : "Beside its feature"}</InfoRow> : null}
    {editable && construction && !entry.presentation && !pending?.values.presentation ? <Button type="button" variant="ghost" size="xs" className="-ml-1.5 h-6 text-tiny"
      data-pmi-pin={entry.id} onClick={() => pmi.pin(entry.id)}><Pin className="size-3" aria-hidden="true" />Pin placement</Button> : null}
    {pending ? <FileSheetStatusText className="px-0">In Quick Edit for the agent to write.</FileSheetStatusText> : null}
  </div>;
}

/** A new annotation being made: its kind's values to give, then Add to Quick Edit. */
function NewEntry({ option, letters, onAdd, onCancel }) {
  const [call, setCall] = useState(option.call);
  const needsValue = call.kind === "geometric_tolerance";
  const ready = !needsValue || (Number.isFinite(call.value) && call.value > 0);
  return <div className="border-b border-border px-2 pb-2 pt-1" data-pmi-new={option.kind}>
    <p className="flex items-center gap-1.5 py-0.5 text-tiny text-foreground"><PmiGlyph name={option.kind === "distance" ? "dimension" : option.kind} className="size-3" aria-hidden="true" />
      {`New ${option.label.toLowerCase()} ${call.id}`}</p>
    {option.nominal !== null && option.nominal !== undefined ? <InfoRow label="Nominal" title="Read here off the mesh; the engine measures it exactly when the model builds" copy={false}>
      <MonoValue>{mm(pmiNumber(option.nominal, 3))}</MonoValue><span className="text-muted-foreground">, measured</span></InfoRow> : null}
    {call.kind === "dimension" ? <ToleranceField value={call.tolerance} onCommit={tolerance => setCall(now => ({ ...now, tolerance }))} /> : null}
    {needsValue ? <ValueField label="Tolerance" value={call.value} onCommit={value => setCall(now => ({ ...now, value }))} /> : null}
    {call.characteristic === "position" ? <DatumPicker letters={letters} value={call.datums} onChange={datums => setCall(now => ({ ...now, datums }))} /> : null}
    {call.kind === "dimension" && !call.tolerance ? <FileSheetStatusText className="px-0">No tolerance: none is written unless you give one.</FileSheetStatusText> : null}
    <div className="flex justify-end gap-1.5 pt-1">
      <Button type="button" variant="ghost" size="xs" className="h-6 text-tiny" onClick={onCancel}>Cancel</Button>
      <Button type="button" size="xs" className="h-6 text-tiny" disabled={!ready} onClick={() => onAdd(call)} data-pmi-add="">Add to Quick Edit</Button>
    </div>
  </div>;
}

/**
 * @param {{ pmi: ReturnType<typeof import("./useXbfPmi.jsx").useXbfPmi>, picked: Parameters<typeof pmiCreateOptions>[0]["picked"],
 *   moving: boolean }} props
 *   `picked`: the faces Select has picked, what New can make of; `moving`: the parts stand elsewhere
 *   than built, so the PMI is not drawn.
 */
export default function PmiSection({ pmi, picked, moving }) {
  const options = useMemo(() => pmiCreateOptions({ picked, entries: pmi.entries }), [picked, pmi.entries]);
  const letters = useMemo(() => pmi.entries.filter(entry => entry.kind === "datum" && entry.datum?.letter).map(entry => entry.datum.letter), [pmi.entries]);
  const [draft, setDraft] = useState(null);
  const shownCount = pmi.entries.filter(entry => entry.supported).length;
  return <ToolPanel id="pmi" title="PMI" label="PMI" fit="tree" resizable collapsible={false} icon={PmiIcon}>
    <ToolPanelHeadAction>
      {pmi.editable ? <DropdownMenu modal={false}>
        <TooltipHint content="New PMI" side="bottom">
          <DropdownMenuTrigger asChild>
            <button type="button" aria-label="New PMI" data-pmi-new-menu="" className={TOOL_PANEL_BUTTON_CLASS}><Plus className="size-3" aria-hidden="true" /></button>
          </DropdownMenuTrigger>
        </TooltipHint>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuLabel className="text-muted-foreground">On the faces picked</DropdownMenuLabel>
          {options.map(option => <DropdownMenuItem key={option.kind} disabled={!option.available} data-pmi-new-kind={option.kind}
            onSelect={() => setDraft(option)}>
            <PmiGlyph name={option.kind === "distance" ? "dimension" : option.kind} className="size-3.5" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            {!option.available ? <span className="truncate text-micro text-muted-foreground">{option.need}</span> : null}
          </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu> : null}
      {shownCount ? <TooltipHint content={pmi.off ? "Show PMI" : "Hide PMI"} side="bottom">
        <button type="button" aria-label={pmi.off ? "Show PMI" : "Hide PMI"} aria-pressed={pmi.off} data-pmi-visibility-all=""
          className={TOOL_PANEL_BUTTON_CLASS} onClick={() => pmi.setOff(!pmi.off)}>
          {pmi.off ? <EyeOff className="size-3" aria-hidden="true" /> : <Eye className="size-3" aria-hidden="true" />}
        </button>
      </TooltipHint> : null}
    </ToolPanelHeadAction>
    {draft?.call ? <NewEntry key={`${draft.kind}:${draft.call.id}`} option={draft} letters={letters}
      onCancel={() => setDraft(null)} onAdd={(call) => { pmi.add(call); setDraft(null); }} /> : null}
    {moving ? <FileSheetStatusText className="py-1">Not drawn while the parts are moved: a tolerance is of the part as made.</FileSheetStatusText> : null}
    {!pmi.entries.length ? <FileSheetStatusText className="py-1">No PMI yet. Pick faces, then New.</FileSheetStatusText> : null}
    <ul className={cn("px-1 py-1 text-tiny", pmi.off && "opacity-60")} aria-label="PMI" data-pmi-rows="">
      {pmi.entries.map((entry) => {
        const hidden = pmi.hiddenIds.includes(entry.id);
        const picked = entry.id === pmi.selectedId;
        return <li key={entry.id} className="min-w-0">
          <TreeRowSurface dense active={picked} className="group/row gap-0 pr-0" style={{ "--row-actions": ROW_ACTIONS_WIDTH }} data-pmi-row={entry.id}
            onMouseEnter={() => pmi.hover(entry.id)} onMouseLeave={() => pmi.hover("")}>
            <button type="button" aria-pressed={picked} aria-label={`${entry.callout.text}${entry.statusText ? `: ${entry.statusText}` : ""}`} data-pmi-pick={entry.id}
              onClick={() => pmi.select(picked ? "" : entry.id)}
              className={cn("flex h-6 min-w-0 flex-1 items-center gap-1.5 rounded pl-1 pr-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                (hidden || !entry.supported) && "text-muted-foreground", hidden ? ROW_NAME_UNDER_ACTIONS.shown : ROW_NAME_UNDER_ACTIONS.hover)}>
              <PmiGlyph name={entry.glyph} className="size-3 shrink-0" aria-hidden="true" />
              <TreeRowLabel className="min-w-0 shrink tabular-nums">{entry.supported ? entry.callout.text : entry.label || entry.id}</TreeRowLabel>
              <TreeRowLabel className="flex-1 text-micro text-muted-foreground">{entry.supported ? entry.id : "not shown"}</TreeRowLabel>
              {entry.status !== "ok" ? <CircleAlert className={cn("size-3 shrink-0", STATUS_TEXT[entry.status])} aria-label={STATUS_WORDS[entry.status]} /> : null}
            </button>
            {entry.supported ? <RowEye id={entry.id} hidden={hidden} onToggle={pmi.toggleHidden} /> : null}
          </TreeRowSurface>
          {picked ? <EntryDetails entry={entry} pmi={pmi} letters={letters} /> : null}
        </li>;
      })}
    </ul>
  </ToolPanel>;
}
