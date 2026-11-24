/**
 * A material's name as an engineer reads it, from the id a model or a study carries (Studio): bd_materials'
 * catalogue name ("Alu_G6061_T6" is "Aluminum 6061-T6", "MildSteel_GA36_HOT_ROLLED" "Mild steel A36, hot
 * rolled") or a name written as an id ("steel-g90-galvanised" is "Steel G90 galvanised"). Any other name
 * ("6061-T6", "Mild steel, zinc plated clear") is kept as it is; "" stays "".
 */

/** A catalogue family as its name is said, where splitting its capitals is not enough. */
const FAMILIES = {
  Alu: "Aluminum", Stainless: "Stainless steel", Asa: "ASA", Esd: "ESD", Peek: "PEEK", FR4: "FR-4",
  HighTemp: "High-temperature resin", SodaLime: "Soda-lime glass"
};

/** Words of a catalogue name that say nothing: every family has a generic grade. */
const SILENT = new Set(["GENERIC"]);

/** The catalogue's codes that have no digit: a board's and a plastic's abbreviations. */
const LETTER_CODES = new Set(["MDF", "OSB", "HDPE", "CF"]);

const isCode = (token) => /\d/.test(token) || LETTER_CODES.has(token);

/** A grade as it is written: "G6061" is 6061, "GA36" A36, "GR5" grade 5; any other code as given. */
function grade(token) {
  if (token === "ALSI10MG") return "AlSi10Mg";
  if (/^GR\d+$/.test(token)) return `grade ${token.slice(2)}`;
  return /^G(\d|A\d)/.test(token) ? token.slice(1) : token;
}

/** A temper or condition code that belongs to the grade before it: 6061-T6, 5052-H32. */
const isTemper = (token) => /^[THO]\d+[A-Z]?$/.test(token);

function catalogueWords(name) {
  const [family, ...rest] = name.split(/[._]/).filter(Boolean);
  // An abbreviation (PLA, PETG, FR4) is kept as it is; a family's words are split at their capitals.
  const said = FAMILIES[family] ?? (family === family.toUpperCase() ? family
    : family.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^(\w)(.*)$/, (_, first, tail) => first + tail.toLowerCase()));
  const codes = [];
  const words = [];
  let shore = false;
  for (const token of rest) {
    if (SILENT.has(token)) continue;
    // A hardness is said with its scale: "SHORE_95A" is Shore 95A.
    if (token === "SHORE") {
      shore = true;
    } else if (shore && isCode(token)) {
      codes.push(`Shore ${token}`);
      shore = false;
    } else if (isCode(token)) {
      if (isTemper(token) && codes.length) codes[codes.length - 1] += `-${token}`;
      else codes.push(grade(token));
    } else {
      words.push(token.toLowerCase());
    }
  }
  return [said, ...codes].join(" ") + (words.length ? `, ${words.join(" ")}` : "");
}

function idWords(name) {
  const tokens = name.split(/[-_.]+/).filter(Boolean)
    .map((token) => (/\d/.test(token) ? token.toUpperCase() : token.toLowerCase()));
  const said = tokens.join(" ");
  return said.charAt(0).toUpperCase() + said.slice(1);
}

export function materialWords(name) {
  const text = typeof name === "string" ? name.trim() : "";
  // A catalogue name is its family's, then its grade's ("Alu_G6061_T6"); an id is lower case, its words
  // joined ("steel-g90-galvanised"). Anything else ("6061-T6", "Custom") is already said as it is.
  if (/^[A-Za-z][A-Za-z0-9]*[._][A-Za-z0-9._]+$/.test(text) && /^[A-Z]/.test(text)) return catalogueWords(text);
  if (/^[a-z][a-z0-9]*([-_][a-z0-9]+)+$/.test(text)) return idWords(text);
  return text;
}
