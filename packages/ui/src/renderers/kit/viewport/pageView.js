/**
 * A flat picture read as a page is read (`useFlatCanvasView`'s `scroll`): it opens at its width
 * with its top in view where it is upright and much taller than the pane (sheets one under
 * another), else whole, as a landscape drawing sheet does; the wheel and a two-finger swipe scroll it, its edges stopping at the pane's, and a pinch
 * or ⌘/Ctrl with the wheel zooms. Plain arithmetic on the view's transform
 * (`@text-to-cad/core/lib/drawing2d/transform.js`: model y up, screen y down).
 */
import { DRAWING_FIT_MARGIN, fitTransform } from "@text-to-cad/core/lib/drawing2d/transform.js";

/** How much sharper than its whole fit its width fit must be before a page opens at its width. */
const WIDTH_FIT_GAIN = 1.5;

/**
 * The fit of a page: the whole of it, unless it is upright and so much taller than the pane that
 * read whole it would be small, then its width, its top in view under `top` (the tool strip).
 * @param {readonly [number, number, number, number]} bounds
 * @param {number} width
 * @param {number} height
 * @param {{ top?: number, margin?: number }} [options]
 */
export function pageFit(bounds, width, height, { top = 0, margin = DRAWING_FIT_MARGIN } = {}) {
  const whole = fitTransform(bounds, width, height, { margin, top });
  const [minX, minY, maxX, maxY] = bounds;
  const across = Math.max(Number.EPSILON, maxX - minX);
  const scale = Math.max(Number.EPSILON, (width - 2 * margin) / across);
  if (maxY - minY <= across || scale <= whole.scale * WIDTH_FIT_GAIN) return whole;
  return { scale, offsetX: (width - across * scale) / 2 - minX * scale, offsetY: top + margin + maxY * scale };
}

/**
 * A page scrolled by (dx, dy) screen pixels. Along an axis it moves on where it is larger than the
 * pane, its edges stop at the pane's (less a margin, and the strip at the top); along one where it
 * fits, or one it does not move on, it stays where it is, so scrolling down never jumps it across.
 * @param {{ scale: number, offsetX: number, offsetY: number }} transform
 * @param {number} dx
 * @param {number} dy
 * @param {readonly [number, number, number, number]} bounds
 * @param {number} width
 * @param {number} height
 * @param {{ top?: number, margin?: number }} [options]
 */
export function scrollPage(transform, dx, dy, bounds, width, height, { top = 0, margin = DRAWING_FIT_MARGIN } = {}) {
  const { scale } = transform;
  const [minX, minY, maxX, maxY] = bounds;
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  let { offsetX, offsetY } = transform;
  if (dx && (maxX - minX) * scale > width - 2 * margin) {
    offsetX = clamp(offsetX + dx, width - margin - maxX * scale, margin - minX * scale);
  }
  if (dy && (maxY - minY) * scale > height - top - 2 * margin) {
    offsetY = clamp(offsetY + dy, height - margin + minY * scale, top + margin + maxY * scale);
  }
  return { scale, offsetX, offsetY };
}
