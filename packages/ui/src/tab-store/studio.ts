// Studio's part of the tab store (studio-base): its settings in the record (`studioSettings.ts`) and its host's
// channels to the part on screen (`editLayoutHost.ts`, `focusHost.ts`, `viewerControlsHost.ts`).
export { editLayoutHost } from './editLayoutHost.js';
export { focusHost } from './focusHost.js';
export { attachViewerControls, MOUSE_PRESETS, viewerControlsHost } from './viewerControlsHost.js';
export type { MousePreset, ViewerControls } from './viewerControlsHost.js';
export type { EditLayout, OpenedFrom } from './studioSettings.js';
