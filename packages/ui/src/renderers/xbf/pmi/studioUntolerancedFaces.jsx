// Studio (studio-base): PMI's one switch for the faces no tolerance holds. Beside a document's PMI
// the engine serves what its coverage check found of each part (`pmi_coverage`): `uncovered`, the
// faces no toleranced dimension, geometric tolerance or general tolerance is on (a datum, a basic
// dimension and a note hold none). The agent asks what is missing in the chat, so the PMI tab lists
// none of it; what is left here is the picture. **Untoleranced faces**, the checkbox at its heading's
// right end, lights those faces on the model as a pick is lit, on every occurrence of their part.
// Where every face holds a tolerance there is no switch. Jake's files carry one hook each:
// `XbfRenderer.jsx` (the hook, and its faces among what is lit) and `PmiSection.jsx` (the switch).
import { useMemo, useState } from "react";
import { useI18n } from "@cad/ui/i18n";
import { FileSheetSettingsSection } from "../../kit/inspector/FileSheet.js";
import { createPmiRefResolver, pmiFeatureIds } from "./pmiRefs.js";

const EMPTY = Object.freeze([]);
const isRecord = value => Boolean(value) && typeof value === "object" && !Array.isArray(value);

/**
 * Each part's untoleranced faces as the engine spells them (`{ part, uncovered }`), a part with none
 * left out, read defensively: a field missing or of the wrong type is none.
 *
 * @param {object | null} structure  A served document's structure.
 * @returns {Array<{ part: number | null, uncovered: string[] }>}
 */
export function readUntolerancedFaces(structure) {
  const served = Array.isArray(structure?.pmi_coverage) ? structure.pmi_coverage : EMPTY;
  return served.filter(isRecord).map(item => ({ part: Number.isInteger(item.part) ? item.part : null,
    uncovered: Array.isArray(item.uncovered) ? item.uncovered.filter(ref => typeof ref === "string" && ref) : [] }))
    .filter(item => item.uncovered.length > 0);
}

/**
 * The switch's state and what it lights: `available` where some face holds no tolerance, `shown`
 * while the switch is on, `show(on)`, and `faceIds`, the faces lit (none while it is off: they are
 * found on the page only then).
 *
 * @param {{ structure: object | null, tree: ReturnType<typeof import("../xbfTree.js").presentXbfTree> | null }} options
 */
export function useUntolerancedFaces({ structure, tree }) {
  const [on, show] = useState(false);
  const parts = useMemo(() => readUntolerancedFaces(structure), [structure]);
  const shown = on && parts.length > 0;
  const faceIds = useMemo(() => {
    if (!shown || !tree) return EMPTY;
    const resolver = createPmiRefResolver(structure, tree);
    const instances = structure?.instances || EMPTY;
    return [...new Set(parts.flatMap(item => pmiFeatureIds({ part: item.part,
      refs: [{ ids: item.uncovered.flatMap(ref => resolver.resolve(ref)) }] }, instances)))];
  }, [shown, parts, structure, tree]);
  return useMemo(() => ({ available: parts.length > 0, shown, show, faceIds }), [parts, shown, faceIds]);
}

/** The switch, a heading of PMI's own with its checkbox, where some face holds no tolerance. */
export function UntolerancedFacesSwitch({ untoleranced }) {
  const { t } = useI18n();
  if (!untoleranced?.available) return null;
  return <FileSheetSettingsSection title={t("pmi.untoleranced")} sectionId="pmi-untoleranced"
    enabled={untoleranced.shown} onEnabledChange={untoleranced.show} />;
}
