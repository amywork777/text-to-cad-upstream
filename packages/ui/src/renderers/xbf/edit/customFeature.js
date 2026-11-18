// A custom feature's dialog, as Onshape builds a FeatureScript feature's from its precondition: one
// control for each declared parameter (a number with its unit, a check box, a list of choices, the faces
// or edges picked on the model), ungrouped ones first and then each group, a group the feature folds
// starting folded. The engine declares them (`cad.build123d.feature`) and reads them back from the call
// (`row.custom.params`); OK writes the call through the custom command (`commands.plan`).

export const CUSTOM = "custom";
const PICKS = new Set(["faces", "edges"]);

/** The toolbar's command id for a new call of a feature: `custom:<module.function>`. */
export const customCommandId = fn => `${CUSTOM}:${fn}`;

/** Whether an open command is a custom feature's (a new call from the toolbar, or Edit Feature on one). */
export const isCustomCommand = command => command === CUSTOM || String(command || "").startsWith(`${CUSTOM}:`);

/**
 * The feature the dialog is for: Edit Feature's (the row's parameters with their values now), or a new
 * call's (the declaration from the project's files, each parameter at its default). Null when it is no
 * longer there.
 */
export function customDefinition(state, command, editing) {
  if (editing?.command === CUSTOM) {
    const row = (state?.rows || []).find(each => each.key === editing.row);
    if (!row?.custom) return null;
    return { name: row.custom.name, function: row.custom.function, params: row.custom.params || [], collapsed: row.custom.collapsed || [],
      row: row.key, editing: true };
  }
  const fn = String(command || "").slice(CUSTOM.length + 1);
  const declared = (state?.customFeatures || []).find(each => each.function === fn);
  if (!declared) return null;
  return { name: declared.name, function: declared.function, doc: declared.doc || "", collapsed: declared.collapsed || [],
    params: declared.params.map(param => ({ ...param, value: PICKS.has(param.kind) ? 0 : param.default, code: null })), row: null, editing: false };
}

/** Each parameter's value as the dialog opens: a number as text, a switch, a choice; picks are kept apart. */
export function customValues(definition) {
  const values = {};
  for (const param of definition?.params || []) {
    if (PICKS.has(param.kind)) continue;
    if (param.kind === "bool") values[param.name] = param.value === true;
    else if (param.kind === "enum") values[param.name] = String(param.value ?? param.choices?.[0]?.value ?? "");
    else values[param.name] = param.value === undefined || param.value === null ? "" : String(param.value);
  }
  return values;
}

/**
 * The dialog's sections: the ungrouped parameters first, then each group in the order its first
 * parameter is declared, a group the feature names in `collapsed` folded (FeatureScript's "Collapsed By
 * Default").
 */
export function customGroups(definition) {
  const sections = [];
  const byTitle = new Map();
  for (const param of definition?.params || []) {
    const title = param.group || null;
    if (!byTitle.has(title)) {
      const section = { title, params: [], folded: Boolean(title) && (definition.collapsed || []).includes(title) };
      byTitle.set(title, section);
      if (title === null) sections.unshift(section); else sections.push(section);
    }
    byTitle.get(title).params.push(param);
  }
  return sections;
}

/** What a pick field says: how many it holds, what it keeps, or what to do. */
export function pickWords(param, picked, editing) {
  const kind = param.kind;
  const one = kind === "faces" ? "face" : "edge";
  if (picked?.length) return picked.length === 1 ? `1 ${one}` : `${picked.length} ${kind}`;
  if (editing && param.value) return `${param.value === 1 ? `1 ${one}` : `${param.value} ${kind}`}, as written`;
  return param.max === 1 ? `Select a ${one}` : `Select ${kind}`;
}

const same = (a, b) => String(a ?? "").trim() === String(b ?? "").trim();

/**
 * OK's request (the engine's custom command): every value of a new call (the engine leaves a default
 * out), only what was changed of Edit Feature's, so what was written by name stays written that way; the
 * faces and edges picked, each parameter's own.
 */
export function customRequest(definition, values, picks = {}) {
  const opened = customValues(definition);
  const inputs = {};
  for (const param of definition.params) {
    if (PICKS.has(param.kind) || !(param.name in values)) continue;
    const value = values[param.name];
    if (definition.editing && (param.kind === "bool" ? value === opened[param.name] : same(value, opened[param.name]))) continue;
    if (param.kind !== "bool" && param.kind !== "enum" && !String(value ?? "").trim()) continue;
    inputs[param.name] = param.kind === "bool" ? Boolean(value) : param.kind === "enum" ? String(value) : String(value).trim();
  }
  const picked = Object.fromEntries(Object.entries(picks).filter(([, items]) => items?.length));
  return { command: CUSTOM, function: definition.function, inputs, picks: picked, ...(definition.editing ? { replace: { row: definition.row } } : {}) };
}

/** Whether OK has anything to write: a new call always; Edit Feature only once something changed. */
export const customChanged = request => !request.replace || Object.keys(request.inputs).length > 0 || Object.keys(request.picks).length > 0;

/** The viewer's selection as a pick field takes it: only its own kind (`items`: `selectionItems`). */
export const picksOfKind = (items, kind, isFace, isEdge) => items.filter(kind === "faces" ? isFace : isEdge);
