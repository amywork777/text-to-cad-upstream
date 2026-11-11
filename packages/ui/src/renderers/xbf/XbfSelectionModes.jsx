import { SELECT_GEOMETRY } from './xbfSelectionFilter.js';
import SelectFilterMenu from "../kit/tools/select/SelectFilterMenu.jsx";
import { filterBadge } from "../kit/tools/select/selectFilter.js";
import { useI18n } from "@cad/ui/i18n";
import { ModeGlyph, ToolModeIcon } from "../kit/tools/select/modeGlyphs.jsx";
import { ToolIcon } from "./edit/cadIcons.jsx";

// Select's button, Measure's and Select's menu, which read on an engine document as the STEP
// renderer's did. The glyphs are the kit's (`kit/tools/select/modeGlyphs.jsx`); in Studio's CAD
// workspace (`cad`) they are its icon generator's (`edit/cadIcons.jsx`, NX's set).

/**
 * Select's two tools, how a pick is made: Select, a click picks what is under it and a drag turns the
 * camera; Box select, a drag from empty space draws a box and picks what is visible in it
 * (`@cad/core/lib/viewer/boxSelect.js`: what shows in it, touching it even in part), a drag from the model, its ink or a measurement still turning
 * the camera and a click still picking as Select's do. Select when a file opens.
 */
export const SELECT_TOOLS = Object.freeze([
  { id: 'select', key: 'tool.select', glyph: 'select' },
  { id: 'box', key: 'select.boxSelect', glyph: 'boxSelect' },
]);

/**
 * The Select tool's button icon: the pointer, or Box select's pointer in a square (`tool`), badged
 * with what its filter ticks (`mode`, `xbfSelectBadge`), none for All. In Studio's CAD workspace
 * (`cad`) Select is the icon generator's (`edit/cadIcons.jsx`'s `ToolIcon`, by the badge's kind; the
 * funnel its plain icon); Box select, which NX's set draws no icon for, keeps the kit's.
 */
export function SelectIcon({ tool = "select", mode = "all", cad = false, ...props }) {
  if (cad && tool !== 'box') return <ToolIcon id="select" mode={mode} className={props.className} />;
  return <ToolModeIcon tool={tool === 'box' ? 'boxSelect' : 'select'} mode={mode} {...props} />;
}

// Measure's badge (`measureBadge`, Select's glyphs) as the CAD workspace's Measure icons name its kinds.
const CAD_MEASURE_MODES = Object.freeze({ points: "vertex", edges: "edge", faces: "face" });

/**
 * The Measure tool's button icon: the ruler, badged with what its filter ticks (`mode`, `MeasureFilterMenu.jsx`'s
 * `measureBadge`), none for All; in Studio's CAD workspace (`cad`) the icon generator's, as Select's is.
 */
export function MeasureIcon({ mode = "all", cad = false, ...props }) {
  if (cad) return <ToolIcon id="measure" mode={CAD_MEASURE_MODES[mode] || mode} className={props.className} />;
  return <ToolModeIcon tool="measure" mode={mode} {...props} />;
}

// The overlays Select picks beside the model's geometry, each a kind of its own: the annotations and the
// measurements, drawn over the model, so a click on one is never taken for the face under it.
const SELECT_OVERLAYS = Object.freeze([
  { id: 'annotation', label: 'Annotations', key: 'pick.annotations' },
  { id: 'measurement', label: 'Measurements', key: 'pick.measurements' },
]);
/**
 * Every box ticked, what an engine document's Select picks when a file opens, as a STEP's: the
 * geometry (Parts too, which a part file offers no box of its own), Position's knobs, the annotations
 * and the measurements -- and the order the filter is kept in.
 */
export const XBF_SELECT_DEFAULT = Object.freeze(['parts', 'faces', 'edges', 'position', 'annotation', 'measurement']);
// Each kind's glyph, and Position's, where one is drawn (the badge on Select's button).
const GLYPHS = Object.freeze({ parts: 'parts', faces: 'faces', edges: 'edges', position: 'position' });

/**
 * An engine document's Select filter's kinds, a STEP's: Parts (in an assembly), Faces, Edges, Annotations
 * and Measurements, each ticked on its own; and its extra, Position (where the file has joints: its knobs,
 * shown while it is ticked, beside whatever the kinds pick).
 */
export function xbfSelectKinds({ assembly }) {
  return [...SELECT_GEOMETRY.filter(item => assembly || !item.assemblyOnly), ...SELECT_OVERLAYS];
}
export const xbfSelectExtras = ({ posable }) => (posable ? [{ id: 'position', label: 'Position', key: 'pick.position' }] : []);

/** The badge Select's button wears for `filter`: none for every kind, one kind's glyph, Position's alone, else the funnel. */
export function xbfSelectBadge(filter, { assembly, posable }) {
  return filterBadge(filter, xbfSelectKinds({ assembly }).map(kind => kind.id), { glyphs: GLYPHS, alone: posable ? 'position' : null });
}

/**
 * An engine document's Select menu, a STEP's (`kit/tools/select/SelectFilterMenu.jsx`): its "Selection
 * tool" section, its two tools (`SELECT_TOOLS`), one chosen, since how a pick is made is a choice apart
 * from what it takes; then its one row, "Filter", its kinds ticked (`xbfSelectKinds`) and Position after
 * them. A face's or an edge's tangent chain is the view's menu's to take (Select tangent faces, Select
 * tangent edges), never a setting here.
 *
 * @param {{ value: readonly string[], onChange(filter: readonly string[]): void, assembly: boolean, posable: boolean,
 *   tool?: "select" | "box", onToolChange?(tool: "select" | "box"): void, disabled?: boolean, cad?: boolean }} props
 *   `cad`: Studio's CAD workspace, where Select's row wears the icon generator's Select, as its ribbon does.
 */
export function SelectMenu({ value, onChange, assembly, posable, tool = 'select', onToolChange = null, disabled = false, cad = false }) {
  const { t } = useI18n();
  const toolIcon = item => (cad && item.id === 'select' ? <ToolIcon id="select" className="size-3.5" />
    : <ModeGlyph tool={item.glyph} mode="all" className="size-3.5" aria-hidden="true" />);
  const tools = onToolChange ? {
    value: tool, onChange: onToolChange,
    items: SELECT_TOOLS.map(item => ({ id: item.id, label: t(item.key), icon: toolIcon(item) })),
  } : null;
  const named = items => items.map(item => ({ id: item.id, label: t(item.key) }));
  return <SelectFilterMenu value={value} onChange={onChange} disabled={disabled} tools={tools} order={XBF_SELECT_DEFAULT}
    kinds={named(xbfSelectKinds({ assembly }))} extras={named(xbfSelectExtras({ posable }))} />;
}
