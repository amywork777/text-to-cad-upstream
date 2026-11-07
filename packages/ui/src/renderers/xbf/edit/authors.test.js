import assert from "node:assert/strict";
import test from "node:test";

import { authorOf } from "./authors.js";

test("marks each feature of a part you and the agent both worked on", () => {
  const authors = { pad: "agent", fillet: "you", hole: "someone else" };
  assert.equal(authorOf(authors, "pad"), "agent");
  assert.equal(authorOf(authors, "fillet"), "you");
  assert.equal(authorOf(authors, "hole"), null);
  assert.equal(authorOf(authors, "unknown"), null);
});

test("marks nothing on a part only one of you made, where a dot would say nothing", () => {
  assert.equal(authorOf({ pad: "agent", hole: "agent" }, "pad"), null);
  assert.equal(authorOf({ pad: "you", hole: "you" }, "pad"), null);
  assert.equal(authorOf(null, "pad"), null);
});
