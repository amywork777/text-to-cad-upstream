// Studio (studio-base): the part on screen selects again what a chat message picked (`tab-store/selectHost.ts`,
// a "N picks" chip pressed in Studio's chat). `XbfRenderer.jsx` calls `useHostSelect` once.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { parseCadRefToken, parseEngineRef } from "@cad/core/lib/cadRefs.js";
import { selectHost } from "../../tab-store/selectHost.js";
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

/**
 * Answers the host's ask once the part is read: what it names is the selection, as presses would make it, and the
 * ask is said taken with what was found and lost, so the host never keeps it. Each ask once; a part out of sight
 * (`onScreen` false: the library's picture) answers nothing.
 *
 * @param {{ onScreen: boolean, documentPath: string, tree: object, structure: object | null, select: (ids: string[]) => void }} part
 */
export function useHostSelect({ onScreen, documentPath, tree, structure, select }) {
  const ask = useSyncExternalStore(selectHost.subscribe, selectHost.get, selectHost.get);
  const taken = useRef(null);
  useEffect(() => {
    if (!ask || !onScreen || !structure || taken.current === ask.nonce) return;
    taken.current = ask.nonce;
    const { ids, found, missing } = hostSelectIds({ references: ask.references, documentPath, tree, structure });
    if (ids.length) select(ids);
    selectHost.take(ask.nonce, found, missing);
  }, [ask, onScreen, documentPath, tree, structure, select]);
}
