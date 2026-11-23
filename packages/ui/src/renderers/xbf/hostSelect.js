// Studio (studio-base): which ids on screen a chat message's picks name (`useHostSelect.js` answers the host with them).
import { parseCadRefToken, parseEngineRef } from "@cad/core/lib/cadRefs.js";
import { xbfElementId } from "@cad/core/lib/xbf/xbfScene.js";
import { createPmiRefResolver } from "./pmi/pmiRefs.js";

const KIND_OF_PREFIX = Object.freeze({ f: "face", e: "edge", v: "vertex" });
const NAMES_KEY = Object.freeze({ face: "faceNames", edge: "edgeNames", vertex: "vertexNames" });

/**
 * A part's picks on the assembly on screen that holds it: Quick Edit names a part's faces and edges by the part's own
 * document (`<part id>#led_module/e:led_module.board_…`), and the assembly's prototypes keep the same element names
 * (`faceNames`, `edgeNames`). An element is found by its name on every instance of a prototype that has it; a part
 * named alone (`led_module`) by the instances whose path ends in it. None where the name is in no part on screen.
 */
function inAssembly(selector, structure) {
  const instances = structure?.instances || [];
  const prototypes = structure?.prototypes || [];
  const one = parseEngineRef(`#${selector}`)?.selectors?.[0];
  if (!one) return [];
  const element = one.element;
  if (typeof element === "string") {
    const kind = KIND_OF_PREFIX[element[0]];
    if (!kind) return [];
    const ids = [];
    instances.forEach((instance, index) => {
      const names = prototypes[instance?.prototype]?.[NAMES_KEY[kind]] || {};
      for (const [ordinal, name] of Object.entries(names)) if (name === element) ids.push(xbfElementId(index, kind, Number(ordinal)));
    });
    return ids;
  }
  if (element !== null && element !== undefined) return [];
  const part = String(selector).split("/").filter(Boolean).pop() || "";
  return part ? instances.flatMap((instance, index) =>
    (String(instance?.path || "").split("/").pop() === part ? [xbfElementId(index)] : [])) : [];
}

/** Whether a reference's file (`cadPath`, as Quick Edit wrote it) is the document on screen: the same path or id, or its tail. */
export function namesDocument(cadPath, documentPath) {
  const ref = String(cadPath || "").replaceAll("\\", "/");
  const own = String(documentPath || "").replaceAll("\\", "/");
  if (!ref || !own) return false;
  return ref === own || own.endsWith(`/${ref}`) || ref.endsWith(`/${own}`);
}

/**
 * The ids on screen the references name (parts and subassemblies by their occurrence refs, faces and edges by
 * the engine's element refs, `pmiRefs.js`'s resolver), and how many of the picks were found and how many are no
 * longer in the model. A pick counts once whatever its selectors resolve to. One naming another document (a part's,
 * where an assembly is on screen) is found by its element's name or its part's (`inAssembly`), else missing.
 *
 * @param {{ references: readonly string[], documentPath: string, tree: object, structure: object | null }} options
 */
export function hostSelectIds({ references, documentPath, tree, structure }) {
  const nodeByRef = new Map();
  for (const id of tree?.nodes?.keys?.() || []) {
    const ref = tree.refOf?.(id);
    if (ref && !nodeByRef.has(ref)) nodeByRef.set(ref, id);
  }
  const resolver = structure ? createPmiRefResolver(structure, tree) : null;
  const ids = [];
  let found = 0;
  let missing = 0;
  for (const reference of references) {
    const parsed = parseCadRefToken(reference);
    if (!parsed) { missing += 1; continue; }
    const named = [];
    if (namesDocument(parsed.cadPath, documentPath)) {
      for (const selector of parsed.selectors) {
        const one = parseEngineRef(`#${selector}`)?.selectors?.[0];
        if (!one) continue;
        if (one.element !== null && one.element !== undefined) named.push(...(resolver?.resolve(`#${selector}`) || []));
        else if (nodeByRef.has(selector)) named.push(nodeByRef.get(selector));
      }
    } else {
      // Another document's picks: a part's, on the assembly on screen that holds it.
      for (const selector of parsed.selectors) named.push(...inAssembly(selector, structure));
    }
    if (named.length) { found += 1; ids.push(...named); } else missing += 1;
  }
  return { ids: [...new Set(ids)], found, missing };
}
