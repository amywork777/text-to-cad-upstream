/**
 * Which feature made a face, as the engine says (`cadgen/edit/face_features.py`), for whatever names a face: its chip, in the Part
 * Navigator's words ("Hole (6) · face 12" rather than today's "bracket · face 12"), and the selection bar's Edit on it, which opens
 * that feature (`selectionBar.js`'s `facePick`). The engine's map (`faceFeatures`) is a face's number on the part → the key of the
 * feature it credits with the face, the id the design tree's rows go by: the first feature with a face there on that surface
 * (`cadgen/edit/face_features.py`, whose blind spot it names). A face where no feature's face overlaps is not known, and keeps today's
 * words. The map is used for the faces it was read for alone (`shownFaces`).
 */
import { navigatorLabel } from "./nx.js";
import { elementOf } from "./selectors.js";

/** A reference to one face by its selector (`"plate/face 12"`, `selectors.js`), as the functions here take one. */
export const faceReference = selector => ({ target: { kind: "cad-selector", selectors: [String(selector ?? "")] } });

/**
 * The number on the part of the face a reference is to: `{ target: { kind: "face", face: 12 } }`, or one face's selector
 * (`{ target: { kind: "cad-selector", selectors: ["plate/face 12"] } }`, `selectors.js`). Null for an edge, several picks, a
 * face named by its derivation rather than its number, or anything else.
 */
export function faceNumber(reference) {
  const target = reference?.target;
  if (target?.kind === "face") return Number.isSafeInteger(target.face) && target.face > 0 ? target.face : null;
  if (target?.kind !== "cad-selector" || target.selectors?.length !== 1) return null;
  const element = elementOf(target.selectors[0]);
  return element?.kind === "face" && Number.isSafeInteger(element.ordinal) && element.ordinal > 0 ? element.ordinal : null;
}

/** The key of the feature that made the face a reference is to, as the map in `state` (`faceFeatures`) says; null where it does not say. */
export function faceFeature(reference, state) {
  const number = faceNumber(reference);
  const key = number === null ? undefined : state?.faceFeatures?.[String(number)];
  return typeof key === "string" && key ? key : null;
}

/**
 * A face's chip name in its pieces, as a chip's compact name has them (`{ name, kind, number }`): the feature that made it as the Part
 * Navigator numbers it (`features`, the part's rows; "Hole2"), "face", and its number. Null where the feature is not known, or is
 * no row the design tree lists.
 */
export function faceChipName(reference, state, features) {
  const id = faceFeature(reference, state);
  const label = id ? navigatorLabel(features, id) : "";
  return label ? { name: label, kind: "face", number: String(faceNumber(reference)) } : null;
}

/**
 * The part's map for the faces on screen, `{ faceFeatures }` as the functions above take it, or null where it is not known to be
 * theirs. In the workspace only (`editing`: Simple view keeps today's words), on a part (`assembly` has none), and not while the
 * rollback bar's body is drawn in place of the part's (`bar.document`, the engine document the bar's body is): picks on it carry no chips, and a reference pasted then is
 * numbered on the part's model, not the body on screen, whose faces the engine does not map. And only while the model on screen is
 * the one the engine read: none while a new one loads (`updating`), while its STEP is built again or failed to be, by the build
 * feed (`rebuilding`) or the edit service (`state.building`), or where the faces on screen (`faces`, how many) are not as many as
 * the part read has (`faceCount`): a model built from another script, which its numbers would misname.
 */
export function shownFaces({ editing, assembly, state, bar, updating, rebuilding, faces }) {
  if (!editing || assembly || bar?.document || updating || rebuilding) return null;
  const building = state?.building;
  if (building?.scripts?.length && (building.error || building.done < building.scripts.length)) return null;
  const map = state?.faceFeatures;
  if (!map || typeof map !== "object" || !Number.isSafeInteger(state.faceCount) || state.faceCount < 1 || state.faceCount !== faces) return null;
  return { faceFeatures: map };
}
