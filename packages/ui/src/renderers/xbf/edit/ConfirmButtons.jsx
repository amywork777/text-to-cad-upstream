import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { cn } from "@text-to-cad/ui/utils";

const BUTTON_CLASS = "flex h-7 min-w-14 items-center justify-center rounded-md border px-2.5 text-tiny font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:pointer-events-none disabled:opacity-40";
const PRIMARY_CLASS = "border-primary bg-primary text-primary-foreground hover:bg-primary/90";
const SECONDARY_CLASS = "border-border bg-background text-foreground hover:bg-accent";

/**
 * A dialog's buttons as NX lays them along its foot: OK (the default, which makes it and closes
 * the dialog), Apply (which makes it and keeps the dialog open for another, given `onApply`) and
 * Cancel. A sketch names them Finish Sketch and Discard Changes. `okReason` says why OK waits (a
 * hole needs its face), as its hint. Without `onOk`, Cancel alone (or Close): a command waiting for
 * its plane, or a panel that only shows something, has nothing to confirm.
 *
 * @param {{ onOk?: (() => void) | null, onApply?: (() => void) | null, onCancel: () => void, okLabel?: string,
 *   cancelLabel?: string, okDisabled?: boolean, okReason?: string, busy?: boolean, className?: string }} props
 */
export function ConfirmButtons({ onOk = null, onApply = null, onCancel, okLabel = "OK", cancelLabel = "Cancel", okDisabled = false,
  okReason = "", busy = false, className }) {
  const waits = okDisabled || busy;
  const button = (label, onClick, primary, disabled, reason = "") => <TooltipHint key={label} content={reason || label}>
    <span className="inline-flex">
      <button type="button" aria-label={label} aria-description={reason || undefined} disabled={disabled}
        className={cn(BUTTON_CLASS, primary ? PRIMARY_CLASS : SECONDARY_CLASS)} onClick={onClick}>{label}</button>
    </span>
  </TooltipHint>;
  return <div className={cn("flex items-center justify-end gap-1.5", className)} data-cad-confirm="">
    {onOk ? button(okLabel, onOk, true, waits, okReason) : null}
    {onApply ? button("Apply", onApply, false, waits, okReason) : null}
    {button(cancelLabel, onCancel, false, busy)}
  </div>;
}
