// A PMI reference found on the page (`pmiRefs.js`): the canonical ref the engine resolved names the
// same element in the scene, by its name or its ordinal; a ref that names nothing, or a part rather
// than an element, names no element; an ambiguous one keeps its candidates.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";

import { presentXbfTree } from "../xbfTree.js";
import { createPmiRefResolver, resolvePmiEntryRefs } from "./pmiRefs.js";

const FIXTURES = join(dirname(createRequire(import.meta.url).resolve("@text-to-cad/core/lib/xbf/xbfDocument.js")), "__fixtures__");
const STRUCTURE = JSON.parse(readFileSync(join(FIXTURES, "bracket", "structure.json"), "utf8"));
const resolver = createPmiRefResolver(STRUCTURE, presentXbfTree(STRUCTURE));

test("a canonical ref names its element on the page", () => {
  assert.deepEqual(resolver.resolve("plate/f:bracket.fillet1~d3f70920d846"), ["i0/face/2"]);
  assert.deepEqual(resolver.resolve("plate/f:bracket.make_cylinder1.1;M:bracket.cut1"), ["i0/face/11"]);
  // A repeated part's element is its occurrence's: the second peg's top.
  assert.deepEqual(resolver.resolve("bracket/peg.2/f:bracket.make_cylinder1.2"), ["i2/face/2"]);
  // By its ordinal too, as a ref may spell it.
  assert.deepEqual(resolver.resolve("plate/face 5"), ["i0/face/5"]);
});

test("a ref that names nothing, or no element, names no element", () => {
  assert.deepEqual(resolver.resolve("plate/f:gone"), []);
  assert.deepEqual(resolver.resolve("plate"), []);
  assert.deepEqual(resolver.resolve("nothing/f:bracket.fillet1~d3f70920d846"), []);
  assert.deepEqual(resolver.resolve(""), []);
});

test("an entry's refs carry what they name, and a broken one only its candidates", () => {
  const refs = resolvePmiEntryRefs({ refs: [
    { role: "feature", ref: "plate/f:bracket.fillet1~d3f70920d846", written: "f:bracket.fillet1~d3f70920d846", status: "ok", candidates: [] },
    { role: "from", ref: "face 3", written: "face 3", status: "ambiguous", candidates: ["plate/face 5", "bracket/peg.1/face 3"] },
    { role: "to", ref: "plate/f:gone", written: "plate/f:gone", status: "missing", candidates: [] },
  ] }, resolver);
  assert.deepEqual(refs.map(ref => [ref.role, ref.ids, ref.candidateIds]), [
    ["feature", ["i0/face/2"], []], ["from", [], ["i0/face/5", "i1/face/3"]], ["to", [], []]]);
});
