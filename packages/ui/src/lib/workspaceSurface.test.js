import assert from "node:assert/strict";
import test from "node:test";
import { WORKSPACE_SURFACE_CLASS } from "./workspaceSurface.js";

// The workspace's cards (the design tree, the open command's dialog, the timeline) stay up over the live
// canvas for as long as it is: white as its toolbar is, opaque, a 1px hairline and 6px corners, and no
// backdrop filter, which the canvas would make the GPU compute again for every frame it draws.
test("the workspace's cards are white and opaque, with a hairline and 6px corners, and filter nothing behind them", () => {
  assert.equal(WORKSPACE_SURFACE_CLASS, "rounded-sm border border-border bg-background text-foreground");
});
