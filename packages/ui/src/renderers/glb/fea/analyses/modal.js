/**
 * Vibration: the part's natural frequencies and the shape it rings in at each (`Mode 2 · 118 Hz`), each
 * shape scaled to a largest motion of 1 mm, mode 1's also the displacement baked into the file. A part
 * nothing holds is free in space, its rigid-body motions left out.
 */
import { heldRows, madeOfRows, wholeRefs } from "../setup.js";
import { planned, routineOf } from "./stub.js";
import { english } from "../../../../i18n/core.js";

/** Vibrate: a one-second loop of the chosen mode's shape, out one way, through rest and back the other. */
export const VIBRATE = routineOf("Vibrate", "vibrate");

/** Study's "Held at" for a part nothing holds: one row, free in space, chosen with the whole part. */
export function freeRows(result, t = english) {
  if (result.study.fixtures.length) return [];
  const refs = wholeRefs(result);
  return [{ id: "free", label: t("fea.heldAt"), detail: "", glyph: "fixture", children: [{
    id: "free:0", label: t("fea.freeInSpace"), detail: "", hint: t("fea.rigidModesHint"), wrap: true,
    ...(refs.length ? { refs, summary: t("fea.freeSummary") } : {}),
  }] }];
}

export default planned({
  name: "modal", word: "Vibration", noun: "this shake",
  checks: ["frequency"],
  setupGroups: [heldRows, freeRows, madeOfRows],
  routine: () => VIBRATE,
  markers: ["fixture"], displayTitle: "Fixtures",
});

