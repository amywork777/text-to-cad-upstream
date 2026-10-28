import { useState } from "react";
import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetControlRow,
  FileSheetSelectRow,
  FileSheetSettingsSection
} from "../../kit/inspector/FileSheet.js";
import { MassPropertiesIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { inertiaRows, massRows } from "./editMode.js";

const NONE = "none";

/**
 * Mass Properties, as SolidWorks' Evaluate tab shows them in a dialog of their own: the material
 * the part is weighed in (the project's own as it opens, or any of the table's picked), and what
 * the server worked out of the part as it is (`edit.mass`): its mass in that material, volume,
 * surface area, center of mass (marked on the model), overall size and, with a material, its
 * moments of inertia, in the part's units. Close,
 * or Escape, puts it away.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function MassProperties({ edit }) {
  const units = edit.state?.units || "mm";
  const mass = edit.mass;
  const [picked, setPicked] = useState(null);
  // The part's own material, as its script keeps it ("" for none: then the project's is weighed in).
  const own = edit.state?.material || "";
  const key = picked ?? mass?.material ?? NONE;
  const material = (mass?.materials || []).find(each => each.key === key) || null;
  const rows = mass?.volume ? massRows(mass, units, material?.density || null) : [];
  const inertia = mass?.volume ? inertiaRows(mass, units, material?.density || null) : [];
  return <div role="dialog" aria-label="Mass Properties" data-cad-mass-properties="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <MassPropertiesIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Mass Properties</h2>
    </div>
    <FileSheetSettingsSection title="Material" sectionId="mass-material">
      <FileSheetSelectRow label="Material" value={key} onValueChange={setPicked}
        options={[{ value: NONE, label: "None" }, ...(mass?.materials || []).map(each => ({ value: each.key, label: each.name }))]} />
      {material ? <FileSheetControlRow label="Density" value={`${material.density} g/cm³`} />
        : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Pick a material to weigh the part.</p>}
      {/* Edit Material, as SolidWorks applies one: kept in the part (its script's MATERIAL), weighed in from then on. */}
      {typeof edit.setMaterial === "function" && key !== (own || NONE) ? <div className="flex justify-end px-2 pb-1.5">
        <button type="button" data-cad-apply-material="" disabled={edit.saving}
          className="rounded-md border border-border px-2 py-0.5 text-tiny text-foreground hover:bg-accent disabled:opacity-40"
          onClick={() => void edit.setMaterial(key === NONE ? "" : key)}>{key === NONE ? "Remove from Part" : "Apply to Part"}</button>
      </div> : null}
    </FileSheetSettingsSection>
    <FileSheetSettingsSection title="Properties" sectionId="mass-properties">
      {mass?.status === "failed" ? <p className="px-2 pb-1 text-tiny leading-4 text-destructive" aria-live="polite">{mass.error}</p>
        : rows.length ? rows.map(row => <FileSheetControlRow key={row.label} label={row.label} value={row.value} />)
          : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`} aria-live="polite">Working out the mass properties</p>}
    </FileSheetSettingsSection>
    {/* Moments of inertia, about the center of mass: they need the material's density. */}
    {inertia.length ? <FileSheetSettingsSection title="Moments of Inertia" sectionId="mass-inertia">
      {inertia.map(row => <FileSheetControlRow key={row.label} label={row.label} value={row.value} />)}
    </FileSheetSettingsSection> : null}
    <ConfirmButtons className="border-t border-border px-2 py-2" onCancel={edit.stopInspecting} cancelLabel="Close" />
  </div>;
}
