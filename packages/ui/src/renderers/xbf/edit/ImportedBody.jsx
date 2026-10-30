import { useState } from "react";
import { Button } from "@text-to-cad/ui/primitives/button";
import { cn } from "@text-to-cad/ui/utils";

const BELOW_STRIP = Object.freeze({ top: "var(--cad-tools-bottom, 0.75rem)" });

/**
 * A STEP brought in, with no part script to edit: offered as a part to model on, as SolidWorks makes
 * a part of a STEP it opens and Fusion and NX hold one as a body with no history. Edit as a part
 * writes a script beside it that reads it (`useEditMode`'s `adopt`), builds it and opens that part
 * by its document's id once the engine holds it; the STEP itself is never written over. One made
 * before is opened instead, once it is built (`onOpenPart`, its id or null), and never made again: a
 * part whose build failed says why (`imported.error`), and opens once its script builds.
 *
 * @param {{ imported: { part: string | null, error?: string }, onAdopt: () => Promise<{ part: string } | null>,
 *   onOpenPart: () => Promise<string | null>, onOpen: (file: string) => void }} props
 */
export default function ImportedBody({ imported, onAdopt, onOpenPart, onOpen }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const run = async (made) => {
    setBusy(true);
    setFailed(false);
    try {
      const part = await made();
      if (part) onOpen(part);
      else setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  // Why the part made of it did not build, as the build said it.
  const said = imported.error ? `Its part did not build: ${imported.error}` : "";
  const words = busy ? "Making it a part" : said || (failed ? "Studio couldn't make it a part. Try again." : "Imported STEP, no history");
  // At the top left, under the tool strip (`--cad-tools-bottom`, the shell's measure), never over it.
  return <div data-cad-imported-body="" style={BELOW_STRIP} className="pointer-events-auto absolute left-3 z-20 flex max-w-[min(32rem,calc(100%-1.5rem))] items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-xs shadow-sm">
    <span className={cn("min-w-0 truncate", said && !busy ? "text-destructive" : "text-muted-foreground")} title={said || undefined}>{words}</span>
    {imported.part
      ? <Button size="xs" disabled={busy} onClick={() => void run(onOpenPart)}>Open its part</Button>
      : <Button size="xs" disabled={busy} onClick={() => void run(async () => (await onAdopt())?.part || null)}>Edit as a part</Button>}
  </div>;
}
