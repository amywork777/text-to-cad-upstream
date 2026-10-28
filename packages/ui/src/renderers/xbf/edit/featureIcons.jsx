import { featureIconName } from "./nx.js";
import { NxIcon } from "../../../lib/nxIcons.generated.jsx";

// `nx.js` names the generator's icon of each row, beside NX's names for them; the name is exported
// here too, beside the icons that draw it.
export { featureIconName };

/**
 * The design tree's icons, the generator's (`lib/nxIcons.generated.jsx`), so a row reads before its
 * name does: each feature the ribbon's own picture of it, as NX's design tree repeats its ribbon's
 * icons, and each row that is not a feature (the part or assembly, its Expressions, the datum
 * coordinate system and its planes, a sketch, an assembly's constraints) its own.
 */
// At 16px, as a CAD tree draws its icons, in the 12px the tree keeps for one.
const ICON_CLASS = "-m-0.5 size-4 shrink-0";

/** A row's icon by its kind, as the engine names it or NX does; a kind without one of its own reads as a solid feature. */
export function FeatureIcon({ kind }) {
  return <NxIcon name={featureIconName(kind)} className={ICON_CLASS} />;
}

export const PlaneIcon = () => <FeatureIcon kind="Plane" />;
export const OriginIcon = () => <FeatureIcon kind="Origin" />;
export const SketchIcon = () => <FeatureIcon kind="Sketch" />;
export const PartIcon = () => <FeatureIcon kind="Part" />;
export const AssemblyIcon = () => <FeatureIcon kind="Assembly" />;
export const MateTreeIcon = () => <FeatureIcon kind="Mates" />;
export const ParametersIcon = () => <FeatureIcon kind="Equations" />;
