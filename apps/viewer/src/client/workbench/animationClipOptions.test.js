import assert from "node:assert/strict";
import test from "node:test";

import { REST_CLIP_ID } from "cadgen-js/common/animationClock.js";

import {
  AUTHORED_CLIPS_GROUP_LABEL,
  NO_CLIP_OPTION_LABEL,
  animationClipOptions
} from "./animationClipOptions.js";

test("the built-in no-clip entry leads, ungrouped, and is not labelled like a clip", () => {
  const options = animationClipOptions([
    { id: "spin", label: "Spin" },
    { id: "walk", label: "Walk" }
  ]);
  assert.equal(options[0].value, REST_CLIP_ID);
  assert.equal(options[0].label, NO_CLIP_OPTION_LABEL);
  assert.equal(options[0].group, undefined);
  // Authored clips keep module order and sit under their own heading, so the
  // dropdown reads as a state followed by a list rather than one list.
  assert.deepEqual(
    options.slice(1),
    [
      { value: "spin", label: "Spin", group: AUTHORED_CLIPS_GROUP_LABEL },
      { value: "walk", label: "Walk", group: AUTHORED_CLIPS_GROUP_LABEL }
    ]
  );
});

test("an authored clip called Rest cannot be confused with the built-in entry", () => {
  // The sibling-project complaint: a pose or clip literally named `rest` used to
  // produce two indistinguishable "Rest" rows. The built-in entry's label never
  // collides with an authored name, and the two never share a group.
  const options = animationClipOptions([{ id: "rest", label: "Rest" }]);
  assert.equal(options.length, 2);
  assert.notEqual(options[0].label, options[1].label);
  assert.notEqual(options[0].value, options[1].value);
  assert.equal(options[1].group, AUTHORED_CLIPS_GROUP_LABEL);
  assert.equal(options[0].group, undefined);
  assert.notEqual(NO_CLIP_OPTION_LABEL.toLowerCase(), "rest");
});

test("no clips still yields the no-clip entry alone", () => {
  assert.deepEqual(animationClipOptions(undefined), [
    { value: REST_CLIP_ID, label: NO_CLIP_OPTION_LABEL }
  ]);
});
