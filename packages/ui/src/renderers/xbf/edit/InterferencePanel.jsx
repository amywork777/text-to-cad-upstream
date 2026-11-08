import { FILE_SHEET_STATUS_TEXT_CLASSES, FileSheetControlRow, FileSheetSettingsSection } from "../../kit/inspector/FileSheet.js";
import { InterferenceIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { interferenceRows } from "./editMode.js";

/**
 * Interference Detection, as SolidWorks' Evaluate tab runs it on an assembly: each two parts (or a
 * part's bodies) whose solids overlap, with the volume they share, largest first, and that shared
 * material drawn red on the model. Touching is not interfering.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function InterferencePanel({ edit }) {
  const units = edit.state?.units || "mm";
  const found = edit.interference;
  const rows = found?.pairs ? interferenceRows(found.pairs, units) : [];
  return <div role="dialog" aria-label="Interference Detection" data-cad-interference="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <InterferenceIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Simple Interference</h2>
    </div>
    <FileSheetSettingsSection title="Results" sectionId="interference-results">
      {found?.status === "failed" ? <p className="px-2 pb-1 text-tiny leading-4 text-destructive" aria-live="polite">{found.error}</p>
        : !found || found.status === "updating" ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">Checking every two parts</p>
          : rows.length ? rows.map(row => <FileSheetControlRow key={row.key} label={row.label} value={row.value} />)
            : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">
              {found.parts > 1 ? `No interferences: none of the ${found.parts} parts overlap.` : "There is only one part or body to check."}
            </p>}
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onCancel={edit.stopInspecting} cancelLabel="Close" />
  </div>;
}
