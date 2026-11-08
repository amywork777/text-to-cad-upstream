import { useEffect, useState } from "react";
import { FILE_SHEET_STATUS_TEXT_CLASSES, FileSheetSettingsSection } from "../../kit/inspector/FileSheet.js";
import { InsertComponentIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";

/**
 * Insert Components, as SolidWorks' adds a part to an assembly: the project's part scripts listed
 * (`edit.insertable`), one picked, and OK imports it in the assembly's script and adds its part to
 * what the assembly returns, where the part is made, for mates to place. A part already in the
 * assembly is listed, and refused with why.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function InsertComponents({ edit }) {
  const [parts, setParts] = useState(null);
  const [picked, setPicked] = useState("");
  useEffect(() => {
    let stopped = false;
    void edit.insertable().then(found => { if (!stopped) setParts(found); });
    return () => { stopped = true; };
  }, [edit.insertable]);
  const blocked = !picked ? "Pick a part to insert." : "";
  const ok = async () => {
    const reply = await edit.mate({ insert: picked });
    if (reply?.ok) edit.stopInspecting();
  };
  return <div role="dialog" aria-label="Insert Components" data-cad-insert="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <InsertComponentIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Insert Components</h2>
    </div>
    <FileSheetSettingsSection title="Part to Insert" sectionId="insert-part">
      {parts === null ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>Finding the project's parts</p>
        : parts.length === 0 ? <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1`}>No other part scripts in this project.</p>
          : <div role="listbox" aria-label="Parts" className="flex flex-col pb-1">
            {parts.map(part => <button key={part} type="button" role="option" aria-selected={picked === part}
              className={`truncate rounded px-1.5 py-1 text-left text-tiny ${picked === part ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"}`}
              onClick={() => setPicked(part)} onDoubleClick={() => { setPicked(part); void edit.mate({ insert: part }).then(reply => { if (reply?.ok) edit.stopInspecting(); }); }}>
              {part}
            </button>)}
          </div>}
    </FileSheetSettingsSection>
    <ConfirmButtons className="border-t border-border px-2 py-2" onOk={() => void ok()} onCancel={edit.stopInspecting}
      okDisabled={Boolean(blocked) || edit.saving} okReason={blocked} busy={edit.saving} />
  </div>;
}
