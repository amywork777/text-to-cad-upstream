import { useEffect, useRef, useState } from "react";
import { Button } from "@cad/ui/primitives/button";
import { cn } from "@cad/ui/utils";

/**
 * A STEP brought in, with no part script to edit: offered as a part to model on, as SolidWorks makes
 * a part of a STEP it opens and Fusion and NX hold one as a body with no history. Edit as a part
 * writes a script beside it that reads it (`useEditMode`'s `adopt`), builds it and opens that part
 * by its document's id once the engine holds it; the STEP itself is never written over. One made
 * before opens in the STEP's place on its own, as a STEP a part script writes opens as its part
 * (`useXbfEditLayout`'s swap), once it is built (`onOpenPart`, its id or null), and is never made
 * again: a part whose build failed says why (`imported.error`) and is not opened, and Open its part
 * asks again. It opens on its own only where CAD mode is up (`opensOnItsOwn`), as the swap does.
 *
 * @param {{ imported: { part: string | null, error?: string }, onAdopt: () => Promise<{ part: string } | null>,
 *   onOpenPart: () => Promise<string | null>, onOpen: (file: string) => void, opensOnItsOwn?: boolean }} props
 */
export default function ImportedBody({ imported, onAdopt, onOpenPart, onOpen, opensOnItsOwn = false }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // The part last opened, by Edit as a part, a press or on its own: never opened on its own again.
  const opened = useRef(null);
  const run = async (made) => {
    setBusy(true);
    setFailed(false);
    try {
      const part = await made();
      if (part) {
        opened.current = part;
        onOpen(part);
      } else setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  // The part made of it before, opened once on its own; one whose build failed waits for a press.
  const runRef = useRef(run);
  runRef.current = run;
  useEffect(() => {
    if (!opensOnItsOwn || busy || !imported.part || imported.error || opened.current === imported.part) return;
    opened.current = imported.part;
    void runRef.current(onOpenPart);
  }, [opensOnItsOwn, busy, imported.part, imported.error, onOpenPart]);
  // Why the part made of it did not build, as the build said it.
  const said = imported.error ? `Its part did not build: ${imported.error}` : "";
  const words = busy
    ? imported.part ? "Opening its part" : "Making it a part"
    : said || (failed
      ? imported.part ? "Studio couldn't open its part. Try again." : "Studio couldn't make it a part. Try again."
      : "Imported STEP, no history");
  // A notice of the view's top-right corner (`RendererShell`'s `notice`): Quick Edit opens under it.
  return <div data-cad-imported-body="" className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-xs shadow-sm">
    <span className={cn("min-w-0 truncate", said && !busy ? "text-destructive" : "text-muted-foreground")} title={said || undefined}>{words}</span>
    {imported.part
      ? <Button size="xs" disabled={busy} onClick={() => void run(onOpenPart)}>Open its part</Button>
      : <Button size="xs" disabled={busy} onClick={() => void run(async () => (await onAdopt())?.part || null)}>Edit as a part</Button>}
  </div>;
}
