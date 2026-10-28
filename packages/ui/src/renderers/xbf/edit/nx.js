/**
 * Edit mode in SolidWorks' words (Amy, 2026-10-26: "SolidWorks names", as the tools now behave as
 * SolidWorks' do; NX's words, chosen 2026-10-23, are still found by the command search). Its commands
 * as SolidWorks' CommandManager names them, its features as the FeatureManager design tree lists them
 * (Boss-Extrude1, Fillet1), the toolbar's tabs (its groups keep Fusion's arrangement), and Extrude's
 * Boss or Cut. What the screen says only: the script, and the notes the agent reads with the person's
 * next message, keep their own names. The file and its exports keep the name they were made with.
 */
import { treeFeatures } from "./editMode.js";

/** A modeling command as SolidWorks' CommandManager names it. A Boss/Base's dialog switches to its
 * Cut, carrying what was typed (`booleanOf`). */
export const NX_COMMANDS = Object.freeze({
  extrude: "Extruded Boss/Base", cut: "Extruded Cut", revolve: "Revolved Boss/Base", revolve_cut: "Revolved Cut",
  sweep: "Swept Boss/Base", sweep_cut: "Swept Cut", loft: "Lofted Boss/Base", loft_cut: "Lofted Cut",
  hole: "Hole Wizard", fillet: "Fillet", chamfer: "Chamfer", rib: "Rib", draft: "Draft", shell: "Shell",
  pattern: "Pattern", mirror: "Mirror", split: "Split", delete_body: "Delete/Keep Body", plane: "Plane",
  offset_face: "Move Face", delete_face: "Delete Face",
});
export const nxCommand = command => NX_COMMANDS[command?.id] || command?.label || "";

// The commands that add material, each with the one taking the same shape away.
const UNITES = Object.freeze({ extrude: "cut", revolve: "revolve_cut", sweep: "sweep_cut", loft: "loft_cut" });
const SUBTRACTS = Object.freeze(Object.fromEntries(Object.entries(UNITES).map(([unite, subtract]) => [subtract, unite])));

/**
 * The Boss or Cut of a command that has one, the switch in its dialog: `value` ("unite" for the Boss/Base,
 * "subtract" for the Cut) and `other`, the command doing the other one; null for a command without.
 */
export function booleanOf(id) {
  if (UNITES[id]) return { value: "unite", other: UNITES[id] };
  if (SUBTRACTS[id]) return { value: "subtract", other: SUBTRACTS[id] };
  return null;
}

/**
 * The Features tab's groups, in Fusion's arrangement. A group is its title, what it
 * holds (modeling commands by their `EDIT_COMMANDS` id, "sketch", or a tool of the viewer:
 * "select"), and how many of them show as buttons (`shown`); the group's
 * title is its menu, with every one. `end`: it stands at the row's right end. The workspace has
 * no agent, so no group of Ask, Add to context or Annotate. A subtracting command (Extruded Cut...) is not
 * listed: it opens by its unite command's Boolean.
 */
export const SOLID_GROUPS = Object.freeze([
  { title: "Create", items: ["sketch", "extrude", "revolve", "sweep", "loft", "rib", "hole", "pattern", "mirror"], shown: 4 },
  // Move Face first, as Fusion's Modify leads with Press Pull: Move Face and Delete Face edit faces where
  // they are, an imported body's (no history) as well as any.
  { title: "Modify", items: ["offset_face", "fillet", "chamfer", "shell", "draft", "split", "delete_face", "delete_body"], shown: 4 },
  { title: "Construct", items: ["plane"], shown: 1 },
  { title: "Select", items: ["select"], shown: 1 },
]);

// The tabs as SolidWorks' CommandManager names them.
const TAB_TITLES = Object.freeze({ solid: "Features", sketch: "Sketch", inspect: "Evaluate", assemble: "Assembly", drafting: "Drawing" });

/**
 * The toolbar's tabs, in order, each `{ id, title }`: Solid, Sketch and Inspect; Assemble for an
 * assembly (`assembly`); Drafting where a drawing's sheet has commands to offer (`drawing`). While a
 * sketch is edited (`sketching`) its task environment has the Sketch tab alone.
 */
export function workspaceTabs({ assembly = false, sketching = false, drawing = false } = {}) {
  const ids = sketching ? ["sketch"] : ["solid", "sketch", "inspect", ...(assembly ? ["assemble"] : []), ...(drawing ? ["drafting"] : [])];
  return ids.map(id => ({ id, title: TAB_TITLES[id] }));
}

// A feature's kind as SolidWorks' design tree names it; a kind not here keeps the engine's (Boss-Extrude, Fillet).
export const NX_KINDS = Object.freeze({
  "Boss-Revolve": "Revolve", "Boss-Sweep": "Sweep", "Boss-Loft": "Loft", "Move/Copy": "Move/Copy Body",
  // An imported STEP: one body with no history, as SolidWorks lists Imported1.
  "Offset Face": "Move Face",
});
export const nxKind = kind => NX_KINDS[kind] || kind || "Feature";

// The generator's icon (`lib/nxIcons.generated.jsx`) for each row the design tree lists, by the name it
// gives the row: a feature's kind, the Origin, a sketch, the part or assembly it opens on, its Equations,
// and an assembly's Mates.
const FEATURE_ICON_NAMES = Object.freeze({
  "Boss-Extrude": "extrude", "Cut-Extrude": "extrude", "Intersect-Extrude": "extrude", Revolve: "revolve", "Cut-Revolve": "revolve",
  Sweep: "sweep", "Cut-Sweep": "sweep", Loft: "loft", "Cut-Loft": "loft", Hole: "hole", Rib: "rib",
  Fillet: "blend", Chamfer: "chamfer", Draft: "draft", Shell: "shell", Pattern: "pattern",
  Mirror: "mirror", Split: "split", "Move/Copy Body": "move", Plane: "plane",
  Origin: "csys", Sketch: "sketch", Part: "part", Assembly: "assembly", Equations: "expressions",
  Mates: "assembly-constraints", Imported: "body", "Move Face": "offset-face", "Delete Face": "delete-face",
});

/**
 * The generator's icon for a row of the design tree, by its kind as the engine names it ("Boss-Revolve") or as
 * the tree does ("Revolve"): a Cut wears its Boss's icon. A kind without one of its own reads as a solid feature.
 */
export const featureIconName = kind => FEATURE_ICON_NAMES[nxKind(kind)] || "extrude";

/** An origin plane as SolidWorks names it: "Top Plane". */
export const nxPlane = name => `${name} Plane`;

// A part's rows as SolidWorks' design tree numbers them: each kind counted on its own, in the order
// they are made (Sketch1, Boss-Extrude1, Sketch2, Cut-Extrude1, Fillet1). Row id → its `label` and
// the `name` given in the tree, which stands in its place, as a feature renamed in SolidWorks does.
function numbered(features) {
  const rows = new Map();
  const counts = new Map();
  const next = kind => { const count = (counts.get(kind) || 0) + 1; counts.set(kind, count); return `${kind}${count}`; };
  for (const feature of features || []) {
    if (feature.kind === "Sketch") {
      rows.set(feature.id, { label: next("Sketch"), name: feature.sketch?.title || feature.title });
      continue;
    }
    if (feature.sketch) rows.set(feature.sketch.id, { label: next("Sketch"), name: feature.sketch.title });
    rows.set(feature.id, { label: next(nxKind(feature.kind)), name: feature.named || "" });
  }
  return rows;
}

/**
 * A part's features titled as SolidWorks' design tree lists them: each kind numbered on its own
 * (Sketch1, Boss-Extrude1, Fillet1), or the name given in the tree in its place. Row id → its title.
 */
export function navigatorTitles(features) {
  return new Map([...numbered(features)].map(([id, { label, name }]) => [id, name || label]));
}

/**
 * A row as the design tree numbers it, without the name given in the tree: "Hole2". Empty for a
 * row the design tree does not list, so whoever names a feature (a face's chip, the timeline) can
 * keep its own words.
 */
export const navigatorLabel = (features, id) => numbered(features).get(id)?.label ?? "";

/** Every row's title in a design tree (`featureTree`): a part's, or each of an assembly's parts'. */
export function treeTitles(tree) {
  const lists = tree?.assembly ? (tree.components || []).map(component => component.features) : [tree?.features || []];
  return new Map(lists.flatMap(features => [...navigatorTitles(features)]));
}

const slashed = path => String(path).replace(/\\/g, "/");

/**
 * The feature a failed build is at, and why. The tree is the last part that built; the script that
 * stopped (`edit.error`, its traceback) has moved on from it, and the engine says where it stopped: the
 * frames of the traceback in the project's own files, the deepest first (`edit.failure.frames`, each
 * `{ file, line, text }`, the line as written). The deepest is the line that raised; when that is in a
 * helper, which makes no row, the next is the call the feature's row stands at. So the walk goes outwards
 * from the deepest frame and stops at the first one a feature's line agrees with: the same file, the same
 * number and the same words. A line that moved, was rewritten or is new is no row of this tree, and neither
 * is the neighbour now at its number: nothing is marked that is not known. `{ id, why }`, `why` the
 * error's last line; null when no frame agrees with a feature, or the first that does agrees with two.
 */
export function buildFailure(tree, error, failure) {
  const why = String(error || "").trim().split("\n").at(-1).trim();
  if (!why) return null;
  const features = treeFeatures(tree);
  for (const { file, line, text } of failure?.frames || []) {
    const words = String(text ?? "").trim();
    if (!file || !line || !words) continue;
    const owners = features.filter(feature => (feature.lines || [])
      .some(each => each.line === line && slashed(each.file) === slashed(file) && String(each.text).trim() === words));
    if (owners.length) return owners.length === 1 ? { id: owners[0].id, why } : null;
  }
  return null;
}
