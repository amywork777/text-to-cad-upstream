import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetCheckboxRow,
  FileSheetControlRow,
  FileSheetSelectRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import { DraftAnalysisIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { DRAFT_CLASSES, draftRows, PULL_PLANES } from "./editMode.js";

/**
 * Draft Analysis, as SolidWorks' Evaluate tab checks a molded part: the direction of pull (an
 * origin plane's normal, reversed if need be) and the least draft a wall needs; the part shaded
 * over (`DraftAnalysisLayer`) green where it faces the pull steeply enough, red where it faces
 * away, yellow where a wall stands too near the pull to come out of a mold, each with its area.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function DraftAnalysis({ edit }) {
  const units = edit.state?.units || "mm";
  const settings = edit.draftSettings;
  const check = edit.draftCheck;
  const rows = check?.areas ? draftRows(check.areas, units) : [];
  return <div role="dialog" aria-label="Draft Analysis" data-cad-draft-analysis="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <DraftAnalysisIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Draft Analysis</h2>
    </div>
    <FileSheetSettingsSection title="Analysis Parameters" sectionId="draft-parameters">
      <FileSheetSelectRow label="Direction of pull" value={settings.plane} options={PULL_PLANES}
        onValueChange={plane => edit.setDraftSettings({ plane })} />
      <FileSheetCheckboxRow label="Reverse direction" checked={Boolean(settings.reverse)}
        onCheckedChange={value => edit.setDraftSettings({ reverse: Boolean(value) })} />
      <FileSheetControlRow label="Draft angle" trailing={<span className="flex shrink-0 items-center gap-1">
        <FileSheetValueInput value={String(settings.angle)} ariaLabel="Draft angle"
          onValueCommit={draft => { const angle = Number(String(draft).trim()); if (Number.isFinite(angle) && angle >= 0 && angle < 90) edit.setDraftSettings({ angle }); }} />
        <span className="w-6 text-micro text-muted-foreground">deg</span>
      </span>} />
    </FileSheetSettingsSection>
    <FileSheetSettingsSection title="Color Settings" sectionId="draft-colors">
      {check?.status === "failed" ? <p className="px-2 pb-1 text-tiny leading-4 text-destructive" aria-live="polite">{check.error}</p>
        : rows.length ? rows.map(row => <FileSheetControlRow key={row.key} label={<span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 shrink-0 rounded-sm" style={{ background: DRAFT_CLASSES[row.key].css }} />{row.label}
        </span>} value={row.value} />)
          : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">Checking the draft</p>}
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onCancel={edit.stopInspecting} cancelLabel="Close" />
  </div>;
}
