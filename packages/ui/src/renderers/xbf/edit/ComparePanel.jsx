import { useEffect, useRef } from "react";
import { cn } from "@text-to-cad/ui/utils";
import { FILE_SHEET_STATUS_TEXT_CLASSES, FileSheetSettingsSection } from "../../kit/inspector/FileSheet.js";
import { CompareIcon } from "./cadIcons.jsx";
import { ConfirmButtons } from "./ConfirmButtons.jsx";
import { compareVolume, timeAgo } from "./editMode.js";

// A version as the list names it: before the files that changed after it.
const changedWords = version => (version.changed.length ? `before ${version.changed.join(", ")} changed` : "before a change");

/**
 * Compare, as SolidWorks' Compare Geometry shows what changed between two versions of a part: the
 * versions edit mode read this session (each change the agent or a hand edit made), newest first;
 * one picked draws the material the part has gained since it in amber and what it has lost in red,
 * with their volumes. It changes nothing.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode> }} props
 */
export default function ComparePanel({ edit }) {
  const { compare } = edit;
  const comparison = edit.comparison;
  // Read again as the part changes, the version picked compared again with it.
  const picked = useRef(null);
  picked.current = comparison?.version ?? null;
  useEffect(() => { void compare(picked.current); }, [compare, edit.state]);
  const versions = comparison?.versions || [];
  const units = edit.state?.units || "mm";
  const now = Date.now() / 1000;
  return <div role="dialog" aria-label="Compare" data-cad-compare="" className="flex shrink-0 flex-col"
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); edit.stopInspecting(); } }}>
    <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
      <CompareIcon className="size-5 shrink-0" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-normal leading-4 text-foreground">Compare</h2>
    </div>
    <FileSheetSettingsSection title="Compare now with" sectionId="compare-versions">
      {versions.length ? <ul aria-label="Versions" className="mx-2 mb-1 flex flex-col gap-0.5">
        {versions.map(version => <li key={version.id}>
          <button type="button" aria-pressed={comparison?.version === version.id} aria-label={`${timeAgo(version.time, now)}, ${changedWords(version)}`}
            className={cn("flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-tiny leading-4 text-foreground hover:bg-accent/70",
              "aria-pressed:bg-accent")}
            onClick={() => void compare(version.id)}>
            <span className="shrink-0 tabular-nums text-muted-foreground">{timeAgo(version.time, now)}</span>
            <span className="min-w-0 flex-1 truncate">{changedWords(version)}</span>
          </button>
        </li>)}
      </ul> : <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} pb-1.5`}>
        Edit mode has read this part once so far. Each change from here, the agent's or yours, can be compared with it.</p>}
    </FileSheetSettingsSection>
    {comparison?.version ? <FileSheetSettingsSection title="What changed" sectionId="compare-changed">
      {comparison.error ? <p className="px-2 pb-1 text-tiny leading-4 text-destructive">{comparison.error}</p> : null}
      <p className={`${FILE_SHEET_STATUS_TEXT_CLASSES} flex flex-col gap-0.5 pb-1.5`} aria-live="polite">
        <span className="flex items-center gap-1.5"><span className="size-2 shrink-0 rounded-sm bg-cad-solid" aria-hidden="true" />
          {`Material it gained: ${compareVolume(comparison.addedVolume, units)}`}</span>
        <span className="flex items-center gap-1.5"><span className="size-2 shrink-0 rounded-sm bg-cad-cut" aria-hidden="true" />
          {`Material it lost: ${compareVolume(comparison.removedVolume, units)}`}</span>
      </p>
    </FileSheetSettingsSection> : null}
    <ConfirmButtons className="border-t border-border px-2 py-2" onCancel={edit.stopInspecting} cancelLabel="Close" />
  </div>;
}
