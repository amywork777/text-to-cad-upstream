/**
 * A CAM job's result, read into the one shape the viewer draws (`detect.js` says whether a GLB is one):
 *
 * - `readCamPlan`: a 0.11 plan, from the `result.json` its folder holds beside `result.glb` (`cad <type> plan --out`),
 *   the whole result `--json` prints. The GLB is the picture alone: "the numbers are result.json's".
 * - `readCamJob`: a 0.10 `<stem>.cam.glb`, whose scene extras carry `generator: "cad cam"` and the job as `cam`
 *   (schema 1), which a project may still hold.
 *
 * What the plan always writes is required: a result missing one, or holding the wrong kind of value, is refused
 * (`CamResultError`, naming where), never drawn with a default in its place. Pure: no three.js, no React.
 */

import { english } from "../../../i18n/core.js";
import { camExtras, carriesCamJob } from "./detect.js";

export { carriesCamJob };

/** A CAM result that is not as the plan writes one; its message names the value, as `cam.setups[0].id` or `result.json.measurements.setups[0].id`. */
export class CamResultError extends Error {
  constructor(where, what) {
    super(`This CAM result is damaged: ${where} ${what}. Plan the job again to write it anew.`);
    this.name = "CamResultError";
  }
}

const plainObject = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

function object(value, where) {
  if (!plainObject(value)) throw new CamResultError(where, "is not an object");
  return value;
}
function list(raw, key, where) {
  if (!Array.isArray(raw[key])) throw new CamResultError(`${where}.${key}`, "is not a list");
  return raw[key];
}
function number(raw, key, where) {
  if (!isNumber(raw[key])) throw new CamResultError(`${where}.${key}`, "is not a number");
  return raw[key];
}
function whole(raw, key, where) {
  if (!Number.isInteger(raw[key])) throw new CamResultError(`${where}.${key}`, "is not a whole number");
  return raw[key];
}
function text(raw, key, where) {
  if (typeof raw[key] !== "string") throw new CamResultError(`${where}.${key}`, "is not text");
  return raw[key];
}
/** Text the plan writes only where there is some (an operation's name, the verdict's G-code line): "" where it is not. */
function optionalText(raw, key, where) {
  return raw[key] === undefined || raw[key] === null ? "" : text(raw, key, where);
}
function texts(raw, key, where) {
  const values = list(raw, key, where);
  values.forEach((value, k) => { if (typeof value !== "string") throw new CamResultError(`${where}.${key}[${k}]`, "is not text"); });
  return values;
}
function oneOf(raw, key, where, allowed) {
  const value = text(raw, key, where);
  if (!allowed.includes(value)) throw new CamResultError(`${where}.${key}`, `is not one of ${allowed.join(", ")}`);
  return value;
}
function point(value, where) {
  if (!Array.isArray(value) || value.length !== 3 || !value.every(isNumber)) throw new CamResultError(where, "is not a point [x, y, z]");
  return value;
}

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

/**
 * The part the job was planned from, the file a row's references name: `document` as the extras
 * write it (relative to the GLB, or absolute), resolved against the GLB's own path.
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

/** The direction a setup's tool comes from, in part (CAD) coordinates: the third row of its `matrix` (part -> WCS, so WCS +Z). */
function setupAxis(rawSetup, where) {
  const matrix = list(rawSetup, "matrix", where);
  if (matrix.length !== 3) throw new CamResultError(`${where}.matrix`, "is not three rows");
  const row = point(matrix[2], `${where}.matrix[2]`);
  const length = Math.hypot(...row);
  if (!(length > 1e-9)) throw new CamResultError(`${where}.matrix[2]`, "is no direction");
  return row.map((value) => value / length);
}

/**
 * A finding as the viewer shows it, from cad cam's `{ check, severity, summary, items: [{ operation, at, ... }] }`:
 * `operation` is the first operation it names, `operations` every one, `at` the first place. An item names an
 * operation and a place only where it has one.
 */
function readFinding(raw, where) {
  object(raw, where);
  const severity = oneOf(raw, "severity", where, ["error", "warning", "info"]);
  const items = list(raw, "items", where).map((item, k) => object(item, `${where}.items[${k}]`));
  const operations = [...new Set(items.flatMap((item, k) => (item.operation === undefined ? [] : [whole(item, "operation", `${where}.items[${k}]`)])))];
  const places = items.flatMap((item, k) => (item.at === undefined ? [] : [point(item.at, `${where}.items[${k}].at`)]));
  return {
    check: text(raw, "check", where), level: severity === "error" ? "error" : "warning", message: text(raw, "summary", where),
    operation: operations.length ? operations[0] : null, operations, at: places[0] || null,
  };
}

/**
 * The job a 0.10 `.cam.glb` carries, or null for any other GLB. A result missing what cad cam always writes throws
 * `CamResultError`.
 *
 * @returns {null | { verdict: { status: "ready" | "fix", headline: string, errors: number, warnings: number, gcode: string },
 *   setups: { id: string, plain: string, timeS: number, orientation: string, axis: number[], operations: object[] }[],
 *   operations: object[], findings: object[], posts: object[], durationS: number, post: string,
 *   tools: object[], toolChanges: number, assumed: { key: string, value: string, why: string }[], document: string, safety: string }}
 *   A setup's `axis` is the direction its tool comes from, in part coordinates. Each operation: `{ index, op, plain, name,
 *   tool, toolPlain, toolDiameterMm, toolType, rpm, feedMmMin, timeS, t0, t1, summary, faces, setup }`, `index` the one
 *   `_CAM_OP` and a finding's `operation` name. `tools` are `readTools`'s.
 */
export function readCamJob(root) {
  if (!carriesCamJob(root)) return null;
  let cam = null;
  root.traverse((object) => { if (!cam) cam = camExtras(object); });
  const where = "cam";
  const listed = list(cam, "tools", where).map((tool, k) => readTool(tool, `${where}.tools[${k}]`));
  const tools = new Map(listed.map((tool) => [tool.id, tool]));
  const operations = [];
  const setups = list(cam, "setups", where).map((rawSetup, s) => {
    const at = `${where}.setups[${s}]`;
    object(rawSetup, at);
    const id = text(rawSetup, "id", at);
    const own = list(rawSetup, "operations", at).map((rawOp, k) => {
      const here = `${at}.operations[${k}]`;
      object(rawOp, here);
      const tool = text(rawOp, "tool", here);
      if (!tools.has(tool)) throw new CamResultError(`${here}.tool`, `names ${tool}, a tool the result does not list`);
      const op = {
        index: whole(rawOp, "index", here), op: text(rawOp, "op", here), plain: text(rawOp, "plain", here),
        name: optionalText(rawOp, "name", here), tool, toolPlain: text(rawOp, "tool_plain", here),
        toolDiameterMm: number(rawOp, "tool_diameter_mm", here), toolType: tools.get(tool).type,
        rpm: number(rawOp, "rpm", here), feedMmMin: number(rawOp, "feed_mm_min", here), timeS: number(rawOp, "time_s", here),
        t0: number(rawOp, "t0", here), t1: number(rawOp, "t1", here), summary: text(rawOp, "summary", here),
        faces: texts(rawOp, "faces", here),
        setup: id,
      };
      operations.push(op);
      return op;
    });
    return { id, plain: text(rawSetup, "plain", at), timeS: number(rawSetup, "time_s", at),
      orientation: oneOf(rawSetup, "orientation", at, ["+Z", "-Z"]), axis: setupAxis(rawSetup, at), operations: own };
  });
  const findings = list(cam, "findings", where).map((raw, k) => readFinding(raw, `${where}.findings[${k}]`))
    .sort((a, b) => (a.level === "error" ? 0 : 1) - (b.level === "error" ? 0 : 1));
  return {
    // A plan with errors writes no G-code; its verdict says so ("G-code not written: fix 2 errors first").
    verdict: readVerdict(cam.verdict, `${where}.verdict`),
    setups, operations, findings,
    // A setup may post several files (one per tool on a controller without tool changes), each naming its `tool`.
    posts: list(cam, "posts", where).map((entry, k) => readPost(entry, `${where}.posts[${k}]`)),
    durationS: number(cam, "duration_s", where),
    // The controller the G-code is written for.
    post: text(object(cam.machine, `${where}.machine`), "post", `${where}.machine`),
    tools: readTools(listed, operations),
    toolChanges: countToolChanges(operations),
    // What the plan took that nobody stated (the rapid rate a cycle time is worked out at).
    assumed: list(cam, "assumed", where).map((entry, k) => readAssumed(entry, `${where}.assumed[${k}]`)),
    document: text(cam, "document", where),
    // The caveat every result carries: what the plan is not, and what to check before cutting.
    safety: text(cam, "safety", where),
  };
}

/** A verdict as the plan writes it: `{ status, headline, errors, warnings, gcode? }`. */
function readVerdict(raw, where) {
  object(raw, where);
  return { status: oneOf(raw, "status", where, ["ready", "fix"]), headline: text(raw, "headline", where),
    errors: whole(raw, "errors", where), warnings: whole(raw, "warnings", where), gcode: optionalText(raw, "gcode", where) };
}

/** A posted file as the plan lists it: `{ setup, file, post, tool }`, `tool` its id where the post splits a setup by tool, else none. */
function readPost(raw, where) {
  object(raw, where);
  return { setup: text(raw, "setup", where), file: text(raw, "file", where), post: text(raw, "post", where), tool: optionalText(raw, "tool", where) };
}

// A tool's plain words as the plan writes them (`Tool.plain`, "6 mm flat"), and the type each kind's word names.
const TOOL_PLAIN = /^\S+ mm (flat|ball|bull nose|drill)$/;
const TOOL_TYPE_OF_WORD = Object.freeze({ flat: "flat", ball: "ball", "bull nose": "bull", drill: "drill" });

/**
 * A 0.11 finding (every check's `CheckFinding`: `{ severity, code, message, location, hint }`) as the viewer shows one.
 * `location` is the places its items name, joined by ", ": a face's ref, a point "(x, y, z)" or "operation N" (one
 * more than the operation's `index`). `operations` are the ones it names, by number or as cutting a face it names
 * (an operation's `faces`), `operation` the first; `at` its first point. Each only where the location has one.
 */
function readCheckFinding(raw, where, operations) {
  object(raw, where);
  const severity = oneOf(raw, "severity", where, ["error", "warning", "info"]);
  const places = optionalText(raw, "location", where);
  const points = [...places.matchAll(/\(([^()]*)\)/g)].map((match) => {
    const values = match[1].split(",").map((value) => (value.trim() === "" ? Number.NaN : Number(value)));
    if (values.length !== 3 || !values.every(isNumber)) throw new CamResultError(`${where}.location`, `holds ${match[0]}, which is not a point (x, y, z)`);
    return values;
  });
  const indices = new Set(operations.map((op) => op.index));
  const named = [];
  const name = (index) => { if (!named.includes(index)) named.push(index); };
  for (const place of places.replace(/\([^()]*\)/g, "").split(",").map((part) => part.trim()).filter(Boolean)) {
    const numbered = /^operation (\d+)$/.exec(place);
    if (numbered) {
      const index = Number(numbered[1]) - 1;
      if (!indices.has(index)) throw new CamResultError(`${where}.location`, `names operation ${numbered[1]}, which the result does not list`);
      name(index);
    } else {
      for (const op of operations) if (op.faces.includes(place)) name(op.index);
    }
  }
  return {
    check: text(raw, "code", where), level: severity === "error" ? "error" : "warning", message: text(raw, "message", where),
    operation: named.length ? named[0] : null, operations: named, at: points[0] || null,
  };
}

/**
 * The job of a 0.11 plan, from the `result.json` beside its `result.glb`: the whole result as `cad <type> plan --json`
 * prints it (`ok`, `path` the part planned, `findings`, `measurements`), in `readCamJob`'s shape. The plan's own
 * numbers throughout: its setups (`measurements.setups`, each its operations from `measurements.operations`, by
 * `setup`), its tools (`measurements.tools`, each as the operations that run it say: `tool_plain` and
 * `tool_diameter_mm`, its type the kind `tool_plain` names), its tool changes (`tool_changes.count`) and its verdict.
 * A result missing what the plan always writes throws `CamResultError`.
 */
export function readCamPlan(raw) {
  const top = object(raw, "result.json");
  const where = "result.json.measurements";
  const numbers = object(top.measurements, where);
  const toolIds = texts(numbers, "tools", where);
  const setupRows = list(numbers, "setups", where).map((row, k) => object(row, `${where}.setups[${k}]`));
  const setupIds = setupRows.map((row, k) => text(row, "id", `${where}.setups[${k}]`));
  const tools = new Map();
  const operations = list(numbers, "operations", where).map((rawOp, k) => {
    const here = `${where}.operations[${k}]`;
    object(rawOp, here);
    const tool = text(rawOp, "tool", here);
    if (!toolIds.includes(tool)) throw new CamResultError(`${here}.tool`, `names ${tool}, a tool the result does not list`);
    const setup = text(rawOp, "setup", here);
    if (!setupIds.includes(setup)) throw new CamResultError(`${here}.setup`, `names ${setup}, a setup the result does not list`);
    const toolPlain = text(rawOp, "tool_plain", here);
    const kind = TOOL_PLAIN.exec(toolPlain);
    if (!kind) throw new CamResultError(`${here}.tool_plain`, "names no kind of tool (flat, ball, bull nose or drill)");
    const toolDiameterMm = number(rawOp, "tool_diameter_mm", here);
    const known = tools.get(tool);
    if (!known) tools.set(tool, { id: tool, type: TOOL_TYPE_OF_WORD[kind[1]], diameterMm: toolDiameterMm, plain: toolPlain });
    else if (known.plain !== toolPlain || known.diameterMm !== toolDiameterMm) {
      throw new CamResultError(`${here}.tool_plain`, `says ${tool} is a ${toolPlain}, where an earlier operation says a ${known.plain}`);
    }
    return {
      index: whole(rawOp, "index", here), op: text(rawOp, "op", here), plain: text(rawOp, "plain", here),
      name: optionalText(rawOp, "name", here), tool, toolPlain, toolDiameterMm, toolType: tools.get(tool).type,
      rpm: number(rawOp, "rpm", here), feedMmMin: number(rawOp, "feed_mm_min", here), timeS: number(rawOp, "time_s", here),
      t0: number(rawOp, "t0", here), t1: number(rawOp, "t1", here), summary: text(rawOp, "summary", here),
      faces: texts(rawOp, "faces", here), setup,
    };
  });
  const listed = toolIds.map((id, k) => {
    if (!tools.has(id)) throw new CamResultError(`${where}.tools[${k}]`, `names ${id}, a tool no operation runs`);
    return tools.get(id);
  });
  const setups = setupRows.map((row, s) => {
    const at = `${where}.setups[${s}]`;
    return { id: setupIds[s], plain: text(row, "plain", at), timeS: number(row, "time_s", at),
      orientation: oneOf(row, "orientation", at, ["+Z", "-Z"]), axis: setupAxis(row, at),
      operations: operations.filter((op) => op.setup === setupIds[s]) };
  });
  const findings = list(top, "findings", "result.json").map((entry, k) => readCheckFinding(entry, `result.json.findings[${k}]`, operations))
    .sort((a, b) => (a.level === "error" ? 0 : 1) - (b.level === "error" ? 0 : 1));
  return {
    verdict: readVerdict(numbers.verdict, `${where}.verdict`),
    setups, operations, findings,
    posts: list(numbers, "posts", where).map((entry, k) => readPost(entry, `${where}.posts[${k}]`)),
    durationS: number(numbers, "duration_s", where),
    post: text(numbers, "post", where),
    tools: readTools(listed, operations),
    toolChanges: whole(object(numbers.tool_changes, `${where}.tool_changes`), "count", `${where}.tool_changes`),
    assumed: list(numbers, "assumed", where).map((entry, k) => readAssumed(entry, `${where}.assumed[${k}]`)),
    document: text(top, "path", "result.json"),
    safety: text(numbers, "safety", where),
  };
}

/** A tool as the result lists it (`Tool.as_dict`): what the viewer reads of it. */
function readTool(raw, where) {
  object(raw, where);
  return { id: text(raw, "id", where), type: oneOf(raw, "type", where, ["flat", "ball", "bull", "drill"]),
    diameterMm: number(raw, "diameter_mm", where), plain: text(raw, "plain", where) };
}

/** An assumed value in words: "grbl", "3000", "false". */
function valueWords(value) {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.map(valueWords).join(", ");
  return String(value);
}

/** What the plan assumed, as it writes it (`{ key, value, why }`), the value in words. */
function readAssumed(raw, where) {
  object(raw, where);
  if (raw.value === undefined || raw.value === null) throw new CamResultError(`${where}.value`, "is missing");
  return { key: text(raw, "key", where), value: valueWords(raw.value), why: text(raw, "why", where) };
}

/** An assumption in one line: "machine.rapid_mm_min 3000". */
export const assumedWords = (entry) => [entry.key, entry.value].filter(Boolean).join(" ");

/** The operations in program order: by when each starts, the job's order where two start together. */
const programOrder = (operations) => operations.map((op, order) => ({ op, order })).sort((a, b) => a.op.t0 - b.op.t0 || a.order - b.order).map(({ op }) => op);

/** The smallest and largest of some values, or null for none. */
function span(values) {
  return values.length ? [Math.min(...values), Math.max(...values)] : null;
}

/**
 * The job's tools, each once, in the order the program first uses them (then any the job lists but no operation
 * uses): `{ id, label, plain, type, diameterMm, operations, rpm, feedMmMin }`. `label` is how the machine names it
 * ("T1"); `plain` what it is ("6 mm flat"); `type` flat, ball, bull or drill; `rpm` and `feedMmMin` the range
 * (`[min, max]`) the operations that use it run it at, or null for a tool no operation uses.
 */
function readTools(listed, operations) {
  const byId = new Map(listed.map((tool) => [tool.id, tool]));
  const ids = [...new Set([...programOrder(operations).map((op) => op.tool), ...byId.keys()])];
  return ids.map((id) => {
    const tool = byId.get(id);
    const uses = operations.filter((op) => op.tool === id);
    return {
      id, label: id, plain: tool.plain, type: tool.type, diameterMm: tool.diameterMm, operations: uses.map((op) => op.index),
      rpm: span(uses.map((op) => op.rpm)), feedMmMin: span(uses.map((op) => op.feedMmMin)),
    };
  });
}

/** The tool changes in the program: one wherever an operation, in program order, runs another tool than the one before it. */
function countToolChanges(operations) {
  let count = 0;
  let last = "";
  for (const op of programOrder(operations)) {
    if (last && op.tool !== last) count += 1;
    last = op.tool;
  }
  return count;
}

const grouped = (value) => Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 });
const ranged = (range, unit) => (range ? `${range[0] === range[1] ? grouped(range[0]) : `${grouped(range[0])}–${grouped(range[1])}`} ${unit}` : "");

/** A tool's speed and feed as the operations that use it run it ("12,000 rpm · 1,440 mm/min"), a range where they differ. */
export const toolSpeeds = (tool) => [ranged(tool.rpm, "rpm"), ranged(tool.feedMmMin, "mm/min")].filter(Boolean).join(" · ");

/** The job's tool changes in words: "No tool changes", "1 tool change", "3 tool changes". */
export const toolChangeWords = (count, t = english) =>
  (count > 0 ? t(count === 1 ? "cam.toolChange" : "cam.toolChanges", { count }) : t("cam.noToolChanges"));

/** What the job takes, under its verdict: its tool changes and the controller its G-code is for ("1 tool change · grbl controller"). */
export function jobSummary(job, t = english) {
  if (!job.operations.length) return "";
  return [toolChangeWords(job.toolChanges, t), job.post ? t("cam.controller", { post: job.post }) : ""].filter(Boolean).join(" · ");
}

/** An operation row's detail: its tool and its time ("6 mm flat · 5 min"). */
export const operationDetail = (op) => [op.toolPlain, formatDuration(op.timeS)].filter(Boolean).join(" · ");
