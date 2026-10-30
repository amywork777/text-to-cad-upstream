import assert from "node:assert/strict";
import test from "node:test";

import { formatPromptMessage, resolvePromptMessage } from "@text-to-cad/core/prompt";
import {
  addToContext, canAddToContext, createQuickEditContext, deliveryFailure, promptAttachments
} from "./quickEditPrompt.js";

const STEP = { kind: "workspace-file", path: "/work/bracket/bracket.step", revision: "r1" };
const pick = selectors => ({ resource: STEP, target: { kind: "cad-selector", selectors } });
const FACE = pick(["o1.f12"]);
const EDGE = pick(["o1.e3"]);
const parts = context => context.parts.map(part => [part.id, part.kind]);

/** A host with a chat box: every context delivered is kept, and the box answers as the host's does. */
function chatHost(answer = { status: "added", partIds: [] }) {
  const delivered = [];
  return {
    delivered,
    promptContext: {
      getSnapshot: () => ({ kind: "composer", available: true }),
      subscribe: () => () => {},
      deliver: context => { delivered.push(context); return Promise.resolve(answer); },
    },
  };
}

test("delivers the picks with no note", async () => {
  const host = chatHost();
  const receipt = await addToContext(host, { resource: STEP, references: [FACE, EDGE] });
  assert.equal(host.delivered.length, 1);
  const [context] = host.delivered;
  // The file on screen and the two picks, as a Queue carries them; nothing the person wrote, so no text part.
  assert.deepEqual(parts(context), [["file", "reference"], ["reference-0", "reference"], ["reference-1", "reference"]]);
  assert.equal(formatPromptMessage(context),
    "File: /work/bracket/bracket.step\nReferences:\n/work/bracket/bracket.step#o1.f12\n/work/bracket/bracket.step#o1.e3");
  // What the host answers is what the caller reads.
  assert.deepEqual(receipt, { status: "added", partIds: [] });
});

test("carries the changes the view was asked for, each a paragraph, as Quick Edit does", async () => {
  const host = chatHost();
  await addToContext(host, { resource: STEP, references: [FACE], requests: ["Add datum A on face 12.", "Make the hole's position tolerance 0.05."] });
  const [context] = host.delivered;
  assert.deepEqual(parts(context), [["requests", "text"], ["file", "reference"], ["reference-0", "reference"]]);
  assert.match(formatPromptMessage(context), /Requested changes:\n\nAdd datum A on face 12\.\n\nMake the hole's position tolerance 0\.05\./);
});

test("is offered only with a chat box to fill", () => {
  assert.equal(canAddToContext({ kind: "composer", available: true }), true);
  // The clipboard takes a copy, not context for the next message; a chat box that cannot take it now is none.
  assert.equal(canAddToContext({ kind: "clipboard" }), false);
  assert.equal(canAddToContext({ kind: "clipboard", available: true }), false);
  assert.equal(canAddToContext({ kind: "composer", available: false, reason: "No chat is open." }), false);
  assert.equal(canAddToContext({ kind: "unavailable", available: false, reason: "Prompt delivery is unavailable in this host." }), false);
  assert.equal(canAddToContext(null), false);
});

test("carries the snapshot of the views a Queue would, and makes no picture of its own", async () => {
  const host = chatHost();
  const files = Promise.resolve({ inline: "{\"jobs\":[{\"label\":\"current view\"}]}" });
  await addToContext(host, { resource: STEP, references: [FACE], views: [{ label: "current view" }], files, read: async () => new Blob([]) });
  const [context] = host.delivered;
  assert.deepEqual(parts(context), [["file", "reference"], ["reference-0", "reference"], ["snapshot", "attachment"]]);
  const snapshot = context.parts.at(-1);
  assert.deepEqual([snapshot.name, snapshot.mimeType, snapshot.about], ["bracket.snapshot.json", "application/json", ["file"]]);
  assert.match(await resolvePromptMessage(context), /Snapshot JSON \(cadgen snapshot --annotation\):[\s\S]*"current view"/);
  // Views the host made no file of (it makes none, or there is nothing to draw) leave nothing to attach.
  const bare = chatHost();
  await addToContext(bare, { resource: STEP, references: [FACE], files });
  await addToContext(bare, { resource: STEP, references: [FACE], views: [{ label: "current view" }] });
  assert.deepEqual(bare.delivered.map(context => context.parts.some(part => part.kind === "attachment")), [false, false]);
});

test("rejects rather than throws when the context cannot be made or the host cannot take it", async () => {
  const lost = chatHost();
  const relative = { resource: { kind: "workspace-file", path: "bracket/bracket.step" }, target: { kind: "cad-selector", selectors: ["o1.f12"] } };
  const unmade = addToContext(lost, { resource: STEP, references: [relative] });
  await assert.rejects(unmade, /absolute/);
  assert.equal(lost.delivered.length, 0);
  const broken = { promptContext: { deliver: () => { throw new Error("The chat is gone."); } } };
  await assert.rejects(addToContext(broken, { resource: STEP, references: [FACE] }), /The chat is gone\./);
});

test("tells a delivery that did not go in the words Quick Edit shows under its note", () => {
  assert.equal(deliveryFailure({ status: "added", partIds: [] }), "");
  assert.equal(deliveryFailure({ status: "failed", message: "Wait for the last message to reach the chat." }), "Wait for the last message to reach the chat.");
  assert.equal(deliveryFailure({ status: "cancelled" }), "The prompt did not go.");
  // Like a Queue, only a failed or cancelled receipt is a failure.
  assert.equal(deliveryFailure({ status: "deferred" }), "");
  assert.equal(deliveryFailure(undefined), "");
});

test("reads a Quick Edit's views and files once, for every way it goes", () => {
  const made = [];
  const read = async () => new Blob([]);
  const prompt = { views: () => [{ label: "current view" }], files: views => { made.push(views); return Promise.resolve({ inline: "{}" }); }, read };
  const attached = promptAttachments(prompt);
  assert.deepEqual(attached.views, [{ label: "current view" }]);
  assert.equal(attached.read, read);
  assert.deepEqual(made, [[{ label: "current view" }]]);
  assert.ok(attached.files instanceof Promise);
  // No views, no files: the host is not asked for a snapshot of nothing.
  const nothing = promptAttachments({ views: () => [], files: () => assert.fail("a snapshot of no view was asked for"), read });
  assert.deepEqual([nothing.views, nothing.files], [[], null]);
  // A Quick Edit with no prompt carries none.
  const none = promptAttachments(null);
  assert.deepEqual([none.views, none.files, none.read], [[], null, undefined]);
});

test("a file the host failed to make is not left unhandled when nothing waits for it", async () => {
  const unhandled = [];
  const seen = reason => unhandled.push(reason);
  process.on("unhandledRejection", seen);
  try {
    promptAttachments({ views: () => [{ label: "current view" }], files: () => Promise.reject(new Error("no snapshot")), read: null });
    await new Promise(resolve => setTimeout(resolve, 10));
  } finally {
    process.off("unhandledRejection", seen);
  }
  assert.deepEqual(unhandled, []);
});

test("carries the marks drawn on a face as a text part after the references, the same however it goes", async () => {
  const MARKS = "Marks on the model, in each face's own coordinates (mm):\n"
    + "bracket · face 12: plane through (10, 0, 5), normal (0, 0, 1), u along (1, 0, 0), v along (0, 1, 0)\n"
    + "- rectangle centred at (12, 4.5), 8 × 3, turned 0°";
  const read = async () => new Blob([]);
  const prompt = { views: () => [{ label: 'view 1' }], files: () => Promise.resolve({ inline: '{}' }), read, marks: () => MARKS };
  assert.equal(promptAttachments(prompt).marks, MARKS);
  // Send and Queue: the note, the file, the picks, the marks, then the snapshot.
  const sent = createQuickEditContext({ resource: STEP, references: [FACE], text: 'Cut a window here.', ...promptAttachments(prompt) });
  assert.deepEqual(parts(sent), [['text', 'text'], ['file', 'reference'], ['reference-0', 'reference'], ['marks', 'text'], ['snapshot', 'attachment']]);
  // Add to context: the same, with no note.
  const host = chatHost();
  await addToContext(host, { resource: STEP, references: [FACE], ...promptAttachments(prompt) });
  const [added] = host.delivered;
  assert.deepEqual(parts(added), parts(sent).slice(1));
  assert.equal(added.parts.find(part => part.id === 'marks').text, MARKS);
  // The message reads them after what the person wrote, before what it is about.
  assert.equal(formatPromptMessage(createQuickEditContext({ resource: STEP, references: [FACE], text: 'Cut a window here.', marks: MARKS })),
    `Cut a window here.\n\n${MARKS}\n\nFile: /work/bracket/bracket.step\nReferences:\n/work/bracket/bracket.step#o1.f12`);
  // With no mark on a face, or a prompt that keeps none, there is no part for them.
  for (const none of [{ ...prompt, marks: () => '' }, { views: prompt.views, files: prompt.files, read }, null]) {
    const context = createQuickEditContext({ resource: STEP, references: [FACE], text: 'Round it.', ...promptAttachments(none) });
    assert.equal(context.parts.some(part => part.id === 'marks'), false);
  }
});

test("a note is its own part, and none is made of an empty one", () => {
  const written = createQuickEditContext({ resource: STEP, references: [FACE], text: "  Round it. " });
  assert.deepEqual(parts(written), [["text", "text"], ["file", "reference"], ["reference-0", "reference"]]);
  assert.equal(written.parts[0].text, "Round it.");
  // Copy Prompt with no note copies the picks alone: the same message, with no empty part to carry.
  for (const text of ["", "   ", undefined]) {
    const blank = createQuickEditContext({ resource: STEP, references: [FACE], text });
    assert.deepEqual(parts(blank), [["file", "reference"], ["reference-0", "reference"]]);
    assert.equal(formatPromptMessage(blank), "File: /work/bracket/bracket.step\nReferences:\n/work/bracket/bracket.step#o1.f12");
  }
});

test("a view nothing draws again sends itself with its marks as a picture, and no snapshot", async () => {
  const PICTURE = { kind: "workspace-file", path: "/work/bracket/drawings/bracket.pdf", revision: "r1" };
  const png = new Blob(["png"], { type: "image/png" });
  const saved = "/tmp/p/bracket-1-view.png";
  const prompt = { views: () => [], files: () => assert.fail("a picture has no snapshot"), read: null,
    picture: () => ({ png: Promise.resolve(png), path: Promise.resolve(saved) }) };
  const context = createQuickEditContext({ resource: PICTURE, text: "Make this hole 5 mm.", ...promptAttachments(prompt) });
  assert.deepEqual(parts(context), [["text", "text"], ["file", "reference"], ["picture", "attachment"]]);
  const picture = context.parts.at(-1);
  assert.equal(picture.mimeType, "image/png");
  assert.equal(picture.name, "bracket-view.png");
  assert.equal(await picture.content, png);
  // A chat that takes text names the picture by where it was saved, so the agent can open it.
  assert.match(await resolvePromptMessage(context), /Picture of the view, with the marks drawn on it: \/tmp\/p\/bracket-1-view\.png/);
  // Without marks the view sends the file alone.
  const plain = createQuickEditContext({ resource: PICTURE, text: "Check it.", ...promptAttachments({ ...prompt, picture: () => null }) });
  assert.deepEqual(parts(plain), [["text", "text"], ["file", "reference"]]);
});
