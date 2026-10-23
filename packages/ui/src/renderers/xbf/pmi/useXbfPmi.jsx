import { useCallback, useEffect, useMemo, useState } from "react";
import { pmiCallText, pmiCallout, pmiChangeRequest, pmiChangeSettled, pmiEntryCall, pmiStatusText, readXbfPmi } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { pmiConstruction, pmiMovedPlacement, pmiPresentationToPart, pmiPresentationToScene } from "@text-to-cad/core/lib/xbf/xbfPmiLayout.js";
import { PmiGlyph } from "./pmiGlyphs.jsx";
import { createPmiRefResolver, resolvePmiEntryRefs } from "./pmiRefs.js";

// An engine document's PMI in the viewer: what the document carries (`structure.pmi`), found on
// the page, drawn and picked; which of it the person has hidden (the file's view, `xbfViewSlices`);
// and the changes asked for it -- a new annotation, a value edited, a label moved -- each the
// `cadgen.engine.pmi` call it would make the code say, which Quick Edit hands the agent
// (`changeChips`). The viewer writes nothing: the model's code is the document's
// source, and a change reaches the view as the engine's next version.

const EMPTY = Object.freeze([]);
const NO_CHANGES = Object.freeze([]);
const glyphOf = entry => (entry.kind === "datum" ? "datum" : entry.kind === "dimension" ? (entry.dimension?.type === "diameter" ? "diameter" : "dimension")
  : entry.kind === "geometric_tolerance" ? entry.tolerance?.characteristic || "frame" : "unsupported");
const callGlyph = call => (call.kind === "datum" ? "datum" : call.kind === "dimension" ? (call.type === "diameter" ? "diameter" : "dimension") : call.characteristic);
const KIND_WORDS = Object.freeze({ datum: "datum", distance: "distance", diameter: "diameter", flatness: "flatness", position: "position" });
const callKind = call => (call.kind === "dimension" ? call.type : call.kind === "datum" ? "datum" : call.characteristic);

/**
 * @param {{ scene: object | null, tree: ReturnType<typeof import("../xbfTree.js").presentXbfTree>, bounds: { min: number[], max: number[] } | null,
 *   moving: boolean, editable: boolean, selectedId: string, onSelect: (id: string) => void }} options
 *   `moving`: the parts stand elsewhere than built (Explode, a pose): a tolerance is of the part as
 *   made, so its callouts are not drawn meanwhile. `editable`: the document is made from code the
 *   agent can change (an `.xbf`), so changes can be asked for. `selectedId`, `onSelect`: the PMI
 *   picked, the renderer's (its Escape and its picks clear it).
 */
export function useXbfPmi({ scene, tree, bounds, moving, editable, selectedId, onSelect }) {
  const structure = scene?.structure || null;
  const read = useMemo(() => readXbfPmi(structure), [structure]);
  const resolver = useMemo(() => createPmiRefResolver(structure, tree), [structure, tree]);
  const entries = useMemo(() => read.map((entry) => {
    // Each reference named as a pick's chip names it ("plate · face 7"), where it is on the page.
    const refs = resolvePmiEntryRefs(entry, resolver).map((ref) => {
      const element = ref.ids.length === 1 ? scene?.describeElement(ref.ids[0]) : null;
      return { ...ref, name: element ? `${element.partName} \u00b7 ${element.kind} ${element.ordinal}` : ref.written };
    });
    // Its part's placement as built: the frame its presentation is in (the part's first occurrence,
    // the one its canonical refs name).
    const instance = entry.part === null ? null : (structure?.instances || []).find(item => item?.prototype === entry.part);
    return { ...entry, refs, callout: pmiCallout(entry), statusText: pmiStatusText(entry), glyph: glyphOf(entry),
      featureIds: [...new Set(refs.flatMap(ref => ref.ids))], frame: instance?.matrix || null };
  }), [read, resolver, structure, scene]);

  const [hoveredId, setHoveredId] = useState("");
  const [hiddenIds, setHiddenIds] = useState(EMPTY);
  const [off, setOff] = useState(false);
  const [changes, setChanges] = useState(NO_CHANGES);
  const restore = useCallback((slice) => { setHiddenIds(slice?.hidden || EMPTY); setOff(Boolean(slice?.off)); }, []);
  const known = useMemo(() => new Set(entries.map(entry => entry.id)), [entries]);
  const selected = known.has(selectedId) ? selectedId : "";
  const hovered = known.has(hoveredId) ? hoveredId : "";

  // A label dragged and not yet written stands where it was let go, until its change goes.
  const placements = useMemo(() => new Map(changes.filter(change => change.kind === "edit" && change.values.presentation)
    .map(change => [change.id, change.values.presentation])), [changes]);
  const constructions = useMemo(() => {
    const found = new Map();
    if (!scene) return found;
    const turns = new Map();
    for (const entry of entries) {
      if (!entry.supported) continue;
      const geometry = {};
      for (const ref of entry.refs) geometry[ref.role] = ref.ids.length === 1 ? scene.elementGeometry(ref.ids[0], { points: true }) : null;
      const first = entry.refs[0]?.ids[0] || entry.id;
      const turn = turns.get(first) || 0;
      turns.set(first, turn + 1);
      // Placements are the part's (as the code writes them); the construction is the scene's.
      const placed = { ...entry, presentation: pmiPresentationToScene(entry.presentation, entry.frame) };
      const construction = pmiConstruction(placed, { geometry, bounds, turn,
        placement: pmiPresentationToScene(placements.get(entry.id) || null, entry.frame) });
      if (construction) found.set(entry.id, construction);
    }
    return found;
  }, [scene, entries, bounds, placements]);

  const shown = useCallback(id => !off && !hiddenIds.includes(id), [off, hiddenIds]);
  // What the file's view keeps of it.
  const slice = useMemo(() => ({ hidden: hiddenIds, off }), [hiddenIds, off]);
  const items = useMemo(() => (moving ? EMPTY : entries.filter(entry => entry.supported && constructions.has(entry.id) && shown(entry.id)).map(entry => ({
    id: entry.id, kind: entry.kind, callout: entry.callout, status: entry.status, problem: entry.statusText,
    construction: constructions.get(entry.id), selected: entry.id === selected, hovered: entry.id === hovered, moved: placements.has(entry.id)
  }))), [moving, entries, constructions, shown, selected, hovered, placements]);

  // What the picked annotation's (and the one under the pointer's) features light.
  const selectedEntry = entries.find(entry => entry.id === selected) || null;
  const hoveredEntry = entries.find(entry => entry.id === hovered) || null;
  const highlight = useMemo(() => ({ selected: selectedEntry?.featureIds || EMPTY, hovered: hoveredEntry?.featureIds[0] || null }),
    [selectedEntry, hoveredEntry]);

  // ---- changes: what Quick Edit hands the agent -------------------------------------------------
  const edit = useCallback((id, values, { placementOnly = false } = {}) => setChanges((now) => {
    const entry = entries.find(item => item.id === id);
    if (!entry?.supported) return now;
    const before = now.find(change => change.key === `edit:${id}`);
    const merged = { ...(before?.values || {}), ...values };
    const change = { key: `edit:${id}`, kind: "edit", id, values: merged, call: pmiEntryCall(entry, merged),
      placementOnly: placementOnly && (!before || before.placementOnly) };
    // Back to what the document says: nothing to ask.
    if (pmiChangeSettled(change, entries)) return before ? now.filter(item => item !== before) : now;
    return before ? now.map(item => (item === before ? change : item)) : [...now, change];
  }), [entries]);
  // A build that has what a change asked for: the change has gone through, and goes.
  useEffect(() => {
    setChanges(now => (now.some(change => pmiChangeSettled(change, entries)) ? now.filter(change => !pmiChangeSettled(change, entries)) : now));
  }, [entries]);
  const add = useCallback(call => setChanges(now => [...now.filter(change => change.key !== `add:${call.id}`), { key: `add:${call.id}`, kind: "add", id: call.id, call }]), []);
  const remove = useCallback(key => setChanges(now => now.filter(change => change.key !== key)), []);
  const clearChanges = useCallback(() => setChanges(now => (now.length ? NO_CHANGES : now)), []);
  const frameOf = useCallback(id => entries.find(entry => entry.id === id)?.frame || null, [entries]);
  const move = useCallback((id, label) => {
    const construction = constructions.get(id);
    if (!construction || !editable) return;
    edit(id, { presentation: pmiPresentationToPart(pmiMovedPlacement(construction.presentation, label), frameOf(id)) }, { placementOnly: true });
  }, [constructions, edit, editable, frameOf]);
  // Pin where it is drawn now: an annotation the code never placed, placed in code as it stands.
  const pin = useCallback((id) => {
    const construction = constructions.get(id);
    if (construction && editable) edit(id, { presentation: pmiPresentationToPart(construction.presentation, frameOf(id)) }, { placementOnly: true });
  }, [constructions, edit, editable, frameOf]);

  const changeChips = useMemo(() => changes.map((change) => {
    const text = pmiChangeRequest(change);
    const kind = KIND_WORDS[callKind(change.call)] || "PMI";
    const label = change.kind === "add" ? `Add ${kind} ${change.id}` : change.placementOnly ? `Move ${change.id}` : `Change ${change.id}`;
    return { key: `pmi:${change.key}`, label, icon: <PmiGlyph name={callGlyph(change.call)} className="size-2.5 shrink-0 text-muted-foreground" aria-hidden="true" />,
      request: text, copy: text, onRemove: () => remove(change.key),
      card: <p className="whitespace-pre-wrap break-all px-2 pb-2 font-mono text-micro leading-4 text-foreground" data-pmi-change-card="">{pmiCallText(change.call)}</p> };
  }), [changes, remove]);

  return {
    entries, items, constructions, selectedId: selected, hoveredId: hovered, selectedEntry, highlight,
    select: onSelect, hover: setHoveredId,
    hiddenIds, off, setOff, restore,
    toggleHidden: id => setHiddenIds(now => (now.includes(id) ? now.filter(item => item !== id) : [...now, id])),
    slice,
    editable, changes, edit, add, remove, clearChanges, move, pin, changeChips
  };
}
