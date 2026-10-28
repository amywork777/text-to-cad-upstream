/**
 * What you see's controls when the study's view names none, and the pieces the view's own controls
 * share with them. Each is a generic parameter (`@text-to-cad/core/common/parameters.js`) with
 * `drives`, what it moves.
 */
import { clamp } from "@text-to-cad/core/common/numbers.js";
import { fieldWord } from "./fields.js";
import { english } from "../../../i18n/core.js";

/** Sensible slider bounds for the deformation scale, with no view to say: 0 to four times the file's own. */
export function deformationRange(baseScale) {
  const max = Math.max(1, (Number(baseScale) || 1) * 4);
  const step = max >= 100 ? 1 : max >= 10 ? 0.5 : 0.1;
  return { min: 0, max, step };
}

/** A select's options over these fields, in this order, each that the result carries, in plain words. */
export function fieldOptions(result, attributes) {
  return attributes.map((attribute) => result.fields.find((entry) => entry.attribute === attribute)).filter(Boolean)
    .map((entry) => ({ value: entry.attribute, label: fieldWord(entry) }));
}

/**
 * The viewer's own two: a field select with no visible label over every field, opening on the first
 * (stress), and a deformation slider from 0 to four times the file's own scale, in the one-column
 * look they always had.
 */
export function fieldAndDeformation(result, t = english) {
  const every = result.fields.map((entry) => entry.attribute);
  const range = deformationRange(result.deformationScale);
  return [
    { id: "field", drives: "field", type: "enum", label: t("fea.field"), ariaLabel: t("fea.resultField"), hideLabel: true,
      options: fieldOptions(result, every), defaultValue: every[0] },
    { id: "deformation", drives: "deformation", type: "number", label: t("fea.deformation"), ariaLabel: t("fea.deformationScale"),
      labelTitle: t("fea.deformationTitle"), min: range.min, max: range.max, step: range.step,
      defaultValue: clamp(result.deformationScale, range.min, range.max), unit: "×" },
  ];
}
