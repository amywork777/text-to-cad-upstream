/**
 * Studio's CAD mode as the XBF view (`XbfRenderer.jsx`) wears it. A document whose part has a script CAD mode edits is
 * CAD mode's too (`useXbfCadMode.jsx`): laid out for modeling it by hand, a CAD tool's toolbar and design tree over the
 * same view and picks. The view holds what must be read before CAD mode is (`useXbfCadState`: the rollback bar's body,
 * the part's units, CAD mode's own Escape) and calls CAD mode once it has its picks (`useXbfCadSurface`); the rest are
 * its pieces here, each called from one line of the view.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ScrollArea } from "@cad/ui/primitives/scroll-area";
import { ToolStackContext } from "../../kit/tools/ToolStack.jsx";
import { goneFromEngine } from "../useXbfScene.js";
import { WORKSPACE_SELECTION_COLOR } from "./editLayout.js";
import { rollbackExport } from "./rollbackExport.js";
import { useXbfCadMode } from "./useXbfCadMode.jsx";

const EMPTY = Object.freeze([]);
// CAD mode's PMI, a section docked under the FeatureManager and always open: nothing sits on the model.
// `panelHead` draws it as the column's section (`ToolPanel`'s docked mode): no box, the dock's head pinned over it.
const PMI_DOCKED = Object.freeze({ panelHead: true });

/**
 * What the view reads of CAD mode before it reads CAD mode (set by `useXbfCadSurface`): the rollback bar's body while
 * the bar is up (`rollback`: a document of its own the edit service handed the engine, opened by its id and drawn and
 * picked in the part's place), the units the part reads in (`units`: Measure reads in them, as SolidWorks' does), CAD
 * mode's own layers under Escape (`held`: a command's dialog open, the bar beside a feature chosen), and CAD mode as last
 * read (`ref`: what a press means to its open command first, its double-clicks, its Escape).
 */
export function useXbfCadState() {
  const [rollback, setRollback] = useState("");
  const [units, setUnits] = useState("");
  const [held, setHeld] = useState(false);
  const ref = useRef(null);
  return { rollback, units, held, ref, setRollback, setUnits, setHeld };
}

/**
 * CAD mode on the view (`useXbfCadMode`'s options, with the isolated rows and what the view read, `error`), what it reads
 * back into `state`, and the view's chips (`ownChips`) with a face picked named by the feature that made it. Returns
 * CAD mode, with those chips (`chips`) and the colour a pick is drawn in (`highlightColor`: the workspace's own while it
 * is up, else the viewer's).
 */
export function useXbfCadSurface(state, { tree, isolatedIds, error, setChosen, ownChips, ...options }) {
  // The isolated rows by name, which CAD mode reads to say which part of an assembly to open to change it.
  const isolatedLabels = useMemo(() => isolatedIds.map(id => tree.nodes.get(id)?.label).filter(Boolean), [tree, isolatedIds]);
  const cad = useXbfCadMode({ ...options, tree, setChosen, isolated: isolatedIds.length > 0, isolatedLabels });
  state.ref.current = cad;
  const { rollback, setUnits, setRollback, setHeld, ref } = state;
  useEffect(() => { setUnits(cad.units); }, [cad.units]);
  useEffect(() => { setRollback(cad.rollback); }, [cad.rollback]);
  // The bar's body gone from the engine: the bar is rolled to the end, and CAD mode says why.
  useEffect(() => { if (rollback && goneFromEngine(error)) ref.current?.rollbackGone(); }, [rollback, error]);
  // What was picked on one body names nothing on the other: the bar's body and the part number their faces apart.
  useEffect(() => { setChosen(now => (now.length ? EMPTY : now)); }, [rollback]);
  useEffect(() => { setHeld(cad.escapeActive); }, [cad.escapeActive]);
  // A face picked names the feature that made it, in CAD mode (`nameChips`).
  const nameChips = cad.nameChips;
  const chips = useMemo(() => nameChips(ownChips), [nameChips, ownChips]);
  return { ...cad, chips, highlightColor: cad.editing ? WORKSPACE_SELECTION_COLOR : null };
}

/**
 * What Export writes while CAD mode's rollback bar may be up: the body on screen is then not the document, so Export
 * keeps writing the part as it last stood on screen (`rollbackExport`). `current`: the export of what is on screen.
 */
export function useRollbackExport(current, rollback) {
  const exported = useRef({ kept: null, bars: new Set() });
  if (rollback) exported.current.bars.add(rollback);
  const exportView = rollbackExport({ current, kept: exported.current.kept, rollback, bars: exported.current.bars });
  exported.current.kept = exportView;
  return exportView;
}

/**
 * CAD mode's design tree (`dock`, its `frame.leftDock`) with the PMI section docked under it (`pmi`, none where the
 * document has none): the tree as tall as its rows, up to 75% of the column, past which it scrolls; PMI directly under
 * it, filling the rest and scrolling inside itself.
 */
export function cadLeftDock(dock, pmi) {
  return dock && pmi ? <div className="grid min-h-0 flex-1 grid-rows-[fit-content(75%)_minmax(0,1fr)]">
    <div className="flex min-h-0 flex-col overflow-hidden">{dock}</div>
    <ScrollArea barShown className="border-t border-border" data-cad-dock="pmi">
      <ToolStackContext.Provider value={PMI_DOCKED}>{pmi}</ToolStackContext.Provider>
    </ScrollArea>
  </div> : dock;
}
