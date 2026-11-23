// Studio (studio-base): a scene's Model tab as an engineer reads it. A file whose nodes are named by their place in the
// assembly ("arm_assembly/head_assembly/led_module", a scene's flat list of nodes) is nested by those places, each name
// is written as a name ("LED module"), an instance's tag after a colon kept as a muted suffix ("base hinge"), and a
// fastener named by its size ("M5×30 screw"). Only in Studio's host (`tab-store/studioNames.ts`); Jake's own viewer
// shows the file's names as they are. Studio's chat names files the same way (`apps/web/.../workbench/partNames.ts`).

const ACRONYMS = new Set(["abs", "asa", "ble", "cnc", "dc", "fdm", "hdmi", "imu", "lcd", "led", "mcu", "nema", "pcb",
  "pcba", "petg", "pla", "psu", "rf", "sla", "sls", "tpu", "usb"]);
const FASTENER = /(?:^|[_\s-])(screw|bolt|nut|locknut|washer|standoff|insert|rivet|pin)s?(?:$|[_\s-])|^(iso|din)\d+/i;
// Fastener standards an engineer knows by what they are.
const STANDARDS = Object.freeze({ iso4762: "socket head screw", din912: "socket head screw", iso7380: "button head screw",
  iso10642: "countersunk screw", iso4017: "hex head screw", iso4032: "hex nut", din934: "hex nut", iso7040: "locknut",
  din985: "locknut", iso7089: "washer", din125: "washer" });
/** The longest a row's name is drawn whole; longer, its middle gives way, the whole name in its tooltip. */
export const NAME_ROOM = 30;

const capitalize = text => (text ? text[0].toUpperCase() + text.slice(1) : text);

/** A stem as a name: "led_module" reads "LED module", "m5" "M5", "headAssembly" "Head assembly". */
export function humanName(stem) {
  const words = String(stem || "").replace(/([a-z]{2})([A-Z])/g, "$1 $2").split(/[\s_.-]+/).filter(Boolean);
  if (!words.length) return String(stem || "");
  const cased = words.map(word => {
    const lower = word.toLowerCase();
    if (ACRONYMS.has(lower)) return lower.toUpperCase();
    if (/^m\d/i.test(word)) return word.toUpperCase().replace(/X(?=\d)/g, "×");
    if (/^[a-z]+[A-Z]/.test(word) || /\d/.test(word)) return word;
    return lower;
  });
  return capitalize(cased.join(" "));
}

/** A fastener's name by its size and kind ("m5x30_screw" → "M5×30 screw", "iso4762_m3x8" → "M3×8 socket head screw"), or null. */
function fastenerName(stem) {
  const text = String(stem || "").toLowerCase();
  const size = /m(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?/.exec(text);
  const standard = /(iso|din)\s*_?(\d+)/.exec(text);
  const kind = standard ? STANDARDS[`${standard[1]}${standard[2]}`] : /(locknut|nut|washer|bolt|screw|standoff|insert|rivet|pin)/.exec(text)?.[1];
  if (!kind || !size) return null;
  return `M${size[1]}${size[2] ? `×${size[2]}` : ""} ${kind}`;
}

/** What a node's name says: `{ name, suffix, kind }`, kind "assembly", "fastener" or "part"; `full` the name as the file has it. */
export function sceneNodeName(label, { branch = false } = {}) {
  const full = String(label || "");
  const last = full.split("/").filter(Boolean).at(-1) || full;
  const [stem, ...tags] = last.split(":");
  const suffix = tags.length ? humanName(tags.join(" ")).toLowerCase() : "";
  const fastener = !branch && FASTENER.test(stem) ? fastenerName(stem) : null;
  return Object.freeze({ name: fastener || humanName(stem), suffix, full, kind: branch ? "assembly" : fastener || FASTENER.test(stem) ? "fastener" : "part" });
}

/** A name too long for its row with its middle given way ("Arm assembly … LED module"); a short one as it is. */
export function middleTruncate(text, room = NAME_ROOM) {
  const value = String(text || "");
  if (value.length <= room) return value;
  const keep = room - 1;
  const head = Math.ceil(keep / 2);
  return `${value.slice(0, head).trimEnd()}…${value.slice(value.length - (keep - head)).trimStart()}`;
}

/**
 * The tree as Studio draws it: nodes named by their place nested under groups of those places (a group made only where
 * no node of that name holds them), and every node named as an engineer names it, its label too (`studio: { name,
 * suffix, kind, full }`). Ids are kept, so a pick on the model still finds its row; a group's id is `studio-group:<place>`.
 *
 * @param {readonly { id: string, label: string, part: string | null, children: object[] }[]} roots
 */
export function studioSceneTree(roots) {
  const named = node => {
    const children = node.children.map(named);
    const studio = sceneNodeName(node.label, { branch: children.length > 0 });
    // Its label is the name too, so the panel's search and a row's spoken name are the engineer's.
    return { ...node, label: studio.suffix ? `${studio.name} ${studio.suffix}` : studio.name, children, studio };
  };
  if (!roots.some(node => String(node.label || "").includes("/"))) return roots.map(named);
  const top = [];
  const groups = new Map();
  const groupFor = path => {
    if (!path.length) return null;
    const key = path.join("/");
    if (groups.has(key)) return groups.get(key);
    const group = { id: `studio-group:${key}`, label: path.at(-1), part: null, children: [] };
    groups.set(key, group);
    const parent = groupFor(path.slice(0, -1));
    (parent ? parent.children : top).push(group);
    return group;
  };
  for (const node of roots) {
    const path = String(node.label || "").split("/").filter(Boolean);
    const parent = groupFor(path.slice(0, -1));
    (parent ? parent.children : top).push(node);
  }
  return top.map(named);
}
