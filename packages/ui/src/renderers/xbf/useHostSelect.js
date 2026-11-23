// Studio (studio-base): the part on screen selects again what a chat message picked (`tab-store/selectHost.ts`,
// a "N picks" chip pressed in Studio's chat). `XbfRenderer.jsx` calls `useHostSelect` once.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { selectHost } from "../../tab-store/selectHost.js";
import { hostSelectIds } from "./hostSelect.js";

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
