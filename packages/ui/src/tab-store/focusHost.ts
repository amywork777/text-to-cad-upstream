/**
 * The place in a part's script the host asks the part on screen to show (Studio's References, which
 * open a part at the line an answer cites, `studio/focus`): the script's path as the host names it, a
 * line of it, and the host's number for the ask (`nonce`), new with each. The app that hosts the
 * viewer takes it from its host context; the STEP view selects the feature whose statement holds the
 * line once the part is read, and says the ask is taken however it went, and whether a feature held
 * the line (`take`), so the host lets it go and, where none did, opens the script there instead
 * (`xbf/edit/useHostFocus.js`). One per page, as a page is one view.
 */
export interface Focus {
  readonly path: string;
  readonly line: number;
  readonly nonce: number;
}

/** An ask the part on screen has taken (`nonce`), and whether a feature of it held the line (`found`). */
export interface FocusTaken {
  readonly nonce: number;
  readonly found: boolean;
}

let focus: Focus | null = null;
const listeners = new Set<() => void>();
const takers = new Set<(taken: FocusTaken) => void>();

/** An ask as the host's context says it: a path, a line from 1 and a number, or none. */
function read(value: unknown): Focus | null {
  if (typeof value !== 'object' || value === null) return null;
  const { path, line, nonce } = value as Record<string, unknown>;
  const asked = typeof path === 'string' && path !== '' && Number.isSafeInteger(line) && (line as number) >= 1
    && typeof nonce === 'number' && Number.isFinite(nonce);
  return asked ? Object.freeze({ path, line: line as number, nonce }) : null;
}

const same = (a: Focus | null, b: Focus | null) =>
  a === b || (a !== null && b !== null && a.path === b.path && a.line === b.line && a.nonce === b.nonce);

export const focusHost = {
  /** The ask the host makes now, or null. */
  get: (): Focus | null => focus,
  /** The host's context says what it asks: anything but a well-formed ask is none. */
  set(next: unknown): void {
    const value = read(next);
    if (same(focus, value)) return;
    focus = value;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** The part on screen has taken the ask numbered `nonce`: its feature selected (`found`), or nothing there to select. */
  take(nonce: number, found: boolean): void {
    const taken = Object.freeze({ nonce, found });
    for (const taker of takers) taker(taken);
  },
  subscribeTaken(taker: (taken: FocusTaken) => void): () => void {
    takers.add(taker);
    return () => {
      takers.delete(taker);
    };
  },
};
