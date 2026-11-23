// Studio (studio-base): which ids on screen a chat message's picks name (`useHostSelect.js` answers the host with them).
import { parseCadRefToken, parseEngineRef } from "@cad/core/lib/cadRefs.js";
import { createPmiRefResolver } from "./pmi/pmiRefs.js";

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
 * longer in the model. A pick counts once whatever its selectors resolve to; one naming another document is
 * missing here, as the host opens a message's file before it asks.
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
    if (!parsed || !namesDocument(parsed.cadPath, documentPath)) { missing += 1; continue; }
    const named = [];
    for (const selector of parsed.selectors) {
      const one = parseEngineRef(`#${selector}`)?.selectors?.[0];
      if (!one) continue;
      if (one.element !== null && one.element !== undefined) named.push(...(resolver?.resolve(`#${selector}`) || []));
      else if (nodeByRef.has(selector)) named.push(nodeByRef.get(selector));
    }
    if (named.length) { found += 1; ids.push(...named); } else missing += 1;
  }
  return { ids: [...new Set(ids)], found, missing };
}
