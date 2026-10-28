import { CONNECTED_SELECTION, SELECT_GEOMETRY, connectedSelectionApplies } from './xbfSelectionFilter.js';
import { DropdownMenuCheckboxItem } from '@text-to-cad/ui/primitives/dropdown-menu';
import SelectFilterMenu from "../kit/tools/select/SelectFilterMenu.jsx";
import { MEASURE_MODES } from "../kit/tools/measure/MeasureFilterMenu.jsx";
import { useControlUsage } from "../../usage/controls.js";
import { useI18n } from "@text-to-cad/ui/i18n";
import { NxIcon } from "../../lib/nxIcons.generated.jsx";
import { SELECT_GROUP_ICON_NAMES, ToolIcon } from "./edit/cadIcons.jsx";

// Select's button, Measure's and Select's menu, which read on an engine document as the STEP
// renderer's did. Every icon is the icon generator's (`edit/cadIcons.jsx`, NX's set, drawn from the
// sprite the frame mounts): a mode's row as the strip's button shows that mode chosen.

/** The Select tool's button icon: what it picks alone (`mode`), the pointer for All. */
export function SelectIcon({ mode = "all", className }) {
  return <ToolIcon id="select" mode={mode} className={className} />;
}

/** The Measure tool's button icon: what it measures alone (`mode`), the ruler for All. */
export function MeasureIcon({ mode = "all", className }) {
  return <ToolIcon id="measure" mode={mode} className={className} />;
}

const modeIcon = (tool, mode) => <ToolIcon id={tool} mode={mode} className="size-3.5" />;
// The overlays All picks too, beside the model's geometry: the annotations and measurements,
// drawn over the model, so a click on one is never mistaken for the face under it.
const SELECT_OVERLAYS = Object.freeze(['annotation', 'measurement']);
/** All, what an engine document's Select picks when a file opens, as a STEP's: Parts too, which a part file offers no mode of its own. */
export const XBF_SELECT_DEFAULT = Object.freeze([...SELECT_GEOMETRY.map(kind => kind.id), 'position', ...SELECT_OVERLAYS]);

/**
 * An engine document's Select modes, a STEP's: All (the default: a face or an edge, else the part,
 * Position's knobs, the annotations and the measurements), then each alone — Parts (in an
 * assembly), Faces, Edges, and Position (where the file has joints: its knobs, the model picks nothing).
 */
export function xbfSelectModes({ assembly, posable }) {
  return [
    { id: 'all', label: 'All', key: 'pick.all', kinds: XBF_SELECT_DEFAULT, icon: modeIcon('select', 'all') },
    ...SELECT_GEOMETRY.filter(item => assembly || !item.assemblyOnly).map(item => ({ id: item.id, label: item.label, key: item.key, kinds: [item.id], icon: modeIcon('select', item.id) })),
    ...(posable ? [{ id: 'position', label: 'Position', key: 'pick.position', kinds: ['position'], icon: modeIcon('select', 'position') }] : []),
  ];
}

/** Measure's modes (`MEASURE_MODES`), each row drawn as the strip's Measure shows it. */
export const XBF_MEASURE_MODES = Object.freeze(MEASURE_MODES.map(mode => ({ ...mode, icon: modeIcon('measure', mode.id) })));

/**
 * An engine document's Select menu, a STEP's (`kit/tools/select/SelectFilterMenu.jsx`): its modes
 * (`xbfSelectModes`), one chosen; then the connected-selection options that do something under it —
 * Group faces while it picks faces, Group edges while it picks edges. An option that does nothing
 * is not shown, and keeps its choice for when it does.
 *
 * @param {{ value: readonly string[], onChange(filter: readonly string[]): void, assembly: boolean, posable: boolean,
 *   connected: { edgeChain: boolean, tangentFaces: boolean },
 *   onConnectedChange(id: "edgeChain" | "tangentFaces", checked: boolean): void, disabled?: boolean }} props
 */
export function SelectModeMenu({ value, onChange, assembly, posable, connected, onConnectedChange, disabled = false }) {
  const options = CONNECTED_SELECTION.filter(option => connectedSelectionApplies(option.id, value));
  const controls = useControlUsage();
  const { t } = useI18n();
  return <SelectFilterMenu value={value} onChange={onChange} modes={xbfSelectModes({ assembly, posable })} disabled={disabled}>
    {options.length ? options.map(option => <DropdownMenuCheckboxItem key={option.id} checked={connected[option.id] === true}
      onSelect={event => event.preventDefault()} onCheckedChange={checked => {
        controls.used(option.id === 'tangentFaces' ? 'select_group_faces' : 'select_group_edges');
        onConnectedChange(option.id, checked === true);
      }}>
      <NxIcon name={SELECT_GROUP_ICON_NAMES[option.id]} className="size-3.5" />{t(option.key)}
    </DropdownMenuCheckboxItem>) : null}
  </SelectFilterMenu>;
}
