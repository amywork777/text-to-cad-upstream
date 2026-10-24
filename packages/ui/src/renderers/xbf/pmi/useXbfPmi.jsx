import { useCallback, useEffect, useMemo, useState } from "react";
import { pmiCallText, pmiCallout, pmiChangeRequest, pmiChangeSettled, pmiEntryCall, pmiKey, pmiStatusText, readXbfPmi } from "@text-to-cad/core/lib/xbf/xbfPmi.js";
import { pmiConstructions, pmiMovedPlacement, pmiPresentationToPart } from "@text-to-cad/core/lib/xbf/xbfPmiLayout.js";
import { xbfElementLabel } from "../xbfChips.jsx";
import { newPmiName } from "./pmiCreate.js";
import { PmiGlyph } from "./pmiGlyphs.jsx";
import { createPmiRefResolver, pmiDrawnAt, pmiFeatureIds, resolvePmiEntryRefs } from "./pmiRefs.js";

// An engine document's PMI in the viewer: what the document carries (`structure.pmi`), found on
// the page, drawn and picked; which of it the person has hidden (the file's view, `xbfViewSlices`);
// and the changes asked for it -- a new annotation, a value edited, a label moved -- each the
// `cadgen.engine.pmi` call it would make the code say, which Quick Edit hands the agent
// (`changeChips`). The viewer writes nothing: the model's code is the document's
// source, and a change reaches the view as the engine's next version.
//
// An annotation is known by its part and its id (`key`: an id is unique only on its part). It is
// drawn at the first occurrence of its part that is shown, and about the same faces on each
// (`pmiRefs.js`).

const EMPTY = Object.freeze([]);
const NO_CHANGES = Object.freeze([]);
const glyphOf = entry => (entry.kind === "datum" ? "datum" : entry.kind === "dimension" ? (entry.dimension?.type === "diameter" ? "diameter" : "dimension")
  : entry.kind === "geometric_tolerance" ? entry.tolerance?.characteristic || "frame" : "unsupported");
const callGlyph = call => (call.kind === "datum" ? "datum" : call.kind === "dimension" ? (call.type === "diameter" ? "diameter" : "dimension") : call.characteristic);

/**
 * @param {{ scene: object | null, tree: ReturnType<typeof import("../xbfTree.js").presentXbfTree>, bounds: { min: number[], max: number[] } | null,
 *   moving: boolean, editable: boolean, hiddenParts?: readonly string[], isolatedParts?: readonly string[],
 *   selectedKey: string, onSelect: (key: string) => void }} options
 *   `moving`: the parts stand elsewhere than built (Explode, a pose): a tolerance is of the part as
 *   made, so its callouts are not drawn meanwhile. `editable`: the document is made from code the
 *   agent can change (an `.xbf`), so changes can be asked for. `hiddenParts`, `isolatedParts`: the
 *   instances hidden and isolated (`i3`), as the scene takes them. `selectedKey`, `onSelect`: the
 *   PMI picked (its `key`), the renderer's (its Escape and its picks clear it).
 */
export function useXbfPmi({ scene, tree, bounds, moving, editable, hiddenParts = EMPTY, isolatedParts = EMPTY, selectedKey, onSelect }) {
  const structure = scene?.structure || null;
  const instances = structure?.instances || EMPTY;
  const read = useMemo(() => readXbfPmi(structure), [structure]);
  const resolver = useMemo(() => createPmiRefResolver(structure, tree), [structure, tree]);
  // A part's name, which a request names the part's annotate call by.
  const partNameOf = useCallback(part => (part === null ? "" : structure?.prototypes?.[part]?.name || ""), [structure]);
  const entries = useMemo(() => read.map((entry) => {
    // Each reference named as a pick's chip names it ("plate · face 7"), where it is on the page.
    const refs = resolvePmiEntryRefs(entry, resolver).map(ref => ({ ...ref, name: (ref.ids.length === 1 && xbfElementLabel({ scene, tree }, ref.ids[0])) || ref.written }));
    return { ...entry, refs, callout: pmiCallout(entry), statusText: pmiStatusText(entry), glyph: glyphOf(entry), partName: partNameOf(entry.part),
      featureIds: pmiFeatureIds({ ...entry, refs }, instances) };
  }), [read, resolver, scene, tree, partNameOf, instances]);

  const [hoveredKey, setHoveredKey] = useState("");
  const [hiddenKeys, setHiddenKeys] = useState(EMPTY);
  const [off, setOff] = useState(false);
  const [changes, setChanges] = useState(NO_CHANGES);
  const [datumFocus, setDatumFocus] = useState("");
  useEffect(() => { setDatumFocus(""); }, [selectedKey, structure]);
  const restore = useCallback((slice) => { setHiddenKeys(slice?.hidden || EMPTY); setOff(Boolean(slice?.off)); }, []);
  const known = useMemo(() => new Set(entries.map(entry => entry.key)), [entries]);
  const selected = known.has(selectedKey) ? selectedKey : "";
  const hovered = known.has(hoveredKey) ? hoveredKey : "";

  // Where each is drawn: the first occurrence of its part shown, or nowhere (`pmiDrawnAt`).
  const drawnAt = useMemo(() => new Map(entries.map(entry => [entry.key, pmiDrawnAt(entry, instances, { hidden: hiddenParts, isolated: isolatedParts })])),
    [entries, instances, hiddenParts, isolatedParts]);
  // A label dragged and not yet written stands where it was let go, until its change goes.
  const placements = useMemo(() => new Map(changes.filter(change => change.kind === "edit" && change.values.presentation)
    .map(change => [change.entryKey, change.values.presentation])), [changes]);
  const constructions = useMemo(() => {
    // The scene's elements stand where Explode or a pose moved them: nothing is built from them
    // meanwhile (and nothing pinned), and the parts at rest are built afresh.
    if (!scene || moving) return new Map();
    const drawn = entries.flatMap((entry) => {
      const at = drawnAt.get(entry.key);
      return at ? [{ entry, elements: at.elements, frame: at.frame }] : [];
    });
    return pmiConstructions(drawn, { geometry: id => scene.elementGeometry(id, { points: true }), bounds, placements });
  }, [scene, moving, entries, drawnAt, bounds, placements]);

  const shown = useCallback(key => !off && !hiddenKeys.includes(key), [off, hiddenKeys]);
  // What the file's view keeps of it.
  const slice = useMemo(() => ({ hidden: hiddenKeys, off }), [hiddenKeys, off]);
  const items = useMemo(() => (moving ? EMPTY : entries.filter(entry => constructions.has(entry.key) && shown(entry.key)).map(entry => ({
    key: entry.key, id: entry.id, kind: entry.kind, callout: entry.callout, status: entry.status, problem: entry.statusText,
    construction: constructions.get(entry.key), selected: entry.key === selected, hovered: entry.key === hovered, moved: placements.has(entry.key)
  }))), [moving, entries, constructions, shown, selected, hovered, placements]);

  // What the picked annotation's (and the one under the pointer's) features light, where it is drawn.
  const drawnFeatureIds = useCallback(key => drawnAt.get(key)?.featureIds || EMPTY, [drawnAt]);
  const selectedEntry = entries.find(entry => entry.key === selected) || null;
  const focusedDatum = entries.find(entry => entry.key === datumFocus && entry.kind === "datum" && entry.part === selectedEntry?.part) || null;
  const highlight = useMemo(() => ({ selected: drawnFeatureIds((focusedDatum || selectedEntry)?.key), hovered: drawnFeatureIds(hovered)[0] || null }),
    [drawnFeatureIds, focusedDatum, selectedEntry, hovered]);

  // ---- changes: what Quick Edit hands the agent -------------------------------------------------
  const edit = useCallback((key, values, { placementOnly = false } = {}) => setChanges((now) => {
    const entry = entries.find(item => item.key === key);
    if (!entry?.supported) return now;
    const before = now.find(change => change.key === `edit:${key}`);
    const merged = { ...(before?.values || {}), ...values };
    const change = { key: `edit:${key}`, kind: "edit", entryKey: key, part: entry.part, partName: entry.partName, id: entry.id, values: merged,
      call: pmiEntryCall(entry, merged), placementOnly: placementOnly && (!before || before.placementOnly) };
    // Back to what the document says: nothing to ask.
    if (pmiChangeSettled(change, entries)) return before ? now.filter(item => item !== before) : now;
    return before ? now.map(item => (item === before ? change : item)) : [...now, change];
  }), [entries]);
  // A build that has what a change asked for: the change has gone through, and goes.
  useEffect(() => {
    setChanges(now => (now.some(change => pmiChangeSettled(change, entries)) ? now.filter(change => !pmiChangeSettled(change, entries)) : now));
  }, [entries]);
  // The new annotations asked for (each its part and its call), whose ids and letters a next one on that part must not take.
  const pending = useMemo(() => changes.filter(change => change.kind === "add").map(change => ({ part: change.part, call: change.call })), [changes]);
  const add = useCallback((part, call) => setChanges((now) => {
    const key = `add:${pmiKey(part, call.id)}`;
    return [...now.filter(change => change.key !== key), { key, kind: "add", part, partName: partNameOf(part), id: call.id, call }];
  }), [partNameOf]);
  const remove = useCallback(key => setChanges(now => now.filter(change => change.key !== key)), []);
  const clearChanges = useCallback(() => setChanges(now => (now.length ? NO_CHANGES : now)), []);
  // Its placement's frame where it is drawn: a placement is written back in its part's frame.
  const frameOf = useCallback(key => drawnAt.get(key)?.frame || null, [drawnAt]);
  const move = useCallback((key, label) => {
    const construction = constructions.get(key);
    if (!construction || !editable) return;
    edit(key, { presentation: pmiPresentationToPart(pmiMovedPlacement(construction.presentation, label), frameOf(key)) }, { placementOnly: true });
  }, [constructions, edit, editable, frameOf]);
  // Pin where it is drawn now: an annotation the code never placed, placed in code as it stands.
  const pin = useCallback((key) => {
    const construction = constructions.get(key);
    if (construction && editable) edit(key, { presentation: pmiPresentationToPart(construction.presentation, frameOf(key)) }, { placementOnly: true });
  }, [constructions, edit, editable, frameOf]);

  const changeChips = useMemo(() => changes.map((change) => {
    const text = pmiChangeRequest(change);
    const label = change.kind === "add" ? `Add ${newPmiName(change.call)}` : change.placementOnly ? `Move ${change.id}` : `Change ${change.id}`;
    return { key: `pmi:${change.key}`, label, icon: <PmiGlyph name={callGlyph(change.call)} className="size-2.5 shrink-0 text-muted-foreground" aria-hidden="true" />,
      request: text, copy: text, onRemove: () => remove(change.key),
      card: <p className="whitespace-pre-wrap break-all px-2 pb-2 font-mono text-micro leading-4 text-foreground" data-pmi-change-card="">{pmiCallText(change.call)}</p> };
  }), [changes, remove]);

  return {
    entries, items, constructions, selectedKey: selected, hoveredKey: hovered, selectedEntry, highlight, drawnFeatureIds,
    select: onSelect, hover: setHoveredKey, datumFocus,
    focusDatum: key => setDatumFocus(now => (now === key ? "" : key)),
    hiddenKeys, off, setOff, restore,
    toggleHidden: key => setHiddenKeys(now => (now.includes(key) ? now.filter(item => item !== key) : [...now, key])),
    slice,
    editable, changes, pending, edit, add, remove, clearChanges, move, pin, changeChips
  };
}
