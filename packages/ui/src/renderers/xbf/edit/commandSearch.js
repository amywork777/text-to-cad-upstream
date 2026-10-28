/**
 * Command search, the box S opens: any CAD command found by name, as Fusion's shortcut box and NX's
 * Command Finder find one. Pure. It says what is listed and in what order (`CommandSearchBox.jsx` draws
 * it, and `EditRibbon.jsx` hands it the buttons the toolbar has, which it lists no more than).
 *
 * A command is found by the name the toolbar gives it (SolidWorks': Fillet), then by the words other
 * tools have for it (NX's edge blend, Fusion's press pull). A query is read word by word, in any case: each of its words
 * must begin a word of the name, or of one of those words, so "pat" finds Pattern Feature and
 * "ect" finds nothing. Commands found by their name come before those found by another tool's
 * word, each in the toolbar's order.
 */
import { editCommand } from "./editMode.js";
import { SOLID_GROUPS, booleanOf, nxCommand } from "./nx.js";
import { SKETCH_ENTITIES, SKETCH_FAMILIES, SKETCH_MODIFY, sketchTool } from "./sketchMode.js";

const frozen = words => Object.freeze(Object.fromEntries(Object.entries(words).map(([id, list]) => [id, Object.freeze(list)])));

/**
 * The words other tools use for a command or tool of the Features tab, by its id: NX's and Fusion's for
 * what SolidWorks names otherwise ("edge blend" finds Fillet, "pocket" an Extruded Cut).
 */
export const COMMAND_WORDS = frozen({
  fillet: ["round", "edge blend"], chamfer: ["bevel"], extrude: ["extrude", "pad", "pull"],
  cut: ["pocket", "extrude"], revolve: ["revolve", "lathe", "turn"], revolve_cut: ["groove", "revolve"], loft: ["loft", "through curves"],
  sweep: ["sweep", "sweep along guide"], hole: ["drill", "tap", "thread"], pattern: ["array", "copy", "pattern feature"],
  mirror: ["symmetry", "mirror feature"], shell: ["hollow"], draft: ["taper"], rib: ["web"],
  split: ["split body"], delete_body: ["remove body", "keep body"],
  offset_face: ["press pull", "push pull", "offset face", "offset region"], delete_face: ["remove face", "defeature"],
  plane: ["datum plane", "work plane", "construction plane", "offset plane"], sketch: ["draw", "profile"], measure: ["distance"],
  clip: ["section", "cross section", "edit section"],
});

/** The same for the toolbar's other buttons (Evaluate, Assemble, Drafting, and the sketch's), by their ids. */
export const TOOLBAR_WORDS = frozen({
  mass: ["measure bodies", "weight", "volume"], interference: ["simple interference", "clash"], "normal-to": ["orient view", "look at"],
  appearance: ["edit object display", "color"], expressions: ["parameters", "expressions", "global variables"],
  mate: ["assembly constraints", "constraint"], "insert-components": ["insert component", "add part", "add component"], "make-drawing": ["new sheet", "new drawing"],
  exit: ["finish sketch"], normal: ["orient view to sketch", "look at"], construction: ["convert to/from reference", "reference"],
  dimension: ["rapid dimension"], centerline: ["reference line"], convert: ["project curve"], offset: ["offset curve"],
  trim: ["quick trim"], extend: ["quick extend"], spline: ["studio spline"],
});

// The Solid tab's buttons that are not modeling commands, and what each of the other tabs adds (the Evaluate tab's, then Assemble's,
// then Drafting's), in the toolbar's order, under the names `EditRibbon.jsx` gives them. Select and the agent's buttons are no CAD command.
const SOLID_BUTTONS = Object.freeze({ sketch: "Sketch" });
const TAB_BUTTONS = Object.freeze([
  ["measure", "Measure"], ["mass", "Mass Properties"], ["draft-analysis", "Draft Analysis"], ["interference", "Interference Detection"], ["compare", "Compare"],
  ["clip", "Section View"], ["normal-to", "Normal To"], ["appearance", "Appearance"], ["expressions", "Equations"],
  ["insert-components", "Insert Components"], ["mate", "Mate"], ["exploded", "Exploded View"],
  ["drawing", "Drawing"], ["make-drawing", "Make Drawing"],
]);

const entry = (id, label, { detail = null, words = [] } = {}) => ({ id, label, detail, words: [...(COMMAND_WORDS[id] || []), ...words, ...(TOOLBAR_WORDS[id] || [])] });

// A modeling command: its SolidWorks name (a Cut its own: Extruded Cut).
function commandEntry(command) {
  return entry(command.id, nxCommand(command), { words: [command.label] });
}

// The Solid tab's buttons in its order, a command's Subtract just after it, then the other tabs' buttons.
function workspaceEntries() {
  const entries = [];
  for (const id of SOLID_GROUPS.flatMap(group => group.items)) {
    const command = editCommand(id);
    if (command) {
      entries.push(commandEntry(command));
      const boolean = booleanOf(id);
      if (boolean?.value === "unite") entries.push(commandEntry(editCommand(boolean.other)));
    } else if (SOLID_BUTTONS[id]) {
      entries.push(entry(id, SOLID_BUTTONS[id]));
    }
  }
  for (const [id, label] of TAB_BUTTONS) entries.push(entry(id, label));
  return entries;
}

// A sketch's toolbar: Exit Sketch, the curves to draw and edit (a family's flyout after its first tool), Smart Dimension and
// Construction Geometry, as `EditRibbon.jsx` lays them out.
function sketchEntries() {
  const tools = ids => ids.flatMap(id => SKETCH_FAMILIES[id] || [id]).map(id => entry(id, sketchTool(id).label));
  return [entry("exit", "Exit Sketch"), entry("normal", "Normal To"), ...tools(SKETCH_ENTITIES), ...tools(SKETCH_MODIFY),
    ...tools(["dimension"]), entry("construction", "Construction Geometry")];
}

const WORKSPACE = Object.freeze(workspaceEntries());
const SKETCH = Object.freeze(sketchEntries());
// Fillet, Chamfer and Mirror are a sketch's own tools while it is open: the sketch has no Edge Blend, and a tool stands for the id.
const SKETCH_IDS = new Set(SKETCH.map(each => each.id));
const WHILE_SKETCHING = Object.freeze([...SKETCH, ...WORKSPACE.filter(each => !SKETCH_IDS.has(each.id))]);

const wordsOf = text => String(text ?? "").toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
const begins = (text, queried) => { const words = wordsOf(text); return queried.every(word => words.some(each => each.startsWith(word))); };

/**
 * The commands a query finds, each `{ id, label, detail }`: its name in the toolbar (NX's), and the Boolean
 * that tells a cut from the Extrude it is a Subtract of (`detail`, else null). Nothing typed lists them all,
 * in the toolbar's order: the Solid tab's, then what Evaluate, Assemble and Drafting add. With a sketch open
 * (`sketching`) its tools come first, then the same, a sketch's Fillet, Chamfer and Mirror standing in for the
 * modeling commands of those ids. `labels` is the toolbar's name for a button where it varies (`{ sketch: "Edit Sketch" }`
 * while a sketch is selected), and is what is found and shown for it.
 *
 * @param {string} query
 * @param {{ sketching?: boolean, labels?: Record<string, string> }} [options]
 * @returns {{ id: string, label: string, detail: string | null }[]}
 */
export function findCommands(query, { sketching = false, labels = {} } = {}) {
  const entries = sketching ? WHILE_SKETCHING : WORKSPACE;
  const shown = each => ({ id: each.id, label: labels[each.id] ?? each.label, detail: each.detail });
  const text = String(query ?? "").trim();
  if (!text) return entries.map(shown);
  const queried = wordsOf(text);
  if (!queried.length) return [];
  const named = [];
  const worded = [];
  for (const each of entries) {
    const result = shown(each);
    if (begins(`${result.label} ${result.detail ?? ""}`, queried)) named.push(result);
    else if (each.words.some(word => begins(word, queried))) worded.push(result);
  }
  return [...named, ...worded];
}
