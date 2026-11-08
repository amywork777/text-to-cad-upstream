// Callouts that would cover one another on screen, set apart: each label the code never placed
// (`movable`) that overlaps a label before it steps down below that one, a few pixels clear, until it
// overlaps none; a label the code placed stays where it was placed, and the others keep clear of it.
// In screen pixels, every frame the camera moves: what it reads as, never where it is in the model.

const GAP_PX = 3;
const overlaps = (a, b) => Math.abs(a.x - b.x) * 2 < a.w + b.w && Math.abs(a.y - b.y) * 2 < a.h + b.h;

/**
 * @param {Array<{ x: number, y: number, w: number, h: number, movable: boolean }>} boxes  Centred boxes, in drawing order.
 * @param {{ bottom: number } | null} [area]  The room there is: a step that would go below it goes above instead.
 * @returns {Array<{ x: number, y: number }>} Where each is drawn.
 */
export function separateLabels(boxes, area = null) {
  const placed = [];
  // The fixed ones first: the movable keep clear of every one of them, whatever the order.
  const fixed = boxes.filter(box => !box.movable);
  return boxes.map((box) => {
    if (!box.movable) { placed.push(box); return { x: box.x, y: box.y }; }
    const at = { ...box };
    for (let tries = 0; tries <= boxes.length; tries += 1) {
      const hit = [...fixed, ...placed].find(other => other !== box && overlaps(at, other));
      if (!hit) break;
      const below = hit.y + (hit.h + at.h) / 2 + GAP_PX;
      at.y = area && below + at.h / 2 > area.bottom ? hit.y - (hit.h + at.h) / 2 - GAP_PX : below;
    }
    placed.push(at);
    return { x: at.x, y: at.y };
  });
}

const inside = (value, low, high) => (low > high ? (low + high) / 2 : Math.min(Math.max(value, low), high));

/**
 * Where a label stands in the room the view has: inside `area`, and off each of `covers`, what is drawn
 * over the view (the toolbar's strip, the file's panel, the cube), by the shortest way that stays inside.
 *
 * @param {{ x: number, y: number, w: number, h: number }} box  Centred.
 * @param {{ left: number, top: number, right: number, bottom: number }} area
 * @param {Array<{ left: number, top: number, right: number, bottom: number }>} [covers]
 * @returns {{ x: number, y: number }}
 */
export function labelInView(box, area, covers = []) {
  const halfW = box.w / 2, halfH = box.h / 2;
  const fit = at => ({ x: inside(at.x, area.left + halfW, area.right - halfW), y: inside(at.y, area.top + halfH, area.bottom - halfH) });
  let at = fit(box);
  for (const cover of covers) {
    const hit = at.x + halfW > cover.left && at.x - halfW < cover.right && at.y + halfH > cover.top && at.y - halfH < cover.bottom;
    if (!hit) continue;
    const from = at;
    const ways = [{ ...from, x: cover.left - halfW - GAP_PX }, { ...from, x: cover.right + halfW + GAP_PX },
      { ...from, y: cover.top - halfH - GAP_PX }, { ...from, y: cover.bottom + halfH + GAP_PX }];
    const roomy = ways.filter(way => way.x === fit(way).x && way.y === fit(way).y);
    const nearest = roomy.sort((a, b) => Math.hypot(a.x - from.x, a.y - from.y) - Math.hypot(b.x - from.x, b.y - from.y))[0];
    if (nearest) at = nearest;
  }
  return at;
}
