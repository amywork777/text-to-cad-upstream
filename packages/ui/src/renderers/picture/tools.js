import { createToolModes } from "../kit/tools/toolModes.js";

// A picture's tools: Select is the view's hand (a drag pans, the wheel or a pinch zooms, a
// double-click fits) and picks the ink drawn on it; Pencil and Shapes draw on the sheet. A picture
// has no entities to pick and no scale to measure in, so it has no Measure.
export const PICTURE_TOOL = Object.freeze({ SELECT: "select", PENCIL: "pencil", SHAPES: "shapes" });

export const PICTURE_TOOL_MODES = createToolModes({
  defaultMode: PICTURE_TOOL.SELECT,
  modes: Object.fromEntries(Object.values(PICTURE_TOOL).map(mode => [mode, {}]))
});

/** What a host command a picture cannot carry out is told. */
export const PICTURE_DECLINED_LIVE_COMMANDS = Object.freeze({
  select: "A picture has nothing to select by reference: mark it up with Pencil or Shapes in the viewer, "
    + "and Quick Edit sends the marks with the note."
});
export const PICTURE_NO_CAMERA = "A picture is shown head on: it has no camera to pose. "
  + "Zoom and pan it in the view, or call resetCamera to fit the whole picture again.";
export const PICTURE_NO_DISPLAY = "A picture has no Display settings: it is painted as it is, a PDF a sheet per page.";
