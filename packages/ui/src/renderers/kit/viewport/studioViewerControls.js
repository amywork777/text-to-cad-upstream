// Studio's (studio-base, not Jake's text-to-cad): the mouse a Studio window's Settings set, on every 3D
// view's camera controls (`tab-store/viewerControlsHost.ts`). Jake's `ShellViewport.jsx` calls it once.
import { useEffect } from "react";
import { attachViewerControls } from "../../../tab-store/viewerControlsHost.js";

/** Applies the host's mouse setting to the view's controls, and again to each runtime that replaces it. */
export function useStudioViewerControls(runtimeRef, viewerReadyTick) {
  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime?.controls?.mouseButtons || !runtime.THREE?.MOUSE) return undefined;
    return attachViewerControls(runtime.controls, runtime.THREE.MOUSE);
  }, [runtimeRef, viewerReadyTick]);
}
