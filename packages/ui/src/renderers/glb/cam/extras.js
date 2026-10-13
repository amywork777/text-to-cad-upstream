/**
 * A CAM job's result as `cadgen cam plan` writes it into `<stem>.cam.glb`: the scene's extras carry
 * `generator: "cadgen cam"` and `cam` (schema 1), which this reads into the one shape the viewer
 * draws (`detect.js` says whether a scene is one). Reading is forgiving: a missing or malformed
 * value takes a plain default, an operation with no index takes its place in the job, a verdict
 * with no status takes it from its errors, so a file written by a newer cadgen still opens.
 * Pure: no three.js, no React.
 */

import { camExtras, carriesCamJob } from "./detect.js";

export { carriesCamJob };

const NONE = Object.freeze([]);

const plainObject = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const list = (value) => (Array.isArray(value) ? value : NONE);
const number = (value, fallback = null) => (typeof value === "number" && Number.isFinite(value) ? value
  : typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : fallback);
const text = (value, fallback = "") => (typeof value === "string" ? value.trim() || fallback
  : typeof value === "number" && Number.isFinite(value) ? String(value) : fallback);

/** A duration in plain words: "35 s", "42 min", "1 h 5 min". */
export function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value === 0) return "0 s";
  if (value < 59.5) return `${Math.max(1, Math.round(value))} s`;
  const minutes = Math.round(value / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** A face token as the prompt grammar writes a selector: its leading "#" is not part of it. */
export const faceSelector = (ref) => String(ref).replace(/^#/, "");

/**
 * The part the job was planned from, the file a row's references name: `document` as the extras
 * write it (relative to the GLB, or absolute), resolved against the GLB's own path. Empty when the
 * extras do not say.
 */
export function camSourcePath(glbPath, document) {
  const named = String(document || "").trim();
  if (!named) return "";
  const absolute = /^(?:[A-Za-z]:)?[\\/]/.test(named);
  const parts = absolute ? named.split("/") : [...String(glbPath || "").split("/").slice(0, -1), ...named.split("/")];
  const out = [];
  for (const part of parts) {
    if (part === "..") out.pop();
    else if (part !== ".") out.push(part);
  }
  return out.join("/");
}

/** The tool's diameter in mm: the operation's, the job's tool list's, else the leading "6 mm" of its plain name. */
function toolDiameter(op, tools) {
  const own = number(op.tool_diameter_mm);
  if (own !== null && own > 0) return own;
  const listed = number(tools[text(op.tool)]?.diameter_mm);
  if (listed !== null && listed > 0) return listed;
  const named = /^\s*(\d+(?:\.\d+)?)\s*mm\b/i.exec(text(op.tool_plain));
  return named ? Number(named[1]) : null;
}

/** A beam's kerf (mm): the operation's tool's, from the job's tool list; null for any other tool. */
function kerf(op, tools) {
  const value = number(tools[text(op.tool)]?.kerf_mm);
  return value !== null && value > 0 ? value : null;
}

/**
 * A setup's frame in part (CAD) coordinates: `axis`, the direction its tool comes from (WCS +Z), and `across`,
 * its WCS +X (a lathe's radial direction), from the extras' `matrix` (part -> WCS, rows WCS X, Y, Z). Without a
 * usable matrix, the axis its `orientation` names ("+Z", "-X", ...), else +Z.
 */
const ORIENTATION_AXES = Object.freeze({ "+Z": [0, 0, 1], "-Z": [0, 0, -1], "+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0], "-Y": [0, -1, 0] });
function unitRow(matrix, row) {
  const values = list(list(matrix)[row]).slice(0, 3).map((value) => number(value));
  if (values.length !== 3 || values.some((value) => value === null)) return null;
  const length = Math.hypot(...values);
  return length > 1e-9 ? values.map((value) => value / length) : null;
}
function setupFrame(rawSetup) {
  const named = typeof rawSetup.orientation === "string" ? ORIENTATION_AXES[rawSetup.orientation.trim().toUpperCase()] : null;
  return { axis: unitRow(rawSetup.matrix, 2) || named || ORIENTATION_AXES["+Z"], across: unitRow(rawSetup.matrix, 0) || [1, 0, 0] };
}

/** A setup's orientation in words: "+Z", or a 3+2 tilt's angles ("A 30° C 90°"). */
function orientationWords(value) {
  if (typeof value === "string") return value.trim();
  if (!plainObject(value)) return "";
  return Object.entries(value).map(([key, angle]) => [/^([abc])_deg$/i.exec(key)?.[1], number(angle)])
    .filter(([axis, angle]) => axis && angle !== null && angle !== 0).map(([axis, angle]) => `${axis.toUpperCase()} ${angle}°`).join(" ") || "+Z";
}

function toolType(op, tools) {
  const own = text(op.tool_type) || text(tools[text(op.tool)]?.type);
  if (own) return own;
  return /\bball\b/i.test(text(op.tool_plain)) ? "ball" : "";
}

function readFinding(raw) {
  if (!plainObject(raw)) return null;
  const level = text(raw.level) || text(raw.severity) || "warning";
  const message = text(raw.message) || text(raw.summary) || text(raw.description) || text(raw.check);
  if (!message) return null;
  const at = list(raw.at).map((value) => number(value)).filter((value) => value !== null);
  return {
    check: text(raw.check), level: level === "error" ? "error" : level === "warning" ? "warning" : level, message,
    operation: Number.isInteger(number(raw.operation)) ? number(raw.operation) : null,
    at: at.length === 3 ? at : null,
  };
}

/**
 * The job a CAM result carries, or null for any other GLB.
 *
 * @returns {null | { schema: number, verdict: { status: "ready" | "fix", headline: string, errors: number, warnings: number },
 *   setups: { id: string, plain: string, timeS: number, orientation: string, axis: number[], across: number[], operations: object[] }[],
 *   operations: object[], findings: object[], adapted: object[], posts: object[], durationS: number, machine: string,
 *   stock: { kind: string, thicknessMm: number | null }, document: string, material: string }}
 *   A setup's `axis` is the direction its tool comes from and `across` its WCS +X, both in part coordinates (`setupFrame`);
 *   `orientation` is in words. Each operation: `{ index, op, plain, name, tool, toolPlain, toolDiameterMm, toolType, kerfMm,
 *   rpm, feedMmMin, timeS, t0, t1, summary, faces, limits, setup }`, `index` the one `_CAM_OP` and a finding's `operation` name.
 */
export function readCamJob(root) {
  if (!carriesCamJob(root)) return null;
  let cam = null;
  root.traverse((object) => { if (!cam) cam = camExtras(object); });
  const tools = Object.fromEntries(list(cam.tools).filter(plainObject).map((tool) => [text(tool.id), tool]));
  const operations = [];
  const setups = [];
  let clock = 0;
  for (const [setupIndex, rawSetup] of list(cam.setups).entries()) {
    if (!plainObject(rawSetup)) continue;
    const id = text(rawSetup.id, `setup-${setupIndex + 1}`);
    const plain = text(rawSetup.plain, id);
    const own = [];
    for (const rawOp of list(rawSetup.operations)) {
      if (!plainObject(rawOp)) continue;
      const index = Number.isInteger(number(rawOp.index)) ? number(rawOp.index) : operations.length;
      const timeS = Math.max(0, number(rawOp.time_s, 0));
      const t0 = number(rawOp.t0, clock);
      const t1 = Math.max(t0, number(rawOp.t1, t0 + timeS));
      clock = Math.max(clock, t1);
      const plainWord = text(rawOp.plain) || text(rawOp.op, "Operation");
      const toolPlain = text(rawOp.tool_plain) || text(rawOp.tool);
      const op = {
        index, op: text(rawOp.op), plain: plainWord, name: text(rawOp.name), tool: text(rawOp.tool), toolPlain,
        toolDiameterMm: toolDiameter(rawOp, tools), toolType: toolType(rawOp, tools), kerfMm: kerf(rawOp, tools),
        rpm: number(rawOp.rpm), feedMmMin: number(rawOp.feed_mm_min), timeS: timeS || t1 - t0, t0, t1,
        summary: text(rawOp.summary) || [plainWord, toolPlain && `with ${toolPlain}`].filter(Boolean).join(" "),
        faces: list(rawOp.faces).map((face) => text(face)).filter(Boolean),
        limits: list(rawOp.limits).map((limit) => text(limit)).filter(Boolean),
        setup: id,
      };
      own.push(op);
      operations.push(op);
    }
    const timeS = number(rawSetup.time_s, own.reduce((sum, op) => sum + op.timeS, 0));
    setups.push({ id, plain, timeS, orientation: orientationWords(rawSetup.orientation), ...setupFrame(rawSetup), operations: own });
  }
  const findings = list(cam.findings).map(readFinding).filter(Boolean)
    .sort((a, b) => (a.level === "error" ? 0 : 1) - (b.level === "error" ? 0 : 1));
  const rawVerdict = plainObject(cam.verdict) ? cam.verdict : {};
  const errors = number(rawVerdict.errors, findings.filter((finding) => finding.level === "error").length);
  const warnings = number(rawVerdict.warnings, findings.filter((finding) => finding.level === "warning").length);
  const status = rawVerdict.status === "ready" || rawVerdict.status === "fix" ? rawVerdict.status : errors > 0 ? "fix" : "ready";
  const durationS = number(cam.duration_s, operations.reduce((end, op) => Math.max(end, op.t1), 0));
  const toolCount = new Set(operations.map((op) => op.tool).filter(Boolean)).size;
  const headline = text(rawVerdict.headline) || (status === "fix" ? `${errors} to fix`
    : ["Ready to cut", formatDuration(durationS), toolCount ? `${toolCount} tool${toolCount === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · "));
  return {
    schema: number(cam.schema, 1),
    verdict: { status, headline, errors, warnings },
    setups, operations, findings,
    adapted: list(cam.adapted).filter(plainObject).map((entry) => ({ step: text(entry.step), note: text(entry.note) })),
    // A setup may post several files (one per tool on a controller without tool changes), each naming its `tool`.
    posts: list(cam.posts).filter(plainObject).map((entry) => ({ setup: text(entry.setup), file: text(entry.file), post: text(entry.post), tool: text(entry.tool) })),
    durationS,
    machine: text(cam.machine?.kind) || text(cam.machine),
    stock: { kind: text(cam.stock?.kind), thicknessMm: number(cam.stock?.thickness_mm) },
    document: text(cam.document),
    material: typeof cam.material === "string" ? cam.material : text(cam.material?.name),
  };
}

/** An operation of the job by its index, or null. */
export const camOperation = (job, index) => job?.operations.find((op) => op.index === index) || null;

/** An operation row's detail: its tool and its time ("6 mm flat · 5 min"). */
export const operationDetail = (op) => [op.toolPlain, formatDuration(op.timeS)].filter(Boolean).join(" · ");
