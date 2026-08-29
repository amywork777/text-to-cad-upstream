// Embedded cadgen identity from a STEP file's own bytes.
//
// Generated exports stamp `cadgen:generator` / `cadgen:sourcePath` (and
// entryKind/sourceHash) as STEP property entities near the end of the file
// (cadgen/_internal/step_metadata.py writes them; this is the read side's JS
// twin, scoped to the two fields the server needs). The point: a GENERATED
// file separated from its render package — packages are gitignored, .step
// files travel — must still classify as generated, or the viewer offers an
// import that silently produces a colorless, provenance-less, params-less
// package over a model whose real builder is `python <source>`.
//
// Reads only the file TAIL (the writer appends metadata just before ENDSEC),
// so probing a 100 MB vendor STEP costs one bounded read. A vendor file
// without the properties returns null immediately on a cheap substring check.
import fs from "node:fs";

export const IDENTITY_TAIL_BYTES = 1024 * 1024;
const GENERATOR_PROPERTY = "cadgen:generator";
const SOURCE_PATH_PROPERTY = "cadgen:sourcePath";
const STEP_STRING = "'(?:''|[^'])*'";

function stepUnescape(raw) {
  let text = String(raw || "").trim();
  if (text.length >= 2 && text.startsWith("'") && text.endsWith("'")) {
    text = text.slice(1, -1);
  }
  return text.replace(/''/g, "'");
}

function readTailText(stepPath) {
  let handle = null;
  try {
    handle = fs.openSync(stepPath, "r");
    const size = fs.fstatSync(handle).size;
    const length = Math.min(size, IDENTITY_TAIL_BYTES);
    const buffer = Buffer.alloc(length);
    fs.readSync(handle, buffer, 0, length, size - length);
    return buffer.toString("utf8");
  } catch {
    return "";
  } finally {
    if (handle !== null) {
      try { fs.closeSync(handle); } catch { /* already closed */ }
    }
  }
}

/**
 * Parse the property graph the same way step_metadata.py does:
 * DESCRIPTIVE_REPRESENTATION_ITEM (values) <- REPRESENTATION (item refs)
 * <- PROPERTY_DEFINITION_REPRESENTATION <- PROPERTY_DEFINITION (names).
 */
function identityFromStepText(stepText) {
  const items = new Map();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*DESCRIPTIVE_REPRESENTATION_ITEM\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*(${STEP_STRING})\\s*\\)\\s*;`, "gis",
  ))) {
    items.set(`#${match[1]}`, stepUnescape(match[3]));
  }
  const representations = new Map();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*REPRESENTATION\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*\\(([^)]*)\\)\\s*,\\s*#\\d+\\s*\\)\\s*;`, "gis",
  ))) {
    representations.set(`#${match[1]}`, match[3].match(/#\d+/g) || []);
  }
  const definitions = new Map();
  for (const match of stepText.matchAll(new RegExp(
    `#(\\d+)\\s*=\\s*PROPERTY_DEFINITION\\s*\\(\\s*(${STEP_STRING})\\s*,\\s*(${STEP_STRING})\\s*,\\s*#[0-9]+\\s*\\)\\s*;`, "gis",
  ))) {
    const name = stepUnescape(match[3]);
    if (name === GENERATOR_PROPERTY || name === SOURCE_PATH_PROPERTY) {
      definitions.set(`#${match[1]}`, name);
    }
  }
  const identity = {};
  for (const match of stepText.matchAll(
    /#\d+\s*=\s*PROPERTY_DEFINITION_REPRESENTATION\s*\(\s*(#\d+)\s*,\s*(#\d+)\s*\)\s*;/gis,
  )) {
    const name = definitions.get(match[1]);
    if (!name) {
      continue;
    }
    for (const itemRef of representations.get(match[2]) || []) {
      const value = items.get(itemRef);
      if (value !== undefined) {
        identity[name === GENERATOR_PROPERTY ? "generator" : "sourcePath"] = value;
        break;
      }
    }
  }
  return identity;
}

/**
 * `{generator, sourcePath}` when the file declares a cadgen generator with a
 * source path, else null. The sourcePath is DISPLAY TEXT for a hint — it is
 * recorded model-folder-relative by the writer and is never resolved or
 * executed by the server.
 */
export function cadgenStepIdentity(stepPath) {
  const tail = readTailText(stepPath);
  if (!tail.includes(GENERATOR_PROPERTY) || !tail.includes(SOURCE_PATH_PROPERTY)) {
    return null;
  }
  const identity = identityFromStepText(tail);
  if (identity.generator === "cadgen" && identity.sourcePath) {
    return { generator: identity.generator, sourcePath: identity.sourcePath };
  }
  return null;
}
