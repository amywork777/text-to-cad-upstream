/**
 * The workspace's icons, every one from the icon generator (`scripts/nx-icons.py`, drawn by
 * `lib/nxIcons.generated.jsx`): the modeling commands', the toolbar's other buttons and their
 * panels', and the viewer's tools on the strip.
 */
import { NxIcon } from "../../../lib/nxIcons.generated.jsx";

/** One of the generator's icons as a component, sized by the class it is given. */
export const generatedIcon = name => {
  const Icon = ({ className }) => <NxIcon name={name} className={className} />;
  Icon.displayName = `NxIcon(${name})`;
  return Icon;
};

/** Sketch, or Edit Sketch on the one selected; and the sketch's panel. */
export const SketchIcon = generatedIcon("sketch");
/** Finish Sketch. */
export const ExitSketchIcon = generatedIcon("finish-sketch");
/** Measure Bodies: what the part weighs, and where its mass centres. */
export const MassPropertiesIcon = generatedIcon("measure-bodies");
/** Draft Analysis: the part's faces, by how they draw against the pull. */
export const DraftAnalysisIcon = generatedIcon("draft-analysis");
/** Simple Interference: where two bodies fill the same room. */
export const InterferenceIcon = generatedIcon("interference");
/** Compare: the part as it is against a version of it. */
export const CompareIcon = generatedIcon("compare");
/** Edit Object Display: the part's color. */
export const AppearanceIcon = generatedIcon("appearance");
/** Assembly Constraints: a part placed against another. */
export const MateIcon = generatedIcon("assembly-constraints");
/** Insert Components: a part of the project added to the assembly. */
export const InsertComponentIcon = generatedIcon("part");
/** A drawing (Drawing, and New Sheet). */
export const DrawingIcon = generatedIcon("drawing");
/** Expressions: the part's named sizes, and their panel. */
export const ExpressionsIcon = generatedIcon("expressions");
/** Ask, Add to context and Annotate: the agent's buttons in the toolbar and in the bar beside a pick. */
export const AskIcon = generatedIcon("ask");
export const AddContextIcon = generatedIcon("add-context");
export const AnnotateIcon = generatedIcon("annotate");
/** Undo and Redo, the ribbon's. */
export const UndoIcon = generatedIcon("undo");
export const RedoIcon = generatedIcon("redo");

/**
 * The generator's icon each modeling command draws. A subtracting command draws its unite
 * command's, because its Boolean is set in its dialog.
 */
export const COMMAND_ICON_NAMES = Object.freeze({
  extrude: "extrude", cut: "extrude", revolve: "revolve", revolve_cut: "revolve", sweep: "sweep", sweep_cut: "sweep",
  loft: "loft", loft_cut: "loft", rib: "rib", hole: "hole", pattern: "pattern", mirror: "mirror", fillet: "blend",
  chamfer: "chamfer", shell: "shell", draft: "draft", plane: "plane", split: "split", delete_body: "delete",
  offset_face: "offset-face", delete_face: "delete-face",
});

/** Each command's mark, in the ribbon and on its panel. */
export const COMMAND_ICONS = Object.freeze(Object.fromEntries(Object.entries(COMMAND_ICON_NAMES).map(([id, name]) => [id, generatedIcon(name)])));

/**
 * The generator's icon of Select and Measure, the strip's tools that the CAD workspace draws its own way
 * (`XbfSelectionModes.jsx`); the AI layout, and the model's effects, keep the kit's.
 */
export const TOOL_ICON_NAMES = Object.freeze({ select: "select", measure: "measure" });

// What Select and Measure show they have in hand, as the strip always has: what their filters have
// them pick alone (All, the tool's own icon).
/** Select's icon by its filter's mode. */
export const SELECT_ICON_NAMES = Object.freeze({ all: "select", faces: "select-face", edges: "select-edge", parts: "select-part",
  position: "select-position" });
/** How Select's menu grows a pick (`CONNECTED_SELECTION`): Group faces, Group edges. */
export const SELECT_GROUP_ICON_NAMES = Object.freeze({ tangentFaces: "select-face-group", edgeChain: "select-edge-group" });
/** Measure's icon by its filter's mode. */
export const MEASURE_ICON_NAMES = Object.freeze({ all: "measure", vertex: "measure-vertex", edge: "measure-edge", face: "measure-face" });
const IN_HAND = Object.freeze({ select: SELECT_ICON_NAMES, measure: MEASURE_ICON_NAMES });

/**
 * Select's or Measure's icon on the CAD workspace's strip, by what it has in hand (`mode`): its filter
 * mode (`pickModeOf`).
 */
export function ToolIcon({ id, mode = "all", className }) {
  return <NxIcon name={IN_HAND[id]?.[mode] || TOOL_ICON_NAMES[id]} className={className} />;
}
