import { useState } from "react";
import {
  FILE_SHEET_STATUS_TEXT_CLASSES,
  FileSheetCheckboxRow,
  FileSheetControlRow,
  FileSheetSelectRow,
  FileSheetSettingsSection,
  FileSheetValueInput
} from "../../kit/inspector/FileSheet.js";
import { DrawingIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { sameValues } from "./editMode.js";

// The ISO sheets a drawing goes on, as SolidWorks' Sheet Properties lists its sheet formats.
const SIZES = Object.freeze(["A4", "A3", "A2", "A1", "A0"].map(size => ({ value: size, label: size })));
// The title block's fields, as its cells name them.
const FIELDS = Object.freeze([["title", "Title"], ["part_number", "Part number"], ["material", "Material"], ["revision", "Revision"],
  ["author", "Drawn by"]]);

/** One title block field, typed over. */
function FieldRow({ label, value, onChange }) {
  return <FileSheetControlRow label={label} trailing={<FileSheetValueInput value={value} ariaLabel={label} inputMode="text"
    className="w-36 text-left" onValueCommit={draft => onChange(String(draft).trim())} />} />;
}

/**
 * The part's drawing, as SolidWorks' Sheet Properties set one: the sheet's size and scale, its
 * title block, and whether the isometric is drawn. OK writes them into the drawing's script and
 * draws its PDF again (`edit.drawing`); the views and dimensions follow the part on their own.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function DrawingPanel({ edit }) {
  const drawing = edit.state?.drawing || {};
  const opened = { size: drawing.size || "A3", scale: drawing.scale || "1:1", iso: Boolean(drawing.iso),
    ...Object.fromEntries(FIELDS.map(([key]) => [key, drawing[key] || ""])) };
  const [values, setValues] = useState(opened);
  const set = key => value => setValues(current => ({ ...current, [key]: value }));
  const ok = async () => {
    const reply = await edit.drawing({ sheet: values });
    if (reply?.ok) edit.stopInspecting();
  };
  return <div role="dialog" aria-label="Drawing" data-cad-drawing="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <DrawingIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Drawing</h2>
    </div>
    <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} py-1.5`}>
      {drawing.drawn ? `Drawn to ${drawing.pdf} by ${drawing.script}. Its views and dimensions follow the part.`
        : `${drawing.script} has not drawn ${drawing.pdf} yet. OK draws it.`}
    </p>
    <FileSheetSettingsSection title="Sheet" sectionId="drawing-sheet">
      <FileSheetSelectRow label="Size" value={values.size} options={SIZES} onValueChange={set("size")} />
      <FileSheetControlRow label="Scale" trailing={<FileSheetValueInput value={values.scale} ariaLabel="Scale" inputMode="text"
        onValueCommit={draft => set("scale")(String(draft).trim())} />} />
    </FileSheetSettingsSection>
    <FileSheetSettingsSection title="Title Block" sectionId="drawing-title">
      {FIELDS.map(([key, label]) => <FieldRow key={key} label={label} value={values[key]} onChange={set(key)} />)}
    </FileSheetSettingsSection>
    <FileSheetSettingsSection title="Views" sectionId="drawing-views">
      <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Top, front and right, in third angle.</p>
      <FileSheetCheckboxRow label="Isometric view" checked={values.iso} onCheckedChange={value => set("iso")(Boolean(value))} />
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onOk={() => void ok()} onCancel={edit.stopInspecting} okDisabled={sameValues(values, opened) || edit.saving} busy={edit.saving} />
  </div>;
}
