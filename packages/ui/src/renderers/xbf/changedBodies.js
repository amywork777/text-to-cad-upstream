// Studio (studio-base): the bodies a rebuild changed, by their geometry (`useChangedBodies.js` lights them once).
import { xbfElementId } from "@cad/core/lib/xbf/xbfScene.js";

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
