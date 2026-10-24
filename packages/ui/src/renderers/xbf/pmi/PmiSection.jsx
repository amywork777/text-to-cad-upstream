import { useContext, useEffect, useMemo, useState } from "react";
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
import { ToolStackContext } from "../../kit/tools/ToolStack.jsx";
import { PmiGlyph, PmiIcon } from "./pmiGlyphs.jsx";
import { MAX_DATUMS, datumLetters, newPmiName, parseToleranceInput, pmiCreateOptions, toggleDatum } from "./pmiCreate.js";
import { datumDependents, datumRelationships, dimensionLimits, featureRequirements } from "./pmiReview.js";

// An engine document's **PMI**, a section of the file sidebar for a document that carries any:
// every annotation, a row each -- its glyph and what its callout says, and its eye -- in the
// document's order; the one picked opens under its row, its values read out with their units and
// where each came from (a nominal measured on the geometry or as another system's file gives it, a
// tolerance as the code gave it, or none given), its references and how they stand, what the build
// warned of, where it is placed; an annotation the viewer does not draw is a row too, saying why. Its head holds New (what the faces Select has picked can be) and
// the eye of them all. Where the document is made from code the agent can change, a value edited
// here, a label moved in the view, a placement pinned or a new annotation is a change Quick Edit
// carries to the agent (`useXbfPmi`): nothing here writes the file. A row is an annotation's `key`
// (its part's and its id), and says its id.

const EMPTY = Object.freeze([]);
const ROW_ACTIONS_WIDTH = "1.5rem";
const ROLE_NAMES = Object.freeze({ feature: "Feature", from: "From", to: "To" });
const STATUS_WORDS = Object.freeze({ ok: "", missing: "Missing", ambiguous: "Ambiguous", invalid: "Invalid" });
const STATUS_TEXT = Object.freeze({ missing: "text-destructive", invalid: "text-destructive", ambiguous: "text-amber-500" });
// What the build that served it warned of: in a warning's colour, as an ambiguous reference is.
const WARNING_TEXT = STATUS_TEXT.ambiguous;
// What an annotation's row says beside its callout: why it broke, else what the build warned of.
const rowNote = entry => [entry.statusText, ...entry.warnings].filter(Boolean).join("; ");
// Where a nominal came from: measured on the geometry by the engine, or as another system's file gives it.
const NOMINAL_SOURCE = Object.freeze({ geometry: { said: ", measured", title: "Measured on the geometry by the engine" },
  file: { said: ", from the file", title: "As the file gives it" } });
const mm = (value, unit = "mm") => `${value} ${unit}`;
// What the list follows: the faces, edges and vertices of a selection, as one key.
const selectionKeyOf = ids => JSON.stringify(ids);

function RowEye({ entry, hidden, onToggle }) {
  const action = hidden ? "Reveal" : "Hide";
  return <div data-row-actions="" className={treeRowActionsClass(hidden)}>
    <TooltipHint content={action}>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`${action} ${entry.id}`} aria-pressed={hidden} className="h-5 w-4 text-muted-foreground"
        data-pmi-visibility={entry.id} onClick={event => { event.stopPropagation(); onToggle(entry.key); }}>
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
      {/* In the order picked, primary first (a frame's order is what it means), at most three. */}
      {letters.map(letter => <button key={letter} type="button" aria-pressed={value.includes(letter)} data-pmi-datum-choice={letter}
        disabled={!value.includes(letter) && value.length >= MAX_DATUMS}
        onClick={() => onChange(toggleDatum(value, letter))}
        className={cn("h-5 min-w-5 rounded-sm border px-1 text-tiny", value.includes(letter) ? "border-foreground bg-accent text-foreground" : "border-border text-muted-foreground")}>
        {letter}
      </button>)}
    </div>
  </div>;
}

/** The values of an annotation, read out: what it is, and where every number came from. */
function EntryDetails({ entry, pmi, onSelectRelated }) {
  const editable = pmi.editable && entry.supported && entry.status === "ok";
  const construction = pmi.constructions.get(entry.key);
  const pending = pmi.changes.find(change => change.key === `edit:${entry.key}`);
  const values = pending?.values || {};
  const given = key => (Object.prototype.hasOwnProperty.call(values, key) ? values[key] : undefined);
  const limits = dimensionLimits(entry);
  const datumLinks = datumRelationships(entry, pmi.entries);
  const dependents = datumDependents(entry, pmi.entries);
  return <div className="px-2 pb-1.5 pt-0.5" data-pmi-details={entry.id}>
    {entry.statusText ? <p className={cn("flex items-start gap-1 py-0.5 text-tiny", STATUS_TEXT[entry.status])} role="status">
      <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" /><span className="min-w-0 [overflow-wrap:anywhere]">{entry.statusText}</span>
    </p> : null}
    {entry.warnings.map(warning => <p key={warning} className={cn("flex items-start gap-1 py-0.5 text-tiny", WARNING_TEXT)} role="status" data-pmi-warning="">
      <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" /><span className="min-w-0 [overflow-wrap:anywhere]">{warning}</span>
    </p>)}
    {!entry.supported ? <FileSheetStatusText className="px-0">{`Not shown: ${entry.unsupported}.`}</FileSheetStatusText> : null}
    {!entry.supported ? (entry.values || []).slice(0, 8).map(([key, value]) => <InfoRow key={key} label={key} copy={false}>{value}</InfoRow>) : null}
    {entry.kind === "dimension" && entry.supported ? <>
      {entry.dimension.nominal === null ? <InfoRow label="Nominal" copy={false}>Unknown: nothing to measure</InfoRow>
        : <InfoRow label="Nominal" title={NOMINAL_SOURCE[entry.dimension.source]?.title}><MonoValue>{mm(entry.callout.diameter ? `⌀${pmiNumber(entry.dimension.nominal, 3)}` : pmiNumber(entry.dimension.nominal, 3), entry.dimension.unit)}</MonoValue>
          <span className="text-muted-foreground">{NOMINAL_SOURCE[entry.dimension.source]?.said || ""}</span></InfoRow>}
      {entry.dimension.basic ? <InfoRow label="Tolerance" copy={false}>None: a basic dimension is exact</InfoRow>
        : editable ? <ToleranceField value={given("tolerance") === undefined ? entry.dimension.tolerance : given("tolerance")}
        onCommit={tolerance => pmi.edit(entry.key, { tolerance })} />
        : <InfoRow label="Tolerance">{entry.dimension.tolerance ? <MonoValue>{mm(pmiToleranceText(entry.dimension.tolerance).text, entry.dimension.unit)}</MonoValue> : "None given"}</InfoRow>}
      {limits ? <InfoRow label="Current limits" copy={false}><MonoValue>{mm(`${pmiNumber(limits.lower, limits.places)}–${pmiNumber(limits.upper, limits.places)}`, limits.unit)}</MonoValue></InfoRow> : null}
    </> : null}
    {entry.kind === "datum" && entry.supported ? <InfoRow label="Letter">{entry.datum.letter}</InfoRow> : null}
    {entry.kind === "geometric_tolerance" && entry.supported ? <>
      <InfoRow label="Kind">{entry.callout.title}</InfoRow>
      {editable ? <ValueField label="Tolerance" value={given("value") ?? entry.tolerance.value} onCommit={value => { if (value !== null) pmi.edit(entry.key, { value }); }} />
        : <InfoRow label="Tolerance"><MonoValue>{mm(`${entry.callout.diameter ? "⌀" : ""}${entry.callout.value}`, entry.tolerance.unit)}</MonoValue></InfoRow>}
      {entry.tolerance.characteristic === "position" ? (editable
        ? <DatumPicker letters={datumLetters(pmi.entries, entry.part)} value={given("datums") ?? entry.tolerance.datums} onChange={datums => pmi.edit(entry.key, { datums })} />
        : <InfoRow label="Datums">{entry.tolerance.datums.join(", ") || "None"}</InfoRow>) : null}
    </> : null}
    {datumLinks.length ? <div className="py-1" role="group" aria-label="Highlight datum references">
      <p className="pb-1 text-tiny text-muted-foreground">Highlight datum references</p>
      {datumLinks.map(({ letter, role, entry: datum }) => <button key={letter} type="button"
        aria-label={`Highlight ${role.toLowerCase()} datum ${letter}`} aria-pressed={Boolean(datum && pmi.datumFocus === datum.key)}
        disabled={!datum || datum.status !== "ok"} onClick={() => pmi.focusDatum(datum.key)}
        className="flex h-6 w-full items-center justify-between gap-2 rounded px-1 text-tiny hover:bg-accent aria-pressed:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
        <span>{role}</span><span>{letter}</span>
      </button>)}
    </div> : null}
    {dependents.length ? <div className="py-1 text-tiny"><p className="pb-1 text-muted-foreground">Used by</p>
      {dependents.map(item => <button key={item.key} type="button" className="block w-full rounded px-1 py-1 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onSelectRelated(item)}>{item.callout.text}</button>)}
    </div> : null}
    {entry.refs.map(ref => <InfoRow key={`${ref.role}:${ref.written}`} label={ROLE_NAMES[ref.role] || ref.role} copy={ref.ref}
      title={ref.status === "ok" ? ref.ref : `${STATUS_WORDS[ref.status]}: ${ref.written}`}>
      <span className={cn("[overflow-wrap:anywhere]", STATUS_TEXT[ref.status])}>{ref.status === "ok" ? ref.name : ref.written}</span>
      {ref.status === "ambiguous" && ref.candidates.length ? <span className="block text-muted-foreground">{`names ${ref.candidates.join(", ")}`}</span> : null}
    </InfoRow>)}
    {entry.supported ? <InfoRow label="Placed" copy={false}>{pending?.values.presentation ? "Moved, in Quick Edit" : entry.presentation ? "In code" : "Beside its feature"}</InfoRow> : null}
    {editable && construction && !entry.presentation && !pending?.values.presentation ? <Button type="button" variant="ghost" size="xs" className="-ml-1.5 h-6 text-tiny"
      data-pmi-pin={entry.id} onClick={() => pmi.pin(entry.key)}><Pin className="size-3" aria-hidden="true" />Pin placement</Button> : null}
    {pending ? <FileSheetStatusText className="px-0">In Quick Edit for the agent to write.</FileSheetStatusText> : null}
  </div>;
}

// A new annotation's glyph: a distance's, basic or not, is a dimension's.
const optionGlyph = kind => (kind === "distance" || kind === "basic" ? "dimension" : kind);

/** A new annotation being made: its kind's values to give, then Add to Quick Edit. A position's datums are its part's. */
function NewEntry({ option, onAdd, onCancel }) {
  const [call, setCall] = useState(option.call);
  const needsValue = call.kind === "geometric_tolerance";
  const ready = !needsValue || (Number.isFinite(call.value) && call.value > 0);
  return <div className="border-b border-border px-2 pb-2 pt-1" data-pmi-new={option.kind}>
    <p className="flex items-center gap-1.5 py-0.5 text-tiny text-foreground"><PmiGlyph name={optionGlyph(option.kind)} className="size-3" aria-hidden="true" />
      {`New ${newPmiName(call)}`}</p>
    {option.nominal !== null && option.nominal !== undefined ? <InfoRow label="Nominal" title="Read here off the mesh; the engine measures it exactly when the model builds" copy={false}>
      <MonoValue>{mm(pmiNumber(option.nominal, 3))}</MonoValue><span className="text-muted-foreground">, measured</span></InfoRow> : null}
    {call.kind === "dimension" && !call.basic ? <ToleranceField value={call.tolerance} onCommit={tolerance => setCall(now => ({ ...now, tolerance }))} /> : null}
    {needsValue ? <ValueField label="Tolerance" value={call.value} onCommit={value => setCall(now => ({ ...now, value }))} /> : null}
    {call.characteristic === "position" ? <DatumPicker letters={option.datums} value={call.datums} onChange={datums => setCall(now => ({ ...now, datums }))} /> : null}
    {call.kind === "dimension" && call.basic ? <FileSheetStatusText className="px-0">Exact: a basic dimension takes no tolerance.</FileSheetStatusText>
      : call.kind === "dimension" && !call.tolerance ? <FileSheetStatusText className="px-0">No tolerance: none is written unless you give one.</FileSheetStatusText> : null}
    <div className="flex justify-end gap-1.5 pt-1">
      <Button type="button" variant="ghost" size="xs" className="h-6 text-tiny" onClick={onCancel}>Cancel</Button>
      <Button type="button" size="xs" className="h-6 text-tiny" disabled={!ready} onClick={() => onAdd(call)} data-pmi-add="">Add to Quick Edit</Button>
    </div>
  </div>;
}

/**
 * @param {{ pmi: ReturnType<typeof import("./useXbfPmi.jsx").useXbfPmi>, picked: Parameters<typeof pmiCreateOptions>[0]["picked"],
 *   selectedFeatureIds?: readonly string[], moving: boolean, request?: { kind: string, key: number } | null,
 *   onRequestDone?: () => void }} props
 *   `picked`: the faces Select has picked, what New can make of; `selectedFeatureIds`: the faces,
 *   edges and vertices Select has picked, whose requirements the list narrows to while no
 *   annotation is picked; `moving`: the parts stand elsewhere than built, so the PMI is not drawn;
 *   `request`: a kind asked for from a face's menu ("Add datum"), which opens the section on its
 *   form; `onRequestDone`: the form has gone (added or cancelled).
 */
export default function PmiSection({ pmi, picked, selectedFeatureIds = EMPTY, moving, request = null, onRequestDone }) {
  // What is already asked for counts as taken: a second new one never reuses a pending id or letter.
  const options = useMemo(() => pmiCreateOptions({ picked, entries: pmi.entries, pending: pmi.pending }), [picked, pmi.entries, pmi.pending]);
  const [draft, setDraft] = useState(null);
  const featureIds = pmi.selectedEntry ? pmi.selectedEntry.featureIds : selectedFeatureIds;
  const selectionKey = selectionKeyOf(featureIds);
  const [showAllFor, setShowAllFor] = useState("");
  const filtered = featureIds.length > 0 && showAllFor !== selectionKey;
  const visible = filtered ? featureRequirements(pmi.entries, featureIds) : pmi.entries;
  // A related annotation picked from another's values: the whole list, for the selection it makes.
  const selectRelated = (entry) => { setShowAllFor(selectionKeyOf(entry.featureIds)); pmi.select(entry.key); };
  // A kind asked for from a face's menu: its form, the section open on it.
  const stack = useContext(ToolStackContext);
  useEffect(() => {
    if (!request) return;
    const option = options.find(item => item.kind === request.kind && item.available);
    if (option) setDraft(option);
    stack?.open?.("pmi");
    // Once per request: the options follow the pick, which the request has just made.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.key]);
  const closeDraft = () => { setDraft(null); onRequestDone?.(); };
  const shownCount = pmi.entries.filter(entry => entry.supported).length;
  return <ToolPanel id="pmi" title="PMI" label="PMI" icon={PmiIcon} fit="tree" resizable collapsible={false}>
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
            <PmiGlyph name={optionGlyph(option.kind)} className="size-3.5" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            {!option.available ? <span className="truncate text-micro text-muted-foreground">{option.need}</span> : null}
          </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu> : null}
      {shownCount ? <TooltipHint content={pmi.off ? "Reveal PMI" : "Hide PMI"} side="bottom">
        <button type="button" aria-label={pmi.off ? "Reveal PMI" : "Hide PMI"} aria-pressed={pmi.off} data-pmi-visibility-all=""
          className={TOOL_PANEL_BUTTON_CLASS} onClick={() => pmi.setOff(!pmi.off)}>
          {pmi.off ? <EyeOff className="size-3" aria-hidden="true" /> : <Eye className="size-3" aria-hidden="true" />}
        </button>
      </TooltipHint> : null}
    </ToolPanelHeadAction>
    {draft?.call ? <NewEntry key={`${draft.kind}:${draft.call.id}`} option={draft}
      onCancel={closeDraft} onAdd={(call) => { pmi.add(draft.part, call); closeDraft(); }} /> : null}
    {moving ? <FileSheetStatusText className="py-1">Not drawn while the parts are moved: a tolerance is of the part as made.</FileSheetStatusText> : null}
    {!pmi.entries.length && !draft ? <FileSheetStatusText className="py-1">No PMI yet: add some from a face's menu.</FileSheetStatusText> : null}
    {featureIds.length ? <div className="flex flex-wrap items-center justify-between gap-1 border-b border-border/60 px-2 py-1 text-tiny">
      <span className="text-muted-foreground">{filtered ? `${visible.length} requirement${visible.length === 1 ? "" : "s"} for selection` : "All PMI"}</span>
      <Button type="button" variant="ghost" size="xs" className="h-6 text-tiny" onClick={() => setShowAllFor(filtered ? selectionKey : "")}>{filtered ? "Show all PMI" : "For selection"}</Button>
    </div> : null}
    {filtered && !visible.length ? <FileSheetStatusText className="py-1">No PMI is attached to this selection. This does not establish that no requirement is needed.</FileSheetStatusText> : null}
    <ul className={cn("px-1 py-1 text-tiny", pmi.off && "opacity-60")} aria-label="PMI" data-pmi-rows="">
      {visible.map((entry) => {
        const hidden = pmi.hiddenKeys.includes(entry.key);
        const picked = entry.key === pmi.selectedKey;
        return <li key={entry.key} className="min-w-0">
          <TreeRowSurface dense active={picked} className="group/row gap-0 pr-0" style={{ "--row-actions": ROW_ACTIONS_WIDTH }} data-pmi-row={entry.id}
            onMouseEnter={() => pmi.hover(entry.key)} onMouseLeave={() => pmi.hover("")}>
            <button type="button" aria-pressed={picked} aria-label={`${entry.callout.text}${rowNote(entry) ? `: ${rowNote(entry)}` : ""}`} data-pmi-pick={entry.id}
              onClick={() => pmi.select(picked ? "" : entry.key)}
              className={cn("flex h-full min-w-0 flex-1 items-center gap-1.5 rounded pl-1 pr-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                (hidden || !entry.supported) && "text-muted-foreground", hidden ? ROW_NAME_UNDER_ACTIONS.shown : ROW_NAME_UNDER_ACTIONS.hover)}>
              <PmiGlyph name={entry.glyph} className="size-3 shrink-0" aria-hidden="true" />
              <TreeRowLabel className="min-w-0 shrink tabular-nums">{entry.supported ? entry.callout.text : entry.label || entry.id}</TreeRowLabel>
              {/* Its id, where it says more than the callout (a datum's id is its letter). */}
              <TreeRowLabel className="flex-1 text-micro text-muted-foreground">{!entry.supported ? "not shown" : entry.kind === "datum" ? "" : entry.id}</TreeRowLabel>
              {entry.status !== "ok" ? <CircleAlert className={cn("size-3 shrink-0", STATUS_TEXT[entry.status])} aria-label={STATUS_WORDS[entry.status]} />
                : entry.warnings.length ? <CircleAlert className={cn("size-3 shrink-0", WARNING_TEXT)} aria-label="Warning" /> : null}
            </button>
            {entry.supported ? <RowEye entry={entry} hidden={hidden} onToggle={pmi.toggleHidden} /> : null}
          </TreeRowSurface>
          {picked ? <EntryDetails entry={entry} pmi={pmi} onSelectRelated={selectRelated} /> : null}
        </li>;
      })}
    </ul>
  </ToolPanel>;
}
