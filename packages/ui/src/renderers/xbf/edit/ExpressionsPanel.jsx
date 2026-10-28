import { FileSheetSettingsSection } from "../../kit/inspector/FileSheet.js";
import { ExpressionsIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { ExpressionRows } from "./EditTree.jsx";

/**
 * Expressions, as NX's dialog lists them: the part's user expressions, each named size with its value
 * typed over in place (one number in the part's script, the part built again with it), and Add
 * expression for a new one. The Inspect tab's Expressions opens it in the card the other Inspect
 * panels open in. It changes nothing by itself; Close, or Escape, puts it away.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function ExpressionsPanel({ edit }) {
  return <div role="dialog" aria-label="Equations" data-cad-expressions="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <ExpressionsIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Equations</h2>
    </div>
    <FileSheetSettingsSection title="Global Variables" sectionId="expressions-user">
      <div className="flex flex-col px-2 pb-1"><ExpressionRows edit={edit} /></div>
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onCancel={edit.stopInspecting} cancelLabel="Close" />
  </div>;
}
