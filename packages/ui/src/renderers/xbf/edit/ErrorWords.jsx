import { cn } from "@cad/ui/utils";
import { AlertDisclosure } from "../../kit/status/ViewerAlertCard.jsx";
import { errorWords } from "./editMode.js";

/**
 * What went wrong, in red, in a line a person reads: of a script that stopped, what was raised and
 * not its traceback (`errorWords`). The traceback is whole under Details, its lines kept and a copy
 * of it one press away, as the alert card over the viewport keeps a failed build's (`AlertDisclosure`);
 * it is code, and not red. An error in words already has no Details. `children` follow it: what the
 * error offers (Redraw it as a sketch).
 *
 * @param {{ error: string, className?: string, children?: import("react").ReactNode }} props
 */
export default function ErrorWords({ error, className, children = null, ...props }) {
  const { why, details } = errorWords(error);
  return <div className={cn("flex min-w-0 flex-col items-start gap-1.5 text-tiny text-destructive", className)} {...props}>
    {why}
    {details ? <AlertDisclosure details={details} className="w-full min-w-0 text-muted-foreground" /> : null}
    {children}
  </div>;
}
