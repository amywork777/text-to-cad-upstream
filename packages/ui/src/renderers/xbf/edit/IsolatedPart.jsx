import { Button } from "@cad/ui/primitives/button";

/**
 * In CAD mode on an assembly, what isolating its parts means for changing them: a part of an
 * assembly is modeled on its own, so one isolated part with a script of its own offers Open Part
 * (SolidWorks' word, as the design tree's), one with none says to ask the agent, and several say
 * how to open one. A notice of the view's top-right corner (`RendererShell`'s `notice`), as
 * `ImportedBody` is.
 *
 * @param {{ isolated: { several?: boolean, name?: string, component?: object | null },
 *   onOpenPart: ((component: object) => void) | null }} props
 */
export default function IsolatedPart({ isolated, onOpenPart }) {
  const openable = !isolated.several && isolated.component && onOpenPart;
  const words = isolated.several ? "Isolated. Double-click a part in the tree to open it and model it."
    : openable ? `${isolated.name} is isolated. Open it to change its features.`
      : `${isolated.name} is isolated. Ask the agent to change it.`;
  return <div data-cad-isolated-part="" className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-xs shadow-sm">
    <span className="min-w-0 text-muted-foreground">{words}</span>
    {openable ? <Button size="xs" onClick={() => onOpenPart(isolated.component)}>Open Part</Button> : null}
  </div>;
}
