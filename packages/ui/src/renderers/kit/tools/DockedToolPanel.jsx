// Studio (studio-base): a tool panel docked in edit mode's left column (`renderers/xbf/edit/`), which
// `ToolPanel` draws when the tool stack's context says `panelHead`.
import { cn } from "@cad/ui/utils";

/**
 * The head of a panel of CAD mode's left dock (the FeatureManager, PMI): one 28px row 8px in, the
 * words as written, a level above the tracked-caps headings inside the panel. The caller ends it:
 * 8px past a bare chevron, 4px past a 20px button, so the glyphs end on one line.
 */
export const DOCK_PANEL_HEAD_CLASS = "flex h-7 w-full shrink-0 items-center gap-1 pl-2 text-left text-xs font-medium leading-4 text-foreground";

/**
 * A panel docked in CAD mode's left column is that column's section: no box, its heading the column's dock
 * head (`DOCK_PANEL_HEAD_CLASS`), pinned over what it scrolls. It neither folds nor sizes: the column does.
 * `ToolPanel` hands it its own refs and close button. (`ToolPanel`'s `solid`: a panel of small text read closely
 * over the model, PMI, on the workspace's opaque card, `WORKSPACE_SURFACE_CLASS`.)
 */
export default function DockedToolPanel({ sectionRef, bodyRef, contentRef, id, fit, label, title, name, summary, actions, header, closeButton, hidden, children }) {
  return <section ref={sectionRef} aria-label={label} hidden={hidden} data-tool-panel={fit} data-tool-panel-id={id || undefined} data-tool-panel-docked=""
    className="flex min-h-0 min-w-0 flex-col text-tiny">
    <div className="sticky top-0 z-10 border-b border-border bg-cad-ws-panel" data-tool-panel-heading="">
      {header ? <div className="flex min-w-0 items-center gap-1 pr-0.5" data-tool-panel-header=""><div className="min-w-0 flex-1">{header}</div>{closeButton}</div>
        : <div className={cn(DOCK_PANEL_HEAD_CLASS, "pr-1")}>
          <h3 className="flex min-w-0 flex-1"><span className="min-w-0 truncate">{title || name || label}</span></h3>
          {summary ? <span className="shrink-0 text-tiny text-muted-foreground">{summary}</span> : null}
          {actions}
          {closeButton}
        </div>}
    </div>
    <div ref={bodyRef} data-tool-panel-body="" className="min-w-0">
      <div ref={contentRef} className="flow-root">{children}</div>
    </div>
  </section>;
}
