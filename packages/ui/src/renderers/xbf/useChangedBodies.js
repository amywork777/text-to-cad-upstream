// Studio (studio-base): the bodies the agent's turn changed, lit once on the first rebuild after a turn began
// (`tab-store/workingHost.ts`), so an engineer sees what moved. `XbfRenderer.jsx` adds them to what it lights.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { xbfElementId } from "@cad/core/lib/xbf/xbfScene.js";
import { workingHost } from "../../tab-store/workingHost.js";

/** How long the changed bodies stay lit: one look, then the model as it was (no animation runs meanwhile). */
export const CHANGED_FLASH_MS = 800;
const EMPTY = Object.freeze([]);

/** Each part on screen by its occurrence ref, with the geometry it draws (its prototype's key). */
export function bodyKeys(structure, tree) {
  const keys = new Map();
  (structure?.instances || []).forEach((instance, index) => {
    const id = xbfElementId(index);
    const ref = tree?.refOf?.(id) || id;
    const key = structure.prototypes?.[instance?.prototype]?.key ?? instance?.prototype;
    keys.set(ref, { id, key: String(key ?? "") });
  });
  return keys;
}

/** The parts whose geometry is new or different from `before` (by ref): a part only moved or recoloured is not. */
export function changedBodies(before, after) {
  if (!before) return EMPTY;
  const changed = [];
  for (const [ref, now] of after) if (before.get(ref)?.key !== now.key) changed.push(now.id);
  return changed;
}

/**
 * The part ids to light now: none, except for `CHANGED_FLASH_MS` after the first rebuild following the start of a
 * turn, when they are the parts that rebuild changed. A rebuild with no turn begun (the person's own edit, a reload)
 * lights nothing.
 *
 * @param {{ structure: object | null, tree: object }} model
 */
export function useChangedBodies({ structure, tree }) {
  const turns = useSyncExternalStore(workingHost.subscribe, workingHost.turns, workingHost.turns);
  // The last model seen, its bodies, and how many turns had begun then: a turn's start alone is no rebuild.
  const seen = useRef({ structure: null, keys: null, turns });
  const [lit, setLit] = useState(EMPTY);
  const timer = useRef(0);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (!structure || seen.current.structure === structure) return;
    const keys = bodyKeys(structure, tree);
    const last = seen.current;
    seen.current = { structure, keys, turns };
    const changed = last.turns !== turns ? changedBodies(last.keys, keys) : EMPTY;
    if (!changed.length) return;
    clearTimeout(timer.current);
    setLit(changed);
    timer.current = setTimeout(() => setLit(EMPTY), CHANGED_FLASH_MS);
  }, [structure, tree, turns]);
  return lit;
}
