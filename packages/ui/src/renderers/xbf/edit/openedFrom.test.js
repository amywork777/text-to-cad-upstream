import assert from "node:assert/strict";
import test from "node:test";

import { openedFrom, rememberOpenedFrom } from "./openedFrom.js";

// The tab's settings as the shell hands them: the snapshot and its writer.
function tabSettings(initial = {}) {
  const services = { preferences: { openedFrom: initial }, onPreferenceChange(patch) { services.preferences = { ...services.preferences, ...patch }; } };
  return services;
}

test("a part opened from an assembly leads back to it, the newest kept last", () => {
  const services = tabSettings({ "/m/post.step": { file: "/m/old.step", title: "Old" }, "/m/base.step": { file: "/m/stack.step", title: "Stack" } });
  rememberOpenedFrom(services, "/m/post.step", { file: "/m/stack.step", title: "Stack" });
  assert.deepEqual(Object.keys(services.preferences.openedFrom), ["/m/base.step", "/m/post.step"]);
  assert.deepEqual(openedFrom(services.preferences, "/m/post.step"), { file: "/m/stack.step", title: "Stack" });
  // A part with no way back, the part itself named as where it came from, or no file at all: none.
  assert.equal(openedFrom(services.preferences, "/m/lid.step"), null);
  assert.equal(openedFrom({ openedFrom: { "/m/lid.step": { file: "/m/lid.step", title: "Lid" } } }, "/m/lid.step"), null);
  assert.equal(openedFrom(services.preferences, ""), null);
  // Nothing to remember without both files.
  rememberOpenedFrom(services, "", { file: "/m/stack.step", title: "Stack" });
  rememberOpenedFrom(services, "/m/lid.step", { title: "No file" });
  assert.deepEqual(Object.keys(services.preferences.openedFrom), ["/m/base.step", "/m/post.step"]);
});
