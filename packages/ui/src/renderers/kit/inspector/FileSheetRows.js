// Studio's edit mode (studio-base): the rows its panels (`xbf/edit/`) draw their parameters with, kept out of
// FileSheet.js, Jake's, whose classes they are built from.
import { Children } from "react";
import { TooltipHint } from "@cad/ui/primitives/tooltip";
import { cn } from "@cad/ui/utils";
import { Checkbox } from "@cad/ui/primitives/checkbox";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@cad/ui/primitives/select";

// A field's label and a select's trigger, as FileSheet.js drew them before 0.11.16 took its select away: the trigger
// clips and ellipsizes its own value (the Radix trigger only sets whitespace-nowrap, so a long option would push its
// chevron out through the border).
export const FILE_SHEET_FIELD_LABEL_CLASSES = "block min-w-0 truncate text-xs leading-(--cad-leading-xs) text-muted-foreground";
export const FILE_SHEET_SELECT_TRIGGER_CLASSES = "!h-control w-full overflow-hidden px-2 !text-xs [&_svg]:size-3.5 [&>span]:min-w-0 [&>span]:truncate";

// A select sized to what it says (the row's own label beside it) rather than the row's width: FileSheet's trigger
// less its full width.
const FILE_SHEET_INLINE_SELECT_TRIGGER_CLASSES = `${FILE_SHEET_SELECT_TRIGGER_CLASSES.replace(/ w-full$/, "")} w-fit min-w-20 max-w-44`;
export const FILE_SHEET_COMPACT_BUTTON_CLASSES = "h-7 px-2 text-tiny text-muted-foreground hover:text-foreground";

// The rows edit mode's panels draw their parameters with: a checkbox row, a row of buttons and a select row.
export function FileSheetCheckboxRow({ label, checked, onCheckedChange, className, disabled = false }) {
  return (
    <label className={cn("flex h-6 items-center gap-2 px-2 text-tiny text-foreground", disabled ? "cursor-default opacity-50" : "cursor-pointer", className)}>
      <Checkbox aria-label={label} checked={checked} disabled={disabled} onCheckedChange={next => onCheckedChange(next === true)} />
      <span className="truncate">{label}</span>
    </label>
  );
}

function FileSheetInlineControlRow({ label, children, className }) {
  return (
    <div className={cn("px-2", className)}>
      <div className="flex min-h-7 max-w-full items-center justify-between gap-2">
        <span className={FILE_SHEET_FIELD_LABEL_CLASSES}>{label}</span>
        <span className="shrink-0">{children}</span>
      </div>
    </div>
  );
}

export function FileSheetButtonRow({ children }) {
  const columnCount = Math.max(1, Children.count(children));
  return (
    <div
      className="grid gap-1.5 px-2"
      style={{ gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))` }}
    >
      {children}
    </div>
  );
}

export function FileSheetSelectRow({
  label,
  value,
  onValueChange,
  options,
  ariaLabel,
  placeholder,
  triggerContent,
  hideLabel = false,
  triggerClassName,
  className
}) {
  const selectedIcon = options.find(option => option.value === value)?.icon;
  const select = (
    <Select value={value} onValueChange={onValueChange}>
      <TooltipHint content={hideLabel ? ariaLabel || label : undefined}><SelectTrigger
        size="sm"
        className={cn(hideLabel ? FILE_SHEET_SELECT_TRIGGER_CLASSES : FILE_SHEET_INLINE_SELECT_TRIGGER_CLASSES, triggerClassName)}

        aria-label={ariaLabel || (typeof label === "string" ? label : undefined)}
      >
        {triggerContent ?? (selectedIcon ? <span className="flex min-w-0 items-center gap-1">{selectedIcon}<SelectValue placeholder={placeholder} /></span> : <SelectValue placeholder={placeholder} />)}
      </SelectTrigger></TooltipHint>
      <SelectContent>
        {(() => {
          // Options may carry a `group`: grouped ones render under SelectGroup headings in
          // first-appearance order, ungrouped ones (e.g. a leading "None") stay at the top.
          const renderItem = (option) => (
            <TooltipHint key={option.value} content={option.title}><SelectItem

              value={option.value}
              disabled={option.disabled}

              icon={option.icon}
            >
              {option.label}
            </SelectItem></TooltipHint>
          );
          const ungrouped = options.filter((option) => !option.group);
          const groupNames = [...new Set(options.map((option) => option.group).filter(Boolean))];
          if (!groupNames.length) {
            return options.map(renderItem);
          }
          return (
            <>
              {ungrouped.map(renderItem)}
              {groupNames.map((groupName) => (
                <SelectGroup key={groupName}>
                  <SelectLabel className="text-tiny uppercase tracking-wide text-muted-foreground">
                    {groupName}
                  </SelectLabel>
                  {options.filter((option) => option.group === groupName).map(renderItem)}
                </SelectGroup>
              ))}
            </>
          );
        })()}
      </SelectContent>
    </Select>
  );
  if (hideLabel) return <div className={cn("min-w-0 px-2", className)}>{select}</div>;
  return (
    <FileSheetInlineControlRow label={label} className={className}>
      {select}
    </FileSheetInlineControlRow>
  );
}
