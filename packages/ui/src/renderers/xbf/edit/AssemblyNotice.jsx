/**
 * In CAD mode on an assembly, how a part of it is edited: isolated, it opens on its own to be modeled (an
 * assembly only places its parts, as SolidWorks models a part in its own window). With nothing isolated it says
 * so; an isolated part no script makes (a bought screw) says to ask the agent; several, to isolate one. A notice
 * of the view's top-right corner (`RendererShell`'s `notice`), as `ImportedBody` is.
 *
 * @param {{ isolated: { several?: boolean, name?: string, component?: object | null } | null, editable: boolean }} props
 *   `isolated`: `isolatedPart`'s answer, null with nothing isolated; `editable`: its parts can be opened here.
 */
export default function AssemblyNotice({ isolated, editable }) {
  const words = !editable ? "This is the assembly. Ask the agent to change a part."
    : !isolated ? "This is the assembly. Isolate a part to edit it."
      : isolated.several ? "Isolate one part to edit it."
        : `${isolated.name} can't be edited here because it has no script, like a bought part. Ask the agent to change it.`;
  return <div data-cad-assembly-notice="" className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-muted-foreground shadow-sm">
    {words}
  </div>;
}
