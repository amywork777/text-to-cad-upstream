// Studio: a chat message's picks selected again on the part on screen (`hostSelect.js`), and the bodies a turn
// changed (`changedBodies.js`), read from the engine's bracket fixture.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";

import { presentXbfTree } from "./xbfTree.js";
import { hostSelectIds, namesDocument } from "./hostSelect.js";
import { bodyKeys, changedBodies } from "./changedBodies.js";

const FIXTURES = join(dirname(createRequire(import.meta.url).resolve("@cad/core/lib/xbf/xbfDocument.js")), "__fixtures__");
const STRUCTURE = JSON.parse(readFileSync(join(FIXTURES, "bracket", "structure.json"), "utf8"));
const tree = presentXbfTree(STRUCTURE);
const DOC = "91fe49be-496c-518e-950a-fdbea23976cd";

test("a reference names the document on screen by its id, its path, or the path's tail", () => {
  assert.equal(namesDocument(DOC, DOC), true);
  assert.equal(namesDocument("parts/bracket.step", "/work/project/parts/bracket.step"), true);
  assert.equal(namesDocument("C:\\work\\bracket.step", "C:/work/bracket.step"), true);
  assert.equal(namesDocument("racket.step", "/work/bracket.step"), false);
  assert.equal(namesDocument("", DOC), false);
});

test("a part's picks, written against the part's own document, select its instances in the assembly on screen", () => {
  const ARM = JSON.parse(readFileSync(join(FIXTURES, "arm", "structure.json"), "utf8"));
  const armTree = presentXbfTree(ARM);
  const PART = "29ae9a38-16fc-587c-b9ea-7a4fc571762e";  // the link part's own document, not the assembly's
  const references = [
    `${PART}#link/e:arm.link.1`,   // an edge, by the name the assembly's prototype keeps for it
    `${PART}#link`,                // the part named alone
    `${PART}#link/e:arm.link.gone`, // an edge no part on screen has
  ];
  const { ids, found, missing } = hostSelectIds({ references, documentPath: "arm-assembly-id", tree: armTree, structure: ARM });
  assert.deepEqual(ids, ["i1/edge/1", "i1"]);
  assert.deepEqual([found, missing], [2, 1]);
});

test("a message's picks select the faces and parts they name, and say how many are no longer in the model", () => {
  const plateRef = tree.refOf("i0");
  assert.ok(plateRef, "the fixture's first part has an occurrence ref");
  const references = [
    `${DOC}#plate/f:bracket.fillet1~d3f70920d846`,
    `${DOC}#plate/face 5`,
    `${DOC}#${plateRef}`,
    `${DOC}#plate/f:gone`,
    "other.step#plate/face 5",
  ];
  const { ids, found, missing } = hostSelectIds({ references, documentPath: DOC, tree, structure: STRUCTURE });
  assert.deepEqual(ids, ["i0/face/2", "i0/face/5", "i0"]);
  assert.deepEqual([found, missing], [3, 2]);
});

test("nothing on screen yet finds no face, and every pick is missing", () => {
  const { ids, found, missing } = hostSelectIds({ references: [`${DOC}#plate/face 5`], documentPath: DOC, tree, structure: null });
  assert.deepEqual([ids, found, missing], [[], 0, 1]);
});

test("a turn's rebuild lights the parts whose geometry changed, not those only moved, and nothing on the first model", () => {
  const before = bodyKeys(STRUCTURE, tree);
  assert.deepEqual(changedBodies(null, before), []);
  assert.deepEqual(changedBodies(before, bodyKeys(STRUCTURE, tree)), []);
  const edited = structuredClone(STRUCTURE);
  const prototype = edited.instances[0].prototype;
  edited.prototypes[prototype].key = "plate-made-thicker";
  const shared = edited.instances.filter(instance => instance.prototype === prototype).length;
  const changed = changedBodies(before, bodyKeys(edited, presentXbfTree(edited)));
  assert.equal(changed.length, shared);
  assert.ok(changed.includes("i0"));
});
