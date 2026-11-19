// Studio's results viewer (studio-base): kept out of tools.js, Jake's.
import { GLB_DECLINED_LIVE_COMMANDS } from "./tools.js";

/**
 * What a host command a result's view (an FEA study's, a CAM job's) cannot carry out is told: its
 * markers, readouts and paths are its own, and nothing in it is selected to clear.
 */
export const GLB_RESULT_LIVE = Object.freeze({ declined: Object.freeze({
  ...GLB_DECLINED_LIVE_COMMANDS,
  clearSelection: "A result's view selects nothing a command could clear: its markers, readouts and paths are its own. Control the camera and display settings instead."
}) });
