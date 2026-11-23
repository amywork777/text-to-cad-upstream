// Studio (studio-base): while the host's agent is changing the project (`tab-store/workingHost.ts`), a note at the
// top-left of the model in plain words, so the engineer knows the part on screen may change under them. It stands in
// the scene canvas's own box, so it starts past the design tree and under the ribbon in CAD mode. Still: nothing in
// it animates (a continuously repainting animation pegs the GPU on high-refresh displays).
import { useSyncExternalStore } from "react";
import { useI18n } from "@cad/ui/i18n";
import { workingHost } from "../../../tab-store/workingHost.js";

export default function StudioWorkingNote() {
  const working = useSyncExternalStore(workingHost.subscribe, workingHost.get, workingHost.get);
  const { t } = useI18n();
  if (!working) return null;
  return <div role="status" aria-live="polite" title={t("studio.workingLabel")} data-studio-working=""
    className="pointer-events-none absolute left-2 top-2 z-10 flex h-6 max-w-[calc(100%-1rem)] items-center gap-1.5 rounded-md border border-border bg-background/90 px-2 text-xs text-muted-foreground shadow-sm">
    <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-info" />
    <span className="truncate">{t("studio.working")}</span>
  </div>;
}
