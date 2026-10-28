/**
 * How CAD mode names a face or an edge of the model, one way throughout: the engine's own ref
 * (`cadgen.engine.refs`, `parseEngineRef`), by its kind and number under its part (`face 12`,
 * `plate/face 12`, `hand/finger.2/edge 3`), as the xbf renderer copies a pick and `cadgen inspect`
 * reads one. The renderer's selection holds its own ids for the same elements (`i0/face/12`,
 * `parseXbfElementId`); `xbfEditReference` turns one into what CAD mode's panels read of a pick.
 *
 * A ref in 0.7's spelling (`o1.f12`, `o1.2.e3`, `f12`), from a note or a study written then, still
 * reads, here and nowhere else (`elementOf`).
 */
import { engineSelectorText, parseEngineRef } from "@text-to-cad/core/lib/cadRefs.js";

// 0.7's spelling: the occurrence (`o1`, the second part of it `o1.2`), then `f` or `e` and the number.
const LEGACY_RE = /^(?:o\d+((?:\.\d+)*)\.)?([fe])([1-9][0-9]*)$/;
const LEGACY_KINDS = Object.freeze({ f: "face", e: "edge" });
// An element name's kind (`f:plate.extrude1.3`): the engine numbers none of these.
const NAMED_KINDS = Object.freeze({ f: "face", e: "edge", v: "vertex" });

/**
 * The face, edge or vertex a selector names: `{ kind, ordinal, owner, occurrence }`. `ordinal` is its
 * number on its part (null for an element named by its derivation, `f:…`); `owner` the part's path as
 * the engine writes it (`plate`, `hand/finger.2`; null for the document's root); `occurrence` the
 * part's place among an assembly's, counted from 1, which only a 0.7 ref says (`o1.2.f3`: 2). Null for
 * a selector that names no element (a part, nothing).
 */
export function elementOf(selector) {
  const text = String(selector ?? "").trim();
  if (!text) return null;
  const legacy = LEGACY_RE.exec(text);
  if (legacy) {
    const place = legacy[1] ? Number(legacy[1].split(".").pop()) : null;
    return { kind: LEGACY_KINDS[legacy[2]], ordinal: Number(legacy[3]), owner: null, occurrence: place };
  }
  const parsed = parseEngineRef(`#${text}`);
  const [one] = parsed?.selectors || [];
  if (!one || parsed.selectors.length !== 1 || one.element === null) return null;
  const owner = one.owner ? engineSelectorText({ owner: one.owner, element: null }) : null;
  if (typeof one.element === "string") return { kind: NAMED_KINDS[one.element[0]] || null, ordinal: null, owner, occurrence: null };
  return { kind: one.element.kind, ordinal: one.element.ordinal, owner, occurrence: null };
}

/** Whether a command's item (`selectionItems`) is a face. */
export const isFaceItem = item => elementOf(item?.selector)?.kind === "face";
/** Whether a command's item (`selectionItems`) is an edge. */
export const isEdgeItem = item => elementOf(item?.selector)?.kind === "edge";

const point = value => (Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(Number.isFinite) ? value.slice(0, 3).map(Number) : null);

/**
 * A face or edge the renderer has picked (`id`, `i0/face/12`), as CAD mode's panels and commands read a
 * pick (`editMode.js`'s `selectionItems`, `EditCommand.jsx`): `{ id, selectorType, displaySelector,
 * normalizedSelector, pickData }`, its selector the engine's ref by number (`plate/face 12`, never its
 * element name, so the edit service finds it by its number), and what is known of it: its kind of
 * surface or curve, a flat face's normal, from the scene (`elementGeometry`), and once the engine has
 * measured it (`facts`, `fetchXbfElementFacts`) its centre, area or length and box. Null for an id the
 * scene does not hold, or a vertex.
 *
 * @param {{ scene: object | null, tree: { elementRefOf: Function }, id: string, facts?: object | null }} options
 */
export function xbfEditReference({ scene, tree, id, facts = null }) {
  const element = scene?.describeElement?.(id);
  if (!element || (element.kind !== "face" && element.kind !== "edge")) return null;
  const selector = tree.elementRefOf(`i${element.instance}`, element.kind, element.ordinal) || `${element.kind} ${element.ordinal}`;
  const box = facts?.box && point(facts.box.min) && point(facts.box.max) ? { min: point(facts.box.min), max: point(facts.box.max) } : null;
  let pickData;
  if (element.kind === "face") {
    const surface = scene.elementGeometry?.(id)?.surface || null;
    const center = point(facts?.centroid);
    pickData = {
      surfaceType: String(facts?.surface || surface?.type || ""),
      ...(center ? { center } : {}),
      ...(surface?.type === "plane" && point(surface.normal) ? { normal: point(surface.normal) } : {}),
      ...(Number.isFinite(Number(facts?.area)) ? { area: Number(facts.area) } : {}),
      ...(box ? { bbox: box } : {}),
    };
  } else {
    // A straight edge's middle and box are its two ends'; a curved one's centre is the engine's to find.
    const ends = (facts?.endpoints || []).map(point).filter(Boolean);
    const straight = facts?.curve === "line" && ends.length === 2;
    pickData = {
      curveType: String(facts?.curve || ""),
      ...(straight ? { center: ends[0].map((value, axis) => (value + ends[1][axis]) / 2) } : {}),
      ...(Number.isFinite(Number(facts?.length)) ? { length: Number(facts.length) } : {}),
      ...(straight ? { bbox: { min: ends[0].map((value, axis) => Math.min(value, ends[1][axis])), max: ends[0].map((value, axis) => Math.max(value, ends[1][axis])) } } : {}),
    };
  }
  return { id, selectorType: element.kind, displaySelector: selector, normalizedSelector: selector, pickData };
}
