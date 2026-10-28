import { FeatureIcon } from "./featureIcons.jsx";
import { featureReference, projectRoot, rowLabel } from "./selectionBar.js";

/**
 * What Ask carries of a feature the person chose (`pick`, from `featurePick`), as a face's selector is what it carries of a
 * face: the statement that makes it, a `text-range` reference to its line in its script (`featureReference`, in the project
 * `state` says the part starts in), and the chip Quick Edit names it by, in the design tree's words ("Hole2") beside
 * its own icon, whose X is `onRemove`: it lets go of the pick. Null where the statement's place is not known.
 *
 * @param {{ state: object | null, tree: object, pick: object | null, onRemove?: () => void }} input
 * @returns {{ reference: import("@text-to-cad/core/prompt").PromptReference, chip: import("../../kit/tools/quick-edit/ReferenceChips.jsx").ReferenceChip } | null}
 */
export function featureAsk({ state, tree, pick, onRemove }) {
  if (!pick) return null;
  const label = rowLabel(tree, pick.id) || pick.feature.title;
  const reference = featureReference({ root: projectRoot(state), pick, label });
  if (!reference) return null;
  return { reference, chip: { key: `feature:${pick.id}`, label, icon: <FeatureIcon kind={pick.sketch ? "Sketch" : pick.feature.kind} />, onRemove } };
}
