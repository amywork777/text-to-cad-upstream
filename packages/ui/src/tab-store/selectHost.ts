/**
 * Studio (studio-base): the picks the host asks the part on screen to select again (a chat message's
 * "N picks" chip, `studio/select` in the host context): the references the message carried, as Quick Edit
 * wrote them (`<file or document id>#<selector>`), and the host's number for the ask (`nonce`), new with
 * each. The part on screen selects those it holds and says the ask is taken, with how many it found and how
 * many it no longer has (`take`), so the host can say "1 pick no longer in the model"
 * (`renderers/xbf/useHostSelect.js`). One per page, as a page is one view.
 */
export interface SelectAsk {
  readonly references: readonly string[];
  readonly nonce: number;
}

/** An ask the part on screen has taken (`nonce`): the picks it selected (`found`) and those it no longer has (`missing`). */
export interface SelectTaken {
  readonly nonce: number;
  readonly found: number;
  readonly missing: number;
}

let ask: SelectAsk | null = null;
const listeners = new Set<() => void>();
const takers = new Set<(taken: SelectTaken) => void>();

/** An ask as the host's context says it: references as strings and a number, or none. */
function read(value: unknown): SelectAsk | null {
  if (typeof value !== 'object' || value === null) return null;
  const { references, nonce } = value as Record<string, unknown>;
  if (!Array.isArray(references) || typeof nonce !== 'number' || !Number.isFinite(nonce)) return null;
  const strings = references.filter((item): item is string => typeof item === 'string' && item.trim() !== '');
  return strings.length ? Object.freeze({ references: Object.freeze([...strings]), nonce }) : null;
}

export const selectHost = {
  /** The ask the host makes now, or null. */
  get: (): SelectAsk | null => ask,
  /** The host's context says what it asks: anything but a well-formed ask is none. */
  set(next: unknown): void {
    const value = read(next);
    if (ask === value || (ask && value && ask.nonce === value.nonce)) return;
    ask = value;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** The part on screen has taken the ask numbered `nonce`. */
  take(nonce: number, found: number, missing: number): void {
    const taken = Object.freeze({ nonce, found, missing });
    for (const taker of takers) taker(taken);
  },
  subscribeTaken(taker: (taken: SelectTaken) => void): () => void {
    takers.add(taker);
    return () => {
      takers.delete(taker);
    };
  },
};
