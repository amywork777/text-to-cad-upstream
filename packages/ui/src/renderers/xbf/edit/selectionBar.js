/**
 * The selection bar's rules, pure: what it offers beside a pick, when Quick Edit shows in the workspace, which
 * design tree row a selection is, and where the bar stands (`EditSelectionBar.jsx` draws it; `useXbfCadMode.jsx`
 * wires it). Picking a face, an edge or a feature with no command open offers a small bar beside it: Ask,
 * Add to context, Annotate and Edit.
 */
import { validatePromptReference } from "@text-to-cad/core/prompt";
import { treeFeatures } from "./editMode.js";
import { faceFeature, faceReference } from "./faceChips.js";
import { navigatorLabel } from "./nx.js";

/** How far the bar stands from what it is about (`GAP`), and from the view's edges and below the toolbar (`EDGE`), in px. */
export const SELECTION_BAR_GAP_PX = 10;
export const SELECTION_BAR_EDGE_PX = 8;

// What the bar is about. A part, a vertex or a plane is none of them.
const PICK_KINDS = Object.freeze(["face", "edge", "feature"]);
const BUSY_WORDS = "Wait for the change in progress to finish.";

// A row of the design tree or the timeline is its own feature, if there is anything to edit in it.
const ownFeature = pick => (pick.kind === "feature" && pick.editable !== false ? pick.id : null);
const featureKey = feature => (feature && typeof feature === "object" ? feature.id : feature);

/**
 * What the bar offers beside the picks, in its order, each `{ id, enabled, reason? }` (`reason`: why it is held):
 * Ask, Add to context and Annotate, and Edit when there is one feature to edit. Nothing in the AI layout, with
 * nothing picked, with a pick that is not a face, an edge or a feature, or while a command or a sketch is open
 * (`commandOpen`, `sketching`): the bar is for choosing what to do with a pick, and an open command is doing it.
 *
 * `picks`: `{ kind: "face" | "edge" | "feature", id }` each; a feature's `editable: false` says it has nothing to
 * edit. `featureOf(pick)`: the feature that made a pick, its id (null: not known), which is how a face
 * comes to have an Edit once the engine says which feature made it; a row of the design tree or the timeline
 * is its own. Edit is Edit Feature, on the one feature every pick is the work of; `busy` holds it while a
 * change is on its way, as the design tree holds a double-click.
 *
 * @param {{ editing: boolean, picks?: { kind: string, id: string, editable?: boolean }[], commandOpen?: boolean,
 *   sketching?: boolean, featureOf?: ((pick: object) => string | { id: string } | null) | null, busy?: boolean }} state
 * @returns {{ id: "ask" | "add-context" | "annotate" | "edit", enabled: boolean, reason?: string }[]}
 */
export function selectionBarActions({ editing, picks, commandOpen = false, sketching = false, featureOf = null, busy = false }) {
  if (!editing || commandOpen || sketching) return [];
  if (!Array.isArray(picks) || !picks.length || !picks.every(pick => PICK_KINDS.includes(pick?.kind))) return [];
  const actions = [{ id: "ask", enabled: true }, { id: "add-context", enabled: true }, { id: "annotate", enabled: true }];
  const features = picks.map(pick => featureOf?.(pick) || ownFeature(pick));
  if (features.every(Boolean) && new Set(features.map(featureKey)).size === 1) {
    actions.push(busy ? { id: "edit", enabled: false, reason: BUSY_WORDS } : { id: "edit", enabled: true });
  }
  return actions;
}

/**
 * Whether Quick Edit shows. With the CAD workspace chosen (`cad`, `editLayout.js`'s `cadChosen`) only once the person
 * has asked (`asked`: an Ask), whatever is picked, and then even with nothing picked, on the part as a whole. In the
 * AI layout as it always has: with a selection it can carry (`selectionActionVisible`).
 */
export function quickEditShown({ cad, asked, selectionActionVisible }) {
  return cad ? Boolean(asked) : Boolean(selectionActionVisible);
}

/**
 * The drawing tools (Pencil, Shapes) the strip shows. They are Annotate's tools, which write to the agent, so the CAD workspace
 * chosen (`cad`, `cadChosen`) has none, even while the engine is still asked whether the part can be edited; the AI layout has
 * them as the viewer ships.
 */
export function stripDrawingTools({ cad, drawing }) {
  return cad ? [] : drawing;
}

/**
 * What Quick Edit is handed to carry: in the AI layout the picks while it shows (`open`), else nothing. The CAD workspace chosen
 * (`cad`, `cadChosen`) has no agent to send them to, so it is given no box at all (`references: null`).
 */
export function quickEditCarries({ cad, open, carried, empty }) {
  if (cad) return { references: null, chips: empty };
  return { references: open ? carried.references : empty, chips: open ? carried.chips : empty };
}

/**
 * Whether the tool in hand must be put down for Select: Pencil or Shapes (`toolMode`) when the CAD workspace is chosen (`cad`,
 * `cadChosen`), whose strip has neither (`stripDrawingTools`), or a click would draw instead of select.
 */
export function mustPutDownTool({ cad, toolMode }) {
  return Boolean(cad) && (toolMode === "pencil" || toolMode === "shapes");
}

/**
 * The row of the design tree (`featureTree`) that `selected`, the id the tree and the timeline select by, is, as the bar
 * sees a pick: `{ kind: "feature", id, feature, sketch, editable }`, or null for what is not a feature or a sketch (the
 * origin, a plane, a part of an assembly, nothing). `sketch` is the sketch a double-click on that row edits: a sketch of
 * its own, or the one a feature was made from when that sketch is what is selected. `editable`: there is something to
 * open, as a double-click on the row opens it: Edit Feature on a feature a command made, Edit Sketch on a sketch
 * the script names. An assembly's parts are opened to be edited, so none of its features is.
 */
export function featurePick(tree, selected) {
  if (!selected) return null;
  for (const feature of treeFeatures(tree)) {
    const own = feature.id === selected;
    const nested = feature.kind !== "Sketch" && feature.sketch?.id === selected;
    if (!own && !nested) continue;
    const sketch = (nested || feature.kind === "Sketch") ? feature.sketch : null;
    const opens = sketch ? Boolean(sketch.constrained) : Boolean(feature.edit);
    return { kind: "feature", id: selected, feature, sketch, editable: !tree.assembly && opens };
  }
  return null;
}

/**
 * The row of the design tree that faces picked on the model are (`picks`, as the bar sees them, each with its `reference`), as
 * `featurePick` gives a row: the one feature the engine says made every one of them, by the map for the faces on screen (`faces`,
 * `faceChips.js`'s `shownFaces`), when it has something to open. Null for an edge among them, a face the engine does not know, faces
 * of two features, or a feature with nothing to edit: those picks have no Edit.
 */
export function facePick(tree, picks, faces) {
  if (!Array.isArray(picks) || !picks.length || !picks.every(pick => pick?.kind === "face")) return null;
  const made = new Set(picks.map(pick => faceFeature(faceReference(pick.reference?.displaySelector || pick.reference?.normalizedSelector || pick.id), faces)));
  const [id] = made;
  const row = made.size === 1 && id ? featurePick(tree, id) : null;
  return row?.editable ? row : null;
}

const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const clamp = (value, low, high) => Math.min(Math.max(value, low), Math.max(low, high));

/**
 * Where the bar stands: `{ left, top }` in the view's pixels, or null where what it is about is out of the free part of the
 * view. Above the pick (`box`, its edges on the screen), centred on it and `gap` off; below it where there is no room above;
 * else right of it, else left of it: the first of these that lies inside the view (`bounds`, inset from its edges and below
 * the toolbar) and clear of every card over the view (`obstacles`, boxes like `box`). Where none is free, over the pick,
 * above it as far as the view allows. `size`: the bar's own.
 *
 * @param {{ box: object | null, size: { width: number, height: number }, bounds: object, obstacles?: object[], gap?: number }} input
 */
export function placeBar({ box, size, bounds, obstacles = [], gap = SELECTION_BAR_GAP_PX }) {
  if (!box || !overlaps(box, bounds)) return null;
  const { width, height } = size;
  const across = clamp((box.left + box.right) / 2 - width / 2, bounds.left, bounds.right - width);
  const along = clamp((box.top + box.bottom) / 2 - height / 2, bounds.top, bounds.bottom - height);
  const candidates = [
    { left: across, top: box.top - gap - height },
    { left: across, top: box.bottom + gap },
    { left: box.right + gap, top: along },
    { left: box.left - gap - width, top: along },
  ];
  const free = ({ left, top }) => left >= bounds.left && top >= bounds.top && left + width <= bounds.right && top + height <= bounds.bottom
    && !obstacles.some(obstacle => overlaps({ left, top, right: left + width, bottom: top + height }, obstacle));
  return candidates.find(free) || { left: across, top: clamp(candidates[0].top, bounds.top, bounds.bottom - height) };
}

// A point put where a matrix (as three.js lays out its 16 numbers, column by column) puts it.
const placed = ([x, y, z], e) => (e?.length === 16
  ? [e[0] * x + e[4] * y + e[8] * z + e[12], e[1] * x + e[5] * y + e[9] * z + e[13], e[2] * x + e[6] * y + e[10] * z + e[14]]
  : [x, y, z]);

/**
 * The eight corners of a box of the model (`{ min, max }`, the part's own units), put where `matrix` puts the part they
 * belong to (Explode moves its parts); none for what is not a box. The bar stands by where these fall on the screen.
 */
export function boundsCorners(bounds, matrix = null) {
  const { min, max } = bounds || {};
  const point = value => Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(Number.isFinite);
  if (!point(min) || !point(max)) return [];
  return [min[0], max[0]].flatMap(x => [min[1], max[1]].flatMap(y => [min[2], max[2]].map(z => placed([x, y, z], matrix))));
}

/**
 * The box round some points of the model (`points`, in the part's own units) on the screen, in the view's pixels (`width` by
 * `height`) as the camera sees the part now (`runtime`: its camera, its model group, and three.js), or null where none of
 * them is in front of the camera.
 */
export function screenBox(runtime, points, width, height) {
  const { THREE, camera, modelGroup } = runtime;
  const point = new THREE.Vector3(), seen = new THREE.Vector3();
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const [x, y, z] of points) {
    point.set(x, y, z).applyMatrix4(modelGroup.matrixWorld);
    // In front of the camera at all: its depth range is the model's, and a corner of a box can fall just past it.
    const inFront = seen.copy(point).applyMatrix4(camera.matrixWorldInverse).z < 0;
    point.project(camera);
    if (!inFront || !Number.isFinite(point.x + point.y)) continue;
    const px = ((point.x + 1) / 2) * width, py = ((1 - point.y) / 2) * height;
    left = Math.min(left, px); right = Math.max(right, px); top = Math.min(top, py); bottom = Math.max(bottom, py);
  }
  return Number.isFinite(left) ? { left, top, right, bottom } : null;
}

const slashed = path => String(path ?? "").replace(/\\/g, "/");

/**
 * Where the part's project starts, as an absolute path with `/`s, which the files a feature is in (`file`, named from it) are
 * relative to: what the engine says of the state it read (`state.root`), else its script's own path (`state.script`) less the
 * script's name among the files it read (`state.files`, the longest if two agree). Empty where neither says, never a guess.
 */
export function projectRoot(state) {
  const root = slashed(state?.root).replace(/\/+$/, "");
  if (root) return root;
  const script = slashed(state?.script);
  const own = Object.keys(state?.files || {}).map(slashed).filter(name => name && script.endsWith(`/${name}`)).sort((a, b) => b.length - a.length)[0];
  return own ? script.slice(0, script.length - own.length - 1) : "";
}

/**
 * A row as the design tree numbers it without the name given in the tree ("Hole2"), in a part's tree or in whichever
 * part of an assembly has it; empty for a row it does not list.
 */
export function rowLabel(tree, id) {
  const lists = tree?.assembly ? (tree.components || []).map(component => component.features) : [tree?.features || []];
  for (const features of lists) {
    const label = navigatorLabel(features, id);
    if (label) return label;
  }
  return "";
}

/**
 * The statement a feature (or sketch) chosen (`pick`, from `featurePick`) stands for in its script, as a prompt reference: a
 * `text-range` over its lines, whole, from its first to its last where the engine read the statement (`end`), else its first
 * alone, in the script's absolute path (the feature's `file` is named from the project's top, `root`, unless it lies outside
 * it, when the engine names it in full), under the words the design tree names it by (`label`: "Hole2"). What Ask
 * carries for a feature, as a face's selector is what it carries for a face; Add to context delivers the same. Null where it
 * cannot be told: no project, or no file or line, or a path the prompt does not take.
 */
export function featureReference({ root, pick, label }) {
  const source = pick?.sketch || pick?.feature;
  const file = slashed(source?.file), line = Number(source?.line);
  if (!file || !Number.isSafeInteger(line) || line < 1) return null;
  const last = Number.isSafeInteger(source.end) && source.end >= line ? source.end : line;
  const path = /^(?:[A-Za-z]:)?\//.test(file) ? file : root ? `${slashed(root).replace(/\/+$/, "")}/${file}` : "";
  if (!path) return null;
  try {
    return validatePromptReference({ resource: { kind: "workspace-file", path },
      target: { kind: "text-range", start: { line: line - 1, character: 0 }, end: { line: last, character: 0 } }, ...(label ? { label } : {}) });
  } catch {
    return null;
  }
}

const NOTHING = Object.freeze([]);

/**
 * What the picks are, in the prompt grammar and as Quick Edit's chips: the model's selection (`selection`, its `selectionChips`)
 * where it can be read (`selectionActionVisible`), the same arrays the surface read; and the feature chosen (`feature`:
 * `{ reference, chip }`, `featureAsk`) after it. What Ask has Quick Edit carry, and what Add to context delivers.
 */
export function pickedReferences({ selectionActionVisible, selection, selectionChips, feature }) {
  const model = Boolean(selectionActionVisible);
  if (!feature) return { references: model ? selection : NOTHING, chips: model ? selectionChips : NOTHING };
  return { references: [...(model ? selection : NOTHING), feature.reference], chips: [...(model ? selectionChips : NOTHING), feature.chip] };
}

/**
 * What Quick Edit's X or a send lets go of: everything picked, as a press on the model's background does; but while a command
 * or a sketch holds the selection (an Edge Blend's edges, `held`), the box alone, so a note written before it opened never
 * empties the command's picks.
 */
export const quickEditLetsGo = ({ held }) => (held ? "box" : "selection");
