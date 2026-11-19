/**
 * Select and Measure as Studio's CAD workspace draws them: its icon generator's (`cadIcons.jsx`'s `ToolIcon`, NX's set),
 * on its ribbon and in Select's menu, where the strip keeps the kit's plain glyphs (`XbfSelectionModes.jsx`).
 */
import { SelectIcon } from "../XbfSelectionModes.jsx";
import { ToolIcon } from "./cadIcons.jsx";

/**
 * Select's icon in the CAD workspace, by its filter's badge (`xbfSelectBadge`; the funnel its plain icon); Box select,
 * which NX's set draws no icon for, keeps the kit's.
 */
export function CadSelectIcon({ tool = "select", mode = "all", ...props }) {
  if (tool !== "box") return <ToolIcon id="select" mode={mode} className={props.className} />;
  return <SelectIcon tool={tool} mode={mode} {...props} />;
}

// Measure's badge (`measureBadge`, Select's glyphs) as the CAD workspace's Measure icons name its kinds.
const CAD_MEASURE_MODES = Object.freeze({ points: "vertex", edges: "edge", faces: "face" });

/** Measure's icon in the CAD workspace, by its filter's badge (`MeasureFilterMenu.jsx`'s `measureBadge`), as Select's is. */
export function CadMeasureIcon({ mode = "all", className }) {
  return <ToolIcon id="measure" mode={CAD_MEASURE_MODES[mode] || mode} className={className} />;
}

/** Select's menu's tool row in the CAD workspace (`SelectMenu`'s `toolIcon`): Select wears the generator's, as its ribbon does. */
export const cadSelectToolIcon = item => (item.id === "select" ? <ToolIcon id="select" className="size-3.5" /> : null);
