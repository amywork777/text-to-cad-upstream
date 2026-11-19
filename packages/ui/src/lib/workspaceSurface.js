// Studio (studio-base): the surfaces of edit mode's workspace (`renderers/xbf/edit/`), kept out of the
// kit's own `floatingSurface.js`.
/**
 * `WORKSPACE_SURFACE_CLASS`: the cards of the workspace (edit mode laid out for modeling by hand), up over the live
 * canvas for as long as it is: the open command's dialog and the timeline, and a tool panel
 * of small text read closely over the model (PMI, `ToolPanel`'s `solid`). White as the
 * workspace's toolbar is (the background, opaque, in either theme), a 1px hairline and 6px corners (`rounded-sm`),
 * and no backdrop filter: a blur over the live canvas is computed again for every frame the canvas draws.
 */
export const WORKSPACE_SURFACE_CLASS = "rounded-sm border border-border bg-background text-foreground";
/**
 * `WORKSPACE_DOCK_CLASS`: the design tree's column, flush against the canvas rather than over it: the workspace's
 * opaque background, one hairline on the side it meets the canvas, and no card's border or corners.
 */
export const WORKSPACE_DOCK_CLASS = "border-r border-border bg-cad-ws-panel text-foreground";
