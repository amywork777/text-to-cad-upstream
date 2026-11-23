import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@cad/ui/utils";
import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetControlRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import {
  FileSheetCheckboxRow,
  FileSheetSelectRow
} from "../../kit/inspector/FileSheetRows.js";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import ErrorWords from "./ErrorWords.jsx";
import { FeatureIcon } from "./featureIcons.jsx";
import { customChanged, customDefinition, customGroups, customRequest, customValues, pickWords, picksOfKind } from "./customFeature.js";
import { selectionItems } from "./editMode.js";
import { isEdgeItem, isFaceItem } from "./selectors.js";

const PREVIEW_WAIT_MS = 250;

/**
 * A custom feature's dialog, as Onshape opens a FeatureScript feature's: built from its declaration
 * (`cad.build123d.feature`), one control for each parameter, the ungrouped ones first and then each
 * group, a group the feature folds starting folded. A number has its unit, a switch is a check box, an
 * enum a list of its choices' labels, and faces or edges a pick field that takes the model's selection
 * while it is the active one, as an Onshape query box does. Opened from the toolbar's Custom group (a new
 * call, its defaults filled in) or by Edit Feature (the call's values now). The preview is the part with
 * the call as typed; OK writes it (`edit.run`, the engine's custom command). A refusal says the feature's
 * own words (`FeatureError`) above the dialog and marks the parameter they are about in red, as
 * FeatureScript's regenError marks its faulty parameters.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>, references?: any[] }} props
 */
export default function EditCustomFeature({ edit, references = [] }) {
  const definition = useMemo(() => customDefinition(edit.state, edit.command, edit.editing), [edit.state, edit.command, edit.editing]);
  const [values, setValues] = useState(() => customValues(definition));
  const [picks, setPicks] = useState({});
  const pickParams = (definition?.params || []).filter(param => param.kind === "faces" || param.kind === "edges");
  // The pick field the model's selection goes to: a new call's first, until another is pressed.
  const [active, setActive] = useState(() => (definition?.editing ? null : pickParams[0]?.name ?? null));
  const [faulty, setFaulty] = useState(null);
  const items = useMemo(() => selectionItems(references), [references]);
  const activeParam = pickParams.find(param => param.name === active) || null;
  const selectionKey = JSON.stringify(items);
  useEffect(() => {
    if (!activeParam) return;
    const taken = picksOfKind(JSON.parse(selectionKey), activeParam.kind, isFaceItem, isEdgeItem);
    setPicks(current => ({ ...current, [activeParam.name]: taken }));
  }, [selectionKey, activeParam]);

  const request = definition ? customRequest(definition, values, picks) : null;
  const wanted = request && edit.previewOn !== false && customChanged(request) ? request : null;
  const wantedRef = useRef(wanted);
  wantedRef.current = wanted;
  const wantedKey = wanted ? JSON.stringify(wanted) : "";
  const { previewFeature } = edit;
  useEffect(() => {
    if (typeof previewFeature !== "function") return undefined;
    const timer = setTimeout(() => previewFeature(wantedRef.current), wantedKey ? PREVIEW_WAIT_MS : 0);
    return () => clearTimeout(timer);
  }, [wantedKey, edit.state, previewFeature]);
  const shown = edit.featurePreview || null;
  const marked = faulty || (shown?.status === "failed" ? shown.featureError?.param : null) || null;

  if (!definition) return null;
  const title = definition.name;
  const set = name => value => { setFaulty(null); setValues(current => ({ ...current, [name]: value })); };
  const ok = async () => {
    if (!customChanged(request)) { edit.close(); return; }
    const reply = await edit.run(request);
    if (!reply?.ok) setFaulty(reply?.featureError?.param || null);
  };
  const label = param => <span className={cn(param.name === marked && "text-destructive")}>{param.label}</span>;
  const control = param => {
    const invalid = param.name === marked;
    if (param.kind === "bool") {
      return <FileSheetCheckboxRow key={param.name} label={param.label} checked={values[param.name] === true} disabled={edit.saving}
        onCheckedChange={set(param.name)} className={cn(invalid && "text-destructive")} />;
    }
    if (param.kind === "enum") {
      return <FileSheetSelectRow key={param.name} label={label(param)} ariaLabel={param.label} value={String(values[param.name] ?? "")}
        onValueChange={set(param.name)} options={(param.choices || []).map(choice => ({ value: choice.value, label: choice.label }))} />;
    }
    if (param.kind === "faces" || param.kind === "edges") {
      const on = active === param.name;
      return <FileSheetControlRow key={param.name} label={label(param)} trailing={<button type="button" aria-pressed={on}
        aria-label={`${param.label}: ${pickWords(param, picks[param.name], definition.editing)}`} disabled={edit.saving}
        onClick={() => { setFaulty(null); setActive(on ? null : param.name); }}
        className={cn("flex h-6 min-w-0 max-w-[10rem] items-center rounded-md border px-2 text-tiny transition-colors",
          on ? "border-info bg-info/10 text-foreground" : "border-input text-muted-foreground hover:bg-accent",
          invalid && "border-destructive")}>
        <span className="truncate">{pickWords(param, picks[param.name], definition.editing)}</span>
      </button>} />;
    }
    return <FileSheetControlRow key={param.name} label={label(param)} trailing={<span className="flex shrink-0 items-center gap-1">
      <FileSheetValueInput value={values[param.name] ?? ""} ariaLabel={param.label} disabled={edit.saving}
        aria-invalid={invalid || undefined} className={cn(invalid && "border-destructive")}
        onValueCommit={draft => set(param.name)(String(draft).trim())} />
      <span className="w-4 text-tiny text-muted-foreground">{param.unit || (param.kind === "angle" ? "deg" : "")}</span>
    </span>} />;
  };
  const sections = customGroups(definition);
  return <div role="dialog" aria-label={title} data-cad-edit-command="custom" className="flex shrink-0 flex-col"
    onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); edit.close(); return; }
      if (event.key === "Enter" && !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(event.target?.tagName)) {
        event.preventDefault(); event.stopPropagation(); void ok();
      }
    }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <FeatureIcon kind={definition.name} />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">{title}</h2>
      <button type="button" aria-label="Close" title="Close" disabled={edit.saving} onClick={edit.close}
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:opacity-40 [&_svg]:size-3.5">
        <X aria-hidden="true" />
      </button>
    </div>
    {definition.doc ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pt-1.5`}>{definition.doc}</p> : null}
    <div className="py-1">
      {sections.map(section => section.title === null
        ? <div key="" className="space-y-1">{section.params.map(control)}</div>
        : <FoldedSection key={section.title} title={section.title} folded={section.folded && !section.params.some(param => param.name === marked)}>
          {section.params.map(control)}
        </FoldedSection>)}
    </div>
    {activeParam ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>
      Select {activeParam.kind} on the model for {activeParam.label}.</p> : null}
    {/* The preview's refusal, unless OK's own already says it above the dialog (`edit.error`): the words once. */}
    {shown?.status === "failed" && !edit.error ? <ErrorWords error={shown.error} className="px-2 pb-1 leading-4" aria-live="polite" /> : null}
    {edit.saving ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`} aria-live="polite">Applying</p> : null}
    <ConfirmButtons onOk={() => void ok()} onCancel={edit.close} busy={edit.saving} className="border-t border-border px-2 py-2" />
  </div>;
}

/** A group of the dialog, folded until its title is pressed when the feature folds it (FeatureScript's "Collapsed By Default"). */
function FoldedSection({ title, folded, children }) {
  const [open, setOpen] = useState(!folded);
  useEffect(() => { if (!folded) setOpen(true); }, [folded]);
  return <FileSheetSettingsSection title={title} sectionId={title} enabled={open} onEnabledChange={setOpen}>{children}</FileSheetSettingsSection>;
}
