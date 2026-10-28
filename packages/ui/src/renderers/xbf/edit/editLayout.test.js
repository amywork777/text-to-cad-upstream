import assert from "node:assert/strict";
import test from "node:test";

import { doubleClickLayout, editLayoutState, pendingFaceStep } from "./editLayout.js";

test("a file has the two layouts once the server says it has a part script, one whose build failed too", () => {
  for (const status of ["probing", "none"]) assert.equal(editLayoutState({ status }).editable, false, status);
  for (const status of ["reading", "idle", "ready", "error"]) assert.equal(editLayoutState({ status }).editable, true, status);
});

test("a command, a sketch, a pick or a change being saved holds the layout until it is finished or cancelled", () => {
  const ready = { status: "ready", command: null, sketch: null, picking: false, saving: false };
  assert.deepEqual(editLayoutState(ready), { editable: true, busy: false });
  for (const open of [{ command: "extrude" }, { sketch: { name: "Sketch (1)" } }, { picking: true }, { saving: true }]) {
    assert.equal(editLayoutState({ ...ready, ...open }).busy, true, JSON.stringify(open));
  }
});

test("in Studio, a double-click on a face of a part laid out for the AI steps into CAD on it; a plain STEP or an assembly keeps Normal To", () => {
  const part = { layout: "ai", hosted: true, editable: true, assembly: false, target: "face", selecting: true, open: false };
  assert.equal(doubleClickLayout(part), "manual");
  // Measure, Explode or Clip in hand: the double-click is theirs, and the layout stays.
  assert.equal(doubleClickLayout({ ...part, selecting: false }), null);
  // A STEP with no part script has no CAD mode: Normal To as today, no switch.
  assert.equal(doubleClickLayout({ ...part, editable: false }), null);
  // Jake's own viewer, which no host lays out, keeps its layout and Normal To.
  assert.equal(doubleClickLayout({ ...part, hosted: false }), null);
  // An assembly's faces are its parts': Normal To.
  assert.equal(doubleClickLayout({ ...part, assembly: true }), null);
  // Empty space laid out for the AI does what it always has.
  assert.equal(doubleClickLayout({ ...part, target: "empty" }), null);
});

test("in Studio's CAD workspace, a double-click on empty space with nothing open goes back to the AI; on a face it selects as ever", () => {
  const empty = { layout: "manual", hosted: true, editable: true, assembly: false, target: "empty", selecting: true, open: false };
  assert.equal(doubleClickLayout(empty), "ai");
  assert.equal(doubleClickLayout({ ...empty, selecting: false }), null);
  assert.equal(doubleClickLayout({ ...empty, assembly: true }), "ai");
  // A command, sketch, pick or sheet open: it stays.
  assert.equal(doubleClickLayout({ ...empty, open: true }), null);
  // A face is the workspace's own double-click: its feature selected.
  assert.equal(doubleClickLayout({ ...empty, target: "face" }), null);
  assert.equal(doubleClickLayout({ ...empty, hosted: false }), null);
  assert.equal(doubleClickLayout({ ...empty, editable: false }), null);
});

test("a face handed to the workspace waits while the part is read, then has its feature selected, once", () => {
  const face = { file: "parts/bracket.step", reached: false };
  const at = { layout: "ai", file: "parts/bracket.step", status: "idle", editing: false, faces: false };
  // The host's CAD layout still to come, then the part read.
  assert.deepEqual(pendingFaceStep(face, at), { step: "wait", reached: false });
  assert.deepEqual(pendingFaceStep(face, { ...at, layout: "manual", editing: true }), { step: "wait", reached: true });
  const reached = { ...face, reached: true };
  assert.deepEqual(pendingFaceStep(reached, { ...at, layout: "manual", editing: true, status: "reading" }), { step: "wait", reached: true });
  assert.deepEqual(pendingFaceStep(reached, { ...at, layout: "manual", editing: true, status: "ready", faces: true }), { step: "select", reached: true });
});

test("a face handed to the workspace is let go on another file, a part that reads to nothing, the AI again, or one try without its faces", () => {
  const face = { file: "parts/bracket.step", reached: true };
  const cad = { layout: "manual", file: "parts/bracket.step", status: "ready", editing: true, faces: true };
  assert.equal(pendingFaceStep(face, { ...cad, file: "parts/lid.step" }).step, "drop");
  for (const status of ["error", "none"]) assert.equal(pendingFaceStep(face, { ...cad, status }).step, "drop", status);
  // Back to the AI once CAD came: the face is not kept for the next time.
  assert.equal(pendingFaceStep(face, { ...cad, layout: "ai", editing: false }).step, "drop");
  // Read, but its faces not mapped to features (a rebuild, the rollback bar, a count that differs): one try, then gone, so
  // it is never selected long after.
  assert.equal(pendingFaceStep(face, { ...cad, faces: false }).step, "drop");
  // Before CAD came, the AI's layout is only the wait for it.
  assert.equal(pendingFaceStep({ ...face, reached: false }, { ...cad, layout: "ai", editing: false, status: "idle" }).step, "wait");
});
