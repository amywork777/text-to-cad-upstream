import { engineSelectorText, parseEngineRef } from "@text-to-cad/core/lib/cadRefs.js";
import { xbfElementId } from "@text-to-cad/core/lib/xbf/xbfScene.js";

// What a PMI reference names in the document on screen: the scene's element ids (`i3/face/12`) of
// the face, edge or vertex its canonical ref spells, as `cadgen.engine.refs` resolves it against the
// served structure (`refs.resolve_structure`). The engine has already resolved every reference of a
// served annotation (its `status`); this finds the same element on the page, by spelling each
// candidate's canonical ref as the tree does (`xbfTree.js`'s `elementRefOf`) and keeping the ones
// that read exactly as the reference does. Nothing is guessed: a ref that names no element, or one
// the page cannot find, names none.

const KIND_OF_PREFIX = Object.freeze({ f: "face", e: "edge", v: "vertex" });
const NAMES_KEY = Object.freeze({ face: "faceNames", edge: "edgeNames", vertex: "vertexNames" });

/**
 * A resolver of refs into the document `structure` (its tree presented as `tree`,
 * `presentXbfTree`): `resolve(ref)` is the element ids it names, in instance order, none for a ref
 * that names no element. Each answer is kept.
 *
 * @param {object | null} structure
 * @param {{ elementRefOf: (partId: string, kind: string, ordinal: number, name?: string) => string }} tree
 */
export function createPmiRefResolver(structure, tree) {
  const instances = structure?.instances || [];
  const prototypes = structure?.prototypes || [];
  const reversed = new Map();
  // A prototype's names of one kind, by name: what a named element's ordinal is.
  const ordinalsOf = (prototype, kind) => {
    const key = `${prototype}:${kind}`;
    if (!reversed.has(key)) {
      const names = prototypes[prototype]?.[NAMES_KEY[kind]] || {};
      reversed.set(key, new Map(Object.entries(names).map(([ordinal, name]) => [name, Number(ordinal)])));
    }
    return reversed.get(key);
  };
  const nameOf = (prototype, kind, ordinal) => prototypes[prototype]?.[NAMES_KEY[kind]]?.[String(ordinal)] || "";
  const known = new Map();
  const resolve = (ref) => {
    const text = String(ref || "");
    if (known.has(text)) return known.get(text);
    const found = [];
    for (const selector of parseEngineRef(text)?.selectors || []) {
      const element = selector.element;
      if (!element) continue;
      const kind = typeof element === "string" ? KIND_OF_PREFIX[element[0]] : element.kind;
      if (!kind) continue;
      const wanted = engineSelectorText(selector);
      instances.forEach((instance, index) => {
        const prototype = instance?.prototype;
        const ordinal = typeof element === "string" ? ordinalsOf(prototype, kind).get(element) : element.ordinal;
        if (!Number.isInteger(ordinal)) return;
        const partId = xbfElementId(index);
        // As the engine spells it (by name where it has one), or by its ordinal, as a ref may.
        const spelled = [tree.elementRefOf(partId, kind, ordinal, nameOf(prototype, kind, ordinal)), tree.elementRefOf(partId, kind, ordinal, "")];
        if (spelled.includes(wanted)) found.push(xbfElementId(index, kind, ordinal));
      });
    }
    const answer = Object.freeze([...new Set(found)]);
    known.set(text, answer);
    return answer;
  };
  return { resolve };
}

/**
 * Each reference of an entry with the element ids it names on the page (`ids`), by role: what its
 * callout is drawn from and what its selection lights. A reference the engine found broken keeps
 * the ids of its candidates (`candidateIds`), which the section lists, and none of its own.
 */
export function resolvePmiEntryRefs(entry, resolver) {
  return entry.refs.map(ref => ({
    ...ref,
    ids: ref.status === "ok" ? resolver.resolve(ref.ref) : [],
    candidateIds: ref.status === "ambiguous" ? ref.candidates.flatMap(candidate => resolver.resolve(candidate)) : []
  }));
}
