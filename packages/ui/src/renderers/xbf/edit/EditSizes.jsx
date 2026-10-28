import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { FILE_SHEET_STATUS_TEXT_CLASSES, FileSheetControlRow, FileSheetValueInput } from "../../kit/inspector/FileSheet.js";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { withUnit } from "./editMode.js";
import { FeatureIcon } from "./featureIcons.jsx";

/**
 * The sizes of a feature's row, labelled as the row has them: two of one label told apart by
 * their order ("X", "X (2)", as a hole drilled at two places has).
 */
export function sizeRows(row) {
  const seen = new Map();
  return (row?.inputs || []).map((input, index) => {
    const count = (seen.get(input.label) || 0) + 1;
    seen.set(input.label, count);
    return { index, label: count > 1 ? `${input.label} (${count})` : input.label, display: String(input.display ?? ""), unit: input.unit || "",
      // The files its numbers are written in (a leaf is `file:line:column`).
      files: [...new Set((input.leaves || []).map(leaf => String(leaf).split(":")[0]))] };
  });
}

/** The files other than the row's own that a feature's sizes are written in: a helper's, `sizes.py`. */
export const sharedFiles = (rows, file) => [...new Set(rows.flatMap(row => row.files))].filter(each => each && each !== file);

/**
 * Edit Feature on a feature no command writes, as a CAD tool opens any feature: a Block or a
 * Cylinder placed with `Pos`, a hole cut as a cylinder, one made in a helper's file. Its row's sizes,
 * typed over, and OK writes those changed together, one change to undo (`edit.setSizes`). Where a
 * size is written in another file, it says so: changing it there changes every part that uses it.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function EditSizes({ edit }) {
  const editing = edit.editing;
  const row = (edit.state?.rows || []).find(each => each.key === editing?.row) || null;
  const rows = sizeRows(row);
  const [values, setValues] = useState(() => Object.fromEntries(rows.map(each => [each.index, each.display])));
  // The preview, as every command's: the part with the sizes typed, what it adds in amber and what it
  // takes away in red, asked again as a size is typed over (`edit.previewSizes`).
  const typed = rows.filter(each => String(values[each.index] ?? "").trim() !== each.display && String(values[each.index] ?? "").trim())
    .map(each => ({ index: each.index, text: String(values[each.index]).trim() }));
  // Nothing typed yet, the feature as it is.
  const previewKey = row && edit.previewOn !== false ? JSON.stringify([row.key, typed]) : "";
  const { previewSizes, previewFeature } = edit;
  useEffect(() => {
    if (typeof previewSizes !== "function") return undefined;
    const timer = setTimeout(() => {
      if (!previewKey) { previewFeature?.(null); return; }
      const [key, values] = JSON.parse(previewKey);
      previewSizes({ row: key, values });
    }, 250);
    return () => clearTimeout(timer);
  }, [previewKey, previewSizes, previewFeature]);
  if (!editing || !row) return null;
  const title = editing.title || "Edit Feature";
  const changed = rows.filter(each => String(values[each.index] ?? "").trim() !== each.display);
  const shared = sharedFiles(rows, row.file);
  const ok = async () => {
    if (!changed.length) { edit.close(); return; }
    await edit.setSizes(row.key, changed.map(each => ({ index: each.index, text: String(values[each.index]).trim() })),
      changed.map(each => `${each.label.toLowerCase()} ${withUnit(String(values[each.index]).trim(), each.unit)}`));
  };
  return <div role="dialog" aria-label={title} data-cad-edit-command="sizes" className="flex shrink-0 flex-col"
    onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); edit.close(); return; }
      // Enter is OK, as in SolidWorks' PropertyManager; in a box it sets the value typed there first.
      if (event.key === "Enter" && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) { event.preventDefault(); event.stopPropagation(); void ok(); }
    }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <FeatureIcon kind={editing.kind || "Extrude"} />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">{title}</h2>
      <button type="button" aria-label="Close" title="Close" disabled={edit.saving} onClick={edit.close}
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:opacity-40 [&_svg]:size-3.5">
        <X aria-hidden="true" />
      </button>
    </div>
    {shared.length ? <p role="note" className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pt-1.5`}>
      Some sizes are in {shared.join(" and ")}. Changing them changes every part that uses {shared.length > 1 ? "those files" : "it"}.</p> : null}
    <div className="py-1">
      {rows.map(each => <FileSheetControlRow key={each.index} label={each.label} trailing={<span className="flex shrink-0 items-center gap-1">
        <FileSheetValueInput value={values[each.index] ?? ""} ariaLabel={each.label} disabled={edit.saving}
          onValueCommit={draft => setValues(current => ({ ...current, [each.index]: String(draft).trim() }))} />
        <span className="w-4 text-micro text-muted-foreground">{each.unit}</span>
      </span>} />)}
    </div>
    {edit.saving ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-2`} aria-live="polite">Applying</p> : null}
    <ConfirmButtons onOk={() => void ok()} onCancel={edit.close} busy={edit.saving} className="border-t border-border px-2 py-2" />
  </div>;
}
