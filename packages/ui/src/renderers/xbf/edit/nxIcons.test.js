import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as cad from "./cadIcons.jsx";
import { COMMAND_ICON_NAMES, COMMAND_ICONS, DRAWING_TOOL_ICONS, SELECT_GROUP_ICON_NAMES, TOOL_ICON_NAMES, ToolIcon } from "./cadIcons.jsx";
import { EDIT_COMMANDS } from "./editMode.js";
import { NX_KINDS, booleanOf, featureIconName } from "./nx.js";
import { SKETCH_TOOLS } from "./sketchMode.js";
import { ConstructionIcon, NormalToIcon, SKETCH_TOOL_ICON_NAMES, SKETCH_TOOL_ICONS, SmartDimensionIcon } from "./sketchIcons.jsx";
import { XBF_TOOL } from "../tools.js";
import { CONNECTED_SELECTION, SELECT_GEOMETRY } from "../xbfSelectionFilter.js";
import { MEASURE_SNAP_KINDS } from "../../kit/tools/measure/measureFilter.js";
import { SHAPE_TOOLS, toolFamily } from "../../../annotation/tools.js";
import { PENCIL_TOOL_ENTRIES } from "../../../annotation/toolbar.jsx";
import { NX_ICON_NAMES, NxIcon, NxIconSprite } from "../../../lib/nxIcons.generated.jsx";

// What Pencil draws with, as its row under the strip lists it.
const PENCIL_TOOLS = PENCIL_TOOL_ENTRIES.map(tool => tool.id);

// The workspace's icons all come from one generator (`scripts/nx-icons.py`), so a command, a tool, a
// row and the sprite have to agree on its names. The sprite is host elements all the way down: read it
// as a tree rather than rendering it.
const MODULE = new URL("../../../lib/nxIcons.generated.jsx", import.meta.url);
const GENERATOR = fileURLToPath(new URL("../../../../scripts/nx-icons.py", import.meta.url));
const GENERATED = readFileSync(MODULE, "utf8");
const tree = node => (node && typeof node === "object" ? [node, ...[node.props?.children ?? []].flat(Infinity).flatMap(tree)] : []);

// An icon component, drawn: the generator's icon it names, which the sprite must have.
function drawnName(Icon, label) {
  assert.equal(typeof Icon, "function", `${label} has an icon`);
  const drawn = Icon({ className: "size-5" });
  assert.equal(drawn.type, NxIcon, `${label} draws the generator's icon`);
  assert.equal(drawn.props.className, "size-5");
  assert.ok(NX_ICON_NAMES.includes(drawn.props.name), `${label} draws "${drawn.props.name}", which the generator has no icon of`);
  return drawn.props.name;
}

// What the generator writes with `flag`, to a file of its own.
function generate(flag, file) {
  const dir = mkdtempSync(path.join(tmpdir(), "nx-icons-"));
  try {
    const out = path.join(dir, file);
    const run = spawnSync("python3", [GENERATOR, flag, out], { encoding: "utf8" });
    assert.equal(run.status, 0, run.stderr);
    return readFileSync(out, "utf8");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("draws every command from the generator", () => {
  for (const { id } of EDIT_COMMANDS) assert.equal(drawnName(COMMAND_ICONS[id], id), COMMAND_ICON_NAMES[id]);
});

test("a subtracting command draws its unite command's icon, its Boolean being set in its dialog", () => {
  const subtracting = EDIT_COMMANDS.filter(({ id }) => booleanOf(id)?.value === "subtract").map(({ id }) => id);
  assert.deepEqual(subtracting, ["cut", "revolve_cut", "sweep_cut", "loft_cut"]);
  for (const id of subtracting) assert.equal(COMMAND_ICON_NAMES[id], COMMAND_ICON_NAMES[booleanOf(id).other], id);
});

test("draws every sketch tool, each its own picture", () => {
  for (const { id } of SKETCH_TOOLS) assert.equal(drawnName(SKETCH_TOOL_ICONS[id], id), SKETCH_TOOL_ICON_NAMES[id]);
  assert.equal(new Set(SKETCH_TOOLS.map(({ id }) => SKETCH_TOOL_ICON_NAMES[id])).size, SKETCH_TOOLS.length);
});

test("draws the strip's tools the workspace shows, each showing what it has in hand", () => {
  // Each of a part's strip tools: Select, Annotate's Pencil and Shapes, Measure, then the model's effects, Explode and Clip.
  assert.deepEqual(Object.keys(TOOL_ICON_NAMES).sort(), [...Object.values(XBF_TOOL), "exploded", "clip"].sort());
  for (const id of ["select", "pencil", "shapes", "measure", "exploded", "clip"]) {
    assert.equal(drawnName(({ className }) => ToolIcon({ id, className }), id), TOOL_ICON_NAMES[id]);
  }
  // As the strip has always shown them: Select and Measure what their filters pick alone, Pencil and
  // Shapes the drawing tool each draws with; each a picture of its own, All the tool's own.
  const inHand = {
    select: ["all", ...SELECT_GEOMETRY.map(({ id }) => id), "position"],
    measure: ["all", ...MEASURE_SNAP_KINDS.map(({ id }) => id)],
    pencil: PENCIL_TOOLS,
    shapes: SHAPE_TOOLS,
  };
  for (const [id, modes] of Object.entries(inHand)) {
    const names = modes.map(mode => drawnName(({ className }) => ToolIcon({ id, mode, className }), `${id}: ${mode}`));
    assert.equal(new Set(names).size, modes.length, `${id} shows each of ${modes.join(", ")} its own way`);
  }
  assert.equal(ToolIcon({ id: "select", mode: "all" }).props.name, TOOL_ICON_NAMES.select);
  assert.equal(ToolIcon({ id: "measure", mode: "all" }).props.name, TOOL_ICON_NAMES.measure);
  // Select's menu also grows a pick (Group faces, Group edges), each drawn its own way.
  const grows = CONNECTED_SELECTION.map(({ id }) => SELECT_GROUP_ICON_NAMES[id]);
  for (const name of grows) assert.ok(NX_ICON_NAMES.includes(name), name);
  assert.equal(new Set([...grows, ...inHand.select.map(mode => ToolIcon({ id: "select", mode }).props.name)]).size, grows.length + inHand.select.length);
  // The row under the strip draws each drawing tool as the strip's button does when it is in hand.
  for (const tool of [...PENCIL_TOOLS, ...SHAPE_TOOLS]) {
    assert.equal(DRAWING_TOOL_ICONS[tool]?.type, NxIcon, tool);
    assert.equal(DRAWING_TOOL_ICONS[tool].props.name, ToolIcon({ id: toolFamily(tool), mode: tool }).props.name, tool);
  }
});

test("draws the toolbar's other buttons and their panels from the generator, each its own", () => {
  const icons = [cad.SketchIcon, cad.ExitSketchIcon, cad.MassPropertiesIcon, cad.DraftAnalysisIcon, cad.InterferenceIcon,
    cad.CompareIcon, cad.AppearanceIcon, cad.MateIcon, cad.DrawingIcon, NormalToIcon, ConstructionIcon,
    cad.UndoIcon, cad.RedoIcon, cad.ExpressionsIcon, cad.AskIcon, cad.AddContextIcon];
  const names = icons.map((Icon, index) => drawnName(Icon, `icon ${index}`));
  assert.equal(new Set(names).size, names.length);
  // The drawing's sheet dimensions as a sketch does; its Undo and Redo are the ribbon's.
  assert.equal(drawnName(SmartDimensionIcon, "Smart Dimension"), SKETCH_TOOL_ICON_NAMES.dimension);
});

// What the design tree lists: a feature by the kind the engine gives it (Boss-Revolve) or the
// name SolidWorks' tree does (Revolve), and the rows that are not features.
const KEPT_NAMES = ["Hole", "Chamfer", "Shell", "Draft", "Rib"];
const ROWS = ["Sketch", "Origin", "Part", "Assembly", "Equations", "Mates"];
const NX_NAMES = [...new Set(Object.values(NX_KINDS)), ...KEPT_NAMES, ...ROWS];

test("draws every design tree row", () => {
  for (const kind of [...NX_NAMES, ...Object.keys(NX_KINDS)]) {
    assert.ok(NX_ICON_NAMES.includes(featureIconName(kind)), `${kind} draws an icon the generator has`);
  }
  // A kind names the same feature either way, so it wears the same icon either way.
  for (const [kind, name] of Object.entries(NX_KINDS)) assert.equal(featureIconName(kind), featureIconName(name), kind);
  // Rows told apart wear different icons; a kind the tree has no picture for reads as a solid feature.
  assert.equal(new Set(NX_NAMES.map(featureIconName)).size, NX_NAMES.length);
  assert.equal(featureIconName("Thicken"), featureIconName("Boss-Extrude"));
});

test("keeps ids of its own", () => {
  const ids = [...GENERATED.matchAll(/\bid="([^"]*)"/g)].map(([, id]) => id);
  assert.ok(ids.length > NX_ICON_NAMES.length, "the module defines its symbols and what they use");
  assert.deepEqual(ids.filter(id => !id.startsWith("nx-")), []);
  assert.equal(new Set(ids).size, ids.length, "each id is defined once");
  // What points at an id points at one of these.
  const used = [...GENERATED.matchAll(/url\(#([^)]*)\)/g)].map(([, id]) => id);
  assert.ok(used.length > 0);
  assert.deepEqual(used.filter(id => !ids.includes(id)), []);
});

test("draws each icon from its symbol in the sprite", () => {
  assert.ok(Object.isFrozen(NX_ICON_NAMES));
  const symbols = tree(NxIconSprite()).filter(element => element.type === "symbol").map(element => element.props.id);
  assert.deepEqual(symbols, NX_ICON_NAMES.map(name => `nx-${name}`));
  for (const name of NX_ICON_NAMES) {
    const drawn = NxIcon({ name, className: "size-4" });
    assert.equal(drawn.props.className, "size-4");
    assert.equal(drawn.props["aria-hidden"], "true");
    assert.deepEqual(tree(drawn).filter(element => element.type === "use").map(element => element.props.href), [`#nx-${name}`]);
  }
});

// Red and green say how something went (failed, passed), so no icon is drawn in them; the set's
// yellow-orange is the one warm color it has. The check is a status mark, not an icon.
test("draws no icon in a status color", () => {
  const hue = hex => {
    const [r, g, b] = [0, 2, 4].map(at => Number.parseInt(hex.slice(at, at + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), chroma = max - min;
    if (chroma < 0.2) return null; // a grey
    const turn = max === r ? (g - b) / chroma : max === g ? (b - r) / chroma + 2 : (r - g) / chroma + 4;
    return (turn * 60 + 360) % 360;
  };
  const status = [];
  for (const [, name, body] of GENERATED.matchAll(/<symbol id="nx-([^"]+)"([\s\S]*?)<\/symbol>/g)) {
    if (name === "check") continue;
    for (const [, hex] of body.matchAll(/#([0-9a-fA-F]{6})\b/g)) {
      const at = hue(hex);
      if (at !== null && (at < 20 || at > 340 || (at > 75 && at < 165))) status.push(`${name}: #${hex}`);
    }
  }
  assert.deepEqual(status, []);
});

test("the module is exactly what the generator writes", () => {
  // Never edited by hand: an icon changes in the generator, which writes the module again.
  assert.ok(generate("--jsx", "nxIcons.generated.jsx") === GENERATED, "run `python3 scripts/nx-icons.py --jsx` and commit what it writes");
});

test("the sheet shows every icon by name at 16, 24 and 32 px, on light and on dark", () => {
  const sheet = generate("--sheet", "sheet.html");
  for (const name of NX_ICON_NAMES) {
    assert.equal(sheet.split(`href="#nx-${name}"`).length - 1, 6, `${name} at three sizes, twice`);
    assert.ok(sheet.includes(`>${name}<`), `${name} is named`);
  }
  for (const size of [16, 24, 32]) assert.ok(sheet.includes(`width="${size}" height="${size}"`), `${size} px`);
});
