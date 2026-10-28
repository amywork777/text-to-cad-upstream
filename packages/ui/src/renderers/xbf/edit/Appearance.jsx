import { useState } from "react";
import { FileSheetControlRow, FileSheetSettingsSection, FileSheetValueInput } from "../../kit/inspector/FileSheet.js";
import { AppearanceIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";

// A product palette to start from, as SolidWorks' Appearances offer plastics by color.
const SWATCHES = Object.freeze([
  ["White", "#F4F4F2"], ["Light gray", "#C9CCD1"], ["Gray", "#8A8F98"], ["Black", "#1E1F22"], ["Cream", "#FFF0C9"],
  ["Yellow", "#F2C14E"], ["Orange", "#E87A35"], ["Red", "#D9453D"], ["Lilac", "#B7A1D7"], ["Blue", "#3E6FD8"],
  ["Teal", "#2E9C95"], ["Green", "#3C9A5F"],
]);
const HEX = /^#[0-9A-F]{6}$/;
const hexOf = text => {
  const written = String(text ?? "").trim().toUpperCase();
  return HEX.test(written) ? written : HEX.test(`#${written}`) ? `#${written}` : null;
};

/**
 * Appearance, as SolidWorks' Edit Appearance colors a part: its color, picked from a swatch, the
 * color wheel or typed as a hex, written into the part's script by OK (`edit.paint`); the part is
 * built again with it. Opens on the color the part shows.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function Appearance({ edit }) {
  const shown = edit.state?.color || "#C9CCD1";
  const [color, setColor] = useState(shown);
  const ok = async () => {
    const reply = await edit.paint(color);
    if (reply?.ok) edit.stopInspecting();
  };
  return <div role="dialog" aria-label="Appearance" data-cad-appearance="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <AppearanceIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Edit Object Display</h2>
    </div>
    <FileSheetSettingsSection title="Color" sectionId="appearance-color">
      <div role="group" aria-label="Swatches" className="grid grid-cols-6 gap-1.5 px-2 pb-1.5">
        {SWATCHES.map(([name, hex]) => <button key={hex} type="button" aria-label={name} aria-pressed={color === hex} title={name}
          className="h-6 rounded-md border border-border outline-none ring-offset-1 ring-offset-background focus-visible:ring-2 focus-visible:ring-ring/45 aria-pressed:ring-2 aria-pressed:ring-foreground"
          style={{ background: hex }} onClick={() => setColor(hex)} />)}
      </div>
      <FileSheetControlRow label="Color" trailing={<input type="color" aria-label="Color wheel" value={color.toLowerCase()}
        className="h-6 w-10 cursor-pointer rounded border border-border bg-transparent p-0" onChange={event => setColor(event.currentTarget.value.toUpperCase())} />} />
      <FileSheetControlRow label="Hex" trailing={<FileSheetValueInput value={color} ariaLabel="Hex"
        onValueCommit={draft => { const hex = hexOf(draft); if (hex) setColor(hex); }} />} />
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onOk={() => void ok()} onCancel={edit.stopInspecting} okDisabled={color === shown} busy={edit.saving} />
  </div>;
}
