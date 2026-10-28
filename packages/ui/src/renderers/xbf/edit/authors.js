/**
 * Who made a feature, as the engine records it (`cadgen/edit/authors.py`; `edit.state.authors`, by the
 * feature's id): the agent, or you. The timeline draws it as a 6px dot under each item and the Part
 * Navigator at each row's right, the agent's purple (`--cad-agent`) and yours grey, each said in words
 * on hover. A feature from before Studio kept track, or one nobody is known to have made, has neither.
 */

/** What a feature's dot says of who made it. */
export const AUTHOR_WORDS = Object.freeze({ agent: "Made by the agent", you: "Made by you" });
/** The dot's color: the agent's purple, yours the muted grey. */
export const AUTHOR_DOT_CLASS = Object.freeze({ agent: "bg-cad-agent", you: "bg-muted-foreground" });

/**
 * Who made the feature `id`, by `authors`: "agent", "you", or null for one it does not name or names
 * otherwise. Nothing is marked that is not known.
 *
 * @param {Record<string, unknown> | null | undefined} authors
 * @param {string} id
 * @returns {"agent" | "you" | null}
 */
export function authorOf(authors, id) {
  const author = authors?.[id];
  return author === "agent" || author === "you" ? author : null;
}
