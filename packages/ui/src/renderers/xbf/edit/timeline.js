/**
 * The timeline's rules, pure: what it lists, where the rollback bar's marker stands and where a dragged one
 * would go (`EditTimeline.jsx` draws it). It lists what the design tree lists, in its order and
 * under its titles, so the two are one history seen twice and the marker is the same rollback as
 * the design tree's bar and its Make Current Feature.
 */

import { authorOf } from "./authors.js";
import { barIndex, rolledBack } from "./editMode.js";
import { treeTitles } from "./nx.js";

/**
 * The timeline of a part (`featureTree`) with its rollback bar (`edit.bar`): one item for each feature
 * the design tree lists as a row of the part, in its order, a sketch of its own (one nothing uses
 * yet) among them. An item is `{ id, kind, title, rolledBack, author, feature, sketch }`: its row's id,
 * its kind as the engine names it (for its icon), its title as the design tree numbers it ("Extrude
 * (2)"), whether the bar leaves it out of the part, who made it, the tree's feature itself and its
 * `sketch`.
 *
 * `sketch`: the sketch the feature was made from, which the engine nests under the feature and the Part
 * Navigator lists under its row, drawn as an icon of its own just before the feature. It has the shape of
 * an item (its id is the one the design tree selects the sketch by, `sketchTreeId`; its title the one
 * it numbers it under, "Sketch (1)"; its `feature` the owner, which Edit Sketch reads it from) and is as
 * its feature is: rolled back with it, and made by whoever made it, a sketch having no author of its
 * own. Null for a feature made from no sketch, and for a sketch that is an item of its own. The two
 * move as one: the bar leaves a feature's sketch out with it and cannot stand between them, so the
 * marker has a place for each item (`marker`, `slotAtX`, `edit.rollTo(items[index].id)`) and none for
 * its sketch.
 *
 * `authors` maps ids to "agent" or "you"; whoever it does not name, or names otherwise, has no author
 * (null): nothing is marked that is not known. `marker`: the index of the first item the bar leaves out,
 * past the last when none is. An assembly lists nothing, as its design tree has no rollback bar: its
 * parts are opened to be modeled.
 *
 * @param {ReturnType<typeof import("./editMode.js").featureTree>} tree
 * @param {{ item?: string } | null | undefined} bar
 * @param {Record<string, string> | null} [authors]
 */
export function timelineItems(tree, bar, authors = {}) {
  const features = tree?.assembly ? [] : tree?.features || [];
  const titles = treeTitles(tree);
  const rolled = rolledBack(tree, bar);
  const items = features.map(feature => {
    const item = {
      id: feature.id,
      kind: feature.kind,
      title: titles.get(feature.id) || feature.title,
      rolledBack: rolled.has(feature.id),
      author: authorOf(authors, feature.id),
      feature,
    };
    const made = feature.kind === "Sketch" ? null : feature.sketch;
    return { ...item, sketch: made ? { ...item, id: made.id, kind: "Sketch", title: titles.get(made.id) || made.title } : null };
  });
  return { items, marker: barIndex(tree, bar) };
}

/**
 * The marker's index for a pointer at `x`: how many of the items' centres (`centers`, left to right,
 * in the pointer's own coordinates, one for each item with the sketch drawn before it) it has passed, so
 * the marker stands between the items either side of it. A pointer on a centre has passed it, as the Part
 * Navigator's bar goes below the row the pointer is past the middle of.
 */
export function slotAtX(x, centers) {
  const ahead = centers.findIndex(center => x < center);
  return ahead < 0 ? centers.length : ahead;
}
